#!/usr/bin/env bash
# Boots the hotel franchise conversion API in the foreground.  Every invocation
# is a brand-new process with completely empty in-memory storage.
set -euo pipefail

cd "$(dirname "$0")"

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 \
    || python3 -m pip install --quiet --break-system-packages flask >/dev/null 2>&1
fi

exec python3 app.py
