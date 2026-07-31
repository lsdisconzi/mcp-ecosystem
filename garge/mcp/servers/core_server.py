"""Garage Core MCP server.

Exposes assistant and knowledge operations through MCP tools.
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

# Ensure sibling module imports work in direct-run and dynamic loader contexts.
THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from common import GarageApiError, garage_multipart_request, garage_request


mcp = FastMCP("garage-core")


@mcp.tool()
async def garage_health() -> Dict[str, Any]:
    """Return Garage API health status."""
    try:
        return await garage_request("GET", "/health")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_list_models() -> Dict[str, Any]:
    """List available chat/completions models."""
    try:
        return await garage_request("GET", "/v1/models")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_chat_completions(
    messages: List[Dict[str, Any]],
    model: str = "lfm2.5:8b",
    temperature: float = 0.7,
    top_p: float = 1.0,
    max_tokens: int = 1000,
    stream: bool = False,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """OpenAI-compatible chat completions endpoint wrapper."""
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if provider is not None:
        payload["provider"] = provider
    if api_key is not None:
        payload["api_key"] = api_key
    if base_url is not None:
        payload["base_url"] = base_url
    try:
        return await garage_request("POST", "/v1/chat/completions", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_list_assistants() -> Dict[str, Any]:
    """List assistants registered in Garage."""
    try:
        return await garage_request("GET", "/v1/assistants/")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_list_files() -> Dict[str, Any]:
    """List files currently tracked by Garage."""
    try:
        return await garage_request("GET", "/v1/files")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_get_assistant(assistant_id: str) -> Dict[str, Any]:
    """Get a specific assistant by id."""
    try:
        return await garage_request("GET", f"/v1/assistants/{assistant_id}")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_update_assistant(
    assistant_id: str,
    updates: Dict[str, Any],
) -> Dict[str, Any]:
    """Partially update an assistant using PATCH."""
    try:
        return await garage_request("PATCH", f"/v1/assistants/{assistant_id}", json_body=updates)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_replace_assistant(
    assistant_id: str,
    assistant: Dict[str, Any],
) -> Dict[str, Any]:
    """Replace assistant fields using PUT."""
    try:
        return await garage_request("PUT", f"/v1/assistants/{assistant_id}", json_body=assistant)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_create_assistant(
    name: str,
    model: str = "gpt-oss:20b",
    description: Optional[str] = None,
    instructions: Optional[str] = None,
    language: str = "en",
    temperature: float = 0.7,
    top_p: float = 1.0,
    max_tokens: int = 500,
    collections: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a new assistant in Garage."""
    payload: Dict[str, Any] = {
        "name": name,
        "model": model,
        "description": description,
        "instructions": instructions,
        "language": language,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "collections": collections or [],
    }
    try:
        return await garage_request("POST", "/v1/assistants/", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_delete_assistant(assistant_id: str, confirm: bool = False) -> Dict[str, Any]:
    """Delete an assistant. Requires confirm=true to avoid accidental deletion."""
    if not confirm:
        return {"success": False, "error": "Set confirm=true to delete the assistant."}
    try:
        return await garage_request("DELETE", f"/v1/assistants/{assistant_id}")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_assistant_chat(
    assistant_id: str,
    user_message: str,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    """Send a single-message chat turn to an assistant."""
    payload: Dict[str, Any] = {
        "messages": [{"role": "user", "content": user_message}],
    }
    if model is not None:
        payload["model"] = model
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    try:
        return await garage_request("POST", f"/v1/assistants/{assistant_id}/chat", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_attach_file_to_assistant(assistant_id: str, file_id: str) -> Dict[str, Any]:
    """Attach a file id to an assistant."""
    try:
        return await garage_request(
            "POST",
            f"/v1/assistants/{assistant_id}/files",
            json_body={"file_id": file_id},
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_list_assistant_files(assistant_id: str) -> Dict[str, Any]:
    """List file ids currently attached to an assistant."""
    try:
        return await garage_request("GET", f"/v1/assistants/{assistant_id}/files")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_detach_file_from_assistant(assistant_id: str, file_id: str) -> Dict[str, Any]:
    """Detach a file id from an assistant."""
    try:
        return await garage_request("DELETE", f"/v1/assistants/{assistant_id}/files/{file_id}")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_query_assistant_knowledge(
    assistant_id: str,
    query: str,
    limit: int = 5,
) -> Dict[str, Any]:
    """Query the collections configured for a specific assistant."""
    try:
        return await garage_request(
            "POST",
            f"/v1/assistants/{assistant_id}/query-knowledge",
            json_body={"query": query, "limit": limit},
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_assign_tool_to_assistant(assistant_id: str, tool_id: str) -> Dict[str, Any]:
    """Assign an existing tool to an assistant."""
    try:
        return await garage_request(
            "POST",
            f"/v1/assistants/{assistant_id}/tools",
            json_body={"tool_id": tool_id},
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_assistant_deepseek(assistant_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Call assistant-scoped deepseek proxy."""
    try:
        return await garage_request("POST", f"/v1/assistants/{assistant_id}/deepseek", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_deepseek_engineer_chat(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Call deepseek engineer chat endpoint."""
    try:
        return await garage_request("POST", "/v1/deepseek-engineer/chat", json_body={"messages": messages})
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_deepseek_stream_proxy(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Call deepseek stream proxy endpoint (supports stream=true payloads)."""
    try:
        return await garage_request("POST", "/v1/assistants/deepseek-stream-proxy", json_body=payload, timeout_seconds=600.0)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_query_knowledge(
    query: str,
    collection_name: str,
    limit: int = 5,
    score_threshold: float = 0.0,
    assistant_id: Optional[str] = None,
    metadata_filter: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Query Garage knowledge collections."""
    payload: Dict[str, Any] = {
        "query": query,
        "collection_name": collection_name,
        "limit": limit,
        "score_threshold": score_threshold,
    }
    if assistant_id is not None:
        payload["assistant_id"] = assistant_id
    if metadata_filter is not None:
        payload["filter"] = metadata_filter

    try:
        return await garage_request("POST", "/v1/knowledge/query", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_query_assistant_knowledge_collections(
    assistant_id: str,
    query: str,
    limit: int = 5,
    score_threshold: float = 0.7,
    metadata_filter: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Query knowledge across all collections configured for an assistant."""
    payload: Dict[str, Any] = {
        "query": query,
        "limit": limit,
        "score_threshold": score_threshold,
    }
    if metadata_filter is not None:
        payload["filter"] = metadata_filter
    try:
        return await garage_request("POST", f"/v1/knowledge/assistant/{assistant_id}/query", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_ingest_knowledge_text(
    collection_name: str,
    text: str,
    metadata: Optional[Dict[str, Any]] = None,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> Dict[str, Any]:
    """Ingest plain text into a knowledge collection."""
    payload: Dict[str, Any] = {
        "collection_name": collection_name,
        "text": text,
        "metadata": metadata or {},
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
    }
    try:
        return await garage_request("POST", "/v1/knowledge/ingest/text", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_ingest_knowledge_file(collection_name: str, file_path: str) -> Dict[str, Any]:
    """Ingest a local file into a knowledge collection."""
    try:
        return await garage_multipart_request(
            "POST",
            "/v1/knowledge/ingest/file",
            file_field="file",
            file_path=file_path,
            form_fields={"collection_name": collection_name},
            timeout_seconds=300.0,
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_clear_knowledge_collection(collection_name: str, confirm: bool = False) -> Dict[str, Any]:
    """Clear and recreate a knowledge collection. Requires confirm=true."""
    if not confirm:
        return {"success": False, "error": "Set confirm=true to clear the collection."}
    try:
        return await garage_request("DELETE", f"/v1/knowledge/collection/{collection_name}/clear")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_get_knowledge_collection_stats(collection_name: str) -> Dict[str, Any]:
    """Get knowledge collection stats."""
    try:
        return await garage_request("GET", f"/v1/knowledge/collection/{collection_name}/stats")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_list_tools() -> Dict[str, Any]:
    """List tool definitions in the tool registry."""
    try:
        return await garage_request("GET", "/v1/tools")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_get_tool(tool_name: str) -> Dict[str, Any]:
    """Get a single tool definition by name."""
    try:
        return await garage_request("GET", f"/v1/tools/{tool_name}")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_delete_tool(tool_name: str, confirm: bool = False) -> Dict[str, Any]:
    """Delete a user-defined tool. Requires confirm=true."""
    if not confirm:
        return {"success": False, "error": "Set confirm=true to delete the tool."}
    try:
        return await garage_request("DELETE", f"/v1/tools/{tool_name}")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_execute_tool(tool_name: str, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Execute a specific tool by path parameter name."""
    try:
        return await garage_request(
            "POST",
            f"/v1/tools/{tool_name}/execute",
            json_body={"parameters": parameters or {}},
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_execute_tool_by_name(tool_name: str, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Execute a tool using tool_name inside the request body."""
    try:
        return await garage_request(
            "POST",
            "/v1/tools/execute",
            json_body={"tool_name": tool_name, "parameters": parameters or {}},
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_create_tool(tool_function: Dict[str, Any]) -> Dict[str, Any]:
    """Create a user-defined tool."""
    try:
        return await garage_request(
            "POST",
            "/v1/tools",
            json_body={"type": "function", "function": tool_function},
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_deep_reasoning(
    question: str,
    max_steps: int = 3,
    use_knowledge_graph: bool = True,
    verify_with_files: bool = True,
    files: Optional[List[str]] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute the deep reasoning tool endpoint."""
    payload: Dict[str, Any] = {
        "question": question,
        "max_steps": max_steps,
        "use_knowledge_graph": use_knowledge_graph,
        "verify_with_files": verify_with_files,
        "files": files or [],
        "model": model,
    }
    try:
        return await garage_request("POST", "/v1/tools/deep_reasoning", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_create_thread(metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create a new thread."""
    try:
        return await garage_request("POST", "/v1/threads/", json_body={"metadata": metadata or {}})
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_list_threads() -> Dict[str, Any]:
    """List all thread resources."""
    try:
        return await garage_request("GET", "/v1/threads/")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_get_thread(thread_id: str) -> Dict[str, Any]:
    """Get one thread by id."""
    try:
        return await garage_request("GET", f"/v1/threads/{thread_id}")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_delete_thread(thread_id: str, confirm: bool = False) -> Dict[str, Any]:
    """Delete a thread and its messages. Requires confirm=true."""
    if not confirm:
        return {"success": False, "error": "Set confirm=true to delete the thread."}
    try:
        return await garage_request("DELETE", f"/v1/threads/{thread_id}")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_add_thread_message(
    thread_id: str,
    content: str,
    role: str = "user",
    file_ids: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Add a message to a thread."""
    payload: Dict[str, Any] = {
        "role": role,
        "content": content,
        "file_ids": file_ids or [],
        "metadata": metadata or {},
    }
    try:
        return await garage_request("POST", f"/v1/threads/{thread_id}/messages", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_list_thread_messages(thread_id: str, limit: int = 20) -> Dict[str, Any]:
    """List messages in a thread."""
    try:
        return await garage_request("GET", f"/v1/threads/{thread_id}/messages", params={"limit": limit})
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_create_thread_run(
    thread_id: str,
    assistant_id: Optional[str] = None,
    model: Optional[str] = None,
    instructions: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run assistant inference over a thread's messages."""
    payload: Dict[str, Any] = {
        "assistant_id": assistant_id,
        "model": model,
        "instructions": instructions,
        "metadata": metadata or {},
    }
    try:
        return await garage_request("POST", f"/v1/threads/{thread_id}/runs", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def garage_attach_file_to_thread(thread_id: str, file_id: str) -> Dict[str, Any]:
    """Attach a file to a thread."""
    try:
        return await garage_request("POST", f"/v1/threads/{thread_id}/files", json_body={"file_id": file_id})
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for remote connectivity tests."""
    return JSONResponse({"status": "ok", "service": "garage-core"})


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8110"))

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
