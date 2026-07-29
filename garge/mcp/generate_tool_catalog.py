"""Generate an MCP-oriented catalog from Garage OpenAPI.

Usage:
  .venv/bin/python3 mcp/generate_tool_catalog.py

Environment variables:
  GARAGE_BASE_URL (default: http://127.0.0.1:8066)
  MCP_CATALOG_OUT_JSON (default: mcp/catalog/garage_openapi_catalog.json)
  MCP_CATALOG_OUT_MD (default: mcp/catalog/garage_openapi_catalog.md)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import httpx


def to_tool_name(method: str, path: str, operation_id: str | None) -> str:
    if operation_id:
        seed = operation_id
    else:
        seed = f"{method}_{path.strip('/').replace('/', '_').replace('-', '_')}"
    cleaned = []
    for ch in seed.lower():
        cleaned.append(ch if (ch.isalnum() or ch == "_") else "_")
    name = "".join(cleaned)
    while "__" in name:
        name = name.replace("__", "_")
    return name.strip("_")


def summarize_schema(schema: Dict[str, Any] | None) -> Dict[str, Any]:
    if not schema:
        return {}
    out: Dict[str, Any] = {}
    if "$ref" in schema:
        out["$ref"] = schema["$ref"]
        return out
    for key in ("type", "title", "description", "enum", "default"):
        if key in schema:
            out[key] = schema[key]
    if "properties" in schema and isinstance(schema["properties"], dict):
        out["properties"] = {k: summarize_schema(v) for k, v in schema["properties"].items()}
    if "required" in schema:
        out["required"] = schema["required"]
    if "items" in schema and isinstance(schema["items"], dict):
        out["items"] = summarize_schema(schema["items"])
    return out


def build_catalog(spec: Dict[str, Any], base_url: str) -> Dict[str, Any]:
    tools: List[Dict[str, Any]] = []
    paths = spec.get("paths", {})

    for path, methods in sorted(paths.items()):
        if not isinstance(methods, dict):
            continue
        for method, op in sorted(methods.items()):
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            if not isinstance(op, dict):
                continue

            operation_id = op.get("operationId")
            tool_name = to_tool_name(method, path, operation_id)
            params = []
            for prm in op.get("parameters", []):
                if not isinstance(prm, dict):
                    continue
                params.append({
                    "name": prm.get("name"),
                    "in": prm.get("in"),
                    "required": prm.get("required", False),
                    "schema": summarize_schema(prm.get("schema")),
                    "description": prm.get("description", ""),
                })

            request_schema: Dict[str, Any] = {}
            req = op.get("requestBody", {})
            if isinstance(req, dict):
                content = req.get("content", {})
                if isinstance(content, dict):
                    if "application/json" in content:
                        request_schema = summarize_schema(content["application/json"].get("schema"))
                    elif "multipart/form-data" in content:
                        request_schema = summarize_schema(content["multipart/form-data"].get("schema"))

            tools.append(
                {
                    "tool_name": tool_name,
                    "method": method.upper(),
                    "path": path,
                    "url": f"{base_url.rstrip('/')}{path}",
                    "operation_id": operation_id,
                    "summary": op.get("summary", ""),
                    "description": op.get("description", ""),
                    "tags": op.get("tags", []),
                    "parameters": params,
                    "request_schema": request_schema,
                }
            )

    return {
        "generated_from": f"{base_url.rstrip('/')}/openapi.json",
        "title": spec.get("info", {}).get("title"),
        "version": spec.get("info", {}).get("version"),
        "tool_count": len(tools),
        "tools": tools,
    }


def write_markdown(catalog: Dict[str, Any], path: Path) -> None:
    lines: List[str] = []
    lines.append("# Garage OpenAPI Tool Catalog")
    lines.append("")
    lines.append(f"Source: {catalog['generated_from']}")
    lines.append("")
    lines.append(f"Total tools: {catalog['tool_count']}")
    lines.append("")
    lines.append("| Tool Name | Method | Path | Tags |")
    lines.append("|---|---|---|---|")
    for tool in catalog["tools"]:
        tags = ", ".join(tool.get("tags", []))
        lines.append(f"| {tool['tool_name']} | {tool['method']} | {tool['path']} | {tags} |")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    base_url = os.getenv("GARAGE_BASE_URL", "http://127.0.0.1:8066")
    out_json = Path(os.getenv("MCP_CATALOG_OUT_JSON", "mcp/catalog/garage_openapi_catalog.json"))
    out_md = Path(os.getenv("MCP_CATALOG_OUT_MD", "mcp/catalog/garage_openapi_catalog.md"))

    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{base_url.rstrip('/')}/openapi.json")
        response.raise_for_status()
        spec = response.json()

    catalog = build_catalog(spec, base_url)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    write_markdown(catalog, out_md)

    print(f"Generated {out_json} and {out_md} ({catalog['tool_count']} tools)")


if __name__ == "__main__":
    main()
