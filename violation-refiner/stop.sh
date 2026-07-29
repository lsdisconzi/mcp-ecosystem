#!/usr/bin/env bash
# ViolationRefiner - stop MCP server
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$SCRIPT_DIR/.run"
MCP_PORT="${MCP_PORT:-8124}"
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
  stop_pid_file "$RUN_DIR/violation-refiner-mcp.pid" "violation-refiner-mcp"
fi

mcp_pids="$(lsof -ti :"$MCP_PORT" 2>/dev/null || true)"
if [[ -n "$mcp_pids" ]]; then
  echo "$mcp_pids" | xargs kill -9 2>/dev/null || true
  [[ "$QUIET" == "--quiet" ]] || echo "Cleared MCP port :$MCP_PORT"
fi

pkill -f "violation_pack.mcp_server" 2>/dev/null || true
pkill -f "violation-pack-mcp" 2>/dev/null || true

[[ "$QUIET" == "--quiet" ]] || echo "Done"
