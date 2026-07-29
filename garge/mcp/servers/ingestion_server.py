"""Garage Ingestion MCP server.

Exposes ingestion and retrieval workflows for legal and transcript corpora.
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


mcp = FastMCP("garage-ingestion")


@mcp.tool()
async def ingestion_collection_info(collection_name: str) -> Dict[str, Any]:
    """Get collection info from the ingestion pipeline endpoints."""
    try:
        return await garage_request("GET", f"/v1/ingestion/collections/{collection_name}/info")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def ingestion_search(collection_name: str, query: str, limit: int = 10) -> Dict[str, Any]:
    """Search documents via the ingestion search endpoint."""
    params = {
        "collection_name": collection_name,
        "query": query,
        "limit": limit,
    }
    try:
        return await garage_request("POST", "/v1/ingestion/search", params=params)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def ingestion_ingest_directory(
    directory_path: str,
    collection_name: str,
    force_recreate: bool = False,
    exclude_dirs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Start directory ingestion through the v1 ingestion pipeline."""
    params: Dict[str, Any] = {
        "directory_path": directory_path,
        "collection_name": collection_name,
        "force_recreate": force_recreate,
    }
    if exclude_dirs:
        params["exclude_dirs"] = exclude_dirs
    try:
        return await garage_request("POST", "/v1/ingestion/ingest-directory", params=params, timeout_seconds=900.0)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def ingestion_ingest_file(
    file_path: str,
    collection_name: str = "default_collection",
    force_recreate: bool = False,
) -> Dict[str, Any]:
    """Ingest a local file using /v1/ingestion/ingest-file multipart endpoint."""
    params: Dict[str, Any] = {
        "collection_name": collection_name,
        "force_recreate": force_recreate,
    }
    try:
        return await garage_multipart_request(
            "POST",
            "/v1/ingestion/ingest-file",
            file_field="file",
            file_path=file_path,
            params=params,
            timeout_seconds=1200.0,
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def ingestion_ingest_legal_file(
    file_path: str,
    collection_name: str = "legal_documents",
    force_recreate: bool = False,
    model_name: Optional[str] = None,
    metadata_json: Optional[str] = None,
    enhanced: bool = True,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> Dict[str, Any]:
    """Ingest one legal file using /v1/ingestion/ingest-legal-file multipart endpoint."""
    params: Dict[str, Any] = {
        "collection_name": collection_name,
        "force_recreate": force_recreate,
        "enhanced": enhanced,
    }
    if model_name is not None:
        params["model_name"] = model_name
    if metadata_json is not None:
        params["metadata_json"] = metadata_json
    if chunk_size is not None:
        params["chunk_size"] = chunk_size
    if chunk_overlap is not None:
        params["chunk_overlap"] = chunk_overlap
    try:
        return await garage_multipart_request(
            "POST",
            "/v1/ingestion/ingest-legal-file",
            file_field="file",
            file_path=file_path,
            params=params,
            timeout_seconds=1200.0,
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def ingestion_analyze_document_structure(file_path: str) -> Dict[str, Any]:
    """Analyze document structure via v1 ingestion endpoint."""
    try:
        return await garage_multipart_request(
            "POST",
            "/v1/ingestion/analyze-document-structure",
            file_field="file",
            file_path=file_path,
            timeout_seconds=300.0,
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def legal_search(
    collection_name: str,
    query: str,
    limit: int = 10,
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Search a legal ingestion collection."""
    payload: Dict[str, Any] = {
        "query": query,
        "limit": limit,
    }
    if filters:
        payload["filters"] = filters

    try:
        return await garage_request("POST", f"/legal-ingestion/search/{collection_name}", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def legal_list_collections() -> Dict[str, Any]:
    """List legal ingestion collections."""
    try:
        return await garage_request("GET", "/legal-ingestion/collections")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def legal_collection_info(collection_name: str) -> Dict[str, Any]:
    """Get legal ingestion collection details."""
    try:
        return await garage_request("GET", f"/legal-ingestion/collection/{collection_name}/info")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def legal_delete_collection(collection_name: str, confirm: bool = False) -> Dict[str, Any]:
    """Delete a legal-ingestion collection. Requires confirm=true."""
    if not confirm:
        return {"success": False, "error": "Set confirm=true to delete the collection."}
    try:
        return await garage_request("DELETE", f"/legal-ingestion/collection/{collection_name}")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def legal_upload_csv(
    file_path: str,
    collection_name: str,
    text_column: str = "texto",
    recreate_collection: bool = False,
    chunk_size: int = 800,
    chunk_overlap: int = 100,
    async_mode: bool = False,
) -> Dict[str, Any]:
    """Upload and ingest CSV using the legal-ingestion upload endpoint."""
    params: Dict[str, Any] = {
        "collection_name": collection_name,
        "text_column": text_column,
        "recreate_collection": recreate_collection,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "async_mode": async_mode,
    }
    try:
        return await garage_multipart_request(
            "POST",
            "/legal-ingestion/upload-csv",
            file_field="file",
            file_path=file_path,
            params=params,
            timeout_seconds=1200.0,
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def legal_ingest_file(
    file_path: str,
    collection_name: str,
    text_column: str = "texto",
    recreate_collection: bool = False,
    chunk_size: int = 800,
    chunk_overlap: int = 100,
    metadata_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Ingest legal CSV from server-side path into Qdrant."""
    params = {"file_path": file_path}
    payload: Dict[str, Any] = {
        "collection_name": collection_name,
        "text_column": text_column,
        "recreate_collection": recreate_collection,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "metadata_columns": metadata_columns,
    }

    try:
        return await garage_request("POST", "/legal-ingestion/ingest-file", params=params, json_body=payload, timeout_seconds=900.0)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def legal_v2_ingest_enhanced_file(
    file_path: str,
    collection_name: str = "legal_documents",
    force_recreate: bool = False,
    model_name: Optional[str] = None,
    metadata_json: Optional[str] = None,
    preserve_sections: bool = True,
    enhanced: bool = True,
    chunk_size: int = 1500,
    chunk_overlap: int = 150,
) -> Dict[str, Any]:
    """Ingest a legal file through the v2 enhanced ingestion endpoint."""
    form_fields: Dict[str, Any] = {
        "collection_name": collection_name,
        "force_recreate": "true" if force_recreate else "false",
        "preserve_sections": "true" if preserve_sections else "false",
        "enhanced": "true" if enhanced else "false",
        "chunk_size": str(chunk_size),
        "chunk_overlap": str(chunk_overlap),
    }
    if model_name is not None:
        form_fields["model_name"] = model_name
    if metadata_json is not None:
        form_fields["metadata_json"] = metadata_json

    try:
        return await garage_multipart_request(
            "POST",
            "/v2/legal-ingestion/ingest-legal-file-enhanced",
            file_field="files",
            file_path=file_path,
            form_fields=form_fields,
            timeout_seconds=1200.0,
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def legal_v2_ingest_folder(
    folder_path: str,
    collection_name: str = "legal_documents",
    force_recreate: bool = False,
    model_name: Optional[str] = None,
    metadata_json: Optional[str] = None,
    preserve_sections: bool = True,
    enhanced: bool = True,
    chunk_size: int = 1500,
    chunk_overlap: int = 150,
    recursive: bool = False,
) -> Dict[str, Any]:
    """Ingest legal documents from a local folder via v2 endpoint."""
    payload: Dict[str, Any] = {
        "folder_path": folder_path,
        "collection_name": collection_name,
        "force_recreate": force_recreate,
        "model_name": model_name,
        "metadata_json": metadata_json,
        "preserve_sections": preserve_sections,
        "enhanced": enhanced,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "recursive": recursive,
    }
    try:
        return await garage_request("POST", "/v2/legal-ingestion/ingest-legal-folder", json_body=payload, timeout_seconds=1200.0)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def legal_v2_analyze_document_structure(file_path: str) -> Dict[str, Any]:
    """Analyze legal document structure through v2 endpoint."""
    try:
        return await garage_multipart_request(
            "POST",
            "/v2/legal-ingestion/analyze-document-structure",
            file_field="file",
            file_path=file_path,
            timeout_seconds=300.0,
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def transcript_ingest_json(
    transcript: Dict[str, Any],
    collection_name: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
    preserve_speaker_turns: bool = True,
    force_recreate: bool = False,
    model_name: Optional[str] = None,
    metadata_json: Optional[str] = None,
) -> Dict[str, Any]:
    """Ingest transcript JSON payload using enhanced transcript pipeline."""
    params: Dict[str, Any] = {
        "collection_name": collection_name,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "preserve_speaker_turns": preserve_speaker_turns,
        "force_recreate": force_recreate,
    }
    if model_name is not None:
        params["model_name"] = model_name
    if metadata_json is not None:
        params["metadata_json"] = metadata_json

    try:
        return await garage_request("POST", "/v2/transcripts/ingest-json", params=params, json_body=transcript, timeout_seconds=900.0)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def transcript_analyze_file(file_path: str) -> Dict[str, Any]:
    """Analyze transcript JSON structure from a local file path."""
    try:
        return await garage_multipart_request(
            "POST",
            "/v2/transcripts/analyze",
            file_field="file",
            file_path=file_path,
            timeout_seconds=300.0,
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def transcript_ingest_enhanced_file(
    file_path: str,
    collection_name: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
    preserve_speaker_turns: bool = True,
    force_recreate: bool = False,
    model_name: Optional[str] = None,
    metadata_json: Optional[str] = None,
) -> Dict[str, Any]:
    """Ingest transcript from a local file path using enhanced speaker-aware pipeline."""
    form_fields: Dict[str, Any] = {
        "collection_name": collection_name,
        "chunk_size": str(chunk_size),
        "chunk_overlap": str(chunk_overlap),
        "preserve_speaker_turns": "true" if preserve_speaker_turns else "false",
        "force_recreate": "true" if force_recreate else "false",
    }
    if model_name is not None:
        form_fields["model_name"] = model_name
    if metadata_json is not None:
        form_fields["metadata_json"] = metadata_json

    try:
        return await garage_multipart_request(
            "POST",
            "/v2/transcripts/ingest-enhanced",
            file_field="file",
            file_path=file_path,
            form_fields=form_fields,
            timeout_seconds=1200.0,
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for remote connectivity tests."""
    return JSONResponse({"status": "ok", "service": "garage-ingestion"})


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8112"))

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
