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
LOG_DIR="$SCRIPT_DIR/.logs"
RUN_DIR="$SCRIPT_DIR/.run"
LEGACY_PID_FILE="$SCRIPT_DIR/.garage.pid"
BOOTSTRAP_LOG="$LOG_DIR/bootstrap.log"

mkdir -p "$LOG_DIR" "$RUN_DIR"

if [[ ! -x "$API_PYTHON_BIN" || ! -x "$API_UVICORN_BIN" ]]; then
    echo "Missing project Python environment in $SCRIPT_DIR/.venv" >&2
    exit 1
fi

# Keep API dependencies pinned in .venv (MCP deps are isolated in .venv-mcp).
if ! "$API_PYTHON_BIN" -c "import importlib.metadata as md; import sys; sys.exit(0 if md.version('starlette').startswith('0.27.') and md.version('anyio').startswith('3.') else 1)" >/dev/null 2>&1; then
    echo "Repairing API dependency versions in .venv"
    "$API_PIP_BIN" install -r "$SCRIPT_DIR/requirements.txt" >>"$BOOTSTRAP_LOG" 2>&1
fi

if [[ ! -x "$MCP_PYTHON_BIN" || ! -x "$MCP_PIP_BIN" ]]; then
    echo "Creating MCP virtual environment in $SCRIPT_DIR/.venv-mcp"
    "$API_PYTHON_BIN" -m venv "$SCRIPT_DIR/.venv-mcp"
fi

if ! "$MCP_PYTHON_BIN" -c "import importlib; importlib.import_module('mcp.server.fastmcp')" >/dev/null 2>&1; then
    echo "Installing missing MCP Python dependencies in .venv-mcp"
    if [[ -f "$SCRIPT_DIR/mcp/requirements.txt" ]]; then
        "$MCP_PIP_BIN" install -r "$SCRIPT_DIR/mcp/requirements.txt" >>"$BOOTSTRAP_LOG" 2>&1
    fi
    "$MCP_PIP_BIN" install mcp >>"$BOOTSTRAP_LOG" 2>&1
fi

"$SCRIPT_DIR/stop.sh" --quiet || true

start_bg() {
    local name="$1"
    local pid_file="$2"
    local log_file="$3"
    shift 3

    nohup "$@" >>"$log_file" 2>&1 &
    local pid=$!
    echo "$pid" >"$pid_file"

    if ! kill -0 "$pid" 2>/dev/null; then
        echo "Failed to start $name. Check $log_file" >&2
        return 1
    fi

    echo "Started $name (pid=$pid)"
}

export HF_HUB_DISABLE_PROGRESS_BARS=1
export TOKENIZERS_PARALLELISM=false

UVICORN_ARGS=(main:app --host "$HOST" --port "$PORT")
if [[ "$RELOAD" == "1" ]]; then
    UVICORN_ARGS+=(--reload)
fi

echo "Starting garge API on ${HOST}:${PORT}"
start_bg "garge-api" "$RUN_DIR/garge-api.pid" "$LOG_DIR/api.log" \
    env PYTHONUNBUFFERED=1 "$API_UVICORN_BIN" "${UVICORN_ARGS[@]}"
cp "$RUN_DIR/garge-api.pid" "$LEGACY_PID_FILE"

echo "Starting garge MCP servers (${MCP_TRANSPORT})"
start_bg "mcp-core" "$RUN_DIR/mcp-core.pid" "$LOG_DIR/mcp-core.log" \
    env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8110 \
    "$MCP_PYTHON_BIN" "$SCRIPT_DIR/mcp/servers/core_server.py"
start_bg "mcp-files" "$RUN_DIR/mcp-files.pid" "$LOG_DIR/mcp-files.log" \
    env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8111 \
    "$MCP_PYTHON_BIN" "$SCRIPT_DIR/mcp/servers/files_server.py"
start_bg "mcp-ingestion" "$RUN_DIR/mcp-ingestion.pid" "$LOG_DIR/mcp-ingestion.log" \
    env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8112 \
    "$MCP_PYTHON_BIN" "$SCRIPT_DIR/mcp/servers/ingestion_server.py"
start_bg "mcp-prompt" "$RUN_DIR/mcp-prompt.pid" "$LOG_DIR/mcp-prompt.log" \
    env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8113 \
    "$MCP_PYTHON_BIN" "$SCRIPT_DIR/mcp/servers/prompt_server.py"
start_bg "mcp-qdrant" "$RUN_DIR/mcp-qdrant.pid" "$LOG_DIR/mcp-qdrant.log" \
    env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8114 \
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
echo "  Logs : $LOG_DIR"
echo "  Stop : ./stop.sh"
