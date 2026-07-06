"""ID 生成工具。"""
import uuid


def new_trace_id() -> str:
    return "trace_" + uuid.uuid4().hex[:16]


def new_session_id() -> str:
    return "sess_" + uuid.uuid4().hex[:16]


def new_message_id() -> str:
    return "msg_" + uuid.uuid4().hex[:12]
