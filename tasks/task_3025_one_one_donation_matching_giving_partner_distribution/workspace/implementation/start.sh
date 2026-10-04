#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# The harness re-invokes this script before every single pytest test
# (per-test-server isolation, run in concurrent sweeps). Installing
# unconditionally here would contend on pip and blow past the restart
# window, so the install is guarded on a cheap import check.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q --disable-pip-version-check -r requirements.txt
fi
exec python3 app.py