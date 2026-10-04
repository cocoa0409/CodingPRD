#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# The harness re-invokes start.sh before every pytest test
# (`--isolation per-test-server`), and the stability sweep reboots the server
# concurrently in several rounds. An unconditional `pip install` on every boot
# causes install contention and flaky "could not be restarted" timeouts, so the
# install is guarded on a cheap import of the framework.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

# Hand off to the server; exec so signals (SIGTERM from the harness) propagate
# and the process stays in the foreground.
exec python3 app.py