#!/usr/bin/env bash
# Launcher for the Neighborhood Swim Club API.
#
# The evaluator runs `bash start.sh` with PORT set in the environment, then
# kills the process; the server therefore runs in the FOREGROUND and every byte
# of state lives in the process's memory, so a re-invocation starts clean.
set -euo pipefail

cd "$(dirname "$0")"

# The evaluator supplies PORT; the fallback exists only for a bare local run.
export PORT="${PORT:-8000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt >/dev/null 2>&1 || true
fi

exec python3 app.py
