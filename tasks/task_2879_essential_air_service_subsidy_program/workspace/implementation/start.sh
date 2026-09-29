#!/usr/bin/env bash
# Launch the Essential Air Service Subsidy API in the foreground.
# The harness restarts this script before every test, so state is always fresh.
set -euo pipefail

cd "$(dirname "$0")"

export PORT="${PORT:-8000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt >/dev/null 2>&1 || true
fi

exec python3 app.py
