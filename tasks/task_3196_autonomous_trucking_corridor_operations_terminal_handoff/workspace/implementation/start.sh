#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install only when missing.  `prd-bench-local-run --isolation per-test-server`
# re-invokes this script before every test (8 rounds concurrently), so an
# unconditional pip install here would cause boot-time contention and flaky
# "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

# Foreground server; `exec` hands the process over so signals propagate and the
# script does not exit while the server is running.
exec python3 app.py