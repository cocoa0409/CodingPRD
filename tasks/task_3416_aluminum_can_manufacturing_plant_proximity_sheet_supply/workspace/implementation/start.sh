#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependency install is guarded: per-test-server isolation re-invokes start.sh
# before every test, and an unconditional pip install causes boot-time
# contention and flaky restart timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
