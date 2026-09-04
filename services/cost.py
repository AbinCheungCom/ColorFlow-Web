"""ColorFlow 共享服务 — 印刷报价。

供 Web (app.py) 与 MCP (mcp_server.py) 共用，消除两份完全相同的报价逻辑。
"""

from mcp_print.tools.cost import print_cost_estimate


def quote(
    width_mm: float = 210.0,
    height_mm: float = 297.0,
    quantity: int = 1000,
    num_colors: int = 4,
    paper_gsm: float = 120.0,
    print_method: str = "offset",
) -> dict:
    """印刷报价，返回 USD 命名字段。

    Args:
        width_mm: 成品宽（mm）
        height_mm: 成品高（mm）
        quantity: 数量
        num_colors: 印刷色数
        paper_gsm: 纸张克重
        print_method: 印刷方式

    Returns:
        报价字典，含 ink_cost_usd/setup_cost_usd/paper_cost_usd/total_cost_usd/cost_per_unit_usd/currency/breakdown
    """
    result = print_cost_estimate(
        width_mm=width_mm,
        height_mm=height_mm,
        quantity=quantity,
        num_colors=num_colors,
        paper_gsm=paper_gsm,
        print_method=print_method,
    )
    return {
        "ink_cost_usd": result["ink_cost"],
        "setup_cost_usd": result["setup_cost"],
        "paper_cost_usd": result["paper_cost"],
        "total_cost_usd": result["total_cost"],
        "cost_per_unit_usd": result["cost_per_unit"],
        "currency": result["currency"],
        "breakdown": result["breakdown"],
    }
