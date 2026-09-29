#!/bin/bash
set -e
cd "$(dirname "$0")"
export PORT="${PORT:-10000}"
exec python3 app.py
