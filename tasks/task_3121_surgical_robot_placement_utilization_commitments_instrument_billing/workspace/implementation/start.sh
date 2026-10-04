#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# `prd-bench-local-run --isolation per-test-server` kills and re-launches this
# script before every individual pytest test, so the dependency install below is
# guarded on a cheap import check: an unconditional `pip install` on every boot
# would cause contention across the concurrent stability rounds and show up as
# flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py