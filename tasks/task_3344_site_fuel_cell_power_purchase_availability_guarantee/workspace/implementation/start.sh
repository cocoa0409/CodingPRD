#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install dependencies only when they are missing: the harness re-invokes
# start.sh before every per-test server reboot, and an unconditional
# pip install here would contend with the concurrent sweep rounds.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
