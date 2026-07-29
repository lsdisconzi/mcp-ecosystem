"""Search endpoints: execute scraper, poll status, retrieve results, list history."""

import threading
import traceback
import uuid
from dataclasses import fields as dc_fields
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

from fastapi import APIRouter, HTTPException

from modules.config import DEFAULT_COURT, SEARCH_HISTORY_DIR
from modules import state as _state
from modules.models import SearchFields
from modules.courts import _resolve_selected_courts, _get_scraper_class
from modules.utils import _normalize_result_item, _read_json_file
from modules.storage_watcher import _persist_search_history

router = APIRouter()


_BRAZIL_FIELD_MAP = {
    "search_text": "search_text",
    "tribunal": "tribunal",
    "orgao_julgador": "orgao_julgador",
    "relator": "relator",
    "tipo_processo": "tipo_processo",
    "classe_cnj": "classe_cnj",
    "assunto_cnj": "assunto_cnj",
    "comarca_origem": "comarca_origem",
    "tipo_decisao": "tipo_decisao",
    "search_index": "search_index",
    "max_results": "max_results",
}

_CHILE_FIELD_MAP = {
    "search_text": "search_text",
    "tribunal": "tribunal",
    "orgao_julgador": "juez",           # route's relator -> Chile's juez
    "relator": "juez",
    "search_index": "search_index",
    "max_results": "max_results",
}

# Fields to extract from user request, independent of court
_USER_FIELD_KEYS = {
    "search_text",
    "tribunal",
    "orgao_julgador",
    "relator",
    "tipo_processo",
    "classe_cnj",
    "assunto_cnj",
    "comarca_origem",
    "tipo_decisao",
    "search_index",
    "max_results",
    # Chile-specific fields sent by the Spanish system prompt
    "categoria",
    "juez",
    "materia",
    "rol",
    "fecha_inicio",
    "fecha_fin",
    "tipo_norma",
    "orden",
}


def _build_criteria_args(
    search_criteria_cls, fields: Dict[str, Any], court_key: str
) -> Dict[str, Any]:
    """Build keyword arguments compatible with the target SearchCriteria dataclass.

    Uses the court key to map route-level field names to court-specific names,
    then only passes fields the dataclass actually accepts.
    """
    acceptable = {f.name for f in dc_fields(search_criteria_cls)}
    args: Dict[str, Any] = {}

    # Collect raw values from the request (both legacy and Chile-specific fields)
    raw: Dict[str, str] = {}
    for key in _USER_FIELD_KEYS:
        val = fields.get(key)
        if val is not None and val != "":
            raw[key] = val

    # Map route-level names -> court-specific names
    for route_name, value in raw.items():
        court_name = route_name
        if court_key == "CL":
            court_name = _CHILE_FIELD_MAP.get(route_name, route_name)
        else:
            court_name = _BRAZIL_FIELD_MAP.get(route_name, route_name)
        if court_name in acceptable:
            args[court_name] = value

    # Apply defaults for fields the user didn't fill
    # (a dataclass field has a default if default != MISSING)
    import dataclasses
    for f in dc_fields(search_criteria_cls):
        if f.name not in args and f.default is not dataclasses.MISSING:
            args[f.name] = f.default

    return args


def _run_scraper(job_id: str, fields: Dict[str, Any]):
    """Run the court-specific scraper in a background thread."""
    try:
        _state.search_jobs[job_id]["status"] = "running"
        _state.search_jobs[job_id]["started_at"] = datetime.utcnow().isoformat()
        _state._persist_job_state(job_id)

        selected_courts = _resolve_selected_courts(
            fields.get("court") or fields.get("tribunal"),
            fields.get("courts"),
        )
        all_results: List[Dict[str, Any]] = []
        per_court: List[Dict[str, Any]] = []

        for court_key in selected_courts:
            scraper_cls, search_criteria_cls = _get_scraper_class(court_key)
            scraper = scraper_cls(headless=True)
            try:
                # Build criteria args compatible with this court's SearchCriteria
                criteria_args = _build_criteria_args(search_criteria_cls, fields, court_key)
                criteria = search_criteria_cls(**criteria_args)
                court_results_raw = scraper.search_with_criteria(criteria) or []
                court_results: List[Dict[str, Any]] = []
                for item in court_results_raw:
                    if isinstance(item, dict):
                        court_results.append(_normalize_result_item(item, court_key))
                all_results.extend(court_results)
                per_court.append({
                    "court": court_key,
                    "status": "completed",
                    "total": len(court_results),
                })
            except Exception as court_exc:
                import logging
                logging.getLogger("juris-search.search").exception("Search failed for %s", court_key)
                per_court.append({
                    "court": court_key,
                    "status": "error",
                    "total": 0,
                    "error": str(court_exc),
                })
            finally:
                scraper.close()

        successful_runs = [item for item in per_court if item.get("status") == "completed"]
        if not successful_runs:
            details = "; ".join(f"{item.get('court')}: {item.get('error', 'erro')}" for item in per_court)
            raise RuntimeError(f"Busca falhou em todas as fontes selecionadas. {details}".strip())

        persisted_fields = dict(fields)
        persisted_fields["courts"] = selected_courts
        persisted_fields["court"] = selected_courts[0]
        persisted_fields["tribunal"] = selected_courts[0] if len(selected_courts) == 1 else "ALL"

        history_file = _persist_search_history(job_id, persisted_fields, all_results)
        _state.search_jobs[job_id]["fields"] = persisted_fields
        _state.search_jobs[job_id]["results"] = all_results
        _state.search_jobs[job_id]["history_file"] = history_file
        _state.search_jobs[job_id]["status"] = "completed"
        _state.search_jobs[job_id]["total"] = len(all_results)
        _state.search_jobs[job_id]["courts"] = selected_courts
        _state.search_jobs[job_id]["per_court"] = per_court
        _state.search_jobs[job_id]["court_errors"] = [item for item in per_court if item.get("status") == "error"]
        _state._persist_job_state(job_id)
    except Exception as e:
        _state.search_jobs[job_id]["status"] = "error"
        _state.search_jobs[job_id]["error"] = str(e)
        _state._persist_job_state(job_id)
        _state.search_jobs[job_id]["traceback"] = traceback.format_exc()


@router.post("/api/search")
async def start_search(fields: SearchFields):
    for _ in range(10):
        job_id = str(uuid.uuid4())[:8]
        if job_id not in _state.search_jobs:
            break
    else:
        raise HTTPException(status_code=500, detail="Could not generate unique job ID")

    _state.search_jobs[job_id] = {
        "status": "queued",
        "fields": fields.dict(),
        "results": [],
        "total": 0,
        "created_at": datetime.utcnow().isoformat(),
    }
    _state._persist_job_state(job_id)

    thread = threading.Thread(target=_run_scraper, args=(job_id, fields.dict()), daemon=True)
    thread.start()

    return {"job_id": job_id, "status": "queued"}


@router.get("/api/search/status/{job_id}")
async def search_status(job_id: str):
    job = _state.search_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job_id,
        "status": job["status"],
        "total": job.get("total", 0),
        "error": job.get("error"),
        "downloaded_files": job.get("downloaded_files", []),
        "download_dir": job.get("download_dir"),
        "history_file": job.get("history_file"),
        "courts": job.get("courts", []),
        "per_court": job.get("per_court", []),
        "court_errors": job.get("court_errors", []),
    }


@router.get("/api/results/{job_id}")
async def get_results(job_id: str):
    job = _state.search_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job_id,
        "status": job["status"],
        "total": job.get("total", 0),
        "results": job.get("results", []),
        "fields": job.get("fields"),
        "history_file": job.get("history_file"),
        "courts": job.get("courts", []),
        "per_court": job.get("per_court", []),
        "court_errors": job.get("court_errors", []),
    }


@router.get("/api/search/history")
async def list_search_history(limit: int = 30):
    history_dir = Path(SEARCH_HISTORY_DIR)
    history_dir.mkdir(parents=True, exist_ok=True)

    files = [p for p in history_dir.glob("search_*.json") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    items: List[Dict[str, Any]] = []
    for path in files[: max(1, min(limit, 200))]:
        payload = _read_json_file(path, {})
        if not isinstance(payload, dict):
            payload = {}

        fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
        items.append({
            "filename": path.name,
            "path": str(path),
            "saved_at": payload.get("saved_at"),
            "job_id": payload.get("job_id"),
            "total": payload.get("total", 0),
            "search_text": fields.get("search_text"),
            "search_index": fields.get("search_index"),
            "max_results": fields.get("max_results"),
        })

    return {
        "history_dir": str(history_dir),
        "total_files": len(files),
        "items": items,
    }


@router.get("/api/search/history/{filename}")
async def get_search_history_file(filename: str):
    if Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Only .json history files are allowed")

    target = Path(SEARCH_HISTORY_DIR) / filename
    if not target.is_file():
        raise HTTPException(status_code=404, detail="History file not found")

    payload = _read_json_file(target, {})
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="History file is invalid")

    payload["path"] = str(target)
    return payload
