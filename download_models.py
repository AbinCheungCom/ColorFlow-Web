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

import hashlib
import os
import socket
import sys
import urllib.request

MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

MODELS = {
    "silueta": {
        "file": "silueta.onnx",
        "url": "https://github.com/danielgatis/rembg/releases/download/v1.0/silueta.onnx",
        "size_mb": 42,
        "desc": "通用 · 快速（默认）",
        "sha256": "",  # 填入后启用完整性校验
    },
    "u2net_human_seg": {
        "file": "u2net_human_seg.onnx",
        "url": "https://github.com/danielgatis/rembg/releases/download/v1.0/u2net_human_seg.onnx",
        "size_mb": 168,
        "desc": "人像 · 精细",
        "sha256": "",
    },
}

_DOWNLOAD_TIMEOUT = 300  # 单次连接超时秒数


def _verify_sha256(path: str, expected: str) -> bool:
    """校验文件 sha256 摘要是否匹配。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest() == expected


def _download_with_timeout(url: str, target: str, size_mb: int):
    """下载 url 到 target（带超时 + 进度），避免 urlretrieve 无超时永久挂起。"""
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(_DOWNLOAD_TIMEOUT)
    try:
        with urllib.request.urlopen(url) as resp:
            total_hdr = resp.headers.get("Content-Length")
            total = int(total_hdr) if total_hdr else size_mb * 1024 * 1024
            downloaded = 0
            with open(target, "wb") as f:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    pct = downloaded / total * 100
                    mb = downloaded / 1024 / 1024
                    total_mb = total / 1024 / 1024
                    sys.stdout.write(f"\r    {mb:.1f} / {total_mb:.1f} MB ({pct:.1f}%)")
                    sys.stdout.flush()
    finally:
        socket.setdefaulttimeout(old)


def download_model(name: str, info: dict) -> bool:
    """下载单个模型到 models/ 目录（临时文件 + 原子替换 + 可选 sha256 校验）。"""
    target = os.path.join(MODELS_DIR, info["file"])
    expected_sha = info.get("sha256", "")

    if os.path.exists(target):
        if expected_sha and not _verify_sha256(target, expected_sha):
            print(f"  ✗ {info['file']} 已存在但 sha256 校验失败，重新下载")
        else:
            size = os.path.getsize(target)
            print(f"  ✓ {info['file']} 已存在 ({size/1024/1024:.1f} MB)")
            return True

    print(f"  下载 {info['file']} ({info['size_mb']} MB) — {info['desc']}")

    tmp_path = target + ".tmp"
    try:
        _download_with_timeout(info["url"], tmp_path, info["size_mb"])
        print()
        if expected_sha and not _verify_sha256(tmp_path, expected_sha):
            print(f"  ✗ {info['file']} sha256 校验失败（文件可能被篡改）")
            os.remove(tmp_path)
            return False
        os.replace(tmp_path, target)  # 原子替换，避免残留半截文件
        size = os.path.getsize(target)
        print(f"  ✓ {info['file']} 下载完成 ({size/1024/1024:.1f} MB)")
        return True
    except Exception as e:
        print(f"\n  ✗ 下载失败: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
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
