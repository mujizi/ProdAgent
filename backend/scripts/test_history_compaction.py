"""History 压缩脚本测试（token 触发版 / plan §11 / Step 9）：
tool message 总 token 超阈值 → 只留最近 N 完整，其余替换，tool_call_id/顺序/总数不变；
未超阈值不压缩。

运行：python scripts/test_history_compaction.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.history.compactor import (  # noqa: E402
    COMPRESSED_PLACEHOLDER,
    compact_tool_messages,
    total_tool_tokens,
)


def make(n_tool, content_len=50):
    msgs = [{"role": "user", "content": "q"}]
    for i in range(n_tool):
        msgs.append({"role": "assistant", "content": None,
                     "tool_calls": [{"id": f"call_{i}"}]})
        msgs.append({"role": "tool", "tool_call_id": f"call_{i}",
                     "content": f"result_{i}" + ("内" * content_len)})
    return msgs


def main():
    msgs = make(6, content_len=50)
    total = total_tool_tokens(msgs)
    print(f"6 个 tool message 总 token ≈ {total}")

    # 低阈值触发压缩，保留最近 4
    out = compact_tool_messages(msgs, keep_latest=4, token_threshold=10)
    tool_msgs = [m for m in out if m["role"] == "tool"]
    compressed = [m for m in tool_msgs if m["content"] == COMPRESSED_PLACEHOLDER]
    intact = [m for m in tool_msgs if m["content"] != COMPRESSED_PLACEHOLDER]

    assert len(compressed) == 2, f"应压缩2个，实际{len(compressed)}"
    assert len(intact) == 4, f"应保留4个，实际{len(intact)}"
    assert intact[0]["content"].startswith("result_2")
    assert intact[-1]["content"].startswith("result_5")
    assert [m["tool_call_id"] for m in tool_msgs] == [f"call_{i}" for i in range(6)]
    assert len(out) == len(msgs)
    assert [m["role"] for m in out] == [m["role"] for m in msgs]
    assert sum(1 for m in out if m["role"] == "assistant" and m.get("tool_calls")) == 6
    print("✓ 超阈值：保留最近4 / 旧替换 / id·顺序·总数不变")

    # 高阈值不压缩
    out2 = compact_tool_messages(msgs, keep_latest=4, token_threshold=10_000_000)
    assert all(m["content"].startswith("result_")
               for m in out2 if m["role"] == "tool")
    print("✓ 未超阈值：不压缩")

    print("✅ History 压缩测试通过（token 触发）")


if __name__ == "__main__":
    main()
