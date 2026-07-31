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

stop_by_pid_file "violation-refiner" "mcp"

# Belt-and-braces: kill anything on our ports
kill_port "violation-refiner" "mcp" "$MCP_PORT"
pkill -f "violation_pack.mcp_server" 2>/dev/null || true
pkill -f "violation-pack-mcp" 2>/dev/null || true

[[ "$QUIET" == "--quiet" ]] || ok "ViolationRefiner stopped — logs preserved in .dev-logs/"