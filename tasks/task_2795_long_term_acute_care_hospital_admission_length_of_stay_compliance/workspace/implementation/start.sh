#!/usr/bin/env bash
# Launch the LTCH compliance API in the foreground on $PORT (default 10000).
set -euo pipefail

cd "$(dirname "$0")"

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 \
    || python3 -m pip install --quiet --disable-pip-version-check --break-system-packages flask >/dev/null 2>&1
fi

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

exec python3 app.py
