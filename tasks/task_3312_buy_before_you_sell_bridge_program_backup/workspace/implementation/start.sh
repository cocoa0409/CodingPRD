#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install only when missing. start.sh is re-invoked before every per-test reboot
# (the runner restarts the server before each individual pytest test, and the
# stability sweep runs those reboots concurrently), so an unconditional
# `pip install` here would create boot-time contention and flaky
# "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py