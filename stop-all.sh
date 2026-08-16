#!/usr/bin/env bash
# stop-all.sh — Stop all projects in mcp-ecosystem
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
G='\033[0;32m' Y='\033[0;33m' R='\033[0;31m' C='\033[0;36m' N='\033[0m'
info()  { printf "${C}▸${N} %s\n" "$*"; }
ok()    { printf "${G}✓${N} %s\n" "$*"; }
warn()  { printf "${Y}⚠${N} %s\n" "$*"; }
fail()  { printf "${R}✗${N} %s\n" "$*"; }

# Stop a project's stop.sh script
stop_project() {
    local dir="$1"
    local name="$2"
    local script="${3:-stop.sh}"

    if [[ -f "$dir/$script" && -x "$dir/$script" ]]; then
        info "Stopping $name..."
        if (cd "$dir" && ./"$script" --quiet); then
            ok "$name stopped"
        else
            warn "$name stop script returned non-zero (continuing)"
        fi
    else
        warn "$name: $script not found or not executable"
    fi
}

info "Stopping all mcp-ecosystem projects..."

# ── Stop in reverse order (ops first, discovery last) ──
stop_project "$ROOT/ops" "ops" "stop.sh"
stop_project "$ROOT/transcription" "transcription" "stop.sh"
stop_project "$ROOT/ocr" "ocr" "stop.sh"
stop_project "$ROOT/audio" "audio" "stop.sh"
stop_project "$ROOT/comfyui" "comfyui" "stop.sh"
stop_project "$ROOT/violation-refiner" "violation-refiner" "stop.sh"
stop_project "$ROOT/garge" "garge" "stop.sh"
stop_project "$ROOT/juris-search" "juris-search" "stop.sh"
stop_project "$ROOT/discovery" "discovery" "stop.sh"

# ── Belt-and-braces: kill any remaining processes on known ports ──
info "Clearing any remaining processes on known ports..."
PORTS=(3010 8000 8116 8066 8110 8111 8112 8113 8114 8124 8777 8765 8098 8049 8121 8122 8123 8130 8131 8132 8133 9000)
for port in "${PORTS[@]}"; do
    pids=$(lsof -ti :"$port" 2>/dev/null || true)
    if [[ -n "$pids" ]]; then
        echo "$pids" | xargs kill -9 2>/dev/null || true
        warn "Cleared port :$port"
    fi
done

# Also kill any remaining project-specific processes
pkill -f "case-server/auto_server_builder.js" 2>/dev/null || true
pkill -f "juris-search" 2>/dev/null || true
pkill -f "garge" 2>/dev/null || true
pkill -f "violation_pack.mcp_server" 2>/dev/null || true
pkill -f "audio.*webapp.server" 2>/dev/null || true
pkill -f "audio.*torchaudio_mcp" 2>/dev/null || true
pkill -f "ocr_server" 2>/dev/null || true
pkill -f "transcription.*src.main" 2>/dev/null || true
pkill -f "transcription.*src.mcp.servers" 2>/dev/null || true
pkill -f "ops-dashboard" 2>/dev/null || true
pkill -f "app.py" 2>/dev/null || true

ok "All projects stopped."