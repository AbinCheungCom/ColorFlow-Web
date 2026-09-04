"""ColorFlow 测试共享配置。

cutout / mode=cutout 测试需用随包 silueta 模型；CI 或本地未显式设置
U2NET_HOME 时回退到包内 models/，避免 rembg 尝试联网下载（国内易超时）。
"""
import os
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent
_MODELS = _HERE / "models"
if _MODELS.exists() and not os.getenv("U2NET_HOME"):
    os.environ["U2NET_HOME"] = str(_MODELS)
