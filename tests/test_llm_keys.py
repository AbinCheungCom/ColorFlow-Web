"""LLM Key Store 测试 — llm_keys 模块 + /api/llm-keys 端点"""
import os
import json
import tempfile
import pytest


# ============================================================
# llm_keys 模块单元测试
# ============================================================

class TestLLMKeyStore:
    """测试 llm_keys.LLMKeyStore"""

    def setup_method(self):
        """每个测试用例使用独立的临时文件"""
        self.tmpdir = tempfile.mkdtemp()
        self.tmpfile = os.path.join(self.tmpdir, "test_keys.json")
        from llm_keys import LLMKeyStore
        self.store = LLMKeyStore(path=self.tmpfile)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_list_all_empty(self):
        from llm_keys import PROVIDERS
        result = self.store.list_all()
        assert isinstance(result, list)
        assert len(result) == len(PROVIDERS)
        for p in result:
            assert p["has_key"] is False
            assert p["key_masked"] == ""

    def test_set_and_get_key(self):
        entry = self.store.set_key("openai", "sk-test-abc123")
        assert entry["key"] == "sk-test-abc123"
        assert self.store.get_key("openai") == "sk-test-abc123"

    def test_key_not_found(self):
        assert self.store.get_key("openai") is None

    def test_remove_key(self):
        self.store.set_key("openai", "sk-test")
        assert self.store.get_key("openai") == "sk-test"
        assert self.store.remove("openai") is True
        assert self.store.get_key("openai") is None

    def test_remove_nonexistent(self):
        assert self.store.remove("nonexistent") is False

    def test_invalid_provider(self):
        with pytest.raises(ValueError):
            self.store.set_key("invalid", "key")

    def test_empty_key_rejected(self):
        with pytest.raises(ValueError):
            self.store.set_key("openai", "")

    def test_list_all_shows_masked_key(self):
        self.store.set_key("openai", "sk-test-very-long-key-12345")
        result = self.store.list_all()
        for p in result:
            if p["provider"] == "openai":
                assert p["has_key"] is True
                # 脱敏格式：sk- + 6个星号 + 最后4位
                assert p["key_masked"].startswith("sk-")
                assert "******" in p["key_masked"]
                assert p["key_masked"].endswith("2345")
                break
        else:
            pytest.fail("OpenAI not found in list")

    def test_has_any(self):
        assert self.store.has_any() is False
        self.store.set_key("openai", "sk-test")
        assert self.store.has_any() is True

    def test_persistence(self):
        """key 应持久化到文件"""
        self.store.set_key("openai", "sk-persist-test")
        # 创建新实例读取同一文件
        from llm_keys import LLMKeyStore
        store2 = LLMKeyStore(path=self.tmpfile)
        assert store2.get_key("openai") == "sk-persist-test"

    def test_get_config(self):
        self.store.set_key("openai", "sk-test", config={"base_url": "https://proxy.example.com"})
        cfg = self.store.get_config("openai")
        assert cfg.get("base_url") == "https://proxy.example.com"

    def test_get_config_empty(self):
        cfg = self.store.get_config("openai")
        assert cfg == {}


# ============================================================
# Flask API 端点测试
# ============================================================

@pytest.fixture
def client():
    """Flask 测试客户端"""
    import app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


class TestLLMKeysAPI:
    """测试 /api/llm-keys 端点"""

    def test_get_list(self, client):
        resp = client.get("/api/llm-keys")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "providers" in data
        assert len(data["providers"]) >= 5

    def test_post_set_key(self, client):
        resp = client.post("/api/llm-keys", json={
            "provider": "openai",
            "key": "sk-api-test-12345",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["action"] == "set"
        assert data["provider"] == "openai"

    def test_post_invalid_provider(self, client):
        resp = client.post("/api/llm-keys", json={
            "provider": "unknown_provider",
            "key": "test",
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data
        assert "valid" in data

    def test_post_empty_key_removes(self, client):
        # 先设置
        client.post("/api/llm-keys", json={
            "provider": "claude", "key": "sk-ant-test"
        })
        # 空串清除
        resp = client.post("/api/llm-keys", json={
            "provider": "claude", "key": ""
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["action"] == "removed"

    def test_delete_key(self, client):
        # 先设置
        client.post("/api/llm-keys", json={
            "provider": "volcano", "key": "volc-test-123"
        })
        # 删除
        resp = client.delete("/api/llm-keys/volcano")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["action"] == "removed"

    def test_delete_invalid_provider(self, client):
        resp = client.delete("/api/llm-keys/nonexistent")
        assert resp.status_code == 400

    def test_set_with_config(self, client):
        resp = client.post("/api/llm-keys", json={
            "provider": "openai",
            "key": "sk-with-config",
            "config": {"base_url": "https://proxy.example.com/v1"},
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_list_shows_set_key(self, client):
        # 设置 key
        client.post("/api/llm-keys", json={
            "provider": "fal", "key": "fal-test-key"
        })
        # 验证列表
        resp = client.get("/api/llm-keys")
        data = resp.get_json()
        for p in data["providers"]:
            if p["provider"] == "fal":
                assert p["has_key"] is True
                break
        else:
            pytest.fail("fal provider not found")