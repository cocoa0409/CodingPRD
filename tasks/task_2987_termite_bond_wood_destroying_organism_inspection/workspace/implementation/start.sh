#!/usr/bin/env bash
# Boots the API in the foreground on $PORT (default 10000), bound to 0.0.0.0.
# Every boot starts from a completely empty in-memory store.
set -euo pipefail

cd "$(dirname "$0")"

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt \
    >/dev/null 2>&1 || true
fi

exec python3 app.py
