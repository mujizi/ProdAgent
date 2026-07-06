"""Local History 脚本测试（plan §15 / Step 8）：空/append/顺序/JSONL/clear/隔离。

运行：python scripts/test_local_history.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 把 JSONL 写到临时目录，避免污染 logs
import app.config as config  # noqa: E402

_tmp = tempfile.mkdtemp()

import app.history.local_history_store as store  # noqa: E402

store._jsonl_path = lambda: Path(_tmp) / "events.jsonl"  # type: ignore


def main():
    store.SESSION_HISTORY.clear()
    ok = 0

    # 空
    assert store.get_history("s1") == []
    ok += 1

    # append user / assistant / tool 顺序
    store.append_message("s1", {"role": "user", "content": "q"}, script_id="sc1")
    store.append_message("s1", {"role": "assistant", "content": None,
                                "tool_calls": [{"id": "c1"}]}, script_id="sc1")
    store.append_message("s1", {"role": "tool", "tool_call_id": "c1",
                                "content": "r"}, script_id="sc1")
    store.append_message("s1", {"role": "assistant", "content": "a"}, script_id="sc1")
    roles = [m["role"] for m in store.get_history("s1")]
    assert roles == ["user", "assistant", "tool", "assistant"], roles
    ok += 1

    # JSONL 写入
    lines = (Path(_tmp) / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 4
    first = json.loads(lines[0])
    assert first["role"] == "user" and first["session_id"] == "s1"
    ok += 1

    # session 隔离
    store.append_message("s2", {"role": "user", "content": "x"})
    assert len(store.get_history("s1")) == 4
    assert len(store.get_history("s2")) == 1
    ok += 1

    # clear
    store.clear_history("s1")
    assert store.get_history("s1") == []
    assert len(store.get_history("s2")) == 1
    ok += 1

    print(f"✅ Local History 测试通过（{ok} 项）")


if __name__ == "__main__":
    main()
