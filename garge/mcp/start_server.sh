#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MCP_DIR="$ROOT_DIR/mcp"
VENV_DIR="$ROOT_DIR/.venv-mcp"
PYTHON_BIN="$VENV_DIR/bin/python3"
PIP_BIN="$VENV_DIR/bin/pip"

SERVER_NAME="${1:-}"

if [[ -z "$SERVER_NAME" ]]; then
  echo "Usage: mcp/start_server.sh <core|files|ingestion|prompt|qdrant|juris>"
  exit 1
fi

case "$SERVER_NAME" in
  core)
    SERVER_SCRIPT="$MCP_DIR/servers/core_server.py"
    ;;
  files)
    SERVER_SCRIPT="$MCP_DIR/servers/files_server.py"
    ;;
  ingestion)
    SERVER_SCRIPT="$MCP_DIR/servers/ingestion_server.py"
    ;;
  prompt)
    SERVER_SCRIPT="$MCP_DIR/servers/prompt_server.py"
    ;;
  qdrant)
    SERVER_SCRIPT="$MCP_DIR/servers/qdrant_server.py"
    ;;
  juris)
    SERVER_SCRIPT="$MCP_DIR/servers/juris_server.py"
    ;;
  *)
    echo "Unknown server: $SERVER_NAME"
    echo "Valid options: core, files, ingestion, prompt, qdrant, juris"
    exit 1
    ;;
esac

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[mcp] Creating isolated MCP environment at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
  "$PIP_BIN" install --upgrade pip
  "$PIP_BIN" install -r "$MCP_DIR/requirements.txt"
fi

echo "[mcp] Starting $SERVER_NAME server"
exec "$PYTHON_BIN" "$SERVER_SCRIPT"
