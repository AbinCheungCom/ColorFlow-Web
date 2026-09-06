"""ColorFlow MCP Server — 让 AI Agent 直接调用描图 / 抠图 / Pantone 匹配 / 印刷报价。

运行方式：
    mcp run mcp_server.py            # 或
    python mcp_server.py

接入 Claude Code（~/.claude.json 或项目 .mcp.json）：
    "mcpServers": {
        "colorflow": {
            "command": "python",
            "args": ["/path/to/mcp_server.py"],
            "env": { "COLORFLOW_API_KEY": "cf_sk_xxx" }
        }
    }
"""

import json
import os

from fastmcp import FastMCP

from colorflow_sdk import extract_svg_colors
from mcp_print.tools.colors import (
    _cmyk_to_lab,
    _hex_to_rgb,
    _rgb_to_lab,
    pantone_search,
    pantone_to_cmyk,
)
from mcp_print.tools.cost import print_cost_estimate

# 复用 Web 应用中的 SDK 实例（同一份 VTracer 输出目录等）
from app import sdk

# API Key 校验（与 Web API 共用同一份 KeyStore）
from colorflow_keys import keystore

from services.color_delta_e import delta_e_cie76

from gen_backends import dispatch as gen_dispatch, GenError as GenGenError
from vision_backends import dispatch_prompt, PromptError as GenPromptError

mcp = FastMCP("ColorFlow")


def _auth_check() -> str | None:
    """校验 API Key：有 Key 但未配置 → 返回错误 JSON；无 Key → 放行（本地开发）

    每次调用时动态读取 COLORFLOW_API_KEY 环境变量，
    确保 Agent 启动后通过 env 注入的 key 能即时生效。
    """
    if not keystore.has_any():
        return None  # 无任何 key → 本地开发模式，放行
    api_key = os.getenv("COLORFLOW_API_KEY", "").strip()
    if not api_key:
        return json.dumps(
            {"error": "未配置 API Key。请在设置页生成 Key 后，通过 COLORFLOW_API_KEY 环境变量传入。"},
            ensure_ascii=False,
        )
    if not keystore.verify(api_key):
        return json.dumps(
            {"error": "API Key 无效或已撤销。请在设置页重新生成。"},
            ensure_ascii=False,
        )
    return None


# 允许的图片扩展名
ALLOWED_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
# 可用抠图模型清单
REMBG_MODELS = ("silueta", "u2net", "u2net_human_seg", "u2netp", "dis_anime",
                "dis_general_use", "withoutbg", "bria-rmbg")


def _delta_e(hex_color: str, cmyk) -> float:
    """计算 HEX 与某 CMYK 色之间的 ΔE（CIELAB 欧氏距离近似）"""
    lab_hex = _rgb_to_lab(*_hex_to_rgb(hex_color))
    lab_pantone = _cmyk_to_lab(*cmyk)
    return delta_e_cie76(lab_hex, lab_pantone)


def _check_ext(image_path: str) -> str | None:
    """校验文件扩展名，非法返回错误 JSON"""
    if not image_path or not image_path.lower().endswith(ALLOWED_EXT):
        return json.dumps(
            {"error": f"不支持的文件类型，允许: {', '.join(ALLOWED_EXT)}"},
            ensure_ascii=False,
        )
    return None


# 合法枚举值（与 Web API _trace_parameters() 保持一致）
_VALID_COLORMODES = ("rgb8", "rgb16", "mono", "grey", "grey16")
_VALID_HIERARCHICAL = ("flat", "stacked")


def _sanitize_trace_params(kwargs: dict) -> dict:
    """校验描图参数，非法值回退默认（与 Web API 行为一致）"""
    cm = kwargs.get("colormode", "rgb8")
    if cm not in _VALID_COLORMODES:
        kwargs["colormode"] = "rgb8"
    hi = kwargs.get("hierarchical", "stacked")
    if hi not in _VALID_HIERARCHICAL:
        kwargs["hierarchical"] = "stacked"
    return kwargs


# ============================================================
# 位图 → SVG 矢量描图
# ============================================================


@mcp.tool()
def trace_image(
    image_path: str,
    mode: str = "color",
    colormode: str = "rgb8",
    hierarchical: str = "stacked",
    filter_speckle: int = 4,
    color_precision: int = 6,
    layer_difference: int = 64,
    corner_threshold: int = 60,
    length_threshold: float = 2.0,
    path_precision: int = 7,
) -> str:
    """将位图（PNG/JPG/WebP/BMP）转换为 SVG 矢量图。

    Args:
        image_path: 图片文件路径
        mode: 描图模式 — color（彩色）| grey（灰度）| human（人像）
        colormode: 颜色深度 — rgb8（默认）| rgb16 | mono（二值化）| grey | grey16
        hierarchical: 输出层级 — stacked（堆叠）| flat（平面化）
        filter_speckle: 斑点过滤阈值（1-100），越大过滤越多
        color_precision: 颜色精度（1-16）
        layer_difference: 图层距离阈值（1-256）
        corner_threshold: 角点阈值（1-180）
        length_threshold: 路径最短长度（0.1-100），越大过滤越多短路径
        path_precision: 路径精度（1-16），越高质量越高
    Returns:
        JSON: {success, svg_path}
    """
    auth = _auth_check()
    if auth:
        return auth
    err = _check_ext(image_path)
    if err:
        return err
    p = _sanitize_trace_params({
        "mode": mode, "colormode": colormode, "hierarchical": hierarchical,
        "filter_speckle": filter_speckle, "color_precision": color_precision,
        "layer_difference": layer_difference, "corner_threshold": corner_threshold,
        "length_threshold": length_threshold, "path_precision": path_precision,
    })
    try:
        svg_path = sdk.trace(image_path, **p)
        return json.dumps({"success": True, "svg_path": svg_path}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"描图失败: {e}"}, ensure_ascii=False)


# ============================================================
# 位图抠图
# ============================================================


@mcp.tool()
def cutout(
    image_path: str,
    model: str = "silueta",
    alpha_matting: bool = False,
    alpha_matting_foreground_threshold: int = 240,
    alpha_matting_background_threshold: int = 10,
    alpha_matting_erode_size: int = 10,
) -> str:
    """AI 抠图：移除背景，输出透明底 PNG。

    Args:
        image_path: 图片文件路径
        model: 抠图模型 — silueta（默认，快速）| u2net | u2net_human_seg | u2netp
               | dis_anime | dis_general_use | withoutbg | bria-rmbg
        alpha_matting: 启用 alpha matting 边缘细化（发丝/半透明场景建议开启）
        alpha_matting_foreground_threshold: 前景阈值（10-255，默认 240）
        alpha_matting_background_threshold: 背景阈值（0-245，默认 10）
        alpha_matting_erode_size: 边缘腐蚀尺寸（1-20，默认 10）
    Returns:
        JSON: {success, png_path, width, height}
    """
    auth = _auth_check()
    if auth:
        return auth
    err = _check_ext(image_path)
    if err:
        return err
    if model not in REMBG_MODELS:
        model = "silueta"
    try:
        png_path = sdk.cutout(
            image_path,
            model=model,
            alpha_matting=alpha_matting,
            alpha_matting_foreground_threshold=alpha_matting_foreground_threshold,
            alpha_matting_background_threshold=alpha_matting_background_threshold,
            alpha_matting_erode_size=alpha_matting_erode_size,
        )
        # 读取图片尺寸
        from PIL import Image
        with Image.open(png_path) as img:
            w, h = img.size
        return json.dumps(
            {"success": True, "png_path": png_path, "width": w, "height": h},
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"error": f"抠图失败: {e}"}, ensure_ascii=False)


# ============================================================
# 抠图 + 描图 一键串联
# ============================================================


@mcp.tool()
def cutout_then_trace(
    image_path: str,
    model: str = "silueta",
    alpha_matting: bool = False,
    trace_mode: str = "color",
    colormode: str = "rgb8",
    hierarchical: str = "stacked",
    filter_speckle: int = 4,
    color_precision: int = 6,
    layer_difference: int = 64,
    corner_threshold: int = 60,
    length_threshold: float = 2.0,
    path_precision: int = 7,
) -> str:
    """一键抠图 + 描图：先移除背景，再合成白底后描图，输出透明底 SVG。

    Args:
        image_path: 图片文件路径
        model: 抠图模型 — silueta（默认）| u2net | ...
        alpha_matting: 抠图时启用 alpha matting 边缘细化
        trace_mode: 描图模式 — color（默认）| grey | human
        colormode: 颜色深度 — rgb8（默认）| rgb16 | mono | grey | grey16
        hierarchical: 输出层级 — stacked（默认）| flat
        filter_speckle: 斑点过滤（1-100，默认 4）
        color_precision: 颜色精度（1-16，默认 6）
        layer_difference: 图层距离（1-256，默认 64）
        corner_threshold: 角点阈值（1-180，默认 60）
        length_threshold: 路径最短长度（0.1-100，默认 2.0）
        path_precision: 路径精度（1-16，默认 7）
    Returns:
        JSON: {success, svg_path}
    """
    auth = _auth_check()
    if auth:
        return auth
    err = _check_ext(image_path)
    if err:
        return err
    if model not in REMBG_MODELS:
        model = "silueta"
    p = _sanitize_trace_params({
        "colormode": colormode, "hierarchical": hierarchical,
        "filter_speckle": filter_speckle, "color_precision": color_precision,
        "layer_difference": layer_difference, "corner_threshold": corner_threshold,
        "length_threshold": length_threshold, "path_precision": path_precision,
    })
    try:
        svg_path = sdk.cutout_then_trace(
            image_path,
            model=model,
            alpha_matting=alpha_matting,
            mode=trace_mode,
            **p,
        )
        return json.dumps({"success": True, "svg_path": svg_path}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"抠图+描图失败: {e}"}, ensure_ascii=False)


# ============================================================
# Pantone 色彩匹配
# ============================================================


@mcp.tool()
def match_pantone(hex_color: str) -> str:
    """根据 HEX 颜色匹配最近的 5 个 Pantone 色（含 ΔE、CMYK、RGB）。

    Args:
        hex_color: HEX 颜色，如 "#DA291C" 或 "DA291C"
    Returns:
        JSON: {success, matches: [{name, hex, cmyk, rgb, delta_e, interpretation}]}
    """
    auth = _auth_check()
    if auth:
        return auth
    if not hex_color.startswith("#"):
        hex_color = "#" + hex_color
    if len(hex_color) != 7:
        return json.dumps({"error": "HEX 格式应为 #RRGGBB"}, ensure_ascii=False)
    # 校验合法十六进制字符，避免下游 _hex_to_rgb 崩溃
    try:
        int(hex_color[1:], 16)
    except ValueError:
        return json.dumps({"error": "HEX 格式应为 #RRGGBB，包含非法字符"}, ensure_ascii=False)

    from services.color_match import match as pantone_match

    matches = pantone_match(hex_color)
    return json.dumps({"success": True, "hex": hex_color, "matches": matches}, ensure_ascii=False)


@mcp.tool()
def pantone_lookup(name: str) -> str:
    """按 Pantone 色号精确查询（如 "485C" / "180 C" / "Warm Red"）。

    Args:
        name: Pantone 色号
    Returns:
        JSON: {success, result: {name, hex, c, m, y, k, rgb}}
    """
    auth = _auth_check()
    if auth:
        return auth
    if not name.strip():
        return json.dumps({"error": "请提供色号"}, ensure_ascii=False)
    try:
        result = pantone_to_cmyk(name.strip())
        return json.dumps({"success": True, "result": result}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"查询失败: {e}"}, ensure_ascii=False)


@mcp.tool()
def pantone_colors(
    page: int = 1,
    limit: int = 50,
    search: str = "",
) -> str:
    """获取 Pantone 色库列表（分页 + 搜索）。

    Args:
        page: 页码（从 1 开始）
        limit: 每页数量（1-200，默认 50）
        search: 搜索关键词（按色名模糊匹配，留空返回全部）
    Returns:
        JSON: {success, items: [{name, hex, c, m, y, k, ...}], total, page, pages}
    """
    auth = _auth_check()
    if auth:
        return auth
    page = max(page, 1)
    limit = min(max(limit, 1), 200)
    try:
        from services.color_list import list_colors as color_list_svc
        result = color_list_svc(page=page, limit=limit, search=search)
        return json.dumps({"success": True, **result}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"查询失败: {e}"}, ensure_ascii=False)


# ============================================================
# 印刷报价
# ============================================================


@mcp.tool()
def quote_print(
    width_mm: float,
    height_mm: float,
    qty: int,
    colors: int = 4,
    gsm: float = 120,
    method: str = "offset",
) -> str:
    """计算印刷报价（油墨 + 版材 + 调机 + 印刷全链路成本）。

    Args:
        width_mm: 成品宽（毫米）
        height_mm: 成品高（毫米）
        qty: 印刷数量
        colors: 颜色数
        gsm: 纸张克重
        method: offset（胶印）| flexo（柔版）| gravure（凹版）| screen（丝网）| digital（数码）
    Returns:
        JSON: {success, result: {ink_cost_usd, setup_cost_usd, total_cost_usd,
               cost_per_unit_usd, currency, breakdown}}
    """
    auth = _auth_check()
    if auth:
        return auth
    from services.cost import quote as cost_quote_svc
    try:
        payload = cost_quote_svc(
            width_mm=width_mm,
            height_mm=height_mm,
            quantity=qty,
            num_colors=colors,
            paper_gsm=gsm,
            print_method=method,
        )
    except Exception as e:
        return json.dumps({"error": f"报价失败: {e}"}, ensure_ascii=False)
    return json.dumps({"success": True, "result": payload}, ensure_ascii=False)


# ============================================================
# 印刷 PDF 导出
# ============================================================


@mcp.tool()
def export_print(
    image_path: str,
    width_mm: float,
    height_mm: float,
    bleed_mm: float = 3.0,
    mode: str = "color",
    path_precision: int = 10,
    filter_speckle: int = 4,
) -> str:
    """位图 → 生产印刷级 CMYK PDF（含出血 + 物理尺寸）。

    Args:
        image_path: 图片文件路径
        width_mm: 成品宽（毫米）
        height_mm: 成品高（毫米）
        bleed_mm: 出血（毫米，默认 3）
        mode: color | grey | human
        path_precision: 路径精度（印刷级建议 10，默认 10）
        filter_speckle: 斑点过滤（1-100，默认 4）
    Returns:
        JSON: {success, pdf_path}
    """
    auth = _auth_check()
    if auth:
        return auth
    err = _check_ext(image_path)
    if err:
        return err
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        pdf_path = tmp.name
    try:
        sdk.export_print(
            image_path,
            pdf_path,
            width_mm=width_mm,
            height_mm=height_mm,
            bleed_mm=bleed_mm,
            mode=mode,
            path_precision=path_precision,
            filter_speckle=filter_speckle,
        )
        return json.dumps({"success": True, "pdf_path": pdf_path}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"导出失败: {e}"}, ensure_ascii=False)


# ============================================================
# 一键流水线：描图 → 主色 → Pantone 匹配
# ============================================================


@mcp.tool()
def trace_and_match(
    image_path: str,
    mode: str = "color",
    colormode: str = "rgb8",
    hierarchical: str = "stacked",
    filter_speckle: int = 4,
    color_precision: int = 6,
    layer_difference: int = 64,
    corner_threshold: int = 60,
    length_threshold: float = 2.0,
    path_precision: int = 7,
) -> str:
    """一键流水线：位图 → SVG → 提取主色 → 每个主色匹配 Pantone（含 ΔE）。

    Args:
        image_path: 图片文件路径
        mode: 描图模式 — color（默认）| grey | human
        colormode: 颜色深度 — rgb8（默认）| rgb16 | mono | grey | grey16
        hierarchical: 输出层级 — stacked（默认）| flat
        filter_speckle: 斑点过滤（1-100，默认 4）
        color_precision: 颜色精度（1-16，默认 6）
        layer_difference: 图层距离（1-256，默认 64）
        corner_threshold: 角点阈值（1-180，默认 60）
        length_threshold: 路径最短长度（0.1-100，默认 2.0）
        path_precision: 路径精度（1-16，默认 7）
    Returns:
        JSON: {success, svg_path, color_count, palette: [{color, pantone_matches}]}
    """
    auth = _auth_check()
    if auth:
        return auth
    err = _check_ext(image_path)
    if err:
        return err
    p = _sanitize_trace_params({
        "mode": mode, "colormode": colormode, "hierarchical": hierarchical,
        "filter_speckle": filter_speckle, "color_precision": color_precision,
        "layer_difference": layer_difference, "corner_threshold": corner_threshold,
        "length_threshold": length_threshold, "path_precision": path_precision,
    })
    try:
        svg_path = sdk.trace(image_path, **p)
    except Exception as e:
        return json.dumps({"error": f"描图失败: {e}"}, ensure_ascii=False)

    with open(svg_path, "rb") as f:
        svg_bytes = f.read()

    from services.pipeline import build_palette
    palette = build_palette(svg_bytes, top_n=5)

    return json.dumps(
        {
            "success": True,
            "svg_path": svg_path,
            "color_count": len(palette),
            "palette": palette,
        },
        ensure_ascii=False,
    )


# ============================================================
# 3D 灰度图（高度图 / 位移贴图）
# ============================================================


@mcp.tool()
def greyscale3d(
    image_path: str,
    invert: bool = False,
    contrast: float = 1.0,
    gamma: float = 1.0,
    smooth: float = 0.0,
    auto_levels: bool = False,
    bit_depth: int = 8,
) -> str:
    """将彩色位图转换为 3D 建模用灰度 PNG（高度图 / 位移贴图）。

    Args:
        image_path: 图片文件路径（PNG/JPG/WebP/BMP）
        invert: 是否反色 — True=黑=低/白=高（适合 3D displacement）, False=正色（默认 False）
        contrast: 对比度增强 0.5-3.0（默认 1.0）
        gamma: Gamma 校正 0.5-2.0（默认 1.0）
        smooth: 高斯模糊平滑半径 0-5（默认 0）
        auto_levels: 自动级别归一化亮度范围（默认 False）
        bit_depth: 输出位深 8 或 16（默认 8）
    Returns:
        JSON: {success, png_path, width, height, bit_depth}
    """
    auth = _auth_check()
    if auth:
        return auth
    err = _check_ext(image_path)
    if err:
        return err

    contrast = max(0.5, min(3.0, contrast))
    gamma = max(0.5, min(2.0, gamma))
    smooth = max(0.0, min(5.0, smooth))
    bit_depth = 16 if bit_depth == 16 else 8

    try:
        from services.grayscale3d import generate as grey3d_generate
        import tempfile

        with open(image_path, "rb") as f:
            image_bytes = f.read()

        result = grey3d_generate(
            image_bytes=image_bytes,
            invert=invert,
            contrast=contrast,
            gamma=gamma,
            smooth=smooth,
            auto_levels=auto_levels,
            bit_depth=bit_depth,
            include_histogram=False,
        )

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            png_path = tmp.name
        with open(png_path, "wb") as f:
            f.write(result.png_bytes)

        return json.dumps(
            {
                "success": True,
                "png_path": png_path,
                "width": result.width,
                "height": result.height,
                "bit_depth": result.bit_depth,
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"error": f"灰度图生成失败: {e}"}, ensure_ascii=False)


# ============================================================
# Pantone 色卡 / 匹配报告 PDF 导出
# ============================================================


@mcp.tool()
def export_pantone_pdf(
    export_type: str = "swatch",
    name: str = "",
    hex_color: str = "#000000",
    cmyk: list = None,
    rgb: list = None,
    input_hex: str = "",
    matches: list = None,
    svg_base64: str = "",
    palette: list = None,
) -> str:
    """生成 Pantone 色卡 / 匹配报告 / 主色提取报告 PDF（CMYK，印刷级）。

    Args:
        export_type: 导出类型 — swatch（单个色卡）| report（匹配报告）| palette（主色提取报告）
        name: 色卡模式下的 Pantone 色号名称
        hex_color: 色卡模式下的 HEX 值（如 "#DA291C"）
        cmyk: 色卡模式下的 CMYK 值 [c, m, y, k]
        rgb: 色卡模式下的 RGB 值 [r, g, b]
        input_hex: 报告模式下的输入色 HEX
        matches: 报告模式下的匹配列表 [{name, hex, cmyk, delta_e}]
        svg_base64: 主色报告模式下的描图 SVG（base64）
        palette: 主色报告模式下的主色列表 [{color:{hex,rgb,share}, pantone_matches:[{name,hex,cmyk,delta_e}]}]
    Returns:
        JSON: {success, pdf_path}
    """
    auth = _auth_check()
    if auth:
        return auth
    if cmyk is None:
        cmyk = [0, 0, 0, 100]
    if rgb is None:
        rgb = [0, 0, 0]
    if matches is None:
        matches = []
    if palette is None:
        palette = []
    try:
        import tempfile
        from services.color_pdf import render_pantone_pdf

        data = {
            "name": name,
            "hex": hex_color,
            "cmyk": cmyk,
            "rgb": rgb,
            "input_hex": input_hex,
            "matches": matches,
            "svg_base64": svg_base64,
            "palette": palette,
        }
        pdf_bytes = render_pantone_pdf(export_type, data)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            pdf_path = tmp.name
        return json.dumps({"success": True, "pdf_path": pdf_path}, ensure_ascii=False)
    except ValueError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"导出失败: {e}"}, ensure_ascii=False)


# ============================================================
# AI 生图（GEN 适配器层）— 零本地 GPU，调用云端图像大模型
# ============================================================


@mcp.tool()
def generate_image(
    prompt: str,
    backend: str = "auto",
    ref_image_path: str = None,
    size: str = "1024x1024",
    n: int = 1,
    model: str = "",
    output_dir: str = "/tmp/colorflow-gen",
) -> str:
    """AI 生成包装效果图（零本地 GPU，调用云端图像大模型）。

    Args:
        prompt: 生图描述（中文/英文均可），如"红色天地盖礼盒，烫金logo，哑光，电商白底"
        backend: auto / volcano / fal / comfyui（默认 auto，按优先级降级）
        ref_image_path: 参考图路径（可选，图生图），PNG/JPG/WebP/BMP
        size: 输出尺寸，如 "1024x1024"
        n: 生成张数 1-4（默认 1）
        model: 覆盖模型名（空则用各后端默认）
        output_dir: 输出目录（默认 /tmp/colorflow-gen）
    Returns:
        JSON: {success, images: [{png_path, width, height, backend, model}],
               backend, count}
        生成的 PNG 路径可直接传给 trace_image / cutout 使用。
    """
    auth = _auth_check()
    if auth:
        return auth
    if not prompt or not prompt.strip():
        return json.dumps({"error": "prompt 不能为空"}, ensure_ascii=False)
    ref_bytes = None
    if ref_image_path:
        if not os.path.exists(ref_image_path):
            return json.dumps({"error": f"参考图不存在: {ref_image_path}"}, ensure_ascii=False)
        with open(ref_image_path, "rb") as f:
            ref_bytes = f.read()
    try:
        results = gen_dispatch(
            prompt, ref_image=ref_bytes, backend=backend,
            size=size, n=n, model=model,
        )
    except GenGenError as e:
        return json.dumps(
            {"error": f"生图失败({e.code}): {e}", "code": e.code, "retryable": e.retryable},
            ensure_ascii=False,
        )

    import tempfile

    os.makedirs(output_dir, exist_ok=True)
    images = []
    for idx, r in enumerate(results):
        prefix = r.backend or "gen"
        with tempfile.NamedTemporaryFile(
            prefix=f"{prefix}_{idx}_", suffix=".png", dir=output_dir, delete=False
        ) as tmp:
            tmp.write(r.png_bytes)
            png_path = tmp.name
        images.append({
            "png_path": png_path,
            "width": r.width,
            "height": r.height,
            "backend": r.backend,
            "model": r.model,
        })
    return json.dumps(
        {"success": True, "images": images, "count": len(images),
         "backend": results[0].backend if results else ""},
        ensure_ascii=False,
    )


# ============================================================
# VISION 图→prompt（image2prompt 反向闭环）— 与 GEN 对称
# ============================================================
#
# 闭环用法：image_to_prompt(image_path) → prompt → generate_image(prompt)
# 或 full_pipeline(image_path=...) 一句话完成 图→prompt→生图→描图→Pantone→报价。
# 后端：vision_backends.dispatch_prompt（openai / claude / mock，auto 降级）。


@mcp.tool()
def image_to_prompt(
    image_path: str,
    backend: str = "auto",
    lang: str = "en",
    style: str = "product",
    model: str = "",
) -> str:
    """图→prompt：图像 → 多模态大模型描述 → 英文 prompt（image2prompt）。

    闭环用法：本工具输出的 prompt 可直接传给 generate_image / full_pipeline，
    完成「图→prompt→生图→描图→Pantone→报价」全链路。

    Args:
        image_path: 本地图像路径（必填），PNG/JPG/WebP/BMP
        backend: auto / openai / claude / mock（默认 auto，按优先级降级）
        lang: 输出语言 en / zh（默认 en）
        style: 风格提示 product / poster / packaging 等（默认 product）
        model: 覆盖模型名（空则用各后端默认）
    Returns:
        JSON: {success, prompt, backend, model, meta}
    """
    auth = _auth_check()
    if auth:
        return auth
    if not image_path or not os.path.exists(image_path):
        return json.dumps({"error": f"图像不存在: {image_path}"}, ensure_ascii=False)
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    try:
        result = dispatch_prompt(image_bytes, backend=backend, lang=lang,
                                 style=style, model=model, timeout=120)
        return json.dumps({
            "success": True,
            "prompt": result.prompt,
            "backend": result.backend,
            "model": result.model,
            "meta": result.meta,
        }, ensure_ascii=False)
    except GenPromptError as e:
        return json.dumps(
            {"error": f"图→prompt 失败({e.code}): {e}",
             "code": e.code, "retryable": e.retryable},
            ensure_ascii=False,
        )


# ============================================================
# Prompt 模板库（Phase 4 · 行业预制 prompt → GEN）
# ============================================================
#
# 模板文件 assets/prompt_templates.json，按 category 分组，每个模板含
# {placeholder} 占位符和 params 定义。Agent 可列出模板 → 选模板 → 填参数
# → 渲染 prompt → 传给 generate_image / full_pipeline。
# 渲染逻辑在 prompt_templates.py（纯 CPU，零延迟，零网络）。


@mcp.tool()
def prompt_templates(category: str = "", search: str = "") -> str:
    """列出行业预制 prompt 模板（按分类分组）。

    用法：先调用本工具获取模板清单，再用 prompt_render 渲染具体模板。

    Args:
        category: 按分类过滤（luxury / food / beauty / electronics / stationery / promotional）
        search: 模糊搜索模板名/描述
    Returns:
        JSON: {success, categories, templates, count}
        templates: [{id, name, category, description, param_names}]
    """
    auth = _auth_check()
    if auth:
        return auth
    from prompt_templates import list_categories, list_templates, TemplateError
    try:
        cats = list_categories()
        tpls = list_templates(category=category or None, search=search or None)
        return json.dumps({
            "success": True, "categories": cats, "templates": tpls,
            "count": len(tpls),
        }, ensure_ascii=False)
    except TemplateError as e:
        return json.dumps({"error": str(e), "code": e.code}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"模板列表查询失败: {e}"}, ensure_ascii=False)


@mcp.tool()
def prompt_render(template_id: str, params: str = "") -> str:
    """渲染 prompt 模板 → 完整英文 prompt。

    用法：先调用 prompt_templates 获取模板清单，再用本工具渲染。
    渲染结果可直接传给 generate_image 或 full_pipeline。

    Args:
        template_id: 模板 id（如 luxury_gift_box）
        params: JSON 字符串 {param_name: value}（可选，缺失用模板默认值）
    Returns:
        JSON: {success, prompt, template_id, template_name, params: {name: {value, default}}}
    """
    auth = _auth_check()
    if auth:
        return auth
    from prompt_templates import render as tpl_render, TemplateError
    if not template_id or not template_id.strip():
        return json.dumps({"error": "template_id 不能为空"}, ensure_ascii=False)
    parsed_params = {}
    if params:
        try:
            parsed_params = json.loads(params)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"params 不是合法 JSON: {e}"}, ensure_ascii=False)
    try:
        result = tpl_render(template_id, parsed_params)
        return json.dumps({"success": True, **result}, ensure_ascii=False)
    except TemplateError as e:
        return json.dumps({"error": str(e), "code": e.code}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"模板渲染失败: {e}"}, ensure_ascii=False)


@mcp.tool()
def prompt_optimize(prompt: str, backend: str = "auto") -> str:
    """优化用户 prompt → 增强版英文 prompt（适合图像生成模型）。

    用法：调用本工具优化 prompt，再把结果传给 generate_image / full_pipeline。
    无 API Key 时自动降级 mock（纯字符串拼接，不调 API）。

    Args:
        prompt: 用户原始 prompt（中文/英文均可）
        backend: auto / openai / mock（默认 auto）
    Returns:
        JSON: {success, prompt, backend, model, meta}
    """
    auth = _auth_check()
    if auth:
        return auth
    from prompt_optimizer import dispatch_optimize, OptimizeError
    if not prompt or not prompt.strip():
        return json.dumps({"error": "prompt 不能为空"}, ensure_ascii=False)
    try:
        result = dispatch_optimize(prompt, backend=backend)
        return json.dumps({
            "success": True, "prompt": result.prompt,
            "backend": result.backend, "model": result.model,
            "meta": result.meta,
        }, ensure_ascii=False)
    except OptimizeError as e:
        return json.dumps({"error": f"优化失败({e.code}): {e}",
                           "code": e.code, "retryable": e.retryable},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"优化失败: {e}"}, ensure_ascii=False)


# ============================================================
# 一句话流水线（Phase 2）：生图 → 抠图 → 描图 → Pantone → 报价 → ZIP
# ============================================================


@mcp.tool()
def full_pipeline(
    prompt: str = "",
    image_path: str = None,
    width_mm: float = 210.0,
    height_mm: float = 297.0,
    depth_mm: float = 0.0,
    qty: int = 1000,
    colors: int = 4,
    backend: str = "auto",
    vision_backend: str = "auto",
    output_dir: str = "/tmp/colorflow-pipeline",
) -> str:
    """一句话完成：生图→抠图→描图→Pantone→报价→生产文件 ZIP。

    支持两种入口（二选一，互斥）：
      - prompt:     直接给生图描述（原有用法）
      - image_path: 给本地图像，先经 image_to_prompt 推导 prompt 再生图
                    （图→prompt→生图 闭环，对应 docs/03 方案 B）

    刀板（DIELINE）模块未就绪时止于 Pantone + 报价（降级不崩溃）。
    每一步失败都记录到 errors 并继续，绝不假成功。

    Args:
        prompt: 生图描述（中文/英文均可），与 image_path 二选一
        image_path: 本地图像路径（可选），提供时自动推导 prompt
        width_mm: 成品宽（毫米），用于报价
        height_mm: 成品高（毫米），用于报价
        depth_mm: 成品深度（毫米），刀板模块预留位
        qty: 印刷数量
        colors: 颜色数（报价用，默认 4C）
        backend: 生图后端 auto / volcano / fal / comfyui
        vision_backend: 图→prompt 后端 auto / openai / claude / mock
        output_dir: 输出目录
    Returns:
        JSON: {success, zip_path, files, quote, color_count, errors}
    """
    auth = _auth_check()
    if auth:
        return auth

    # ── 入口解析：prompt 或 image_path（image_path 优先，自动推导 prompt）──
    if image_path:
        if not os.path.exists(image_path):
            return json.dumps({"error": f"图像不存在: {image_path}"}, ensure_ascii=False)
        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            v = dispatch_prompt(image_bytes, backend=vision_backend, lang="en",
                                style="product", timeout=120)
            prompt = prompt or v.prompt
        except GenPromptError as e:
            return json.dumps(
                {"error": f"图→prompt 失败({e.code}): {e}",
                 "code": e.code, "retryable": e.retryable},
                ensure_ascii=False,
            )

    if not prompt or not prompt.strip():
        return json.dumps({"error": "prompt 与 image_path 至少提供一个"}, ensure_ascii=False)

    from mcp_print.tools.colors import cmyk_to_rgb
    import tempfile
    import zipfile

    files = []      # [(type, path)]
    errors = []

    try:
        # ── 1) 生图 ────────────────────────────────────────────
        gen_results = gen_dispatch(prompt, backend=backend, size=(1024, 1024), n=1)
        os.makedirs(output_dir, exist_ok=True)
        gen_png = None
        for idx, r in enumerate(gen_results):
            tmp = tempfile.NamedTemporaryFile(
                prefix="gen_", suffix=".png", dir=output_dir, delete=False
            )
            tmp.write(r.png_bytes)
            tmp.close()
            gen_png = tmp.name
            files.append(("gen_image", gen_png))
            if idx == 0:
                break  # 取首张作为流水线输入
        if not gen_png:
            return json.dumps({"error": "生图未返回有效图像", "errors": errors},
                               ensure_ascii=False)

        # ── 2) 抠图（降级：失败则直接用原图）────────────────────
        cutout_png = gen_png
        try:
            cutout_png = sdk.cutout(gen_png, model="silueta", alpha_matting=True)
            files.append(("cutout", cutout_png))
        except Exception as e:
            errors.append(f"抠图失败（用原图降级）: {e}")

        # ── 3) 描图 ────────────────────────────────────────────
        svg_path = sdk.trace(
            cutout_png, mode="color", colormode="rgb8", hierarchical="stacked",
            path_precision=10, filter_speckle=4, length_threshold=2.0,
            color_precision=6, layer_difference=64, corner_threshold=60,
        )
        files.append(("svg", svg_path))

        # ── 4) 主色 + Pantone 匹配 ─────────────────────────────
        with open(svg_path, "rb") as f:
            svg_bytes = f.read()
        palette = []
        for c in extract_svg_colors(svg_bytes, top_n=5):
            matches = []
            try:
                for m in pantone_search(hex_color=c["hex"]).get("matches", [])[:3]:
                    rgb = cmyk_to_rgb(m["c"], m["m"], m["y"], m["k"])
                    matches.append({
                        "name": m["name"],
                        "hex": m["hex"],
                        "cmyk": [m["c"], m["m"], m["y"], m["k"]],
                        "rgb": [rgb["r"], rgb["g"], rgb["b"]],
                        "delta_e": round(
                            _delta_e(c["hex"], (m["c"], m["m"], m["y"], m["k"])), 2
                        ),
                    })
            except Exception as e:
                errors.append(f"Pantone 匹配失败（跳过该色）: {e}")
            palette.append({"color": c, "pantone_matches": matches})

        # ── 5) 报价（降级：失败则 quote 为 None）──────────────
        quote = None
        try:
            n_colors = max(2, min(int(colors) or 4, len(palette) + 1))
            q = print_cost_estimate(
                width_mm=float(width_mm), height_mm=float(height_mm),
                quantity=int(qty), num_colors=n_colors,
                paper_gsm=120.0, print_method="offset",
            )
            quote = {
                "ink_cost_usd": q["ink_cost"],
                "setup_cost_usd": q["setup_cost"],
                "paper_cost_usd": q["paper_cost"],
                "total_cost_usd": q["total_cost"],
                "cost_per_unit_usd": q["cost_per_unit"],
                "currency": q["currency"],
                "colors": n_colors,
                "qty": int(qty),
            }
        except Exception as e:
            errors.append(f"报价失败: {e}")

        # ── 6) 打包 ZIP：PNG + 抠图 + SVG + palette + quote ────
        palette_path = os.path.join(output_dir, "colorflow_palette.json")
        quote_path = os.path.join(output_dir, "colorflow_quote.json")
        with open(palette_path, "w", encoding="utf-8") as f:
            json.dump({"palette": palette}, f, ensure_ascii=False, indent=2)
        files.append(("palette", palette_path))
        if quote:
            with open(quote_path, "w", encoding="utf-8") as f:
                json.dump({"quote": quote}, f, ensure_ascii=False, indent=2)
            files.append(("quote", quote_path))

        zip_path = os.path.join(output_dir, "colorflow_pipeline.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(gen_png, "colorflow_gen.png")
            if cutout_png != gen_png:
                zf.write(cutout_png, "colorflow_cutout.png")
            zf.write(svg_path, "colorflow_output.svg")
            zf.write(palette_path, "colorflow_palette.json")
            if quote:
                zf.write(quote_path, "colorflow_quote.json")
        files.append(("zip", zip_path))

        return json.dumps({
            "success": True,
            "zip_path": zip_path,
            "files": [{"type": t, "path": p} for t, p in files],
            "quote": quote,
            "color_count": len(palette),
            "errors": errors,
        }, ensure_ascii=False)
    except GenGenError as e:
        return json.dumps({
            "error": f"生图失败({e.code}): {e}",
            "code": e.code, "retryable": e.retryable,
            "files": [{"type": t, "path": p} for t, p in files],
            "errors": errors,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "error": f"流水线失败: {e}",
            "files": [{"type": t, "path": p} for t, p in files],
            "errors": errors + [str(e)],
        }, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
