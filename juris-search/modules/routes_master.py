"""Master jurisprudence indexer endpoints."""

import json
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from typing import Optional as OptStr

import modules.master_indexer as _mi

router = APIRouter()


@router.get("/api/master-index/stats")
async def master_index_stats():
    if not _mi._MASTER_INDEXER_AVAILABLE:
        return {"available": False, "reason": "indexer module unavailable"}
    if _mi._master_indexer is None:
        return {"available": False, "reason": "indexer not running"}
    return _mi._master_indexer.stats()


@router.get("/api/master-index/documents")
async def master_index_documents(
    tribunal: Optional[str] = None,
    year: Optional[str] = None,
    relator: Optional[str] = None,
    outcome: Optional[str] = None,
    assunto: Optional[str] = None,
    comarca: Optional[str] = None,
    text: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    indexer = _mi._require_indexer()
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    return indexer.list_documents(
        tribunal=tribunal,
        year=year,
        relator=relator,
        outcome=outcome,
        assunto=assunto,
        comarca=comarca,
        text=text,
        limit=limit,
        offset=offset,
    )


@router.get("/api/master-index/document/{doc_id}")
async def master_index_document(doc_id: str):
    indexer = _mi._require_indexer()
    doc = indexer.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"document {doc_id} not found")
    return doc


@router.get("/api/master-index/document/{doc_id}/correlations")
async def master_index_document_correlations(doc_id: str):
    """Return documents correlated by relator, assunto, and legislacao."""
    indexer = _mi._require_indexer()
    result = indexer.correlate_document(doc_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=f"document {doc_id} not found")
    return result


@router.post("/api/master-index/rebuild")
async def master_index_rebuild(force_ingest: bool = False):
    indexer = _mi._require_indexer()
    return indexer.rebuild(force_ingest=force_ingest)


@router.post("/api/master-index/pause")
async def master_index_pause(collection: OptStr[str] = None):
    """Pause background ingestion for a specific collection or all.

    ``collection`` can be ``"law_br"``, ``"juris_search_memory"``, or omit to pause all.
    """
    if collection and collection not in ("law_br", "juris_search_memory"):
        raise HTTPException(status_code=400, detail="collection must be 'law_br' or 'juris_search_memory'")
    return _mi.pause_indexer(collection)


@router.post("/api/master-index/resume")
async def master_index_resume(collection: OptStr[str] = None):
    """Resume background ingestion for a specific collection or all.

    ``collection`` can be ``"law_br"``, ``"juris_search_memory"``, or omit to resume all.
    """
    if collection and collection not in ("law_br", "juris_search_memory"):
        raise HTTPException(status_code=400, detail="collection must be 'law_br' or 'juris_search_memory'")
    return _mi.resume_indexer(collection)


@router.get("/api/master-index/markdown")
async def master_index_markdown(rebuild: bool = False):
    """Return the navigable Markdown view of the master index."""
    indexer = _mi._require_indexer()
    md_path = indexer.config.master_dir / "master_index.md"
    if rebuild or not md_path.is_file():
        try:
            from render_master_markdown import render_master_markdown
            render_master_markdown(indexer.master_index_path, md_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"render failed: {exc}")
    if not md_path.is_file():
        raise HTTPException(status_code=404, detail="markdown index not generated yet")
    return FileResponse(str(md_path), media_type="text/markdown", filename="master_index.md")


@router.get("/api/master-index/jurisprudence")
async def master_index_jurisprudence(rebuild: bool = False):
    """Return the expanded master jurisprudence index (.jsx JSON superset)."""
    indexer = _mi._require_indexer()
    jsx_path = indexer.config.master_dir / "masterjurisprudence.jsx"
    if rebuild or not jsx_path.is_file():
        try:
            from render_masterjurisprudence import render as render_juris
            render_juris(
                indexer.master_index_path,
                jx_path=jsx_path,
                md_path=indexer.config.master_dir / "masterjurisprudence.md",
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"render failed: {exc}")
    if not jsx_path.is_file():
        raise HTTPException(status_code=404, detail="jurisprudence index not generated yet")
    return FileResponse(str(jsx_path), media_type="application/json", filename="masterjurisprudence.jsx")


@router.get("/api/master-index/jurisprudence/markdown")
async def master_index_jurisprudence_markdown(rebuild: bool = False):
    """Return the rendered Markdown companion of the expanded master index."""
    indexer = _mi._require_indexer()
    md_path = indexer.config.master_dir / "masterjurisprudence.md"
    if rebuild or not md_path.is_file():
        try:
            from render_masterjurisprudence import render as render_juris
            render_juris(
                indexer.master_index_path,
                jx_path=indexer.config.master_dir / "masterjurisprudence.jsx",
                md_path=md_path,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"render failed: {exc}")
    if not md_path.is_file():
        raise HTTPException(status_code=404, detail="jurisprudence markdown not generated yet")
    return FileResponse(str(md_path), media_type="text/markdown", filename="masterjurisprudence.md")


@router.get("/api/master-index/download-file")
async def master_index_download_file(path: str):
    from pathlib import Path
    from modules.config import DOWNLOADS_BASE_DIR, DOCX_JURISPRUDENCE_DIR, JSON_JURISPRUDENCE_DIR

    allowed_dirs = [
        Path(DOWNLOADS_BASE_DIR).resolve(),
        Path(DOCX_JURISPRUDENCE_DIR).resolve(),
        Path(JSON_JURISPRUDENCE_DIR).resolve(),
    ]

    p = Path(path)
    if not p.is_absolute():
        target_path = (allowed_dirs[0] / p).resolve()
    else:
        target_path = p.resolve()

    is_allowed = False
    for allowed_dir in allowed_dirs:
        try:
            target_path.relative_to(allowed_dir)
            is_allowed = True
            break
        except ValueError:
            continue

    if not is_allowed:
        raise HTTPException(status_code=403, detail="Access denied")

    if not target_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    media_type = "application/octet-stream"
    suffix = target_path.suffix.lower()
    if suffix == ".pdf":
        media_type = "application/pdf"
    elif suffix in (".html", ".htm"):
        media_type = "text/html"
    elif suffix == ".docx":
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    return FileResponse(
        str(target_path),
        media_type=media_type,
        filename=target_path.name
    )



@router.post("/api/master-index/search")
async def master_index_semantic_search(payload: Dict[str, Any]):
    """Proxy semantic search to the Qdrant management service (port 8066)."""
    indexer = _mi._require_indexer()
    cfg = indexer.config
    query_text = (payload.get("query") or payload.get("query_text") or "").strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="query is required")
    body = {
        "collection_name": payload.get("collection_name") or cfg.qdrant_collection,
        "query_text": query_text,
        "limit": int(payload.get("limit") or 10),
        "filters": payload.get("filters") or None,
        "min_score": float(payload.get("min_score") or 0.0),
    }
    import urllib.request
    import urllib.error
    req = urllib.request.Request(
        f"{cfg.qdrant_base_url}/v1/qdrant/search",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.request_timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail=exc.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"qdrant gateway error: {exc}")
