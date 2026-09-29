#!/usr/bin/env bash
# Boots the VoIP Porting & E911 API in the foreground on $PORT (default 10000).
set -euo pipefail
cd "$(dirname "$0")"
export PORT="${PORT:-10000}"
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt \
    || python3 -m pip install --quiet --disable-pip-version-check --break-system-packages -r requirements.txt
fi
exec python3 app.py
