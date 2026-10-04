#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install only when the framework is missing: this script is re-invoked before
# every per-test server reboot (many boots run concurrently on the host), so an
# unconditional pip install here causes boot-time contention and flaky restarts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py