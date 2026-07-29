#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_URL="${GARAGE_BASE_URL:-http://127.0.0.1:8066}"
MCP_PYTHON="$ROOT_DIR/.venv-mcp/bin/python3"
CORE_SERVER="$ROOT_DIR/mcp/servers/core_server.py"

if [[ ! -x "$MCP_PYTHON" ]]; then
  echo "ERROR: $MCP_PYTHON not found. Create MCP env first:" >&2
  echo "  python3 -m venv .venv-mcp && .venv-mcp/bin/pip install -r mcp/requirements.txt" >&2
  exit 1
fi

echo "[1/3] API health check: $API_URL/health"
API_HEALTH_JSON="$(curl -sS --max-time 20 "$API_URL/health")"
echo "API_HEALTH=$API_HEALTH_JSON"

echo "[2/3] MCP list_tools + garage_health"
"$MCP_PYTHON" - <<'PY'
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> int:
    base_url = os.getenv("GARAGE_BASE_URL", "http://127.0.0.1:8066")
    env = dict(os.environ)
    env["GARAGE_BASE_URL"] = base_url

    params = StdioServerParameters(
        command=".venv-mcp/bin/python3",
        args=["mcp/servers/core_server.py"],
        env=env,
    )

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"MCP_TOOLS_REGISTERED={len(tools.tools)}")

            response = await session.call_tool("garage_health", {})
            if hasattr(response, "model_dump"):
                payload = response.model_dump()
            else:
                print("ERROR: Unexpected response type from garage_health")
                return 1

            structured = payload.get("structuredContent", {})
            result = structured.get("result", structured)
            print("MCP_GARAGE_HEALTH=" + json.dumps(result, ensure_ascii=True))

            if not isinstance(result, dict) or result.get("status") != "healthy":
                print("ERROR: MCP garage_health did not report healthy status")
                return 1

    return 0


raise SystemExit(asyncio.run(main()))
PY

echo "[3/3] OK: API + MCP health validation passed"
