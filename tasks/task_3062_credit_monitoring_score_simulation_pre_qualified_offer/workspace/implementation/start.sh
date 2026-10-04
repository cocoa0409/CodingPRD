#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependency install is guarded: start.sh is re-invoked before every per-test
# server reboot (and across concurrent sweep rounds), so an unconditional
# pip install here would cause boot-time contention and flaky restarts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py