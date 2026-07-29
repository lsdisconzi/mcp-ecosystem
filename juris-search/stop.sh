#!/usr/bin/env bash
# juris-search - stop API + MCP server
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$SCRIPT_DIR/.run"
PORT="${PORT:-8000}"
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
    stop_pid_file "$RUN_DIR/mcp-juris-search.pid" "mcp-juris-search"
    stop_pid_file "$RUN_DIR/juris-search-api.pid" "juris-search-api"
fi

pids="$(lsof -ti :"$PORT" 2>/dev/null || true)"
if [[ -n "$pids" ]]; then
    echo "$pids" | xargs kill -9 2>/dev/null || true
    [[ "$QUIET" == "--quiet" ]] || echo "Cleared port :$PORT"
fi

pkill -f "$SCRIPT_DIR/mcp/juris_mcp_server.js" 2>/dev/null || true

[[ "$QUIET" == "--quiet" ]] || echo "Done"
