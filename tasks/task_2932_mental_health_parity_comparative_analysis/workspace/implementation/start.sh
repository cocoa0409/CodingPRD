#!/usr/bin/env bash
# Launch the Mental Health Parity Comparative Analysis API in the foreground.
set -e

cd "$(dirname "$0")"

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet flask >/dev/null 2>&1 \
    || python3 -m pip install --quiet --break-system-packages flask >/dev/null 2>&1
fi

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

exec python3 app.py
