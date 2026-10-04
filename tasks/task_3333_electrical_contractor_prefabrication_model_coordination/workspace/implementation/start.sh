#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install only when the framework is missing — the runner re-invokes start.sh
# before every per-test reboot (8 rounds concurrently), so an unconditional
# pip install here causes boot-time contention and flaky restart timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

export PORT="${PORT:-10000}"
exec python3 app.py