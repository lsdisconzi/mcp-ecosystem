"""
Neo4j router for Garage.

Thin proxy to the Manus service's existing Neo4j endpoints
(/api/memory/graph/*). Exposes a stable, Garage-prefixed surface
(`/v1/neo4j/*`) so the frontend never needs to know whether the
implementation is a proxy or a native driver — swapping later is
a single-file change with no UI impact.

Endpoints
---------
GET  /v1/neo4j/health        → ping Manus + report reachability
GET  /v1/neo4j/stats         → proxy of /api/memory/graph/stats
POST /v1/neo4j/cypher        → proxy of /api/memory/graph/query (read-only by default)
POST /v1/neo4j/rag-context   → run a Cypher and serialize records into a
                                text block suitable for prompt injection.

Configuration
-------------
MANUS_SERVICE_URL  base URL of the Manus service (default http://localhost:8078)
NEO4J_PROXY_TIMEOUT seconds (default 30)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/neo4j", tags=["neo4j"])

_MANUS_ORIGIN = os.getenv("MANUS_SERVICE_URL", "http://localhost:8078")
_TIMEOUT = float(os.getenv("NEO4J_PROXY_TIMEOUT", "30"))

# Block obvious write/destructive clauses when allow_writes is not set.
_WRITE_KEYWORDS = (
    "create ", "merge ", "delete ", "detach ", "set ", "remove ",
    "drop ", "call db.", "call apoc.",
)


class CypherRequest(BaseModel):
    query: str = Field(..., description="Cypher query to execute")
    params: Optional[Dict[str, Any]] = None
    template: Optional[str] = None
    allow_writes: bool = False


class RagContextRequest(BaseModel):
    query: str = Field("", description="Optional user question (for logging / future LLM->Cypher)")
    cypher: str = Field(..., description="Cypher to execute and serialize")
    params: Optional[Dict[str, Any]] = None
    limit: int = Field(25, ge=1, le=500)
    allow_writes: bool = False


def _is_read_only(q: str) -> bool:
    lowered = q.lower()
    return not any(kw in lowered for kw in _WRITE_KEYWORDS)


async def _manus_request(method: str, path: str, **kwargs) -> httpx.Response:
    url = f"{_MANUS_ORIGIN}{path}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            return await client.request(method, url, **kwargs)
    except httpx.RequestError as exc:
        logger.error("Manus upstream error %s %s: %s", method, url, exc)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "Manus service unreachable",
                "upstream": url,
                "message": str(exc),
            },
        )


@router.get("/health")
async def health() -> Dict[str, Any]:
    """Ping the Manus Neo4j stats endpoint as a liveness probe."""
    try:
        r = await _manus_request("GET", "/api/memory/graph/stats")
        return {
            "status": "healthy" if r.status_code == 200 else "degraded",
            "upstream": _MANUS_ORIGIN,
            "upstream_status": r.status_code,
        }
    except HTTPException as e:
        return {"status": "unhealthy", "upstream": _MANUS_ORIGIN, "error": e.detail}


@router.get("/stats")
async def stats() -> Any:
    r = await _manus_request("GET", "/api/memory/graph/stats")
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


@router.post("/cypher")
async def cypher(req: CypherRequest) -> Any:
    if not req.allow_writes and not _is_read_only(req.query):
        raise HTTPException(
            status_code=403,
            detail="Write Cypher rejected. Set allow_writes=true to permit.",
        )
    payload = {"query": req.query, "params": req.params, "template": req.template}
    r = await _manus_request("POST", "/api/memory/graph/query", json=payload)
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


def _serialize_records(records: List[Any], limit: int) -> str:
    """Flatten Neo4j-style records into a prompt-friendly text block."""
    lines: List[str] = []
    for i, rec in enumerate(records[:limit]):
        if isinstance(rec, dict):
            parts = [f"{k}={v!r}" for k, v in rec.items()]
            lines.append(f"[{i + 1}] " + " | ".join(parts))
        else:
            lines.append(f"[{i + 1}] {rec!r}")
    return "\n".join(lines)


@router.post("/rag-context")
async def rag_context(req: RagContextRequest) -> Dict[str, Any]:
    """Run a Cypher query and return a text block ready for prompt injection."""
    if not req.allow_writes and not _is_read_only(req.cypher):
        raise HTTPException(
            status_code=403,
            detail="Write Cypher rejected. Set allow_writes=true to permit.",
        )
    payload = {"query": req.cypher, "params": req.params}
    r = await _manus_request("POST", "/api/memory/graph/query", json=payload)
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)

    data = r.json() if r.content else {}
    records = (
        data.get("records")
        or data.get("results")
        or data.get("data")
        or (data if isinstance(data, list) else [])
    )
    if not isinstance(records, list):
        records = [records]

    context = _serialize_records(records, req.limit)
    return {
        "context": context,
        "record_count": len(records),
        "truncated": len(records) > req.limit,
    }
