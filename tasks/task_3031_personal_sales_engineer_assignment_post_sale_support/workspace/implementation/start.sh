#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Guarded install: the harness re-runs this script before every per-test reboot
# (8 rounds concurrently), so an unconditional `pip install` here would contend
# on the network/index and slow boots past the restart window.
if ! python3 -c "import flask, waitress" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py
