"""Compactor 单元测试（token 触发版）。"""
from app.history.compactor import (
    COMPRESSED_PLACEHOLDER,
    compact_tool_messages,
    total_tool_tokens,
)


def make_history(n_tool: int, content_len: int = 8):
    """构造 user / assistant(tool_calls) / tool 交替的历史，含 n_tool 个 tool 消息。

    content_len 控制每个 tool 消息内容长度，用于控制总 token。
    """
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "q"}]
    for i in range(n_tool):
        msgs.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": f"call_{i}", "type": "function",
                            "function": {"name": "execute_mongo_query", "arguments": "{}"}}],
        })
        # 用可识别前缀 + 填充，确保内容唯一且长度可控
        body = f"tool_result_{i}" + ("内" * content_len)
        msgs.append({"role": "tool", "tool_call_id": f"call_{i}", "content": body})
    msgs.append({"role": "assistant", "content": "final"})
    return msgs


def tool_contents(msgs):
    return [m["content"] for m in msgs if m["role"] == "tool"]


def test_no_compaction_under_token_threshold():
    # 大量 tool 消息但总 token 很小 → 高阈值下不压缩
    msgs = make_history(20, content_len=2)
    out = compact_tool_messages(msgs, token_threshold=100000)
    assert all(c != COMPRESSED_PLACEHOLDER for c in tool_contents(out))


def test_compaction_triggers_over_threshold():
    # 低阈值 → 触发压缩，只保留最近 4
    msgs = make_history(6, content_len=50)
    assert total_tool_tokens(msgs) > 10
    out = compact_tool_messages(msgs, keep_latest=4, token_threshold=10)
    contents = tool_contents(out)
    compressed = [c for c in contents if c == COMPRESSED_PLACEHOLDER]
    intact = [c for c in contents if c != COMPRESSED_PLACEHOLDER]
    assert len(compressed) == 2
    assert len(intact) == 4
    assert intact[0].startswith("tool_result_2")
    assert intact[-1].startswith("tool_result_5")


def test_threshold_boundary_not_compacted():
    # 总 token 恰好等于阈值（<=）→ 不压缩
    msgs = make_history(3, content_len=10)
    total = total_tool_tokens(msgs)
    out = compact_tool_messages(msgs, keep_latest=1, token_threshold=total)
    assert all(c != COMPRESSED_PLACEHOLDER for c in tool_contents(out))


def test_tool_call_id_and_order_and_count_unchanged():
    msgs = make_history(6, content_len=50)
    out = compact_tool_messages(msgs, keep_latest=4, token_threshold=10)
    tool_msgs = [m for m in out if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == [f"call_{i}" for i in range(6)]
    assert len(out) == len(msgs)
    assert [m["role"] for m in out] == [m["role"] for m in msgs]


def test_assistant_tool_calls_not_removed():
    msgs = make_history(6, content_len=50)
    out = compact_tool_messages(msgs, keep_latest=4, token_threshold=10)
    assert sum(1 for m in out if m["role"] == "assistant" and m.get("tool_calls")) == 6


def test_input_not_mutated():
    msgs = make_history(6, content_len=50)
    compact_tool_messages(msgs, keep_latest=4, token_threshold=10)
    assert all(c != COMPRESSED_PLACEHOLDER for c in tool_contents(msgs))


def test_idempotent():
    msgs = make_history(6, content_len=50)
    out1 = compact_tool_messages(msgs, keep_latest=4, token_threshold=10)
    out2 = compact_tool_messages(out1, keep_latest=4, token_threshold=10)
    assert out1 == out2


def test_total_tool_tokens_counts_only_tool_role():
    msgs = make_history(2, content_len=10)
    # 只统计 role=tool；user/assistant/system 不计入
    assert total_tool_tokens(msgs) == sum(
        max(1, len(m["content"]) // 2) for m in msgs if m["role"] == "tool"
    )
