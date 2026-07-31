#!/usr/bin/env bash
# ops-dashboard/stop.sh — resilient stopper (default port 9000)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${PORT:-${OPS_DASHBOARD_PORT:-9000}}"
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
info "Stopping ops-dashboard..."

stop_by_pid_file "ops" "dashboard"

# Belt-and-braces: kill anything on our port
kill_port "ops" "dashboard" "$PORT"

[[ "$QUIET" == "--quiet" ]] || ok "ops-dashboard stopped — logs preserved in .dev-logs/"