"""Garage Prompt Engineer MCP server.

Exposes prompt lab capabilities as MCP tools.
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

# Ensure sibling module imports work in direct-run and dynamic loader contexts.
THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from common import GarageApiError, garage_request


mcp = FastMCP("garage-prompt")


@mcp.tool()
async def prompt_generate(
    model: str,
    user_input: str,
    system_prompt: str,
    vector_context: str = "",
    files_context: str = "",
    reference_prompts: str = "",
    quality_metrics: str = "",
    temperature: float = 0.7,
    max_tokens: int = 1000,
    assistant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a high-quality prompt from user needs and context."""
    payload: Dict[str, Any] = {
        "model": model,
        "user_input": user_input,
        "system_prompt": system_prompt,
        "vector_context": vector_context,
        "files_context": files_context,
        "reference_prompts": reference_prompts,
        "quality_metrics": quality_metrics,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "assistant_id": assistant_id,
    }
    try:
        return await garage_request("POST", "/v1/prompt-engineer/generate", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def prompt_analyze(user_input: str, model: str) -> Dict[str, Any]:
    """Analyze a prompt request and return structured needs."""
    payload = {"user_input": user_input, "model": model}
    try:
        return await garage_request("POST", "/v1/prompt-engineer/analyze", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def prompt_variations(prompt: str, model: str, count: int = 3) -> Dict[str, Any]:
    """Generate alternative versions of a prompt."""
    payload = {"prompt": prompt, "model": model, "count": count}
    try:
        return await garage_request("POST", "/v1/prompt-engineer/variations", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def prompt_optimize(prompt: str, model: str, metrics: Dict[str, int]) -> Dict[str, Any]:
    """Optimize a prompt against quality metrics."""
    payload = {"prompt": prompt, "model": model, "metrics": metrics}
    try:
        return await garage_request("POST", "/v1/prompt-engineer/optimize", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def prompt_evaluate(prompt: str, model: str) -> Dict[str, Any]:
    """Evaluate a prompt across clarity/specificity/structure/conciseness."""
    payload = {"prompt": prompt, "model": model}
    try:
        return await garage_request("POST", "/v1/prompt-engineer/evaluate", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def prompt_improve(prompt: str, model: str, metrics: Dict[str, int]) -> Dict[str, Any]:
    """Get improvement suggestions and an improved prompt version."""
    payload = {"prompt": prompt, "model": model, "metrics": metrics}
    try:
        return await garage_request("POST", "/v1/prompt-engineer/improve", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def prompt_examples(category: str = "general") -> Dict[str, Any]:
    """Fetch prompt examples by category."""
    try:
        return await garage_request("GET", "/v1/prompt-engineer/examples", params={"category": category})
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for remote connectivity tests."""
    return JSONResponse({"status": "ok", "service": "garage-prompt"})


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8113"))

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
