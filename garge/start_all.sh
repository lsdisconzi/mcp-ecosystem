#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

LOG_DIR="$PROJECT_ROOT/.logs"
mkdir -p "$LOG_DIR"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8066}"
RELOAD="${RELOAD:-1}"

START_OLLAMA="${START_OLLAMA:-0}"
START_MCP_MEMORY="${START_MCP_MEMORY:-0}"
START_MCP_SEQUENTIAL="${START_MCP_SEQUENTIAL:-0}"
START_MCP_FILESYSTEM="${START_MCP_FILESYSTEM:-0}"
START_MCP_GARAGE_QDRANT="${START_MCP_GARAGE_QDRANT:-0}"
START_MCP_GARAGE_CORE="${START_MCP_GARAGE_CORE:-0}"
START_MCP_GARAGE_INGESTION="${START_MCP_GARAGE_INGESTION:-0}"
START_MCP_GARAGE_PROMPT="${START_MCP_GARAGE_PROMPT:-0}"
START_MCP_GARAGE_FILES="${START_MCP_GARAGE_FILES:-0}"
START_FRAMEWORK_WATCHER="${START_FRAMEWORK_WATCHER:-0}"
GENERATE_FRAMEWORK_LIST_ON_START="${GENERATE_FRAMEWORK_LIST_ON_START:-1}"

MCP_FILESYSTEM_ROOT="${MCP_FILESYSTEM_ROOT:-$PROJECT_ROOT/data}"
OLLAMA_PORT="${OLLAMA_PORT:-11434}"
MCP_MEMORY_PORT="${MCP_MEMORY_PORT:-9001}"
MCP_SEQUENTIAL_PORT="${MCP_SEQUENTIAL_PORT:-9003}"

if [[ -x .venv/bin/python3 ]]; then
	PY_BIN=".venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
	PY_BIN="python3"
elif command -v python >/dev/null 2>&1; then
	PY_BIN="python"
else
	PY_BIN=""
fi

if [[ -f .venv/bin/activate ]]; then
	# shellcheck disable=SC1091
	source .venv/bin/activate
fi

port_in_use() {
	lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

start_bg() {
	local name="$1"
	local log_file="$2"
	shift 2
	"$@" >"$log_file" 2>&1 &
	echo "✅ $name started (pid=$!, log=$(basename "$log_file"))"
}

echo "🚀 Starting services from $PROJECT_ROOT"

if port_in_use "$PORT"; then
	echo "❌ Port $PORT is already in use."
	echo "   Find process: lsof -nP -iTCP:$PORT -sTCP:LISTEN"
	echo "   Stop process: kill -9 <PID>"
	exit 1
fi

if [[ "$START_OLLAMA" == "1" ]]; then
	if command -v ollama >/dev/null 2>&1; then
		if port_in_use "$OLLAMA_PORT"; then
			echo "⚠️  Skipping Ollama: port $OLLAMA_PORT already in use"
		else
			start_bg "Ollama" "$LOG_DIR/ollama.log" env OLLAMA_HOST="0.0.0.0:$OLLAMA_PORT" ollama serve
		fi
	else
		echo "⚠️  Skipping Ollama: command not found"
	fi
fi

if [[ "$START_MCP_MEMORY" == "1" ]]; then
	if command -v npx >/dev/null 2>&1; then
		if port_in_use "$MCP_MEMORY_PORT"; then
			echo "⚠️  Skipping MCP Memory: port $MCP_MEMORY_PORT already in use"
		else
			start_bg "MCP Memory" "$LOG_DIR/mcp-memory.log" npx -y @modelcontextprotocol/server-memory --port "$MCP_MEMORY_PORT"
		fi
	else
		echo "⚠️  Skipping MCP Memory: npx not found"
	fi
fi

if [[ "$START_MCP_SEQUENTIAL" == "1" ]]; then
	if command -v npx >/dev/null 2>&1; then
		if port_in_use "$MCP_SEQUENTIAL_PORT"; then
			echo "⚠️  Skipping MCP Sequential Thinking: port $MCP_SEQUENTIAL_PORT already in use"
		else
			start_bg "MCP Sequential Thinking" "$LOG_DIR/mcp-sequential-thinking.log" npx -y @modelcontextprotocol/server-sequential-thinking --port "$MCP_SEQUENTIAL_PORT"
		fi
	else
		echo "⚠️  Skipping MCP Sequential Thinking: npx not found"
	fi
fi

if [[ "$START_MCP_FILESYSTEM" == "1" ]]; then
	if command -v npx >/dev/null 2>&1; then
		mkdir -p "$MCP_FILESYSTEM_ROOT"
		start_bg "MCP Filesystem" "$LOG_DIR/mcp-filesystem.log" npx -y @modelcontextprotocol/server-filesystem "$MCP_FILESYSTEM_ROOT"
		echo "   MCP Filesystem root: $MCP_FILESYSTEM_ROOT"
	else
		echo "⚠️  Skipping MCP Filesystem: npx not found"
	fi
fi

if [[ "$START_MCP_GARAGE_QDRANT" == "1" ]]; then
	if [[ -n "$PY_BIN" ]]; then
		start_bg "Garage MCP Qdrant" "$LOG_DIR/mcp-garage-qdrant.log" "$PY_BIN" mcp/servers/qdrant_server.py
	else
		echo "⚠️  Skipping Garage MCP Qdrant: Python not found"
	fi
fi

if [[ "$START_MCP_GARAGE_CORE" == "1" ]]; then
	if [[ -n "$PY_BIN" ]]; then
		start_bg "Garage MCP Core" "$LOG_DIR/mcp-garage-core.log" "$PY_BIN" mcp/servers/core_server.py
	else
		echo "⚠️  Skipping Garage MCP Core: Python not found"
	fi
fi

if [[ "$START_MCP_GARAGE_INGESTION" == "1" ]]; then
	if [[ -n "$PY_BIN" ]]; then
		start_bg "Garage MCP Ingestion" "$LOG_DIR/mcp-garage-ingestion.log" "$PY_BIN" mcp/servers/ingestion_server.py
	else
		echo "⚠️  Skipping Garage MCP Ingestion: Python not found"
	fi
fi

if [[ "$START_MCP_GARAGE_PROMPT" == "1" ]]; then
	if [[ -n "$PY_BIN" ]]; then
		start_bg "Garage MCP Prompt" "$LOG_DIR/mcp-garage-prompt.log" "$PY_BIN" mcp/servers/prompt_server.py
	else
		echo "⚠️  Skipping Garage MCP Prompt: Python not found"
	fi
fi

if [[ "$START_MCP_GARAGE_FILES" == "1" ]]; then
	if [[ -n "$PY_BIN" ]]; then
		start_bg "Garage MCP Files" "$LOG_DIR/mcp-garage-files.log" "$PY_BIN" mcp/servers/files_server.py
	else
		echo "⚠️  Skipping Garage MCP Files: Python not found"
	fi
fi

if [[ "$GENERATE_FRAMEWORK_LIST_ON_START" == "1" ]]; then
	if [[ -n "$PY_BIN" ]]; then
		if "$PY_BIN" -c "from services.watch_frameworks import FrameworkHandler; FrameworkHandler().update_framework_list()" >/dev/null 2>&1; then
			echo "✅ Generated framework list: static/js/legal_frameworks/framework_list.json"
		else
			echo "⚠️  Could not generate framework list automatically (check python deps/logs)"
		fi
	else
		echo "⚠️  Skipping framework list generation: Python not found"
	fi
fi

if [[ "$START_FRAMEWORK_WATCHER" == "1" ]]; then
	if [[ -n "$PY_BIN" ]]; then
		start_bg "Framework Watcher" "$LOG_DIR/framework_watcher.log" "$PY_BIN" services/watch_frameworks.py
	else
		echo "⚠️  Skipping framework watcher: Python not found"
	fi
fi

UVICORN_ARGS=(main:app --host "$HOST" --port "$PORT")
if [[ "$RELOAD" == "1" ]]; then
	UVICORN_ARGS+=(--reload)
fi

echo "✅ Starting Garage API on $HOST:$PORT (reload=$RELOAD)"
if [[ -x .venv/bin/uvicorn ]]; then
	exec .venv/bin/uvicorn "${UVICORN_ARGS[@]}"
fi

if command -v uvicorn >/dev/null 2>&1; then
	exec uvicorn "${UVICORN_ARGS[@]}"
fi

echo "❌ Uvicorn not found. Install dependencies with: .venv/bin/pip install -r requirements.txt"
exit 1
