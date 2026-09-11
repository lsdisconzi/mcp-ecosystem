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
MCP_PORT="${MCP_PORT:-8124}"

# The health probe needs a concrete destination: 0.0.0.0 is a bind address.
PROBE_HOST="$MCP_HOST"
if [[ -z "$PROBE_HOST" || "$PROBE_HOST" == "0.0.0.0" ]]; then
  PROBE_HOST="127.0.0.1"
fi

# Source centralized logging
source "$SCRIPT_DIR/../.dev-logs/common-logging.sh"

mkdir -p "$(dirname "$(get_log_file "violation-refiner" "mcp")")"

# Resolve a project interpreter. Prefer this checkout's virtualenv, but fall
# back to PATH so a fresh clone that has not created `.venv` yet can still
# start (the bootstrap below installs deps for whichever interpreter is found).
resolve_python() {
  local candidate
  for candidate in \
    "$SCRIPT_DIR/.venv/bin/python" \
    "$(command -v python3 2>/dev/null || true)" \
    "$(command -v python 2>/dev/null || true)"
  do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

if ! PYTHON_BIN="$(resolve_python)"; then
  echo "No Python interpreter found (looked for .venv/bin/python, python3, python)." >&2
  echo "Create the environment first, e.g.:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -e '.[mcp]'" >&2
  exit 1
fi

if ! "$PYTHON_BIN" -c "import importlib.metadata as md; import pydantic, mcp; raise SystemExit(0 if md.version('mcp').split('.')[0] == '1' else 1)" >/dev/null 2>&1; then
  echo "Installing compatible ViolationRefiner Python dependencies"
  "$PYTHON_BIN" -m pip install --upgrade --force-reinstall -e ".[mcp]" >>"$(get_log_file "violation-refiner" "bootstrap")" 2>&1
fi

"$SCRIPT_DIR/stop.sh" --quiet || true

echo "Starting ViolationRefiner MCP server (${MCP_TRANSPORT})"
start_logging "violation-refiner" "mcp" env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT="$MCP_PORT" \
    "$PYTHON_BIN" -m violation_pack.mcp_server

echo "Waiting for MCP health endpoint"
for _ in $(seq 1 30); do
    if curl -sf "http://${PROBE_HOST}:${MCP_PORT}/health" >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
done

if ! wait_for_port "$MCP_PORT"; then
  echo "ViolationRefiner MCP failed to listen on port ${MCP_PORT}" >&2
  exit 1
fi

echo ""
echo "ViolationRefiner MCP is running"
echo "  Transport : ${MCP_TRANSPORT}"
echo "  Host/Port : ${MCP_HOST}:${MCP_PORT}"
echo "  Python    : ${PYTHON_BIN}"
echo "  Logs      : .dev-logs/violation-refiner/"
echo "  Stop      : ./stop.sh"