#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# The evaluator re-runs this script before every pytest test under
# --isolation per-test-server, so the dependency install is guarded: an
# unconditional pip install on every boot causes contention and flaky
# "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py
