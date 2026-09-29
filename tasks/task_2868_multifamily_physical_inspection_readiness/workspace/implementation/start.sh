#!/usr/bin/env bash
# Boots the Multifamily Physical Inspection Readiness API in the foreground.
# The harness relaunches this script before every individual test, so the
# process must come up clean and hold no state from any earlier run.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 || true
fi

exec python3 app.py
