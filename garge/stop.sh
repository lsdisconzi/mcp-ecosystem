#!/usr/bin/env bash
# garge - stop API + MCP servers
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$SCRIPT_DIR/.run"
LEGACY_PID_FILE="$SCRIPT_DIR/.garage.pid"
PORT="${PORT:-8066}"
QUIET="${1:-}"

stop_pid_file() {
    local pid_file="$1"
    local label="$2"
    [[ -f "$pid_file" ]] || return 0

    local pid
    pid="$(cat "$pid_file")"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        sleep 0.2
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null || true
        fi
        [[ "$QUIET" == "--quiet" ]] || echo "Stopped $label (pid=$pid)"
    fi
    rm -f "$pid_file"
}

if [[ -d "$RUN_DIR" ]]; then
    stop_pid_file "$RUN_DIR/mcp-qdrant.pid" "mcp-qdrant"
    stop_pid_file "$RUN_DIR/mcp-prompt.pid" "mcp-prompt"
    stop_pid_file "$RUN_DIR/mcp-ingestion.pid" "mcp-ingestion"
    stop_pid_file "$RUN_DIR/mcp-files.pid" "mcp-files"
    stop_pid_file "$RUN_DIR/mcp-core.pid" "mcp-core"
    stop_pid_file "$RUN_DIR/garge-api.pid" "garge-api"
fi

stop_pid_file "$LEGACY_PID_FILE" "garge-api"

pids="$(lsof -ti :"$PORT" 2>/dev/null || true)"
if [[ -n "$pids" ]]; then
    echo "$pids" | xargs kill -9 2>/dev/null || true
    [[ "$QUIET" == "--quiet" ]] || echo "Cleared port :$PORT"
fi

pkill -f "$SCRIPT_DIR/mcp/servers/core_server.py" 2>/dev/null || true
pkill -f "$SCRIPT_DIR/mcp/servers/files_server.py" 2>/dev/null || true
pkill -f "$SCRIPT_DIR/mcp/servers/ingestion_server.py" 2>/dev/null || true
pkill -f "$SCRIPT_DIR/mcp/servers/prompt_server.py" 2>/dev/null || true
pkill -f "$SCRIPT_DIR/mcp/servers/qdrant_server.py" 2>/dev/null || true

[[ "$QUIET" == "--quiet" ]] || echo "Done"
