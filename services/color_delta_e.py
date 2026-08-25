"""ColorFlow 共享色彩服务 — ΔE 色差计算。

集中 CIE76 ΔE 实现，供 Web (app.py) 与 MCP (mcp_server.py) 共用，
消除此前两份实现的行为偏差，并为后续一次性升级为 ΔE2000
（见开发文档 P3-19）提供单一改动点。
"""

import math


def delta_e_cie76(lab1, lab2) -> float:
    """CIE76 ΔE：两 CIELAB 三元组间的欧氏距离。

    lab1 / lab2 为 (L, a, b) 可迭代对象（长度需一致）。
    返回浮点色差，值越大表示视觉差异越大。
    """
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(lab1, lab2)))
