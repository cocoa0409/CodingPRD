#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — the per-test-server harness re-invokes start.sh
# before every test; an unconditional pip install here causes boot-time
# contention across concurrent reboots.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
