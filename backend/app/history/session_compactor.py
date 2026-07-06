"""会话级 LLM 摘要压缩（第二层，OpenCode 风格）。

触发：估算/真实 input tokens ≥ MODEL_MAX_INPUT_TOKENS × COMPACT_TRIGGER_PCT(0.85)。
切分：按 user 消息边界切成 turn，保证不破坏 tool_call/tool_result 配对。
保留：最近若干完整 turn（≥ MIN_RECENT_TURNS 且累计 token ≥ COMPACT_RECENT_PROTECT_TOKENS）。
压缩：把更早的 turn（连同已有摘要）交给 LLM 生成结构化 <summary>，递归更新。
拼回：build = [system] + [summary system 消息] + 受保护 turn。

纯逻辑部分（split/select/estimate/render/extract）可离线测；summarize 走 LLM。
"""
from __future__ import annotations

import re

from app.agent.openrouter_client import complete_text
from app.agent.prompts import SUMMARY_SYSTEM_PROMPT
from app.config import settings
from app.history.compactor import compact_tool_messages
from app.history.local_history_store import (
    get_history,
    get_summary,
    replace_history,
    set_summary,
)
from app.logging_config import get_logger
from app.tools.budget import estimate_tokens
from app.utils.json_utils import dumps

_log = get_logger("history")


def estimate_message_tokens(msg: dict) -> int:
    """单条消息 token 粗估：content + tool_calls 参数 + 小幅结构开销。"""
    total = 4  # 每条消息固定开销
    content = msg.get("content")
    if isinstance(content, str):
        total += estimate_tokens(content)
    for tc in (msg.get("tool_calls") or []):
        fn = tc.get("function", {})
        total += estimate_tokens(str(fn.get("name", "")) + str(fn.get("arguments", "")))
    return total


def estimate_messages_tokens(messages: list[dict]) -> int:
    return sum(estimate_message_tokens(m) for m in messages)


def split_turns(history: list[dict]) -> list[list[dict]]:
    """按 user 消息边界把历史切成 turn（每个 turn 自包含 tool_call/result）。"""
    turns: list[list[dict]] = []
    cur: list[dict] = []
    for m in history:
        if m.get("role") == "user" and cur:
            turns.append(cur)
            cur = [m]
        else:
            cur.append(m)
    if cur:
        turns.append(cur)
    return turns


def turn_tokens(turn: list[dict]) -> int:
    return estimate_messages_tokens(turn)


def select_eviction(
    history: list[dict],
    protect_tokens: int | None = None,
    min_recent_turns: int | None = None,
) -> tuple[list[dict], list[dict]]:
    """返回 (evicted_msgs, protected_msgs)。只在 turn 边界切，配对不破坏。

    从最新 turn 往回保留，直到 turn 数 ≥ min_recent_turns 且累计 token ≥ protect_tokens；
    更早的 turn 全部淘汰。无可淘汰则 evicted 为空。
    """
    if protect_tokens is None:
        protect_tokens = settings.compact_recent_protect_tokens
    if min_recent_turns is None:
        min_recent_turns = settings.min_recent_turns

    turns = split_turns(history)
    if len(turns) <= min_recent_turns:
        return [], history

    acc = 0
    n = 0
    cut = len(turns)  # 第一个受保护 turn 的下标
    for t in reversed(turns):
        acc += turn_tokens(t)
        n += 1
        cut -= 1
        if n >= min_recent_turns and acc >= protect_tokens:
            break

    if cut <= 0:
        return [], history

    evicted = [m for t in turns[:cut] for m in t]
    protected = [m for t in turns[cut:] for m in t]
    return evicted, protected


def render_messages(msgs: list[dict]) -> str:
    """把消息渲染成可读文字，交给摘要器。"""
    lines: list[str] = []
    for m in msgs:
        role = m.get("role")
        if role == "user":
            lines.append(f"用户: {m.get('content', '')}")
        elif role == "assistant":
            if m.get("content"):
                lines.append(f"助手: {m['content']}")
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function", {})
                lines.append(f"助手调用工具: {fn.get('name', '')} {fn.get('arguments', '')}")
        elif role == "tool":
            lines.append(f"工具结果: {m.get('content', '')}")
    return "\n".join(lines)


def extract_summary(text: str) -> str:
    """从 LLM 输出里取 <summary>…</summary>；取不到则原样返回（去首尾空白）。"""
    m = re.search(r"<summary>(.*?)</summary>", text, re.DOTALL)
    body = m.group(1).strip() if m else text.strip()
    return f"<summary>\n{body}\n</summary>"


async def summarize(prev_summary: str | None, evicted_msgs: list[dict]) -> str:
    """调用 LLM 生成结构化摘要。"""
    transcript = render_messages(evicted_msgs)
    user_content = ""
    if prev_summary:
        user_content += f"已有摘要：\n{prev_summary}\n\n"
    user_content += f"需要压缩的早期对话：\n{transcript}"
    messages = [
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    text = await complete_text(messages, model=settings.summary_model or None)
    return extract_summary(text)


async def compact_session_if_needed(
    session_id: str, *, measured_tokens: int, trace_id: str = "-", script_id: str = "-"
) -> bool:
    """达阈值则压缩一次。返回是否真的压缩了。"""
    threshold = settings.compact_trigger_tokens
    if measured_tokens < threshold:
        return False

    history = get_history(session_id)
    evicted, protected = select_eviction(history)
    if not evicted:
        _log.info(f"compaction_skip reason=no_evictable "
                  f"measured={measured_tokens} threshold={threshold} "
                  f"history_msgs={len(history)}")
        return False

    _log.info(f"compaction_trigger measured={measured_tokens} threshold={threshold} "
              f"evict_msgs={len(evicted)} protect_msgs={len(protected)}")

    prev = get_summary(session_id)
    try:
        new_summary = await summarize(prev, evicted)
    except Exception as e:  # noqa: BLE001
        # 降级：不丢数据，对整段历史强制 tool 剪枝以收敛 token
        _log.error(f"compaction_error error={e!r} degrade=tool_pruning")
        replace_history(session_id, compact_tool_messages(history, token_threshold=0))
        return False

    set_summary(session_id, new_summary)
    replace_history(session_id, protected)
    _log.info(f"compaction_done evicted_msgs={len(evicted)} "
              f"protected_msgs={len(protected)} summary_tokens={estimate_tokens(new_summary)}")
    return True


def _summary_dump(session_id: str) -> str:
    """调试用：导出当前摘要。"""
    return dumps({"session_id": session_id, "summary": get_summary(session_id)})
