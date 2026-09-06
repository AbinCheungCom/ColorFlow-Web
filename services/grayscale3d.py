"""ColorFlow 共享服务 — 3D 灰度图生成（高度图 / 位移贴图）。

供 Web (app.py) 与 MCP (mcp_server.py) 共用，消除两份完全相同的灰度转换逻辑。
"""

import io as _io
import json as _json
from dataclasses import dataclass
from typing import Union


@dataclass
class Grey3DResult:
    """灰度图生成结果"""
    png_bytes: bytes
    width: int
    height: int
    bit_depth: int
    histogram: list = None  # 256 bin 归一化直方图（仅 Web 端使用）
    hist_peak: int = 0      # 直方图峰值 bin 索引（0-255）
    min_value: int = 0      # 直方图 bin 计数的最小值（非像素值范围）
    max_value: int = 0      # 直方图 bin 计数的最大值（非像素值范围）


def generate(
    image_bytes: bytes,
    invert: bool = False,
    contrast: float = 1.0,
    gamma: float = 1.0,
    smooth: float = 0.0,
    auto_levels: bool = False,
    bit_depth: int = 8,
    include_histogram: bool = True,
) -> Grey3DResult:
    """位图 → 3D 灰度 PNG。

    Args:
        image_bytes: 图片原始字节
        invert: 反色（黑=低 白=高）
        contrast: 对比度 0.5-3.0
        gamma: Gamma 校正 0.5-2.0
        smooth: 高斯模糊半径 0-5
        auto_levels: 自动级别归一化
        bit_depth: 输出位深 8 或 16
        include_histogram: 是否计算直方图（Web 端需要，MCP 端不需要）

    Returns:
        Grey3DResult 数据类
    """
    from PIL import Image, ImageOps, ImageEnhance, ImageFilter

    contrast = max(0.5, min(3.0, contrast))
    gamma = max(0.5, min(2.0, gamma))
    smooth = max(0.0, min(5.0, smooth))
    bit_depth = 16 if bit_depth == 16 else 8

    img = Image.open(_io.BytesIO(image_bytes)).convert("RGB")
    grey = img.convert("L")

    # 1) 高斯模糊
    if smooth > 0:
        grey = grey.filter(ImageFilter.GaussianBlur(radius=int(smooth)))

    # 2) 自动级别
    if auto_levels:
        grey = ImageOps.autocontrast(grey)

    # 3) 对比度
    if contrast != 1.0:
        grey = ImageEnhance.Contrast(grey).enhance(contrast)

    # 4) Gamma
    if gamma != 1.0:
        curve = [int(round(255 * ((p / 255.0) ** (1.0 / gamma)))) for p in range(256)]
        grey = grey.point(curve)

    # 5) 反色
    if invert:
        grey = ImageOps.invert(grey)

    # 6) 直方图（位深转换前计算）
    histogram = None
    hist_peak = 0
    min_val = 0
    max_val = 0
    if include_histogram:
        histogram_raw = grey.histogram()
        hist_bins = histogram_raw[:256] if len(histogram_raw) >= 256 else histogram_raw
        hist_total = sum(hist_bins) or 1
        histogram = [v / hist_total for v in hist_bins]
        hist_peak = max(range(len(hist_bins)), key=lambda i: hist_bins[i])
        min_val = min(hist_bins)
        max_val = max(hist_bins)

    # 7) 位深转换
    if bit_depth == 16:
        grey = grey.point(lambda p: p * 257).convert("I;16")

    buf = _io.BytesIO()
    grey.save(buf, format="PNG")

    return Grey3DResult(
        png_bytes=buf.getvalue(),
        width=grey.width,
        height=grey.height,
        bit_depth=bit_depth,
        histogram=histogram,
        hist_peak=hist_peak,
        min_value=min_val,
        max_value=max_val,
    )
