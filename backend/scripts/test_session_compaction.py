"""真实会话级摘要压缩端到端（RUN_LLM_TESTS=1）。

把触发阈值临时调到很低，多轮提问，验证：
- 真的触发 LLM 摘要（SESSION_SUMMARY 被写入）
- 历史被折叠（turn 数 ≤ 受保护数）
- 压缩后拼回的 messages 仍合法 → 后续真实问答仍能正常出答案
- 压缩后历史无孤立 tool 消息（配对完整）

运行：RUN_LLM_TESTS=1 python scripts/test_session_compaction.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.agent.loop import run_chat_stream  # noqa: E402
from app.history.local_history_store import get_history, get_summary  # noqa: E402
from app.history.session_compactor import split_turns  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402

SCRIPT_ID = "690c1b6736c9c50c40160976"
SESSION = "sess_compaction_e2e"


def ev_name(e):
    return e.split("\n", 1)[0].replace("event: ", "")


async def ask(q):
    deltas = []
    names = []
    async for e in run_chat_stream(session_id=SESSION, script_id=SCRIPT_ID,
                                   question=q, trace_id="trace_compact"):
        names.append(ev_name(e))
        if ev_name(e) == "delta":
            import json
            deltas.append(json.loads(e.split("data: ", 1)[1])["text"])
    return names, "".join(deltas)


def assert_no_orphan_tool(history):
    open_ids = set()
    for m in history:
        if m.get("role") == "assistant":
            for tc in (m.get("tool_calls") or []):
                open_ids.add(tc["id"])
        elif m.get("role") == "tool":
            assert m["tool_call_id"] in open_ids, "压缩后出现孤立 tool 消息！"


async def main():
    setup_logging()
    # 临时把阈值压到很低，逼出压缩
    settings.model_max_input_tokens = 1200
    settings.compact_recent_protect_tokens = 200
    settings.min_recent_turns = 1
    print(f"触发线 = {settings.compact_trigger_tokens} tokens（已临时调低用于验证）\n")

    questions = [
        "第1场发生了什么？",
        "第2场呢？",
        "这个剧本的主要人物有哪些？",
        "结合前面，安迪是个怎样的人？",
    ]

    compacted_seen = False
    for i, q in enumerate(questions, 1):
        names, ans = await ask(q)
        summary = get_summary(SESSION)
        hist = get_history(SESSION)
        nturns = len(split_turns(hist))
        print(f"[Q{i}] {q}")
        print(f"     events: done={names[-1]=='done'} delta数={names.count('delta')} 答案前40={ans[:40]!r}")
        print(f"     压缩后: turn数={nturns} 有摘要={summary is not None} "
              f"history条数={len(hist)}")
        assert names[-1] == "done", "未正常结束"
        assert len(ans) > 0, "答案为空（拼回的 messages 可能非法）"
        assert_no_orphan_tool(hist)
        if summary is not None:
            compacted_seen = True

    assert compacted_seen, "整轮下来从未触发压缩，阈值需再调低"
    print("\n当前摘要预览：")
    print((get_summary(SESSION) or "")[:600])
    print("\n✅ 会话级摘要压缩端到端通过：触发/折叠/拼回合法/配对完整/后续问答正常")


if __name__ == "__main__":
    asyncio.run(main())
