#!/usr/bin/env bash
# Foreground launcher.  The harness re-invokes this for every test, so it must
# start a brand-new process holding no state from the previous run.
set -e

cd "$(dirname "$0")"

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 || true
fi

export PORT="${PORT:-10000}"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1

exec python3 app.py
