#!/usr/bin/env bash
# comfyui — start the 4 ComfyUI MCP servers (workflow/model/node/system)
# Standardized start script (compatible with ops-dashboard + start-all.sh)
# The servers are HTTP clients to the running ComfyUI server (port 8188).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

# Optional .env overrides
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a; source "$SCRIPT_DIR/.env"; set +a
fi

# ComfyUI installation root — defaults to the directory that contains mcp-ecosystem
COMFYUI_ROOT="${COMFYUI_ROOT:-$ROOT/../ComfyUI}"
COMFYUI_BASE_URL="${COMFYUI_BASE_URL:-http://127.0.0.1:8188}"
MCP_HOST="${MCP_HOST:-0.0.0.0}"
MCP_TRANSPORT="${MCP_TRANSPORT:-streamable-http}"

MCP_PYTHON="$SCRIPT_DIR/.venv-mcp/bin/python"
MCP_PIP="$SCRIPT_DIR/.venv-mcp/bin/pip"

# Source centralized logging
source "$SCRIPT_DIR/../.dev-logs/common-logging.sh"

if [[ ! -d "$COMFYUI_ROOT/mcp/servers" ]]; then
    echo "ComfyUI MCP servers not found under $COMFYUI_ROOT/mcp/servers" >&2
    echo "Set COMFYUI_ROOT to the ComfyUI installation directory." >&2
    exit 1
fi

# ── stop any existing instance ───────────────────────────────────────────────
"$SCRIPT_DIR/stop.sh" --quiet || true

# ── isolated MCP python venv ─────────────────────────────────────────────────
if [[ ! -x "$MCP_PYTHON" ]]; then
    echo "Creating ComfyUI MCP venv…"
    python3 -m venv "$SCRIPT_DIR/.venv-mcp"
fi
# The ComfyUI MCP servers import `fastmcp` directly (with a fallback to
# `mcp.server.fastmcp`). The standalone `fastmcp` package pulls in `mcp` as a
# dependency, so installing it covers both import paths.
if ! "$MCP_PYTHON" -c "import importlib; importlib.import_module('fastmcp')" >/dev/null 2>&1; then
    echo "Installing fastmcp (MCP SDK) in .venv-mcp…"
    "$MCP_PIP" install -q --upgrade fastmcp
fi

# ── start the 4 domain servers ───────────────────────────────────────────────
# name:port — script is <name>_server.py, pid/log service is mcp-<name>
servers=(workflow:8130 model:8131 node:8132 system:8133)
for entry in "${servers[@]}"; do
    name="${entry%%:*}"
    port="${entry##*:}"
    echo "Starting comfyui MCP ${name} on ${MCP_HOST}:${port}…"
    start_logging "comfyui" "mcp-$name" env PYTHONUNBUFFERED=1 \
        MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT="$port" \
        COMFYUI_BASE_URL="$COMFYUI_BASE_URL" \
        "$MCP_PYTHON" "$COMFYUI_ROOT/mcp/servers/${name}_server.py"
done

echo
echo "ComfyUI MCP servers started (workflow=8130 model=8131 node=8132 system=8133)."
echo "  ComfyUI       : ${COMFYUI_BASE_URL}"
echo "  Transport     : ${MCP_TRANSPORT}"
echo "  Logs          : .dev-logs/comfyui-mcp-*.log"
