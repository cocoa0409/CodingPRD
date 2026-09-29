#!/bin/bash
set -e
cd "$(dirname "$0")"
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q --disable-pip-version-check flask >/dev/null 2>&1 || \
    python3 -m pip install -q --break-system-packages flask >/dev/null 2>&1
fi
export PORT="${PORT:-10000}"
exec python3 app.py
