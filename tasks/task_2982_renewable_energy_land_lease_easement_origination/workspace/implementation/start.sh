#!/usr/bin/env bash
# Launch the Renewable Land Origination API.
#
# The harness kills and re-launches this script before every individual test,
# so the boot path must be fast and must never depend on state left behind by
# a previous process: storage is in-memory only and starts empty every time.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

# Flask is normally already present; only install when it is genuinely missing.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check \
    -r requirements.txt >/dev/null 2>&1 || true
fi

exec python3 app.py
