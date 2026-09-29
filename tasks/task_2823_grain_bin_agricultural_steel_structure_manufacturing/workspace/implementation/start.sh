#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing -- start.sh is re-invoked before every per-test
# server reboot, and unconditional pip installs cause boot-time contention.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
export PORT="${PORT:-10000}"
exec python3 app.py
