"""真实 /api/chat/stream HTTP SSE 测试（plan §15 / Step 1+10）。

需后端已启动（uvicorn app.main:app --port 8000）。
验证：收到 status / tool_result(仅 preview，不含 full_result) / delta / done，且 SSE 头正确。

运行：RUN_STREAM_TESTS=1 python scripts/test_stream_api.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

BASE = "http://localhost:8000"
SCRIPT_ID = "690c1b6736c9c50c40160976"


def main():
    # 健康检查
    h = httpx.get(f"{BASE}/health", timeout=10)
    print("health:", h.status_code, h.json())
    assert h.status_code == 200

    payload = {
        "user_id": "dev_user_stream_test",
        "session_id": "sess_stream_api_test",
        "script_id": SCRIPT_ID,
        "question": "第1场发生了什么？",
    }

    events = []
    deltas = []
    with httpx.stream("POST", f"{BASE}/api/chat/stream", json=payload,
                      timeout=60) as resp:
        print("status:", resp.status_code)
        print("content-type:", resp.headers.get("content-type"))
        print("cache-control:", resp.headers.get("cache-control"))
        print("x-accel-buffering:", resp.headers.get("x-accel-buffering"))
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        assert resp.headers.get("cache-control") == "no-cache"
        assert resp.headers.get("x-accel-buffering") == "no"

        cur_event = None
        for line in resp.iter_lines():
            if line.startswith("event: "):
                cur_event = line[len("event: "):]
                events.append(cur_event)
            elif line.startswith("data: ") and cur_event == "delta":
                deltas.append(json.loads(line[len("data: "):])["text"])
            elif line.startswith("data: ") and cur_event == "tool_result":
                data = json.loads(line[len("data: "):])
                assert "preview" in data and "full_result" not in data
                print(f"  tool_result: truncated={data['truncated']} "
                      f"est_tokens={data['estimated_tokens']}")

    print("\nevents:", events)
    answer = "".join(deltas)
    print("answer:", answer[:200])

    assert "status" in events
    assert "tool_result" in events
    assert "delta" in events
    assert events[-1] == "done"
    assert len(answer) > 0
    print("\n✅ /api/chat/stream HTTP SSE 测试通过（头/事件/流式终答均正常）")


if __name__ == "__main__":
    main()
