#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# start.sh is re-invoked before every per-test server reboot (and the stability
# sweep runs those reboots concurrently), so the dependency install is guarded
# on a cheap import: an unconditional `pip install` here causes boot-time
# contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt >/dev/null 2>&1 || true
fi

exec python3 app.py