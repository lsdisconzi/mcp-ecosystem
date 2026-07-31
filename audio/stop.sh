#!/usr/bin/env bash
# audio - stop webapp API + MCP server
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-8777}"
MCP_PORT="${MCP_PORT:-8765}"
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
info "Stopping audio services..."

stop_by_pid_file "audio" "api"
stop_by_pid_file "audio" "mcp"

# Belt-and-braces: kill anything on our ports
kill_port "audio" "api" "$PORT"
kill_port "audio" "mcp" "$MCP_PORT"
pkill -f "$SCRIPT_DIR/mcp/torchaudio_mcp/server.py" 2>/dev/null || true
pkill -f "webapp.server:app" 2>/dev/null || true

[[ "$QUIET" == "--quiet" ]] || ok "audio stopped — logs preserved in .dev-logs/"