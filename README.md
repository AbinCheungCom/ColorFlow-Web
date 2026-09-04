# ColorFlow Web

> AI 位图抠图 + 矢量描图 + Pantone 色彩管理 — 一个页面搞定从位图到透明 PNG / SVG / 印刷落地

<!-- 徽标区 -->
<p align="center">
  <a href="https://opensource.org/licenses/MIT"><img alt="License" src="https://img.shields.io/badge/License-MIT-yellow.svg"></a>
  <a href="https://www.python.org/downloads/"><img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white"></a>
  <a href="https://github.com/Abinius/ColorFlow-Web/releases"><img alt="Version" src="https://img.shields.io/github/v/tag/Abinius/ColorFlow-Web?sort=semver&label=release&color=blue"></a>
  <a href="https://github.com/Abinius/ColorFlow-Web/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/Abinius/ColorFlow-Web/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="Tests" src="https://img.shields.io/badge/tests-212%20passed-brightgreen.svg">
  <img alt="MCP Tools" src="https://img.shields.io/badge/MCP%20Tools-17-7B61FF">
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg">
  <img alt="GPU" src="https://img.shields.io/badge/GPU-0%20local%20inference-important.svg">
  <img alt="Stack" src="https://img.shields.io/badge/Stack-Flask%20%2F%20rembg%20%2F%20VTracer%20%2F%20Pantone-24423b.svg">
</p>
<p align="center">
  <a href="https://github.com/Abinius/ColorFlow-Web/issues"><img alt="Issues" src="https://img.shields.io/github/issues/Abinius/ColorFlow-Web?color=red"></a>
  <a href="https://github.com/Abinius/ColorFlow-Web/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/Abinius/ColorFlow-Web?style=social"></a>
  <a href="https://github.com/Abinius/ColorFlow-Web"><img alt="Repo" src="https://img.shields.io/github/repo-size/Abinius/ColorFlow-Web?color=blueviolet"></a>
  <a href="https://github.com/Abinius/ColorFlow-Web/commits/main"><img alt="Last Commit" src="https://img.shields.io/github/last-commit/Abinius/ColorFlow-Web?color=orange"></a>
</p>

## 定位

ColorFlow Web 是 **ColorFlow 矢量描图 SDK** 和 **Pantone 色彩管理** 的 Web 前端界面，开源可免费部署。将 AI 位图抠图、矢量描图、Pantone 色号匹配、Delta E 色彩偏差计算聚合在一个页面中。

界面采用 **Figma DESIGN.md 设计规范**（黑白编辑风 + 巨型 pastel 色块 + 药丸按钮），布局为 **DeepSeek Harness 式左栏导航 + 内容工作区**双栏结构，移动端自动折叠为抽屉式菜单。

## 功能

| 功能 | 说明 |
|------|------|
| **位图抠图** | 上传位图，rembg AI 移除背景，8 模型可选 + Alpha Matting 边缘细化，输出**透明 PNG** |
| **矢量描图** | 上传位图（PNG/JPG/WebP/BMP），VTracer 转 SVG，10 个精度参数可调 |
| **忽略白色** | 描图后自动去除白色路径，输出透明背景 SVG（容差可调） |
| **Pantone 查色** | 输入 Pantone 色号，一键获取 HEX / CMYK / RGB 值 |
| **色彩匹配** | 输入 HEX，自动匹配最近的 5 个 Pantone 色 + ΔE 色彩偏差 |
| **一键流水线** | 描图后自动提取主色 → 逐一匹配 Pantone |
| **印刷 PDF 导出** | 位图 → 生产印刷级 CMYK PDF（含出血 + 物理尺寸） |
| **Pantone 色卡导出** | 色号查询详情一键导出色卡 PDF；匹配结果导出报告 PDF（CMYK 印刷级）|
| **API Key 管理** | 设置页一键生成 / 撤销 Key，Web API 与 MCP 共用 |
| **3D 灰度图** | 彩色位图 → 灰度高度图 / 位移贴图（8/16-bit），用于 3D 建模（Blender / 3D 打印 / 深度通道）+ 实时直方图 |
| **服务重启** | 设置页「重启服务」按钮一键重启 Flask 实例 |
| **AI 生图** | 一句话生成包装效果图（火山方舟 / fal.ai / ComfyUI 三后端 auto 降级，零本地 GPU），生成图直接送抠图 / 描图 / Pantone 流水线 |
| **批量生图** | 一次提交多个 prompt（换行分隔）批量生成，异步任务 + 进度轮询 |
| **图→prompt 反向闭环** | 上传参考图 → 多模态大模型（OpenAI gpt-4o / Claude / mock）自动描述 → 回填 prompt → 一键生图，完成「图→prompt→生图→描图→Pantone」全闭环 |
| **Prompt 优化** | 「✨ 优化」一键把中文/短 prompt 增强为结构化英文（OpenAI，mock 降级）|
| **行业模板库** | 12 个预制 prompt 模板 · 6 分类（奢侈品/食品/美妆/电子/文具/促销），支持参数化渲染 |
| **模板市场** | 自定义模板 + 导入 / 导出 JSON |
| **参考图库** | 保存/复用参考图（localStorage），点击即加载到反向闭环 |
| **LLM API Key 管理** | 设置页持久化管理 5 家模型商（OpenAI/Claude/火山/fal/ComfyUI）的 Key + Base URL + **模型名**，保存即生效、重启不丢（不再硬编码 / 不依赖环境变量）|
| **AI Agent 接入** | 内置 MCP Server（17 工具），Claude Code / Cursor 可直接调用 |

## 第三方技术核心清单

ColorFlow Web 依赖的第三方技术与开源项目（按使用场景分类）：

| 场景 | 技术 / 项目 | 版本 | 许可证 | 核心作用 |
|------|------------|------|--------|---------|
| Web 后端 | [Flask](https://flask.palletsprojects.com/) | ≥3.0 | BSD-3-Clause | 全部 API 路由 + 模板渲染 |
| WSGI 服务 | [waitress](https://github.com/Pylons/waitress) | ≥3.0 | ZPL-2.0 | 生产级 WSGI（Windows/Linux 通用，见 `serve.py`）|
| AI 抠图 | [rembg](https://github.com/danielgatis/rembg) + [onnxruntime](https://onnxruntime.ai/) | ≥2.0 | MIT | silueta/u2net ONNX 模型，CPU 推理移除背景（模型 42MB 随包）|
| 矢量描图 | [VTracer](https://github.com/visioncortex/vtracer) | Rust | MIT | 位图 → SVG 矢量描图（经 ColorFlow SDK 调用）|
| 图像处理 | [Pillow](https://python-pillow.org/) | — | HPND | PNG/JPG/WebP 格式转码、3D 灰度图、PDF 配图 |
| 色彩数据 | [mcp-print](https://github.com/kcgdz/mcp-print) | ≥0.1 | — | 2415 Pantone 色库、CMYK/ΔE 计算、印刷报价 |
| 矢量 SDK | [ColorFlow SDK](https://github.com/Abinius/ColorFlow) | git+ | — | 矢量描图/忽略白色/主色提取（本仓库核心引擎）|
| PDF 输出 | [reportlab](https://www.reportlab.com/) | ≥4.0 | BSD | 印刷级 CMYK PDF 生成 |
| SVG→PDF | [svglib](https://github.com/deeplook/svglib) | ≥1.5 | LGPL-3.0 | SVG 矢量图渲染进 PDF（export_print）|
| MCP 协议 | [FastMCP](https://github.com/jlowin/fastmcp) | ≥2.0 | MIT | MCP Server（17 工具，Agent 标准接入）|
| 前端 | 原生 HTML + CSS + JS | — | — | 零框架依赖（无 React/Vue/构建链）|
| 前端字体 | [Google Fonts: Inter + JetBrains Mono](https://fonts.google.com/) | — | OFL-1.1 | Figma DESIGN.md 设计规范的字体 |
| 工作流 CI | [GitHub Actions](https://github.com/features/actions) | — | — | pytest + 产物（`.github/workflows/ci.yml`）|

> 说明：PyInstaller 桌面打包另见 `requirements-desktop.txt`（pywebview + pythonnet + bottle）。全部模型推理为零本地 GPU（CPU / 云端 API）。

## 快速启动

### 前提

- **Python 3.11+**
- 国内网络建议使用清华镜像加速依赖安装

```bash
# 1. 创建虚拟环境
python -m venv .venv

# 2. 安装依赖（国内镜像）
.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> 注意：`colorflow-sdk` 未发布到 PyPI，requirements.txt 已内置 `git+` 引用，会自动从 GitHub 安装。若网络受限，可本地安装：`pip install -e /path/to/ColorFlow`。

### 运行

```bash
# Windows 一键启动
start.bat

# 或手动
.venv\Scripts\python.exe app.py
# → http://localhost:5000
```

### 抠图模型

- 抠图模型 `models/silueta.onnx`（42MB）已随仓库附带，启动时自动设置 `U2NET_HOME` 指向包内目录，**无需联网下载**。
- 若模型缺失，首次抠图会尝试从 GitHub 下载（国内可能很慢），可用镜像：
  ```
  https://gh.ddlc.top/https://github.com/danielgatis/rembg/releases/download/v0.0.0/silueta.onnx
  ```

## AI 生图（GEN 适配器层）

一句话生成包装效果图，**零本地 GPU**（调用云端图像大模型 API，本地仅做 Pillow 格式转码）。生成的 PNG 可直接送下游抠图 / 描图 / Pantone 流水线。

### 后端（按优先级 auto 降级）

| 后端 | 设置页 provider | 环境变量（备选） | 默认模型 |
|------|----------------|-----------------|---------|
| volcano | `火山方舟 · 即梦` | `VOLCANO_API_KEY` | `doubao-seedream-4-0-t2i` |
| fal | `fal.ai` | `FAL_KEY` | `fal-ai/flux-pro/v1.1` |
| comfyui | `本地 ComfyUI` | `COMFYUI_URL` | 本地工作流（URL 即配置） |

**推荐配置方式：设置页 → 「大模型 API」→ 对应 provider 填 Key + Base URL + 模型名 → 保存**。Key 持久化到 `~/.colorflow/llm_keys.json`（0600），**保存即生效、重启不丢**，无需设置环境变量。

模型名读取优先级：**设置页配置的 model → 环境变量（`VOLCANO_MODEL` / `FAL_MODEL`）→ 后端默认**。`backend=auto` 时按 `volcano → fal → comfyui` 探测，失败且 `retryable` 自动降级到下一后端，绝不假成功。

### 可选环境变量

```bash
export GEN_DEFAULT_BACKEND=auto   # 默认后端（auto/volcano/fal/comfyui）
export GEN_TIMEOUT=120            # 超时秒数
export GEN_MAX_IMAGES=4           # 单次最多张数
```

### 示例

```bash
# AI 生图 → PNG（base64，同步版，适合生图 <30s）
curl -X POST http://localhost:5000/api/generate \
  -F "prompt=红色天地盖礼盒，烫金logo，哑光，电商白底" \
  -F "backend=auto" \
  -F "size=1024x1024"

# AI 生图 → 异步任务（生图 10–60s 推荐，避免网关超时）
JOB=$(curl -s -X POST http://localhost:5000/api/generate/jobs \
  -F "prompt=红色天地盖礼盒，烫金logo" -F "backend=auto" | jq -r .job_id)
curl http://localhost:5000/api/generate/jobs/$JOB
# → {"status":"queued|running|done|failed", ...}  done 时携带 images

# 查看已配置的生图后端
curl http://localhost:5000/api/generate/backends
```

> 生成图为灵感稿，印刷请走右侧生产链路。无后端 Key 时返回 401 明确提示。
> 前端 Tab 6 统一走任务模式（提交 → 轮询，2s 间隔，3 分钟超时），进度文案实时刷新。
> 任务存储为进程内（单进程 Flask）；多 worker 生产部署需换共享存储（Redis/DB）。

## 图→prompt（VISION 适配器层 · image2prompt 反向闭环）

与 GEN 对称设计：上传一张图 → 多模态大模型描述 → 返回结构化英文 prompt，前端可直接回填到 GEN 提示词框。对应 [docs/03-工作流集成方案.md](docs/03-工作流集成方案.md) 方案 B（P1），补齐「图→prompt→生图→描图→Pantone→报价→ZIP」全闭环。

### 后端（按优先级 auto 降级）

| 后端 | 设置页 provider | 环境变量（备选） | 默认模型 |
|------|----------------|-----------------|---------|
| openai | `OpenAI` | `OPENAI_API_KEY` | `gpt-4o`（设置页可改）|
| claude | `Anthropic Claude` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6`（设置页可改）|
| mock | — | — | 零 Key 演示 / 测试，返回固定 prompt，不参与主链路 |

`backend=auto` 时按 `openai → claude` 探测，**未配置任何真实 Key 时直接走 mock 降级**（不报错，`meta.fallback_from` 记录来源），绝不假成功。Key + 模型名同样通过设置页「大模型 API」持久化管理。

### 可选环境变量

```bash
export VISION_DEFAULT_BACKEND=auto      # 默认后端（auto/openai/claude/mock）
export VISION_MODEL_OPENAI=gpt-4o       # OpenAI 模型名
export VISION_MODEL_CLAUDE=claude-sonnet-4-6
export OPENAI_BASE_URL=...              # 兼容代理（如 Azure/OpenRouter）
export ANTHROPIC_BASE_URL=...           # 兼容代理
export VISION_MAX_TOKENS=300            # 单次输出 token 上限
```

### 示例

```bash
# 图→prompt（multipart form）
curl -X POST http://localhost:5000/api/prompt/generate \
  -F "image=@reference.png" \
  -F "backend=auto" \
  -F "lang=en" -F "style=product"
# → {"success":true,"prompt":"a clean product render...","backend":"openai","elapsed_ms":3421}

# 查看已配置的 Vision 后端
curl http://localhost:5000/api/prompt/backends
```

> 红线：Key 仅存服务端（设置页 Key Store / 环境变量），不进前端；零本地 GPU；失败可降级不假成功。
> 前端 Tab 6「反向闭环」上传区 → 「提取 prompt」按钮 → 自动回填 prompt 框并启用生成。
> MCP 工具 `image_to_prompt` 与 `full_pipeline(image_path=...)` 支持一句话闭环。

## 钥匙体系（两类 Key 分离）

ColorFlow 有两把独立的钥匙，都存在服务端本地（均 0600 权限），互不混淆：

| 钥匙 | 存储文件 | 用途 | 生成方式 |
|------|---------|------|---------|
| **应用 API Key**（`cf_sk_*`）| `~/.colorflow/keys.json` | 前端请求 / MCP 接入鉴权（`x-api-key` 头）| 设置页 → 「生成新 Key」 |
| **大模型 Key** | `~/.colorflow/llm_keys.json` | 生图 / 图→prompt / Prompt 优化 调用第三方大模型 | 设置页 → 「大模型 API」→ 对应 provider |

### 应用 API Key（`cf_sk_*`）

启动服务后打开 **设置页**（左栏底部齿轮图标）→ 「生成新 Key」按钮 → 输入名称 → Key 明文仅显示一次 → 自动填充到 MCP 配置。

- 支持多个 Key，每个可命名 / 撤销
- 撤销后即时生效，所有请求立即被拒
- 首次无 Key 时全部开放（本地开发模式）

### 大模型 API Key（`llm_keys.json`）

设置页 → 「大模型 API」（合并页：生图后端状态 + Key 配置 + 环境变量备选）→ 每个 provider 可填：

- **Key**：火山方舟 / fal.ai / OpenAI / Claude 的 API Key；ComfyUI 填 `http://127.0.0.1:8188`
- **Base URL**：可选，兼容代理（Azure/OpenRouter）
- **模型名**：可选，覆盖该后端默认模型（如 `doubao-seedream-4-0-t2i` / `gpt-4o` / `flux-pro`）

保存即生效、重启不丢；读取优先级：**设置页 → 环境变量 → 后端默认**。删除 Key 后自动回退到环境变量 / mock 降级。

### 环境变量（向后兼容）

```bash
# 传统方式：启动前设置环境变量（仍然有效，会自动 bootstrap 进 KeyStore）
export COLORFLOW_API_KEY="cf_sk_xxx"
```

### 生产部署

```bash
export FLASK_DEBUG=false
export PORT=5000
python3 app.py
```

或使用 Gunicorn：

```bash
pip install gunicorn
gunicorn -w 2 -b 0.0.0.0:5000 app:app
```

详细部署说明见 [DEPLOY.md](DEPLOY.md)。

## 服务重启

### 手动重启

```bash
# Windows PowerShell
.\restart.ps1
```

`restart.ps1` 会自动：
1. 杀掉 5000 端口旧进程
2. 启动新 Flask 实例（后台运行）

### API 重启

```bash
curl -X POST http://localhost:5000/api/restart
```

或在前端设置页点击「重启服务」按钮。

## AI Agent 接入（MCP Server）

内置 MCP Server，让 Claude Code / Cursor 等 Agent 直接调用全部能力。

### 快速接入

1. 启动 ColorFlow Web 服务
2. 打开设置页 → 生成 API Key → 复制 `.mcp.json` 配置（Key 已自动填充）
3. 粘贴到 Claude Code / Cursor 的配置文件

```json
{
  "mcpServers": {
    "colorflow": {
      "command": "python",
      "args": ["mcp_server.py"],
      "env": {
        "COLORFLOW_API_KEY": "cf_sk_xxx"
      }
    }
  }
}
```

### 可用工具（17 个）

| Tool | 说明 | 关键参数 |
|------|------|---------|
| `trace_image` | 位图 → SVG 矢量图 | mode, colormode, hierarchical, 8 个精度参数 |
| `cutout` | AI 抠图 → 透明 PNG | model（8 选）, alpha_matting（3 阈值）|
| `cutout_then_trace` | 抠图 + 描图一键串联 | 抠图参数 + 描图参数全量 |
| `trace_and_match` | 描图 → 主色 → Pantone 匹配 | 8 个精度参数 |
| `match_pantone` | HEX → 最近 5 个 Pantone + ΔE | hex_color |
| `pantone_lookup` | 按色号精确查询 Pantone | name（如 485C）|
| `pantone_colors` | Pantone 色库分页 + 搜索 | page, limit, search |
| `quote_print` | 印刷全链路报价 | width, height, qty, colors, gsm, method |
| `export_print` | 位图 → 印刷级 CMYK PDF | width_mm, height_mm, bleed_mm, mode |
| `export_pantone_pdf` | 色卡 / 匹配报告 PDF | export_type（swatch / report / palette）, 颜色数据 |
| `greyscale3d` | 位图 → 3D 灰度高度图 / 位移贴图 | invert, contrast, gamma, smooth, auto_levels, bit_depth |
| `generate_image` | AI 生成包装效果图（零本地 GPU）| prompt, backend（auto 降级）, ref_image_path, size, n |
| `image_to_prompt` | 图→prompt 反向闭环（OpenAI/Claude/mock，auto 降级）| image_path, backend, lang, style, model |
| `full_pipeline` | 一句话：生图→抠图→描图→Pantone→报价→ZIP | prompt **或** image_path（图→prompt 自动推导）, width_mm, height_mm, qty, colors, backend, vision_backend |
| `prompt_templates` | 列出行业预制 prompt 模板（按分类分组）| category, search |
| `prompt_render` | 渲染模板 → 完整英文 prompt | template_id, params（JSON 字符串）|
| `prompt_optimize` | 优化用户 prompt → 增强版英文 prompt | prompt, backend（auto/openai/mock）|

### Agent 调用示例

```
用户: 「把 D:/img.png 描成矢量，提取主色，匹配 Pantone」
Agent: 调用 trace_and_match("D:/img.png")
  → SVG 文件路径 + 调色板（主色 + Pantone 匹配 + ΔE）

用户: 「帮我把这张照片背景抠掉」
Agent: 调用 cutout("D:/photo.jpg", model="silueta", alpha_matting=True)
  → 透明 PNG 文件路径

用户: 「查询 Pantone 485C 的 CMYK 值」
Agent: 调用 pantone_lookup("485C")
  → {name, hex, c, m, y, k, rgb}

用户: 「把 485C 的色值导出成色卡 PDF」
Agent: 调用 export_pantone_pdf(export_type="swatch", name="485 C",
         hex_color="#DA291C", cmyk=[0,85,95,5], rgb=[218,41,28])
  → {success, pdf_path}

用户: 「把这张物体照片转成 3D 灰度高度图」
Agent: 调用 greyscale3d("D:/object.jpg", invert=True, contrast=1.5, gamma=0.9,
         smooth=1, auto_levels=True, bit_depth=16)
   → {success, png_path, width, height, bit_depth}

用户: 「生成一个红色天地盖礼盒效果图，然后描成矢量」
Agent: 调用 generate_image("红色天地盖礼盒，烫金logo，哑光，电商白底")
  → {success, images: [{png_path, width, height, backend: "volcano"}]}
  再调 trace_image(png_path) → SVG 路径

用户: 「生成一个礼盒效果图，一条龙出 SVG、Pantone 色号和印刷报价」
Agent: 调用 full_pipeline("红色天地盖礼盒，烫金logo", width_mm=210,
         height_mm=297, qty=1000)
  → {success, zip_path: "colorflow_pipeline.zip", quote: {...}, files: [...]}

用户: 「用这张参考图复刻一个产品效果图，再走完整流水线」
Agent: 调用 full_pipeline(image_path="D:/reference.png", width_mm=210, height_mm=297)
  → 自动经 image_to_prompt 推导 prompt，再生图→描图→Pantone→报价→ZIP
  （等价于先调 image_to_prompt 再调 full_pipeline，但一次调用完成闭环）
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/cutout` | 位图抠图 → 透明 PNG（base64）|
| `POST` | `/api/trace` | 位图 → SVG（`mode=cutout` 时走抠图+描图）|
| `POST` | `/api/trace/colors` | 描图 + 主色提取 + Pantone 匹配（一键流水线）|
| `POST` | `/api/pantone/match` | HEX → Pantone 最近匹配 + ΔE |
| `GET` | `/api/pantone/lookup?name=` | Pantone 色号精确查询 |
| `GET` | `/api/pantone/colors?page=&limit=&search=` | Pantone 颜色列表（分页）|
| `POST` | `/api/cost/quote` | 印刷报价计算 |
| `POST` | `/api/print/export` | 位图 → 印刷级 CMYK PDF 下载 |
| `POST` | `/api/pantone/export` | 色卡 / 匹配报告 PDF（CMYK）|
| `POST` | `/api/grayscale3d` | 位图 → 3D 灰度高度图 / 位移贴图（8/16-bit PNG）|
| `POST` | `/api/generate` | AI 生图（同步）→ PNG（base64），backend=auto 按优先级降级 |
| `POST` | `/api/generate/jobs` | AI 生图（异步任务）→ `{job_id, status:"queued"}` |
| `GET` | `/api/generate/jobs/<id>` | 查询任务状态 queued/running/done/failed（done 携 images）|
| `GET` | `/api/generate/backends` | 生图后端状态（volcano/fal/comfyui 可用性 + 当前模型名）|
| `POST` | `/api/generate/batch` | 批量生图（换行分隔 prompts）→ `{batch_id, status:"queued"}` |
| `GET` | `/api/generate/batch/<batch_id>` | 查询批量任务状态（done 携 images/errors）|
| `GET` | `/api/prompt/backends` | 图→prompt 后端状态（openai/claude/mock 可用性）|
| `POST` | `/api/prompt/generate` | 图→prompt（image2prompt）→ 英文 prompt，用于回填 GEN 提示词框 |
| `POST` | `/api/prompt/optimize` | prompt 优化（中文/短 prompt → 增强版英文）|
| `GET` | `/api/prompt-templates` | 列出行业预制 prompt 模板（可按 category/search 过滤）|
| `GET` | `/api/prompt-templates/<id>` | 获取单个模板完整定义（含 prompt 原文和 params）|
| `POST` | `/api/prompt-templates/render` | 渲染模板 → 完整 prompt（支持 JSON 和 form 两种提交）|
| `GET` | `/api/llm-keys` | 列出所有大模型 provider 的 Key 状态（脱敏 + 当前模型）|
| `POST` | `/api/llm-keys` | 设置某 provider 的 Key + config{base_url, model}（空串 = 清除）|
| `DELETE` | `/api/llm-keys/<provider>` | 删除某 provider 的大模型 Key |
| `POST` | `/api/restart` | 触发服务重启（异步启动 restart.ps1）|
| `POST` | `/api/keys/generate` | 生成新 API Key |
| `GET` | `/api/keys` | 列出所有 Key（脱敏）|
| `DELETE` | `/api/keys/<key_id>` | 撤销指定 Key |

### 描图请求参数（multipart/form-data）

| 参数 | 说明 | 默认 |
|------|------|------|
| `image` | 图片文件（PNG/JPG/WebP/BMP，≤10MB）| 必填 |
| `mode` | `color` / `grey` / `human` / `cutout` | `color` |
| `colormode` | `rgb8` / `rgb16` / `mono` / `grey` / `grey16` | `rgb8` |
| `hierarchical` | `stacked` / `flat` | `stacked` |
| `filter_speckle` | 斑点过滤（1-100）| 4 |
| `color_precision` | 颜色精度（1-16）| 6 |
| `layer_difference` | 图层距离（1-256）| 64 |
| `corner_threshold` | 角点阈值（1-180）| 60 |
| `length_threshold` | 路径最短长度（0.1-100）| 2.0 |
| `path_precision` | 路径精度（1-16）| 7 |
| `ignore_white` | `1` 时去除白色路径输出透明 SVG | `0` |

### 抠图请求参数

| 参数 | 说明 | 默认 |
|------|------|------|
| `model` | silueta / u2net / u2net_human_seg / u2netp / dis_anime / dis_general_use / withoutbg / bria-rmbg | `silueta` |
| `alpha_matting` | `1` 启用边缘细化 | `0` |
| `alpha_matting_foreground_threshold` | 前景阈值（10-255）| 240 |
| `alpha_matting_background_threshold` | 背景阈值（0-245）| 10 |
| `alpha_matting_erode_size` | 腐蚀尺寸（1-20）| 10 |
| `decontaminate` | `1` 清除边缘色晕 | `0` |
| `post_process_mask` | `1` 二值掩码去噪 | `0` |

### 3D 灰度图请求参数（multipart/form-data）

| 参数 | 说明 | 默认 |
|------|------|------|
| `image` | 图片文件（PNG/JPG/WebP/BMP，≤10MB）| 必填 |
| `invert` | `1` 反色（黑=低 白=高，适合 displacement）| `0` |
| `contrast` | 对比度增强（0.5-3.0）| `1.0` |
| `gamma` | Gamma 校正（0.5-2.0）| `1.0` |
| `smooth` | 高斯模糊半径（0-5）| `0` |
| `auto_levels` | `1` 自动级别（归一化亮度）| `0` |
| `bit_depth` | 输出位深：`8` 或 `16` | `8` |

### 示例

```bash
# 抠图 → 透明 PNG
curl -X POST http://localhost:5000/api/cutout \
  -F "image=@photo.jpg" \
  -F "model=silueta" \
  -F "alpha_matting=1"

# 矢量描图
curl -X POST http://localhost:5000/api/trace \
  -F "image=@logo.png" \
  -F "mode=color" \
  -F "colormode=mono" \
  -F "path_precision=10"

# 色彩匹配
curl -X POST http://localhost:5000/api/pantone/match \
  -H "Content-Type: application/json" \
  -d '{"hex_color": "#DA291C"}'

# 生成 API Key
curl -X POST http://localhost:5000/api/keys/generate \
  -H "Content-Type: application/json" \
  -d '{"name": "我的 Agent"}'

# 3D 灰度高度图
curl -X POST http://localhost:5000/api/grayscale3d \
  -F "image=@object.jpg" \
  -F "invert=1" \
  -F "contrast=1.5" \
  -F "gamma=0.9" \
  -F "smooth=1" \
  -F "auto_levels=1" \
  -F "bit_depth=16"

# 重启服务
curl -X POST http://localhost:5000/api/restart
```

## 错误码

| 错误码 | 说明 |
|--------|------|
| 400 | 参数错误 / 缺少必要字段 / 非法 JSON |
| 401 | API Key 缺失或无效 |
| 415 | 不支持的图片类型或未带 JSON Content-Type |
| 500 | 服务端执行失败 |

## 设计规范

界面遵循 [Figma DESIGN.md 设计语言](https://github.com/Abinius/awesome-design-md)（`awesome-design-md/design-md/figma/DESIGN.md`）：

- **黑白编辑风**：纯白画布 + 纯黑墨色，所有 CTA 为药丸形（pill），图标按钮为圆形
- **pastel 色块**：lime / lilac / cream / mint / pink 等大色块点缀（logo mark、强调按钮）
- **字体**：Inter 变量字体（权重 320–700 细腻分级）+ JetBrains Mono（caption/eyebrow）
- **布局**：DeepSeek Harness 式左栏（LOGO + 工具导航 + footer）+ 右侧内容工作区，移动端抽屉折叠

## 架构

```
colorflow-web/
├── app.py               # Flask 入口：35+ API 路由 + Key 管理 + 3D 灰度图 + AI 生图(同步/任务/批量) + 图→prompt + prompt 优化/模板 + 服务重启
├── gen_backends.py      # GEN 生图适配器层（volcano / fal / comfyui + auto 降级 + GenResult/GenError + 模型名读取 Key Store）
├── vision_backends.py   # VISION 图→prompt 适配器层（openai / claude / mock + auto 降级 + PromptResult/PromptError）
├── prompt_templates.py  # Prompt 模板库加载器（assets/prompt_templates.json → render）
├── prompt_optimizer.py  # Prompt 优化器（OpenAI Chat API，mock 降级）
├── llm_keys.py          # LLM Key Store：5 家大模型 Key/Base/模型名 持久化管理（~/.colorflow/llm_keys.json）
├── colorflow_keys.py    # KeyStore：应用 API Key（cf_sk_*）生成 / 校验 / 撤销
├── mcp_server.py        # MCP Server（17 工具 + Key 认证）
├── colorflow_desktop_app.py   # 桌面入口（PyWebview 原生窗口 + Flask 线程）
├── colorflow_desktop_app.spec # PyInstaller 打包配置
├── restart.ps1          # 服务重启脚本（杀旧进程 + 拉起新实例）
├── templates/
│   └── index.html      # 单页（抠图 / 描图 / Pantone / 色彩匹配 / 3D 灰度图 / AI 生图+反向闭环 / 参考图库 / 批量生图 / 模板市场 + 设置页）
├── static/
│   ├── style.css       # Figma DESIGN.md 样式
│   ├── app.js          # 前端交互（全站 SVG 图标）+ Key 管理 + MCP 配置 + 3D 灰度图 + AI 生图(任务轮询) + 图→prompt 提取
│   └── favicon.*       # 浏览器图标（ico/png/svg/manifest）
├── assets/
│   └── gen_workflow_api.json  # ComfyUI 文生图工作流模板（可替换本机构造）
│   └── prompt_templates.json  # 行业预制 prompt 模板库（12 模板 · 6 分类）
├── models/
│   └── silueta.onnx    # 抠图模型（42MB，随包附带）
├── tests/              # 212 用例
│   ├── conftest.py     # 共享配置（U2NET_HOME 回退包内模型 + LLM Key Store 隔离到临时文件）
│   ├── test_app.py     # API 集成测试 + Key 管理 + 3D 灰度图 + 抠图/忽略白色
│   ├── test_mcp.py     # MCP Server 全工具测试
│   ├── test_gen.py     # GEN 生图适配器 + VISION 图→prompt + LLM Key Store 模型解析
│   ├── test_llm_keys.py# LLM Key Store（模块 + /api/llm-keys 端点全量测试）
│   └── test_prompt_templates.py  # Prompt 模板库（模块/API/MCP 全量测试）
├── .github/workflows/ci.yml  # GitHub Actions（pytest + zip 产物）
├── start.bat           # Windows 一键启动
├── DEPLOY.md           # 部署说明
├── requirements.txt    # 依赖清单
└── requirements-desktop.txt  # 桌面打包依赖（pywebview + pyinstaller）
```

## 测试

```bash
pip install pytest
python -m pytest tests/ -q     # 212 个用例
```

## 相关项目

| 项目 | 说明 |
|------|------|
| [ColorFlow SDK](https://github.com/Abinius/ColorFlow) | AI Agent 矢量描图 SDK（Python/CLI/API）|
| [mcp-print](https://github.com/kcgdz/mcp-print) | Pantone + CMYK + Delta E + 印刷报价（2415 色）|
| [vtracer](https://github.com/visioncortex/vtracer) | Rust 矢量描图引擎 |
| [rembg](https://github.com/danielgatis/rembg) | AI 背景移除（silueta/u2net 模型）|
| [FastMCP](https://github.com/jlowin/fastmcp) | MCP Server 框架 |

## License

MIT © AbinCheungCom
