#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# start.sh is re-invoked before every per-test server reboot (8 rounds
# concurrently), so the dependency install must be a no-op once Flask is
# present. An unconditional pip install here causes boot-time contention and
# shows up as flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

export PORT="${PORT:-10000}"
exec python3 app.py