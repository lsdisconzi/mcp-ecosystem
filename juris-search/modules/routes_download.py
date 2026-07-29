"""Download endpoints for juris-search."""

import os
import sys
import uuid
import threading
import logging
from typing import Dict, Any, List

from fastapi import APIRouter, HTTPException

from modules.config import DEFAULT_COURT, DOWNLOADS_BASE_DIR
from modules import state as _state
from modules.models import DownloadRequest, BatchDownloadRequest
from modules.courts import _resolve_court, _get_scraper_class
from modules.storage_watcher import (
    _refresh_storage_pipelines_best_effort,
)
from modules.storage_utils import _sync_export_links
from modules.master_indexer import _master_indexer, _MASTER_INDEXER_AVAILABLE

logger = logging.getLogger("juris-search.download")

def _resolve_headless() -> bool:
    """Whether to run the Selenium browser headless.

    Google reCAPTCHA escalates to the image challenge far more often under
    headless Chrome, so courts protected by a checkbox reCAPTCHA (TJAL/TJAM)
    pass more reliably in a visible session. Set JURIS_CAPTCHA_HEADLESS=false
    to run visible (e.g. under a display/xvfb) for those courts.
    """
    return os.environ.get("JURIS_CAPTCHA_HEADLESS", "true").strip().lower() not in (
        "0", "false", "no", "off",
    )

# ── Auto-extraction + Qdrant ingestion helpers ──────────────────────────────

_COURT_EXTRACTOR_AVAILABLE = False
_extract_and_ingest = None

def _try_import_extractor():
    global _COURT_EXTRACTOR_AVAILABLE, _extract_and_ingest
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        import court_extractor
        _extract_and_ingest = getattr(court_extractor, "extract_and_ingest", None)
        _COURT_EXTRACTOR_AVAILABLE = _extract_and_ingest is not None
        if _COURT_EXTRACTOR_AVAILABLE:
            logger.info("court_extractor.extract_and_ingest available for auto-ingestion")
    except Exception as exc:
        logger.warning("court_extractor not available: %s", exc)


def _auto_extract_and_ingest(file_path: str, tribunal: str) -> bool:
    """Run extraction + Qdrant ingestion on a downloaded file. Non-blocking."""
    if not _COURT_EXTRACTOR_AVAILABLE or _extract_and_ingest is None:
        return False
    try:
        result = _extract_and_ingest(file_path, tribunal)
        if result.get("ok"):
            logger.info("Auto-extracted+ingested %s: %s", os.path.basename(file_path), result.get("proc"))
        else:
            logger.warning("Auto-extract+ingest failed for %s: %s", os.path.basename(file_path), result.get("error"))
        return result.get("ok", False)
    except Exception as exc:
        logger.exception("Auto-extract+ingest error for %s: %s", os.path.basename(file_path), exc)
    return False


_try_import_extractor()
router = APIRouter()


def _collect_download_results(req: DownloadRequest) -> List[Dict[str, Any]]:
    if req.results:
        return req.results

    single_url = (req.url or req.inteiro_url or "").strip()
    if not single_url:
        return []

    return [{
        "inteiro_url": single_url,
        "numero_processo": req.numero_processo,
    }]


@router.post("/api/download")
async def download_inteiro_teor(req: DownloadRequest):
    results = _collect_download_results(req)
    if not results:
        raise HTTPException(status_code=422, detail="Provide either 'results' or 'url'/'inteiro_url'.")

    is_legacy_single = not req.results and bool((req.url or req.inteiro_url))

    if is_legacy_single:
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
            court = (req.tribunal or results[0].get("tribunal") or DEFAULT_COURT)
            scraper_cls, _ = _get_scraper_class(court)

            save_root = DOWNLOADS_BASE_DIR
            os.makedirs(save_root, exist_ok=True)

            target = results[0]
            target_url = target.get("inteiro_url")
            numero = target.get("numero_processo")

            scraper = scraper_cls(headless=_resolve_headless())
            try:
                file_path = scraper.download_inteiro_teor_url(
                    url=target_url,
                    save_dir=save_root,
                    metadata={
                        "numero_processo": numero,
                        "source_url": target_url,
                    },
                    folder_name=req.folder_name,
                    agent_id="juris-search",
                    search_params={
                        "tribunal": req.tribunal or DEFAULT_COURT,
                        "mode": "single",
                    },
                )
            finally:
                scraper.close()

            if file_path:
                storage_sync = _refresh_storage_pipelines_best_effort(force_rebuild=False)
                _sync_export_links()
                # Auto-extract structured fields + ingest to Qdrant
                _auto_extract_and_ingest(file_path, req.tribunal or DEFAULT_COURT)
                if _MASTER_INDEXER_AVAILABLE and _master_indexer is not None:
                    try:
                        _master_indexer.rebuild(force_ingest=True)
                    except Exception as exc:
                        logger.warning("Post-download master index rebuild failed: %s", exc)
                return {
                    "success": True,
                    "file_path": file_path,
                    "error": None,
                    "numero_processo": numero,
                    "docx_sync": storage_sync.get("docx"),
                    "json_sync": storage_sync.get("json"),
                    "storage_sync": storage_sync,
                }

            return {
                "success": False,
                "file_path": None,
                "error": "Download failed - no file returned",
                "numero_processo": numero,
            }
        except Exception as e:
            return {
                "success": False,
                "file_path": None,
                "error": str(e),
                "numero_processo": req.numero_processo,
            }

    job_id = str(uuid.uuid4())[:8]

    def _do_download():
        try:
            save_root = DOWNLOADS_BASE_DIR
            os.makedirs(save_root, exist_ok=True)

            grouped_results: Dict[str, List[Dict[str, Any]]] = {}
            for item in results:
                if not isinstance(item, dict):
                    continue
                court_key = _resolve_court(item.get("tribunal") or item.get("court") or req.tribunal or DEFAULT_COURT)
                normalized_item = dict(item)
                normalized_item["tribunal"] = court_key
                grouped_results.setdefault(court_key, []).append(normalized_item)

            if not grouped_results:
                raise RuntimeError("Nenhum item válido para download.")

            files: List[str] = []
            download_report: List[Dict[str, Any]] = []

            for court_key, court_results in grouped_results.items():
                scraper_cls, _ = _get_scraper_class(court_key)
                scraper = scraper_cls(headless=_resolve_headless())
                try:
                    court_files = scraper.download_all_inteiro_teor(
                        court_results,
                        save_dir=save_root,
                        folder_name=req.folder_name,
                        agent_id="juris-search",
                        search_params={
                            "tribunal": court_key,
                            "mode": "batch",
                        },
                    )
                    files.extend(court_files)
                    download_report.append({
                        "court": court_key,
                        "status": "completed",
                        "requested": len(court_results),
                        "downloaded": len(court_files),
                    })
                except Exception as court_exc:
                    logger.exception("Download failed for %s", court_key)
                    download_report.append({
                        "court": court_key,
                        "status": "error",
                        "requested": len(court_results),
                        "downloaded": 0,
                        "error": str(court_exc),
                    })
                finally:
                    scraper.close()

            if not files and any(item.get("status") == "error" for item in download_report):
                details = "; ".join(f"{item.get('court')}: {item.get('error', 'erro')}" for item in download_report if item.get("status") == "error")
                raise RuntimeError(f"Falha ao baixar arquivos nas fontes selecionadas. {details}")

            storage_sync = _refresh_storage_pipelines_best_effort(force_rebuild=False)
            _sync_export_links()
            # Auto-extract structured fields + ingest all downloaded files to Qdrant
            for f in files:
                court_for_file = req.tribunal or DEFAULT_COURT
                _auto_extract_and_ingest(f, court_for_file)
            if _MASTER_INDEXER_AVAILABLE and _master_indexer is not None:
                try:
                    _master_indexer.rebuild(force_ingest=True)
                except Exception as exc:
                    logger.warning("Post-download master index rebuild failed: %s", exc)
            _state.search_jobs[job_id]["download_report"] = download_report
            _state.search_jobs[job_id]["downloaded_files"] = files
            _state.search_jobs[job_id]["download_dir"] = os.path.dirname(files[0]) if files else save_root
            _state.search_jobs[job_id]["docx_sync"] = storage_sync.get("docx")
            _state.search_jobs[job_id]["json_sync"] = storage_sync.get("json")
            _state.search_jobs[job_id]["storage_sync"] = storage_sync
            _state.search_jobs[job_id]["status"] = "completed"
            _state.search_jobs[job_id]["total"] = len(files)
        except Exception as e:
            _state.search_jobs[job_id]["status"] = "error"
            _state.search_jobs[job_id]["error"] = str(e)

    _state.search_jobs[job_id] = {"status": "running", "total": 0, "downloaded_files": []}
    thread = threading.Thread(target=_do_download, daemon=True)
    thread.start()

    return {"job_id": job_id, "status": "running"}


@router.get("/api/download/status/{job_id}")
async def download_status(job_id: str):
    job = _state.search_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job_id,
        "status": job.get("status", "unknown"),
        "total": job.get("total", 0),
        "error": job.get("error"),
        "downloaded_files": job.get("downloaded_files", []),
        "download_dir": job.get("download_dir"),
        "docx_sync": job.get("docx_sync"),
        "json_sync": job.get("json_sync"),
        "storage_sync": job.get("storage_sync"),
        "download_report": job.get("download_report", []),
    }


@router.post("/api/download-batch")
async def download_batch_compat(req: BatchDownloadRequest):
    """Legacy-compatible synchronous batch download endpoint."""
    to_download = [r for r in req.results if r.get("inteiro_url")]

    if not to_download:
        return {
            "total_requested": len(req.results),
            "successful": 0,
            "failed": 0,
            "files": [],
            "errors": ["No results with inteiro_url found"],
        }

    try:
        court = req.tribunal or DEFAULT_COURT
        scraper_cls, _ = _get_scraper_class(court)

        save_root = DOWNLOADS_BASE_DIR
        os.makedirs(save_root, exist_ok=True)

        scraper = scraper_cls(headless=_resolve_headless())
        try:
            saved_files = scraper.download_all_inteiro_teor(
                results=to_download,
                save_dir=save_root,
                overwrite=False,
                delay=0.5,
                folder_name=req.folder_name,
                agent_id="juris-search",
                search_params={
                    "tribunal": req.tribunal or DEFAULT_COURT,
                    "mode": "batch-compat",
                },
            )
        finally:
            scraper.close()

        successful = len(saved_files)
        failed = len(to_download) - successful
        storage_sync = _refresh_storage_pipelines_best_effort(force_rebuild=False)
        _sync_export_links()
        if _MASTER_INDEXER_AVAILABLE and _master_indexer is not None:
            try:
                _master_indexer.rebuild(force_ingest=True)
            except Exception as exc:
                logger.warning("Post-download master index rebuild failed: %s", exc)

        return {
            "total_requested": len(req.results),
            "successful": successful,
            "failed": failed,
            "files": saved_files,
            "docx_sync": storage_sync.get("docx"),
            "json_sync": storage_sync.get("json"),
            "storage_sync": storage_sync,
            "errors": [] if failed == 0 else [f"{failed} downloads failed"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch download failed: {e}")
