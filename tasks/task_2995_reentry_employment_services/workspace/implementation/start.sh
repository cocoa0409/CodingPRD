#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PORT="${PORT:-10000}"
python3 -c "import flask" >/dev/null 2>&1 || python3 -m pip install --quiet -r requirements.txt
exec python3 app.py
