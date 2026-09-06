"""ColorFlow 共享服务 — SVG 调色板 + Pantone 匹配。

供 Web (app.py) 与 MCP (mcp_server.py) 共用，消除两份完全相同的调色板构建逻辑。
"""

from colorflow_sdk import extract_svg_colors
from mcp_print.tools.colors import _hex_to_rgb
from services.color_match import match as pantone_match


def build_palette(svg_bytes: bytes, top_n: int = 5, match_limit: int = 3) -> list[dict]:
    """从 SVG 提取主色并为每个主色匹配 Pantone。

    Args:
        svg_bytes: SVG 字节
        top_n: 提取的前 N 个主色（默认 5）
        match_limit: 每个主色返回的 Pantone 匹配数（默认 3）

    Returns:
        调色板列表，每项含 color（hex/count/share/rgb）和 pantone_matches
    """
    colors = extract_svg_colors(svg_bytes, top_n=top_n)
    palette = []
    for c in colors:
        palette.append({
            "color": {
                "hex": c["hex"],
                "count": c["count"],
                "share": c["share"],
                "rgb": list(_hex_to_rgb(c["hex"])),
            },
            "pantone_matches": pantone_match(c["hex"], limit=match_limit),
        })
    return palette
