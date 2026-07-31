#!/usr/bin/env bash
# transcription - start API + MCP servers
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

cd "$SCRIPT_DIR"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-${transcription_PORT:-8049}}"
APP_URL="${APP_URL:-http://${HOST}:${PORT}/pinocchio}"

MCP_TRANSPORT="${MCP_TRANSPORT:-streamable-http}"
MCP_HOST="${MCP_HOST:-0.0.0.0}"

PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
UVICORN_BIN="$SCRIPT_DIR/.venv/bin/uvicorn"

# Source centralized logging
source "$SCRIPT_DIR/../.dev-logs/common-logging.sh"

mkdir -p "$(dirname "$(get_log_file "transcription" "api")")"

if [[ ! -x "$PYTHON_BIN" || ! -x "$UVICORN_BIN" ]]; then
    echo "Missing project Python environment in $SCRIPT_DIR/.venv" >&2
    exit 1
fi

"$SCRIPT_DIR/stop.sh" --quiet || true

echo "Starting transcription API on ${HOST}:${PORT}"
start_logging "transcription" "api" env PYTHONUNBUFFERED=1 "$UVICORN_BIN" src.main:app --host "$HOST" --port "$PORT"

echo "Starting transcription MCP servers (${MCP_TRANSPORT})"
start_logging "transcription" "mcp-transcription" env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8121 \
    "$PYTHON_BIN" -m src.mcp.servers.transcription_server
start_logging "transcription" "mcp-transcripts" env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8122 \
    "$PYTHON_BIN" -m src.mcp.servers.transcripts_server
start_logging "transcription" "mcp-meta" env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8123 \
    "$PYTHON_BIN" -m src.mcp.servers.meta_server

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
echo "transcription is running"
echo "  URL  : $APP_URL"
echo "  Logs : .dev-logs/transcription/"
echo "  Stop : ./stop.sh"