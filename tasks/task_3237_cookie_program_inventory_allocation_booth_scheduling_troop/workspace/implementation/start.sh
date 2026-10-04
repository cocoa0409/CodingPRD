#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Guarded install: start.sh is re-run before every per-test reboot; only
# install when flask is missing.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
