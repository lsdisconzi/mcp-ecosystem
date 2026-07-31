#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# Discovery — One-Command Start
# Awareness-AI · Ontology v2.4 · Accountable by Design
#
# Usage:  ./start.sh
#   • First run  → installs deps, starts service, opens browser
#   • Next runs  → restarts everything, opens browser
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CASE_PORT="${PORT:-${CASE_PORT:-3010}}"

# Source centralized logging
source "$ROOT/../.dev-logs/common-logging.sh"
LOGDIR=$(get_log_file "discovery" "main")
mkdir -p "$(dirname "$LOGDIR")"

# ── Colors ──
R='\033[0;31m' G='\033[0;32m' A='\033[0;33m' C='\033[0;36m' W='\033[1;37m' N='\033[0m'
info()  { printf "${C}▸${N} %s\n" "$*"; }
ok()    { printf "${G}✓${N} %s\n" "$*"; }
warn()  { printf "${A}⚠${N} %s\n" "$*"; }
fail()  { printf "${R}✗${N} %s\n" "$*"; exit 1; }

# ── Pre-flight checks ──
command -v node    >/dev/null 2>&1 || fail "node not found — install Node.js 18+ from https://nodejs.org"
command -v npm     >/dev/null 2>&1 || fail "npm not found — install Node.js 18+"

# ── Stop any previous processes on our ports ──
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
  if [ "$killed" -eq 1 ]; then
    info "Stopped previous processes"
    sleep 1
  fi
}

# ── Install Node deps ──
install_node() {
  info "Installing Discovery runtime dependencies…"
  cd "$ROOT"
  npm install --omit=dev --silent 2>&1 | tail -1
  ok "Runtime dependencies ready"
  cd "$ROOT"
}

# ── Check if runtime deps need installing ──
runtime_deps_ready() {
  [ -d "$ROOT/node_modules/express" ] && [ -d "$ROOT/node_modules/cors" ] && [ -d "$ROOT/node_modules/multer" ]
}

# ── Start case-server (Node.js) ──
start_case_server() {
  info "Starting Discovery on :${CASE_PORT}…"
  cd "$ROOT"
  # Strict isolation default: start on an isolated workspace root, not shared documents_scanned.
  local default_root="$ROOT/documents_scanned/sessions/_server_boot/workspace"
  mkdir -p "$default_root"
  export ROOT_DIR="${ROOT_DIR:-$default_root}"
  export DISCOVERY_STRICT_ISOLATION="${DISCOVERY_STRICT_ISOLATION:-true}"
  export DISCOVERY_ALLOW_GLOBAL_ROOT="${DISCOVERY_ALLOW_GLOBAL_ROOT:-false}"
  export DISCOVERY_WORKSPACE_BASE_DIR="${DISCOVERY_WORKSPACE_BASE_DIR:-$ROOT/documents_scanned/sessions}"
  export PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-http://localhost:${CASE_PORT}}"

  local log_file=$(get_log_file "discovery" "case-server")
  local pid_file=$(get_pid_file "discovery" "case-server")
  mkdir -p "$(dirname "$log_file")"

  nohup sh -c "node case-server/auto_server_builder.js 2>&1 | tee -a '$log_file' >/dev/null" >/dev/null 2>&1 &
  echo $! > "$pid_file"
  log_ok "discovery" "case-server" "Started PID $!, logging to $log_file"
  cd "$ROOT"
}

# ── Wait for a service to become healthy ──
wait_for() {
  local name=$1 url=$2 tries=0
  while [ $tries -lt 20 ]; do
    if curl -sf "$url" >/dev/null 2>&1; then
      ok "$name is live"
      return 0
    fi
    sleep 0.5
    tries=$((tries + 1))
  done
  warn "$name didn't respond — check $LOGDIR/"
  return 1
}

should_open_browser() {
  case "${OPEN_BROWSER:-auto}" in
    0|false|FALSE|no|NO) return 1 ;;
    1|true|TRUE|yes|YES) return 0 ;;
  esac

  # Remote shell sessions should never try to launch a local browser.
  if [ -n "${SSH_CONNECTION:-}" ] || [ -n "${SSH_TTY:-}" ] || { [ -n "${TERM_PROGRAM:-}" ] && [ "${TERM_PROGRAM:-}" = "vscode" ]; }; then
    return 1
  fi

  if [ "$(uname -s)" = "Darwin" ]; then
    return 0
  fi

  # Only auto-open on Linux when a GUI session is clearly available.
  if [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
    return 0
  fi

  return 1
}

# ════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════
printf "\n${W}═══════════════════════════════════════════════${N}\n"
printf "${W}  Discovery · Awareness-AI${N}\n"
printf "${W}═══════════════════════════════════════════════${N}\n\n"

stop_existing

if ! runtime_deps_ready; then
  install_node
else
  ok "Runtime dependencies already installed"
fi

start_case_server

echo ""
wait_for "case-server"       "http://localhost:${CASE_PORT}/health"

echo ""
printf "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}\n"
printf "${W}  Case API:  ${A}http://localhost:${CASE_PORT}${N}\n"
printf "${W}  Discovery UI: ${A}http://localhost:${CASE_PORT}${N}\n"
printf "${W}  API:       ${A}http://localhost:${CASE_PORT}/api/manifest${N}\n"
printf "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}\n\n"

# Open browser only when a local GUI session is available.
if should_open_browser; then
  if command -v open >/dev/null 2>&1; then
    open "http://localhost:${CASE_PORT}"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://localhost:${CASE_PORT}"
  elif command -v start >/dev/null 2>&1; then
    start "http://localhost:${CASE_PORT}"
  fi
else
  warn "Skipping browser open in headless session. From your Mac, use: ssh -L ${CASE_PORT}:localhost:${CASE_PORT} root@72.60.143.139"
fi

log_ok "discovery" "main" "Ready — logs in $LOGDIR"
