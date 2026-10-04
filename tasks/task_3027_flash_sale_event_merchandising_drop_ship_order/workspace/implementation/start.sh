#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install only when missing.  start.sh is re-invoked before every per-test
# server reboot and the stability sweep runs those reboots concurrently, so an
# unconditional pip install here would contend on every boot and show up as
# flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

# Storage is in-memory only: the server process starts with an empty store on
# every invocation, so each reboot is a genuinely fresh boot.
export PYTHONUNBUFFERED=1
exec python3 app.py
