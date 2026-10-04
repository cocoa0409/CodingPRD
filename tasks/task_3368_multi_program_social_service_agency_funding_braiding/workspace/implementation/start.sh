#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Guard the dependency install: the harness re-runs start.sh before every
# per-test server reboot (concurrently), so an unconditional pip install here
# would create boot-time contention and flaky restart timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
