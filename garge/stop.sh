#!/usr/bin/env bash
# garge - stop API + MCP servers
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-8066}"
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
info "Stopping garge services..."

stop_by_pid_file "garge" "api"
stop_by_pid_file "garge" "mcp-core"
stop_by_pid_file "garge" "mcp-files"
stop_by_pid_file "garge" "mcp-ingestion"
stop_by_pid_file "garge" "mcp-prompt"
stop_by_pid_file "garge" "mcp-qdrant"

# Belt-and-braces: kill anything on our ports
kill_port "garge" "api" "$PORT"
pkill -f "$SCRIPT_DIR/mcp/servers/core_server.py" 2>/dev/null || true
pkill -f "$SCRIPT_DIR/mcp/servers/files_server.py" 2>/dev/null || true
pkill -f "$SCRIPT_DIR/mcp/servers/ingestion_server.py" 2>/dev/null || true
pkill -f "$SCRIPT_DIR/mcp/servers/prompt_server.py" 2>/dev/null || true
pkill -f "$SCRIPT_DIR/mcp/servers/qdrant_server.py" 2>/dev/null || true

[[ "$QUIET" == "--quiet" ]] || ok "garge stopped — logs preserved in .dev-logs/"