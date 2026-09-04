"""共享 LLM 工具函数 — 消除 gen_backends / vision_backends / prompt_optimizer 之间的重复。

提供：
  - env(name)            : 读取环境变量并 trim
  - http_json(...)       : JSON HTTP 请求，错误类通过 error_factory 参数注入
  - get_key(provider)    : 从 llm_keys 或环境变量获取 API Key
  - get_base(provider)   : 从 llm_keys 或环境变量获取 Base URL
  - get_model(...)       : 从 llm_keys 或环境变量获取模型名
"""

import json
import os
import urllib.request
import urllib.error


def env(name: str) -> str:
    """读取环境变量并 trim，避免尾部空白导致认证失败"""
    return os.getenv(name, "").strip()


def http_json(
    url: str,
    method: str = "POST",
    headers: dict = None,
    body: dict = None,
    timeout: int = 120,
    *,
    error_factory,
) -> dict:
    """发起 JSON 请求并解析 JSON 响应。

    网络层异常通过 error_factory(code, message, retryable) 映射为调用方指定的错误类。

    error_factory 签名: (code: str, message: str, retryable: bool) -> Exception
    """
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
            raise error_factory("auth", f"后端认证失败 ({code}): {body_text}", retryable=False)
        if code == 402:
            raise error_factory("quota", f"额度不足 ({code}): {body_text}", retryable=True)
        if code == 429:
            raise error_factory("rate_limit", f"请求过频 ({code}): {body_text}", retryable=True)
        raise error_factory("upstream", f"HTTP {code}: {body_text}", retryable=True)
    except TimeoutError:
        raise error_factory("timeout", f"请求超时 ({timeout}s)", retryable=True)
    except urllib.error.URLError as e:
        if "timed out" in str(e).lower():
            raise error_factory("timeout", f"请求超时 ({timeout}s)", retryable=True)
        raise error_factory("upstream", f"网络错误: {e}", retryable=True)
    except Exception as e:
        raise error_factory("upstream", f"未知错误: {e}", retryable=True)


def get_key(provider: str) -> str:
    """从 LLM Key Store 或环境变量获取 Key（Key Store 优先）。"""
    try:
        from llm_keys import llm_keystore
        key = llm_keystore.get_key(provider)
        if key:
            return key
    except Exception:
        pass
    return env(_ENV_KEYS.get(provider, ""))


def get_base(provider: str, default: str = "") -> str:
    """从 LLM Key Store config 或环境变量获取 Base URL。"""
    try:
        from llm_keys import llm_keystore
        cfg = llm_keystore.get_config(provider)
        if cfg and isinstance(cfg, dict):
            return cfg.get("base_url", "")
    except Exception:
        pass
    env_key = _ENV_BASES.get(provider, "")
    return env(env_key) or default


def get_model(provider: str, env_key: str, default: str) -> str:
    """读取模型名：设置页 Key Store config.model → 环境变量 → 默认值。"""
    try:
        from llm_keys import llm_keystore
        cfg = llm_keystore.get_config(provider)
        if cfg and isinstance(cfg, dict) and cfg.get("model"):
            return cfg["model"]
    except Exception:
        pass
    return env(env_key) or default


# ── provider → env var 映射表 ──────────────────────────────────
_ENV_KEYS = {
    "volcano": "VOLCANO_API_KEY",
    "fal": "FAL_KEY",
    "comfyui": "COMFYUI_URL",
    "openai": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
}

_ENV_BASES = {
    "volcano": "VOLCANO_BASE_URL",
    "fal": "FAL_BASE_URL",
    "comfyui": "COMFYUI_URL",
    "openai": "OPENAI_BASE_URL",
    "claude": "ANTHROPIC_BASE_URL",
}
