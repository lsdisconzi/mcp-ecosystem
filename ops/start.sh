#!/usr/bin/env bash
# ops-dashboard/start.sh — resilient launcher (port 9000)
#
# Default mode is daemonized so the dashboard survives terminal/session churn.
# Use --foreground to keep legacy blocking behavior.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${PORT:-${OPS_DASHBOARD_PORT:-9000}}"
MODE="daemon"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)
            PORT="${2:-$PORT}"
            shift 2
            ;;
        --foreground)
            MODE="foreground"
            shift
            ;;
        --daemon)
            MODE="daemon"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--port <num>] [--foreground|--daemon]"
            exit 1
            ;;
    esac
done

export OPS_DASHBOARD_PORT="$PORT"
VENV_BIN="$SCRIPT_DIR/.venv/bin"
PYTHON_BIN="$VENV_BIN/python"

# Source centralized logging
source "$SCRIPT_DIR/../.dev-logs/common-logging.sh"

mkdir -p "$(dirname "$(get_log_file "ops" "dashboard")")"

if [[ ! -x "$PYTHON_BIN" ]]; then
    python3 -m venv "$SCRIPT_DIR/.venv"
    "$VENV_BIN/pip" install -q -r requirements.txt
fi

existing_pid="$(lsof -ti :"$PORT" -sTCP:LISTEN 2>/dev/null | head -n1 || true)"
if [[ -n "$existing_pid" ]]; then
    echo "ops-dashboard already running on port $PORT (pid: $existing_pid)"
    exit 0
fi

if [[ "$MODE" == "foreground" ]]; then
    echo "============================================================"
    echo "  Awareness-AI · Ops Dashboard"
    echo "  http://localhost:$PORT"
    echo "============================================================"
    exec "$PYTHON_BIN" app.py
fi

echo "Starting ops-dashboard in daemon mode on port $PORT..."
start_logging "ops" "dashboard" env PYTHONUNBUFFERED=1 "$PYTHON_BIN" app.py

for ((_try=0; _try<30; _try++)); do
    if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
        echo "ops-dashboard started (port: $PORT)"
        echo "log: $(get_log_file "ops" "dashboard")"
        exit 0
    fi
    sleep 0.2
done

echo "ops-dashboard failed to start on port $PORT"
tail -n 40 "$(get_log_file "ops" "dashboard")" || true
exit 1