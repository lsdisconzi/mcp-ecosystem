"""Health, stats, and legacy compatibility endpoints."""

import json
import os
import urllib.request
import urllib.error

from fastapi import APIRouter
from datetime import datetime
from typing import Optional

from modules.config import (
    DEEPSEEK_API_KEY,
    DEFAULT_COURT,
    DOWNLOADS_BASE_DIR,
    SEARCH_HISTORY_DIR,
    DOCX_JURISPRUDENCE_DIR,
    JSON_JURISPRUDENCE_DIR,
)
from modules.deepseek_client import _resolve_deepseek_model
from modules.courts import SUPPORTED_COURTS, COURT_NAMES
from modules.storage_utils import (
    _collect_download_stats,
    _collect_history_stats,
    _collect_docx_stats,
    _collect_json_stats,
    _collect_link_stats,
)

router = APIRouter()


@router.get("/api/health")
async def health():
    return {
        "status": "ok",
        "deepseek_configured": bool(DEEPSEEK_API_KEY),
        "deepseek_model": _resolve_deepseek_model(),
        "default_court": DEFAULT_COURT,
        "supported_courts": list(SUPPORTED_COURTS.keys()),
    }


@router.get("/health")
async def health_legacy():
    return {
        "status": "ok",
        "service": "juris-search",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "deepseek_configured": bool(DEEPSEEK_API_KEY),
        "deepseek_model": _resolve_deepseek_model(),
        "default_court": DEFAULT_COURT,
        "supported_courts": list(SUPPORTED_COURTS.keys()),
    }


@router.get("/api/stats")
@router.get("/stats")
async def stats_compat():
    payload = _collect_download_stats(DOWNLOADS_BASE_DIR)
    payload.update(_collect_history_stats())
    payload.update(_collect_docx_stats())
    payload.update(_collect_json_stats())
    payload.update(_collect_link_stats())
    payload["storage_paths"] = {
        "download_dir": DOWNLOADS_BASE_DIR,
        "search_history_dir": SEARCH_HISTORY_DIR,
        "docx_dir": DOCX_JURISPRUDENCE_DIR,
        "json_dir": JSON_JURISPRUDENCE_DIR,
    }
    return payload


# ── Court-scraper type classification ──────────────────────────────────────

_COURT_SCRAPER_TYPES = {}
for _key, _info in SUPPORTED_COURTS.items():
    _mod = _info.get("scraper_module", "")
    if _key == "CL":
        _COURT_SCRAPER_TYPES[_key] = "chile"
    elif _mod.startswith("_shared.esaj"):
        _COURT_SCRAPER_TYPES[_key] = "esaj"
    else:
        _COURT_SCRAPER_TYPES[_key] = "dedicated"

# ── Court region classification (Brazilian macro-regions) ──────────────────

_COURT_REGIONS = {
    "TJRS": "South",
    "TJSC": "South",
    "TJPR": "South",
    "TJSP": "Southeast",
    "TJMG": "Southeast",
    "TJRJ": "Southeast",
    "TJES": "Southeast",
    "TJBA": "Northeast",
    "TJPE": "Northeast",
    "TJCE": "Northeast",
    "TJMA": "Northeast",
    "TJPB": "Northeast",
    "TJRN": "Northeast",
    "TJAL": "Northeast",
    "TJSE": "Northeast",
    "TJPI": "Northeast",
    "TJPA": "North",
    "TJAM": "North",
    "TJRO": "North",
    "TJTO": "North",
    "TJAC": "North",
    "TJRR": "North",
    "TJAP": "North",
    "TJDFT": "Center-West",
    "TJGO": "Center-West",
    "TJMT": "Center-West",
    "TJMS": "Center-West",
    "STF": "Federal",
    "CL": "Chile",
}


@router.get("/api/courts")
@router.get("/courts")
async def list_courts():
    """Return all supported courts with metadata and document counts."""
    # Collect per-court document counts from master index
    doc_counts: dict = {}
    try:
        from modules.master_indexer import _master_indexer
        if _master_indexer is not None:
            stats = _master_indexer.stats()
            doc_counts = stats.get("by_tribunal", {})
    except Exception:
        pass

    courts = []
    for key in SUPPORTED_COURTS:
        courts.append({
            "key": key,
            "name": COURT_NAMES.get(key, key),
            "short_name": SUPPORTED_COURTS[key].get("name", key),
            "scraper_type": _COURT_SCRAPER_TYPES.get(key, "unknown"),
            "jurisdiction": "CL" if key == "CL" else "BR",
            "region": _COURT_REGIONS.get(key, "Other"),
            "document_count": doc_counts.get(key, 0),
        })

    return {
        "courts": courts,
        "totals": {
            "courts": len(courts),
            "documents": sum(doc_counts.values()),
            "jurisdictions": {
                "BR": sum(1 for c in courts if c["jurisdiction"] == "BR"),
                "CL": sum(1 for c in courts if c["jurisdiction"] == "CL"),
            },
        },
    }


# ── Admin: Qdrant collections ──────────────────────────────────────────────

_MGMT_API_BASE = os.environ.get("QDRANT_MANAGEMENT_API", "http://localhost:8066").rstrip("/")


@router.get("/api/admin/qdrant-collections")
async def qdrant_collections():
    """Return all Qdrant collections via the management API."""
    try:
        req = urllib.request.Request(
            f"{_MGMT_API_BASE}/v1/qdrant/collections",
            method="GET",
            headers={"accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw = data.get("collections") or []
            items = []
            for c in raw:
                items.append({
                    "name": c.get("name"),
                    "vectors_count": c.get("vectors_count"),
                    "vector_size": c.get("vector_size"),
                })
            items.sort(key=lambda c: c.get("vectors_count", 0) or 0, reverse=True)
            return {"ok": True, "collections": items, "total": len(items)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
