#!/usr/bin/env bash
# Launch the craft-brewery API. Fresh in-memory state on every invocation.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

PYTHON="${PYTHON:-python3}"

if ! "$PYTHON" -c "import flask" >/dev/null 2>&1; then
  "$PYTHON" -m pip install --quiet --disable-pip-version-check -r requirements.txt >/dev/null 2>&1 || true
fi

exec "$PYTHON" app.py
