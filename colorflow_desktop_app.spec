# PyInstaller 打包配置 — ColorFlow Desktop 原生应用
# 用法: .venv\Scripts\pyinstaller.exe colorflow_desktop_app.spec
#
# 说明：BASE_DIR 相对计算（从本 .spec 文件位置推导），保证在任意目录
# 运行或 CI 中都能定位项目源码，避免硬编码绝对路径。

import os

HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = HERE
ENTRY = os.path.join(BASE_DIR, "colorflow_desktop_app.py")

datas = [
    (os.path.join(BASE_DIR, "templates"), "templates"),
    (os.path.join(BASE_DIR, "static"), "static"),
    (os.path.join(BASE_DIR, "assets"), "assets"),     # ComfyUI 工作流模板
    (os.path.join(BASE_DIR, "models"), "models"),     # silueta.onnx（42MB，随包）
]

hiddenimports = [
    # 桌面窗口
    "flask", "jinja2", "markupsafe", "werkzeug",
    "webview", "webview.gui", "webview.http", "webview.settings",
    "pythonnet", "clr_loader", "bottle",
    # 图像 / 抠图 / 描图
    "numpy", "PIL", "PIL.Image", "PIL.ImageFilter", "PIL.ImageOps",
    "PIL.ImageEnhance", "PIL.ImageDraw", "PIL.ImageFont",
    "onnxruntime", "onnxruntime.capi",
    "lxml", "svglib", "reportlab", "reportlab.lib", "reportlab.pdfgen",
    "reportlab.graphics",
    # 项目自研模块（本地模块需显式声明，防 PyInstaller 静态分析遗漏）
    "gen_backends",
    "vision_backends",
    "prompt_templates",
    "prompt_optimizer",
    "services", "services.color_delta_e", "services.color_pdf",
    "colorflow_keys",
    "llm_keys",
    "colorflow_sdk", "colorflow_sdk.exceptions",
    "mcp_print", "mcp_print.tools.colors", "mcp_print.tools.cost", "mcp_print.tools",
    "rembg",
]

a = Analysis(
    [ENTRY],
    pathex=[BASE_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "pytest",
        "PySide6", "PyQt6", "PyQt5",
        "docx",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ColorFlow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    noconsole=True,
    icon=os.path.join(BASE_DIR, "colorflow.ico"),
    cipher_block="AES",
    disable_windowed_traceback=False,
)
