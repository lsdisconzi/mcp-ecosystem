#!/usr/bin/env bash
# Discovery — Stop all services
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CASE_PORT="${PORT:-${CASE_PORT:-3010}}"

# Source centralized logging
source "$ROOT/../.dev-logs/common-logging.sh"

# ── Colors ──
R='\033[0;31m' G='\033[0;32m' A='\033[0;33m' C='\033[0;36m' W='\033[1;37m' N='\033[0m'
info()  { printf "${C}▸${N} %s\n" "$*"; }
ok()    { printf "${G}✓${N} %s\n" "$*"; }
warn()  { printf "${A}⚠${N} %s\n" "$*"; }
fail()  { printf "${R}✗${N} %s\n" "$*"; exit 1; }

# ── Stop existing processes ──
stop_existing() {
  local killed=0
  for port in $CASE_PORT; do
    local pids
    pids=$(lsof -ti :"$port" 2>/dev/null || true)
    if [ -n "$pids" ]; then
      echo "$pids" | xargs kill -9 2>/dev/null || true
      killed=1
    fi
  done

  # Also stop case-server via PID file
  stop_by_pid_file "discovery" "case-server"

  if [ "$killed" -eq 1 ]; then
    info "Stopped previous processes"
    sleep 1
  fi
}

# ════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════
info "Stopping Discovery services..."

stop_existing

kill_port "discovery" "case-server" "$CASE_PORT"

ok "Discovery stopped — logs preserved in .dev-logs/"