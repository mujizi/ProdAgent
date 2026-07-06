"""Tool Message 压缩（plan §11，token 触发版）。

规则：
- 统计所有 role=tool 消息 content 的总 token（len // CHARS_PER_TOKEN）
- 总 token <= TOOL_COMPACT_TOKEN_THRESHOLD → 不压缩，全部保留完整
- 总 token > 阈值 → 只保留最近 KEEP_LATEST_TOOL_MESSAGES 个完整，
  更早的 role=tool 消息 content 替换为压缩占位符
- assistant tool_calls 不删除；tool_call_id 不修改
- 消息顺序不变；消息总数不减少

纯逻辑，可离线测。
"""
from __future__ import annotations

import copy

from app.config import settings
from app.tools.budget import estimate_tokens

COMPRESSED_PLACEHOLDER = (
    "[TOOL_RESULT_COMPRESSED]\n"
    "早期 Mongo 查询结果已从当前上下文中压缩，不能作为精确事实依据。\n"
    "如后续问题需要准确细节，请重新调用 execute_mongo_query 查询。"
)


def total_tool_tokens(messages: list[dict]) -> int:
    """所有 role=tool 消息 content 的总 token 粗估。"""
    total = 0
    for m in messages:
        if m.get("role") == "tool":
            content = m.get("content")
            if isinstance(content, str):
                total += estimate_tokens(content)
    return total


def compact_tool_messages(
    messages: list[dict],
    keep_latest: int | None = None,
    token_threshold: int | None = None,
) -> list[dict]:
    """返回压缩后的新消息列表（不修改入参）。

    仅当所有 tool message 的总 token 超过 token_threshold 时才触发压缩，
    触发后只保留最近 keep_latest 个 tool message 完整，其余替换为占位符。
    """
    if keep_latest is None:
        keep_latest = settings.keep_latest_tool_messages
    if token_threshold is None:
        token_threshold = settings.tool_compact_token_threshold

    # 未超过 token 阈值 → 不压缩
    if total_tool_tokens(messages) <= token_threshold:
        return copy.deepcopy(messages)

    # 找出所有 role=tool 的下标
    tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]

    # 需要压缩的：除最近 keep_latest 个之外的旧 tool 消息
    to_compress = set(tool_indices[:-keep_latest]) if keep_latest > 0 else set(tool_indices)

    result = copy.deepcopy(messages)
    for i in to_compress:
        # 已经是压缩占位符则跳过（幂等）
        if result[i].get("content") == COMPRESSED_PLACEHOLDER:
            continue
        result[i]["content"] = COMPRESSED_PLACEHOLDER
        # tool_call_id 等其它字段保持不变
    return result
