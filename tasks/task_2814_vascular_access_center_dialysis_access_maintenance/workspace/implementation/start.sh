#!/bin/bash
set -e

cd "$(dirname "$0")"

export PORT="${PORT:-10000}"

# Dependencies: install only when Flask is not already importable.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt || \
    python3 -m pip install -q --break-system-packages -r requirements.txt
fi

exec python3 app.py
