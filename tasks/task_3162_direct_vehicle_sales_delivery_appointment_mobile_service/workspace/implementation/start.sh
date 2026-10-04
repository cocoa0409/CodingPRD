#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Guard the install: prd-bench-local-run --isolation per-test-server re-invokes
# this script before every pytest test, so an unconditional pip install would
# add boot-time contention and cause flaky "could not be restarted" failures.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
