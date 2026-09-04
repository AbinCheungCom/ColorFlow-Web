#!/usr/bin/env python3
"""ColorFlow 模型下载脚本。

下载 rembg 抠图模型到 models/ 目录（168MB，不入 git）。

用法：
    python download_models.py                    # 下载所有缺失模型
    python download_models.py u2net_human_seg    # 仅下载指定模型

模型列表：
    - silueta.onnx         (42MB)  通用 · 快速（已随仓库附带）
    - u2net_human_seg.onnx (168MB) 人像 · 精细（需手动下载）

模型源：https://github.com/danielgatis/rembg/releases
"""

import os
import sys
import urllib.request

MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

MODELS = {
    "silueta": {
        "file": "silueta.onnx",
        "url": "https://github.com/danielgatis/rembg/releases/download/v1.0/silueta.onnx",
        "size_mb": 42,
        "desc": "通用 · 快速（默认）",
    },
    "u2net_human_seg": {
        "file": "u2net_human_seg.onnx",
        "url": "https://github.com/danielgatis/rembg/releases/download/v1.0/u2net_human_seg.onnx",
        "size_mb": 168,
        "desc": "人像 · 精细",
    },
}


def download_model(name: str, info: dict) -> bool:
    """下载单个模型到 models/ 目录。"""
    target = os.path.join(MODELS_DIR, info["file"])

    if os.path.exists(target):
        size = os.path.getsize(target)
        print(f"  ✓ {info['file']} 已存在 ({size/1024/1024:.1f} MB)")
        return True

    print(f"  下载 {info['file']} ({info['size_mb']} MB) — {info['desc']}")

    def hook(count, block_size, total_size):
        downloaded = count * block_size
        if total_size > 0:
            pct = downloaded / total_size * 100
            mb = downloaded / 1024 / 1024
            total_mb = total_size / 1024 / 1024
            sys.stdout.write(f"\r    {mb:.1f} / {total_mb:.1f} MB ({pct:.1f}%)")
            sys.stdout.flush()

    try:
        urllib.request.urlretrieve(info["url"], target, hook)
        print()
        size = os.path.getsize(target)
        print(f"  ✓ {info['file']} 下载完成 ({size/1024/1024:.1f} MB)")
        return True
    except Exception as e:
        print(f"\n  ✗ 下载失败: {e}")
        # 清理不完整文件
        if os.path.exists(target):
            os.remove(target)
        return False


def main():
    os.makedirs(MODELS_DIR, exist_ok=True)

    # 解析命令行参数
    if len(sys.argv) > 1:
        requested = sys.argv[1]
        if requested not in MODELS:
            print(f"未知模型: {requested}")
            print(f"可选: {', '.join(MODELS.keys())}")
            sys.exit(1)
        models_to_download = {requested: MODELS[requested]}
    else:
        models_to_download = MODELS

    print(f"\nColorFlow 模型下载")
    print(f"目标目录: {MODELS_DIR}\n")

    success = 0
    for name, info in models_to_download.items():
        if download_model(name, info):
            success += 1

    print(f"\n完成: {success}/{len(models_to_download)} 模型就绪")


if __name__ == "__main__":
    main()
