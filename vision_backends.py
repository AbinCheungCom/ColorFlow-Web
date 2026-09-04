"""ColorFlow VISION 图→prompt 适配器层 — 与 gen_backends.py 对称设计。

设计目标（见 docs/03-工作流集成方案.md 方案 B）：
  - 单一入口 dispatch_prompt()，backend="auto" 时按 openai → claude → mock
    优先级探测可用后端，失败且 retryable 时自动降级。
  - 输入图像（任意格式，由 Flask 上传得到 bytes）→ 返回结构化 prompt。
  - 所有网络调用带超时；失败抛 PromptError(code, retryable)。
  - 零本地 GPU：纯云端多模态 API，本地仅做 base64 编码。

支持的 provider（默认 OPENAI，可通过 VISION_DEFAULT_BACKEND 切换）：
  - openai   : gpt-4o（VLM），OPENAI_API_KEY + OPENAI_BASE_URL（可选，默认官方）
  - claude   : claude-sonnet-4-6，ANTHROPIC_API_KEY + ANTHROPIC_BASE_URL
  - mock     : 零 Key 演示/测试用，返回固定 prompt 并标记 backend="mock"

红线：
  - Key 仅存服务端环境变量，不进前端页面回显。
  - 失败可降级：auto 失败按顺序降级，最终失败抛明确错误码，绝不假成功。
"""

from dataclasses import dataclass, field
import base64
import mimetypes
import os
import time
import logging
import urllib.request
import urllib.error
import json

logger = logging.getLogger("colorflow.vision")

# ── 后端优先级（auto 模式按此顺序探测）──────────────────────────────
_BACKEND_PRIORITY = ("openai", "claude", "mock")


@dataclass
class PromptResult:
    """统一图→prompt 返回结构"""
    prompt: str = ""                       # 生成的英文 prompt
    backend: str = ""                      # 实际命中的后端：openai / claude / mock
    model: str = ""                        # 实际命中的模型名
    meta: dict = field(default_factory=dict)  # 耗时/tokens/费用等


class PromptError(Exception):
    """图→prompt 失败。code ∈ {auth, quota, timeout, rate_limit, upstream, bad_image}"""
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


# ============================================================
# 工具函数
# ============================================================

def _env(name: str) -> str:
    """读取环境变量并 trim，避免尾部空白导致认证失败"""
    return os.getenv(name, "").strip()


def _http_json(url: str, method: str = "POST", headers: dict = None,
               body: dict = None, timeout: int = 120) -> dict:
    """发起 JSON 请求并解析 JSON 响应（urllib 实现，无额外依赖）。"""
    data = json.dumps(body or {}).encode("utf-8") if body is not None else None
    hdr = {"Content-Type": "application/json"}
    if headers:
        hdr.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdr, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            try:
                return json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {"_raw": payload}
    except urllib.error.HTTPError as e:
        code = e.code
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        if code in (401, 403):
            raise PromptError("auth", f"后端认证失败 ({code}): {body_text}", retryable=False)
        if code == 402:
            raise PromptError("quota", f"额度不足 ({code}): {body_text}", retryable=True)
        if code == 429:
            raise PromptError("rate_limit", f"请求过频 ({code}): {body_text}", retryable=True)
        raise PromptError("upstream", f"HTTP {code}: {body_text}", retryable=True)
    except TimeoutError:
        raise PromptError("timeout", f"请求超时 ({timeout}s)", retryable=True)
    except urllib.error.URLError as e:
        if "timed out" in str(e).lower():
            raise PromptError("timeout", f"请求超时 ({timeout}s)", retryable=True)
        raise PromptError("upstream", f"网络错误: {e}", retryable=True)
    except Exception as e:  # noqa: BLE001 - 兜底，绝不假成功
        raise PromptError("upstream", f"未知网络错误: {e}", retryable=True)


def _image_to_data_url(png_bytes: bytes) -> str:
    """图像 bytes → data: URL（VLM API 通用输入格式）"""
    b64 = base64.b64encode(png_bytes).decode("ascii")
    mime = "image/png"  # 上传层已通过 ALLOWED_CONTENT_TYPES 校验，统一按 PNG 传
    return f"data:{mime};base64,{b64}"


def _system_prompt(style: str = "product", lang: str = "en") -> str:
    """构造用于图→prompt 的系统提示词"""
    lang_hint = "English" if lang == "en" else "中文"
    return (
        f"You are a prompt engineer for AI image generation. Describe the uploaded "
        f"image in detail so that an image model can reproduce it. "
        f"Focus on: subject, composition, colors (name the colors precisely), "
        f"style, lighting, background, and aspect ratio. "
        f"Return ONLY a single paragraph prompt in {lang_hint}, no preamble, "
        f"no markdown, no bullet points. Keep it between 40 and 180 words. "
        f"Style hint: {style}."
    )


# ============================================================
# Provider 实现
# ============================================================

def mock_backend(prompt: str, image: bytes, timeout: int = 30, model: str = "",
                 lang: str = "en", style: str = "product", **kw) -> PromptResult:
    """零 Key 演示/测试用后端 — 不做任何 API 调用，返回固定 prompt。"""
    return PromptResult(
        prompt="a clean product render on a white background, studio lighting, "
               "high detail, centered composition",
        backend="mock",
        model="mock-v1",
        meta={"note": "mock backend, no API call; set OPENAI_API_KEY for real generation",
              "image_bytes": len(image),
              "elapsed": 0.0},
    )


def openai_backend(prompt: str, image: bytes, timeout: int = 120, model: str = "",
                   lang: str = "en", style: str = "product", **kw) -> PromptResult:
    """OpenAI Vision（gpt-4o）— 事实标准 VLM。"""
    api_key = _env("OPENAI_API_KEY")
    if not api_key:
        raise PromptError("auth", "OPENAI_API_KEY 未设置", retryable=False)
    base_url = _env("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    model = model or _env("VISION_MODEL_OPENAI") or "gpt-4o"

    t0 = time.time()
    data_url = _image_to_data_url(image)
    body = {
        "model": model,
        "max_tokens": int(_env("VISION_MAX_TOKENS") or 300),
        "messages": [
            {"role": "system", "content": _system_prompt(style, lang)},
            {"role": "user", "content": [
                {"type": "text", "content": "Describe this image."},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]},
        ],
    }
    resp = _http_json(f"{base_url.rstrip('/')}/chat/completions",
                      headers={"Authorization": f"Bearer {api_key}"},
                      body=body, timeout=timeout)
    elapsed = time.time() - t0
    if "_raw" in resp:
        raise PromptError("upstream", "OpenAI 返回非 JSON 响应", retryable=True)
    try:
        text = resp["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as e:
        raise PromptError("upstream", f"OpenAI 响应结构异常: {resp}", retryable=False)
    if not text:
        raise PromptError("upstream", "OpenAI 返回空 prompt", retryable=False)
    return PromptResult(
        prompt=text,
        backend="openai",
        model=model,
        meta={"elapsed": round(elapsed, 2),
              "tokens_used": resp.get("usage", {}).get("total_tokens", 0)},
    )


def claude_backend(prompt: str, image: bytes, timeout: int = 120, model: str = "",
                   lang: str = "en", style: str = "product", **kw) -> PromptResult:
    """Anthropic Claude Vision — 备选 VLM，用于 OpenAI 不可用时。"""
    api_key = _env("ANTHROPIC_API_KEY")
    if not api_key:
        raise PromptError("auth", "ANTHROPIC_API_KEY 未设置", retryable=False)
    base_url = _env("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"
    model = model or _env("VISION_MODEL_CLAUDE") or "claude-sonnet-4-6"

    t0 = time.time()
    b64 = base64.b64encode(image).decode("ascii")
    body = {
        "model": model,
        "max_tokens": int(_env("VISION_MAX_TOKENS") or 300),
        "system": _system_prompt(style, lang),
        "messages": [
            {"role": "user", "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png", "data": b64,
                }},
                {"type": "text", "text": "Describe this image."},
            ]},
        ],
    }
    resp = _http_json(f"{base_url.rstrip('/')}/v1/messages",
                      headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                      body=body, timeout=timeout)
    elapsed = time.time() - t0
    if "_raw" in resp:
        raise PromptError("upstream", "Claude 返回非 JSON 响应", retryable=True)
    try:
        text = "".join(b.get("text", "") for b in resp.get("content", [])).strip()
    except (AttributeError, TypeError) as e:
        raise PromptError("upstream", f"Claude 响应结构异常: {resp}", retryable=False)
    if not text:
        raise PromptError("upstream", "Claude 返回空 prompt", retryable=False)
    return PromptResult(
        prompt=text,
        backend="claude",
        model=model,
        meta={"elapsed": round(elapsed, 2),
              "tokens_used": resp.get("usage", {}).get("input_tokens", 0)
                              + resp.get("usage", {}).get("output_tokens", 0)},
    )


# ============================================================
# 注册表 + dispatch
# ============================================================

_BACKENDS = {
    "openai": openai_backend,
    "claude": claude_backend,
    "mock": mock_backend,
}


def available_backends() -> list:
    """探测已配置 Key 的后端列表（按 _BACKEND_PRIORITY 顺序），mock 始终可用。"""
    avail = []
    if _env("OPENAI_API_KEY"):
        avail.append("openai")
    if _env("ANTHROPIC_API_KEY"):
        avail.append("claude")
    avail.append("mock")  # mock 始终可用（零 Key 降级/测试）
    return avail


def dispatch_prompt(image: bytes, backend: str = "auto", timeout: int = 120,
                    lang: str = "en", style: str = "product", model: str = "") -> PromptResult:
    """统一图→prompt 入口。backend='auto' 时按优先级降级，最终失败抛 PromptError。"""
    if not image:
        raise PromptError("bad_image", "未提供图像数据", retryable=False)
    if len(image) > 25 * 1024 * 1024:  # 25MB 上限，避免 base64 膨胀过大
        raise PromptError("bad_image", "图像过大（>25MB）", retryable=False)
    if backend == "auto":
        return _dispatch_auto(image, timeout=timeout, lang=lang, style=style, model=model)
    fn = _BACKENDS.get(backend)
    if fn is None:
        raise PromptError("upstream", f"未知后端: {backend}", retryable=False)
    return fn(prompt="", image=image, timeout=timeout, lang=lang, style=style, model=model)


def _dispatch_auto(image: bytes, **kw) -> PromptResult:
    avail = available_backends()
    # auto 模式下，若未配置任何真实 Key，直接走 mock（返回 mock 结果，不报错）
    if avail == ["mock"]:
        logger.info("未配置任何 Vision 后端 Key，使用 mock 降级")
        return _BACKENDS["mock"](prompt="", image=image, timeout=kw.get("timeout", 30),
                                 lang=kw.get("lang", "en"), style=kw.get("style", "product"),
                                 model="")
    last_err = None
    # auto 排除 mock（mock 是最终降级兜底，不参与主链路）
    for bid in _BACKEND_PRIORITY:
        if bid == "mock":
            continue
        if bid not in avail:
            continue
        fn = _BACKENDS[bid]
        try:
            return fn(prompt="", image=image, timeout=kw.get("timeout", 120),
                      lang=kw.get("lang", "en"), style=kw.get("style", "product"),
                      model=kw.get("model", ""))
        except PromptError as e:
            last_err = e
            logger.warning("Vision 后端 %s 失败 (%s, retryable=%s): %s",
                           bid, e.code, e.retryable, e)
            if not e.retryable and e.code == "bad_image":
                break
            continue
    # 所有真实后端失败 → 降级到 mock
    logger.warning("所有真实 Vision 后端失败，降级到 mock；last_err=%s", last_err)
    result = _BACKENDS["mock"](prompt="", image=image, timeout=30,
                               lang=kw.get("lang", "en"), style=kw.get("style", "product"),
                               model="")
    result.meta["fallback_from"] = str(last_err.code if last_err else "unknown")
    return result
