#!/usr/bin/env bash
# Foreground launcher for the Data Labeling Ops API.
#
# The evaluator's whole contract is `bash start.sh` from ./implementation/.
# `prd-bench-local-run --isolation per-test-server` re-invokes this script
# before *every* pytest test, and the stability sweep runs several of those
# reboots concurrently, so the dependency install is guarded on a cheap
# import: an unconditional `pip install` on every boot contends on the
# package cache and shows up as flaky "could not be restarted" timeouts.
set -euo pipefail
cd "$(dirname "$0")"

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py