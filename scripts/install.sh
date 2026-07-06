#!/usr/bin/env bash
# One-shot local dependency installer.
# Usage:
#   bash scripts/install.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

PYTHON_BIN="${PYTHON_BIN:-python3.12}"

green() { printf "\033[32m%s\033[0m\n" "$1"; }
red() { printf "\033[31m%s\033[0m\n" "$1"; }

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  red "未找到 $PYTHON_BIN。请先安装 Python 3.12，或指定 PYTHON_BIN=/path/to/python bash scripts/install.sh"
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  red "未找到 npm。请先安装 Node.js 20+。"
  exit 1
fi

green "==> 安装后端 Python 依赖"
if [ ! -d "$BACKEND/.venv" ]; then
  "$PYTHON_BIN" -m venv "$BACKEND/.venv"
fi
"$BACKEND/.venv/bin/python" -m pip install --upgrade pip
"$BACKEND/.venv/bin/pip" install -r "$BACKEND/requirements.txt"

if [ ! -f "$BACKEND/.env" ]; then
  cp "$BACKEND/.env.example" "$BACKEND/.env"
  green "已创建 backend/.env，请填入真实 DASHSCOPE / Azure fallback / Mongo / Redis 配置。"
fi

green "==> 安装前端 Node 依赖"
(cd "$FRONTEND" && npm install)

green "安装完成。填好 backend/.env 后运行：bash start.sh"
