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
LOG_DIR="$SCRIPT_DIR/.logs"
RUN_DIR="$SCRIPT_DIR/.run"
LEGACY_PID_FILE="$SCRIPT_DIR/.transcription.pid"

mkdir -p "$LOG_DIR" "$RUN_DIR"

if [[ ! -x "$PYTHON_BIN" || ! -x "$UVICORN_BIN" ]]; then
    echo "Missing project Python environment in $SCRIPT_DIR/.venv" >&2
    exit 1
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

echo "Starting transcription API on ${HOST}:${PORT}"
start_bg "transcription-api" "$RUN_DIR/transcription-api.pid" "$LOG_DIR/api.log" \
    env PYTHONUNBUFFERED=1 "$UVICORN_BIN" src.main:app --host "$HOST" --port "$PORT"
cp "$RUN_DIR/transcription-api.pid" "$LEGACY_PID_FILE"

echo "Starting transcription MCP servers (${MCP_TRANSPORT})"
start_bg "mcp-transcription" "$RUN_DIR/mcp-transcription.pid" "$LOG_DIR/mcp-transcription.log" \
    env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8121 \
    "$PYTHON_BIN" -m src.mcp.servers.transcription_server
start_bg "mcp-transcripts" "$RUN_DIR/mcp-transcripts.pid" "$LOG_DIR/mcp-transcripts.log" \
    env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8122 \
    "$PYTHON_BIN" -m src.mcp.servers.transcripts_server
start_bg "mcp-meta" "$RUN_DIR/mcp-meta.pid" "$LOG_DIR/mcp-meta.log" \
    env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8123 \
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
echo "  Logs : $LOG_DIR"
echo "  Stop : ./stop.sh"
