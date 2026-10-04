#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
# waitress preferred when available (robust under the 8-way parallel sweep);
# app.py falls back to the Flask dev server when it is not installed.
if ! python3 -c "import waitress" >/dev/null 2>&1; then
  python3 -m pip install -q waitress >/dev/null 2>&1 || true
fi
exec python3 app.py
