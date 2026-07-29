#!/usr/bin/env bash
# audio - stop webapp API + MCP server
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$SCRIPT_DIR/.run"
PORT="${PORT:-8777}"
MCP_PORT="${MCP_PORT:-8765}"
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
  stop_pid_file "$RUN_DIR/audio-mcp.pid" "audio-mcp"
  stop_pid_file "$RUN_DIR/audio-api.pid" "audio-api"
fi

api_pids="$(lsof -ti :"$PORT" 2>/dev/null || true)"
if [[ -n "$api_pids" ]]; then
  echo "$api_pids" | xargs kill -9 2>/dev/null || true
  [[ "$QUIET" == "--quiet" ]] || echo "Cleared API port :$PORT"
fi

mcp_pids="$(lsof -ti :"$MCP_PORT" 2>/dev/null || true)"
if [[ -n "$mcp_pids" ]]; then
  echo "$mcp_pids" | xargs kill -9 2>/dev/null || true
  [[ "$QUIET" == "--quiet" ]] || echo "Cleared MCP port :$MCP_PORT"
fi

pkill -f "$SCRIPT_DIR/mcp/torchaudio_mcp/server.py" 2>/dev/null || true
pkill -f "webapp.server:app" 2>/dev/null || true

[[ "$QUIET" == "--quiet" ]] || echo "Done"
