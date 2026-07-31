#!/usr/bin/env bash
# install-all.sh — Install dependencies for all projects in mcp-ecosystem
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
G='\033[0;32m' Y='\033[0;33m' R='\033[0;31m' C='\033[0;36m' N='\033[0m'
info()  { printf "${C}▸${N} %s\n" "$*"; }
ok()    { printf "${G}✓${N} %s\n" "$*"; }
warn()  { printf "${Y}⚠${N} %s\n" "$*"; }
fail()  { printf "${R}✗${N} %s\n" "$*"; }

run() {
    local dir="$1"
    local cmd="$2"
    local desc="$3"
    info "$desc"
    if (cd "$dir" && eval "$cmd"); then
        ok "$desc"
    else
        warn "$desc failed (continuing...)"
    fi
}

info "Installing dependencies for all mcp-ecosystem projects..."

# ── discovery ──
run "$ROOT/discovery" "npm ci" "discovery (root): npm ci"
run "$ROOT/discovery/case-server" "npm ci" "discovery/case-server: npm ci"
run "$ROOT/discovery/mcp" "npm ci" "discovery/mcp: npm ci"
run "$ROOT/discovery/ui" "npm ci" "discovery/ui: npm ci"

# ── juris-search ──
run "$ROOT/juris-search/mcp" "npm ci" "juris-search/mcp: npm ci"
run "$ROOT/juris-search/tjrs-frontend" "npm ci" "juris-search/tjrs-frontend: npm ci"

# ── garge (Python) ──
if [[ -f "$ROOT/garge/requirements.txt" ]]; then
    run "$ROOT/garge" "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" "garge: Python venv + deps"
fi
if [[ -f "$ROOT/garge/mcp/requirements.txt" ]]; then
    run "$ROOT/garge" "python3 -m venv .venv-mcp && .venv-mcp/bin/pip install -r mcp/requirements.txt" "garge: MCP venv + deps"
fi

# ── violation-refiner (Python) ──
if [[ -f "$ROOT/violation-refiner/pyproject.toml" ]]; then
    run "$ROOT/violation-refiner" "python3 -m venv .venv && .venv/bin/pip install -e '.[mcp]'" "violation-refiner: Python venv + editable install"
fi

# ── audio (Python) ──
if [[ -f "$ROOT/audio/requirements.txt" ]]; then
    run "$ROOT/audio" "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" "audio: Python venv + deps"
fi

# ── ocr (Python) ──
if [[ -f "$ROOT/ocr/requirements.txt" ]]; then
    run "$ROOT/ocr" "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" "ocr: Python venv + deps"
fi

# ── transcription (Python) ──
if [[ -f "$ROOT/transcription/requirements.txt" ]]; then
    run "$ROOT/transcription" "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" "transcription: Python venv + deps"
fi

# ── ops (Python) ──
if [[ -f "$ROOT/ops/requirements.txt" ]]; then
    run "$ROOT/ops" "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" "ops: Python venv + deps"
fi

ok "All installations attempted. Check warnings above for any failures."
info "Run ./start-all.sh to start all services."