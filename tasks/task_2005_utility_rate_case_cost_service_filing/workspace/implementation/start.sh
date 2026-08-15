#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
# The entry filename is deliberately task-unique: co-tenant pipelines on this
# shared host run `pkill -f "python3 app.py"` / `pkill -f app.py` as sweep
# cleanup, which would otherwise kill this server mid-test and surface as
# spurious connection resets. The evaluator contract is `bash start.sh`.
exec python3 utility_rate_case_server.py
