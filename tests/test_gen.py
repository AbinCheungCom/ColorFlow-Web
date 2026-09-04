"""ColorFlow GEN 生图适配器层测试（mock 后端，不真实调用付费 API）。

覆盖（见《开发文档 02》§9.2 验收标准）：
  - 单元：_parse_size / _to_png_bytes / available_backends / comfyui 工作流注入
  - auto 降级：volcano 失败(retryable) → fal 成功，backend 字段正确
  - bad_prompt 阻断：不换后端
  - API：/api/generate/backends 状态、无 prompt 400、无后端 401、成功 200、超时 504、配额 402
  - MCP：generate_image 注册 + 成功落盘
"""
import base64
import io
import json
import os
import time

import pytest

from app import app
import gen_backends as gb
from gen_backends import GenResult, GenError, available_backends, dispatch

client = app.test_client()


def _png_bytes():
    """1×1 RGBA PNG（不依赖外部 sample）"""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (1, 1), (255, 0, 0, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _submit_and_wait(client, data, timeout=10.0, interval=0.05):
    """提交异步生图任务并轮询直到 done/failed 或超时，返回 (job_id, job_snapshot)"""
    resp = client.post("/api/generate/jobs", data=data,
                       content_type="multipart/form-data")
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["success"] is True and d["job_id"]
    assert d["status"] == "queued"
    job_id = d["job_id"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/generate/jobs/{job_id}")
        j = r.get_json()
        if j.get("status") in ("done", "failed"):
            return job_id, j
        time.sleep(interval)
    return job_id, client.get(f"/api/generate/jobs/{job_id}").get_json()


# ============================================================
# 单元测试
# ============================================================

class TestParseSize:
    def test_tuple(self):
        assert gb._parse_size((512, 768)) == (512, 768)

    def test_string_x(self):
        assert gb._parse_size("1024x1024") == (1024, 1024)

    def test_string_fullwidth(self):
        assert gb._parse_size("1024×1536") == (1024, 1536)

    def test_invalid_falls_back(self):
        assert gb._parse_size("bad") == (1024, 1024)


class TestToPng:
    def test_png_roundtrip(self):
        raw = _png_bytes()
        out, w, h = gb._to_png_bytes(raw)
        assert (w, h) == (1, 1)
        assert out[:8] == b"\x89PNG\r\n\x1a\n"


class TestAvailableBackends:
    def test_none_configured(self, monkeypatch):
        for k in ("VOLCANO_API_KEY", "FAL_KEY", "COMFYUI_URL"):
            monkeypatch.delenv(k, raising=False)
        # 同时屏蔽 LLM Key Store（防止文件中有残留 key 影响测试）
        import llm_keys
        monkeypatch.setattr(llm_keys.llm_keystore, "get_key", lambda p: None)
        assert available_backends() == []

    def test_priority_order(self, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "f")
        monkeypatch.setenv("VOLCANO_API_KEY", "v")
        monkeypatch.setenv("COMFYUI_URL", "http://127.0.0.1:8188")
        assert available_backends() == ["volcano", "fal", "comfyui"]


class TestComfyuiWorkflow:
    def test_load_has_clip_text_node(self):
        wf = gb._load_comfyui_workflow()
        ct_nodes = [n for n in wf.values()
                    if isinstance(n, dict) and n.get("class_type") == "CLIPTextEncode"]
        assert len(ct_nodes) >= 1

    def test_inject_prompt_and_size(self):
        wf = gb._load_comfyui_workflow()
        wf = gb._inject_prompt(wf, "a red gift box", (512, 768))
        injected = any(
            isinstance(n, dict) and n.get("class_type") == "CLIPTextEncode"
            and n["inputs"].get("text") == "a red gift box"
            for n in wf.values()
        )
        assert injected
        for n in wf.values():
            if isinstance(n, dict) and n.get("class_type") == "EmptyLatentImage":
                assert n["inputs"]["width"] == 512
                assert n["inputs"]["height"] == 768


# ============================================================
# dispatch auto 降级
# ============================================================

def _patch_backend(monkeypatch, name, fn):
    """替换 _BACKENDS 注册表中的后端函数（dispatch 运行时读取该表）"""
    monkeypatch.setitem(gb._BACKENDS, name, fn)


class TestDispatchAuto:
    def test_no_backend_configured(self, monkeypatch):
        for k in ("VOLCANO_API_KEY", "FAL_KEY", "COMFYUI_URL"):
            monkeypatch.delenv(k, raising=False)
        import llm_keys
        monkeypatch.setattr(llm_keys.llm_keystore, "get_key", lambda p: None)
        with pytest.raises(GenError) as ei:
            dispatch("a box", backend="auto")
        assert ei.value.code == "auth"

    def test_empty_prompt(self, monkeypatch):
        monkeypatch.setenv("VOLCANO_API_KEY", "v")
        with pytest.raises(GenError) as ei:
            dispatch("   ", backend="auto")
        assert ei.value.code == "bad_prompt"
        assert ei.value.retryable is False

    def test_auto_degrades_volcano_to_fal(self, monkeypatch):
        monkeypatch.setenv("VOLCANO_API_KEY", "v")
        monkeypatch.setenv("FAL_KEY", "f")
        png = _png_bytes()
        called = []

        def fake_volcano(prompt, ref_image=None, size=(1024, 1024), n=1, timeout=120, model=""):
            called.append("volcano")
            raise GenError("timeout", "volcano timeout", retryable=True)

        def fake_fal(prompt, ref_image=None, size=(1024, 1024), n=1, timeout=120, model=""):
            called.append("fal")
            return [GenResult(png_bytes=png, width=1, height=1, backend="fal", model="flux")]

        _patch_backend(monkeypatch, "volcano", fake_volcano)
        _patch_backend(monkeypatch, "fal", fake_fal)

        results = dispatch("box", backend="auto")
        assert called == ["volcano", "fal"]
        assert len(results) == 1
        assert results[0].backend == "fal"

    def test_bad_prompt_stops_degradation(self, monkeypatch):
        """bad_prompt 非法，换后端无意义，应阻断而非继续"""
        monkeypatch.setenv("VOLCANO_API_KEY", "v")
        monkeypatch.setenv("FAL_KEY", "f")
        called = []

        def fake_volcano(prompt, ref_image=None, size=(1024, 1024), n=1, timeout=120, model=""):
            called.append("volcano")
            raise GenError("bad_prompt", "illegal prompt", retryable=False)

        def fake_fal(prompt, ref_image=None, size=(1024, 1024), n=1, timeout=120, model=""):
            called.append("fal")
            return []

        _patch_backend(monkeypatch, "volcano", fake_volcano)
        _patch_backend(monkeypatch, "fal", fake_fal)

        with pytest.raises(GenError) as ei:
            dispatch("x", backend="auto")
        assert ei.value.code == "bad_prompt"
        assert called == ["volcano"]  # fal 未被尝试

    def test_specified_backend_no_key(self, monkeypatch):
        monkeypatch.delenv("VOLCANO_API_KEY", raising=False)
        import llm_keys
        monkeypatch.setattr(llm_keys.llm_keystore, "get_key", lambda p: None)
        with pytest.raises(GenError) as ei:
            dispatch("box", backend="volcano")
        assert ei.value.code == "auth"

    def test_unknown_backend(self, monkeypatch):
        with pytest.raises(GenError) as ei:
            dispatch("box", backend="nonsense")
        assert ei.value.code == "bad_prompt"


# ============================================================
# /api/generate API
# ============================================================

class TestGenerateAPI:
    def test_backends_status(self):
        resp = client.get("/api/generate/backends")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert isinstance(data["backends"], list)
        assert "any_configured" in data

    def test_no_prompt_400(self):
        resp = client.post("/api/generate", data={}, content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_no_backend_configured_401(self, monkeypatch):
        for k in ("VOLCANO_API_KEY", "FAL_KEY", "COMFYUI_URL"):
            monkeypatch.delenv(k, raising=False)
        resp = client.post(
            "/api/generate",
            data={"prompt": "a box"},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 401

    def test_success_200(self, monkeypatch):
        png = _png_bytes()

        def fake_dispatch(prompt, ref_image=None, backend="auto",
                          size=(1024, 1024), n=1, timeout=120, model=""):
            assert prompt == "a red box"
            return [GenResult(png_bytes=png, width=1, height=1,
                              backend="volcano", model="seedream")]

        monkeypatch.setattr("app.gen_dispatch", fake_dispatch)
        resp = client.post(
            "/api/generate",
            data={"prompt": "a red box", "backend": "auto", "n": "1"},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["count"] == 1
        img = data["images"][0]
        assert img["backend"] == "volcano"
        assert img["width"] == 1
        assert base64.b64decode(img["png_base64"]) == png

    def test_timeout_504(self, monkeypatch):
        def fake_dispatch(prompt, **kw):
            raise GenError("timeout", "slow", retryable=True)

        monkeypatch.setattr("app.gen_dispatch", fake_dispatch)
        resp = client.post(
            "/api/generate",
            data={"prompt": "box"},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 504
        assert resp.get_json()["retryable"] is True

    def test_quota_402(self, monkeypatch):
        def fake_dispatch(prompt, **kw):
            raise GenError("quota", "no credit", retryable=True)

        monkeypatch.setattr("app.gen_dispatch", fake_dispatch)
        resp = client.post(
            "/api/generate",
            data={"prompt": "box"},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 402

    def test_bad_prompt_400(self, monkeypatch):
        def fake_dispatch(prompt, **kw):
            raise GenError("bad_prompt", "illegal", retryable=False)

        monkeypatch.setattr("app.gen_dispatch", fake_dispatch)
        resp = client.post(
            "/api/generate",
            data={"prompt": "box"},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400


# ============================================================
# MCP generate_image
# ============================================================

class TestMCPGenerate:
    def test_registered(self):
        import mcp_server as ms

        assert callable(ms.generate_image)

    def test_empty_prompt(self):
        import mcp_server as ms

        data = json.loads(ms.generate_image(""))
        assert data.get("error")

    def test_no_backend(self, monkeypatch):
        import mcp_server as ms

        for k in ("VOLCANO_API_KEY", "FAL_KEY", "COMFYUI_URL"):
            monkeypatch.delenv(k, raising=False)
        data = json.loads(ms.generate_image("box"))
        assert data.get("error")

    def test_success_writes_png(self, monkeypatch, tmp_path):
        import mcp_server as ms

        png = _png_bytes()

        def fake_dispatch(prompt, ref_image=None, backend="auto",
                          size=(1024, 1024), n=1, timeout=120, model=""):
            return [GenResult(png_bytes=png, width=1, height=1,
                              backend="fal", model="flux")]

        monkeypatch.setattr("mcp_server.gen_dispatch", fake_dispatch)
        data = json.loads(ms.generate_image("box", output_dir=str(tmp_path)))
        assert data["success"] is True
        assert data["count"] == 1
        assert os.path.exists(data["images"][0]["png_path"])
        assert data["images"][0]["backend"] == "fal"

    def test_failure_returns_error(self, monkeypatch):
        import mcp_server as ms

        def fake_dispatch(prompt, **kw):
            raise GenError("timeout", "slow", retryable=True)

        monkeypatch.setattr("mcp_server.gen_dispatch", fake_dispatch)
        data = json.loads(ms.generate_image("box"))
        assert data.get("error")
        assert data.get("retryable") is True


# ============================================================
# 异步任务模式（/api/generate/jobs，Phase 2）
# ============================================================

class TestGenerateJobs:
    """POST 提交 → GET 轮询 → done/failed 状态机"""

    def test_create_returns_job_id(self):
        resp = client.post(
            "/api/generate/jobs",
            data={"prompt": "box"},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        d = resp.get_json()
        assert d["success"] is True
        assert d["status"] == "queued"
        assert len(d["job_id"]) > 10

    def test_no_prompt_400(self):
        resp = client.post("/api/generate/jobs", data={},
                           content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_unknown_job_404(self):
        resp = client.get("/api/generate/jobs/deadbeef000000000000000000000000")
        assert resp.status_code == 404
        assert resp.get_json()["status"] == "not_found"

    def test_done_with_images(self, monkeypatch):
        """成功：job 走完 queued→running→done，done 携带 images（与同步端点结构一致）"""
        png = _png_bytes()

        def fake_dispatch(prompt, ref_image=None, backend="auto",
                          size=(1024, 1024), n=1, timeout=120, model=""):
            return [GenResult(png_bytes=png, width=1, height=1,
                              backend="volcano", model="seedream")]

        monkeypatch.setattr("app.gen_dispatch", fake_dispatch)
        _, job = _submit_and_wait(
            client, {"prompt": "a box"}, timeout=5.0
        )
        assert job["status"] == "done"
        assert job["count"] == 1
        img = job["images"][0]
        assert img["backend"] == "volcano"
        assert img["width"] == 1
        assert base64.b64decode(img["png_base64"]) == png
        assert job["elapsed_ms"] >= 0

    def test_failed_propagates_code(self, monkeypatch):
        """失败：GenError 的 code/retryable 落进 job，绝不假成功"""
        def fake_dispatch(prompt, **kw):
            raise GenError("quota", "no credit", retryable=True)

        monkeypatch.setattr("app.gen_dispatch", fake_dispatch)
        _, job = _submit_and_wait(client, {"prompt": "box"}, timeout=5.0)
        assert job["status"] == "failed"
        assert job["code"] == "quota"
        assert job["retryable"] is True
        assert job["error"]

    def test_no_backend_fails_with_auth(self, monkeypatch):
        for k in ("VOLCANO_API_KEY", "FAL_KEY", "COMFYUI_URL"):
            monkeypatch.delenv(k, raising=False)
        _, job = _submit_and_wait(client, {"prompt": "box"}, timeout=5.0)
        assert job["status"] == "failed"
        assert job["code"] == "auth"
        assert job["retryable"] is False


# ============================================================
# full_pipeline MCP（生图→抠图→描图→Pantone→报价→ZIP，逐级降级）
# ============================================================

class TestFullPipeline:
    def test_registered(self):
        import mcp_server as ms

        assert callable(ms.full_pipeline)

    def test_empty_prompt(self):
        import mcp_server as ms

        data = json.loads(ms.full_pipeline(""))
        assert data.get("error")

    def test_success_builds_zip(self, monkeypatch, tmp_path):
        import mcp_server as ms
        import zipfile

        png = _png_bytes()
        out = tmp_path / "pipeline"

        def fake_dispatch(prompt, **kw):
            return [GenResult(png_bytes=png, width=1, height=1,
                              backend="fal", model="flux")]

        monkeypatch.setattr("mcp_server.gen_dispatch", fake_dispatch)
        # 抠图降级：返回原图路径（等价于抠图失败用原图）
        monkeypatch.setattr(ms.sdk, "cutout", lambda path, **kw: path)
        # 描图：写一个含填充色的最小合法 SVG
        def fake_trace(path, **kw):
            p = tmp_path / "out.svg"
            p.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1">'
                '<rect fill="#DA291C" width="1" height="1"/></svg>',
                encoding="utf-8",
            )
            return str(p)

        monkeypatch.setattr(ms.sdk, "trace", fake_trace)

        data = json.loads(ms.full_pipeline("box", output_dir=str(out)))
        assert data["success"] is True
        assert os.path.exists(data["zip_path"])
        assert data["color_count"] >= 1
        assert data["quote"] is not None
        assert data["quote"]["total_cost_usd"] > 0
        with zipfile.ZipFile(data["zip_path"]) as zf:
            names = set(zf.namelist())
        for expected in ("colorflow_gen.png", "colorflow_output.svg",
                         "colorflow_palette.json", "colorflow_quote.json"):
            assert expected in names, f"zip 缺 {expected}"

    def test_cutout_failure_degrades(self, monkeypatch, tmp_path):
        """抠图失败 → 记录 errors 但流水线继续，最终 success=True"""
        import mcp_server as ms

        png = _png_bytes()

        def fake_dispatch(prompt, **kw):
            return [GenResult(png_bytes=png, width=1, height=1,
                              backend="fal", model="flux")]

        monkeypatch.setattr("mcp_server.gen_dispatch", fake_dispatch)

        def boom_cutout(path, **kw):
            raise RuntimeError("model not loaded")

        monkeypatch.setattr(ms.sdk, "cutout", boom_cutout)

        def fake_trace(path, **kw):
            p = tmp_path / "o.svg"
            p.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1">'
                '<rect fill="#DA291C" width="1" height="1"/></svg>',
                encoding="utf-8",
            )
            return str(p)

        monkeypatch.setattr(ms.sdk, "trace", fake_trace)

        data = json.loads(ms.full_pipeline("box", output_dir=str(tmp_path)))
        assert data["success"] is True, data
        assert any("抠图失败" in e for e in data["errors"])

    def test_gen_failure_short_circuits(self, monkeypatch, tmp_path):
        """生图失败 → 直接返回错误，不产出 ZIP"""
        import mcp_server as ms

        def fake_dispatch(prompt, **kw):
            raise GenError("timeout", "slow", retryable=True)

        monkeypatch.setattr("mcp_server.gen_dispatch", fake_dispatch)
        data = json.loads(ms.full_pipeline("box", output_dir=str(tmp_path)))
        assert data.get("error")
        assert data["code"] == "timeout"
        assert data["retryable"] is True
        assert not os.path.exists(str(tmp_path / "colorflow_pipeline.zip"))


# ============================================================
# VISION 图→prompt（image2prompt 反向闭环）
# ============================================================
import vision_backends as vb
from vision_backends import PromptResult, PromptError, dispatch_prompt, available_backends as v_avail


class TestVisionBackends:
    """vision_backends 单元测试（mock 后端，不真实调用付费 API）"""

    def test_available_backends_always_has_mock(self):
        avail = v_avail()
        assert "mock" in avail

    def test_mock_backend_returns_prompt(self):
        r = vb.mock_backend("", image=_png_bytes())
        assert isinstance(r, PromptResult)
        assert r.prompt
        assert r.backend == "mock"
        assert r.model == "mock-v1"
        assert r.meta["image_bytes"] == len(_png_bytes())

    def test_dispatch_prompt_bad_image_empty(self):
        with pytest.raises(PromptError) as ei:
            dispatch_prompt(b"", backend="mock")
        assert ei.value.code == "bad_image"

    def test_dispatch_prompt_bad_image_too_large(self):
        big = b"\x00" * (26 * 1024 * 1024)
        with pytest.raises(PromptError) as ei:
            dispatch_prompt(big, backend="mock")
        assert ei.value.code == "bad_image"

    def test_dispatch_prompt_unknown_backend(self):
        with pytest.raises(PromptError) as ei:
            dispatch_prompt(_png_bytes(), backend="nonsense")
        assert ei.value.code == "upstream"

    def test_dispatch_prompt_explicit_mock(self):
        r = dispatch_prompt(_png_bytes(), backend="mock")
        assert r.backend == "mock"
        assert r.prompt

    def test_dispatch_prompt_auto_no_real_keys_falls_back_to_mock(self, monkeypatch):
        """无 OPENAI_API_KEY/ANTHROPIC_API_KEY 时 auto 直接走 mock，不报错"""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        import llm_keys
        monkeypatch.setattr(llm_keys.llm_keystore, "get_key", lambda p: None)
        r = dispatch_prompt(_png_bytes(), backend="auto")
        assert r.backend == "mock"
        assert r.prompt

    def test_dispatch_prompt_auto_real_backend_failure_degrades_to_mock(self, monkeypatch):
        """openai 失败(retryable) → claude 未配 → 降级 mock"""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        def boom(prompt, **kw):
            raise PromptError("timeout", "openai slow", retryable=True)

        monkeypatch.setitem(vb._BACKENDS, "openai", boom)
        r = dispatch_prompt(_png_bytes(), backend="auto")
        assert r.backend == "mock"
        assert r.meta.get("fallback_from") == "timeout"

    def test_dispatch_prompt_openai_no_key_auth_error(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        # 同时屏蔽 LLM Key Store（防止文件中有残留 key 影响测试）
        import llm_keys
        monkeypatch.setattr(llm_keys.llm_keystore, "get_key", lambda p: None)
        with pytest.raises(PromptError) as ei:
            dispatch_prompt(_png_bytes(), backend="openai")
        assert ei.value.code == "auth"
        assert ei.value.retryable is False

    def test_system_prompt_contains_language(self):
        assert "English" in vb._system_prompt("product", "en")
        assert "中文" in vb._system_prompt("product", "zh")


class TestPromptAPI:
    """/api/prompt/* API 测试"""

    def test_backends_status(self):
        resp = client.get("/api/prompt/backends")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert isinstance(data["backends"], list)
        ids = {b["id"] for b in data["backends"]}
        assert {"openai", "claude", "mock"} == ids
        # mock 始终 available
        mock = next(b for b in data["backends"] if b["id"] == "mock")
        assert mock["available"] is True

    def test_generate_missing_file(self):
        resp = client.post("/api/prompt/generate", data={},
                           content_type="multipart/form-data")
        assert resp.status_code == 400
        assert "image" in resp.get_json()["error"]

    def test_generate_empty_filename(self):
        resp = client.post("/api/prompt/generate",
                           data={"image": (io.BytesIO(b"x"), "")},
                           content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_generate_unsupported_type(self):
        resp = client.post("/api/prompt/generate",
                           data={"image": (io.BytesIO(b"x"), "a.txt", "text/plain")},
                           content_type="multipart/form-data")
        assert resp.status_code == 415

    def test_generate_mock_success(self):
        resp = client.post("/api/prompt/generate",
                           data={
                               "image": (io.BytesIO(_png_bytes()), "ref.png", "image/png"),
                               "backend": "mock",
                               "lang": "en",
                               "style": "product",
                           },
                           content_type="multipart/form-data")
        assert resp.status_code == 200, resp.get_json()
        data = resp.get_json()
        assert data["success"] is True
        assert data["prompt"]
        assert data["backend"] == "mock"
        assert data["elapsed_ms"] >= 0

    def test_generate_auto_falls_back_to_mock(self):
        """无真实 Key 时 auto 走 mock，不报错"""
        resp = client.post("/api/prompt/generate",
                           data={
                               "image": (io.BytesIO(_png_bytes()), "ref.png", "image/png"),
                               "backend": "auto",
                           },
                           content_type="multipart/form-data")
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["backend"] == "mock"


class TestMCPImageToPrompt:
    """MCP image_to_prompt 工具测试"""

    def test_registered(self):
        import mcp_server as ms
        assert callable(ms.image_to_prompt)

    def test_missing_file(self):
        import mcp_server as ms
        data = json.loads(ms.image_to_prompt("/no/such/path.png"))
        assert data.get("error")

    def test_success_with_mock(self, monkeypatch, tmp_path):
        import mcp_server as ms
        png_path = tmp_path / "ref.png"
        png_path.write_bytes(_png_bytes())
        data = json.loads(ms.image_to_prompt(str(png_path), backend="mock"))
        assert data["success"] is True
        assert data["prompt"]
        assert data["backend"] == "mock"

    def test_auth_blocks_when_key_mismatch(self, monkeypatch, tmp_path):
        """配置了 COLORFLOW_API_KEY 且请求无 x-api-key → _auth_check 返回错误 JSON"""
        import mcp_server as ms
        png_path = tmp_path / "ref.png"
        png_path.write_bytes(_png_bytes())
        # 模拟 keystore 中已有 key（任意非空字符串），但 env 未配置 → 应拒绝
        monkeypatch.setattr(ms.keystore, "has_any", lambda: True)
        data = json.loads(ms.image_to_prompt(str(png_path), backend="mock"))
        assert data.get("error")
        assert "API Key" in data["error"]


class TestFullPipelineImage:
    """full_pipeline(image_path=...) 闭环测试"""

    def test_success_with_image_path(self, monkeypatch, tmp_path):
        """图→prompt→生图→描图→Pantone→报价→ZIP 全链路"""
        import mcp_server as ms
        import zipfile

        png = _png_bytes()
        src = tmp_path / "src.png"
        src.write_bytes(png)
        out = tmp_path / "pipeline"

        # 图→prompt 走 mock
        monkeypatch.setattr(ms, "dispatch_prompt",
                            lambda b, **kw: PromptResult(
                                prompt="a red gift box on white background",
                                backend="mock", model="mock-v1"))

        def fake_dispatch(prompt, **kw):
            # 断言：prompt 来自 image_to_prompt，而非空
            assert "red gift box" in prompt
            return [GenResult(png_bytes=png, width=1, height=1,
                              backend="fal", model="flux")]

        monkeypatch.setattr("mcp_server.gen_dispatch", fake_dispatch)
        monkeypatch.setattr(ms.sdk, "cutout", lambda path, **kw: path)

        def fake_trace(path, **kw):
            p = tmp_path / "out.svg"
            p.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1">'
                '<rect fill="#DA291C" width="1" height="1"/></svg>',
                encoding="utf-8",
            )
            return str(p)

        monkeypatch.setattr(ms.sdk, "trace", fake_trace)

        data = json.loads(ms.full_pipeline(image_path=str(src), output_dir=str(out)))
        assert data["success"] is True, data
        assert os.path.exists(data["zip_path"])
        with zipfile.ZipFile(data["zip_path"]) as zf:
            assert "colorflow_gen.png" in set(zf.namelist())

    def test_image_to_prompt_failure_short_circuits(self, monkeypatch, tmp_path):
        """图→prompt 失败 → 直接返回错误，不生图"""
        import mcp_server as ms

        src = tmp_path / "src.png"
        src.write_bytes(_png_bytes())

        def boom(b, **kw):
            raise PromptError("timeout", "vision slow", retryable=True)

        monkeypatch.setattr(ms, "dispatch_prompt", boom)
        data = json.loads(ms.full_pipeline(image_path=str(src),
                                           output_dir=str(tmp_path)))
        assert data.get("error")
        assert data["code"] == "timeout"
        assert data["retryable"] is True
        assert not os.path.exists(str(tmp_path / "colorflow_pipeline.zip"))

    def test_missing_both_prompt_and_image(self):
        """prompt 与 image_path 都不给 → 报错"""
        import mcp_server as ms
        data = json.loads(ms.full_pipeline())
        assert data.get("error")
        assert "至少提供一个" in data["error"]
