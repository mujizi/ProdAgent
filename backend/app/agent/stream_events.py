"""SSE 事件构造（plan §6.1）。

每个 helper 返回符合 SSE 协议的字符串：
    event: <name>\\n
    data: <json>\\n\\n
"""
from app.utils.json_utils import dumps


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {dumps(data)}\n\n"


def status_event(message: str) -> str:
    return _sse("status", {"message": message})


def tool_start_event(*, tool_call_id: str, tool_name: str, purpose: str) -> str:
    return _sse("tool_start", {
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "purpose": purpose,
    })


def tool_result_event(
    *,
    tool_call_id: str,
    tool_name: str,
    purpose: str,
    preview: str,
    truncated: bool,
    estimated_tokens: int,
    truncation_reason: str | None,
) -> str:
    return _sse("tool_result", {
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "purpose": purpose,
        "preview": preview,
        "truncated": truncated,
        "estimated_tokens": estimated_tokens,
        "truncation_reason": truncation_reason,
        "expandable": False,
    })


def delta_event(text: str) -> str:
    return _sse("delta", {"text": text})


def done_event(session_id: str) -> str:
    return _sse("done", {"session_id": session_id})


def error_event(message: str) -> str:
    return _sse("error", {"message": message})
