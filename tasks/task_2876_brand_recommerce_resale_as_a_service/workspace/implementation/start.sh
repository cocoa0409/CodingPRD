#!/usr/bin/env bash
# Launch the Brand Re-Commerce API.  All state is in memory, so every
# invocation of this script starts from a completely empty programme.
set -e

cd "$(dirname "$0")"

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt >/dev/null 2>&1 \
    || python3 -m pip install --quiet --break-system-packages --disable-pip-version-check -r requirements.txt >/dev/null 2>&1
fi

exec python3 app.py
