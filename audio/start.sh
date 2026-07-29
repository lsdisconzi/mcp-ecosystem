#!/usr/bin/env bash
# audio - start webapp API + MCP server
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

cd "$SCRIPT_DIR"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8777}"
APP_URL="${APP_URL:-http://127.0.0.1:${PORT}/}"

MCP_TRANSPORT="${MCP_TRANSPORT:-streamable-http}"
MCP_HOST="${MCP_HOST:-0.0.0.0}"
MCP_PORT="${MCP_PORT:-8765}"

PYTHON_API="$SCRIPT_DIR/.venv/bin/python"
UVICORN_BIN=""
if [[ -x "$SCRIPT_DIR/.venv-mcp/bin/python" ]]; then
  PYTHON_MCP="$SCRIPT_DIR/.venv-mcp/bin/python"
else
  PYTHON_MCP="$SCRIPT_DIR/.venv/bin/python"
fi

if [[ -x "$SCRIPT_DIR/.venv/bin/uvicorn" ]]; then
  UVICORN_BIN="$SCRIPT_DIR/.venv/bin/uvicorn"
elif [[ -x "$SCRIPT_DIR/.venv-mcp/bin/uvicorn" ]]; then
  UVICORN_BIN="$SCRIPT_DIR/.venv-mcp/bin/uvicorn"
fi

LOG_DIR="$SCRIPT_DIR/.logs"
RUN_DIR="$SCRIPT_DIR/.run"
mkdir -p "$LOG_DIR" "$RUN_DIR"

if [[ ! -x "$PYTHON_API" ]]; then
  echo "Missing project environment in $SCRIPT_DIR/.venv" >&2
  exit 1
fi

if [[ -z "$UVICORN_BIN" ]] && ! "$PYTHON_API" -c "import uvicorn" >/dev/null 2>&1; then
  echo "Missing uvicorn for audio webapp (.venv/.venv-mcp)" >&2
  exit 1
fi

if [[ ! -x "$PYTHON_MCP" ]]; then
  echo "Missing Python for MCP server" >&2
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

echo "Starting audio webapp API on ${HOST}:${PORT}"
if [[ -n "$UVICORN_BIN" ]]; then
  start_bg "audio-api" "$RUN_DIR/audio-api.pid" "$LOG_DIR/api.log" \
    env PYTHONUNBUFFERED=1 "$UVICORN_BIN" webapp.server:app --host "$HOST" --port "$PORT"
else
  start_bg "audio-api" "$RUN_DIR/audio-api.pid" "$LOG_DIR/api.log" \
    env PYTHONUNBUFFERED=1 "$PYTHON_API" -m uvicorn webapp.server:app --host "$HOST" --port "$PORT"
fi

echo "Starting audio MCP server (${MCP_TRANSPORT}) on ${MCP_HOST}:${MCP_PORT}"
start_bg "audio-mcp" "$RUN_DIR/audio-mcp.pid" "$LOG_DIR/mcp.log" \
  env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT="$MCP_PORT" \
  "$PYTHON_MCP" "$SCRIPT_DIR/mcp/torchaudio_mcp/server.py"

echo "Waiting for API readiness"
for _ in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${PORT}/" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

echo ""
echo "audio is running"
echo "  URL     : $APP_URL"
echo "  MCP     : ${MCP_TRANSPORT}://${MCP_HOST}:${MCP_PORT}"
echo "  Logs    : $LOG_DIR"
echo "  Stop    : ./stop.sh"
