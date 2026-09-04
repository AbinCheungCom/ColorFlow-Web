"""ColorFlow Prompt 模板库测试（Phase 4 · 行业预制 prompt → GEN）。

覆盖：
  - 模块级：list_categories / list_templates / get_template / render
  - API：/api/prompt-templates GET、/api/prompt-templates/<id> GET、/api/prompt-templates/render POST
  - MCP：prompt_templates / prompt_render
"""
import json

import pytest

from app import app
import prompt_templates as pt
from prompt_templates import (
    list_categories,
    list_templates,
    get_template,
    render,
    render_prompt,
    TemplateError,
    reload_templates,
)

client = app.test_client()


# ============================================================
# 模块级单元测试
# ============================================================

class TestListCategories:
    def test_returns_list(self):
        cats = list_categories()
        assert isinstance(cats, list)
        assert len(cats) >= 6

    def test_has_required_fields(self):
        for c in list_categories():
            assert "id" in c
            assert "name" in c
            assert "icon" in c


class TestListTemplates:
    def test_all_templates(self):
        tpls = list_templates()
        assert len(tpls) >= 10
        for t in tpls:
            assert "id" in t
            assert "name" in t
            assert "category" in t
            assert "param_names" in t

    def test_filter_by_category(self):
        tpls = list_templates(category="luxury")
        assert len(tpls) >= 1
        for t in tpls:
            assert t["category"] == "luxury"

    def test_filter_by_search(self):
        tpls = list_templates(search="礼盒")
        assert len(tpls) >= 1
        assert any("礼盒" in t["name"] for t in tpls)

    def test_empty_search(self):
        tpls = list_templates(search="zzzz_nonexistent")
        assert len(tpls) == 0


class TestGetTemplate:
    def test_existing(self):
        t = get_template("luxury_gift_box")
        assert t["id"] == "luxury_gift_box"
        assert "prompt" in t
        assert "params" in t
        assert len(t["params"]) >= 3

    def test_not_found(self):
        with pytest.raises(TemplateError) as ei:
            get_template("nonexistent_id")
        assert ei.value.code == "not_found"


class TestRender:
    def test_default_values(self):
        """无参数时用默认值渲染"""
        result = render("luxury_gift_box")
        assert result["prompt"]
        assert result["template_id"] == "luxury_gift_box"
        assert "params" in result
        # 不应有未替换的占位符
        assert "{" not in result["prompt"] or "}" not in result["prompt"]

    def test_custom_params(self):
        """自定义参数替换占位符"""
        result = render("luxury_gift_box", {
            "color": "navy blue",
            "finish": "gloss lamination",
            "detail": "silver foil stamping",
        })
        assert "navy blue" in result["prompt"]
        assert "gloss lamination" in result["prompt"]
        assert "silver foil stamping" in result["prompt"]
        # 其他参数用默认值
        assert "rigid tuck-end" in result["prompt"]  # shape 默认值

    def test_render_prompt_returns_string(self):
        """render_prompt 只返回字符串"""
        p = render_prompt("luxury_gift_box")
        assert isinstance(p, str)
        assert len(p) > 20

    def test_not_found(self):
        with pytest.raises(TemplateError) as ei:
            render("nonexistent_id")
        assert ei.value.code == "not_found"

    def test_all_templates_render_without_error(self):
        """所有模板都能用默认值渲染（不报错）"""
        tpls = list_templates()
        for t in tpls:
            result = render(t["id"])
            assert result["prompt"]
            assert t["id"] not in result["prompt"]  # 模板 id 不应出现在 prompt 中

    def test_params_are_reported(self):
        """渲染结果报告实际使用的参数值"""
        result = render("luxury_gift_box", {"color": "emerald green"})
        params = result["params"]
        assert "color" in params
        assert params["color"]["value"] == "emerald green"
        assert "default" in params["color"]


# ============================================================
# API 测试
# ============================================================

class TestTemplatesAPI:
    def test_list_all(self):
        resp = client.get("/api/prompt-templates")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["templates"]) >= 10
        assert len(data["categories"]) >= 6
        assert data["count"] == len(data["templates"])

    def test_filter_category(self):
        resp = client.get("/api/prompt-templates?category=luxury")
        data = resp.get_json()
        assert data["success"] is True
        assert all(t["category"] == "luxury" for t in data["templates"])

    def test_filter_search(self):
        resp = client.get("/api/prompt-templates?search=food")
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["templates"]) >= 1

    def test_detail_exists(self):
        resp = client.get("/api/prompt-templates/luxury_gift_box")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["template"]["id"] == "luxury_gift_box"
        assert "params" in data["template"]

    def test_detail_not_found(self):
        resp = client.get("/api/prompt-templates/nonexistent")
        assert resp.status_code == 404

    def test_render_json(self):
        resp = client.post("/api/prompt-templates/render",
                           json={"template_id": "luxury_gift_box",
                                 "params": {"color": "navy blue"}})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "navy blue" in data["prompt"]
        assert data["template_id"] == "luxury_gift_box"

    def test_render_form(self):
        resp = client.post("/api/prompt-templates/render",
                           data={"template_id": "luxury_gift_box",
                                 "param_color": "emerald green"},
                           content_type="multipart/form-data")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "emerald green" in data["prompt"]

    def test_render_no_template_id(self):
        resp = client.post("/api/prompt-templates/render", json={})
        assert resp.status_code == 400

    def test_render_not_found(self):
        resp = client.post("/api/prompt-templates/render",
                           json={"template_id": "nonexistent"})
        assert resp.status_code == 404


# ============================================================
# MCP 工具测试
# ============================================================

class TestMCPPromptTemplates:
    def test_prompt_templates_registered(self):
        import mcp_server as ms
        assert callable(ms.prompt_templates)

    def test_prompt_render_registered(self):
        import mcp_server as ms
        assert callable(ms.prompt_render)

    def test_prompt_templates_all(self):
        import mcp_server as ms
        data = json.loads(ms.prompt_templates())
        assert data["success"] is True
        assert len(data["templates"]) >= 10

    def test_prompt_templates_filter(self):
        import mcp_server as ms
        data = json.loads(ms.prompt_templates(category="luxury"))
        assert data["success"] is True
        assert all(t["category"] == "luxury" for t in data["templates"])

    def test_prompt_render_success(self):
        import mcp_server as ms
        data = json.loads(ms.prompt_render("luxury_gift_box"))
        assert data["success"] is True
        assert data["prompt"]
        assert data["template_id"] == "luxury_gift_box"

    def test_prompt_render_with_params(self):
        import mcp_server as ms
        params = json.dumps({"color": "navy blue", "finish": "gloss lamination"})
        data = json.loads(ms.prompt_render("luxury_gift_box", params))
        assert data["success"] is True
        assert "navy blue" in data["prompt"]

    def test_prompt_render_bad_json(self):
        import mcp_server as ms
        data = json.loads(ms.prompt_render("luxury_gift_box", "not json"))
        assert data.get("error")

    def test_prompt_render_empty_id(self):
        import mcp_server as ms
        data = json.loads(ms.prompt_render(""))
        assert data.get("error")

    def test_prompt_render_not_found(self):
        import mcp_server as ms
        data = json.loads(ms.prompt_render("nonexistent"))
        assert data.get("error")
        assert data["code"] == "not_found"
