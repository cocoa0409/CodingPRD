#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# The test harness re-invokes this script before every single test
# (prd-bench-local-run --isolation per-test-server) and runs the stability
# sweep concurrently, so the dependency install MUST be a no-op once the
# framework is importable.  An unconditional `pip install` here would make
# hundreds of contended installs and surface as flaky "could not be restarted".
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

# Foreground hand-off so the runner's SIGTERM reaches the server process.
exec python3 app.py
