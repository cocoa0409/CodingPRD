#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# The test harness re-invokes start.sh before every single pytest test
# (`prd-bench-local-run --isolation per-test-server`), and the stability sweep
# runs those reboots concurrently.  An unconditional `pip install` here would
# mean hundreds of contended installs, which slows boot past the runner's
# restart window and shows up as flaky "could not be restarted" failures.
# Guard on a cheap import so the install is a no-op once deps are present.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py