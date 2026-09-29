#!/usr/bin/env bash
# Launcher for the harness: fresh process, foreground, PORT-aware.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py
