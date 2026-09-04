"""ColorFlow 共享服务 — Pantone 色库分页查询。

供 Web (app.py) 与 MCP (mcp_server.py) 共用，消除两份完全相同的分页+搜索逻辑。
"""

from mcp_print.tools.colors import _load_db


def list_colors(page: int = 1, limit: int = 50, search: str = "") -> dict:
    """分页查询 Pantone 色库，支持按色名模糊搜索。

    Args:
        page: 页码（从 1 开始，最小 1）
        limit: 每页数量（1-200，默认 50）
        search: 搜索关键词（按色名模糊匹配）

    Returns:
        分页结果字典: items/total/page/limit/pages
    """
    page = max(page, 1)
    limit = min(max(limit, 1), 200)

    db = _load_db()

    if search:
        s = search.lower()
        db = [c for c in db if s in c.get("name", "").lower()]

    total = len(db)
    start = (page - 1) * limit
    end = start + limit

    return {
        "items": db[start:end],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }
