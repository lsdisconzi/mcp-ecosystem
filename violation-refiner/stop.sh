#!/usr/bin/env bash
# ViolationRefiner - stop MCP server
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MCP_PORT="${MCP_PORT:-8124}"
QUIET="${1:-}"

# Source centralized logging
source "$SCRIPT_DIR/../.dev-logs/common-logging.sh"

# ── Colors ──
R='\033[0;31m' G='\033[0;32m' A='\033[0;33m' C='\033[0;36m' W='\033[1;37m' N='\033[0m'
info()  { printf "${C}▸${N} %s\n" "$*"; }
ok()    { printf "${G}✓${N} %s\n" "$*"; }
warn()  { printf "${A}⚠${N} %s\n" "$*"; }
fail()  { printf "${R}✗${N} %s\n" "$*"; exit 1; }

# ── Stop services ──
info "Stopping ViolationRefiner services..."

# Reap any ViolationRefiner server process that belongs to THIS checkout.
#
# `kill_port` below already frees the listener, so this only matters for
# transports that bind no port. It is deliberately scoped by the process's
# working directory: the previous `pkill -f violation_pack.mcp_server` was
# system-wide and would kill servers started from any other checkout or
# virtualenv on the machine.
reap_local_server_processes() {
  local pid cwd
  for pid in $(pgrep -f 'violation_pack[._]mcp_server' 2>/dev/null || true); do
    [[ "$pid" == "$$" || "$pid" == "$PPID" ]] && continue
    cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)"
    if [[ "$cwd" == "$SCRIPT_DIR" ]]; then
      kill "$pid" 2>/dev/null || true
      sleep 0.3
      kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
    fi
  done
}

stop_by_pid_file "violation-refiner" "mcp"

# Belt-and-braces: reclaim our port, then sweep any straggler from this checkout
kill_port "violation-refiner" "mcp" "$MCP_PORT"
reap_local_server_processes

[[ "$QUIET" == "--quiet" ]] || ok "ViolationRefiner stopped — logs preserved in .dev-logs/"