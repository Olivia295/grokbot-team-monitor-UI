#!/usr/bin/env sh
# Start Bot Monitoring Room on macOS or Linux and open it in the browser.
# Usage: ./start.sh [--demo] [--port 10000]
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then PY=python3; elif command -v python >/dev/null 2>&1; then PY=python; else
  echo "Python 3.9+ is required: https://www.python.org/downloads/"; exit 1
fi
exec "$PY" backend/server.py --open "$@"
