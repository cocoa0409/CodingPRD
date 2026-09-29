#!/usr/bin/env bash
# Boots the Nutrient Trading & Watershed Load Allocation API in the foreground.
set -e
cd "$(dirname "$0")"

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 \
    || python3 -m pip install --quiet --break-system-packages flask >/dev/null 2>&1 \
    || true
fi

export PORT="${PORT:-10000}"
exec python3 app.py
