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
from colorflow_sdk.exceptions import ValidationError
from mcp_print.tools.colors import (
    _cmyk_to_lab,
    _hex_to_rgb,
    _load_db,
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

    from mcp_print.tools.colors import cmyk_to_rgb

    results = pantone_search(hex_color=hex_color)
    rgb_hex = _hex_to_rgb(hex_color)
    lab_hex = _rgb_to_lab(*rgb_hex)

    matches = []
    for m in results.get("matches", [])[:5]:
        c, mm, y, k = m["c"], m["m"], m["y"], m["k"]
        lab_pantone = _cmyk_to_lab(c, mm, y, k)
        de = round(delta_e_cie76(lab_hex, lab_pantone), 2)
        interp = (
            "excellent — imperceptible" if de < 1
            else "good — barely perceptible" if de < 3
            else "fair — noticeable" if de < 6
            else "poor — obvious"
        )
        rgb = cmyk_to_rgb(c, mm, y, k)
        matches.append({
            "name": m["name"],
            "hex": m["hex"],
            "cmyk": [c, mm, y, k],
            "rgb": [rgb["r"], rgb["g"], rgb["b"]],
            "delta_e": de,
            "interpretation": interp,
        })

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
        db = _load_db()
        if search:
            s = search.lower()
            db = [c for c in db if s in c.get("name", "").lower()]
        total = len(db)
        start = (page - 1) * limit
        end = start + limit
        return json.dumps(
            {
                "success": True,
                "items": db[start:end],
                "total": total,
                "page": page,
                "limit": limit,
                "pages": (total + limit - 1) // limit,
            },
            ensure_ascii=False,
        )
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
    try:
        result = print_cost_estimate(
            width_mm=width_mm,
            height_mm=height_mm,
            quantity=qty,
            num_colors=colors,
            paper_gsm=gsm,
            print_method=method,
        )
    except Exception as e:
        return json.dumps({"error": f"报价失败: {e}"}, ensure_ascii=False)
    payload = {
        "ink_cost_usd": result["ink_cost"],
        "setup_cost_usd": result["setup_cost"],
        "paper_cost_usd": result["paper_cost"],
        "total_cost_usd": result["total_cost"],
        "cost_per_unit_usd": result["cost_per_unit"],
        "currency": result["currency"],
        "breakdown": result["breakdown"],
    }
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

    palette = []
    for c in extract_svg_colors(svg_bytes, top_n=5):
        matches = [
            {
                "name": m["name"],
                "hex": m["hex"],
                "cmyk": [m["c"], m["m"], m["y"], m["k"]],
                "delta_e": round(
                    _delta_e(c["hex"], (m["c"], m["m"], m["y"], m["k"])), 2
                ),
            }
            for m in pantone_search(hex_color=c["hex"]).get("matches", [])[:3]
        ]
        palette.append({"color": c, "pantone_matches": matches})

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
        from PIL import Image, ImageOps, ImageEnhance, ImageFilter
        import tempfile

        with Image.open(image_path) as img:
            grey = img.convert("RGB").convert("L")

        # 高斯模糊
        if smooth > 0:
            grey = grey.filter(ImageFilter.GaussianBlur(radius=int(smooth)))

        # 自动级别
        if auto_levels:
            grey = ImageOps.autocontrast(grey)

        # 对比度
        if contrast != 1.0:
            grey = ImageEnhance.Contrast(grey).enhance(contrast)

        # Gamma
        if gamma != 1.0:
            curve = [int(round(255 * ((p / 255.0) ** (1.0 / gamma)))) for p in range(256)]
            grey = grey.point(curve)

        # 反色
        if invert:
            grey = ImageOps.invert(grey)

        # 位深转换
        if bit_depth == 16:
            grey = grey.point(lambda p: p * 257).convert("I;16")

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            png_path = tmp.name
        grey.save(png_path, format="PNG")

        return json.dumps(
            {
                "success": True,
                "png_path": png_path,
                "width": grey.width,
                "height": grey.height,
                "bit_depth": bit_depth,
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


if __name__ == "__main__":
    mcp.run()
