#!/usr/bin/env bash
# Launch the Cement Plant Kiln & Clinker Operations API in the foreground.
# Reads PORT from the environment (default 10000) and binds 0.0.0.0.
set -euo pipefail

cd "$(dirname "$0")"

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt >/dev/null 2>&1 \
        || python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1
fi

exec python3 app.py
