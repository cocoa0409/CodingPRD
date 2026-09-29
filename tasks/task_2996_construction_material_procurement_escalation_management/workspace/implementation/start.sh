#!/usr/bin/env bash
# Foreground launcher. State is in-memory only, so every invocation starts clean.
set -euo pipefail

cd "$(dirname "$0")"

export PORT="${PORT:-8080}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 || true
fi

exec python3 app.py
