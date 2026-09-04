# syntax=docker/dockerfile:1.7
# ============================================================
# ColorFlow Web — 生产镜像
#
# 构建：docker build -t colorflow-web .
# 运行：docker run -p 5000:5000 --env-file .env colorflow-web
#
# 红线：
#   - 零本地 GPU（云端 API 做生图/抠图，容器仅 CPU）
#   - Key 仅注入服务端环境变量，不进镜像层
#   - 非 root 用户运行（UID 10001）
# ============================================================

FROM python:3.11-slim AS base

# 系统依赖：Pillow 编译 + onnxruntime 需要 libc/CA
RUN apt-get update && apt-get install -y --no-install-recommends \
        libjpeg62-turbo \
        zlib1g-dev \
        libwebp7 \
        libffi-dev \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --upgrade pip setuptools wheel

# 应用目录
WORKDIR /app

# 先装依赖（利用 Docker layer cache：源码变化不 reinstall）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 拷源码（排除 .git / venv / 模型等大文件，见 .dockerignore）
COPY . .

# 抠图模型：随镜像附带（~42MB，启动即用，无需联网下载）
RUN mkdir -p /app/models && \
    if [ ! -f /app/models/silueta.onnx ]; then \
        echo "WARN: silueta.onnx 未找到，将在首次抠图时联网下载" && \
    fi

# 运行时目录
RUN mkdir -p /tmp/colorflow-uploads /tmp/colorflow-output /tmp/colorflow-gen \
    && chown -R 10001:10001 /tmp/colorflow-uploads /tmp/colorflow-output /tmp/colorflow-gen /app

# 非 root 用户
USER 10001

# 端口（serve.py 默认 5000，可用 PORT 环境变量覆盖）
EXPOSE 5000

# 健康检查：每 30s 探测 /healthz，5s 超时，失败 3 次标记 unhealthy
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://127.0.0.1:5000/healthz || exit 1

# 生产入口：waitress WSGI（多线程，Windows/Linux 通用）
# 线程数默认 4，可用 THREADS 环境变量覆盖
CMD ["python", "serve.py"]
