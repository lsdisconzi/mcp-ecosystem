"""Background watcher for DOCX and JSON storage pipelines."""

import json
import threading
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

from modules.config import (
    DOWNLOADS_BASE_DIR,
    DOCX_JURISPRUDENCE_DIR,
    JSON_JURISPRUDENCE_DIR,
    DOCX_WATCH_INTERVAL_SECONDS,
    SEARCH_HISTORY_DIR,
)
from modules import state as _state
from modules.storage_docx import _process_docx_pipeline
from modules.storage_json import _process_json_pipeline
from modules.storage_utils import _sync_export_links

logger = logging.getLogger("juris-search.storage_watcher")


def _persist_search_history(job_id: str, fields: Dict[str, Any], results: List[Dict[str, Any]]) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"search_{timestamp}_{job_id}.json"
    output_path = Path(SEARCH_HISTORY_DIR) / filename

    payload = {
        "job_id": job_id,
        "saved_at": datetime.utcnow().isoformat() + "Z",
        "fields": fields,
        "total": len(results),
        "results": results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return str(output_path)


def _docx_watch_loop() -> None:
    logger.info(
        "Storage watcher started: source=%s docx=%s json=%s interval=%ss",
        DOWNLOADS_BASE_DIR,
        DOCX_JURISPRUDENCE_DIR,
        JSON_JURISPRUDENCE_DIR,
        DOCX_WATCH_INTERVAL_SECONDS,
    )
    while not _state._docx_watch_stop_event.is_set():
        try:
            _state._evict_expired_jobs()
            _process_docx_pipeline(force_rebuild=False)
            _process_json_pipeline(force_rebuild=False)
        except Exception as exc:
            logger.warning("Storage watcher cycle failed: %s", exc)
        _state._docx_watch_stop_event.wait(DOCX_WATCH_INTERVAL_SECONDS)


def _start_docx_watcher_if_enabled() -> None:
    from modules.config import DOCX_WATCH_ENABLED

    if not DOCX_WATCH_ENABLED:
        logger.info("DOCX watcher disabled via JURIS_SEARCH_DOCX_WATCH")
        return

    if _state._docx_watch_thread and _state._docx_watch_thread.is_alive():
        return

    _state._docx_watch_stop_event.clear()
    _state._docx_watch_thread = threading.Thread(target=_docx_watch_loop, name="juris-docx-watcher", daemon=True)
    _state._docx_watch_thread.start()


def _refresh_docx_pipeline_best_effort(force_rebuild: bool = False) -> Dict[str, Any]:
    try:
        return _process_docx_pipeline(force_rebuild=force_rebuild)
    except Exception as exc:
        logger.warning("DOCX pipeline refresh failed: %s", exc)
        from modules.config import DOCX_INDEX_PATH

        return {
            "scanned": 0,
            "converted": 0,
            "skipped": 0,
            "failed": 1,
            "error": str(exc),
            "index_file": str(DOCX_INDEX_PATH),
            "docx_dir": DOCX_JURISPRUDENCE_DIR,
        }


def _refresh_json_pipeline_best_effort(force_rebuild: bool = False) -> Dict[str, Any]:
    try:
        return _process_json_pipeline(force_rebuild=force_rebuild)
    except Exception as exc:
        logger.warning("JSON pipeline refresh failed: %s", exc)
        from modules.config import JSON_INDEX_PATH

        return {
            "scanned": 0,
            "converted": 0,
            "skipped": 0,
            "failed": 1,
            "error": str(exc),
            "index_file": str(JSON_INDEX_PATH),
            "json_dir": JSON_JURISPRUDENCE_DIR,
        }


def _refresh_storage_pipelines_best_effort(force_rebuild: bool = False) -> Dict[str, Any]:
    docx = _refresh_docx_pipeline_best_effort(force_rebuild=force_rebuild)
    json_result = _refresh_json_pipeline_best_effort(force_rebuild=force_rebuild)
    return {
        "docx": docx,
        "json": json_result,
    }
