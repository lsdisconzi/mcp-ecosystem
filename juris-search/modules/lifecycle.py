"""Application lifecycle (startup/shutdown) event registration.

Exports register_lifecycle(app) to be called from main.py after
all routers have been included.
"""

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Set

from modules import state as _state
from modules.storage_watcher import (
    _start_docx_watcher_if_enabled,
    _refresh_storage_pipelines_best_effort,
)
from modules.storage_utils import _sync_export_links
from modules.master_indexer import (
    _start_master_indexer_if_enabled,
    _stop_master_indexer,
    _master_indexer,
    _MASTER_INDEXER_AVAILABLE,
)
from modules.config import DOWNLOADS_BASE_DIR

logger = logging.getLogger("juris-search.lifecycle")

_PIPELINE_CATCHUP_INTERVAL = int(os.environ.get(
    "JURIS_SEARCH_PIPELINE_CATCHUP_INTERVAL", "300"))  # 5 minutes

_catchup_stop = threading.Event()
_catchup_thread = None


# ── Dead-letter handling for unextractable downloads ───────────────────────
#
# Some downloads are saved as Chrome's built-in PDF-viewer wrapper pages
# (chrome-extension://.../pdf_embedder.css, empty <body>) or other content
# that yields 0 extractable chars. The extractor correctly refuses them, but
# without a durable "done" marker the catch-up loop re-scans and re-SKIPs
# them on every startup and every interval forever. We record a dead-letter
# sidecar next to such files so they are excluded until the source file
# changes (e.g. re-downloaded with real content).

_DEADLETTER_SUFFIX = ".deadletter"

# Chrome's built-in PDF viewer renders a tiny wrapper page with this marker.
_CHROME_VIEWER_MARKER = "pdf_embedder.css"

# Extensions that should have been real artifacts but can be poisoned wrappers.
_WRAPPER_PRONE_EXTS = {".html", ".htm"}


def _deadletter_path(fpath: Path) -> Path:
    return fpath.with_suffix(fpath.suffix + _DEADLETTER_SUFFIX)


def _is_deadlettered(fpath: Path) -> bool:
    """True if a dead-letter marker exists that still matches the file size."""
    marker = _deadletter_path(fpath)
    if not marker.exists():
        return False
    try:
        size = fpath.stat().st_size
        stored = int(marker.read_text(encoding="utf-8").strip() or "-1")
        # A re-downloaded (size-changed) file should be retried, so drop stale marker.
        if stored != size:
            try:
                marker.unlink()
            except OSError:
                pass
            return False
        return True
    except (OSError, ValueError):
        return False


def _mark_deadletter(fpath: Path, reason: str) -> None:
    """Record that a file is unextractable so it isn't reprocessed endlessly."""
    try:
        _deadletter_path(fpath).write_text(str(fpath.stat().st_size), encoding="utf-8")
        logger.info("Dead-letter %s: %s (size=%d)", fpath.name, reason, fpath.stat().st_size)
    except OSError as exc:
        logger.warning("Could not write dead-letter marker for %s: %s", fpath.name, exc)


def _is_chrome_viewer_wrapper(fpath: Path) -> bool:
    """True if an HTML file is Chrome's empty PDF-viewer wrapper, not a document."""
    if fpath.suffix.lower() not in _WRAPPER_PRONE_EXTS:
        return False
    if fpath.stat().st_size > 8192:
        # Real jurisprudence HTML pages are substantially larger.
        return False
    try:
        head = fpath.read_text(encoding="utf-8", errors="ignore")[:4096]
    except OSError:
        return False
    return _CHROME_VIEWER_MARKER in head


def _pipeline_catch_up_cycle() -> dict:
    """Scan for downloads not yet extracted/ingested and process them.

    Returns {"found": N, "extracted": N, "ingested": N, "errors": [...]}.
    """
    result = {"found": 0, "extracted": 0, "ingested": 0, "errors": []}

    if not Path(DOWNLOADS_BASE_DIR).is_dir():
        return result

    # ── Collect already-extracted source_files ────────────────────────
    extractions_dir = Path(os.environ.get(
        "JURIS_SEARCH_EXTRACTIONS_DIR",
        str(Path(__file__).resolve().parent.parent / "extracted_documents"),
    ))
    extracted_sources: Set[str] = set()
    if extractions_dir.is_dir():
        for f in extractions_dir.glob("*.json"):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
                sf = doc.get("source_file", "")
                if sf:
                    extracted_sources.add(sf)
            except Exception:
                pass

    # ── Find unextracted downloads ────────────────────────────────────
    missing = []
    for f in Path(DOWNLOADS_BASE_DIR).rglob("*"):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        # .doc needs DOCX conversion (handled by storage watcher). Skip.
        if ext not in (".pdf", ".docx", ".html", ".htm"):
            continue
        if f.name in extracted_sources:
            continue
        # Skip files already proven unextractable (e.g. Chrome-viewer wrappers
        # or 0-char content). A size change clears the marker so re-downloads retry.
        if _is_deadlettered(f):
            continue
        # Proactively drop Chrome's empty PDF-viewer wrappers before even trying.
        if _is_chrome_viewer_wrapper(f):
            _mark_deadletter(f, "chrome pdf-viewer wrapper (0 chars)")
            continue
        missing.append(f)

    result["found"] = len(missing)
    if not missing:
        return result

    # ── Import extract_and_ingest on demand ───────────────────────────
    try:
        sys_path = str(Path(__file__).resolve().parent.parent)
        import sys
        if sys_path not in sys.path:
            sys.path.insert(0, sys_path)
        from court_extractor import extract_and_ingest
    except Exception as exc:
        logger.warning("Pipeline catch-up: cannot import court_extractor: %s", exc)
        return result

    # ── Process each missing file ─────────────────────────────────────
    for fpath in missing:
        tribunal = _guess_tribunal(fpath.name)
        try:
            r = extract_and_ingest(str(fpath), tribunal)
            if r.get("ok"):
                result["extracted"] += 1
                result["ingested"] += 1
                logger.info("Catch-up extracted+ingested: %s [%s]", fpath.name, r.get("proc", "?"))
            else:
                err = r.get("error", "unknown")
                # "extraction failed" (0 chars / empty) is permanent for this exact
                # file content — dead-letter it so we don't re-SKIP on every cycle.
                if err in ("extraction failed", "text too short"):
                    _mark_deadletter(fpath, err)
                else:
                    result["errors"].append(f"{fpath.name}: {err}")
        except Exception as exc:
            result["errors"].append(f"{fpath.name}: {exc}")
            logger.warning("Catch-up failed for %s: %s", fpath.name, exc)

    # ── Rebuild master index after processing stragglers ──────────────
    if result["extracted"] > 0:
        try:
            if _MASTER_INDEXER_AVAILABLE and _master_indexer is not None:
                _master_indexer.rebuild(force_ingest=True)
                logger.info("Catch-up triggered master index rebuild with %s new docs",
                            result["extracted"])
        except Exception as exc:
            logger.warning("Catch-up master index rebuild failed: %s", exc)

    return result


def _guess_tribunal(filename: str) -> str:
    """Heuristic: guess tribunal from filename patterns."""
    fname = filename.lower()
    if "tjsp" in fname:
        return "TJSP"
    if "tjrs" in fname:
        return "TJRS"
    if "tjms" in fname:
        return "TJMS"
    if "tjce" in fname:
        return "TJCE"
    # Fallback: let the extractor auto-detect from content
    if fname.startswith("inteiro_teor_"):
        # e-SAJ format — could be TJSP, TJMS, or TJCE
        return "TJSP"  # try TJSP first; extractor will validate internally
    return "TJSP"


def _pipeline_catch_up_loop(interval: int = _PIPELINE_CATCHUP_INTERVAL) -> None:
    """Background thread: periodically scan for pipeline stragglers."""
    logger.info("Pipeline catch-up thread started (interval=%ss)", interval)
    while not _catchup_stop.is_set():
        try:
            result = _pipeline_catch_up_cycle()
            if result["found"] > 0 or result["extracted"] > 0:
                logger.info(
                    "Pipeline catch-up: found=%d, extracted=%d, ingested=%d, errors=%d",
                    result["found"], result["extracted"],
                    result["ingested"], len(result.get("errors", [])),
                )
        except Exception as exc:
            logger.warning("Pipeline catch-up cycle error: %s", exc)
        _catchup_stop.wait(interval)


def _start_pipeline_catch_up() -> None:
    """Start the pipeline catch-up watcher thread."""
    global _catchup_thread
    if _catchup_thread and _catchup_thread.is_alive():
        return
    _catchup_stop.clear()
    _catchup_thread = threading.Thread(
        target=_pipeline_catch_up_loop,
        args=(_PIPELINE_CATCHUP_INTERVAL,),
        daemon=True,
        name="juris-pipeline-catchup",
    )
    _catchup_thread.start()


def _stop_pipeline_catch_up() -> None:
    """Stop the pipeline catch-up watcher thread."""
    _catchup_stop.set()
    if _catchup_thread and _catchup_thread.is_alive():
        _catchup_thread.join(timeout=5.0)


def register_lifecycle(app):
    """Register startup and shutdown event handlers on the given FastAPI app."""

    @app.on_event("startup")
    async def _startup():
        _state._rehydrate_jobs_from_disk()
        _refresh_storage_pipelines_best_effort(force_rebuild=False)
        _sync_export_links()
        _start_docx_watcher_if_enabled()
        # Run master indexer init in a background thread so it doesn't block
        # the event loop (it makes synchronous urllib HTTP calls to Qdrant).
        threading.Thread(target=_start_master_indexer_if_enabled, daemon=True).start()
        # Start pipeline catch-up watcher (catches documents from before automation)
        threading.Thread(target=_start_pipeline_catch_up, daemon=True).start()

    @app.on_event("shutdown")
    async def _shutdown():
        _state._docx_watch_stop_event.set()
        if _state._docx_watch_thread and _state._docx_watch_thread.is_alive():
            _state._docx_watch_thread.join(timeout=2.0)
        _state._docx_watch_thread = None
        _stop_master_indexer()
        _stop_pipeline_catch_up()
