#!/usr/bin/env python3
"""
probe_mcp_tools.py — Probe an MCP streamable-HTTP server and print its live tool inventory.

Usage:
    python3 scripts/probe_mcp_tools.py --host 127.0.0.1 --port 8110            # -> count only
    python3 scripts/probe_mcp_tools.py --host 127.0.0.1 --port 8110 --names    # -> one tool per line
    python3 scripts/probe_mcp_tools.py --host 127.0.0.1 --port 8110 --json     # -> {"server": "...", "tools": [...]}

Returns exit code 0 on success, 1 if the server is unreachable or returns no tools.
"""
import argparse
import json
import re
import subprocess
import sys


def _request(host: str, port: int, payload: dict, session: str | None = None) -> str:
    cmd = [
        "curl", "-s", "--max-time", "6", "-X", "POST", f"http://{host}:{port}/mcp",
        "-H", "Content-Type: application/json",
        "-H", "Accept: application/json, text/event-stream",
    ]
    if session:
        cmd += ["-H", f"Mcp-Session-Id: {session}"]
    cmd += ["-d", json.dumps(payload)]
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def probe(host: str, port: int) -> tuple[str | None, list[str]]:
    """Return (server_name_or_None, tool_name_list)."""
    # 1) initialize (capture HTTP headers to obtain Mcp-Session-Id)
    init_raw = _request(host, port, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "ecosystem-report-probe", "version": "1.0"},
        },
    })
    session = None
    m = re.search(r"mcp-session-id:\s*([^\s\r\n]+)", init_raw, re.IGNORECASE)
    if m:
        session = m.group(1)

    # 2) tools/list
    raw = _request(host, port, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, session)
    server_name = None
    tools: list[str] = []
    for m in re.finditer(r"data:\s*(\{.*?\})(?:\n\n|\r\n\r\n|$)", raw, re.DOTALL):
        try:
            d = json.loads(m.group(1))
        except Exception:
            continue
        result = d.get("result")
        if not isinstance(result, dict):
            continue
        if "serverInfo" in result:
            server_name = result["serverInfo"].get("name") or server_name
        if "tools" in result:
            tools = [t.get("name", "") for t in result["tools"] if isinstance(t, dict)]
    # Some servers return a bare JSON body instead of SSE events.
    if not tools:
        try:
            d = json.loads(raw)
            result = d.get("result")
            if isinstance(result, dict) and "tools" in result:
                tools = [t.get("name", "") for t in result["tools"] if isinstance(t, dict)]
        except Exception:
            pass
    return server_name, [t for t in tools if t]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--names", action="store_true", help="Print one tool name per line")
    ap.add_argument("--json", action="store_true", help="Print JSON {server, tools}")
    args = ap.parse_args()

    server, tools = probe(args.host, args.port)
    if args.json:
        print(json.dumps({"server": server, "tools": tools}, ensure_ascii=False))
    elif args.names:
        for t in tools:
            print(t)
    else:
        print(len(tools))
    return 0 if tools else 1


if __name__ == "__main__":
    sys.exit(main())
