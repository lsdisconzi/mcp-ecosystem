#!/usr/bin/env bash
# Stop Discovery services
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
HOME_LOGDIR="$HOME/.dev-logs"
PROJECT_LOGDIR="$ROOT/.dev-discovery-log"
mkdir -p "$HOME_LOGDIR" "$PROJECT_LOGDIR"

sync_logs_to_project() {
  find "$HOME_LOGDIR" -maxdepth 1 -type f \( -name "*.log" -o -name "*.pid" -o -name "*.env" \) -exec cp -f {} "$PROJECT_LOGDIR"/ \; 2>/dev/null || true
}

for port in 3010; do
  pids=$(lsof -ti :"$port" 2>/dev/null || true)
  [ -n "$pids" ] && echo "$pids" | xargs kill -9 2>/dev/null && echo "Stopped :$port"
done
sync_logs_to_project
echo "Done"
