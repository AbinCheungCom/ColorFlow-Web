"""ColorFlow 共享服务 — SVG 调色板 + Pantone 匹配。

供 Web (app.py) 与 MCP (mcp_server.py) 共用，消除两份完全相同的调色板构建逻辑。
"""

from colorflow_sdk import extract_svg_colors
from mcp_print.tools.colors import pantone_search, cmyk_to_rgb, _hex_to_rgb
from services.color_delta_e import delta_e_cie76
from mcp_print.tools.colors import _rgb_to_lab, _cmyk_to_lab


def build_palette(svg_bytes: bytes, top_n: int = 5) -> list[dict]:
    """从 SVG 提取主色并为每个主色匹配 Pantone。

    Args:
        svg_bytes: SVG 字节
        top_n: 提取的前 N 个主色（默认 5）

    Returns:
        调色板列表，每项含 color（hex/count/share/rgb）和 pantone_matches
    """
    colors = extract_svg_colors(svg_bytes, top_n=top_n)
    palette = []
    for c in colors:
        lab_hex = _rgb_to_lab(*_hex_to_rgb(c["hex"]))
        matches = []
        for m in pantone_search(hex_color=c["hex"]).get("matches", [])[:3]:
            lab_pantone = _cmyk_to_lab(m["c"], m["m"], m["y"], m["k"])
            de = delta_e_cie76(lab_hex, lab_pantone)
            _rgb = cmyk_to_rgb(m["c"], m["m"], m["y"], m["k"])
            matches.append({
                "name": m["name"],
                "hex": m["hex"],
                "cmyk": [m["c"], m["m"], m["y"], m["k"]],
                "rgb": _rgb if isinstance(_rgb, list) else [_rgb.get("r", 0), _rgb.get("g", 0), _rgb.get("b", 0)],
                "delta_e": round(de, 2),
            })
        palette.append({
            "color": {
                "hex": c["hex"],
                "count": c["count"],
                "share": c["share"],
                "rgb": list(_hex_to_rgb(c["hex"])),
            },
            "pantone_matches": matches,
        })
    return palette
