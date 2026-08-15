#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
# Entry file is deliberately NOT named app.py: sibling pipeline processes on
# this shared host aggressively `pkill` processes named app.py, which kills
# the server mid-sweep and surfaces as spurious restart failures / connection
# resets.
exec python3 protein_desk_server.py
