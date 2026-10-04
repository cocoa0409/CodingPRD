#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# `start.sh` is re-invoked before every per-test reboot (concurrently).  An
# unconditional pip install on every boot causes contention and flaky
# "could not be restarted" failures, so guard it on a cheap import probe.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py