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
LOG_DIR="${DEV_LOG_DIR:-$HOME/.dev-logs}"
LOG_FILE="$LOG_DIR/ops-dashboard.log"
PID_FILE="$SCRIPT_DIR/.ops-dashboard.pid"

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

mkdir -p "$LOG_DIR"
: > "$LOG_FILE"

echo "Starting ops-dashboard in daemon mode on port $PORT..."
nohup "$PYTHON_BIN" app.py >> "$LOG_FILE" 2>&1 &
pid="$!"
echo "$pid" > "$PID_FILE"

for ((_try=0; _try<30; _try++)); do
    if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
        echo "ops-dashboard started (pid: $pid, port: $PORT)"
        echo "log: $LOG_FILE"
        exit 0
    fi
    if ! kill -0 "$pid" >/dev/null 2>&1; then
        break
    fi
    sleep 0.2
done

echo "ops-dashboard failed to start on port $PORT"
echo "Last log lines:"
tail -n 40 "$LOG_FILE" || true
exit 1
