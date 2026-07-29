"""Garage Qdrant MCP server.

Exposes a focused set of Qdrant operations through MCP tools so LLM clients
can manage and query Garage collections over stdio transport.
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


mcp = FastMCP("garage-qdrant")

# --- Allowed base directories for security validation ---
_GARAGE_ROOT = Path("/home/garge").resolve()
ALLOWED_BASE_DIRS = [
    _GARAGE_ROOT,
    _GARAGE_ROOT / "data",
    _GARAGE_ROOT / "static",
]
# Also resolve upload dir from env if set
_upload_dir_env = os.getenv("UPLOAD_DIR", "")
if _upload_dir_env:
    _upload_path = Path(_upload_dir_env)
    if _upload_path.is_absolute():
        ALLOWED_BASE_DIRS.append(_upload_path.resolve())
    else:
        ALLOWED_BASE_DIRS.append((_GARAGE_ROOT / _upload_path).resolve())


def _validate_directory_path(directory_path: str) -> Path:
    """Validate that directory_path is within an allowed base directory tree.

    Raises GarageApiError if the path is outside the allowed tree.
    Returns the resolved Path if valid.
    """
    resolved = Path(directory_path).resolve()
    allowed = False
    for base in ALLOWED_BASE_DIRS:
        try:
            resolved.relative_to(base)
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        raise GarageApiError(
            f"Access denied: directory path '{directory_path}' is outside "
            f"allowed directories: {[str(d) for d in ALLOWED_BASE_DIRS]}"
        )
    if not resolved.exists():
        raise GarageApiError(f"Directory does not exist: {directory_path}")
    if not resolved.is_dir():
        raise GarageApiError(f"Path is not a directory: {directory_path}")
    return resolved


@mcp.tool()
async def qdrant_connect() -> Dict[str, Any]:
    """Check connectivity between Garage and the configured Qdrant instance."""
    try:
        return await garage_request("POST", "/v1/qdrant/connect")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def qdrant_list_collections() -> Dict[str, Any]:
    """List all available collections with vector metadata."""
    try:
        return await garage_request("GET", "/v1/qdrant/collections")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def qdrant_create_collection(
    name: str,
    vector_size: int,
    distance_metric: str = "cosine",
) -> Dict[str, Any]:
    """Create or recreate a collection with a specific vector size and metric."""
    try:
        payload = {
            "name": name,
            "vector_size": vector_size,
            "distance_metric": distance_metric,
        }
        return await garage_request("POST", "/v1/qdrant/collections", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def qdrant_collection_summary(collection_name: str) -> Dict[str, Any]:
    """Return points count and document type breakdown for a collection."""
    path = f"/v1/qdrant/collections/{collection_name}/summary"
    try:
        return await garage_request("GET", path)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def qdrant_search(
    collection_name: str,
    query_text: str,
    limit: int = 10,
    min_score: float = 0.0,
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run semantic search over a collection using Garage embeddings."""
    payload: Dict[str, Any] = {
        "collection_name": collection_name,
        "query_text": query_text,
        "limit": limit,
        "min_score": min_score,
    }
    if filters:
        payload["filters"] = filters

    try:
        return await garage_request("POST", "/v1/qdrant/search", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def qdrant_structured_ingest(
    collection_name: str,
    data_type: str,
    items: list[Dict[str, Any]],
) -> Dict[str, Any]:
    """Ingest structured transcript/violation/law/generic payloads."""
    payload: Dict[str, Any] = {
        "collection_name": collection_name,
        "data_type": data_type,
        "items": items,
    }
    try:
        return await garage_request("POST", "/v1/qdrant/collections/structured_ingest", json_body=payload, timeout_seconds=600.0)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def qdrant_ensure_legal_indexes(collection_name: str) -> Dict[str, Any]:
    """Ensure legal metadata payload indexes exist for a collection."""
    try:
        return await garage_request("POST", f"/v1/qdrant/collections/{collection_name}/ensure-indexes")
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def qdrant_ingest_file(
    collection_name: str,
    file_path: str,
    use_auto_chunking: bool = True,
    chunk_size: Optional[int] = None,
    doc_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Ingest a local file into a qdrant collection via multipart upload."""
    form_fields: Dict[str, Any] = {
        "use_auto_chunking": "true" if use_auto_chunking else "false",
    }
    if chunk_size is not None:
        form_fields["chunk_size"] = str(chunk_size)
    if doc_type is not None:
        form_fields["doc_type"] = doc_type
    try:
        return await garage_multipart_request(
            "POST",
            f"/v1/qdrant/collections/{collection_name}/ingest",
            file_field="files",
            file_path=file_path,
            form_fields=form_fields,
            timeout_seconds=1200.0,
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def qdrant_ingest_directory(
    directory_path: str,
    collection_name: str,
    force_recreate: bool = False,
    exclude_dirs: Optional[List[str]] = None,
    embedding_dim: Optional[int] = None,
) -> Dict[str, Any]:
    """Ingest all documents from a local directory into a Qdrant collection.

    Security: directory_path must be within the allowed data tree.
    If embedding_dim is provided and the collection does not exist, it will
    be created before ingestion begins.
    """
    # Security: validate directory path
    try:
        _validate_directory_path(directory_path)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}

    # If embedding_dim is specified, create the collection first
    if embedding_dim is not None:
        try:
            await garage_request(
                "POST", "/v1/qdrant/collections",
                json_body={
                    "name": collection_name,
                    "vector_size": embedding_dim,
                    "distance_metric": "cosine",
                },
                timeout_seconds=30.0,
            )
        except GarageApiError as exc:
            # Collection may already exist — that's fine, proceed
            pass

    payload: Dict[str, Any] = {
        "directory_path": directory_path,
        "collection_name": collection_name,
        "force_recreate": force_recreate,
    }
    if exclude_dirs:
        payload["exclude_dirs"] = exclude_dirs

    try:
        return await garage_request(
            "POST", "/v1/ingestion/ingest-directory",
            params=payload,
            timeout_seconds=900.0,
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def embed_uploads_global() -> Dict[str, Any]:
    """Rebuild the 'uploads-global' collection with all uploaded files.

    Scans the uploads root directory and indexes all files into the
    'uploads-global' Qdrant collection. Recreates the collection each time.
    """
    upload_dir = os.getenv("UPLOAD_DIR", "data/uploads")
    upload_path = Path(upload_dir)
    if not upload_path.is_absolute():
        upload_path = Path("/home/garge") / upload_path
    return await qdrant_ingest_directory(
        directory_path=str(upload_path.resolve()),
        collection_name="uploads-global",
        force_recreate=True,
    )


@mcp.tool()
async def embed_project_uploads(project_id: str) -> Dict[str, Any]:
    """Rebuild the 'project-{project_id}' collection for a specific project.

    Scans uploads/projects/{project_id}/ and indexes all files.
    Recreates the collection each time.
    """
    upload_dir = os.getenv("UPLOAD_DIR", "data/uploads")
    upload_path = Path(upload_dir)
    if not upload_path.is_absolute():
        upload_path = Path("/home/garge") / upload_path
    project_path = upload_path / "projects" / project_id
    return await qdrant_ingest_directory(
        directory_path=str(project_path.resolve()),
        collection_name=f"project-{project_id}",
        force_recreate=True,
    )


@mcp.tool()
async def embed_dev_code(project_root: str = "/home/garge") -> Dict[str, Any]:
    """Index source code symbols into the 'olivia-dev-code' collection.

    Generates markdown summaries per source file, then ingests them via
    the /v1/qdrant/embed-project-code endpoint. Default project_root
    is the Garage project directory. Specify a different path to index
    another project's source tree.
    """
    try:
        return await garage_request(
            "POST", "/v1/qdrant/embed-project-code",
            json_body={"project_root": project_root},
            timeout_seconds=600.0,
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def qdrant_embed_case_directory(
    case_directory: str,
    collection_name: str,
    embedding_dim: int = 384,
) -> Dict[str, Any]:
    """Scan and ingest an entire case directory into a collection.

    Refactored to use the generic qdrant_ingest_directory tool internally.
    The case_directory parameter is resolved relative to the static base path.
    """
    static_base = Path("/home/garge/static")
    full_path = static_base / "latam/violations_data/Case/latam_fiasco/transcript_analyses" / case_directory
    return await qdrant_ingest_directory(
        directory_path=str(full_path),
        collection_name=collection_name,
        force_recreate=True,
        embedding_dim=embedding_dim,
    )


@mcp.tool()
async def qdrant_query(
    collection_name: str,
    query_vector: list[float],
    limit: int = 10,
) -> Dict[str, Any]:
    """Run a direct vector query."""
    payload = {
        "collection_name": collection_name,
        "query_vector": query_vector,
        "limit": limit,
    }
    try:
        return await garage_request("POST", "/v1/qdrant/query", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def qdrant_search_legacy(
    collection_name: str,
    query_text: str,
    limit: int = 10,
    min_score: float = 0.0,
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run the legacy qdrant search endpoint."""
    payload: Dict[str, Any] = {
        "collection_name": collection_name,
        "query_text": query_text,
        "limit": limit,
        "min_score": min_score,
    }
    if filters:
        payload["filters"] = filters
    try:
        return await garage_request("POST", "/v1/qdrant/qdrant/search", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def qdrant_index_reviewed_transcript(
    transcript_id: str,
    collection: str = "reviewed_transcripts",
) -> Dict[str, Any]:
    """Idempotently index reviewed transcript segments into Qdrant."""
    payload: Dict[str, Any] = {"collection": collection}
    try:
        return await garage_request(
            "POST",
            f"/api/transcripts/{transcript_id}/review/index",
            json_body=payload,
            timeout_seconds=600.0,
        )
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def qdrant_query_vector(
    collection_name: str,
    query_vector: Any,
    limit: int = 10,
    score_threshold: Optional[float] = None,
    with_payload: bool = True,
    qdrant_filter: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Query a collection using text or vector through the vector endpoint."""
    payload: Dict[str, Any] = {
        "query_vector": query_vector,
        "limit": limit,
        "with_payload": with_payload,
    }
    if score_threshold is not None:
        payload["score_threshold"] = score_threshold
    if qdrant_filter is not None:
        payload["filter"] = qdrant_filter
    try:
        return await garage_request("POST", f"/v1/qdrant/collections/{collection_name}/query/vector", json_body=payload)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def qdrant_delete_collection(collection_name: str, confirm: bool = False) -> Dict[str, Any]:
    """Delete a collection. Requires confirm=true to avoid accidental data loss."""
    if not confirm:
        return {
            "success": False,
            "error": "Set confirm=true to delete the collection.",
        }

    path = f"/v1/qdrant/collections/{collection_name}"
    try:
        return await garage_request("DELETE", path)
    except GarageApiError as exc:
        return {"success": False, "error": str(exc)}


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for remote connectivity tests."""
    return JSONResponse({"status": "ok", "service": "garage-qdrant"})


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8114"))

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
