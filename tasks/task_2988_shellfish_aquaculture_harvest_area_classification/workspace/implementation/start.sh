#!/usr/bin/env bash
# Launch the Shellfish Harvest Classification API in the foreground.
# The evaluator runs `bash start.sh` from inside this directory before every
# test, so the process must bind $PORT and hold the terminal.
set -euo pipefail

cd "$(dirname "$0")"

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt
fi

export PORT="${PORT:-10000}"
exec python3 app.py
