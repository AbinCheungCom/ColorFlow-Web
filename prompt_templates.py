"""ColorFlow Prompt 模板库 — 行业预制 prompt → GEN 生图。

设计目标：
  - 加载 assets/prompt_templates.json，按 category 分组索引
  - render(template_id, params) → 完整英文 prompt（{placeholder} 替换）
  - 前端下拉选模板 → 填参数 → 回填 prompt 框 → 生图
  - MCP 工具 prompt_template(category) 返回模板清单，prompt_render(id, params) 渲染

红线：
  - 模板文件随仓库分发，不依赖网络
  - 渲染纯 CPU 字符串操作，零延迟
  - 参数缺失时用模板默认值，绝不报 KeyError
"""

import json
import os

# ── 模板文件路径 ──────────────────────────────────────
_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "assets", "prompt_templates.json",
)


class TemplateError(Exception):
    """模板相关错误"""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code  # not_found / invalid_params / file_error


# ── 模块级缓存 ──────────────────────────────────────
_cache = None
_cache_path = None


def _load(path: str = None):
    """加载并缓存模板 JSON。文件变更时（mtime 不同）重新加载。"""
    global _cache, _cache_path
    p = path or _TEMPLATE_PATH
    if _cache is not None and _cache_path == p:
        return _cache
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        raise TemplateError("file_error", f"模板文件加载失败: {e}")
    _cache = data
    _cache_path = p
    return data


def reload_templates(path: str = None):
    """强制重新加载模板（测试用）"""
    global _cache, _cache_path
    _cache = None
    _cache_path = None
    return _load(path)


# ============================================================
# 查询接口
# ============================================================

def list_categories() -> list:
    """返回所有分类（[{id, name, icon}]）"""
    data = _load()
    return data.get("categories", [])


def list_templates(category: str = None, search: str = None) -> list:
    """列出模板，可按 category / search 过滤。

    Returns:
        [{id, name, category, description, param_names: [...]}, ...]
        （不含 prompt 原文和完整 params，避免前端 payload 过大）
    """
    data = _load()
    templates = data.get("templates", [])
    result = []
    for t in templates:
        if category and t.get("category") != category:
            continue
        if search:
            s = search.lower()
            if (s not in t.get("name", "").lower()
                    and s not in t.get("description", "").lower()
                    and s not in t.get("id", "").lower()):
                continue
        result.append({
            "id": t["id"],
            "name": t["name"],
            "category": t["category"],
            "description": t.get("description", ""),
            "param_names": list(t.get("params", {}).keys()),
        })
    return result


def get_template(template_id: str) -> dict:
    """获取单个模板完整定义（含 prompt 原文和 params）。"""
    data = _load()
    for t in data.get("templates", []):
        if t["id"] == template_id:
            return t
    raise TemplateError("not_found", f"模板不存在: {template_id}")


# ============================================================
# 渲染
# ============================================================

def render(template_id: str, params: dict = None) -> dict:
    """渲染模板 → 完整 prompt。

    Args:
        template_id: 模板 id（如 luxury_gift_box）
        params: {param_name: value}，缺失时用模板默认值

    Returns:
        {prompt, template_id, template_name, params: {name: {value, default}},
         placeholders: {name: value}}
    """
    t = get_template(template_id)
    params = params or {}
    t_params = t.get("params", {})

    # 收集实际使用的值
    used = {}
    defaults = {}
    for pname, pdef in t_params.items():
        default = pdef.get("default", "")
        value = params.get(pname, default)
        used[pname] = value
        defaults[pname] = default

    # 渲染 prompt（逐占位符替换，避免 str.format 的 KeyError）
    prompt = t["prompt"]
    for pname, value in used.items():
        prompt = prompt.replace("{" + pname + "}", str(value))

    # 检查是否有未替换的占位符（说明模板和 params 不一致）
    import re
    remaining = re.findall(r"\{(\w+)\}", prompt)
    if remaining:
        raise TemplateError(
            "invalid_params",
            f"占位符未替换: {', '.join(remaining)}"
        )

    return {
        "prompt": prompt,
        "template_id": template_id,
        "template_name": t["name"],
        "params": {
            pname: {"value": used[pname], "default": defaults[pname]}
            for pname in t_params
        },
    }


def render_prompt(template_id: str, params: dict = None) -> str:
    """只返回渲染后的 prompt 字符串（MCP 工具用）"""
    return render(template_id, params)["prompt"]
