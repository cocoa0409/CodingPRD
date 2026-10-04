#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when the framework is missing: the harness re-invokes start.sh
# before every per-test reboot, so an unconditional pip install here would cause
# boot-time contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt >/dev/null 2>&1 || true
fi
exec python3 app.py