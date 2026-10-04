#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install only when the framework is genuinely missing.  The evaluator
# re-invokes this script before every single per-test reboot (concurrently,
# across rounds), so an unconditional `pip install` here would contend on the
# interpreter and push startup past the harness restart window.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

# Foreground: exec hands the process over so signals propagate to the server.
exec python3 app.py