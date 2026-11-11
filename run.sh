#!/usr/bin/env bash
# 一键启动：后端 FastAPI(8000) + 前端 Vite(5173)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$ROOT/.venv" ]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -r "$ROOT/backend/requirements.txt"
fi

# 首次运行自动播种 SQLite（backend/data/replay.db）
setsid "$ROOT/.venv/bin/python" -m uvicorn app.main:app \
  --host 127.0.0.1 --port 8000 --app-dir "$ROOT/backend" \
  > /tmp/replay-backend.log 2>&1 < /dev/null &
echo "后端已启动: http://127.0.0.1:8000  (日志 /tmp/replay-backend.log)"

if [ ! -d "$ROOT/frontend/node_modules" ]; then
  (cd "$ROOT/frontend" && npm install --cache "$ROOT/frontend/.npm-cache")
fi
setsid npm --prefix "$ROOT/frontend" run dev \
  > /tmp/replay-frontend.log 2>&1 < /dev/null &
echo "前端已启动: http://localhost:5173  (日志 /tmp/replay-frontend.log)"
echo "打开 http://localhost:5173 ，首次进入点右上角「重新运行回放」。"
