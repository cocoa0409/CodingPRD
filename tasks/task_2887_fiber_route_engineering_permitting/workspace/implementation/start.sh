#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install only when missing -- start.sh is re-invoked before every per-test
# reboot (and 8 stability rounds run those reboots concurrently), so an
# unconditional pip install here would cause boot-time contention and flaky
# "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt || true
fi

export PYTHONDONTWRITEBYTECODE=1
exec python3 app.py
