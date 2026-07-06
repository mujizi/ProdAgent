"""Session identity helpers.

业务上一个会话由 user_id + script_id + session_id 唯一确定。内部存储统一使用
session_key，避免不同用户或不同剧本复用 session_id 时串上下文。
"""
from __future__ import annotations

from dataclasses import dataclass
import re

_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


@dataclass(frozen=True)
class SessionRef:
    user_id: str
    script_id: str
    session_id: str

    @property
    def session_key(self) -> str:
        return make_session_key(self.user_id, self.script_id, self.session_id)


def validate_id(name: str, value: str) -> str:
    if not value or not _ID_RE.match(value):
        raise ValueError(f"{name} 只能包含字母、数字、下划线、点、短横线，长度 1-128")
    return value


def make_session_key(user_id: str, script_id: str, session_id: str) -> str:
    user_id = validate_id("user_id", user_id)
    script_id = validate_id("script_id", script_id)
    session_id = validate_id("session_id", session_id)
    return f"{user_id}:{script_id}:{session_id}"


def session_ref_from_parts(user_id: str, script_id: str, session_id: str) -> SessionRef:
    return SessionRef(
        user_id=validate_id("user_id", user_id),
        script_id=validate_id("script_id", script_id),
        session_id=validate_id("session_id", session_id),
    )


def split_session_key(session_key: str) -> SessionRef:
    parts = session_key.split(":")
    if len(parts) < 3:
        return SessionRef(user_id="unknown", script_id="-", session_id=session_key)
    user_id = parts[0]
    script_id = parts[1]
    session_id = ":".join(parts[2:])
    return SessionRef(user_id=user_id, script_id=script_id, session_id=session_id)
