"""MCP Server 完整测试"""
import json
from pathlib import Path

import pytest

import mcp_server as ms


def test_all_tools_registered():
    assert callable(ms.trace_image)
    assert callable(ms.match_pantone)
    assert callable(ms.quote_print)
    assert callable(ms.export_print)
    assert callable(ms.trace_and_match)
    assert callable(ms.cutout)
    assert callable(ms.cutout_then_trace)
    assert callable(ms.pantone_lookup)
    assert callable(ms.pantone_colors)
    assert callable(ms.export_pantone_pdf)
    assert callable(ms.greyscale3d)
    assert len([x for x in dir(ms) if callable(getattr(ms, x)) and not x.startswith("_")]) >= 10


class TestPantone:
    def test_match_success(self):
        data = json.loads(ms.match_pantone("#DA291C"))
        assert data["success"] is True
        assert len(data["matches"]) > 0
        m = data["matches"][0]
        for key in ("name", "hex", "cmyk", "delta_e", "rgb", "interpretation"):
            assert key in m, f"missing key: {key}"

    def test_match_bad_hex(self):
        data = json.loads(ms.match_pantone("bad"))
        assert data.get("error")

    def test_match_invalid_hex_chars(self):
        # Bug: '#GGGGGG' 长度正确但包含非法十六进制字符，应返回错误而非崩溃
        data = json.loads(ms.match_pantone("#GGGGGG"))
        assert data.get("error")

    def test_lookup_success(self):
        data = json.loads(ms.pantone_lookup("485C"))
        assert data["success"] is True
        assert data["result"]["name"]

    def test_lookup_empty(self):
        data = json.loads(ms.pantone_lookup(""))
        assert data.get("error")

    def test_colors_default(self):
        data = json.loads(ms.pantone_colors())
        assert data["success"] is True
        assert data["total"] > 0
        assert len(data["items"]) <= 50

    def test_colors_search(self):
        data = json.loads(ms.pantone_colors(search="red", limit=10))
        assert data["success"] is True
        assert all("red" in c.get("name", "").lower() for c in data["items"])


class TestQuote:
    def test_fields(self):
        data = json.loads(ms.quote_print(210, 297, 1000, 4, 120, "offset"))
        assert data["success"] is True
        for key in ("ink_cost_usd", "setup_cost_usd", "total_cost_usd",
                    "cost_per_unit_usd", "currency", "breakdown"):
            assert key in data["result"], f"missing key: {key}"
        assert data["result"]["total_cost_usd"] > 0


class TestTrace:
    def test_bad_extension(self):
        data = json.loads(ms.trace_image("photo.gif"))
        assert data.get("error")

    def test_with_params(self, tmp_path):
        # 生成一个极小 PNG
        png = tmp_path / "test.png"
        from PIL import Image
        Image.new("RGB", (10, 10), color=(255, 128, 0)).save(png)
        data = json.loads(ms.trace_image(str(png), mode="color", colormode="mono",
                                          hierarchical="flat", filter_speckle=10,
                                          color_precision=8, layer_difference=80,
                                          corner_threshold=90, length_threshold=1.0,
                                          path_precision=12))
        assert data["success"] is True
        assert data["svg_path"]


class TestTraceAndMatch:
    def test_bad_extension(self):
        data = json.loads(ms.trace_and_match("photo.gif"))
        assert data.get("error")

    def test_with_params(self, tmp_path):
        png = tmp_path / "test.png"
        from PIL import Image
        Image.new("RGB", (10, 10), color=(255, 128, 0)).save(png)
        data = json.loads(ms.trace_and_match(str(png), mode="color", colormode="rgb8",
                                              hierarchical="stacked", filter_speckle=4))
        assert data["success"] is True
        assert data["svg_path"]
        assert data["color_count"] >= 0


class TestCutout:
    def test_bad_extension(self):
        data = json.loads(ms.cutout("photo.gif"))
        assert data.get("error")

    def test_invalid_model_fallback(self, tmp_path):
        png = tmp_path / "test.png"
        from PIL import Image
        Image.new("RGB", (10, 10), color=(255, 128, 0)).save(png)
        data = json.loads(ms.cutout(str(png), model="INVALID"))
        # 非法模型回退 silueta，silueta 在本地，可正常执行
        assert data["success"] is True
        assert data["png_path"]
        assert data["width"] == 10
        assert data["height"] == 10

    def test_with_alpha_matting(self, tmp_path):
        png = tmp_path / "test.png"
        from PIL import Image
        Image.new("RGB", (10, 10), color=(255, 128, 0)).save(png)
        data = json.loads(ms.cutout(str(png), alpha_matting=True,
                                     alpha_matting_foreground_threshold=200,
                                     alpha_matting_background_threshold=20,
                                     alpha_matting_erode_size=15))
        assert data["success"] is True


class TestCutoutThenTrace:
    def test_bad_extension(self):
        data = json.loads(ms.cutout_then_trace("photo.gif"))
        assert data.get("error")

    def test_success(self, tmp_path):
        png = tmp_path / "test.png"
        from PIL import Image
        Image.new("RGB", (10, 10), color=(255, 128, 0)).save(png)
        data = json.loads(ms.cutout_then_trace(str(png), model="silueta",
                                                alpha_matting=False,
                                                trace_mode="color",
                                                colormode="rgb8",
                                                hierarchical="stacked",
                                                filter_speckle=4,
                                                path_precision=7))
        assert data["success"] is True
        assert data["svg_path"]


class TestExportPrint:
    def test_bad_extension(self):
        data = json.loads(ms.export_print("photo.gif", 100, 80))
        assert data.get("error")

    def test_success(self, tmp_path):
        png = tmp_path / "test.png"
        from PIL import Image
        Image.new("RGB", (10, 10), color=(255, 128, 0)).save(png)
        data = json.loads(ms.export_print(str(png), 100, 80, bleed_mm=3,
                                           mode="color", path_precision=10,
                                           filter_speckle=4))
        assert data["success"] is True
        assert data["pdf_path"]


class TestExportPantonePdf:
    def test_swatch(self):
        data = json.loads(ms.export_pantone_pdf(
            export_type="swatch",
            name="485 C",
            hex_color="#DA291C",
            cmyk=[0, 85, 95, 5],
            rgb=[218, 41, 28],
        ))
        assert data["success"] is True
        assert data["pdf_path"]

    def test_report(self):
        data = json.loads(ms.export_pantone_pdf(
            export_type="report",
            input_hex="#DA291C",
            matches=[
                {"name": "485 C", "hex": "#DA291C", "cmyk": [0, 85, 95, 5], "delta_e": 0.32},
                {"name": "186 C", "hex": "#C8102E", "cmyk": [0, 90, 95, 20], "delta_e": 3.15},
            ],
        ))
        assert data["success"] is True
        assert data["pdf_path"]

    def test_invalid_type(self):
        data = json.loads(ms.export_pantone_pdf(export_type="invalid"))
        assert data.get("error")

    def test_palette(self):
        # P2-12b 回归：此前 MCP 端缺 palette 导出（与 Web 行为偏差），修复后应可用
        data = json.loads(ms.export_pantone_pdf(
            export_type="palette",
            svg_base64="",
            palette=[
                {"color": {"hex": "#DA291C", "rgb": [218, 41, 28], "share": 0.6},
                 "pantone_matches": [
                     {"name": "485 C", "hex": "#DA291C",
                      "cmyk": [0, 85, 95, 5], "delta_e": 0.5}
                 ]},
            ],
        ))
        assert data["success"] is True
        assert data["pdf_path"]


class TestGreyscale3D:
    """MCP greyscale3d 工具测试"""

    def test_bad_extension(self, tmp_path):
        data = json.loads(ms.greyscale3d("photo.gif"))
        assert data.get("error")

    def test_all_params(self, tmp_path):
        png = tmp_path / "test.png"
        from PIL import Image
        Image.new("RGB", (20, 20), color=(255, 128, 0)).save(png)
        data = json.loads(ms.greyscale3d(
            str(png),
            invert=True,
            contrast=1.5,
            gamma=0.9,
            smooth=1,
            auto_levels=True,
            bit_depth=16,
        ))
        assert data["success"] is True
        assert data["png_path"]
        assert data["width"] == 20
        assert data["height"] == 20
        assert data["bit_depth"] == 16