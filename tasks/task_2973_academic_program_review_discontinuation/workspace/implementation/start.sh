#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt || python3 -m pip install -q --break-system-packages -r requirements.txt
fi
exec python3 app.py
