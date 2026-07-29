"""Shared mutable state for the juris-search API.

Includes the in-memory search_jobs dictionary, DOCX watcher
threading primitives, and job persistence (disk-backed crash recovery).
"""

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from modules.config import SEARCH_HISTORY_DIR
from modules.utils import _utc_now, _read_json_file, _write_json_file

logger = logging.getLogger("juris-search.state")

# ── In-memory state ─────────────────────────────────────────────────────────

search_jobs: Dict[str, Dict[str, Any]] = {}

_docx_watch_lock = threading.Lock()
_docx_watch_stop_event = threading.Event()
_docx_watch_thread: Optional[threading.Thread] = None
_link_sync_report: List[Dict[str, Any]] = []


# ── Job persistence ─────────────────────────────────────────────────────────

def _job_state_path(job_id: str) -> Path:
    """Path to the transient job-state file for crash recovery."""
    return Path(SEARCH_HISTORY_DIR) / f".job_{job_id}.json"


def _persist_job_state(job_id: str) -> None:
    """Write the current in-memory job dict to disk for crash recovery."""
    job = search_jobs.get(job_id)
    if job is None:
        return
    payload = dict(job)
    payload["_persisted_at"] = _utc_now()
    _write_json_file(_job_state_path(job_id), payload)


def _remove_job_state(job_id: str) -> None:
    """Remove the transient job-state file."""
    path = _job_state_path(job_id)
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


_JOB_TTL_SECONDS = 6 * 3600
_MAX_IN_MEMORY_JOBS = 500


def _evict_expired_jobs() -> int:
    """Remove old completed/error jobs from memory and disk. Returns count evicted."""
    now = datetime.utcnow()
    evicted = 0

    for job_id in list(search_jobs.keys()):
        job = search_jobs.get(job_id, {})
        status = job.get("status")
        if status not in ("completed", "error"):
            continue
        created_raw = job.get("created_at", "")
        try:
            created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            age = (now - created.replace(tzinfo=None)).total_seconds()
        except Exception:
            age = _JOB_TTL_SECONDS + 1

        if age > _JOB_TTL_SECONDS:
            del search_jobs[job_id]
            _remove_job_state(job_id)
            evicted += 1

    while len(search_jobs) > _MAX_IN_MEMORY_JOBS:
        oldest_id = None
        oldest_time = None
        for jid, j in search_jobs.items():
            if j.get("status") not in ("completed", "error"):
                continue
            try:
                t = datetime.fromisoformat(j.get("created_at", "").replace("Z", "+00:00"))
                if oldest_time is None or t < oldest_time:
                    oldest_time = t
                    oldest_id = jid
            except Exception:
                oldest_id = jid
                break
        if oldest_id:
            del search_jobs[oldest_id]
            _remove_job_state(oldest_id)
            evicted += 1
        else:
            break

    if evicted:
        logger.info("Evicted %d expired/completed jobs from memory", evicted)
    return evicted


def _rehydrate_jobs_from_disk() -> None:
    """Scan searches_history/ for .job_*.json files and restore completed jobs into memory."""
    history_dir = Path(SEARCH_HISTORY_DIR)
    if not history_dir.is_dir():
        return

    restored = 0
    for state_file in sorted(history_dir.glob(".job_*.json")):
        payload = _read_json_file(state_file, None)
        if not isinstance(payload, dict):
            continue
        job_id = payload.get("job_id")
        if not job_id:
            continue
        status = payload.get("status")
        if status == "completed":
            history_file = payload.get("history_file")
            if history_file and Path(history_file).is_file():
                search_jobs[job_id] = payload
                restored += 1
            else:
                _remove_job_state(job_id)
        elif status in ("running", "queued"):
            payload["status"] = "error"
            payload["error"] = "Server restarted while job was in progress"
            payload["recovered_at"] = _utc_now()
            search_jobs[job_id] = payload
            _persist_job_state(job_id)
            restored += 1
        else:
            _remove_job_state(job_id)

    if restored:
        logger.info("Rehydrated %d jobs from disk", restored)
