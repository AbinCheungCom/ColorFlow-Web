#!/usr/bin/env python3
"""ColorFlow 生产入口 — waitress WSGI 服务器（Windows/Linux 通用）。

用法：
    python serve.py                              # 默认 0.0.0.0:5000
    PORT=8080 THREADS=8 python serve.py          # 自定义端口/线程
    WAITRESS_CHANNEL_TIMEOUT=30 python serve.py  # keepalive 调优

环境变量：
    PORT                    监听端口（默认 5000）
    THREADS                 工作线程数（默认 4；CPU 密集型建议 2-8）
    WAITRESS_CHANNEL_TIMEOUT 连接 keepalive 秒数（默认 75）
    WAITRESS_BACKLOG        监听队列（默认 50）
    WAITRESS_CLEANUP_INTERVAL 空闲连接清理间隔秒（默认 1）
    FLASK_ENV               flask 环境变量（不用于 waitress 自身）

与 app.py 的区别：
    - app.py 的 __main__ 用 flask dev server（debug=True，热重载，**不适合生产**）
    - serve.py 用 waitress（生产级 WSGI，多线程，无热重载，适合 Windows/Linux 生产）
    - 桌面封装走 colorflow_desktop_app.py（PyWebview 窗口 + Flask 线程）

健康检查：GET /healthz（不经 /api/* 鉴权）
"""

import os
import sys


def main():
    from waitress import serve
    from app import app

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    threads = int(os.getenv("THREADS", "4"))
    channel_timeout = int(os.getenv("WAITRESS_CHANNEL_TIMEOUT", "75"))
    backlog = int(os.getenv("WAITRESS_BACKLOG", "50"))
    cleanup_interval = int(os.getenv("WAITRESS_CLEANUP_INTERVAL", "1"))

    # 桌面/容器环境：把 SDK 抠图模型指向包内 models/（与 colorflow_desktop_app.py 一致）
    # 仅在 U2NET_HOME 未设置时生效；已显式设置的（如开发机已下载模型）不覆盖
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if not os.getenv("U2NET_HOME"):
        bundled_models = os.path.join(base_dir, "models")
        if os.path.isdir(bundled_models):
            os.environ["U2NET_HOME"] = bundled_models
            print(f"[serve] U2NET_HOME -> {bundled_models}")

    # 输出目录：默认 /tmp，容器内建议挂载卷
    output_dir = os.getenv("COLORFLOW_OUTPUT_DIR", "/tmp/colorflow-output")
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    print(f"[serve] waitress on {host}:{port}, threads={threads}")
    print(f"[serve] health check: GET http://{host}:{port}/healthz")
    print(f"[serve] model dir: {os.getenv('U2NET_HOME', '(default ~/.u2net)')}")
    print(f"[serve] output dir: {output_dir}")

    serve(
        app,
        host=host,
        port=port,
        threads=threads,
        backlog=backlog,
        cleanup_interval=cleanup_interval,
        channel_timeout=channel_timeout,
    )


if __name__ == "__main__":
    sys.exit(main())
