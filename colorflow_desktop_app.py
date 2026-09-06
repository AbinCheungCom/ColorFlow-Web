# ColorFlow Desktop App — 原生桌面窗口
#
# 架构：
#   1. Flask 后端在后台线程启动
#   2. PyWebview 创建原生桌面窗口，加载 Flask 前端页面
#   3. 用户关闭窗口时自动停止 Flask 后端
#   4. 整个过程无浏览器标签页，完全原生窗口体验
#
# 打包: pyinstaller colorflow_desktop_app.spec

import sys
import os
import pathlib
import threading
import time
import traceback

LOG_PATH = pathlib.Path(os.environ.get("TEMP", ".")) / "colorflow_desktop.log"


def log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


# ============================================================
# PyInstaller 路径处理
# ============================================================
def get_base_dir():
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys._MEIPASS)
    return pathlib.Path(__file__).resolve().parent


def setup_environment():
    base_dir = get_base_dir()
    os.chdir(base_dir)
    log(f"工作目录: {base_dir}")

    models_dir = base_dir / "models"
    if models_dir.exists():
        os.environ["U2NET_HOME"] = str(models_dir)
        log(f"U2NET_HOME: {models_dir}")

    import tempfile
    output_dir = pathlib.Path(tempfile.gettempdir()) / "colorflow-output"
    output_dir.mkdir(exist_ok=True)
    os.environ["COLORFLOW_OUTPUT_DIR"] = str(output_dir)


# ============================================================
# Flask 后端管理
# ============================================================
def start_flask_backend():
    """在后台线程启动 Flask，等待端口就绪"""
    import app
    import http.client

    host = "127.0.0.1"
    port = int(os.getenv("PORT", "5000"))
    flask_thread = threading.Thread(
        target=lambda: app.app.run(host=host, port=port, debug=False),
        daemon=True,
    )
    flask_thread.start()
    log(f"Flask 线程已启动, 等待端口 {port} ...")

    for i in range(30):
        try:
            conn = http.client.HTTPConnection(host, port, timeout=2)
            conn.request("GET", "/")
            resp = conn.getresponse()
            conn.close()
            log(f"Flask 后端就绪: HTTP {resp.status}")
            return flask_thread
        except Exception:
            time.sleep(0.5)

    log("Flask 后端启动超时")
    return flask_thread


# ============================================================
# 主入口
# ============================================================
def main():
    try:
        log("=" * 40)
        log("ColorFlow Desktop 原生桌面应用启动")

        setup_environment()

        log("启动 Flask 后端...")
        start_flask_backend()
        time.sleep(1)

        log("初始化 PyWebview 窗口...")
        import webview

        port = int(os.getenv("PORT", "5000"))
        url = f"http://127.0.0.1:{port}"

        webview.create_window(
            title="ColorFlow - AI 矢量描图工具",
            url=url,
            width=1400,
            height=900,
            min_size=(1000, 700),
            resizable=True,
            fullscreen=False,
            confirm_close=True,
        )

        webview.start(debug=False)

    except Exception as e:
        err = traceback.format_exc()
        log(f"启动失败:\n{err}")
        print(f"[ERROR] ColorFlow 启动失败\n{err}")
        input("按回车退出...")
        sys.exit(1)


if __name__ == "__main__":
    main()
