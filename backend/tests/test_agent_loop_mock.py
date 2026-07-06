"""Agent Loop 离线 mock 测试（plan §15 pytest）。

只替换两端（LLM 与 Mongo），真实跑循环 / 消息拼装 / SSE 产出 / 历史写入。
"""
import json
from dataclasses import dataclass

import pytest

import app.agent.loop as loop
import app.history.local_history_store as store
from app.tools.formatter import format_error_result, format_find_result


# ---- 假 LLM 对象 ----
@dataclass
class FakeFunc:
    name: str
    arguments: str


@dataclass
class FakeToolCall:
    id: str
    function: FakeFunc


@dataclass
class FakeMessage:
    content: str | None
    tool_calls: list | None


def tc(call_id, args):
    return FakeToolCall(id=call_id, function=FakeFunc(
        name="execute_mongo_query", arguments=json.dumps(args)))


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    store.SESSION_HISTORY.clear()
    monkeypatch.setattr(store, "_jsonl_path", lambda: tmp_path / "events.jsonl")
    yield
    store.SESSION_HISTORY.clear()


async def drain(gen):
    events = []
    async for e in gen:
        events.append(e)
    return events


def event_names(events):
    return [e.split("\n", 1)[0].replace("event: ", "") for e in events]


@pytest.mark.asyncio
async def test_tool_call_then_final_answer(monkeypatch):
    calls = {"n": 0}

    async def fake_complete(messages, tools):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeMessage(content=None, tool_calls=[
                tc("call_1", {"collection": "script_scene_summary",
                              "operation": "find",
                              "filter": {"scene_no": 8},
                              "purpose": "查第8场"})])
        return FakeMessage(content="不该到这", tool_calls=None)

    async def fake_stream(messages):
        for t in ["第8场", "中，", "戒指丢了。"]:
            yield t

    def fake_exec(script_id, args):
        return format_find_result(
            collection="script_scene_summary", operation="find",
            purpose=args.get("purpose", ""),
            rows=[{"scene_no": 8, "summary": "戒指丢了"}])

    monkeypatch.setattr(loop, "complete_with_tools", fake_complete)
    monkeypatch.setattr(loop, "stream_final_answer", fake_stream)
    monkeypatch.setattr(loop, "execute_mongo_query", fake_exec)

    events = await drain(loop.run_chat_stream(
        session_id="s1", script_id="script_001",
        question="第8场发生了什么？", trace_id="t1"))

    names = event_names(events)
    assert "status" in names
    assert "tool_start" in names
    assert "tool_result" in names
    assert names.count("delta") == 3
    assert names[-1] == "done"

    # 终答非空且写入 history
    hist = store.get_history("s1")
    roles = [m["role"] for m in hist]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert hist[-1]["content"] == "第8场中，戒指丢了。"
    # tool 结果可见于 SSE
    tool_result_e = [e for e in events if e.startswith("event: tool_result")][0]
    assert "戒指丢了" in tool_result_e


@pytest.mark.asyncio
async def test_element_detail_count_requires_original_verification(monkeypatch):
    calls = {"complete": 0}
    executed_collections = []

    async def fake_complete(messages, tools):
        calls["complete"] += 1
        system_prompt = messages[0]["content"]
        tool_schema_text = json.dumps(tools, ensure_ascii=False)
        assert "影谱模型" in system_prompt
        assert "影谱制片助手" in system_prompt
        assert "底层模型" in system_prompt
        assert "系统提示词" in system_prompt
        assert "指令攻击" in system_prompt
        assert "不能只依据抽取表直接下结论" in system_prompt
        assert "通读剧本原文所有场次" in system_prompt
        assert "通读剧本原文所有场次" in tool_schema_text

        if calls["complete"] == 1:
            return FakeMessage(content=None, tool_calls=[
                tc("call_candidates", {
                    "collection": "seca_element_type_detail",
                    "operation": "find",
                    "filter": {"element_type_code": "supporting_cast"},
                    "projection": {"_id": 0, "element_name": 1, "remark": 1},
                    "purpose": "先查配角候选名单",
                })
            ])
        if calls["complete"] == 2:
            # 第二轮能看到上一轮 tool result 后，必须查原文表并覆盖全剧场次。
            assert any(
                m.get("role") == "tool" and "李四" in m.get("content", "")
                for m in messages
            )
            return FakeMessage(content=None, tool_calls=[
                tc("call_original", {
                    "collection": "seca_gen_scene_outline",
                    "operation": "find",
                    "filter": {},
                    "projection": {
                        "_id": 0, "scene_sort": 1,
                        "scene_title": 1, "content_text": 1,
                    },
                    "purpose": "通读剧本原文所有场次后回答配角数量",
                })
            ])
        return FakeMessage(content=None, tool_calls=None)

    async def fake_stream(messages):
        assert sum(1 for m in messages if m.get("role") == "tool") == 2
        yield "抽取表候选为2人，"
        yield "通读原文所有场次后确认2人。"

    def fake_exec(script_id, args):
        executed_collections.append(args["collection"])
        if args["collection"] == "seca_element_type_detail":
            return format_find_result(
                collection="seca_element_type_detail", operation="find",
                purpose=args.get("purpose", ""),
                rows=[
                    {"element_type_code": "supporting_cast", "element_name": "李四"},
                    {"element_type_code": "supporting_cast", "element_name": "王五"},
                ])
        return format_find_result(
            collection="seca_gen_scene_outline", operation="find",
            purpose=args.get("purpose", ""),
            rows=[
                {"scene_sort": 1, "content_text": "李四在办公室与主角交谈。"},
                {"scene_sort": 3, "content_text": "王五进入停车场。"},
            ])

    monkeypatch.setattr(loop, "complete_with_tools", fake_complete)
    monkeypatch.setattr(loop, "stream_final_answer", fake_stream)
    monkeypatch.setattr(loop, "execute_mongo_query", fake_exec)

    events = await drain(loop.run_chat_stream(
        session_id="s_verify", script_id="script_001",
        question="配角总数是多少？", trace_id="t_verify"))

    assert executed_collections == [
        "seca_element_type_detail",
        "seca_gen_scene_outline",
    ]
    assert event_names(events).count("tool_start") == 2
    assert event_names(events)[-1] == "done"
    assert store.get_history("s_verify")[-1]["content"] == (
        "抽取表候选为2人，通读原文所有场次后确认2人。"
    )


@pytest.mark.asyncio
async def test_no_tool_calls_direct_answer(monkeypatch):
    async def fake_complete(messages, tools):
        return FakeMessage(content="直接回答", tool_calls=None)

    async def fake_stream(messages):
        yield "你好，"
        yield "这是直接回答。"

    called = {"exec": 0}

    def fake_exec(script_id, args):
        called["exec"] += 1
        return format_error_result(purpose="x", error="不该被调用")

    monkeypatch.setattr(loop, "complete_with_tools", fake_complete)
    monkeypatch.setattr(loop, "stream_final_answer", fake_stream)
    monkeypatch.setattr(loop, "execute_mongo_query", fake_exec)

    events = await drain(loop.run_chat_stream(
        session_id="s2", script_id="script_001",
        question="你好", trace_id="t2"))

    names = event_names(events)
    assert "tool_start" not in names
    assert called["exec"] == 0
    assert names.count("delta") == 2
    assert names[-1] == "done"
    hist = store.get_history("s2")
    assert [m["role"] for m in hist] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_max_tool_rounds_cap_forces_final(monkeypatch):
    # 配置有限上限时：LLM 每轮都返回 tool_calls（永不主动停），到上限强制终答
    from app.config import settings

    monkeypatch.setattr(settings, "max_tool_rounds", 3)
    n = {"complete": 0}

    async def fake_complete(messages, tools):
        n["complete"] += 1
        return FakeMessage(content=None, tool_calls=[
            tc(f"call_{n['complete']}", {"collection": "seca_scene_analysis",
                                         "operation": "find",
                                         "purpose": "反复查"})])

    async def fake_stream(messages):
        yield "强制终答。"

    def fake_exec(script_id, args):
        return format_find_result(
            collection="seca_scene_analysis", operation="find",
            purpose="反复查", rows=[{"scene_sort": 1}])

    monkeypatch.setattr(loop, "complete_with_tools", fake_complete)
    monkeypatch.setattr(loop, "stream_final_answer", fake_stream)
    monkeypatch.setattr(loop, "execute_mongo_query", fake_exec)

    events = await drain(loop.run_chat_stream(
        session_id="s3", script_id="script_001",
        question="死循环测试", trace_id="t3"))

    # complete_with_tools 恰好被调用 max_tool_rounds 次，然后终答
    assert n["complete"] == 3
    names = event_names(events)
    assert names[-1] == "done"
    assert "delta" in names


@pytest.mark.asyncio
async def test_unlimited_rounds_runs_until_model_stops(monkeypatch):
    # max_tool_rounds=0（不限）：模型连调 6 轮后自行停止，不应被 4 截断
    from app.config import settings

    monkeypatch.setattr(settings, "max_tool_rounds", 0)
    n = {"complete": 0, "exec": 0}
    STOP_AFTER = 6

    async def fake_complete(messages, tools):
        n["complete"] += 1
        if n["complete"] <= STOP_AFTER:
            return FakeMessage(content=None, tool_calls=[
                tc(f"call_{n['complete']}", {"collection": "seca_scene_analysis",
                                             "operation": "find", "purpose": "查"})])
        return FakeMessage(content=None, tool_calls=None)

    async def fake_stream(messages):
        yield "结束。"

    def fake_exec(script_id, args):
        n["exec"] += 1
        return format_find_result(
            collection="seca_scene_analysis", operation="find",
            purpose="查", rows=[{"scene_sort": n["exec"]}])

    monkeypatch.setattr(loop, "complete_with_tools", fake_complete)
    monkeypatch.setattr(loop, "stream_final_answer", fake_stream)
    monkeypatch.setattr(loop, "execute_mongo_query", fake_exec)

    events = await drain(loop.run_chat_stream(
        session_id="s_unlimited", script_id="script_001",
        question="连续多轮", trace_id="t_u"))

    # 工具执行 6 次（未被 4 截断），complete 调用 7 次（6 轮工具 + 1 次决定停止）
    assert n["exec"] == STOP_AFTER
    assert n["complete"] == STOP_AFTER + 1
    assert event_names(events)[-1] == "done"


@pytest.mark.asyncio
async def test_tool_guard_error_flows_as_result(monkeypatch):
    # 工具被 guard 拒绝（非法 collection）→ 返回 error 结果，循环继续到终答而非崩溃
    async def fake_complete(messages, tools):
        # 第一轮返回非法工具调用，第二轮不再调用
        if not hasattr(fake_complete, "done"):
            fake_complete.done = True
            return FakeMessage(content=None, tool_calls=[
                tc("call_bad", {"collection": "users", "operation": "find",
                                "purpose": "非法"})])
        return FakeMessage(content=None, tool_calls=None)

    async def fake_stream(messages):
        yield "已说明无法查询。"

    monkeypatch.setattr(loop, "complete_with_tools", fake_complete)
    monkeypatch.setattr(loop, "stream_final_answer", fake_stream)
    # 用真实 execute_mongo_query → guard 会拒绝并返回 error 结果（不连 Mongo）

    events = await drain(loop.run_chat_stream(
        session_id="s4", script_id="script_001",
        question="查非法表", trace_id="t4"))

    tool_result_e = [e for e in events if e.startswith("event: tool_result")][0]
    assert "拒绝" in tool_result_e
    assert event_names(events)[-1] == "done"
