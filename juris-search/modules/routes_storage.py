"""Storage management endpoints (paths, DOCX/JSON index and rebuild)."""

from fastapi import APIRouter

from modules.config import (
    DOWNLOADS_BASE_DIR,
    SEARCH_HISTORY_DIR,
    DOCX_JURISPRUDENCE_DIR,
    JSON_JURISPRUDENCE_DIR,
    SHARED_LINK_ROOT,
    AGENTS_LINK_ROOT,
    EXPORT_LINKS_ENABLED,
    DOCX_INDEX_PATH,
    JSON_INDEX_PATH,
)
from modules.utils import _read_json_file
from modules.storage_watcher import (
    _refresh_docx_pipeline_best_effort,
    _refresh_json_pipeline_best_effort,
    _refresh_storage_pipelines_best_effort,
)
from modules.storage_utils import _sync_export_links

router = APIRouter()


@router.get("/api/storage/paths")
async def get_storage_paths():
    return {
        "download_dir": DOWNLOADS_BASE_DIR,
        "search_history_dir": SEARCH_HISTORY_DIR,
        "docx_dir": DOCX_JURISPRUDENCE_DIR,
        "json_dir": JSON_JURISPRUDENCE_DIR,
        "shared_link_root": SHARED_LINK_ROOT,
        "agents_link_root": AGENTS_LINK_ROOT,
        "links_enabled": EXPORT_LINKS_ENABLED,
    }


@router.get("/api/docx/index")
async def docx_index():
    payload = _read_json_file(DOCX_INDEX_PATH, {})
    if isinstance(payload, dict) and payload:
        return payload

    _refresh_docx_pipeline_best_effort(force_rebuild=False)
    payload = _read_json_file(DOCX_INDEX_PATH, {})
    return payload if isinstance(payload, dict) else {}


@router.get("/api/json/index")
async def json_index():
    payload = _read_json_file(JSON_INDEX_PATH, {})
    if isinstance(payload, dict) and payload:
        return payload

    _refresh_json_pipeline_best_effort(force_rebuild=False)
    payload = _read_json_file(JSON_INDEX_PATH, {})
    return payload if isinstance(payload, dict) else {}


@router.post("/api/docx/rebuild")
async def docx_rebuild():
    return _refresh_docx_pipeline_best_effort(force_rebuild=True)


@router.post("/api/json/rebuild")
async def json_rebuild():
    return _refresh_json_pipeline_best_effort(force_rebuild=True)


@router.post("/api/storage/rebuild")
async def storage_rebuild():
    sync = _refresh_storage_pipelines_best_effort(force_rebuild=True)
    links = _sync_export_links()
    return {
        "storage_sync": sync,
        "link_sync_report": links,
    }
