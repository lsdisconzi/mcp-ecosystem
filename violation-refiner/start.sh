#!/usr/bin/env bash
# ViolationRefiner - start MCP server
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

cd "$SCRIPT_DIR"

MCP_TRANSPORT="${MCP_TRANSPORT:-streamable-http}"
MCP_HOST="${MCP_HOST:-0.0.0.0}"

PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
PIP_BIN="$SCRIPT_DIR/.venv/bin/pip"

LOG_DIR="$SCRIPT_DIR/.logs"
RUN_DIR="$SCRIPT_DIR/.run"
mkdir -p "$LOG_DIR" "$RUN_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing project environment in $SCRIPT_DIR/.venv" >&2
  exit 1
fi

if ! "$PYTHON_BIN" -c "import pydantic, mcp" >/dev/null 2>&1; then
  echo "Installing missing ViolationRefiner Python dependencies"
  "$PIP_BIN" install -e ".[mcp]" >>"$LOG_DIR/bootstrap.log" 2>&1
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

echo "Starting ViolationRefiner MCP server (${MCP_TRANSPORT})"
start_bg "violation-refiner-mcp" "$RUN_DIR/violation-refiner-mcp.pid" "$LOG_DIR/mcp.log" \
    env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8124 \
    "$PYTHON_BIN" -m violation_pack.mcp_server

echo "Waiting for MCP health endpoint"
for _ in $(seq 1 30); do
    if curl -sf "http://${MCP_HOST}:8124/health" >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
done

echo ""
echo "ViolationRefiner MCP is running"
echo "  Transport : ${MCP_TRANSPORT}"
echo "  Logs  : $LOG_DIR"
echo "  Stop  : ./stop.sh"
