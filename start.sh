#!/usr/bin/env bash
# 一键启动前后端（剧本问答 Agent）。
#   bash start.sh
# 后端单进程（不加 --reload，避免清空内存 history）；前端注入真实 script_id。
# Ctrl+C 一并关闭两边。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
# 默认测试剧本
SCRIPT_ID="${SCRIPT_ID:-6a4f56a54bc764f6d3181d83}"
USER_ID="${USER_ID:-dev_user_frontend}"

PY="$BACKEND/.venv/bin/python"

red() { printf "\033[31m%s\033[0m\n" "$1"; }
grn() { printf "\033[32m%s\033[0m\n" "$1"; }

# --- 前置检查 ---
if [ ! -x "$PY" ]; then
  red "未找到后端 venv：$PY"
  red "请先：cd backend && python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
if [ ! -f "$BACKEND/.env" ]; then
  red "未找到 backend/.env，请先 cp backend/.env.example backend/.env 并填写 key/mongo"
  exit 1
fi
if [ ! -d "$FRONTEND/node_modules" ]; then
  red "未找到 frontend/node_modules，请先：cd frontend && npm install"
  exit 1
fi

# --- 清理旧进程 ---
lsof -ti:"$BACKEND_PORT" | xargs kill -9 2>/dev/null || true
lsof -ti:"$FRONTEND_PORT" | xargs kill -9 2>/dev/null || true

BACK_PID=""
FRONT_PID=""
cleanup() {
  echo ""
  echo "正在关闭..."
  [ -n "$BACK_PID" ] && kill "$BACK_PID" 2>/dev/null || true
  [ -n "$FRONT_PID" ] && kill "$FRONT_PID" 2>/dev/null || true
  lsof -ti:"$BACKEND_PORT" | xargs kill -9 2>/dev/null || true
  lsof -ti:"$FRONTEND_PORT" | xargs kill -9 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

# --- 启动后端 ---
grn "启动后端 (单进程) → http://localhost:$BACKEND_PORT"
mkdir -p "$BACKEND/logs"
( cd "$BACKEND" && "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" \
    > "$BACKEND/logs/server.log" 2>&1 ) &
BACK_PID=$!

# 等后端健康
echo -n "等待后端就绪"
for i in $(seq 1 30); do
  if curl --noproxy '*' -sf "http://localhost:$BACKEND_PORT/health" >/dev/null 2>&1; then
    echo ""
    grn "后端就绪：$(curl --noproxy '*' -s http://localhost:$BACKEND_PORT/health)"
    break
  fi
  echo -n "."
  sleep 1
  if [ "$i" = "30" ]; then
    red ""
    red "后端启动超时，看日志：$BACKEND/logs/server.log"
    cleanup
  fi
done

# --- 启动前端 ---
grn "启动前端 → http://localhost:$FRONTEND_PORT (剧本 script_id=$SCRIPT_ID)"
( cd "$FRONTEND" && \
    NEXT_PUBLIC_API_BASE="http://localhost:$BACKEND_PORT" \
    NEXT_PUBLIC_USER_ID="$USER_ID" \
    NEXT_PUBLIC_SCRIPT_ID="$SCRIPT_ID" \
    npm run dev -- -p "$FRONTEND_PORT" > "$ROOT/frontend-dev.log" 2>&1 ) &
FRONT_PID=$!

# 等前端就绪
echo -n "等待前端就绪"
for i in $(seq 1 40); do
  if curl --noproxy '*' -sf "http://localhost:$FRONTEND_PORT" >/dev/null 2>&1; then
    echo ""
    break
  fi
  echo -n "."
  sleep 1
done

echo ""
grn "========================================"
grn " 前端:  http://localhost:$FRONTEND_PORT"
grn " 后端:  http://localhost:$BACKEND_PORT/health"
grn " 剧本:  $SCRIPT_ID"
grn " 用户:  $USER_ID"
grn " 日志:  backend/logs/{app,llm,tool,history}.log"
grn " 按 Ctrl+C 关闭前后端"
grn "========================================"

# 任一进程退出则一起清理（轮询，兼容 macOS 自带 bash 3.2，不用 wait -n）
while kill -0 "$BACK_PID" 2>/dev/null && kill -0 "$FRONT_PID" 2>/dev/null; do
  sleep 2
done
red "检测到某个服务已退出，正在清理另一个..."
cleanup
