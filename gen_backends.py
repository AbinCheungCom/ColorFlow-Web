"""ColorFlow GEN 生图适配器层 — 统一三个云后端，全部零本地 GPU。

设计目标（见《ColorFlow 开发文档 02 · 生图适配器（GEN · 路线 A）》）：
  - 单一入口 dispatch()，backend="auto" 时按 volcano → fal → comfyui 优先级
    探测可用后端，失败且 retryable 时自动降级到下一后端。
  - 输出统一为 PNG bytes（后端若返回 JPG/WebP 由适配器内部用 Pillow 转码）。
  - 所有网络调用带超时；失败抛 GenError(code, retryable)，由上层决定重试。
  - ref_image 传参即"图生图/参考图"模式；不支持的后端忽略并记 warning。

红线：
  - 零 GPU：任何后端不得引入本地模型推理，本地仅做 Pillow 格式转码（CPU 级）。
  - 失败可降级：auto 失败按顺序降级，最终失败抛明确错误码，绝不假成功。
  - Key 仅存服务端环境变量，不进前端页面回显。
"""

from dataclasses import dataclass, field
import io
import json
import os
import urllib.request
import urllib.error
import base64
import time
import logging

logger = logging.getLogger("colorflow.gen")


def _get_key(provider: str) -> str:
    """从 llm_keys 读取 key，回退到环境变量。"""
    try:
        from llm_keys import llm_keystore
        key = llm_keystore.get_key(provider)
        if key:
            return key
    except Exception:
        pass
    env_map = {"volcano": "VOLCANO_API_KEY", "fal": "FAL_KEY", "comfyui": "COMFYUI_URL"}
    return os.getenv(env_map.get(provider, ""), "").strip()


def _get_base(provider: str, default: str) -> str:
    """从 llm_keys 读取 base_url，回退到环境变量或默认值。"""
    try:
        from llm_keys import llm_keystore
        cfg = llm_keystore.get_config(provider)
        if cfg and isinstance(cfg, dict) and cfg.get("base_url"):
            return cfg["base_url"]
    except Exception:
        pass
    env_map = {"volcano": "VOLCANO_BASE_URL", "fal": "FAL_BASE_URL", "comfyui": "COMFYUI_URL"}
    return os.getenv(env_map.get(provider, ""), "") or default


def _get_model(provider: str, env_key: str, default: str) -> str:
    """读取模型名：设置页 Key Store config.model → 环境变量 → 默认值。"""
    try:
        from llm_keys import llm_keystore
        cfg = llm_keystore.get_config(provider)
        if cfg and isinstance(cfg, dict) and cfg.get("model"):
            return cfg["model"]
    except Exception:
        pass
    return _env(env_key) or default

# ── 后端优先级（auto 模式按此顺序探测）──────────────────────────────
_BACKEND_PRIORITY = ("volcano", "fal", "comfyui")


@dataclass
class GenResult:
    """统一生图返回结构"""
    png_bytes: bytes            # 图像原始字节（PNG）
    width: int = 0
    height: int = 0
    backend: str = ""           # 实际命中的后端：volcano / fal / comfyui
    model: str = ""             # 实际命中的模型名
    meta: dict = field(default_factory=dict)  # 各后端附加信息（耗时/费用/seed）


class GenError(Exception):
    """生图失败。code ∈ {auth, quota, timeout, rate_limit, upstream, bad_prompt}"""
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


# ============================================================
# 工具函数
# ============================================================

def _env(name: str) -> str:
    """读取环境变量并 trim，避免 Agent 启动后注入的尾部空白导致认证失败"""
    return os.getenv(name, "").strip()


def _http_json(url: str, method: str = "POST", headers: dict = None,
               body: dict = None, timeout: int = 120) -> dict:
    """发起 JSON 请求并解析 JSON 响应（urllib 实现，无额外依赖）。

    网络层异常统一映射为 GenError：
      - 超时 → timeout（retryable）
      - 401/403 → auth（不 retryable，但 auto 会换后端）
      - 402/429 → quota/rate_limit（retryable）
      - 其他 HTTP/网络 → upstream（retryable）
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
                # 非 JSON 响应，原样回传供上层判断
                return {"_raw": payload}
    except urllib.error.HTTPError as e:
        code = e.code
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        if code in (401, 403):
            raise GenError("auth", f"后端认证失败 ({code}): {body_text}", retryable=False)
        if code == 402:
            raise GenError("quota", f"额度不足 ({code}): {body_text}", retryable=True)
        if code == 429:
            raise GenError("rate_limit", f"请求过频 ({code}): {body_text}", retryable=True)
        raise GenError("upstream", f"HTTP {code}: {body_text}", retryable=True)
    except TimeoutError:
        raise GenError("timeout", f"请求超时 ({timeout}s)", retryable=True)
    except urllib.error.URLError as e:
        if "timed out" in str(e).lower():
            raise GenError("timeout", f"请求超时 ({timeout}s)", retryable=True)
        raise GenError("upstream", f"网络错误: {e}", retryable=True)
    except Exception as e:  # noqa: BLE001 - 兜底，绝不假成功
        raise GenError("upstream", f"未知错误: {e}", retryable=True)


def _http_bytes(url: str, headers: dict = None, timeout: int = 120) -> bytes:
    """发起 GET 取二进制（图片下载）"""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:  # noqa: BLE001
        raise GenError("upstream", f"图片下载失败: {e}", retryable=True)


def _to_png_bytes(raw: bytes) -> "tuple[bytes, int, int]":
    """任意图像字节（PNG/JPG/WebP/BMP）→ (PNG bytes, width, height)，用 Pillow 转码（CPU）"""
    from PIL import Image  # 延迟导入，避免无 Pillow 环境导入即失败

    img = Image.open(io.BytesIO(raw))
    if img.mode in ("RGBA", "LA"):
        pass
    else:
        img = img.convert("RGBA")
    w, h = img.size
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), w, h


def _parse_size(size) -> "tuple[int, int]":
    """size 接受 (w,h) 元组或 'WxH' 字符串，返回 (w,h)"""
    if isinstance(size, (tuple, list)) and len(size) == 2:
        return int(size[0]), int(size[1])
    if isinstance(size, str):
        for sep in ("x", "×", "*"):
            if sep in size:
                a, b = size.split(sep, 1)
                return int(a), int(b)
    return 1024, 1024


# ============================================================
# 后端能力发现
# ============================================================

def available_backends() -> list:
    """仅注册配置了 API Key/URL 的后端，按优先级排序"""
    found = []
    if _get_key("volcano"):
        found.append("volcano")
    if _get_key("fal"):
        found.append("fal")
    if _get_key("comfyui"):
        found.append("comfyui")
    # 保持优先级顺序
    return [b for b in _BACKEND_PRIORITY if b in found]


# ============================================================
# 适配器 A：volcano（火山方舟 / 即梦 Seedream 4）— 默认推荐
# ============================================================

_VOLCANO_URL = "https://ark.cn-beijing.volces.com/api/v3/images/generations"


def _gen_volcano(prompt: str, ref_image: bytes = None,
                 size=(1024, 1024), n: int = 1, timeout: int = 120,
                 model: str = "") -> list:
    """火山方舟生图。Seedream 支持中文 prompt，图生图传 ref_image。"""
    key = _get_key("volcano")
    if not key:
        raise GenError("auth", "未配置火山方舟 API Key", retryable=False)
    if not model:
        model = _get_model("volcano", "VOLCANO_MODEL", "doubao-seedream-4-0-t2i")
    w, h = _parse_size(size)

    body = {
        "model": model,
        "prompt": prompt,
        "size": f"{w}x{h}",
        "n": max(1, min(n, 4)),
        "response_format": "b64_json",
    }
    # 图生图：Seedream 编辑/参考能力（如后端支持 image 字段）
    if ref_image:
        body["image"] = base64.b64encode(ref_image).decode("utf-8")

    t0 = time.time()
    data = _http_json(_get_base("volcano", _VOLCANO_URL), headers={"Authorization": f"Bearer {key}"},
                     body=body, timeout=timeout)
    elapsed = int((time.time() - t0) * 1000)

    images = data.get("data") or data.get("images") or []
    if not images:
        raise GenError("upstream", f"volcano 返回无图像: {str(data)[:200]}", retryable=True)

    results = []
    for item in images:
        b64 = item.get("b64_json") or item.get("image") or ""
        if not b64:
            url = item.get("url")
            if url:
                raw = _http_bytes(url, timeout=timeout)
            else:
                continue
        else:
            raw = base64.b64decode(b64)
        png, iw, ih = _to_png_bytes(raw)
        results.append(GenResult(
            png_bytes=png, width=iw, height=ih,
            backend="volcano", model=model,
            meta={"elapsed_ms": elapsed, **(item.get("meta") or {})},
        ))
    if not results:
        raise GenError("upstream", "volcano 返回图像均无效", retryable=True)
    return results


# ============================================================
# 适配器 B：fal（fal.ai）— 海外/模型最全
# ============================================================

def _gen_fal(prompt: str, ref_image: bytes = None,
             size=(1024, 1024), n: int = 1, timeout: int = 120,
             model: str = "") -> list:
    """fal.ai 队列式生图：提交 → request_id → 轮询 status → 取图。"""
    key = _get_key("fal")
    if not key:
        raise GenError("auth", "未配置 FAL_KEY", retryable=False)
    if not model:
        model = _get_model("fal", "FAL_MODEL", "fal-ai/flux-pro/v1.1")
    w, h = _parse_size(size)

    fal_base = _get_base("fal", "https://queue.fal.run").rstrip("/")
    submit_url = f"{fal_base}/{model}"
    body = {
        "prompt": prompt,
        "image_size": {"width": w, "height": h},
        "num_images": max(1, min(n, 4)),
    }
    if ref_image:
        body["image_url"] = "data:image/png;base64," + base64.b64encode(ref_image).decode("utf-8")

    submit = _http_json(submit_url, headers={"Authorization": f"Key {key}"},
                        body=body, timeout=timeout)
    rid = submit.get("request_id")
    if not rid:
        raise GenError("upstream", f"fal 未返回 request_id: {str(submit)[:200]}", retryable=True)

    # 轮询状态
    status_url = f"{fal_base}/{model}/requests/{rid}/status"
    deadline = time.time() + timeout
    last_status = None
    while time.time() < deadline:
        st = _http_json(status_url, method="GET",
                        headers={"Authorization": f"Key {key}"}, timeout=30)
        last_status = st.get("status")
        if last_status == "COMPLETED":
            break
        if last_status in ("FAILED", "ERROR"):
            raise GenError("upstream", f"fal 生成失败: {st.get('error') or st}",
                           retryable=True)
        time.sleep(2)
    else:
        raise GenError("timeout", f"fal 轮询超时 (status={last_status})", retryable=True)

    # 取结果
    result_url = f"{fal_base}/{model}/requests/{rid}"
    result = _http_json(result_url, method="GET",
                        headers={"Authorization": f"Key {key}"}, timeout=timeout)
    imgs = (result.get("images") or result.get("data", {}).get("images") or [])
    if not imgs:
        raise GenError("upstream", f"fal 结果无图像: {str(result)[:200]}", retryable=True)

    out = []
    for item in imgs:
        url = item.get("url")
        if not url:
            continue
        raw = _http_bytes(url, timeout=timeout)
        png, iw, ih = _to_png_bytes(raw)
        out.append(GenResult(
            png_bytes=png, width=iw, height=ih,
            backend="fal", model=model,
            meta={"request_id": rid, "seed": item.get("seed")},
        ))
    if not out:
        raise GenError("upstream", "fal 返回图像均无效", retryable=True)
    return out


# ============================================================
# 适配器 C：comfyui（本地 ComfyUI HTTP API）— 可选装
# ============================================================

def _load_comfyui_workflow() -> dict:
    """加载文生图 API 工作流模板（assets/gen_workflow_api.json）。

    缺失时返回内置最小模板（含一个 CLIPTextEncode 节点，prompt 可注入）。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "assets", "gen_workflow_api.json"),
        os.path.join(here, "static", "gen_workflow_api.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    # 内置最小工作流模板（API 格式）
    return {
        "3": {"class_type": "KSampler", "inputs": {
            "seed": 0, "steps": 20, "cfg": 8,
            "sampler_name": "euler", "scheduler": "normal",
            "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
            "latent_image": ["5", 0]}},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "model.safetensors"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad", "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "colorflow"}},
    }


def _inject_prompt(workflow: dict, prompt: str, size=(1024, 1024)) -> dict:
    """向工作流中 CLIPTextEncode 节点注入 prompt，并按尺寸调整 EmptyLatentImage。

    工作流可能含 _comment 等字符串元字段，迭代时跳过非 dict 节点。
    """
    w, h = _parse_size(size)
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type", "")
        if ct == "CLIPTextEncode" and "text" in node.get("inputs", {}):
            # 找到 positive（含空 text 的第一个 CLIPTextEncode）注入
            if not node["inputs"]["text"]:
                node["inputs"]["text"] = prompt
        elif ct == "EmptyLatentImage":
            node["inputs"]["width"] = w
            node["inputs"]["height"] = h
    return workflow


def _gen_comfyui(prompt: str, ref_image: bytes = None,
                 size=(1024, 1024), n: int = 1, timeout: int = 120,
                 model: str = "") -> list:
    """本地 ComfyUI /prompt 提交 + /history 轮询 + /view 取图。"""
    base = _get_key("comfyui").rstrip("/")
    if not base:
        raise GenError("auth", "未配置 COMFYUI_URL", retryable=False)

    workflow = _load_comfyui_workflow()
    workflow = _inject_prompt(workflow, prompt, size)
    if ref_image:
        # comfyui 图生图需用户工作流自带 LoadImage 节点，此处仅提示
        logger.warning("comfyui 后端图生图依赖用户工作流自带 LoadImage 节点，ref_image 已忽略")

    submit = _http_json(f"{base}/prompt", body={"prompt": workflow, "client_id": "colorflow"},
                        timeout=30)
    pid = submit.get("prompt_id")
    if not pid:
        raise GenError("upstream", f"comfyui 未返回 prompt_id: {str(submit)[:200]}", retryable=True)

    deadline = time.time() + timeout
    outputs = None
    while time.time() < deadline:
        hist = _http_json(f"{base}/history/{pid}", method="GET", timeout=30)
        entry = hist.get(pid)
        if entry and entry.get("outputs"):
            outputs = entry["outputs"]
            break
        time.sleep(2)
    else:
        raise GenError("timeout", f"comfyui 轮询超时 (prompt_id={pid})", retryable=True)

    out = []
    for node_id, node_out in outputs.items():
        for img in (node_out.get("images") or []):
            fname = img.get("filename")
            sub = img.get("subfolder", "")
            typ = img.get("type", "output")
            params = f"filename={fname}&subfolder={sub}&type={typ}"
            raw = _http_bytes(f"{base}/view?{params}", timeout=timeout)
            png, iw, ih = _to_png_bytes(raw)
            out.append(GenResult(
                png_bytes=png, width=iw, height=ih,
                backend="comfyui", model=model or "comfyui-workflow",
                meta={"prompt_id": pid, "node": node_id},
            ))
            if len(out) >= max(1, min(n, 4)):
                break
    if not out:
        raise GenError("upstream", "comfyui 输出无图像", retryable=True)
    return out


# ============================================================
# 后端注册表
# ============================================================

_BACKENDS = {
    "volcano": _gen_volcano,
    "fal": _gen_fal,
    "comfyui": _gen_comfyui,
}


# ============================================================
# 唯一入口：dispatch
# ============================================================

def dispatch(prompt: str, ref_image: bytes = None,
             backend: str = "auto",
             size=(1024, 1024), n: int = 1, timeout: int = 120,
             model: str = "") -> list:
    """统一生图入口。

    Args:
        prompt: 生图描述（中文/英文均可）
        ref_image: 参考图字节（图生图），可选
        backend: auto / volcano / fal / comfyui
        size: 输出尺寸，元组或 'WxH'
        n: 生成张数（上限 4，见 GEN_MAX_IMAGES）
        timeout: 超时秒数
        model: 覆盖模型名（空则用各后端默认）
    Returns:
        list[GenResult]
    Raises:
        GenError: 最终失败（含 code 与 retryable）
    """
    if not prompt or not prompt.strip():
        raise GenError("bad_prompt", "prompt 不能为空", retryable=False)
    # ref_image 类型校验：只接受 bytes 或 None（JSON 路径可能传入 str）
    if ref_image is not None and not isinstance(ref_image, (bytes, bytearray)):
        raise GenError("bad_prompt", "ref_image 必须是 bytes（PNG/JPG 字节），不接受 str", retryable=False)
    try:
        n = max(1, min(int(n), int(os.getenv("GEN_MAX_IMAGES", "4"))))
        timeout = int(os.getenv("GEN_TIMEOUT", str(timeout)) or timeout)
    except (TypeError, ValueError):
        raise GenError("bad_prompt", "n 或 GEN_TIMEOUT 参数非法", retryable=False)

    # 指定后端
    if backend and backend != "auto":
        if backend not in _BACKENDS:
            raise GenError("bad_prompt", f"未知后端: {backend}", retryable=False)
        fn = _BACKENDS[backend]
        # 指定后端也校验是否已配置（volcano/fal 需 Key，comfyui 需 URL）
        if backend == "volcano" and not _get_key("volcano"):
            raise GenError("auth", "未配置火山方舟 API Key", retryable=False)
        if backend == "fal" and not _get_key("fal"):
            raise GenError("auth", "未配置 FAL_KEY", retryable=False)
        if backend == "comfyui" and not _get_key("comfyui"):
            raise GenError("auth", "未配置 COMFYUI_URL", retryable=False)
        try:
            return fn(prompt, ref_image=ref_image, size=size, n=n, timeout=timeout, model=model)
        except GenError:
            raise
        except Exception as e:
            raise GenError("upstream", f"后端 {backend} 异常: {type(e).__name__}", retryable=True) from e

    # auto：按优先级探测可用后端，retryable 失败降级
    avail = available_backends()
    if not avail:
        raise GenError("auth", "未配置任何生图后端 Key（VOLCANO_API_KEY / FAL_KEY / COMFYUI_URL）",
                       retryable=False)

    last_err = None
    for bid in avail:
        fn = _BACKENDS[bid]
        try:
            return fn(prompt, ref_image=ref_image, size=size, n=n, timeout=timeout, model=model)
        except GenError as e:
            last_err = e
            logger.warning("后端 %s 失败 (%s, retryable=%s): %s — 尝试下一后端",
                           bid, e.code, e.retryable, e)
            if not e.retryable and e.code == "bad_prompt":
                break  # prompt 本身非法，换后端无意义
            continue
        except Exception as e:
            last_err = GenError("upstream", f"后端 {bid} 异常: {type(e).__name__}", retryable=True)
            logger.warning("后端 %s 异常: %s — 尝试下一后端", bid, e, exc_info=True)
            continue
    raise last_err or GenError("upstream", "所有后端均失败", retryable=False)
