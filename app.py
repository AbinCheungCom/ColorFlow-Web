# ColorFlow Web - AI 矢量描图 + Pantone 色彩管理

from flask import Flask, render_template, request, jsonify, Response
import os
import base64
import secrets
import tempfile
import logging
import time
import threading
import uuid

from colorflow_sdk import ColorFlowSDK, extract_svg_colors
from colorflow_sdk.exceptions import ValidationError
from mcp_print.tools.colors import (
    pantone_to_cmyk,
    pantone_search,
    cmyk_to_rgb,
    _hex_to_rgb,
    _rgb_to_lab,
    _cmyk_to_lab,
)
from mcp_print.tools.cost import print_cost_estimate

from services.color_delta_e import delta_e_cie76

from gen_backends import dispatch as gen_dispatch, available_backends, GenError as GenGenError
from vision_backends import (
    dispatch_prompt,
    available_backends as vision_available_backends,
    PromptError as GenPromptError,
)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB
# 上传目录：桌面封装（colorflow_desktop_app.py）通过 COLORFLOW_UPLOAD_DIR 指向临时目录；
# 未设置时回退到 /tmp（Linux/macOS 或已 chdir 的 Windows）
_upload_dir = os.getenv("COLORFLOW_UPLOAD_DIR") or "/tmp/colorflow-uploads"
app.config["UPLOAD_FOLDER"] = _upload_dir

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# === 日志配置：便于排查 "Failed to fetch" 等异常 ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("colorflow")

# === CORS 支持：允许浏览器跨域请求（解决 "TypeError: Failed to fetch"） ===
@app.after_request
def add_cors_headers(response):
    """为所有响应添加 CORS 头，允许浏览器跨域访问 API"""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, x-api-key, Authorization"
    )
    return response


@app.before_request
def handle_preflight():
    """处理 CORS preflight OPTIONS 请求"""
    if request.method == "OPTIONS":
        return Response(status=204)

# Initialize SDK
sdk = ColorFlowSDK(output_dir="/tmp/colorflow-output")

_START_TIME = time.time()  # 进程启动时间戳（供 /healthz 上报 uptime）


@app.route("/healthz", methods=["GET"])
def healthz():
    """轻量健康检查：返回 200 表示进程存活。

    不触发 SDK/抠图模型加载（避免探针拖慢冷启动），仅检查进程级依赖导入。
    Docker HEALTHCHECK / K8s livenessProbe / readinessProbe 可直接使用。
    该端点不经 /api/* 鉴权，供负载均衡 / 容器编排探针访问。
    """
    checks = {}
    try:
        import colorflow_sdk  # noqa: F401
        checks["colorflow_sdk"] = True
    except Exception as e:
        checks["colorflow_sdk"] = str(e)
    try:
        import rembg  # noqa: F401
        checks["rembg"] = True
    except Exception as e:
        checks["rembg"] = str(e)
    try:
        import reportlab  # noqa: F401
        checks["reportlab"] = True
    except Exception as e:
        checks["reportlab"] = str(e)
    checks["gen_backends"] = available_backends()
    checks["vision_backends"] = vision_available_backends()
    return jsonify({
        "status": "ok",
        "pid": os.getpid(),
        "uptime_s": round(time.time() - _START_TIME, 1),
        "checks": checks,
    })


# 允许的图片类型
ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp", "image/bmp"}

# API Key 认证：通过 KeyStore 管理（支持从 UI 生成/撤销）；COLORFLOW_API_KEY 环境变量向后兼容
from colorflow_keys import keystore

# Key 管理端点白名单（不需要已有 key 即可访问 — bootstrap 模式）
_KEY_MGMT_PATHS = {"/api/keys/generate", "/api/keys"}


@app.before_request
def require_api_key():
    """保护 /api/* 路由：已配置 Key 时，请求必须携带正确的 x-api-key 头。"""
    if not request.path.startswith("/api/"):
        return  # 页面 / 与静态资源保持公开

    # Key 管理端点的特殊处理
    if request.path in _KEY_MGMT_PATHS:
        # 如果还没有任何 key → 允许首次生成（bootstrap）
        if not keystore.has_any():
            return
        # 已有 key → 必须携带有效 key 才能管理
        api_key = request.headers.get("x-api-key", "")
        if keystore.verify(api_key):
            return
        return jsonify({"error": "Unauthorized: missing or invalid API key"}), 401

    # 普通业务端点
    if not keystore.has_any():
        return  # 无 key → 开放（本地开发模式）

    api_key = request.headers.get("x-api-key", "")
    if keystore.verify(api_key):
        return
    return jsonify({"error": "Unauthorized: missing or invalid API key"}), 401


def _int_arg(value, default):
    """解析 int 表单/查询参数，非法值返回默认值（不抛异常）"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_arg(value, default):
    """解析 float 表单/查询参数，非法值返回默认值"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _require_hex(hex_color):
    """校验 HEX 颜色格式（#RRGGBB），非法则返回 None"""
    if not hex_color:
        return None
    if not hex_color.startswith("#"):
        hex_color = "#" + hex_color
    if len(hex_color) != 7:
        return None
    try:
        int(hex_color[1:], 16)
    except ValueError:
        return None
    return hex_color.upper()


def _get_uploaded_image():
    """校验并读取上传图片。

    Returns:
        (image_bytes, image_format) 成功；失败时返回 (None, (error_response, status))。
    """
    if "image" not in request.files:
        return None, (jsonify({"error": "No image provided"}), 400)

    file = request.files["image"]
    if not file.filename:
        return None, (jsonify({"error": "Empty file"}), 400)

    content_type = file.content_type or "image/png"
    if content_type not in ALLOWED_CONTENT_TYPES:
        return None, (
            jsonify({"error": f"Unsupported file type: {content_type}"}),
            415,
        )

    format_map = {
        "image/png": "png",
        "image/jpeg": "jpeg",
        "image/webp": "webp",
        "image/bmp": "bmp",
    }
    return (file.read(), format_map[content_type]), None


def _trace_parameters():
    """从表单读取描图参数（非法值回退默认值）"""
    # mode 由 SDK 校验（仅接受 color/grey/human），非法值由 SDK 抛 ValidationError → 400
    mode = request.form.get("mode", "color").strip() or "color"

    colormode = request.form.get("colormode", "rgb8").strip() or "rgb8"
    VALID_COLORMODES = ("rgb8", "rgb16", "mono", "grey", "grey16")
    if colormode not in VALID_COLORMODES:
        colormode = "rgb8"

    hierarchical = request.form.get("hierarchical", "stacked").strip() or "stacked"
    VALID_HIER = ("flat", "stacked")
    if hierarchical not in VALID_HIER:
        hierarchical = "stacked"

    lt_raw = request.form.get("length_threshold", "").strip()
    if lt_raw == "":
        length_threshold = 2.0
    else:
        try:
            length_threshold = max(0.1, min(100.0, float(lt_raw)))
        except (ValueError, TypeError):
            length_threshold = 2.0

    return {
        "mode": mode,
        "colormode": colormode,
        "hierarchical": hierarchical,
        "length_threshold": length_threshold,
        "filter_speckle": _int_arg(request.form.get("filter_speckle"), 4),
        "color_precision": _int_arg(request.form.get("color_precision"), 6),
        "layer_difference": _int_arg(request.form.get("layer_difference"), 64),
        "corner_threshold": _int_arg(request.form.get("corner_threshold"), 60),
        "path_precision": _int_arg(request.form.get("path_precision"), 7),
        "ignore_white": request.form.get("ignore_white", "0") in ("1", "true", "yes"),
    }


# === 忽略白色：SVG 后处理 ===
#
# VTracer 不支持透明 PNG（alpha 像素会被压成黑色，见 colorflow_sdk/cutout.py
# composite_on_background 注释），因此「先把输入图白色抠掉再描」走不通。
# 但 VTracer 输出的 SVG 自身没有显式 background，白色区域其实是一个
# fill="rgb(255,255,255)" 的底层 <path>——把它移除，SVG 自然就透明。
#
# 容差默认 16：JPEG 压缩会让纯白背景变成 #F0F0F0 上下，需要一定宽容度。
import io as _io
import re as _re
import xml.etree.ElementTree as _ET

_RGB_RE = _re.compile(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", _re.I)
_HEX_RE = _re.compile(r"#([0-9a-f]{3}|[0-9a-f]{6})\b", _re.I)


def _parse_svg_color(value):
    """解析 'rgb(R,G,B)' / '#RRGGBB' / '#RGB' / 'white' → (R,G,B) 元组；不支持的格式返回 None"""
    if not value:
        return None
    v = value.strip().lower()
    if v == "white":
        return (255, 255, 255)
    m = _RGB_RE.match(v)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _HEX_RE.match(v)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    return None


def _strip_white_paths(svg_bytes, tolerance=16):
    """移除 SVG 中 fill 为白色 / 近白（容差内）的 path 元素，返回新字节"""
    try:
        root = _ET.fromstring(svg_bytes)
    except _ET.ParseError:
        return svg_bytes  # 解析失败 → 原样返回，不影响主流程

    _ET.register_namespace("", "http://www.w3.org/2000/svg")
    _ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")

    def is_near_white(v):
        c = _parse_svg_color(v)
        return c is not None and all(ch >= 255 - tolerance for ch in c)

    for parent in root.iter():
        to_remove = [ch for ch in parent if is_near_white(ch.get("fill", ""))]
        for ch in to_remove:
            parent.remove(ch)

    out = _io.BytesIO()
    _ET.ElementTree(root).write(out, encoding="utf-8", xml_declaration=True)
    return out.getvalue()


@app.route("/")
def index():
    resp = render_template("index.html")
    # no-cache：改版后浏览器不再显示旧页面（开发清单 P1-2.1）
    return Response(resp, headers={
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    })


@app.route("/api/health", methods=["GET"])
def health_check():
    """健康检查：返回服务状态"""
    return jsonify({
        "status": "ok",
        "version": "1.0",
    })


# VTracer mode 只接受 color / grey / human；抠图模式内部强制走 color 描图
# colormode 已加入透传：SDK 在输入侧用 ImageOps 补偿（灰度/二值/posterize）
_TRACE_SDK_KEYS = (
    "filter_speckle",
    "color_precision",
    "layer_difference",
    "corner_threshold",
    "path_precision",
    "colormode",
    "hierarchical",
    "length_threshold",
)


def _trace_svg(image_bytes, image_format, params):
    """按参数生成 SVG 字节：mode=cutout 走 rembg 抠图+描图，否则走 VTracer 描图。

    抠图时自动去除白色底层路径（rembg 输出为透明底 PNG，SDK 会先合成白底再
    描图，需后处理去掉白底），因此忽略 ignore_white 开关（必然透明）。
    """
    mode = params.get("mode", "color")
    ignore_white = params.pop("ignore_white", False)

    if mode == "cutout":
        trace_kwargs = {k: params[k] for k in _TRACE_SDK_KEYS if k in params}
        trace_kwargs["mode"] = "color"  # VTracer 不接受 cutout
        # 抠图精度参数
        cutout_params = _cutout_parameters()
        cutout_model = cutout_params.pop("model", "silueta")
        rgba = _rembg_cutout(image_bytes, model=cutout_model, **cutout_params)
        import io as _bio

        flat = _bio.BytesIO()
        from PIL import Image as _PILImage

        white_bg = _PILImage.new("RGB", rgba.size, (255, 255, 255))
        white_bg.paste(rgba, mask=rgba.split()[3])
        flat_buf = _bio.BytesIO()
        white_bg.save(flat_buf, format="PNG")
        svg_bytes = sdk.trace_bytes(flat_buf.getvalue(), image_format="png", **trace_kwargs)
        return _strip_white_paths(svg_bytes), True  # 抠图恒透明
    else:
        svg_bytes = sdk.trace_bytes(
            image_bytes,
            image_format=image_format,
            **params,
        )
        if ignore_white:
            svg_bytes = _strip_white_paths(svg_bytes)
        return svg_bytes, False


# === rembg 抠图（session 缓存） ===
#
# 背景：cutout_image() 每次调用都会 new_session() 重新加载 42MB ONNX 模型，
# 在服务器上会导致每次抠图耗时数秒 + 内存峰值高，低配服务器易超时/崩溃，
# 前端表现为 "TypeError: Failed to fetch"（连接被重置，不是 HTTP 错误）。
# 解决：全局缓存 rembg session，模型只加载一次，后续请求直接复用。
import threading as _threading

_rembg_sessions: dict = {}
_rembg_session_errors: dict = {}  # 模型加载失败缓存，避免重复下载
_rembg_session_lock = _threading.Lock()


def _get_rembg_session(model="silueta"):
    """获取（并缓存）rembg session，按模型名分表缓存，避免每次请求重新加载。
    模型加载失败时缓存错误，后续请求直接返回错误，不再重试下载。
    """
    with _rembg_session_lock:
        if model in _rembg_session_errors:
            raise _rembg_session_errors[model]
        if model not in _rembg_sessions:
            from rembg import new_session

            try:
                _rembg_sessions[model] = new_session(model)
            except Exception as e:
                # 缓存错误（ValueError: model not supported; ConnectTimeout: 下载超时等）
                _rembg_session_errors[model] = e
                raise
    return _rembg_sessions[model]


def _rembg_cutout(image_bytes, model="silueta", **kwargs):
    """位图字节 → rembg 抠图 → 透明底 RGBA PIL Image（复用缓存 session，精度参数透传）"""
    import io as _bio

    from rembg import remove as _rembg_remove

    session = _get_rembg_session(model)
    result = _rembg_remove(image_bytes, session=session, **kwargs)
    return _bio_open_rgba(result)


# rembg 支持的模型（保留随包可用 + 已缓存可下载的模型，剔除需下载/需API的模型）
REMBG_MODELS = [
    ("silueta", "通用 · 快速（默认，已随包附带）"),
    ("u2net_human_seg", "人像 · 精细（已缓存）"),
]


def _cutout_parameters():
    """从表单读取抠图精度参数（非法值回退 rembg 默认值）"""
    # 模型名校验：非法模型回退 silueta（已随包附带，无需下载）
    model = request.form.get("model", "silueta").strip() or "silueta"
    VALID_REMBG_MODELS = {m[0] for m in REMBG_MODELS}
    if model not in VALID_REMBG_MODELS:
        model = "silueta"

    params = {
        "model": model,
        "alpha_matting": request.form.get("alpha_matting", "0") in ("1", "true", "yes"),
        "alpha_matting_foreground_threshold": _int_arg(
            request.form.get("alpha_matting_foreground_threshold"), 240
        ),
        "alpha_matting_background_threshold": _int_arg(
            request.form.get("alpha_matting_background_threshold"), 10
        ),
        "alpha_matting_erode_size": _int_arg(
            request.form.get("alpha_matting_erode_size"), 10
        ),
        "decontaminate": request.form.get("decontaminate", "0") in ("1", "true", "yes"),
        "post_process_mask": request.form.get("post_process_mask", "0") in ("1", "true", "yes"),
    }
    params["alpha_matting_foreground_threshold"] = max(10, min(255, params["alpha_matting_foreground_threshold"]))
    params["alpha_matting_background_threshold"] = max(0, min(245, params["alpha_matting_background_threshold"]))
    params["alpha_matting_erode_size"] = max(1, min(20, params["alpha_matting_erode_size"]))
    return params


def _bio_open_rgba(data):
    import io as _bio

    from PIL import Image

    return Image.open(_bio.BytesIO(data)).convert("RGBA")


@app.route("/api/cutout", methods=["POST"])
def cutout_api():
    """位图抠图：上传图片 → rembg 移除背景 → 透明 PNG（base64）"""
    upload, err = _get_uploaded_image()
    if err:
        return err

    image_bytes, _image_format = upload

    params = _cutout_parameters()
    model = params.pop("model", "silueta")

    try:
        import io as _b

        from PIL import Image

        rgba = _rembg_cutout(image_bytes, model=model, **params)  # 复用缓存 session + 精度参数
        buf = _b.BytesIO()
        rgba.save(buf, format="PNG")
        png_bytes = buf.getvalue()
        return jsonify(
            {
                "success": True,
                "png_base64": base64.b64encode(png_bytes).decode("utf-8"),
                "size": len(png_bytes),
                "width": rgba.width,
                "height": rgba.height,
                "model": model,
            }
        )
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    except (ValueError, OSError) as e:
        err = str(e)
        if "No session class" in err:
            return jsonify({"error": f"模型 '{model}' 在当前 rembg 版本中不受支持，请换用 silueta"}), 500
        if "Invalid argument" in err or "Errno 22" in err:
            return jsonify({"error": f"模型 '{model}' 加载失败（可能缓存损坏），建议换用 silueta 或重启服务"}), 500
        return jsonify({"error": err}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/trace", methods=["POST"])
def trace_image():
    """位图 → SVG 矢量描图（mode=cutout 时为抠图）"""
    upload, err = _get_uploaded_image()
    if err:
        return err

    image_bytes, image_format = upload
    params = _trace_parameters()

    try:
        svg_bytes, _is_cutout = _trace_svg(image_bytes, image_format, params)
        # Return as base64 for easier JS handling
        b64 = base64.b64encode(svg_bytes).decode("utf-8")
        return jsonify(
            {
                "success": True,
                "svg_base64": b64,
                "size": len(svg_bytes),
            }
        )
    except ValidationError as e:
        logger.warning("trace_image 参数校验失败: %s", e)
        return jsonify({"error": str(e)}), 400
    except (ValueError, OSError) as e:
        err = str(e)
        model = request.form.get("model", "silueta").strip() or "silueta"
        if "No session class" in err:
            return jsonify({"error": f"模型 '{model}' 在当前 rembg 版本中不受支持，请换用 silueta"}), 500
        if "Invalid argument" in err or "Errno 22" in err:
            return jsonify({"error": f"模型 '{model}' 加载失败（可能缓存损坏），建议换用 silueta 或重启服务"}), 500
        logger.exception("trace_image 描图失败")
        return jsonify({"error": err}), 500
    except Exception as e:
        logger.exception("trace_image 描图失败（可能导致浏览器 Failed to fetch）")
        return jsonify({"error": f"描图失败: {type(e).__name__}"}), 500


@app.route("/api/trace/colors", methods=["POST"])
def trace_colors():
    """一键流水线：位图 → SVG → 提取主色 → Pantone 匹配（含 ΔE）"""
    upload, err = _get_uploaded_image()
    if err:
        return err

    image_bytes, image_format = upload
    params = _trace_parameters()

    try:
        svg_bytes, _is_cutout = _trace_svg(image_bytes, image_format, params)
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    except (ValueError, OSError) as e:
        err = str(e)
        model = request.form.get("model", "silueta").strip() or "silueta"
        if "No session class" in err:
            return jsonify({"error": f"模型 '{model}' 在当前 rembg 版本中不受支持，请换用 silueta"}), 500
        if "Invalid argument" in err or "Errno 22" in err:
            return jsonify({"error": f"模型 '{model}' 加载失败（可能缓存损坏），建议换用 silueta 或重启服务"}), 500
        return jsonify({"error": err}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    try:
        # 提取主色并逐一匹配 Pantone
        colors = extract_svg_colors(svg_bytes, top_n=5)
        palette = []
        for c in colors:
            lab_hex = _rgb_to_lab(*_hex_to_rgb(c["hex"]))
            matches = []
            for m in pantone_search(hex_color=c["hex"]).get("matches", [])[:3]:
                lab_pantone = _cmyk_to_lab(m["c"], m["m"], m["y"], m["k"])
                de = delta_e_cie76(lab_hex, lab_pantone)
                _rgb = cmyk_to_rgb(m["c"], m["m"], m["y"], m["k"])
                matches.append(
                    {
                        "name": m["name"],
                        "hex": m["hex"],
                        "cmyk": [m["c"], m["m"], m["y"], m["k"]],
                        "rgb": [_rgb["r"], _rgb["g"], _rgb["b"]],
                        "delta_e": round(de, 2),
                    }
                )
            palette.append(
                {
                    "color": {
                        "hex": c["hex"],
                        "count": c["count"],
                        "share": c["share"],
                        "rgb": list(_hex_to_rgb(c["hex"])),
                    },
                    "pantone_matches": matches,
                }
            )

        return jsonify(
            {
                "success": True,
                "svg_base64": base64.b64encode(svg_bytes).decode("utf-8"),
                "size": len(svg_bytes),
                "palette": palette,
                "color_count": len(palette),
            }
        )
    except ValidationError as e:
        # 参数类错误（如 pantone_search 收到非法颜色），4xx，无堆栈
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        # 真实逻辑/数据错误：记录完整堆栈便于线上排障，避免被宽泛捕获掩盖
        app.logger.exception("trace_colors 调色板构建失败")
        return jsonify({"error": f"调色板构建失败: {type(e).__name__}"}), 500


@app.route("/api/pantone/match", methods=["POST"])
def match_pantone():
    """HEX → Pantone 匹配"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400
    hex_color = _require_hex(data.get("hex_color", "").strip())
    if not hex_color:
        return jsonify({"error": "Invalid hex_color. Expected format: #RRGGBB"}), 400

    try:
        results = pantone_search(hex_color=hex_color)
        matches = results.get("matches", [])[:5]

        # Convert input hex to LAB for Delta E calculation
        rgb_hex_tuple = _hex_to_rgb(hex_color)
        lab_hex = _rgb_to_lab(*rgb_hex_tuple)

        # Enrich with delta E and RGB
        enriched = []
        for m in matches:
            c, mm, y, k = m["c"], m["m"], m["y"], m["k"]
            rgb = cmyk_to_rgb(c, mm, y, k)
            # Delta E via LAB
            lab_pantone = _cmyk_to_lab(c, mm, y, k)
            de_value = delta_e_cie76(lab_hex, lab_pantone)
            de_interp = (
                "excellent — imperceptible difference"
                if de_value < 1
                else "good — barely perceptible"
                if de_value < 3
                else "fair — noticeable difference"
                if de_value < 6
                else "poor — obvious difference"
            )
            enriched.append(
                {
                    "name": m["name"],
                    "hex": m["hex"],
                    "cmyk": [c, mm, y, k],
                    "rgb": rgb,
                    "delta_e": round(de_value, 2),
                    "interpretation": de_interp,
                }
            )

        return jsonify(
            {
                "success": True,
                "matches": enriched,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/pantone/lookup", methods=["GET"])
def pantone_lookup():
    """Pantone 名称精确查询"""
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "No name provided"}), 400

    try:
        result = pantone_to_cmyk(name)
        return jsonify(
            {
                "success": True,
                "result": result,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/pantone/colors", methods=["GET"])
def list_colors():
    """获取所有 Pantone 颜色（分页）"""
    page = _int_arg(request.args.get("page"), 1)
    limit = _int_arg(request.args.get("limit"), 50)
    search = request.args.get("search", "").strip()

    # 分页参数边界约束
    page = max(page, 1)
    limit = min(max(limit, 1), 200)

    try:
        from mcp_print.tools.colors import _load_db

        db = _load_db()

        if search:
            search = search.lower()
            db = [c for c in db if search in c.get("name", "").lower()]

        total = len(db)
        start = (page - 1) * limit
        end = start + limit
        items = db[start:end]

        return jsonify(
            {
                "success": True,
                "items": items,
                "total": total,
                "page": page,
                "limit": limit,
                "pages": (total + limit - 1) // limit,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cost/quote", methods=["POST"])
def cost_quote():
    """印刷报价"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400
    try:
        result = print_cost_estimate(
            width_mm=float(data.get("width", 210)),
            height_mm=float(data.get("height", 297)),
            quantity=int(data.get("qty", 1000)),
            num_colors=int(data.get("colors", 4)),
            paper_gsm=float(data.get("gsm", 120)),
            print_method=data.get("method", "offset"),
        )
        # 映射为前端期望的 USD 命名字段（mcp-print 返回 ink_cost/total_cost/...，无 _usd 后缀）
        payload = {
            "ink_cost_usd": result["ink_cost"],
            "setup_cost_usd": result["setup_cost"],
            "paper_cost_usd": result["paper_cost"],
            "total_cost_usd": result["total_cost"],
            "cost_per_unit_usd": result["cost_per_unit"],
            "currency": result["currency"],
            "breakdown": result["breakdown"],
        }
        return jsonify(
            {
                "success": True,
                "result": payload,
            }
        )
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid input: {e}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/print/export", methods=["POST"])
def export_print():
    """位图 → 生产印刷级 CMYK PDF 下载（export_print SDK 前端入口）"""
    upload, err = _get_uploaded_image()
    if err:
        return err

    image_bytes, image_format = upload
    width_mm = _float_arg(request.form.get("width_mm"), 0)
    height_mm = _float_arg(request.form.get("height_mm"), 0)
    bleed_mm = _float_arg(request.form.get("bleed_mm"), 3.0)
    mode = request.form.get("mode", "color")

    if width_mm <= 0 or height_mm <= 0:
        return jsonify({"error": "width_mm / height_mm 必须大于 0"}), 400
    if bleed_mm < 0:
        return jsonify({"error": "bleed_mm 不能为负"}), 400

    tmp_in, pdf_out = None, None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=f".{image_format}", delete=False
        ) as tmp:
            tmp.write(image_bytes)
            tmp_in = tmp.name

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            pdf_out = tmp.name

        sdk.export_print(
            tmp_in,
            pdf_out,
            width_mm=width_mm,
            height_mm=height_mm,
            bleed_mm=bleed_mm,
            mode=mode,
        )
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if tmp_in and os.path.exists(tmp_in):
            os.unlink(tmp_in)

    with open(pdf_out, "rb") as f:
        pdf_bytes = f.read()
    if os.path.exists(pdf_out):
        os.unlink(pdf_out)

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="colorflow_print.pdf"',
        },
    )


# === API Key 管理 ===


@app.route("/api/keys/generate", methods=["POST"])
def generate_key():
    """生成新 API Key（明文仅返回一次）"""
    data = request.get_json(silent=True) or {}
    name = data.get("name", "")
    entry = keystore.generate(name=name)
    return jsonify({
        "success": True,
        "key": entry["key"],  # 明文，仅此一次
        "key_id": entry["key_id"],  # 非敏感 id，供前端撤销定位
        "name": entry["name"],
        "created_at": entry["created_at"],
    })


@app.route("/api/keys", methods=["GET"])
def list_keys():
    """列出所有 Key（脱敏）"""
    keys = keystore.list_all()
    return jsonify({"success": True, "keys": keys, "count": len(keys)})


@app.route("/api/keys/<path:key_id>", methods=["DELETE"])
def revoke_key(key_id):
    """撤销指定 Key"""
    if keystore.revoke(key_id):
        return jsonify({"success": True, "revoked": key_id[:8] + "****"})
    return jsonify({"error": "Key not found"}), 404


# === Pantone 色卡 / 匹配报告 PDF 导出 ===


# ============================================================
# 3D 灰度图生成（高度图 / 位移贴图）
# ============================================================
#
# 将任意彩色位图转换为 3D 建模用灰度 PNG：
#   - 灰度转换 + 反色（3D 中黑=低/白=高，或反过来）
#   - 对比度增强、Gamma 校正
#   - 高斯模糊平滑
#   - 自动级别（归一化亮度范围）
#   - 8-bit / 16-bit 位深输出（16-bit 精度更高，适合高精度位移贴图）
#   - 直方图数据（前端渲染亮度分布图）
#
# 典型用途：Blender displacement map / Photoshop 深度通道 / 3D 打印模型


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


@app.route("/api/grayscale3d", methods=["POST"])
def grayscale3d_api():
    """位图 → 3D 灰度 PNG（高度图 / 位移贴图）

    Form 参数：
        image              图片文件（PNG/JPG/WebP/BMP，≤10MB）
        invert             1=反色（黑=低 白=高）, 0=正色（默认 0）
        contrast           对比度 0.5-3.0（默认 1.0）
        gamma              Gamma 校正 0.5-2.0（默认 1.0）
        smooth             平滑半径（高斯模糊半径）0-5（默认 0）
        auto_levels        1=自动级别（归一化亮度）, 0=不处理（默认 0）
        bit_depth          输出位深: 8 或 16（默认 8）
    """
    upload, err = _get_uploaded_image()
    if err:
        return err

    image_bytes, _image_format = upload

    invert = request.form.get("invert", "0") in ("1", "true", "yes")
    contrast = _float_arg(request.form.get("contrast"), 1.0)
    contrast = _clamp(contrast, 0.5, 3.0)
    gamma = _float_arg(request.form.get("gamma"), 1.0)
    gamma = _clamp(gamma, 0.5, 2.0)
    smooth = _float_arg(request.form.get("smooth"), 0.0)
    smooth = _clamp(smooth, 0.0, 5.0)
    auto_levels = request.form.get("auto_levels", "0") in ("1", "true", "yes")
    bit_depth = _int_arg(request.form.get("bit_depth"), 8)
    bit_depth = 16 if bit_depth == 16 else 8

    try:
        import io as _bio
        from PIL import Image, ImageOps, ImageEnhance, ImageFilter

        img = Image.open(_bio.BytesIO(image_bytes)).convert("RGB")
        # 1) 灰度转换
        grey = img.convert("L")

        # 2) 高斯模糊平滑（必须先做，避免对模糊后数据做级别归一化影响过大）
        if smooth > 0:
            radius = int(smooth)
            grey = grey.filter(ImageFilter.GaussianBlur(radius=radius))

        # 3) 自动级别：归一化 0-255 全范围（扩大对比度）
        if auto_levels:
            grey = ImageOps.autocontrast(grey)

        # 4) 对比度增强
        if contrast != 1.0:
            grey = ImageEnhance.Contrast(grey).enhance(contrast)

        # 5) Gamma 校正（亮度曲线）
        if gamma != 1.0:
            # PIL 没有 ImageOps.gamma，手动 point 映射
            curve = [int(round(255 * ((p / 255.0) ** (1.0 / gamma)))) for p in range(256)]
            grey = grey.point(curve)

        # 6) 反色（3D 场景：反色后黑=低 / 白=高）
        if invert:
            grey = ImageOps.invert(grey)

        # 7) 位深转换 + 直方图
        histogram_raw = grey.histogram()
        if bit_depth == 16:
            # 8-bit → 16-bit：每通道乘以 257（65535/255 ≈ 257）
            grey = grey.point(lambda p: p * 257).convert("I;16")

        buf = _bio.BytesIO()
        grey.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        # 直方图数据：256 个 bin，归一化为 0-1 浮点
        hist_bins = histogram_raw[:256] if len(histogram_raw) >= 256 else histogram_raw
        hist_total = sum(hist_bins) or 1
        hist_norm = [v / hist_total for v in hist_bins]
        # 找到最高 bin 索引
        hist_peak = max(range(len(hist_bins)), key=lambda i: hist_bins[i])

        return jsonify({
            "success": True,
            "png_base64": base64.b64encode(png_bytes).decode("utf-8"),
            "size": len(png_bytes),
            "width": grey.width,
            "height": grey.height,
            "bit_depth": bit_depth,
            "histogram": hist_norm,
            "hist_peak": hist_peak,
            "min_value": min(hist_bins),
            "max_value": max(hist_bins),
        })
    except Exception as e:
        return jsonify({"error": f"灰度图生成失败: {e}"}), 500


@app.route("/api/pantone/export", methods=["POST"])
def pantone_export_pdf():
    """生成色卡 / 匹配报告 / 主色提取报告 PDF（CMYK，印刷级）

    请求体 JSON:
      type: "swatch" (单个色卡) | "report" (匹配报告) | "palette" (主色提取报告)
      色卡模式: {type, name, hex, cmyk: [c,m,y,k], rgb: [r,g,b]}
      报告模式: {type, input_hex, matches: [{name, hex, cmyk, rgb, delta_e}]}
      主色报告模式: {type, svg_base64, palette: [{color:{hex,rgb,share}, pantone_matches:[...]}]}
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    export_type = data.get("type", "swatch")
    try:
        from services.color_pdf import render_pantone_pdf
        pdf_bytes = render_pantone_pdf(export_type, data)
        filename = "colorflow_swatch.pdf"
        if export_type == "palette":
            filename = "colorflow_palette_report.pdf"
        elif export_type == "report":
            filename = "colorflow_match_report.pdf"
        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="{}"'.format(filename)},
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
# ============================================================
# 服务重启
# ============================================================


def _find_restart_script():
    """定位 restart.ps1，优先用当前文件所在目录"""
    import pathlib

    here = pathlib.Path(__file__).resolve().parent
    ps1 = here / "restart.ps1"
    if ps1.exists():
        return str(ps1)
    # fallback: cwd
    cwd_ps1 = pathlib.Path("restart.ps1")
    if cwd_ps1.exists():
        return str(cwd_ps1)
    return None


@app.route("/api/restart", methods=["POST"])
def restart_service():
    """触发服务重启：异步启动 restart.ps1，杀掉旧进程后拉起新实例"""
    ps1 = _find_restart_script()
    if not ps1:
        return jsonify({"error": "restart.ps1 脚本未找到"}), 404

    try:
        import subprocess

        # 用 powershell 启动脚本，detached 模式（不阻塞 Flask 响应）
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1],
            creationflags=subprocess.CREATE_NO_WINDOW,
            cwd=os.path.dirname(ps1),
        )
        return jsonify({
            "success": True,
            "message": "重启已触发，服务将在 2 秒内恢复。",
        })
    except Exception as e:
        return jsonify({"error": f"重启失败: {e}"}), 500


# ============================================================
# AI 生图（GEN 适配器层 · Phase 1 同步版）
# ============================================================
#
# 见《ColorFlow 开发文档 02 · 生图适配器（GEN · 路线 A）》。
# 零本地 GPU：调用云端图像大模型 API，本地仅做 Pillow 格式转码。
# 失败可降级：backend=auto 时按 volcano → fal → comfyui 优先级探测，
# retryable 失败自动降级到下一后端，绝不假成功。


def _gen_error_response(e: GenGenError):
    """GenError → HTTP 响应，沿用现有错误码体系 + 文档 02 §4.1 补充"""
    code_map = {
        "bad_prompt": (400, "生成描述无效"),
        "auth": (401, "GEN not configured"),
        "quota": (402, "后端额度不足"),
        "timeout": (504, "生成超时"),
        "rate_limit": (429, "请求过频"),
        "upstream": (500, "上游生成失败"),
    }
    status, label = code_map.get(e.code, (500, "生成失败"))
    return jsonify({
        "error": f"{label}: {e}",
        "code": e.code,
        "retryable": e.retryable,
    }), status


def _gen_form_params():
    """从 multipart form 读取生图参数。

    Returns:
        (params_dict, None) 成功；或 (None, (error_response, status)) 失败。
    """
    prompt = (request.form.get("prompt", "") or "").strip()
    if not prompt:
        return None, (jsonify({"error": "prompt 不能为空"}), 400)

    backend = (request.form.get("backend", "auto") or "auto").strip()
    size = (request.form.get("size", "1024x1024") or "1024x1024").strip()
    try:
        n = max(1, min(int(request.form.get("n", "1") or "1"), 4))
    except (TypeError, ValueError):
        n = 1
    model = (request.form.get("model", "") or "").strip()

    ref_bytes = None
    if "ref_image" in request.files and request.files["ref_image"].filename:
        rf = request.files["ref_image"]
        ctype = rf.content_type or "image/png"
        if ctype not in ALLOWED_CONTENT_TYPES:
            return None, (jsonify({"error": f"参考图类型不支持: {ctype}"}), 415)
        ref_bytes = rf.read()

    return {"prompt": prompt, "backend": backend, "size": size, "n": n,
            "model": model, "ref_image": ref_bytes}, None


def _gen_results_to_images(results):
    """GenResult 列表 → 前端期望的 images 结构（base64）"""
    images = []
    for r in results:
        images.append({
            "png_base64": base64.b64encode(r.png_bytes).decode("utf-8"),
            "width": r.width,
            "height": r.height,
            "backend": r.backend,
            "model": r.model,
            "meta": r.meta,
        })
    return images


# ============================================================
# 异步任务模式（Phase 2）
# ============================================================
#
# 生图耗时 10–60s，同步请求易撞网关超时。任务模式参考 ComfyUI
# /prompt + /history 设计：提交即返回 job_id，前端轮询 GET 取状态。
#
# 存储：进程内 dict + 锁（单进程 Flask 适用）。多 worker 生产部署
# （gunicorn -w N）需换共享存储（Redis/DB），此处不做，保持极简。
# job_id 为 uuid4 不透明串，不暴露任何生成参数。

_JOBS = {}
_JOBS_LOCK = threading.Lock()
_JOB_TTL = 600          # 任务保留 10 分钟
_JOB_PROGRESS_MSG = "生成中，通常 10–60 秒…"


def _prune_jobs_locked():
    """清理过期任务（调用方需持 _JOBS_LOCK）"""
    now = time.time()
    dead = [jid for jid, job in _JOBS.items() if now - job["created_at"] > _JOB_TTL]
    for jid in dead:
        _JOBS.pop(jid, None)


def _gen_job_worker(job_id, params):
    """后台线程：执行生图并更新任务状态。

    任何异常都落为 failed 并记录 code/retryable，绝不假成功。
    """
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job["status"] = "running"
        job["progress"] = _JOB_PROGRESS_MSG

    t0 = time.time()
    try:
        results = gen_dispatch(
            params["prompt"], ref_image=params["ref_image"],
            backend=params["backend"], size=params["size"],
            n=params["n"], model=params["model"],
        )
        images = _gen_results_to_images(results)
        with _JOBS_LOCK:
            job["status"] = "done"
            job["progress"] = "完成"
            job["images"] = images
            job["count"] = len(images)
            job["elapsed_ms"] = int((time.time() - t0) * 1000)
            job["finished_at"] = time.time()
    except GenGenError as e:
        with _JOBS_LOCK:
            job["status"] = "failed"
            job["progress"] = "失败"
            job["error"] = str(e)
            job["code"] = e.code
            job["retryable"] = e.retryable
            job["elapsed_ms"] = int((time.time() - t0) * 1000)
            job["finished_at"] = time.time()
    except Exception as e:
        logger.exception("gen_job_worker 生图失败")
        with _JOBS_LOCK:
            job["status"] = "failed"
            job["progress"] = "失败"
            job["error"] = f"生图失败: {e}"
            job["code"] = "upstream"
            job["retryable"] = True
            job["elapsed_ms"] = int((time.time() - t0) * 1000)
            job["finished_at"] = time.time()


@app.route("/api/generate/backends", methods=["GET"])
def gen_backends_status():
    """返回已配置的生图后端状态（Key 不回显，仅 available 标志）"""
    avail = available_backends()
    all_backends = [
        {"id": "volcano", "label": "火山方舟 · 即梦 Seedream（国内默认）",
         "available": "volcano" in avail},
        {"id": "fal", "label": "fal.ai（海外 · 模型最全）",
         "available": "fal" in avail},
        {"id": "comfyui", "label": "本地 ComfyUI（可选装）",
         "available": "comfyui" in avail},
    ]
    default = os.getenv("GEN_DEFAULT_BACKEND", "auto")
    return jsonify({
        "success": True,
        "backends": all_backends,
        "any_configured": len(avail) > 0,
        "default_backend": default,
    })


@app.route("/api/generate", methods=["POST"])
def generate_image_api():
    """AI 生图（同步版，Phase 1）：prompt → 云端图像大模型 → PNG（base64）

    Form 参数（multipart/form-data，与 /api/trace 风格一致）：
        prompt      生图描述（必填，中文/英文均可）
        backend     auto / volcano / fal / comfyui（默认 auto）
        ref_image   参考图（可选，图生图）PNG/JPG/WebP/BMP
        size        输出尺寸，如 1024x1024（默认 1024x1024）
        n           生成张数 1-4（默认 1）
        model       覆盖模型名（可选）
    """
    params, err = _gen_form_params()
    if err:
        return err
    try:
        t0 = time.time()
        results = gen_dispatch(
            params["prompt"], ref_image=params["ref_image"],
            backend=params["backend"], size=params["size"],
            n=params["n"], model=params["model"],
        )
        images = _gen_results_to_images(results)
        return jsonify({
            "success": True,
            "images": images,
            "count": len(images),
            "elapsed_ms": int((time.time() - t0) * 1000),
        })
    except GenGenError as e:
        return _gen_error_response(e)
    except Exception as e:
        logger.exception("generate_image_api 生图失败")
        return jsonify({"error": f"生图失败: {e}"}), 500


@app.route("/api/generate/jobs", methods=["POST"])
def gen_jobs_create():
    """提交异步生图任务（Phase 2）。提交即返回 job_id，不阻塞。

    Form 参数与 /api/generate 一致。
    Returns:
        {success, job_id, status: "queued"}
    """
    params, err = _gen_form_params()
    if err:
        return err

    job_id = uuid.uuid4().hex
    now = time.time()
    with _JOBS_LOCK:
        _prune_jobs_locked()
        _JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "progress": "排队中…",
            "created_at": now,
        }

    threading.Thread(target=_gen_job_worker, args=(job_id, params), daemon=True).start()
    return jsonify({"success": True, "job_id": job_id, "status": "queued"})


@app.route("/api/generate/jobs/<job_id>", methods=["GET"])
def gen_jobs_get(job_id):
    """查询异步生图任务状态。

    status: queued / running / done / failed
      - done: 携带 images（与 /api/generate 一致）+ count + elapsed_ms
      - failed: 携带 error + code + retryable
    """
    with _JOBS_LOCK:
        _prune_jobs_locked()
        job = _JOBS.get(job_id)
        if not job:
            return jsonify({"error": "任务不存在或已过期", "status": "not_found"}), 404
        # 构造快照（避免前端持有活引用）
        snap = {k: v for k, v in job.items()}
    return jsonify(snap)


# ============================================================
# VISION 图→prompt（Phase 3 · image2prompt 反向闭环）
# ============================================================
#
# 与 /api/generate（prompt→图）对称：上传一张图 → 多模态大模型描述 → 返回
# 结构化英文 prompt，前端可直接回填到 GEN 提示词框，完成「图→prompt→生图→
# 描图→Pantone→报价」全闭环（见 docs/03-工作流集成方案.md 方案 B）。
#
# 后端：vision_backends.dispatch_prompt（openai / claude / mock，auto 降级）

def _vision_error_response(e):
    """Vision 错误 → HTTP 响应（与 _gen_error_response 风格一致）"""
    code_map = {
        "auth": (401, "未配置 Vision 后端 Key"),
        "quota": (402, "Vision 后端额度不足"),
        "timeout": (504, "Vision 后端超时"),
        "rate_limit": (429, "Vision 后端限流"),
        "bad_image": (400, "图像无效"),
        "upstream": (500, "Vision 上游失败"),
    }
    status, label = code_map.get(e.code, (500, "Vision 失败"))
    return jsonify({"error": f"{label}: {e}", "code": e.code, "retryable": e.retryable}), status


@app.route("/api/prompt/backends", methods=["GET"])
def vision_backends_status():
    """返回已配置的 Vision（图→prompt）后端状态；Key 不回显，仅 available 标志。"""
    avail = vision_available_backends()
    all_backends = [
        {"id": "openai", "label": "OpenAI · gpt-4o（VLM 默认）",
         "available": "openai" in avail},
        {"id": "claude", "label": "Anthropic · Claude（备选）",
         "available": "claude" in avail},
        {"id": "mock", "label": "本地 mock（零 Key 演示/测试）",
         "available": "mock" in avail},
    ]
    default = os.getenv("VISION_DEFAULT_BACKEND", "auto")
    any_real = any(b["available"] for b in all_backends if b["id"] != "mock")
    return jsonify({
        "success": True,
        "backends": all_backends,
        "any_configured": any_real,
        "default_backend": default,
    })


@app.route("/api/prompt/generate", methods=["POST"])
def generate_prompt_api():
    """图→prompt：上传图像 → 多模态大模型描述 → 返回英文 prompt（image2prompt）。

    Form 参数（multipart/form-data）：
        image   图像文件（必填）PNG/JPG/WebP/BMP
        backend auto / openai / claude / mock（默认 auto）
        lang    输出语言 en / zh（默认 en）
        style   风格提示 product / poster / packaging 等（默认 product）
        model   覆盖模型名（可选）

    返回：{success, prompt, backend, model, elapsed_ms, meta}
    """
    if "image" not in request.files:
        return jsonify({"error": "未提供图像文件（image）"}), 400
    f = request.files["image"]
    if not f.filename:
        return jsonify({"error": "图像文件名为空"}), 400
    ctype = f.content_type or "image/png"
    if ctype not in ALLOWED_CONTENT_TYPES:
        return jsonify({"error": f"图像类型不支持: {ctype}"}), 415
    image_bytes = f.read()

    backend = (request.form.get("backend", "auto") or "auto").strip()
    lang = (request.form.get("lang", "en") or "en").strip()
    style = (request.form.get("style", "product") or "product").strip()
    model = (request.form.get("model", "") or "").strip()

    try:
        t0 = time.time()
        result = dispatch_prompt(image_bytes, backend=backend, lang=lang,
                                 style=style, model=model, timeout=120)
        return jsonify({
            "success": True,
            "prompt": result.prompt,
            "backend": result.backend,
            "model": result.model,
            "elapsed_ms": int((time.time() - t0) * 1000),
            "meta": result.meta,
        })
    except GenPromptError as e:
        return _vision_error_response(e)
    except Exception as e:
        logger.exception("generate_prompt_api 图→prompt 失败")
        return jsonify({"error": f"图→prompt 失败: {e}"}), 500


# ============================================================
# Prompt 模板库（Phase 4 · 行业预制 prompt → GEN）
# ============================================================
#
# 模板文件 assets/prompt_templates.json 按 category 分组，每个模板含
# {placeholder} 占位符和 params 定义。前端下拉选模板 → 填参数 → 渲染 →
# 回填 GEN 提示词框 → 生图。对应 docs/03 P2「Prompt 模板库」。
#
# 渲染逻辑在 prompt_templates.py（纯 CPU 字符串替换，零延迟，零网络）。

@app.route("/api/prompt-templates", methods=["GET"])
def prompt_templates_list():
    """列出所有模板（按 category 分组），支持 search 过滤。

    Query:
        category: 按分类过滤（luxury / food / beauty / electronics / stationery / promotional）
        search:   模糊搜索模板名/描述
    """
    from prompt_templates import list_categories, list_templates
    category = request.args.get("category", "").strip() or None
    search = request.args.get("search", "").strip() or None
    try:
        cats = list_categories()
        tpls = list_templates(category=category, search=search)
        return jsonify({"success": True, "categories": cats, "templates": tpls,
                        "count": len(tpls)})
    except Exception as e:
        logger.exception("prompt_templates_list 失败")
        return jsonify({"error": str(e)}), 500


@app.route("/api/prompt-templates/<template_id>", methods=["GET"])
def prompt_template_detail(template_id):
    """获取单个模板完整定义（含 prompt 原文和 params 定义）"""
    from prompt_templates import get_template, TemplateError
    try:
        t = get_template(template_id)
        return jsonify({"success": True, "template": t})
    except TemplateError as e:
        status = 404 if e.code == "not_found" else 500
        return jsonify({"error": str(e), "code": e.code}), status
    except Exception as e:
        logger.exception("prompt_template_detail 失败")
        return jsonify({"error": str(e)}), 500


@app.route("/api/prompt-templates/render", methods=["POST"])
def prompt_template_render():
    """渲染模板 → 完整 prompt。

    Form/JSON:
        template_id: 模板 id（必填）
        params:     {param_name: value}（可选，缺失用默认值）
    """
    from prompt_templates import render as tpl_render, TemplateError
    # 支持 JSON 和 form 两种提交方式
    if request.is_json:
        template_id = (request.json.get("template_id", "") or "").strip()
        params = request.json.get("params", {}) or {}
    else:
        template_id = (request.form.get("template_id", "") or "").strip()
        params = {}
        for k, v in request.form.items():
            if k.startswith("param_"):
                params[k[6:]] = v

    if not template_id:
        return jsonify({"error": "template_id 不能为空"}), 400
    try:
        result = tpl_render(template_id, params)
        return jsonify({"success": True, **result})
    except TemplateError as e:
        status = 404 if e.code == "not_found" else 400
        return jsonify({"error": str(e), "code": e.code}), status
    except Exception as e:
        logger.exception("prompt_template_render 失败")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )
