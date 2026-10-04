#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when the framework is missing. The harness re-invokes this script
# before every per-test reboot (concurrently), so an unconditional pip install
# here would cause boot-time contention and flaky restart timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py