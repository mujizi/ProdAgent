#!/usr/bin/env bash
set -euo pipefail

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

mkdir -p /app/backend/logs

cd /app/backend
python -m uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" &
BACK_PID=$!

cd /app/frontend
./node_modules/.bin/next start -p "$FRONTEND_PORT" &
FRONT_PID=$!

cleanup() {
  kill "$BACK_PID" "$FRONT_PID" 2>/dev/null || true
}
trap cleanup INT TERM

wait -n "$BACK_PID" "$FRONT_PID"
cleanup
