"""Agent Loop 离线 mock 测试（plan §15 pytest）。

只替换两端（LLM 与 Mongo），真实跑循环 / 消息拼装 / SSE 产出 / 历史写入。
"""
import json
from dataclasses import dataclass

import pytest

import app.agent.loop as loop
import app.history.local_history_store as store
from app.tools.formatter import (
    format_db_unavailable_result,
    format_error_result,
    format_find_result,
)


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


def tc(call_id, args, name="execute_mongo_query"):
    return FakeToolCall(id=call_id, function=FakeFunc(
        name=name, arguments=json.dumps(args)))


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    store.SESSION_HISTORY.clear()
    monkeypatch.setattr(store, "_jsonl_path", lambda: tmp_path / "events.jsonl")
    monkeypatch.setattr(
        loop,
        "build_scene_count_context",
        lambda script_id: "- 原文表检测到可靠场次数：2 场（测试桩）。",
    )
    yield
    store.SESSION_HISTORY.clear()


async def drain(gen):
    events = []
    async for e in gen:
        events.append(e)
    return events


def event_names(events):
    return [e.split("\n", 1)[0].replace("event: ", "") for e in events]


def event_data(event: str) -> dict:
    data_line = [line for line in event.splitlines() if line.startswith("data: ")][0]
    return json.loads(data_line.removeprefix("data: "))


@pytest.mark.asyncio
async def test_tool_call_then_final_answer(monkeypatch):
    calls = {"n": 0}

    async def fake_complete(messages, tools):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeMessage(content=None, tool_calls=[
                tc("call_1", {"collection": "seca_gen_scene_outline",
                              "operation": "find",
                              "filter": {"scene_sort": 8},
                              "purpose": "查第8场"})])
        return FakeMessage(content="不该到这", tool_calls=None)

    async def fake_stream(messages):
        for t in ["第8场", "中，", "戒指丢了。"]:
            yield t

    def fake_exec(script_id, args):
        return format_find_result(
            collection="seca_gen_scene_outline", operation="find",
            purpose=args.get("purpose", ""),
            rows=[{"scene_sort": 8, "scene_summary": "戒指丢了"}])

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
    assert "剧本原文资料" in tool_result_e


@pytest.mark.asyncio
async def test_empty_final_stream_yields_visible_fallback(monkeypatch):
    monkeypatch.setattr(loop.settings, "max_tool_rounds", 1)

    async def fake_complete(messages, tools):
        return FakeMessage(content=None, tool_calls=[
            tc("call_1", {
                "collection": "seca_gen_scene_outline",
                "operation": "find",
                "filter": {},
                "purpose": "查资料后回答",
            })
        ])

    async def fake_stream(messages):
        assert messages[-1]["role"] == "system"
        assert "必须仅基于上面的资料查询结果直接给出中文回答" in messages[-1]["content"]
        if False:
            yield ""

    def fake_exec(script_id, args):
        return format_find_result(
            collection="seca_gen_scene_outline", operation="find",
            purpose=args.get("purpose", ""),
            rows=[{"scene_sort": 1, "scene_summary": "有一场关键戏"}],
        )

    monkeypatch.setattr(loop, "complete_with_tools", fake_complete)
    monkeypatch.setattr(loop, "stream_final_answer", fake_stream)
    monkeypatch.setattr(loop, "execute_mongo_query", fake_exec)

    events = await drain(loop.run_chat_stream(
        session_id="s_empty", script_id="script_001",
        question="需要查资料的问题", trace_id="t_empty"))

    names = event_names(events)
    assert "tool_result" in names
    assert names[-2] == "delta"
    assert names[-1] == "done"
    assert "最终回答没有生成出有效文本" in event_data(events[-2])["text"]
    assert store.get_history("s_empty")[-1]["content"]


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
        assert "每 50 场一批" in system_prompt
        assert "1-50、51-100" in system_prompt
        assert "通读剧本原文所有场次" in tool_schema_text
        assert "每50场一批" in tool_schema_text

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
async def test_misspelled_character_name_requires_clarification(monkeypatch):
    calls = {"complete": 0}
    resolved = []

    async def fake_complete(messages, tools):
        calls["complete"] += 1
        system_prompt = messages[0]["content"]
        tool_schema_text = json.dumps(tools, ensure_ascii=False)
        assert "resolve_character_name" in tool_schema_text
        assert "未被当前资料可靠确认" in system_prompt
        assert "不得直接回答“不存在”" in system_prompt
        assert "clarification_required=true" in system_prompt

        if calls["complete"] == 1:
            return FakeMessage(content=None, tool_calls=[
                tc("call_resolve", {
                    "raw_name": "暗迪",
                    "purpose": "核实用户提到的人物名",
                }, name="resolve_character_name")
            ])
        if calls["complete"] == 2:
            assert any(
                m.get("role") == "tool" and "安迪·杜弗兰" in m.get("content", "")
                for m in messages
            )
            return FakeMessage(content=None, tool_calls=None)
        return FakeMessage(content=None, tool_calls=None)

    def fake_resolve(script_id, args):
        resolved.append(args["raw_name"])
        payload = {
            "raw_name": "暗迪",
            "matched": False,
            "canonical_name": None,
            "clarification_required": True,
            "candidates": [
                {"name": "安迪·杜弗兰", "score": 0.5, "remark": "原银行副总裁"},
                {"name": "瑞德", "score": 0.0, "remark": "囚犯"},
            ],
        }
        result = format_find_result(
            collection="resolve_character_name", operation="resolve",
            purpose=args.get("purpose", ""), rows=[payload],
        )
        result.payload = payload
        return result

    def fake_exec(script_id, args):
        raise AssertionError("澄清前不应继续查询对手戏")

    async def fake_stream(messages):
        raise AssertionError("需要澄清时应使用确定性澄清话术")
        yield ""

    monkeypatch.setattr(loop, "complete_with_tools", fake_complete)
    monkeypatch.setattr(loop, "stream_final_answer", fake_stream)
    monkeypatch.setattr(loop, "resolve_character_name", fake_resolve)
    monkeypatch.setattr(loop, "execute_mongo_query", fake_exec)

    events = await drain(loop.run_chat_stream(
        session_id="s_resolve", script_id="script_001",
        question="暗迪有对手戏的几个角色是谁？", trace_id="t_resolve"))

    assert resolved == ["暗迪"]
    assert calls["complete"] == 1
    assert event_names(events).count("tool_start") == 1
    assert store.get_history("s_resolve")[-1]["content"] == (
        "你说的“暗迪”是否指“安迪·杜弗兰”？请确认后我再继续核实。"
    )


@pytest.mark.asyncio
async def test_db_unavailable_uses_fixed_user_message(monkeypatch):
    async def fake_complete(messages, tools):
        return FakeMessage(content=None, tool_calls=[
            tc("call_db", {
                "collection": "seca_gen_scene_outline",
                "operation": "find",
                "filter": {"scene_sort": 1},
                "purpose": "查询第1场剧情",
            })
        ])

    async def fake_stream(messages):
        raise AssertionError("数据库不可用时不应再调用终答模型")
        yield ""

    def fake_exec(script_id, args):
        return format_db_unavailable_result(purpose=args.get("purpose", ""))

    monkeypatch.setattr(loop, "complete_with_tools", fake_complete)
    monkeypatch.setattr(loop, "stream_final_answer", fake_stream)
    monkeypatch.setattr(loop, "execute_mongo_query", fake_exec)

    events = await drain(loop.run_chat_stream(
        session_id="s_db_down", script_id="script_001",
        question="第1场发生了什么？", trace_id="t_db_down"))

    delta_events = [e for e in events if e.startswith("event: delta")]
    assert len(delta_events) == 1
    assert "剧本数据库暂时连接不上，可以稍后再试。" in delta_events[0]
    assert store.get_history("s_db_down")[-1]["content"] == (
        "剧本数据库暂时连接不上，可以稍后再试。"
    )


@pytest.mark.asyncio
async def test_db_timeout_uses_fixed_user_message(monkeypatch):
    async def fake_complete(messages, tools):
        return FakeMessage(content=None, tool_calls=[
            tc("call_timeout", {
                "collection": "seca_gen_scene_outline",
                "operation": "find",
                "purpose": "查询原文",
            })
        ])

    async def fake_stream(messages):
        raise AssertionError("数据库超时时不应再调用终答模型")
        yield ""

    def fake_exec(script_id, args):
        return format_db_unavailable_result(
            purpose=args.get("purpose", ""), error_code="db_timeout"
        )

    monkeypatch.setattr(loop, "complete_with_tools", fake_complete)
    monkeypatch.setattr(loop, "stream_final_answer", fake_stream)
    monkeypatch.setattr(loop, "execute_mongo_query", fake_exec)

    events = await drain(loop.run_chat_stream(
        session_id="s_db_timeout", script_id="script_001",
        question="读取原文", trace_id="t_db_timeout"))

    assert event_names(events)[-1] == "done"
    assert "剧本数据库暂时连接不上，可以稍后再试。" in "".join(events)


@pytest.mark.asyncio
async def test_internal_tool_error_is_not_reported_as_db_unavailable(monkeypatch):
    calls = {"complete": 0}

    async def fake_complete(messages, tools):
        calls["complete"] += 1
        if calls["complete"] == 1:
            return FakeMessage(content=None, tool_calls=[
                tc("call_internal", {
                    "collection": "seca_gen_scene_outline",
                    "operation": "find",
                    "purpose": "查询原文",
                })
            ])
        assert any(
            m.get("role") == "tool" and "internal_error" in m.get("content", "")
            for m in messages
        )
        return FakeMessage(content=None, tool_calls=None)

    async def fake_stream(messages):
        yield "当前资料处理失败，无法完成核实。"

    def fake_exec(script_id, args):
        return format_error_result(
            purpose=args.get("purpose", ""),
            error="剧本资料处理失败，当前无法完成核实。",
            error_code="internal_error",
        )

    monkeypatch.setattr(loop, "complete_with_tools", fake_complete)
    monkeypatch.setattr(loop, "stream_final_answer", fake_stream)
    monkeypatch.setattr(loop, "execute_mongo_query", fake_exec)

    events = await drain(loop.run_chat_stream(
        session_id="s_internal", script_id="script_001",
        question="读取原文", trace_id="t_internal"))

    assert event_names(events)[-1] == "done"
    assert calls["complete"] == 2
    assert "剧本数据库暂时连接不上" not in "".join(events)


@pytest.mark.asyncio
async def test_llm_connection_error_uses_safe_user_message(monkeypatch):
    async def fake_complete(messages, tools):
        raise Exception("Connection error.")

    async def fake_stream(messages):
        raise AssertionError("工具轮连接失败时不应进入终答")
        yield ""

    monkeypatch.setattr(loop, "complete_with_tools", fake_complete)
    monkeypatch.setattr(loop, "stream_final_answer", fake_stream)

    events = await drain(loop.run_chat_stream(
        session_id="s_llm_down", script_id="script_001",
        question="暗迪有对手戏的几个角色是谁？", trace_id="t_llm_down"))

    assert event_names(events)[-1] == "error"
    error_payload = event_data(events[-1])
    assert error_payload["message"] == "模型服务暂时连接不上，可以稍后再试。"
    assert "Connection error" not in events[-1]


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
            tc(f"call_{n['complete']}", {"collection": "seca_gen_scene_outline",
                                         "operation": "find",
                                         "purpose": "反复查"})])

    async def fake_stream(messages):
        yield "强制终答。"

    def fake_exec(script_id, args):
        return format_find_result(
            collection="seca_gen_scene_outline", operation="find",
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
                tc(f"call_{n['complete']}", {"collection": "seca_gen_scene_outline",
                                             "operation": "find", "purpose": "查"})])
        return FakeMessage(content=None, tool_calls=None)

    async def fake_stream(messages):
        yield "结束。"

    def fake_exec(script_id, args):
        n["exec"] += 1
        return format_find_result(
            collection="seca_gen_scene_outline", operation="find",
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
