"""Prompt 优化器 — 用户 prompt → 增强版 prompt（Phase 5 · S4-C）。

设计目标：
  - 输入：用户原始 prompt（中文/英文）
  - 输出：增强版英文 prompt（适合图像生成模型）
  - 后端：OpenAI Chat Completions（text→text，非 Vision）
  - 降级：无 Key 时返回 mock 增强（纯字符串拼接，不调 API）

红线：
  - Key 仅服务端，不进前端
  - 零本地 GPU（纯云端 API）
  - 失败降级，不假成功
"""

import json
import os
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field


@dataclass
class OptimizeResult:
    prompt: str = ""
    backend: str = ""  # "openai" or "mock"
    model: str = ""
    meta: dict = field(default_factory=dict)


class OptimizeError(Exception):
    """Prompt 优化失败。code ∈ {auth, quota, timeout, upstream}"""
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _http_json(url: str, headers: dict, body: dict, timeout: int = 60) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            try:
                return json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {"_raw": payload}
    except urllib.error.HTTPError as e:
        code = e.code
        try:
            body_text = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            body_text = ""
        if code in (401, 403):
            raise OptimizeError("auth", f"认证失败 ({code}): {body_text}", retryable=False)
        if code == 402:
            raise OptimizeError("quota", f"额度不足 ({code}): {body_text}", retryable=True)
        if code == 429:
            raise OptimizeError("quota", f"限流 ({code}): {body_text}", retryable=True)
        raise OptimizeError("upstream", f"HTTP {code}: {body_text}", retryable=True)
    except TimeoutError:
        raise OptimizeError("timeout", "请求超时", retryable=True)
    except urllib.error.URLError as e:
        raise OptimizeError("upstream", f"网络错误: {e}", retryable=True)
    except Exception as e:
        raise OptimizeError("upstream", f"未知错误: {e}", retryable=True)


# ============================================================
# Provider 实现
# ============================================================

def _get_key(provider: str) -> str:
    """从 llm_keys 读取 key，回退到环境变量。"""
    try:
        from llm_keys import llm_keystore
        key = llm_keystore.get_key(provider)
        if key:
            return key
    except Exception:
        pass
    return _env({"openai": "OPENAI_API_KEY"}.get(provider, ""))


def _get_base(provider: str, default: str) -> str:
    """从 llm_keys 读取 base_url，回退到环境变量。"""
    try:
        from llm_keys import llm_keystore
        cfg = llm_keystore.get_config(provider)
        if cfg and isinstance(cfg, dict):
            return cfg.get("base_url", "")
    except Exception:
        pass
    env_key = {"openai": "OPENAI_BASE_URL"}.get(provider, "")
    return _env(env_key) or default


def _mock_optimize(prompt: str) -> OptimizeResult:
    # 简单启发式增强：添加常用图像生成修饰词
    enhanced = (
        f"{prompt}, "
        "professional product photography, "
        "studio lighting, "
        "high detail, "
        "8k resolution, "
        "clean composition, "
        "no text, "
        "white background"
    )
    return OptimizeResult(
        prompt=enhanced,
        backend="mock",
        model="mock-v1",
        meta={"note": "mock 后端，未调 API；设置 OPENAI_API_KEY 启用真实优化"},
    )


def _openai_optimize(prompt: str, model: str = "", timeout: int = 60) -> OptimizeResult:
    """OpenAI Chat Completions：text→text 优化 prompt。"""
    api_key = _get_key("openai")
    if not api_key:
        raise OptimizeError("auth", "OpenAI API Key 未配置", retryable=False)
    base_url = _get_base("openai", "https://api.openai.com/v1")
    model = model or _env("VISION_MODEL_OPENAI") or "gpt-4o"

    t0 = time.time()
    body = {
        "model": model,
        "max_tokens": 500,
        "temperature": 0.7,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a prompt optimization engine for AI image generation models. "
                    "Given a user's prompt (which may be in Chinese or English), rewrite it "
                    "as a detailed, well-structured English prompt suitable for image "
                    "generation models like SDXL, Flux, or DALL-E. "
                    "Include: subject description, style, lighting, composition, "
                    "background, quality modifiers. "
                    "Return ONLY the optimized prompt, no preamble, no explanation."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    resp = _http_json(f"{base_url.rstrip('/')}/chat/completions", headers, body, timeout)
    elapsed = time.time() - t0

    if "_raw" in resp:
        raise OptimizeError("upstream", "非 JSON 响应", retryable=True)
    try:
        text = resp["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        raise OptimizeError("upstream", f"响应结构异常: {resp}", retryable=False)
    if not text:
        raise OptimizeError("upstream", "空响应", retryable=False)

    return OptimizeResult(
        prompt=text,
        backend="openai",
        model=model,
        meta={"elapsed": round(elapsed, 2),
              "tokens_used": resp.get("usage", {}).get("total_tokens", 0)},
    )


# ============================================================
# 统一入口
# ============================================================

def dispatch_optimize(prompt: str, backend: str = "auto",
                      model: str = "", timeout: int = 60) -> OptimizeResult:
    """统一 prompt 优化入口。

    backend='auto': 有 OPENAI_API_KEY → openai，否则 → mock
    backend='openai': 强制 openai
    backend='mock': 强制 mock
    """
    if not prompt or not prompt.strip():
        raise OptimizeError("upstream", "prompt 不能为空", retryable=False)

    if backend == "mock":
        return _mock_optimize(prompt)

    if backend == "openai":
        return _openai_optimize(prompt, model=model, timeout=timeout)

    # auto
    if _get_key("openai"):
        try:
            return _openai_optimize(prompt, model=model, timeout=timeout)
        except OptimizeError as e:
            if e.code == "auth":
                # Key 无效，降级 mock
                result = _mock_optimize(prompt)
                result.meta["fallback_from"] = str(e)
                return result
            raise
    else:
        return _mock_optimize(prompt)
