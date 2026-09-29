#!/usr/bin/env bash
# Boot the vineyard custom-farming API on $PORT (default 10000).
# Every invocation starts a brand-new process with empty in-memory state.
set -euo pipefail

cd "$(dirname "$0")"

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt
fi

exec python3 app.py
