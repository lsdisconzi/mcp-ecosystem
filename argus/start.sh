#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p logs

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8029}"

if [[ -x .venv/bin/python3 ]]; then
    PY_BIN=".venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
    PY_BIN="python3"
else
    echo "argus: python3 not found"
    exit 1
fi

if [[ ! -d .venv ]]; then
    "$PY_BIN" -m venv .venv
fi

if [[ ! -x .venv/bin/python3 ]]; then
    echo "argus: invalid .venv, recreating"
    rm -rf .venv
    "$PY_BIN" -m venv .venv
fi

if [[ ! -f .venv/.requirements-stamp ]] || [[ requirements.txt -nt .venv/.requirements-stamp ]]; then
    .venv/bin/pip install --quiet --upgrade pip
    .venv/bin/pip install --quiet -r requirements.txt
    touch .venv/.requirements-stamp
fi

export HOST
export PORT
nohup .venv/bin/python3 app.py > logs/argus.log 2>&1 &
echo "argus started on ${HOST}:${PORT}"