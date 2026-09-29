#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing -- start.sh is re-invoked before every per-test
# reboot (and 8 stability rounds run those reboots concurrently), so an
# unconditional pip install would cause boot contention and flaky restarts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt >/dev/null 2>&1 || \
    python3 -m pip install -q --break-system-packages -r requirements.txt >/dev/null 2>&1 || true
fi
exec python3 app.py
