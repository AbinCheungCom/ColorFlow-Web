"""ColorFlow LLM Key Store — 大模型 API Key 管理（生图/图→prompt/优化）

存储格式：JSON 文件，默认 ~/.colorflow/llm_keys.json
与 colorflow_keys.py（应用 API Key）分离：本模块管理 LLM 后端 Key。

支持的 provider：
  - openai   : OPENAI_API_KEY（生图/图→prompt/优化）
  - claude   : ANTHROPIC_API_KEY（图→prompt）
  - volcano  : VOLCANO_API_KEY（生图）
  - fal      : FAL_KEY（生图）
  - comfyui  : COMFYUI_URL（生图，非 Key 而是 URL）

每个 provider 可配置：
  - key:     API Key 或 URL（脱敏存储）
  - name:    名称标签
  - config:  附加配置（base_url, model 等）
  - created_at / last_used: 时间戳
"""

import json
import os
import secrets
import threading
from datetime import datetime, timezone

# Key 文件默认路径
_DEFAULT_PATH = os.path.join(os.path.expanduser("~"), ".colorflow", "llm_keys.json")

_lock = threading.Lock()

# Provider 注册表：定义每个 provider 的元数据
PROVIDERS = {
    "openai": {
        "label": "OpenAI",
        "icon": "🤖",
        "uses": ["gen", "vision", "optimize"],
        "key_prefix": "sk-",
        "env_key": "OPENAI_API_KEY",
        "env_base": "OPENAI_BASE_URL",
        "default_base": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
    },
    "claude": {
        "label": "Anthropic Claude",
        "icon": "🧠",
        "uses": ["vision"],
        "key_prefix": "sk-ant-",
        "env_key": "ANTHROPIC_API_KEY",
        "env_base": "ANTHROPIC_BASE_URL",
        "default_base": "https://api.anthropic.com",
        "default_model": "claude-sonnet-4-6",
    },
    "volcano": {
        "label": "火山方舟 · 即梦",
        "icon": "🌋",
        "uses": ["gen"],
        "key_prefix": "",
        "env_key": "VOLCANO_API_KEY",
        "env_base": "VOLCANO_BASE_URL",
        "default_base": "",
        "default_model": "seedream-2.0",
    },
    "fal": {
        "label": "fal.ai",
        "icon": "⚡",
        "uses": ["gen"],
        "key_prefix": "",
        "env_key": "FAL_KEY",
        "env_base": "FAL_BASE_URL",
        "default_base": "https://fal.run",
        "default_model": "",
    },
    "comfyui": {
        "label": "本地 ComfyUI",
        "icon": "🖥️",
        "uses": ["gen"],
        "key_prefix": "http",
        "env_key": "COMFYUI_URL",
        "env_base": "",
        "default_base": "http://127.0.0.1:8188",
        "default_model": "",
    },
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mask_key(key, provider):
    """脱敏 Key：显示前缀 + 后 4 位"""
    if not key:
        return ""
    info = PROVIDERS.get(provider, {})
    prefix = info.get("key_prefix", "")
    if prefix and key.startswith(prefix):
        return prefix + "*" * 6 + key[-4:]
    if len(key) <= 10:
        return key[:3] + "****"
    return key[:6] + "…" + key[-4:]


class LLMKeyStore:
    """线程安全的 LLM API Key 管理器"""

    def __init__(self, path=None):
        self.path = path or _DEFAULT_PATH
        self._cache = None

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _save(self, data):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        self._cache = data

    def _flush(self):
        self._cache = None

    # ---- 公开 API ----

    def get_key(self, provider):
        """获取指定 provider 的 Key（明文），无则返回 None"""
        with _lock:
            data = self._load()
            entry = data.get(provider)
            if entry and entry.get("key"):
                return entry["key"]
        return None

    def get_config(self, provider):
        """获取指定 provider 的完整配置（含 config dict）"""
        with _lock:
            data = self._load()
            return data.get(provider, {}).get("config", {})

    def set_key(self, provider, key, name="", config=None):
        """设置/更新指定 provider 的 Key。返回 entry（含明文 key，仅此一次可见）"""
        if provider not in PROVIDERS:
            raise ValueError(f"未知 provider: {provider}")
        if not key or not key.strip():
            raise ValueError("key 不能为空")
        key = key.strip()
        entry = {
            "key": key,
            "name": name.strip() or PROVIDERS[provider]["label"],
            "created_at": _now_iso(),
            "last_used": None,
            "config": config or {},
        }
        with _lock:
            data = self._load()
            data[provider] = entry
            self._save(data)
        return entry

    def remove(self, provider):
        """移除指定 provider 的 Key，返回 bool"""
        with _lock:
            data = self._load()
            if provider in data:
                del data[provider]
                self._save(data)
                return True
            return False

    def list_all(self):
        """列出所有 provider 的 Key 状态（脱敏）"""
        with _lock:
            data = self._load()
        result = []
        for pid, info in PROVIDERS.items():
            entry = data.get(pid, {})
            has_key = bool(entry.get("key"))
            result.append({
                "provider": pid,
                "label": info["label"],
                "icon": info["icon"],
                "uses": info["uses"],
                "has_key": has_key,
                "key_masked": _mask_key(entry.get("key", ""), pid) if has_key else "",
                "name": entry.get("name", ""),
                "created_at": entry.get("created_at", ""),
                "last_used": entry.get("last_used"),
                "base_url": entry.get("config", {}).get("base_url", info.get("default_base", "")),
                "model": entry.get("config", {}).get("model", info.get("default_model", "")),
            })
        return result

    def has_any(self):
        """是否已有任何 LLM Key"""
        with _lock:
            return len(self._load()) > 0

    def mark_used(self, provider):
        """标记指定 provider 的 Key 已使用（更新 last_used）"""
        with _lock:
            data = self._load()
            entry = data.get(provider)
            if entry:
                now = _now_iso()
                if entry.get("last_used") != now:
                    entry["last_used"] = now
                    try:
                        self._save(data)
                    except OSError:
                        pass


# 全局单例
llm_keystore = LLMKeyStore()

# 启动时从环境变量 bootstrap（向后兼容）
for pid, info in PROVIDERS.items():
    env_key_name = info.get("env_key", "")
    env_val = os.getenv(env_key_name, "").strip()
    if env_val:
        with _lock:
            data = llm_keystore._load()
            if pid not in data or not data[pid].get("key"):
                base_env = info.get("env_base", "")
                base_val = os.getenv(base_env, "").strip() if base_env else ""
                llm_keystore._save({**data, pid: {
                    "key": env_val,
                    "name": info["label"] + " (env)",
                    "created_at": _now_iso(),
                    "last_used": None,
                    "config": {"base_url": base_val} if base_val else {},
                }})
