#!/bin/bash
# Thin wrapper — always forces MODE=DEV, activates venv, then delegates to the Python test runner.
# Usage:
#   ./tests/test-all.sh
#   QUERY="ristorante napoli" ./tests/test-all.sh
#   BASE_URL=http://myserver:8000 ./tests/test-all.sh

export MODE=DEV   # tests always use cheap/fast images

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Activate venv so playwright, requests, etc. are available
VENV="$PROJECT_DIR/venv"
if [ -f "$VENV/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
else
  echo "⚠️  No venv found at $VENV — running with system python3"
  echo "   Create it: python3 -m venv venv && pip install -r requirements.txt"
fi

exec python3 "$SCRIPT_DIR/test-all.py" "$@"
