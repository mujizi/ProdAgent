"""自写 Agent Tool Loop（plan §12，最终版）。

- 工具轮：complete_with_tools(stream=False, tools=TOOLS)
- 终答：stream_final_answer(stream=True, tool_choice="none")
- Mongo 执行走 run_in_threadpool，不阻塞事件循环
- 到 MAX_TOOL_ROUNDS 仍要工具 → 直接进入终答
- 产出 SSE 事件字符串（async generator）

为便于离线 mock 测试，外部依赖以模块级名字导入（complete_with_tools /
stream_final_answer / execute_mongo_query），测试可直接 monkeypatch。
"""
from __future__ import annotations

import json
import time

from starlette.concurrency import run_in_threadpool

import app.agent.openrouter_client as orc
from app.agent.openrouter_client import complete_with_tools, stream_final_answer
from app.agent.prompts import SUMMARY_MARKER, SYSTEM_PROMPT
from app.agent.stream_events import (
    delta_event,
    done_event,
    error_event,
    status_event,
    tool_result_event,
    tool_start_event,
)
from app.agent.tool_schemas import TOOLS
from app.config import settings
from app.history.compactor import compact_tool_messages
from app.history.local_history_store import (
    append_message,
    get_history,
    get_summary,
    replace_history,
)
from app.history.session_compactor import (
    compact_session_if_needed,
    estimate_messages_tokens,
)
from app.logging_config import bind_context, get_logger
from app.tools.mongo_query_tool import execute_mongo_query

_log = get_logger("app")


def _build_messages(history_key: str) -> list[dict]:
    """拼回发给 LLM 的 messages：system + (会话摘要) + 受保护历史。"""
    msgs: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    summary = get_summary(history_key)
    if summary:
        msgs.append({"role": "system", "content": f"{SUMMARY_MARKER}\n{summary}"})
    msgs.extend(get_history(history_key))
    return msgs


def _assistant_toolcall_message(msg) -> dict:
    """把 LLM 返回的带 tool_calls 的 assistant message 转成可回传的 dict。"""
    tool_calls = []
    for tc in (msg.tool_calls or []):
        tool_calls.append({
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.function.name,
                "arguments": tc.function.arguments,
            },
        })
    return {"role": "assistant", "content": msg.content, "tool_calls": tool_calls}


def _parse_args(raw: str) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}


async def run_chat_stream(
    *, session_id: str, script_id: str, question: str, trace_id: str,
    user_id: str = "dev_user",
    history_key: str | None = None,
):
    """主流程，yield SSE 字符串。"""
    history_key = history_key or session_id
    bind_context(trace_id=trace_id, session_id=session_id, script_id=script_id)
    t0 = time.time()
    _log.info(f"stream_start question={question!r}")

    try:
        # 写 user message 到 history（含 JSONL）
        append_message(
            history_key, {"role": "user", "content": question},
            trace_id=trace_id, script_id=script_id,
        )

        # 入口压缩预检（估算口径）→ 构造 messages：system + (摘要) + history
        await compact_session_if_needed(
            history_key,
            measured_tokens=estimate_messages_tokens(_build_messages(history_key)),
            trace_id=trace_id, script_id=script_id,
        )
        messages = _build_messages(history_key)

        yield status_event("正在分析问题...")

        # 工具循环：MAX_TOOL_ROUNDS<=0 表示不限轮数（由模型自行停止调用工具来结束）；
        # >0 时到达上限强制进入终答，防止极端情况下无限循环。
        max_rounds = settings.max_tool_rounds
        round_idx = 0
        while True:
            msg = await complete_with_tools(messages, TOOLS)
            tool_calls = msg.tool_calls or []
            if not tool_calls:
                break

            assistant_msg = _assistant_toolcall_message(msg)
            messages.append(assistant_msg)
            append_message(history_key, assistant_msg,
                           trace_id=trace_id, script_id=script_id)

            for tc in tool_calls:
                args = _parse_args(tc.function.arguments)
                purpose = args.get("purpose", "")
                yield tool_start_event(
                    tool_call_id=tc.id, tool_name=tc.function.name, purpose=purpose,
                )

                result = await run_in_threadpool(
                    execute_mongo_query, script_id, args
                )

                yield tool_result_event(
                    tool_call_id=tc.id,
                    tool_name=tc.function.name,
                    purpose=purpose,
                    preview=result.preview,
                    truncated=result.truncated,
                    estimated_tokens=result.estimated_tokens,
                    truncation_reason=result.truncation_reason,
                )

                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result.full_result,
                }
                messages.append(tool_msg)
                append_message(history_key, tool_msg,
                               trace_id=trace_id, script_id=script_id)

            round_idx += 1
            _log.info(f"tool_round_done round={round_idx} max={max_rounds or 'unlimited'}")

            # 轮内压缩检查（优先用真实 prompt_tokens，回退估算）→ 压了就重建 messages
            measured = orc.LAST_PROMPT_TOKENS or estimate_messages_tokens(messages)
            if await compact_session_if_needed(
                history_key, measured_tokens=measured,
                trace_id=trace_id, script_id=script_id,
            ):
                messages = _build_messages(history_key)

            if max_rounds > 0 and round_idx >= max_rounds:
                # 到达配置的上限仍在调工具 → 强制进入终答
                _log.info(f"max_tool_rounds_reached rounds={round_idx}")
                break

        # 终答：流式 + tool_choice=none
        answer_parts: list[str] = []
        async for text in stream_final_answer(messages):
            answer_parts.append(text)
            yield delta_event(text)

        answer = "".join(answer_parts)

        # 写 assistant 终答到 history（含 JSONL）
        append_message(
            history_key, {"role": "assistant", "content": answer},
            trace_id=trace_id, script_id=script_id,
        )

        # 工具消息压缩并回写内存
        compacted = compact_tool_messages(get_history(history_key))
        replace_history(history_key, compacted)

        dur = int((time.time() - t0) * 1000)
        _log.info(f"stream_done answer_len={len(answer)} duration_ms={dur}")
        yield done_event(session_id)

    except Exception as e:  # noqa: BLE001
        _log.error(f"stream_error error={e!r}")
        yield error_event(f"服务出错：{e}")
