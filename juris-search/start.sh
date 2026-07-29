#!/usr/bin/env bash
# juris-search - start API + MCP server
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

cd "$SCRIPT_DIR"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
APP_URL="${APP_URL:-http://${HOST}:${PORT}/juris-search/}"
BUILD_FRONTEND="${BUILD_FRONTEND:-${JURIS_SEARCH_BUILD_FRONTEND:-0}}"

MCP_TRANSPORT="${MCP_TRANSPORT:-streamable-http}"
MCP_HOST="${MCP_HOST:-0.0.0.0}"
MCP_PORT="${MCP_PORT:-8116}"

PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
UVICORN_BIN="$SCRIPT_DIR/.venv/bin/uvicorn"
LOG_DIR="$SCRIPT_DIR/.logs"
RUN_DIR="$SCRIPT_DIR/.run"
FRONTEND_DIR="$SCRIPT_DIR/tjrs-frontend"
MCP_DIR="$SCRIPT_DIR/mcp"

mkdir -p "$LOG_DIR" "$RUN_DIR"

if [[ ! -x "$PYTHON_BIN" || ! -x "$UVICORN_BIN" ]]; then
    echo "Missing project Python environment in $SCRIPT_DIR/.venv" >&2
    exit 1
fi

if ! command -v node >/dev/null 2>&1; then
    echo "Missing node command required by juris-search MCP server" >&2
    exit 1
fi

if ! NODE_PATH="$MCP_DIR/node_modules${NODE_PATH:+:$NODE_PATH}" node -e "require('@modelcontextprotocol/sdk/server/index.js')" >/dev/null 2>&1; then
    echo "Installing juris-search MCP node dependencies"
    npm --prefix "$MCP_DIR" install --omit=dev >>"$LOG_DIR/npm-mcp.log" 2>&1
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

if [[ "$BUILD_FRONTEND" == "1" && -f "$FRONTEND_DIR/package.json" ]]; then
    echo "Building frontend"
    (
        cd "$FRONTEND_DIR"
        npm install >>"$LOG_DIR/frontend-build.log" 2>&1
        npm run build >>"$LOG_DIR/frontend-build.log" 2>&1
    )
fi

# Generate the expanded master jurisprudence index (.jsx JSON + .md companion)
if [[ -f "$SCRIPT_DIR/render_masterjurisprudence.py" && -f "$SCRIPT_DIR/master_index/master_index.json" ]]; then
    echo "Generating master jurisprudence index"
    "$PYTHON_BIN" "$SCRIPT_DIR/render_masterjurisprudence.py" \
        --input "$SCRIPT_DIR/master_index/master_index.json" \
        >>"$LOG_DIR/jurisprudence.log" 2>&1 || \
        echo "Warning: master jurisprudence index generation failed" >&2
else
    echo "Skipping master jurisprudence index (source data not present)"
fi

echo "Starting juris-search API on ${HOST}:${PORT}"
start_bg "juris-search-api" "$RUN_DIR/juris-search-api.pid" "$LOG_DIR/api.log" \
    env PYTHONUNBUFFERED=1 "$PYTHON_BIN" -m uvicorn main:app --host "$HOST" --port "$PORT"

echo "Starting juris-search MCP (${MCP_TRANSPORT})"
start_bg "mcp-juris-search" "$RUN_DIR/mcp-juris-search.pid" "$LOG_DIR/mcp-juris-search.log" \
  env MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT="$MCP_PORT" \
  JURIS_SEARCH_BASE_URL="http://127.0.0.1:${PORT}" \
  NODE_PATH="$MCP_DIR/node_modules${NODE_PATH:+:$NODE_PATH}" \
  node "$SCRIPT_DIR/mcp/juris_mcp_server.js"

echo "Waiting for API health endpoint"
for _ in $(seq 1 30); do
    if curl -sf "http://${HOST}:${PORT}/api/health" >/dev/null 2>&1; then
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
echo "juris-search is running"
echo "  URL  : $APP_URL"
echo "  Logs : $LOG_DIR"
echo "  Stop : ./stop.sh"