"""Local History Store 单元测试（离线，真实写 JSONL 到临时目录）。"""
import importlib

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    # 把 LOG_DIR 指到临时目录，重载相关模块使 settings 生效
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    import app.config as config
    importlib.reload(config)
    import app.logging_config as logging_config
    importlib.reload(logging_config)
    import app.history.local_history_store as s
    importlib.reload(s)
    s.SESSION_HISTORY.clear()
    return s


def test_empty_history(store):
    assert store.get_history("sess_x") == []


def test_append_and_order(store):
    store.append_message("s1", {"role": "user", "content": "q"}, script_id="script_001")
    store.append_message("s1", {"role": "assistant", "content": "a"}, script_id="script_001")
    h = store.get_history("s1")
    assert [m["role"] for m in h] == ["user", "assistant"]


def test_session_isolation(store):
    store.append_message("s1", {"role": "user", "content": "a"})
    store.append_message("s2", {"role": "user", "content": "b"})
    assert len(store.get_history("s1")) == 1
    assert len(store.get_history("s2")) == 1
    assert store.get_history("s1")[0]["content"] == "a"


def test_jsonl_written(store, tmp_path):
    store.append_message(
        "s1", {"role": "user", "content": "第8场发生了什么？"},
        trace_id="trace_1", script_id="script_001",
    )
    jsonl = tmp_path / "conversation_events.jsonl"
    assert jsonl.exists()
    content = jsonl.read_text(encoding="utf-8").strip()
    assert "第8场发生了什么？" in content
    assert "trace_1" in content
    assert "script_001" in content


def test_clear(store):
    store.append_message("s1", {"role": "user", "content": "q"})
    store.clear_history("s1")
    assert store.get_history("s1") == []


def test_replace(store):
    store.append_message("s1", {"role": "user", "content": "q"})
    store.replace_history("s1", [{"role": "system", "content": "x"}])
    h = store.get_history("s1")
    assert len(h) == 1 and h[0]["role"] == "system"


def test_get_returns_copy(store):
    store.append_message("s1", {"role": "user", "content": "q"})
    h = store.get_history("s1")
    h[0]["content"] = "mutated"
    assert store.get_history("s1")[0]["content"] == "q"
