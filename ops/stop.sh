#!/usr/bin/env bash
# ops-dashboard/stop.sh — resilient stopper (default port 9000)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${PORT:-${OPS_DASHBOARD_PORT:-9000}}"
PID_FILE="$SCRIPT_DIR/.ops-dashboard.pid"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)
            PORT="${2:-$PORT}"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--port <num>]"
            exit 1
            ;;
    esac
done

stop_pid() {
    local pid="$1"
    if [[ -z "$pid" ]]; then
        return 1
    fi

    if ! kill -0 "$pid" >/dev/null 2>&1; then
        return 1
    fi

    kill "$pid" >/dev/null 2>&1 || true

    for ((_try=0; _try<25; _try++)); do
        if ! kill -0 "$pid" >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.2
    done

    kill -9 "$pid" >/dev/null 2>&1 || true

    for ((_try=0; _try<10; _try++)); do
        if ! kill -0 "$pid" >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.1
    done

    return 1
}

stopped_any=0

if [[ -f "$PID_FILE" ]]; then
    pid_from_file="$(tr -d '[:space:]' < "$PID_FILE" || true)"
    if [[ "$pid_from_file" =~ ^[0-9]+$ ]]; then
        if stop_pid "$pid_from_file"; then
            echo "Stopped ops-dashboard from PID file (pid: $pid_from_file)"
            stopped_any=1
        fi
    fi
fi

pids_on_port="$(lsof -ti :"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [[ -n "$pids_on_port" ]]; then
    while IFS= read -r pid; do
        [[ -z "$pid" ]] && continue
        if stop_pid "$pid"; then
            echo "Stopped process on port $PORT (pid: $pid)"
            stopped_any=1
        fi
    done <<< "$pids_on_port"
fi

if [[ -f "$PID_FILE" ]]; then
    rm -f "$PID_FILE"
fi

remaining="$(lsof -ti :"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [[ -n "$remaining" ]]; then
    echo "Failed to stop all processes on port $PORT"
    echo "Remaining PID(s):"
    echo "$remaining"
    exit 1
fi

if [[ "$stopped_any" -eq 1 ]]; then
    echo "ops-dashboard stopped on port $PORT"
else
    echo "ops-dashboard is not running on port $PORT"
fi
