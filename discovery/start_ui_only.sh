#!/usr/bin/env bash
# discovery/start_ui_only.sh — Legacy helper kept for compatibility.
# Starts the single Node Discovery service (UI + API) on port 3010.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CASE_PORT="${PORT:-${CASE_PORT:-3010}}"
HOME_LOGDIR="$HOME/.dev-logs"
PROJECT_LOGDIR="$SCRIPT_DIR/.dev-discovery-log"
LOGDIR="$HOME_LOGDIR"
mkdir -p "$HOME_LOGDIR" "$PROJECT_LOGDIR"

sync_logs_to_project() {
	find "$HOME_LOGDIR" -maxdepth 1 -type f \( -name "*.log" -o -name "*.pid" -o -name "*.env" \) -exec cp -f {} "$PROJECT_LOGDIR"/ \; 2>/dev/null || true
}

# Kill existing process on the target port
lsof -ti :"$CASE_PORT" 2>/dev/null | xargs kill -9 2>/dev/null || true

nohup sh -c "node case-server/auto_server_builder.js 2>&1 | tee -a '$HOME_LOGDIR/discovery.log' '$PROJECT_LOGDIR/discovery.log' >/dev/null" >/dev/null 2>&1 &
echo $! > "$HOME_LOGDIR/case-server.pid"
cp -f "$HOME_LOGDIR/case-server.pid" "$PROJECT_LOGDIR/case-server.pid" 2>/dev/null || true
sync_logs_to_project
echo "discovery started on :$CASE_PORT"
