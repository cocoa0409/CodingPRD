#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PORT="${PORT:-8080}"
export PYTHONDONTWRITEBYTECODE=1
exec python3 app.py
