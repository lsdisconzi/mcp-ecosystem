"""Master jurisprudence indexer management."""

import logging
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from modules.config import (
    BASE_DIR,
    DOWNLOADS_BASE_DIR,
    DOCX_JURISPRUDENCE_DIR,
    JSON_JURISPRUDENCE_DIR,
    SEARCH_HISTORY_DIR,
    MASTER_INDEXER_ENABLED,
    _env_flag,
)

logger = logging.getLogger("juris-search.master_indexer")

# ── Lazy import the indexer module ──────────────────────────────────────────

try:
    from juris_indexer import IndexerConfig, JurisMasterIndexer, get_indexer
    _MASTER_INDEXER_AVAILABLE = True
except Exception as _ix_exc:
    logger.warning("Master indexer module unavailable: %s", _ix_exc)
    IndexerConfig = None
    JurisMasterIndexer = None
    get_indexer = None
    _MASTER_INDEXER_AVAILABLE = False

_master_indexer: Optional["JurisMasterIndexer"] = None


def _build_master_indexer_config() -> Optional["IndexerConfig"]:
    if not _MASTER_INDEXER_AVAILABLE:
        return None
    return IndexerConfig.from_env(
        base_dir=BASE_DIR,
        downloads_dir=Path(DOWNLOADS_BASE_DIR),
        docx_dir=Path(DOCX_JURISPRUDENCE_DIR),
        json_dir=Path(JSON_JURISPRUDENCE_DIR),
        history_dir=Path(SEARCH_HISTORY_DIR),
    )


def _start_master_indexer_if_enabled() -> None:
    global _master_indexer
    logger.info("_start_master_indexer_if_enabled: available=%s enabled=%s", _MASTER_INDEXER_AVAILABLE, MASTER_INDEXER_ENABLED)
    if not (_MASTER_INDEXER_AVAILABLE and MASTER_INDEXER_ENABLED):
        logger.info("Master indexer disabled or unavailable")
        return
    cfg = _build_master_indexer_config()
    logger.info("_start_master_indexer_if_enabled: config built=%s", cfg is not None)
    if cfg is None:
        return
    _master_indexer = get_indexer(cfg)
    logger.info("_start_master_indexer_if_enabled: indexer=%s", type(_master_indexer).__name__)
    # Defer the initial rebuild to the background watcher thread.
    # Calling rebuild() here makes synchronous urllib HTTP calls to Qdrant
    # which block the FastAPI event loop.
    _master_indexer.start()
    logger.info("_start_master_indexer_if_enabled: started")


def _stop_master_indexer() -> None:
    global _master_indexer
    if _master_indexer is not None:
        try:
            _master_indexer.stop()
        except Exception:
            pass
        _master_indexer = None


def _require_indexer() -> "JurisMasterIndexer":
    if _master_indexer is None:
        raise HTTPException(status_code=503, detail="Master indexer not running")
    return _master_indexer


def pause_indexer(collection: Optional[str] = None) -> dict:
    """Pause master indexer ingestion for a collection or all."""
    indexer = _require_indexer()
    state = indexer.pause(collection)
    label = collection or "all"
    logger.info("Master indexer paused: collection=%s", label)
    return state


def resume_indexer(collection: Optional[str] = None) -> dict:
    """Resume master indexer ingestion for a collection or all."""
    indexer = _require_indexer()
    state = indexer.resume(collection)
    label = collection or "all"
    logger.info("Master indexer resumed: collection=%s", label)
    return state
