"""会话级摘要压缩单元测试（离线，summarize 用 mock）。"""
import pytest

import app.history.local_history_store as store
import app.history.session_compactor as sc


def turn(i, with_tool=True):
    """构造一个完整 turn：user + assistant(tool_calls) + tool + assistant(final)。"""
    msgs = [{"role": "user", "content": f"问题{i}" + "啊" * 30}]
    if with_tool:
        msgs.append({"role": "assistant", "content": None,
                     "tool_calls": [{"id": f"call_{i}", "type": "function",
                                     "function": {"name": "execute_mongo_query",
                                                  "arguments": "{}"}}]})
        msgs.append({"role": "tool", "tool_call_id": f"call_{i}",
                     "content": f"结果{i}" + "数" * 60})
    msgs.append({"role": "assistant", "content": f"回答{i}" + "答" * 30})
    return msgs


def history(n):
    return [m for i in range(n) for m in turn(i)]


@pytest.fixture(autouse=True)
def clean():
    store.SESSION_HISTORY.clear()
    store.SESSION_SUMMARY.clear()
    yield
    store.SESSION_HISTORY.clear()
    store.SESSION_SUMMARY.clear()


# ---------- 纯逻辑 ----------
def test_split_turns_groups_by_user_boundary():
    turns = sc.split_turns(history(3))
    assert len(turns) == 3
    assert all(t[0]["role"] == "user" for t in turns)
    # 每个 turn 内 tool_call 与 tool 成对
    for t in turns:
        assert any(m["role"] == "assistant" and m.get("tool_calls") for m in t)
        assert any(m["role"] == "tool" for m in t)


def test_select_eviction_no_evict_when_few_turns():
    h = history(2)
    evicted, protected = sc.select_eviction(h, protect_tokens=1, min_recent_turns=3)
    assert evicted == []
    assert protected == h


def test_select_eviction_protects_min_turns_and_evicts_older():
    h = history(8)
    evicted, protected = sc.select_eviction(h, protect_tokens=1, min_recent_turns=3)
    # 至少保留最近 3 个 turn
    assert len(sc.split_turns(protected)) == 3
    assert len(evicted) > 0
    # 被保留的是最新 3 个 turn（含 问题5/6/7）
    assert protected[0]["content"].startswith("问题5")


def test_eviction_never_orphans_tool_message():
    h = history(8)
    evicted, protected = sc.select_eviction(h, protect_tokens=1, min_recent_turns=3)
    for seg in (evicted, protected):
        open_ids = set()
        for m in seg:
            if m["role"] == "assistant":
                for tc in (m.get("tool_calls") or []):
                    open_ids.add(tc["id"])
            elif m["role"] == "tool":
                # 每个 tool 的 call_id 必须在同段里有对应 assistant.tool_calls
                assert m["tool_call_id"] in open_ids, "孤立 tool 消息，配对被破坏"


def test_protect_tokens_keeps_more_when_large():
    h = history(8)
    # 很大的 protect_tokens → 保留更多 turn
    _, protected = sc.select_eviction(h, protect_tokens=10_000_000, min_recent_turns=1)
    assert len(sc.split_turns(protected)) == 8  # 全保留，无可淘汰


def test_extract_summary_wraps_and_strips():
    assert sc.extract_summary("foo <summary> AAA </summary> bar") == "<summary>\nAAA\n</summary>"
    assert sc.extract_summary("无标签内容").startswith("<summary>")


# ---------- 编排（mock summarize）----------
@pytest.mark.asyncio
async def test_no_compaction_below_threshold(monkeypatch):
    called = {"n": 0}

    async def fake_sum(prev, ev):
        called["n"] += 1
        return "<summary>X</summary>"

    monkeypatch.setattr(sc, "summarize", fake_sum)
    for m in history(8):
        store.append_message("s1", m, persist=False)

    did = await sc.compact_session_if_needed("s1", measured_tokens=1)
    assert did is False
    assert called["n"] == 0
    assert len(store.get_history("s1")) == len(history(8))


@pytest.mark.asyncio
async def test_compaction_triggers_and_rebuilds(monkeypatch):
    captured = {}

    async def fake_sum(prev, ev):
        captured["prev"] = prev
        captured["evicted"] = ev
        return "<summary>SUM</summary>"

    monkeypatch.setattr(sc, "summarize", fake_sum)
    monkeypatch.setattr(sc.settings, "compact_recent_protect_tokens", 1)
    for m in history(8):
        store.append_message("s1", m, persist=False)

    did = await sc.compact_session_if_needed("s1", measured_tokens=10**9)
    assert did is True
    # 摘要写入
    assert store.get_summary("s1") == "<summary>SUM</summary>"
    # 历史只剩受保护的最近 3 个 turn
    new_h = store.get_history("s1")
    assert len(sc.split_turns(new_h)) == 3
    assert new_h[0]["content"].startswith("问题5")
    # 被淘汰的是更早的 turn
    assert captured["prev"] is None
    assert len(captured["evicted"]) > 0
    # 压缩后历史里无孤立 tool
    open_ids = set()
    for m in new_h:
        if m["role"] == "assistant":
            for tc in (m.get("tool_calls") or []):
                open_ids.add(tc["id"])
        elif m["role"] == "tool":
            assert m["tool_call_id"] in open_ids


@pytest.mark.asyncio
async def test_recursive_passes_prev_summary(monkeypatch):
    async def fake_sum(prev, ev):
        return f"<summary>prev={bool(prev)}</summary>"

    monkeypatch.setattr(sc, "summarize", fake_sum)
    monkeypatch.setattr(sc.settings, "compact_recent_protect_tokens", 1)
    store.set_summary("s1", "<summary>OLD</summary>")
    for m in history(8):
        store.append_message("s1", m, persist=False)

    captured = {}

    async def fake_sum2(prev, ev):
        captured["prev"] = prev
        return "<summary>NEW</summary>"

    monkeypatch.setattr(sc, "summarize", fake_sum2)
    await sc.compact_session_if_needed("s1", measured_tokens=10**9)
    assert captured["prev"] == "<summary>OLD</summary>"


@pytest.mark.asyncio
async def test_summarize_failure_degrades_without_data_loss(monkeypatch):
    async def boom(prev, ev):
        raise RuntimeError("llm down")

    monkeypatch.setattr(sc, "summarize", boom)
    monkeypatch.setattr(sc.settings, "compact_recent_protect_tokens", 1)
    for m in history(8):
        store.append_message("s1", m, persist=False)
    before = len(store.get_history("s1"))

    did = await sc.compact_session_if_needed("s1", measured_tokens=10**9)
    assert did is False
    # 不丢消息（降级为 tool 剪枝，条数不变）
    assert len(store.get_history("s1")) == before
    # 无摘要写入
    assert store.get_summary("s1") is None
