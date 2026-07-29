#!/usr/bin/env bash
# transcription - stop API + MCP servers
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$SCRIPT_DIR/.run"
LEGACY_PID_FILE="$SCRIPT_DIR/.transcription.pid"
PORT="${PORT:-${transcription_PORT:-8049}}"
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
    stop_pid_file "$RUN_DIR/mcp-meta.pid" "mcp-meta"
    stop_pid_file "$RUN_DIR/mcp-transcripts.pid" "mcp-transcripts"
    stop_pid_file "$RUN_DIR/mcp-transcription.pid" "mcp-transcription"
    stop_pid_file "$RUN_DIR/transcription-api.pid" "transcription-api"
fi

stop_pid_file "$LEGACY_PID_FILE" "transcription-api"

pids="$(lsof -ti :"$PORT" 2>/dev/null || true)"
if [[ -n "$pids" ]]; then
    echo "$pids" | xargs kill -9 2>/dev/null || true
    [[ "$QUIET" == "--quiet" ]] || echo "Cleared port :$PORT"
fi

pkill -f "src.mcp.servers.transcription_server" 2>/dev/null || true
pkill -f "src.mcp.servers.transcripts_server" 2>/dev/null || true
pkill -f "src.mcp.servers.meta_server" 2>/dev/null || true

[[ "$QUIET" == "--quiet" ]] || echo "Done"
