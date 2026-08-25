"""ColorFlow Web 集成测试"""

import io
import json
from pathlib import Path

import pytest

import app as app_module
from app import app
from colorflow_keys import keystore

client = app.test_client()

# 测试素材（复用 ColorFlow SDK 仓库的 sample.png）
_SAMPLE_PATHS = [
    Path("/d/Abin/ColorFlow/assets/sample.png"),
    Path(__file__).resolve().parent.parent.parent / "ColorFlow" / "assets" / "sample.png",
]


def _sample_png():
    for p in _SAMPLE_PATHS:
        if p.exists():
            return p
    return None


class TestIndex:
    def test_homepage(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"ColorFlow" in resp.data


class TestTrace:
    def test_no_image(self):
        resp = client.post("/api/trace", data={})
        assert resp.status_code == 400

    def test_empty_filename(self):
        resp = client.post(
            "/api/trace",
            data={"image": (io.BytesIO(b"x"), "")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400

    def test_unsupported_content_type(self):
        resp = client.post(
            "/api/trace",
            data={"image": (io.BytesIO(b"GIF89a"), "a.gif")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 415

    def test_invalid_mode(self):
        resp = client.post(
            "/api/trace",
            data={
                "image": (io.BytesIO(b"fake"), "a.png"),
                "mode": "invalid-mode",
            },
            content_type="multipart/form-data",
        )
        # 非法 mode：SDK ValidationError 应映射为 400
        assert resp.status_code == 400

    def test_invalid_numeric_param_falls_back(self):
        """非法数字参数应回退默认值而不 500"""
        png = _sample_png()
        if not png:
            pytest.skip("sample.png not found")
        with open(png, "rb") as f:
            resp = client.post(
                "/api/trace",
                data={
                    "image": (f, "sample.png"),
                    "filter_speckle": "not-a-number",
                    "mode": "color",
                },
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_success_trace(self):
        png = _sample_png()
        if not png:
            pytest.skip("sample.png not found")
        with open(png, "rb") as f:
            resp = client.post(
                "/api/trace",
                data={"image": (f, "sample.png")},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["svg_base64"]
        assert data["size"] > 0


class TestPantoneMatch:
    def test_no_json_content_type(self):
        # 未带 application/json -> Flask 自动 415
        resp = client.post("/api/pantone/match")
        assert resp.status_code == 415

    def test_empty_json_body(self):
        # 带 JSON content-type 但 body 为空 -> 400
        resp = client.post("/api/pantone/match", data="", content_type="application/json")
        assert resp.status_code == 400

    def test_no_hex(self):
        resp = client.post("/api/pantone/match", json={})
        assert resp.status_code == 400

    def test_invalid_hex(self):
        resp = client.post("/api/pantone/match", json={"hex_color": "xyz"})
        assert resp.status_code == 400

    def test_valid_hex(self):
        resp = client.post("/api/pantone/match", json={"hex_color": "#DA291C"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["matches"]) > 0
        m = data["matches"][0]
        # 前端依赖的字段
        assert "name" in m and "hex" in m and "cmyk" in m and "delta_e" in m


class TestPantoneLookup:
    def test_missing_name(self):
        resp = client.get("/api/pantone/lookup")
        assert resp.status_code == 400

    def test_lookup_success(self):
        resp = client.get("/api/pantone/lookup?name=485C")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["result"]["name"]


class TestPantoneColors:
    def test_list_default(self):
        resp = client.get("/api/pantone/colors")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["total"] > 0
        assert len(data["items"]) <= 50

    def test_invalid_page_falls_back(self):
        resp = client.get("/api/pantone/colors?page=abc&limit=xyz")
        assert resp.status_code == 200  # 回退默认值而不是 500
        data = resp.get_json()
        assert data["page"] == 1

    def test_search(self):
        resp = client.get("/api/pantone/colors?search=red&limit=10")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert all("red" in c.get("name", "").lower() for c in data["items"])


class TestApiAuth:
    """API Key 认证测试（默认无 Key → 开放；生成 Key 后保护 /api/*）"""

    def test_disabled_by_default(self):
        from colorflow_keys import keystore
        assert not keystore.has_any()

    def test_requires_key_when_configured(self, monkeypatch):
        from colorflow_keys import keystore
        # 生成一个 key
        entry = keystore.generate(name="test-key")
        test_key = entry["key"]
        try:
            # 无 key → 401
            r = client.get("/api/pantone/colors")
            assert r.status_code == 401
            # 错误 key → 401
            r = client.get("/api/pantone/colors", headers={"x-api-key": "wrong"})
            assert r.status_code == 401
            # 正确 key → 200
            r = client.get("/api/pantone/colors", headers={"x-api-key": test_key})
            assert r.status_code == 200
            # 非 ASCII key → 401（不应 500）
            r = client.get("/api/pantone/colors", headers={"x-api-key": "中文😀"})
            assert r.status_code == 401
        finally:
            keystore.revoke(entry["key_id"])

    def test_static_and_index_open_when_configured(self, monkeypatch):
        from colorflow_keys import keystore
        entry = keystore.generate(name="test-key-2")
        test_key = entry["key"]
        try:
            assert client.get("/").status_code == 200
            assert client.get("/static/app.js").status_code == 200
        finally:
            keystore.revoke(entry["key_id"])


class TestKeyManagement:
    """API Key 管理端点测试"""

    def test_generate_and_list(self):
        # 先生成一个 key 用于认证
        from colorflow_keys import keystore
        entry = keystore.generate(name="mgmt-test")
        key = entry["key"]
        key_id = entry["key_id"]
        try:
            # 列出 keys
            r = client.get("/api/keys", headers={"x-api-key": key})
            assert r.status_code == 200
            data = r.get_json()
            assert data["success"] is True
            assert data["count"] > 0
            # 验证脱敏 + key_id 非敏感（P0-1：响应中不得出现明文 key）
            for k in data["keys"]:
                assert "****" in k["key_masked"]
                assert k["key_id"] != key
                assert k["key_id"].startswith("kid_")
                assert key not in json.dumps(k)
        finally:
            keystore.revoke(key_id)

    def test_revoke(self):
        from colorflow_keys import keystore
        entry = keystore.generate(name="revoke-test")
        key = entry["key"]
        key_id = entry["key_id"]
        try:
            r = client.delete("/api/keys/" + key_id, headers={"x-api-key": key})
            assert r.status_code == 200
            assert r.get_json()["success"] is True
        finally:
            keystore.revoke(key_id)  # 幂等


class TestTraceColors:
    """一键流水线：描图 → 主色 → Pantone 匹配"""

    def test_no_image(self):
        resp = client.post("/api/trace/colors", data={})
        assert resp.status_code == 400

    def test_unsupported_type(self):
        resp = client.post(
            "/api/trace/colors",
            data={"image": (io.BytesIO(b"GIF89a"), "a.gif")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 415

    def test_pipeline_success(self):
        png = _sample_png()
        if not png:
            pytest.skip("sample.png not found")
        with open(png, "rb") as f:
            resp = client.post(
                "/api/trace/colors",
                data={"image": (f, "sample.png")},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["svg_base64"]
        assert data["color_count"] > 0
        assert len(data["palette"]) == data["color_count"]
        item = data["palette"][0]
        # 主色与 Pantone 匹配字段
        assert "color" in item and "hex" in item["color"]
        assert "pantone_matches" in item
        if item["pantone_matches"]:
            m = item["pantone_matches"][0]
            assert "name" in m and "hex" in m and "delta_e" in m

    def test_pipeline_color_has_rgb(self):
        """潘通色卡：主色应含 RGB 值（需求：色卡展示 RGB）"""
        png = _sample_png()
        if not png:
            pytest.skip("sample.png not found")
        with open(png, "rb") as f:
            resp = client.post(
                "/api/trace/colors",
                data={"image": (f, "sample.png")},
                content_type="multipart/form-data",
            )
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["color_count"] > 0
        for item in data["palette"]:
            rgb = item["color"].get("rgb")
            assert rgb and len(rgb) == 3
            assert all(isinstance(v, int) and 0 <= v <= 255 for v in rgb)

    def test_pipeline_matches_have_rgb(self):
        """潘通色卡：匹配色应含 RGB 值"""
        png = _sample_png()
        if not png:
            pytest.skip("sample.png not found")
        with open(png, "rb") as f:
            resp = client.post(
                "/api/trace/colors",
                data={"image": (f, "sample.png")},
                content_type="multipart/form-data",
            )
        data = resp.get_json()
        assert resp.status_code == 200
        for item in data["palette"]:
            for m in item["pantone_matches"]:
                rgb = m.get("rgb")
                assert rgb and len(rgb) == 3

    def test_pipeline_backward_compat(self):
        """向后兼容：现有字段(hex/count/share/name/cmyk/delta_e)全部保留"""
        png = _sample_png()
        if not png:
            pytest.skip("sample.png not found")
        with open(png, "rb") as f:
            resp = client.post(
                "/api/trace/colors",
                data={"image": (f, "sample.png")},
                content_type="multipart/form-data",
            )
        data = resp.get_json()
        assert resp.status_code == 200
        for item in data["palette"]:
            assert {"hex", "count", "share"} <= set(item["color"].keys())
            for m in item["pantone_matches"]:
                assert {"name", "hex", "cmyk", "delta_e"} <= set(m.keys())


class TestPrintExport:
    """印刷 PDF 导出端点（export_print M3）"""

    def test_no_image(self):
        resp = client.post("/api/print/export", data={})
        assert resp.status_code == 400

    def test_missing_dimensions(self):
        png = _sample_png()
        if not png:
            pytest.skip("sample.png not found")
        with open(png, "rb") as f:
            resp = client.post(
                "/api/print/export",
                data={"image": (f, "sample.png")},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 400

    def test_invalid_dimensions(self):
        png = _sample_png()
        if not png:
            pytest.skip("sample.png not found")
        with open(png, "rb") as f:
            resp = client.post(
                "/api/print/export",
                data={"image": (f, "sample.png"), "width_mm": "0", "height_mm": "80"},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 400

    def test_success_pdf(self):
        png = _sample_png()
        if not png:
            pytest.skip("sample.png not found")
        with open(png, "rb") as f:
            resp = client.post(
                "/api/print/export",
                data={
                    "image": (f, "sample.png"),
                    "width_mm": "100",
                    "height_mm": "80",
                    "bleed_mm": "3",
                },
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.data[:5] == b"%PDF-"


class TestCostQuote:
    def test_no_json_content_type(self):
        resp = client.post("/api/cost/quote")
        assert resp.status_code == 415

    def test_empty_json_body(self):
        resp = client.post("/api/cost/quote", data="", content_type="application/json")
        assert resp.status_code == 400

    def test_invalid_numbers(self):
        resp = client.post(
            "/api/cost/quote",
            json={"width": "abc", "height": "def", "qty": "xyz"},
        )
        # float('abc') 抛 ValueError -> 400
        assert resp.status_code == 400

    def test_success_and_field_mapping(self):
        """回归：前端期望的 _usd 字段必须存在（此前全部显示 N/A）"""
        resp = client.post(
            "/api/cost/quote",
            json={"width": 210, "height": 297, "qty": 1000, "colors": 4, "gsm": 120, "method": "offset"},
        )
        assert resp.status_code == 200
        r = resp.get_json()["result"]
        for key in ("ink_cost_usd", "setup_cost_usd", "paper_cost_usd", "total_cost_usd", "cost_per_unit_usd", "currency", "breakdown"):
            assert key in r, f"missing key: {key}"
        assert r["breakdown"]["plates"] is not None


class TestGrayscale3D:
    """3D 灰度图生成功能测试"""

    def test_no_image(self):
        resp = client.post("/api/grayscale3d", data={})
        assert resp.status_code == 400

    def test_invalid_content_type(self):
        resp = client.post(
            "/api/grayscale3d",
            data={"image": (io.BytesIO(b"GIF89a"), "a.gif")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 415

    def test_params_clamp_defaults(self):
        """参数边界验证：超出范围应被 clamping 为默认值"""
        png = _sample_png()
        if not png:
            pytest.skip("sample.png not found")
        with open(png, "rb") as f:
            resp = client.post(
                "/api/grayscale3d",
                data={
                    "image": (f, "sample.png"),
                    "contrast": "999",     # 应 clamping 为 3.0
                    "gamma": "0.1",       # 应 clamping 为 0.5
                    "smooth": "-5",       # 应 clamping 为 0.0
                    "bit_depth": "99",    # 非 16 应降级为 8
                },
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        # 验证 PNG base64 存在且尺寸合理
        assert data["png_base64"]
        assert data["size"] > 0
        assert 0 < data["width"] <= 10000
        assert 0 < data["height"] <= 10000
        assert data["bit_depth"] == 8  # 非 16 应降级为 8

    def test_success_default_params(self):
        png = _sample_png()
        if not png:
            pytest.skip("sample.png not found")
        with open(png, "rb") as f:
            resp = client.post(
                "/api/grayscale3d",
                data={"image": (f, "sample.png")},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["png_base64"]
        assert data["size"] > 0
        assert data["width"] > 0 and data["height"] > 0
        assert data["bit_depth"] == 8
        # 直方图数据：256 个 bin，归一化为 0-1 浮点
        assert "histogram" in data
        assert len(data["histogram"]) == 256
        assert all(0 <= v <= 1 for v in data["histogram"])
        assert 0 <= data["hist_peak"] <= 255
        assert data["min_value"] >= 0
        assert data["max_value"] >= data["min_value"]

    def test_all_params_16bit(self):
        """全参数测试 + 16-bit 输出"""
        png = _sample_png()
        if not png:
            pytest.skip("sample.png not found")
        with open(png, "rb") as f:
            resp = client.post(
                "/api/grayscale3d",
                data={
                    "image": (f, "sample.png"),
                    "invert": "1",
                    "contrast": "1.5",
                    "gamma": "0.9",
                    "smooth": "1",
                    "auto_levels": "1",
                    "bit_depth": "16",
                },
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["bit_depth"] == 16
        # 16-bit 图像通常比 8-bit 大
        assert data["size"] > 0
        # 直方图应仍然基于 8-bit（因为 histogram 在转换前计算）
        assert len(data["histogram"]) == 256


class TestRestart:
    """服务重启功能测试"""

    def test_restart_endpoint_exists(self):
        """重启端点应存在并返回有效响应"""
        # 验证端点可访问（200 表示脚本存在且可触发，404 表示脚本不存在）
        resp = client.post("/api/restart")
        # 不做断言，仅验证端点不会崩溃
        # 真实重启不在测试环境执行，避免影响其他测试
        assert resp.status_code in (200, 404)


class TestPantoneExport:
    """Pantone PDF 导出端点（P2-12b 重构后：swatch / report / palette 走共享渲染）"""

    def _authed(self):
        entry = keystore.generate(name="pdf-test")
        return entry["key"], entry["key_id"]

    def test_invalid_type(self):
        key, kid = self._authed()
        try:
            r = client.post(
                "/api/pantone/export",
                json={"type": "bogus"},
                headers={"x-api-key": key},
            )
            assert r.status_code == 400
            assert "Invalid type" in r.get_json()["error"]
        finally:
            keystore.revoke(kid)

    def test_swatch(self):
        key, kid = self._authed()
        try:
            r = client.post(
                "/api/pantone/export",
                json={
                    "type": "swatch",
                    "name": "PMS 485 C",
                    "hex": "#DA291C",
                    "cmyk": [0, 91, 84, 4],
                    "rgb": [218, 41, 28],
                },
                headers={"x-api-key": key},
            )
            assert r.status_code == 200
            assert r.data[:5] == b"%PDF-"
        finally:
            keystore.revoke(kid)

    def test_report(self):
        key, kid = self._authed()
        try:
            r = client.post(
                "/api/pantone/export",
                json={
                    "type": "report",
                    "input_hex": "#DA291C",
                    "matches": [
                        {"name": "PMS 485 C", "hex": "#DA291C",
                         "cmyk": [0, 91, 84, 4], "delta_e": 0.0}
                    ],
                },
                headers={"x-api-key": key},
            )
            assert r.status_code == 200
            assert r.data[:5] == b"%PDF-"
        finally:
            keystore.revoke(kid)

    def test_palette(self):
        key, kid = self._authed()
        try:
            r = client.post(
                "/api/pantone/export",
                json={
                    "type": "palette",
                    "svg_base64": "",
                    "palette": [
                        {"color": {"hex": "#DA291C", "rgb": [218, 41, 28], "share": 0.6},
                         "pantone_matches": [
                             {"name": "PMS 485 C", "hex": "#DA291C",
                              "cmyk": [0, 91, 84, 4], "delta_e": 0.5}
                         ]}
                    ],
                },
                headers={"x-api-key": key},
            )
            assert r.status_code == 200
            assert r.data[:5] == b"%PDF-"
        finally:
            keystore.revoke(kid)

    def test_null_optional_fields_do_not_500(self):
        """可选列表字段传 null 不得 500（P2-12b 边界健壮性修复）。"""
        key, kid = self._authed()
        try:
            r = client.post(
                "/api/pantone/export",
                json={"type": "report", "input_hex": "#DA291C", "matches": None},
                headers={"x-api-key": key},
            )
            assert r.status_code == 200
            assert r.data[:5] == b"%PDF-"
        finally:
            keystore.revoke(kid)
