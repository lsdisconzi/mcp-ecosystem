#!/usr/bin/env bash
# juris-search - stop API + MCP server
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-8000}"
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
info "Stopping juris-search services..."

stop_by_pid_file "juris-search" "api"
stop_by_pid_file "juris-search" "mcp"

# Belt-and-braces: kill anything on our ports
kill_port "juris-search" "api" "$PORT"
pkill -f "$SCRIPT_DIR/mcp/juris_mcp_server.js" 2>/dev/null || true

[[ "$QUIET" == "--quiet" ]] || ok "juris-search stopped — logs preserved in .dev-logs/"