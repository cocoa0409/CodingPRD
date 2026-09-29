#!/usr/bin/env bash
# Launch the Robocall Mitigation & Call Authentication API in the foreground.
# Binds 0.0.0.0 on $PORT (default 10000). All state is in-memory: a fresh
# process always starts empty.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 || true
fi

exec python3 app.py
