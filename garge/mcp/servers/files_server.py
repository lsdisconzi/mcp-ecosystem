"""Garage Files MCP server.

Exposes file read/list/upload workflows as MCP tools.
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

# Ensure sibling module imports work in direct-run and dynamic loader contexts.
THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from common import GarageApiError, garage_multipart_request, garage_raw_request, garage_request


mcp = FastMCP("garage-files")


@mcp.tool()
async def files_list(path: str) -> Dict[str, Any]:
    """List files in a server-side directory path."""
    try:
        data = await garage_request("GET", "/v1/files/list", params={"path": path})
        if isinstance(data, dict):
            return data
        return {"files": data}
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def files_read(path: str) -> Dict[str, Any]:
    """Read text/json/pdf/binary contents from a server-side file path."""
    try:
        return await garage_request("GET", "/v1/files/read", params={"path": path}, timeout_seconds=300.0)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def files_summarize(
    file_ids: list[str],
    model: str = "llama3.1:8b",
    temperature: float = 0.1,
    max_tokens: int = 1000,
) -> Dict[str, Any]:
    """Summarize one or more uploaded files."""
    payload: Dict[str, Any] = {
        "file_ids": file_ids,
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        return await garage_request("POST", "/v1/files/summarize", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def files_upload(file_path: str, purpose: str = "assistants") -> Dict[str, Any]:
    """Upload a local file to Garage file storage."""
    try:
        return await garage_multipart_request(
            "POST",
            "/v1/files",
            file_field="file",
            file_path=file_path,
            form_fields={"purpose": purpose},
            timeout_seconds=300.0,
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def files_upload_transcript(file_path: str) -> Dict[str, Any]:
    """Upload a local transcript file to Garage evidence storage."""
    try:
        return await garage_multipart_request(
            "POST",
            "/v1/files/upload/transcript",
            file_field="file",
            file_path=file_path,
            timeout_seconds=300.0,
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def files_upload_law(file_path: str) -> Dict[str, Any]:
    """Upload a local law/regulation file to Garage law storage."""
    try:
        return await garage_multipart_request(
            "POST",
            "/v1/files/upload/law",
            file_field="file",
            file_path=file_path,
            timeout_seconds=300.0,
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def files_get_content(file_id: str) -> Dict[str, Any]:
    """Fetch raw file content by id. Binary payloads are returned as base64."""
    try:
        return await garage_raw_request("GET", f"/v1/files/{file_id}/content", timeout_seconds=300.0)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def files_delete(file_id: str, confirm: bool = False) -> Dict[str, Any]:
    """Delete an uploaded file record and content. Requires confirm=true."""
    if not confirm:
        return {
            "success": False,
            "error": "Set confirm=true to delete the file.",
        }
    try:
        return await garage_request("DELETE", f"/v1/files/{file_id}")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def files_list_transcripts() -> Dict[str, Any]:
    """List transcript files in Garage evidence storage."""
    try:
        data = await garage_request("GET", "/v1/files/transcripts")
        if isinstance(data, dict):
            return data
        return {"files": data}
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def files_list_laws() -> Dict[str, Any]:
    """List law files in Garage law storage."""
    try:
        data = await garage_request("GET", "/v1/files/laws")
        if isinstance(data, dict):
            return data
        return {"files": data}
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for remote connectivity tests."""
    return JSONResponse({"status": "ok", "service": "garage-files"})


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8111"))

    if transport == "stdio":
        mcp.run()
        sys.exit(0)

    if transport not in {"sse", "streamable-http"}:
        print(f"Unsupported MCP_TRANSPORT '{transport}'. Use: stdio, sse, streamable-http", file=sys.stderr)
        sys.exit(1)

    if hasattr(mcp, "settings"):
        if hasattr(mcp.settings, "host"):
            mcp.settings.host = host
        if hasattr(mcp.settings, "port"):
            mcp.settings.port = port

    try:
        mcp.run(transport=transport, host=host, port=port)
    except TypeError:
        mcp.run(transport=transport)
