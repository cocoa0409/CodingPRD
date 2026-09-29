#!/usr/bin/env bash
# Launcher contract: bind 0.0.0.0 on $PORT (default 10000) in the foreground.
set -e
cd "$(dirname "$0")"
export PORT="${PORT:-10000}"
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 || true
fi
exec python3 app.py
