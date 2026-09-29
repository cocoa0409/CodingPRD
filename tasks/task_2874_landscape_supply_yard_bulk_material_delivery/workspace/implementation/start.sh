#!/usr/bin/env bash
# Boots the Landscape Supply Yard API in the foreground on $PORT.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

export PORT="${PORT:-8000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 || true
fi

exec python3 app.py
