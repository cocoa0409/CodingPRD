#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Only install when the framework is missing: the harness re-invokes this
# script before every per-test reboot and an unconditional pip install here
# would contend at boot time and cause flaky restart timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py