"""ColorFlow 测试共享配置。

cutout / mode=cutout 测试需用随包 silueta 模型；CI 或本地未显式设置
U2NET_HOME 时回退到包内 models/，避免 rembg 尝试联网下载（国内易超时）。

同时把 Key Store 重定向到临时文件，防止测试用例把假 Key/假模型写进
真实 ~/.colorflow/（此前导致设置页出现 sk-api-test 等脏数据）。
"""
import os
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent.parent
_MODELS = _HERE / "models"
if _MODELS.exists() and not os.getenv("U2NET_HOME"):
    os.environ["U2NET_HOME"] = str(_MODELS)


@pytest.fixture(autouse=True)
def _isolate_keystores(tmp_path, monkeypatch):
    """每个测试用独立临时文件承载 Key Store（API Key + LLM Key），测完自动还原。

    采用 patch .path 方式：无论调用方是模块级导入（app.py 的 keystore）
    还是函数内延迟导入（gen_backends 的 llm_keystore），都指向同一临时文件，
    避免写入真实 ~/.colorflow/keys.json 与 llm_keys.json。
    """
    from colorflow_keys import keystore as _cf_ks
    from llm_keys import llm_keystore as _llm_ks

    monkeypatch.setattr(_cf_ks, "path", str(tmp_path / "keys.json"))
    monkeypatch.setattr(_llm_ks, "path", str(tmp_path / "llm_keys.json"))
    yield
