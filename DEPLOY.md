# ColorFlow Web 部署说明

## 系统要求

| 项 | 要求 |
|---|---|
| Python | **3.11+**（推荐 3.11，已用 3.11.15 验证） |
| 操作系统 | Windows / Linux / macOS |
| 内存 | ≥ 1GB（rembg 抠图推理需要） |
| 网络 | 首次安装依赖需要联网（建议国内使用清华镜像） |

## 安装（首次部署）

```bash
# 1. 创建虚拟环境
python -m venv .venv

# 2. 安装依赖（国内用清华镜像加速）
.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
# Linux/macOS: .venv/bin/python -m pip install -r requirements.txt

# 3. （可选）验证模型
#    models\silueta.onnx 已随包附带，启动脚本会自动设置 U2NET_HOME
```

## 启动

### Windows
双击 **`start.bat`**（会自动检测 venv 并设置模型目录）。

### 手动启动
```bash
.venv\Scripts\python.exe app.py
# 或 Linux/macOS: .venv/bin/python app.py
```

访问 **http://127.0.0.1:5000**

## 功能说明

| 功能 | 说明 |
|---|---|
| 位图抠图 | rembg（silueta 模型），输出透明 PNG |
| 矢量描图 | VTracer 位图转 SVG，支持忽略白色输出透明 SVG |
| 抠图 + 描图 | 一键串联：抠图去背景 → 合成白底描图 → 输出透明 SVG |
| Pantone 查色 | 色号 → CMYK/HEX/RGB |
| 色彩匹配 | HEX → 最近 Pantone 色（ΔE），一键提取主色 + 匹配 |
| 印刷 PDF 导出 | 位图 → 印刷级 CMYK PDF（含出血 + 物理尺寸）|
| 色卡 / 报告 PDF | 单色色卡 / 匹配报告 / 主色提取报告（CMYK 印刷级）|
| 3D 灰度图 | 位图 → 8/16-bit 灰度高度图 / 位移贴图，含直方图 |
| AI 生图 | 一句话生成包装效果图（零本地 GPU），直接送下游流水线 |
| MCP Server | 12 个工具，Claude Code / Cursor 可直接调用 |
| 一句话流水线 | full_pipeline：生图→抠图→描图→Pantone→报价→生产文件 ZIP |

## 模型说明

- 抠图模型 `models\silueta.onnx`（42MB）已包含在包内
- 若删除该文件，首次抠图会自动尝试从 GitHub 下载（国内可能很慢），可用以下镜像手动下载：
  ```
  https://gh.ddlc.top/https://github.com/danielgatis/rembg/releases/download/v0.0.0/silueta.onnx
  ```
- 模型缓存目录由环境变量 `U2NET_HOME` 控制（默认 `%USERPROFILE%\.u2net`）

## 可选环境变量

| 变量 | 作用 |
|---|---|
| `COLORFLOW_API_KEY` | 设置后启用 `/api/*` 接口鉴权 |
| `PORT` | 自定义端口（默认 5000） |
| `FLASK_DEBUG` | 是否开启 Debug 模式（生产不要开） |
| `VOLCANO_API_KEY` | 火山方舟 / 即梦 Seedream 生图 Key（配置后启用 volcano 后端）|
| `FAL_KEY` | fal.ai 生图 Key（配置后启用 fal 后端）|
| `COMFYUI_URL` | 本地 ComfyUI 地址，如 `http://127.0.0.1:8188`（配置后启用 comfyui 后端）|
| `GEN_DEFAULT_BACKEND` | 默认生图后端（auto / volcano / fal / comfyui，默认 auto）|
| `GEN_TIMEOUT` | 生图超时秒数（默认 120）|
| `GEN_MAX_IMAGES` | 单次最多生成张数（默认 4）|
| `COLORFLOW_UPLOAD_DIR` | 上传临时目录（桌面封装时自动设置）|

> 生图后端为**可插拔**：配置一个或多个 Key 即可，未配置的任何后端不影响既有功能。
> 详见 README 的「AI 生图（GEN 适配器层）」章节。

## 桌面打包（PyWebview + PyInstaller）

把 Web 应用打成原生桌面窗口（无浏览器标签页），适合非技术用户分发。

```bash
# 1. 安装桌面依赖（Windows）
.venv\Scripts\python.exe -m pip install -r requirements-desktop.txt

# 2. 打包
.venv\Scripts\pyinstaller.exe colorflow_desktop_app.spec

# 3. 运行
dist\ColorFlow.exe
```

打包要点：
- 输出单文件 exe 约 **200–300MB**（含 silueta.onnx 抠图模型 + onnxruntime）
- `U2NET_HOME` 自动指向包内 `models/`，**完全离线可用，无需联网下载模型**
- Windows 依赖 **Edge WebView2**（Win10/11 已内置；老系统需安装）
- 桌面入口 `colorflow_desktop_app.py` 在后台线程启动 Flask，窗口关闭即停后端
- 上传/输出目录自动指向系统临时目录（`COLORFLOW_UPLOAD_DIR` / `COLORFLOW_OUTPUT_DIR`）
- 详细评估见 `doc/ColorFlow-Web-桌面应用封装可行性评估.md`

## 生产部署提示

Flask 内置服务器仅适合本地/内网使用。生产环境建议：

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```
（Windows 上可用 waitress 替代 gunicorn）
