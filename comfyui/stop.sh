#!/usr/bin/env bash
# comfyui — stop the 4 ComfyUI MCP servers
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
QUIET="${1:-}"

# Source centralized logging
source "$SCRIPT_DIR/../.dev-logs/common-logging.sh"

# ── Colors ──
C='\033[0;36m' N='\033[0m'
info()  { printf "${C}▸${N} %s\n" "$*"; }

info "Stopping ComfyUI MCP servers…"

for name in workflow model node system; do
    stop_by_pid_file "comfyui" "mcp-$name"
done

# Belt-and-braces: clear the ports too
for port in 8130 8131 8132 8133; do
    kill_port "comfyui" "mcp-stop" "$port"
done

[[ "$QUIET" == "--quiet" ]] || info "ComfyUI MCP servers stopped — logs preserved in .dev-logs/"
