#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# start.sh is re-invoked before every per-test server reboot (and those reboots
# run concurrently during the stability sweep). An unconditional pip install
# here creates boot-time contention, so install only when the framework is
# missing.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py