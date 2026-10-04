#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install dependencies ONLY when they are missing.  The test harness re-invokes
# this script before every individual pytest test (per-test-server isolation),
# and the stability sweep reboots the server concurrently; an unconditional
# `pip install` on every boot would contend on the package index and push
# startup past the runner's restart window.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

# No .pyc is written: concurrent boots re-import the same modules, and avoiding
# bytecode churn keeps the implementation directory free of runtime artifacts.
export PYTHONDONTWRITEBYTECODE=1

# Foreground server; $PORT is honoured by app.py (default 10000) and the
# server binds 0.0.0.0.
exec python3 app.py