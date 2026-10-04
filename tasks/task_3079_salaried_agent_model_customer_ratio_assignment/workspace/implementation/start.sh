#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install only when missing — start.sh is re-run before every per-test server
# reboot, so an unconditional pip install here would cause boot-time
# contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

# PORT defaults to 10000; the server binds 0.0.0.0 and runs in the foreground.
exec python3 app.py