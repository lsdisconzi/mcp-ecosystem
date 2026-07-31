#!/usr/bin/env bash
# garge - start API + MCP servers
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

cd "$SCRIPT_DIR"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8066}"
RELOAD="${RELOAD:-0}"
APP_URL="${APP_URL:-http://${HOST}:${PORT}/}"

MCP_TRANSPORT="${MCP_TRANSPORT:-streamable-http}"
MCP_HOST="${MCP_HOST:-0.0.0.0}"

API_PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
API_UVICORN_BIN="$SCRIPT_DIR/.venv/bin/uvicorn"
API_PIP_BIN="$SCRIPT_DIR/.venv/bin/pip"
MCP_PYTHON_BIN="$SCRIPT_DIR/.venv-mcp/bin/python"
MCP_PIP_BIN="$SCRIPT_DIR/.venv-mcp/bin/pip"

# Source centralized logging
source "$SCRIPT_DIR/../.dev-logs/common-logging.sh"

mkdir -p "$(dirname "$(get_log_file "garge" "api")")"

if [[ ! -x "$API_PYTHON_BIN" || ! -x "$API_UVICORN_BIN" ]]; then
    echo "Missing project Python environment in $SCRIPT_DIR/.venv" >&2
    exit 1
fi

# Keep API dependencies pinned in .venv (MCP deps are isolated in .venv-mcp).
if ! "$API_PYTHON_BIN" -c "import importlib.metadata as md; import sys; sys.exit(0 if md.version('starlette').startswith('0.27.') and md.version('anyio').startswith('3.') else 1)" >/dev/null 2>&1; then
    echo "Repairing API dependency versions in .venv"
    "$API_PIP_BIN" install -r "$SCRIPT_DIR/requirements.txt" >>"$(get_log_file "garge" "bootstrap")" 2>&1
fi

if [[ ! -x "$MCP_PYTHON_BIN" || ! -x "$MCP_PIP_BIN" ]]; then
    echo "Creating MCP virtual environment in $SCRIPT_DIR/.venv-mcp"
    "$API_PYTHON_BIN" -m venv "$SCRIPT_DIR/.venv-mcp"
fi

if ! "$MCP_PYTHON_BIN" -c "import importlib; importlib.import_module('mcp.server.fastmcp')" >/dev/null 2>&1; then
    echo "Installing missing MCP Python dependencies in .venv-mcp"
    if [[ -f "$SCRIPT_DIR/mcp/requirements.txt" ]]; then
        "$MCP_PIP_BIN" install -r "$SCRIPT_DIR/mcp/requirements.txt" >>"$(get_log_file "garge" "bootstrap")" 2>&1
    fi
    "$MCP_PIP_BIN" install mcp >>"$(get_log_file "garge" "bootstrap")" 2>&1
fi

"$SCRIPT_DIR/stop.sh" --quiet || true

export HF_HUB_DISABLE_PROGRESS_BARS=1
export TOKENIZERS_PARALLELISM=false

UVICORN_ARGS=(main:app --host "$HOST" --port "$PORT")
if [[ "$RELOAD" == "1" ]]; then
    UVICORN_ARGS+=(--reload)
fi

echo "Starting garge API on ${HOST}:${PORT}"
start_logging "garge" "api" env PYTHONUNBUFFERED=1 "$API_UVICORN_BIN" "${UVICORN_ARGS[@]}"

echo "Starting garge MCP servers (${MCP_TRANSPORT})"
start_logging "garge" "mcp-core" env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8110 \
    "$MCP_PYTHON_BIN" "$SCRIPT_DIR/mcp/servers/core_server.py"
start_logging "garge" "mcp-files" env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8111 \
    "$MCP_PYTHON_BIN" "$SCRIPT_DIR/mcp/servers/files_server.py"
start_logging "garge" "mcp-ingestion" env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8112 \
    "$MCP_PYTHON_BIN" "$SCRIPT_DIR/mcp/servers/ingestion_server.py"
start_logging "garge" "mcp-prompt" env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8113 \
    "$MCP_PYTHON_BIN" "$SCRIPT_DIR/mcp/servers/prompt_server.py"
start_logging "garge" "mcp-qdrant" env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8114 \
    "$MCP_PYTHON_BIN" "$SCRIPT_DIR/mcp/servers/qdrant_server.py"

echo "Waiting for API health endpoint"
for _ in $(seq 1 30); do
    if curl -sf "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
done

if [[ -n "${OPEN_APP:-}" ]]; then
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$APP_URL" >/dev/null 2>&1 || true
    elif command -v open >/dev/null 2>&1; then
        open "$APP_URL" >/dev/null 2>&1 || true
    fi
fi

echo ""
echo "garge is running"
echo "  URL  : $APP_URL"
echo "  Logs : .dev-logs/garge/"
echo "  Stop : ./stop.sh"