#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# start.sh is re-invoked before every per-test server reboot, and the stability
# sweep reboots many servers concurrently. Guard the dependency install so it is
# a no-op once Flask is importable; an unconditional pip install here causes
# boot-time contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py