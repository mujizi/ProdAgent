#!/usr/bin/env bash
# Build and run the all-in-one ProdAgent image.
# Usage:
#   bash scripts/docker-run.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE_NAME="${IMAGE_NAME:-prodagent:latest}"
CONTAINER_NAME="${CONTAINER_NAME:-prodagent}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
SCRIPT_ID="${SCRIPT_ID:-6a4f56a54bc764f6d3181d83}"
USER_ID="${USER_ID:-dev_user_frontend}"
API_BASE="${NEXT_PUBLIC_API_BASE:-http://localhost:${BACKEND_PORT}}"
ENV_FILE="${ENV_FILE:-$ROOT/backend/.env}"
NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmmirror.com}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

if [ ! -f "$ENV_FILE" ]; then
  echo "未找到 env 文件：$ENV_FILE"
  echo "请先 cp backend/.env.example backend/.env 并填写真实配置。"
  exit 1
fi

docker build \
  --build-arg NPM_REGISTRY="$NPM_REGISTRY" \
  --build-arg PIP_INDEX_URL="$PIP_INDEX_URL" \
  --build-arg NEXT_PUBLIC_API_BASE="$API_BASE" \
  --build-arg NEXT_PUBLIC_SCRIPT_ID="$SCRIPT_ID" \
  --build-arg NEXT_PUBLIC_USER_ID="$USER_ID" \
  -t "$IMAGE_NAME" "$ROOT"

docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

docker run --name "$CONTAINER_NAME" \
  --env-file "$ENV_FILE" \
  -e BACKEND_PORT=8000 \
  -e FRONTEND_PORT=3000 \
  -p "$BACKEND_PORT:8000" \
  -p "$FRONTEND_PORT:3000" \
  "$IMAGE_NAME"
