"""Garage Jurisprudence MCP server.

Exposes jurisprudence extraction, Qdrant ingestion, and master index operations
from the attached `mcp/to-be-added-mcp` helper scripts.
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

# Ensure sibling helper modules are importable from the attached source directory.
THIS_DIR = Path(__file__).resolve().parent
HELPER_DIR = THIS_DIR.parent / "to-be-added-mcp"
if str(HELPER_DIR) not in sys.path:
    sys.path.insert(0, str(HELPER_DIR))

mcp = FastMCP("garage-juris")


def _load_juris_modules() -> Tuple[Any, Any, Any]:
    try:
        import court_extractor
        import ingest_to_qdrant
        import juris_indexer
    except Exception as exc:
        raise RuntimeError(f"Failed to import jurisprudence helper modules: {exc}") from exc
    return court_extractor, ingest_to_qdrant, juris_indexer


def _resolve_path(path: Optional[str], default: Path) -> Path:
    return Path(path) if path else default


def _prepare_court_extractor(
    court_extractor: Any,
    master_index_path: Optional[str] = None,
    extractions_dir: Optional[str] = None,
) -> None:
    if master_index_path:
        court_extractor.MASTER_INDEX_PATH = Path(master_index_path)
    if extractions_dir:
        court_extractor.EXTRACTIONS_DIR = Path(extractions_dir)


def _prepare_ingest_to_qdrant(
    ingest_module: Any,
    api_base: Optional[str] = None,
    collection: Optional[str] = None,
) -> None:
    if api_base:
        ingest_module.API_BASE = api_base.rstrip("/")
    if collection:
        ingest_module.COLLECTION = collection


def _resolve_indexer_config(
    base_dir: Optional[str] = None,
    downloads_dir: Optional[str] = None,
    docx_dir: Optional[str] = None,
    json_dir: Optional[str] = None,
    history_dir: Optional[str] = None,
) -> Any:
    base_dir_path = Path(base_dir or os.environ.get("JURIS_SEARCH_BASE_DIR", "/root/juris-search"))
    downloads_dir_path = Path(downloads_dir or os.environ.get("JURIS_SEARCH_DOWNLOADS_DIR", str(base_dir_path / "jurisprudence_downloads")))
    docx_dir_path = Path(docx_dir or os.environ.get("JURIS_SEARCH_DOCX_DIR", str(base_dir_path / "docx_jurisprudence")))
    json_dir_path = Path(json_dir or os.environ.get("JURIS_SEARCH_JSON_DIR", str(base_dir_path / "json_jurisprudence")))
    history_dir_path = Path(history_dir or os.environ.get("JURIS_SEARCH_HISTORY_DIR", str(base_dir_path / "searches_history")))

    import juris_indexer

    return juris_indexer.IndexerConfig.from_env(
        base_dir_path,
        downloads_dir_path,
        docx_dir_path,
        json_dir_path,
        history_dir_path,
    )


def _get_juris_indexer(
    base_dir: Optional[str] = None,
    downloads_dir: Optional[str] = None,
    docx_dir: Optional[str] = None,
    json_dir: Optional[str] = None,
    history_dir: Optional[str] = None,
) -> Any:
    _, _, juris_indexer = _load_juris_modules()
    try:
        return juris_indexer.get_indexer()
    except RuntimeError:
        config = _resolve_indexer_config(base_dir, downloads_dir, docx_dir, json_dir, history_dir)
        return juris_indexer.get_indexer(config)


@mcp.tool()
async def juris_process_file(
    filepath: str,
    tribunal: str,
    master_index_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Process a single document file and return extracted metadata without persisting it."""
    try:
        court_extractor, _, _ = _load_juris_modules()
        if master_index_path:
            court_extractor.MASTER_INDEX_PATH = Path(master_index_path)
        master_lookup = court_extractor._load_master_index(str(court_extractor.MASTER_INDEX_PATH))
        result = court_extractor.process_file(filepath, tribunal, master_lookup)
        if result is None:
            return {"success": False, "error": "extraction failed or returned empty"}
        return {"success": True, "document": result}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def juris_extract_file(
    filepath: str,
    tribunal: str,
    master_index_path: Optional[str] = None,
    extractions_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract structured fields from a file and save the result to extracted_documents."""
    try:
        court_extractor, _, _ = _load_juris_modules()
        _prepare_court_extractor(court_extractor, master_index_path, extractions_dir)
        result = court_extractor.extract_file(filepath, tribunal)
        if result is None:
            return {"success": False, "error": "extraction failed or returned empty"}
        return {"success": True, "document": result}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def juris_ingest_extracted_to_qdrant(
    doc: Dict[str, Any],
    qdrant_api: Optional[str] = None,
    collection: str = "juris_br_v1",
) -> Dict[str, Any]:
    """Ingest a previously extracted document dictionary into Qdrant."""
    try:
        court_extractor, _, _ = _load_juris_modules()
        if qdrant_api:
            court_extractor._QDRANT_API_BASE = qdrant_api.rstrip("/")
        court_extractor._QDRANT_COLLECTION = collection
        result = court_extractor.ingest_extracted_to_qdrant(doc, qdrant_api=qdrant_api or court_extractor._QDRANT_API_BASE, collection=collection)
        return {"success": bool(result.get("ok")), **result}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def juris_extract_and_ingest(
    filepath: str,
    tribunal: str,
    master_index_path: Optional[str] = None,
    extractions_dir: Optional[str] = None,
    qdrant_api: Optional[str] = None,
    collection: str = "juris_br_v1",
) -> Dict[str, Any]:
    """Extract a court document and ingest the extracted result into Qdrant."""
    try:
        court_extractor, _, _ = _load_juris_modules()
        _prepare_court_extractor(court_extractor, master_index_path, extractions_dir)
        if qdrant_api:
            court_extractor._QDRANT_API_BASE = qdrant_api.rstrip("/")
        court_extractor._QDRANT_COLLECTION = collection
        result = court_extractor.extract_and_ingest(filepath, tribunal)
        return {"success": bool(result.get("ok")), **result}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def juris_ensure_collection(
    collection: str = "juris_br_v1",
    api_base: Optional[str] = None,
) -> Dict[str, Any]:
    """Ensure the jurisprudence Qdrant collection exists and is connected."""
    try:
        _, ingest_module, _ = _load_juris_modules()
        _prepare_ingest_to_qdrant(ingest_module, api_base, collection)
        ok = ingest_module.ensure_collection()
        return {"success": ok}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def juris_ingest_single(
    doc: Dict[str, Any],
    doc_id: Optional[str] = None,
    collection: str = "juris_br_v1",
    api_base: Optional[str] = None,
) -> Dict[str, Any]:
    """Ingest a single extracted jurisprudence document into Qdrant."""
    try:
        _, ingest_module, _ = _load_juris_modules()
        _prepare_ingest_to_qdrant(ingest_module, api_base, collection)
        result = ingest_module.ingest_single(doc, doc_id=doc_id, collection=collection, api_base=ingest_module.API_BASE)
        return {"success": bool(result.get("ok")), **result}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def juris_ingest_batch(
    items: List[Dict[str, Any]],
    collection: str = "juris_br_v1",
    api_base: Optional[str] = None,
) -> Dict[str, Any]:
    """Ingest a batch of extracted jurisprudence documents into Qdrant."""
    try:
        _, ingest_module, _ = _load_juris_modules()
        _prepare_ingest_to_qdrant(ingest_module, api_base, collection)
        status, error = ingest_module.ingest_batch(items)
        return {"success": status < 400, "status": status, "error": error}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def juris_indexer_start(
    base_dir: Optional[str] = None,
    downloads_dir: Optional[str] = None,
    docx_dir: Optional[str] = None,
    json_dir: Optional[str] = None,
    history_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Start the jurisprudence master indexer background worker."""
    try:
        _get_juris_indexer(base_dir, downloads_dir, docx_dir, json_dir, history_dir).start()
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def juris_indexer_stop(
    timeout: float = 2.0,
) -> Dict[str, Any]:
    """Stop the jurisprudence master indexer background worker."""
    try:
        idx = _get_juris_indexer()
        idx.stop(timeout=timeout)
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def juris_indexer_pause(
    collection: Optional[str] = None,
) -> Dict[str, Any]:
    """Pause ingestion for the master indexer for a specific collection or all."""
    try:
        idx = _get_juris_indexer()
        return {"success": True, "result": idx.pause(collection)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def juris_indexer_resume(
    collection: Optional[str] = None,
) -> Dict[str, Any]:
    """Resume ingestion for the master indexer for a specific collection or all."""
    try:
        idx = _get_juris_indexer()
        return {"success": True, "result": idx.resume(collection)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def juris_indexer_paused_state() -> Dict[str, Any]:
    """Return the current paused state of the jurisprudence master indexer."""
    try:
        idx = _get_juris_indexer()
        return {"success": True, "result": idx.paused_state()}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def juris_indexer_rebuild(
    force_ingest: bool = False,
) -> Dict[str, Any]:
    """Synchronously rebuild the jurisprudence master index."""
    try:
        idx = _get_juris_indexer()
        return {"success": True, "result": idx.rebuild(force_ingest=force_ingest)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def juris_indexer_stats() -> Dict[str, Any]:
    """Return master index stats and current indexer summary."""
    try:
        idx = _get_juris_indexer()
        return {"success": True, "result": idx.stats()}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def juris_indexer_get_document(
    doc_id: str,
) -> Dict[str, Any]:
    """Return a single document record from the master index."""
    try:
        idx = _get_juris_indexer()
        document = idx.get_document(doc_id)
        if document is None:
            return {"success": False, "error": "not found"}
        return {"success": True, "document": document}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def juris_indexer_list_documents(
    tribunal: Optional[str] = None,
    year: Optional[str] = None,
    relator: Optional[str] = None,
    outcome: Optional[str] = None,
    assunto: Optional[str] = None,
    comarca: Optional[str] = None,
    text: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """List master index documents with optional filtering."""
    try:
        idx = _get_juris_indexer()
        return {"success": True, "result": idx.list_documents(
            tribunal=tribunal,
            year=year,
            relator=relator,
            outcome=outcome,
            assunto=assunto,
            comarca=comarca,
            text=text,
            limit=limit,
            offset=offset,
        )}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def juris_indexer_correlate_document(
    doc_id: str,
) -> Dict[str, Any]:
    """Return related documents for a single master index record."""
    try:
        idx = _get_juris_indexer()
        return {"success": True, "result": idx.correlate_document(doc_id)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for remote connectivity tests."""
    return JSONResponse({"status": "ok", "service": "garage-juris"})


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
