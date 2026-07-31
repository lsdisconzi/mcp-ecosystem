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

# Source centralized logging
source "$SCRIPT_DIR/../.dev-logs/common-logging.sh"

mkdir -p "$(dirname "$(get_log_file "violation-refiner" "mcp")")"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing project environment in $SCRIPT_DIR/.venv" >&2
  exit 1
fi

if ! "$PYTHON_BIN" -c "import pydantic, mcp" >/dev/null 2>&1; then
  echo "Installing missing ViolationRefiner Python dependencies"
  "$PIP_BIN" install -e ".[mcp]" >>"$(get_log_file "violation-refiner" "bootstrap")" 2>&1
fi

"$SCRIPT_DIR/stop.sh" --quiet || true

echo "Starting ViolationRefiner MCP server (${MCP_TRANSPORT})"
start_logging "violation-refiner" "mcp" env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8124 \
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
echo "  Logs  : .dev-logs/violation-refiner/"
echo "  Stop  : ./stop.sh"