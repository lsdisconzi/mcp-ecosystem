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
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"
WEBAPP_REQUIREMENTS_FILE="$SCRIPT_DIR/webapp/requirements.txt"
REQUIREMENTS_STAMP="$SCRIPT_DIR/.venv/.requirements-stamp"
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

# Source centralized logging
source "$SCRIPT_DIR/../.dev-logs/common-logging.sh"

mkdir -p "$(dirname "$(get_log_file "audio" "api")")"

if [[ ! -x "$PYTHON_API" ]]; then
  echo "Creating audio Python environment"
  python3.12 -m venv "$SCRIPT_DIR/.venv"
fi
if [[ -f "$REQUIREMENTS_FILE" && ( ! -f "$REQUIREMENTS_STAMP" || "$REQUIREMENTS_FILE" -nt "$REQUIREMENTS_STAMP" || "$WEBAPP_REQUIREMENTS_FILE" -nt "$REQUIREMENTS_STAMP" || "$SCRIPT_DIR/mcp/requirements.txt" -nt "$REQUIREMENTS_STAMP" ) ]] || ! "$PYTHON_API" -c 'import mcp' >/dev/null 2>&1; then
  echo "Installing audio Python dependencies"
  "$PYTHON_API" -m pip install -q --upgrade pip
  "$PYTHON_API" -m pip install -q -r "$REQUIREMENTS_FILE" -r "$WEBAPP_REQUIREMENTS_FILE" -r "$SCRIPT_DIR/mcp/requirements.txt"
  touch "$REQUIREMENTS_STAMP"
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

echo "Starting audio webapp API on ${HOST}:${PORT}"
if [[ -n "$UVICORN_BIN" ]]; then
  start_logging "audio" "api" env PYTHONUNBUFFERED=1 "$UVICORN_BIN" webapp.server:app --host "$HOST" --port "$PORT"
else
  start_logging "audio" "api" env PYTHONUNBUFFERED=1 "$PYTHON_API" -m uvicorn webapp.server:app --host "$HOST" --port "$PORT"
fi

echo "Starting audio MCP server (${MCP_TRANSPORT}) on ${MCP_HOST}:${MCP_PORT}"
start_logging "audio" "mcp" env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT="$MCP_PORT" \
  "$PYTHON_MCP" "$SCRIPT_DIR/mcp/dynamic_server.py"

echo "Waiting for API readiness"
for _ in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${PORT}/" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

if ! wait_for_port "$MCP_PORT"; then
  echo "audio MCP server failed to listen on port $MCP_PORT" >&2
  exit 1
fi

echo ""
echo "audio is running"
echo "  URL     : $APP_URL"
echo "  MCP     : ${MCP_TRANSPORT}://${MCP_HOST}:${MCP_PORT}"
echo "  Logs    : .dev-logs/audio/"
echo "  Stop    : ./stop.sh"