@echo off
chcp 65001 >nul
echo ========================================
echo   ColorFlow Web - Service Launcher
echo ========================================
echo.

cd /d "%~dp0"

REM 设置模型缓存目录（指向包内 models\，避免联网下载）
if exist "models" (
    set "U2NET_HOME=%~dp0models"
    echo [INFO] 模型目录: %U2NET_HOME%
)

REM 检查 venv 是否存在；不存在则引导创建
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo [ERROR] 未找到虚拟环境 .venv！
    echo 首次部署请执行以下命令：
    echo.
    echo    python -m venv .venv
    echo    .venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo.
    pause
    exit /b 1
)

echo.
echo [INFO] 启动 ColorFlow Web 服务...
echo [INFO] 访问地址: http://127.0.0.1:5000
echo.
echo [DEV MODE] 启动开发服务器，生产部署请用 serve.py
echo.

REM 启动 Flask 应用
.venv\Scripts\python.exe app.py

pause
