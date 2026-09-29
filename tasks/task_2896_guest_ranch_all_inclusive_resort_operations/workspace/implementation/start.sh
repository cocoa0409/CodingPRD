#!/usr/bin/env bash
# Boots a completely fresh, in-memory instance of the ranch API.
set -euo pipefail
cd "$(dirname "$0")"
export PORT="${PORT:-10000}"
python3 -c 'import flask' >/dev/null 2>&1 || pip install --quiet --disable-pip-version-check -r requirements.txt
exec python3 app.py
