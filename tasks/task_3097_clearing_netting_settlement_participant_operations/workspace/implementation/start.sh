#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-invoked before every per-test server reboot (and the stability
# sweep runs those reboots concurrently), so the dependency install MUST be
# guarded: an unconditional `pip install` on every boot contends on the package
# index and slows startup past the runner's restart window.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py