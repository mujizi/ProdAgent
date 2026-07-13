"""真实 Agent Loop 端到端（plan §15 / Step 7）。

真 LLM(qwen3.7-max) + 真 Mongo，验证：触发 tool call → 执行 → tool result 入 messages →
终答流式非空。

运行：RUN_LLM_TESTS=1 python scripts/test_agent_tool_loop.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.loop import run_chat_stream  # noqa: E402
from app.history.local_history_store import get_history  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402

SCRIPT_ID = "6a4f56a54bc764f6d3181d83"
SESSION = "sess_agent_loop_test"


def ev_name(e: str) -> str:
    return e.split("\n", 1)[0].replace("event: ", "")


async def ask(question: str):
    print(f"\n>>> 提问: {question}")
    events = []
    delta_text = []
    async for e in run_chat_stream(
        session_id=SESSION, script_id=SCRIPT_ID, question=question,
        trace_id="trace_loop_test",
    ):
        events.append(e)
        name = ev_name(e)
        if name == "tool_start":
            print("   [tool_start]", e.split("data: ", 1)[1].strip()[:120])
        elif name == "tool_result":
            import json
            data = json.loads(e.split("data: ", 1)[1])
            print(f"   [tool_result] truncated={data['truncated']} "
                  f"est_tokens={data['estimated_tokens']} preview={data['preview'][:80]!r}")
        elif name == "delta":
            import json
            delta_text.append(json.loads(e.split("data: ", 1)[1])["text"])
        elif name in ("status", "done", "error"):
            print(f"   [{name}]", e.split("data: ", 1)[1].strip())
    answer = "".join(delta_text)
    print(f"   终答({len(answer)}字): {answer[:200]}")
    names = [ev_name(e) for e in events]
    return names, answer


async def main():
    setup_logging()
    names, answer = await ask("第1场发生了什么？")

    assert "tool_start" in names, "未触发 tool call"
    assert "tool_result" in names, "无 tool result"
    assert names.count("delta") > 0, "终答无流式 delta"
    assert names[-1] == "done", f"最后事件不是 done: {names[-1]}"
    assert len(answer) > 0, "终答为空"

    # tool message 入 history
    hist = get_history(SESSION)
    roles = [m["role"] for m in hist]
    assert "tool" in roles, "tool message 未入 history"
    assert roles[-1] == "assistant", "最后一条不是 assistant 终答"

    # 第二轮：指代消解（结合历史）
    names2, answer2 = await ask("那这一场里有哪些主要人物？")
    assert names2[-1] == "done"
    assert len(answer2) > 0

    print("\n✅ 真实 Agent Loop 端到端通过：tool 调用/执行/终答流式/历史写入全部正常。")


if __name__ == "__main__":
    asyncio.run(main())
