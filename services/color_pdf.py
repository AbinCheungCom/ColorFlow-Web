"""ColorFlow 共享色彩服务 — Pantone PDF 渲染。

集中印刷级 CMYK PDF 的色卡 / 匹配报告 / 主色提取报告渲染逻辑，
供 Web (app.py) 与 MCP (mcp_server.py) 共用。此举消除两份渲染实现
的行为偏差，并为 MCP 端补齐此前缺失的 palette 导出类型
（见开发文档 P2-12b）。
"""

import base64
import io


def _hex_to_cmyk_color(hex_str):
    """HEX 字符串 → reportlab CMYKColor（经 PIL RGB→CMYK 转换，印刷级）"""
    from reportlab.lib.colors import CMYKColor
    from PIL import Image
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    cmyk = Image.new("RGB", (1, 1), (r, g, b)).convert("CMYK").load()[0, 0]
    return CMYKColor(cmyk[0] / 255, cmyk[1] / 255, cmyk[2] / 255, cmyk[3] / 255)


def render_pantone_pdf(export_type: str, data: dict) -> bytes:
    """渲染 Pantone 色卡 / 匹配报告 / 主色提取报告 PDF（CMYK，印刷级）。

    Args:
        export_type: "swatch" | "report" | "palette"
        data: 渲染数据，字段随类型而异
            - swatch:  {name, hex, cmyk:[c,m,y,k], rgb:[r,g,b]}
            - report:  {input_hex, matches:[{name,hex,cmyk,rgb,delta_e}]}
            - palette: {svg_base64, palette:[{color:{hex,rgb,share},
                       pantone_matches:[{name,hex,cmyk,delta_e}]}]}
    Returns:
        PDF 字节流。
    Raises:
        ValueError: export_type 非法。
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.colors import Color
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4

    if export_type == "swatch":
        # === 单个色卡 ===
        name = data.get("name", "Unknown")
        hex_val = data.get("hex", "#000000")
        cmyk = data.get("cmyk", [0, 0, 0, 100])
        rgb = data.get("rgb", [0, 0, 0])

        swatch_x = 50
        swatch_y = page_h - 250
        swatch_w = 180
        swatch_h = 180

        c.setFillColor(_hex_to_cmyk_color(hex_val))
        c.rect(swatch_x, swatch_y, swatch_w, swatch_h, fill=1, stroke=0)

        # 右侧色值信息
        text_x = swatch_x + swatch_w + 30
        text_y = swatch_y + swatch_h - 20
        c.setFillColor(Color(0, 0, 0))
        c.setFont("Helvetica-Bold", 20)
        c.drawString(text_x, text_y, name)
        c.setFont("Helvetica", 12)
        c.drawString(text_x, text_y - 30, "HEX    " + hex_val.upper())
        c.drawString(text_x, text_y - 50, "CMYK   {} / {} / {} / {}".format(*cmyk))
        c.drawString(text_x, text_y - 70, "RGB    {} / {} / {}".format(*rgb))

        # 底部品牌
        c.setFont("Helvetica", 9)
        c.setFillColor(Color(0.5, 0.5, 0.5))
        c.drawString(50, 40, "ColorFlow · 色卡规格")

    elif export_type == "report":
        # === 匹配报告 ===
        input_hex = data.get("input_hex", "#000000")
        matches = data.get("matches", [])

        # 标题
        c.setFillColor(Color(0, 0, 0))
        c.setFont("Helvetica-Bold", 18)
        c.drawString(50, page_h - 60, "色彩匹配报告")

        # 输入色块
        c.setFillColor(_hex_to_cmyk_color(input_hex))
        c.rect(50, page_h - 160, 60, 60, fill=1, stroke=0)
        c.setFillColor(Color(0, 0, 0))
        c.setFont("Helvetica", 12)
        c.drawString(125, page_h - 110, "输入色 " + input_hex.upper())

        # 匹配列表
        y = page_h - 200
        c.setFont("Helvetica-Bold", 11)
        c.drawString(50, y, "色块")
        c.drawString(120, y, "Pantone")
        c.drawString(330, y, "HEX")
        c.drawString(430, y, "ΔE")
        y -= 6
        c.setStrokeColor(Color(0.8, 0.8, 0.8))
        c.line(50, y, page_w - 50, y)
        y -= 20

        for m in matches:
            m_hex = m.get("hex", "#000000")
            m_name = m.get("name", "")
            m_de = m.get("delta_e", 0)

            # 色块
            c.setFillColor(_hex_to_cmyk_color(m_hex))
            c.rect(50, y - 14, 50, 20, fill=1, stroke=0)

            c.setFillColor(Color(0, 0, 0))
            c.setFont("Helvetica", 11)
            c.drawString(120, y - 8, m_name)
            c.drawString(330, y - 8, m_hex.upper())
            c.drawString(430, y - 8, str(m_de))
            y -= 35

        # 底部
        c.setFont("Helvetica", 9)
        c.setFillColor(Color(0.5, 0.5, 0.5))
        c.drawString(50, 40, "ColorFlow · 色彩匹配报告 · 输入色 " + input_hex.upper())

    elif export_type == "palette":
        # === 主色提取报告（首图 SVG + 主色 + Pantone 匹配列表）===
        svg_b64 = data.get("svg_base64", "")
        palette = data.get("palette", [])

        # ---- 标题 ----
        c.setFillColor(Color(0, 0, 0))
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(page_w / 2, page_h - 45, "主色提取报告 · Pantone 匹配")

        # ---- SVG 矢量缩略图（居中，最大 340×220）----
        # reportlab 坐标原点在页面左下角；y 向上增大
        # SVG 顶部距页面顶 75pt（标题 45pt + 间距 30pt）
        svg_top_margin = 75
        max_tw, max_th = 340.0, 220.0
        draw_x, draw_y = 0, 0
        list_y = page_h - 100  # 默认列表起始（无 SVG 时）

        if svg_b64:
            try:
                from svglib.svglib import svg2rlg
                from io import BytesIO as _BytesIO

                svg_bytes = base64.b64decode(svg_b64)
                drawing = svg2rlg(_BytesIO(svg_bytes))
                dw, dh = drawing.width, drawing.height
                # 等比缩放至 max_tw × max_th 范围内
                draw_scale = min(max_tw / dw, max_th / dh)
                draw_w, draw_h = dw * draw_scale, dh * draw_scale
                # 水平居中
                draw_x = (page_w - draw_w) / 2
                # 正确坐标：SVG 顶部 = page_h - svg_top_margin
                # draw_y = SVG 底部 Y = page_h - svg_top_margin - draw_h
                draw_y = page_h - svg_top_margin - draw_h

                c.saveState()
                c.translate(draw_x, draw_y)
                c.scale(draw_scale, draw_scale)
                drawing.drawOn(c, 0, 0)
                c.restoreState()

                # 分隔线 + 列表起始
                sep_y = draw_y - 12
                c.setStrokeColor(Color(0.7, 0.7, 0.7))
                c.line(50, sep_y, page_w - 50, sep_y)
                list_y = sep_y - 22
            except Exception:
                list_y = page_h - 110
        else:
            list_y = page_h - 100

        # ---- 主色 + Pantone 匹配列表 ----
        # 表头
        c.setFillColor(Color(0, 0, 0))
        c.setFont("Helvetica-Bold", 9)
        c.drawString(50, list_y, "色块")
        c.drawString(100, list_y, "HEX")
        c.drawString(175, list_y, "RGB")
        c.drawString(260, list_y, "Pantone")
        c.drawString(380, list_y, "CMYK")
        c.drawString(480, list_y, "ΔE")
        list_y -= 5
        c.setStrokeColor(Color(0.75, 0.75, 0.75))
        c.line(50, list_y, page_w - 50, list_y)
        list_y -= 18

        c.setFont("Helvetica", 8)
        for idx, item in enumerate(palette):
            # 新页判断
            if list_y < 65:
                c.showPage()
                c.setFont("Helvetica", 8)
                list_y = page_h - 60

            color = item.get("color", {})
            top = (item.get("pantone_matches") or [None])[0]

            hex_val = color.get("hex", "#000000")
            rgb_vals = (color.get("rgb") or [0, 0, 0])
            share = color.get("share", 0)

            # 色块
            c.setFillColor(_hex_to_cmyk_color(hex_val))
            c.rect(50, list_y - 13, 22, 18, fill=1, stroke=0)

            c.setFillColor(Color(0, 0, 0))
            c.drawString(80, list_y - 7, hex_val.upper())
            c.drawString(175, list_y - 7, "{}/{}/{} ({:.0f}%)".format(
                rgb_vals[0], rgb_vals[1], rgb_vals[2], share * 100
            ))

            if top:
                top_name = top.get("name", "")
                cmyk_vals = top.get("cmyk", [0, 0, 0, 0])
                de_val = top.get("delta_e", 0)
                c.drawString(260, list_y - 7, top_name)
                c.drawString(380, list_y - 7,
                    "{}/{}/{}/{}".format(*cmyk_vals))
                c.drawString(480, list_y - 7, str(de_val))
            else:
                c.drawString(260, list_y - 7, "无匹配")

            list_y -= 22

        # ---- 底部品牌 ----
        c.setFont("Helvetica", 9)
        c.setFillColor(Color(0.5, 0.5, 0.5))
        c.drawCentredString(page_w / 2, 30,
            "ColorFlow · 主色提取报告 · 印刷级 CMYK")

    else:
        raise ValueError("Invalid type: must be 'swatch', 'report' or 'palette'")

    c.save()
    return buf.getvalue()
