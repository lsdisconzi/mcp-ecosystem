#!/usr/bin/env python3
"""Dynamic MCP server that reads OpenAPI spec and exposes all endpoints as tools.

This server dynamically reads the OpenAPI specification, generates MCP tools for
all endpoints, and handles file uploads by accepting base64-encoded file content
from the MCP client (since MCP tools typically exchange JSON, not multipart/form-data).
"""

from __future__ import annotations

import json
import base64
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, get_args, get_type_hints

import torch
import torchaudio
from fastapi import FastAPI, File, UploadFile, Form, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import torchaudio.functional as F
import torchaudio.transforms as T
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse


# ──────────────────────────────────────────────
# OpenAPI spec path
# ──────────────────────────────────────────────
SPEC_PATH = Path(__file__).parent / "openapi.json"

# Base URL of the audio webapp API this server proxies to.
# Overridable via env (start.sh exports APP_URL).
AUDIO_API_BASE = os.getenv("AUDIO_API_BASE", "http://127.0.0.1:8777").rstrip("/")
with open(SPEC_PATH, "r") as f:
    OPENAPI: Dict[str, Any] = json.load(f)


# ──────────────────────────────────────────────
# In-memory session storage for processed audio
# ──────────────────────────────────────────────
sessions: dict[str, dict] = {}


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _as_abs_path(path: str) -> Path:
    return Path(path).expanduser().resolve()


def _load_upload(file_content: bytes) -> tuple[torch.Tensor, int]:
    """Load waveform from raw file bytes."""
    import io
    waveform, sample_rate = torchaudio.load(io.BytesIO(file_content))
    return waveform, sample_rate


def _tensor_to_wav_bytes(waveform: torch.Tensor, sample_rate: int) -> bytes:
    """Convert a waveform tensor to WAV bytes."""
    waveform = waveform.cpu().detach()
    if waveform.dim() == 1:
        waveform = waveform.unsqueeze(0)
    buf = io.BytesIO()
    try:
        torchaudio.save(buf, waveform, sample_rate, format="wav", channels_first=True)
        buf.seek(0)
        return buf.read()
    except Exception:
        pass
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        torchaudio.save(tmp_path, waveform, sample_rate, format="wav", channels_first=True)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _tensor_to_b64(waveform: torch.Tensor, sample_rate: int) -> str:
    """Convert waveform tensor to base64-encoded WAV."""
    wav_bytes = _tensor_to_wav_bytes(waveform, sample_rate)
    return base64.b64encode(wav_bytes).decode("utf-8")


# ──────────────────────────────────────────────
# OpenAPI schema helpers
# ──────────────────────────────────────────────

def _get_request_body_schema(path_item: Dict[str, Any], method: str) -> Optional[Dict[str, Any]]:
    """Extract requestBody schema from a path item for a given method."""
    operation = path_item.get(method, {})
    return operation.get("requestBody", {}).get("content", {}).get("multipart/form-data", {}).get("schema")


def _get_response_schema(path_item: Dict[str, Any], method: str) -> Optional[Dict[str, Any]]:
    """Extract response schema from a path item for a given method."""
    operation = path_item.get(method, {})
    return operation.get("responses", {}).get("200", {}).get("content", {}).get("application/json", {}).get("schema")


def _get_path_params(path_item: Dict[str, Any], method: str) -> List[Dict[str, Any]]:
    """Extract path parameters from a path item for a given method."""
    operation = path_item.get(method, {})
    params = operation.get("parameters", [])
    return [p for p in params if p.get("in") == "path"]


def _get_query_params(path_item: Dict[str, Any], method: str) -> List[Dict[str, Any]]:
    """Extract query parameters from a path item for a given method."""
    operation = path_item.get(method, {})
    params = operation.get("parameters", [])
    return [p for p in params if p.get("in") == "query"]


# ──────────────────────────────────────────────
# Dynamic tool generation
# ──────────────────────────────────────────────

def _generate_tools_from_spec():
    """Generate MCP tools from the OpenAPI specification."""
    mcp = FastMCP("torchaudio-full")

    # Route health check first
    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request: Request) -> JSONResponse:
        return JSONResponse({
            "status": "ok",
            "service": "torchaudio-full",
            "torch": torch.__version__,
            "torchaudio": torchaudio.__version__,
        })

    # Process each path in the OpenAPI spec
    for path, path_item in OPENAPI.get("paths", {}).items():
        for method_str, operation in path_item.items():
            method_lower = method_str.lower()
            if method_lower not in ("get", "post"):
                continue

            operation_id = operation.get("operationId", "")
            summary = operation.get("summary", "")
            description = operation.get("description", f"{method_str} {path}")

            # Handle path parameters
            path_params = _get_path_params(path_item, method_str)
            query_params = _get_query_params(path_item, method_str)

            # Build the function signature based on parameters
            func_args: Dict[str, Any] = {}
            arg_descriptions: Dict[str, str] = {}

            # Process path parameters
            for pp in path_params:
                name = pp["name"]
                # Extract from path: /api/audio/{session_id} -> session_id
                # Remove braces from path to get the pattern
                pattern = path
                # Check if this is a path param by looking for {name} in path
                if f"{{{name}}}" in pattern:
                    func_args[name] = Any
                    arg_descriptions[name] = pp.get("description", f"Path parameter: {name}")

            # Process query parameters
            for qp in query_params:
                name = qp["name"]
                if name not in func_args:
                    default = qp.get("default", "")
                    if default:
                        func_args[name] = default
                    else:
                        func_args[name] = Any
                    arg_descriptions[name] = qp.get("description", f"Query parameter: {name}")

            # Process request body parameters (form data)
            body_schema = _get_request_body_schema(path_item, method_str)
            body_params: Dict[str, str] = {}
            if body_schema and body_schema.get("properties"):
                for pname, pschema in body_schema["properties"].items():
                    if pname == "file":
                        # File parameter - will be handled via base64
                        body_params[pname] = "file_base64"
                        arg_descriptions[pname] = "Base64-encoded audio file content"
                    else:
                        # Regular form parameter
                        ptype = pschema.get("type", "string")
                        default = pschema.get("default", "")
                        if default:
                            body_params[pname] = default
                        else:
                            body_params[pname] = Any
                        arg_descriptions[pname] = pschema.get("description", f"Form parameter: {pname}")

            # Determine if this endpoint has a file upload
            has_file = "file_base64" in str(body_params) or any(
                pname == "file" for pname in body_params
            )

            # Create the tool function
            def make_tool_fn(
                method: str,
                path: str,
                body_param_names: Dict[str, str],
                has_file: bool,
                operation_id: str,
                summary: str,
                description: str,
            ):
                """Create a tool function for an API endpoint."""

                if method == "get":
                    # For GET endpoints
                    deps = list(body_param_names.values()) + list(func_args.keys())
                    deps_str = ", ".join(deps) if deps else ""

                    @mcp.tool(name=operation_id)
                    def make_fn(**kwargs: Any) -> Dict[str, Any]:
                        # Build query parameters
                        params: Dict[str, Any] = {}
                        for key, val in kwargs.items():
                            if key in body_param_names.values():
                                # This is a file parameter - skip for GET
                                continue
                            params[key] = val

                        # Make HTTP request
                        import httpx
                        url = f"{AUDIO_API_BASE}{path}"
                        try:
                            resp = httpx.get(url, params=params, timeout=60.0)
                            resp.raise_for_status()
                            return resp.json()
                        except Exception as e:
                            return {"error": str(e)}

                    make_fn.__name__ = operation_id
                    make_fn.__doc__ = f"{summary}: {description}"
                    return make_fn

                else:  # POST
                    # For POST endpoints with possible file upload
                    # Build the list of non-file arguments
                    non_file_args = [k for k in func_args.keys() if k != "file_base64"]
                    file_arg = "file_base64" if has_file else None

                    @mcp.tool(name=operation_id)
                    def make_fn(
                        file_base64: str = None,
                        **kwargs: Any,
                    ) -> Dict[str, Any]:
                        """Call the {operation_id} endpoint."""
                        import httpx
                        import io

                        # Decode base64 file if provided
                        file_bytes = None
                        if file_base64:
                            try:
                                file_bytes = base64.b64decode(file_base64)
                            except Exception:
                                return {"error": "Invalid base64 file content"}

                        # Build form data for HTTP request
                        form_data: Dict[str, Any] = {}

                        # Add non-file kwargs
                        for key, val in kwargs.items():
                            if key != "file_base64":
                                form_data[key] = val

                        # Add file if present
                        if file_bytes is not None:
                            # For multipart, we need to add the file
                            # FastAPI expects 'file' as form field with binary content
                            form_data["file"] = (io.BytesIO(file_bytes), "audio.wav")

                        # Build URL
                        url = f"{AUDIO_API_BASE}{path}"

                        try:
                            resp = httpx.post(url, form=form_data, timeout=120.0)
                            resp.raise_for_status()
                            return resp.json()
                        except Exception as e:
                            return {"error": str(e)}

                    make_fn.__name__ = operation_id
                    make_fn.__doc__ = f"{summary}: {description}"
                    return make_fn

            # Generate the tool
            tool_fn = make_tool_fn(
                method_lower,
                path,
                body_params,
                has_file,
                operation_id,
                summary,
                description,
            )

            # Register the tool with proper name and doc
            tool_name = operation_id.replace("/", "_").replace("-", "_")
            setattr(mcp, operation_id, tool_fn)

    return mcp


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main() -> None:
    """Start the dynamic MCP server."""
    mcp = _generate_tools_from_spec()

    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8765"))

    if transport == "stdio":
        mcp.run()
        return

    if transport not in {"sse", "streamable-http"}:
        raise ValueError(
            "Unsupported MCP_TRANSPORT. Use one of: stdio, sse, streamable-http"
        )

    # Newer FastMCP versions take host/port from settings, while older ones
    # accept host/port directly in run(). Support both signatures.
    if hasattr(mcp, "settings"):
        if hasattr(mcp.settings, "host"):
            mcp.settings.host = host
        if hasattr(mcp.settings, "port"):
            mcp.settings.port = port

    # Add status endpoint that upstream can consume
    @mcp.custom_route("/status", methods=["GET"])
    async def mcp_status(request: Request) -> JSONResponse:
        """Return status of the MCP service including tool count and health."""
        import httpx
        # Check if the underlying webapp is running
        try:
            resp = httpx.get("http://localhost:8000/health", timeout=2.0)
            webapp_health = resp.json().get("status", "unknown")
        except Exception:
            webapp_health = "unknown"

        # Count registered tools
        tool_names = [t for t in dir(mcp) if not t.startswith('_')]
        our_tools = [t for t in tool_names if t not in [
            'add_prompt', 'add_resource', 'add_tool', 'call_tool', 'completion',
            'custom_route', 'dependencies', 'get_context', 'get_prompt', 'icons',
            'instructions', 'list_prompts', 'list_resource_templates', 'list_resources',
            'list_tools', 'name', 'prompt', 'read_resource', 'remove_tool', 'resource',
            'run', 'run_sse_async', 'run_stdio_async', 'run_streamable_http_async',
            'session_manager', 'settings', 'sse_app', 'streamable_http_app', 'tool',
            'website_url'
        ]]

        return JSONResponse({
            "status": "healthy" if webapp_health == "ok" else "degraded",
            "service": "torchaudio-full-mcp",
            "transport": transport,
            "tool_count": len(our_tools),
            "total_specified_routes": len(OPENAPI.get("paths", {})),
            "version": "1.0.0",
            "endpoints": list(OPENAPI.get("paths", {}).keys())
        })

    try:
        mcp.run(transport=transport, host=host, port=port)
    except TypeError as exc:
        message = str(exc)
        if "unexpected keyword argument" in message and (
            "host" in message or "port" in message
        ):
            mcp.run(transport=transport)
            return
        raise


if __name__ == "__main__":
    main()