#!/usr/bin/env bash
# Start the dashboard API and the React app together. Ctrl+C stops both.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cleanup() { trap - INT TERM EXIT; [[ -n "${API_PID:-}" ]] && kill "$API_PID" 2>/dev/null || true; [[ -n "${WEB_PID:-}" ]] && kill "$WEB_PID" 2>/dev/null || true; }
trap cleanup INT TERM EXIT

cd "$ROOT/backend/Orchestrator"
.venv/bin/python -m scripts.serve_ui --events "${MT02_EVENTS:-700}" &
API_PID=$!

cd "$ROOT/frontend"
[[ -d node_modules ]] || npm install
npm run dev -- --host 127.0.0.1 --port 5173 &
WEB_PID=$!

echo "API: http://127.0.0.1:8001/api/overview   UI: http://127.0.0.1:5173   (press play in the UI)"
wait
