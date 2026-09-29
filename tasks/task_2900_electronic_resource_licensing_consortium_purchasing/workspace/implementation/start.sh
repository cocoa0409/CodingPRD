#!/usr/bin/env bash
# Boot the Electronic Resource Licensing & Consortium Purchasing API.
# The process runs in the foreground and rebuilds its whole (empty) world on
# every launch, so the harness may kill and relaunch it before every test.
set -e

cd "$(dirname "$0")"

if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 \
        || python3 -m pip install --quiet --break-system-packages flask >/dev/null 2>&1 \
        || true
fi

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

exec python3 app.py
