"""ColorFlow KeyStore 单元测试（纯标准库，不依赖 Flask / reportlab）。

可在无项目依赖环境直接运行：``python tests/test_keystore.py``。
函数名以 test_ 开头，亦兼容 pytest。
验证 P0-1：key_id 非敏感、list_all 不泄露明文、revoke 按 key_id、历史 entry 惰性迁移。
"""

import json
import os
import tempfile

from colorflow_keys import KeyStore, _now_iso


def _fresh_keystore():
    """返回一个指向临时 keys.json 的 KeyStore，避免污染真实存储。"""
    d = tempfile.mkdtemp(prefix="cf_keys_test_")
    path = os.path.join(d, "keys.json")
    return KeyStore(path=path), d


def test_generate_returns_key_and_key_id():
    ks, _ = _fresh_keystore()
    entry = ks.generate(name="unit")
    assert entry["key"].startswith("cf_sk_")
    assert entry["key_id"].startswith("kid_")
    assert entry["key_id"] != entry["key"]
    # 明文 key 不得以作为 key_id 的子串出现
    assert entry["key"] not in entry["key_id"]


def test_list_all_never_leaks_plaintext():
    ks, _ = _fresh_keystore()
    entry = ks.generate(name="secret")
    raw_key = entry["key"]
    rows = ks.list_all()
    assert len(rows) == 1
    row = rows[0]
    # 返回的是非敏感 key_id，不是明文
    assert row["key_id"] == entry["key_id"]
    assert row["key_id"].startswith("kid_")
    assert row["key_id"] != raw_key
    # 脱敏字段含 ****
    assert "****" in row["key_masked"]
    # 整行序列化里不得出现明文 key
    assert raw_key not in json.dumps(row)


def test_revoke_by_key_id():
    ks, _ = _fresh_keystore()
    entry = ks.generate(name="to-revoke")
    key_id = entry["key_id"]
    # 按非敏感 key_id 撤销
    assert ks.revoke(key_id) is True
    assert ks.has_any() is False
    # 再次撤销（幂等）→ False
    assert ks.revoke(key_id) is False
    # 用明文 key 去撤销不得成功（旧路径已废弃）
    entry2 = ks.generate(name="second")
    assert ks.revoke(entry2["key"]) is False
    assert ks.has_any() is True
    # 清理
    assert ks.revoke(entry2["key_id"]) is True


def test_legacy_entries_lazy_migrated_stable():
    """历史 entry 缺 key_id：list_all 触发迁移并持久化，且 key_id 稳定。"""
    ks, d = _fresh_keystore()
    path = ks.path
    # 手写一个 legacy entry（无 key_id）
    legacy = [{"key": "cf_sk_legacy" + "a" * 27, "name": "legacy", "created_at": "t", "last_used": None}]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(legacy, f)
    # 第一次 list_all 触发迁移，返回一个 key_id
    rows1 = ks.list_all()
    assert len(rows1) == 1
    kid1 = rows1[0]["key_id"]
    assert kid1.startswith("kid_")
    assert kid1 != rows1[0]["key_masked"]
    # 明文不得泄露
    assert legacy[0]["key"] not in json.dumps(rows1[0])
    # 第二次 list_all → 同一个 key_id（已持久化，稳定）
    rows2 = ks.list_all()
    assert rows2[0]["key_id"] == kid1
    # 该 key_id 可用于撤销
    assert ks.revoke(kid1) is True
    assert ks.has_any() is False


def test_verify_still_works():
    """P0-1 不得破坏 verify 路径。"""
    ks, _ = _fresh_keystore()
    entry = ks.generate(name="verify-me")
    raw = entry["key"]
    assert ks.verify(raw) is True
    assert ks.verify("cf_sk_wrong") is False
    assert ks.verify("") is False
    # verify 后 last_used 应被更新
    rows = ks.list_all()
    assert rows[0]["last_used"] is not None


def test_bootstrap_from_env_assigns_key_id():
    ks, _ = _fresh_keystore()
    ks.bootstrap_from_env("cf_sk_fromenv" + "b" * 21)
    rows = ks.list_all()
    assert len(rows) == 1
    assert rows[0]["key_id"].startswith("kid_")
    # 幂等：再次 bootstrap 同一 env key 不重复
    ks.bootstrap_from_env("cf_sk_fromenv" + "b" * 21)
    assert len(ks.list_all()) == 1


def test_revoke_rejects_empty_id_without_wiping():
    """空 / None key_id 撤销必须被拒绝，不得清空全部 key（数据防误删）。"""
    ks, _ = _fresh_keystore()
    e1 = ks.generate(name="a")
    e2 = ks.generate(name="b")
    assert ks.revoke("") is False
    assert ks.revoke(None) is False
    assert len(ks.list_all()) == 2
    assert ks.revoke(e1["key_id"]) is True
    assert ks.revoke(e2["key_id"]) is True
    assert ks.has_any() is False


def test_verify_tolerates_persist_failure():
    """认证热路径：写盘失败（磁盘异常）不得阻断 verify（P0-1 不抛错）。"""
    ks, _ = _fresh_keystore()
    entry = ks.generate(name="durable")

    def boom(keys):
        raise OSError("disk full")

    ks._save = boom
    assert ks.verify(entry["key"]) is True  # 校验成功，即便 last_used 持久化失败
    assert ks.verify("cf_sk_wrong") is False


def test_verify_skips_write_when_last_used_unchanged():
    """last_used 在同一秒内未变化时，verify 不重复写盘（认证热路径减负）。"""
    import colorflow_keys

    ks, _ = _fresh_keystore()
    entry = ks.generate(name="hot")
    fixed = "2026-01-01T00:00:00+00:00"
    with open(ks.path, "w", encoding="utf-8") as f:
        json.dump([dict(entry, last_used=fixed)], f)
    orig_now = colorflow_keys._now_iso
    colorflow_keys._now_iso = lambda: fixed
    try:
        calls = []
        orig_save = ks._save

        def counting(keys):
            calls.append(1)
            orig_save(keys)

        ks._save = counting
        assert ks.verify(entry["key"]) is True
        assert calls == []
    finally:
        colorflow_keys._now_iso = orig_now


_RUNNABLE = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]


if __name__ == "__main__":
    passed = 0
    failed = 0
    for t in _RUNNABLE:
        name = t.__name__
        try:
            t()
            print(f"PASS  {name}")
            passed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
