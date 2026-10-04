#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install only when missing: prd-bench-local-run --isolation per-test-server
# re-invokes this script before every pytest test (and the stability sweep runs
# those reboots concurrently), so an unconditional pip install here causes
# boot-time contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

# All state is in-memory and process-local: a fresh interpreter means a fresh,
# completely empty store.  Nothing is persisted anywhere.
exec python3 app.py