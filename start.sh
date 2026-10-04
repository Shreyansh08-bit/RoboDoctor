#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo 'Install Python 3.10+ first.'; exit 1; }
command -v node >/dev/null || { echo 'Install Node.js 20.19+ first.'; exit 1; }
[[ -x .venv/bin/python ]] || { echo 'Run the one-time Python setup in README.md first.'; exit 1; }
[[ -f frontend/node_modules/vite/bin/vite.js ]] || { echo 'Run npm ci in frontend once; see README.md.'; exit 1; }
web_only=false
terminal_dir="$PWD"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --web-only) web_only=true; shift ;;
    --cwd) terminal_dir="$(cd "$2" && pwd)"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done
if ! $web_only; then
  .venv/bin/python -c 'import tkinter' || { echo 'Install python3-tk explicitly or use --web-only.'; exit 1; }
fi
backend_pid=''
frontend_pid=''
desktop_pid=''
cleanup() {
  [[ -z "$backend_pid" ]] || kill "$backend_pid" 2>/dev/null || true
  [[ -z "$frontend_pid" ]] || kill "$frontend_pid" 2>/dev/null || true
  [[ -z "$desktop_pid" ]] || kill "$desktop_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM
(cd backend && exec ../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
backend_pid=$!
(cd frontend && exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --strictPort) &
frontend_pid=$!
if ! $web_only; then
  .venv/bin/python -m companion.desktop --cwd "$terminal_dir" &
  desktop_pid=$!
fi
echo 'RoboDoctor: http://127.0.0.1:5173 · Ctrl+C to stop'
while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do sleep 1; done
echo 'A server stopped; shutting down RoboDoctor.'
exit 1
