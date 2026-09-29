#!/usr/bin/env bash
# Launch the Hotel Channel Distribution API in the foreground on $PORT.
# Every invocation is a brand new process with an empty in-memory store.
set -euo pipefail

cd "$(dirname "$0")"

export PORT="${PORT:-10000}"
export PYTHONDONTWRITEBYTECODE=1

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1
fi

exec python3 app.py
