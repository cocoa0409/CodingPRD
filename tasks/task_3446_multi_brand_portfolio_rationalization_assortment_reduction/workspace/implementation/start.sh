#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Choose interpreter: cached venv if present, else system python3.
PY=python3
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
fi

# Install deps only when missing — start.sh is re-invoked before every
# per-test reboot (per-test-server isolation); unconditional pip install on
# every boot causes contention and flaky restart timeouts.
if ! "$PY" -c "import flask" >/dev/null 2>&1; then
  "$PY" -m pip install -q -r requirements.txt
fi

# Foreground server; PORT env var (default 10000 per INSTRUCTION.md), 0.0.0.0.
exec "$PY" app.py
