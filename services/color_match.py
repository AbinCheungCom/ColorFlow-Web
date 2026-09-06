"""ColorFlow 共享服务 — Pantone 色彩匹配。

供 Web (app.py) 与 MCP (mcp_server.py) 共用，消除两份完全相同的匹配逻辑。
"""

from mcp_print.tools.colors import pantone_search, cmyk_to_rgb, _hex_to_rgb, _rgb_to_lab, _cmyk_to_lab
from services.color_delta_e import delta_e_cie76


def _interpret_de(de: float) -> str:
    """ΔE 分级描述"""
    if de < 1:
        return "excellent — imperceptible difference"
    elif de < 3:
        return "good — barely perceptible"
    elif de < 6:
        return "fair — noticeable difference"
    return "poor — obvious difference"


def match(hex_color: str, limit: int = 5) -> list[dict]:
    """HEX → 最近的 Pantone 匹配，含 ΔE、CMYK、RGB。

    Args:
        hex_color: HEX 颜色（#RRGGBB）
        limit: 返回的匹配数（默认 5）

    Returns:
        匹配列表，每项含 name/hex/cmyk/rgb/delta_e/interpretation
    """
    results = pantone_search(hex_color=hex_color)
    rgb_hex = _hex_to_rgb(hex_color)
    lab_hex = _rgb_to_lab(*rgb_hex)

    matches = []
    for m in results.get("matches", [])[:limit]:
        c, mm, y, k = m["c"], m["m"], m["y"], m["k"]
        lab_pantone = _cmyk_to_lab(c, mm, y, k)
        de = round(delta_e_cie76(lab_hex, lab_pantone), 2)
        rgb = cmyk_to_rgb(c, mm, y, k)
        matches.append({
            "name": m["name"],
            "hex": m["hex"],
            "cmyk": [c, mm, y, k],
            "rgb": rgb if isinstance(rgb, list) else [rgb.get("r", 0), rgb.get("g", 0), rgb.get("b", 0)],
            "delta_e": de,
            "interpretation": _interpret_de(de),
        })
    return matches
