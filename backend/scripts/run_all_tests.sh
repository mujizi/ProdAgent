#!/usr/bin/env bash
# 回归测试三档（plan §15/§16）：
#   bash scripts/run_all_tests.sh                                  # 离线
#   RUN_LLM_TESTS=1 bash scripts/run_all_tests.sh                  # + LLM
#   RUN_LLM_TESTS=1 RUN_STREAM_TESTS=1 bash scripts/run_all_tests.sh  # + HTTP 流式
set -e
cd "$(dirname "$0")/.."

PY="${PYTHON:-.venv/bin/python}"

echo "==> pytest（离线纯逻辑）";        "$PY" -m pytest tests -q
echo "==> Mongo 连接";               "$PY" scripts/test_mongo_connection.py
echo "==> Mongo Tool（真实查询）";    "$PY" scripts/test_mongo_tool.py
echo "==> Local History";            "$PY" scripts/test_local_history.py
echo "==> History 压缩";             "$PY" scripts/test_history_compaction.py

if [ "$RUN_LLM_TESTS" = "1" ]; then
  echo "==> DashScope Qwen 冒烟";   "$PY" scripts/test_openrouter_basic.py
  echo "==> Agent Tool Loop（真实）"; "$PY" scripts/test_agent_tool_loop.py
fi
if [ "$RUN_STREAM_TESTS" = "1" ]; then
  echo "==> Stream API（需后端已启动）"; "$PY" scripts/test_stream_api.py
fi
echo "All tests passed."
