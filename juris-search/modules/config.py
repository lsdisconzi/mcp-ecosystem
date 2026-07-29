"""Environment variables and path configuration for juris-search."""

import os
import logging
from pathlib import Path

logger = logging.getLogger("juris-search.config")


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


BASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = BASE_DIR.parent.parent
TJRS_FRONTEND_DIST_DIR = BASE_DIR / "tjrs-frontend" / "dist"

# ── DeepSeek ────────────────────────────────────────────────────────────────

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")

# ── Court defaults ──────────────────────────────────────────────────────────

DEFAULT_COURT = os.environ.get("JURIS_SEARCH_DEFAULT_COURT", "TJRS").strip().upper() or "TJRS"

# ── Storage paths ───────────────────────────────────────────────────────────

DEFAULT_DOWNLOADS_DIR = BASE_DIR / "jurisprudence_downloads"
DEFAULT_SEARCH_HISTORY_DIR = BASE_DIR / "searches_history"
DEFAULT_DOCX_DIR = BASE_DIR / "docx_jurisprudence"
DEFAULT_JSON_DIR = BASE_DIR / "json_jurisprudence"
DEFAULT_SHARED_LINK_ROOT = BASE_DIR / "_shared" / "cases" / "juris-search"
DEFAULT_AGENTS_LINK_ROOT = WORKSPACE_ROOT / "agents" / "agents-groups" / "la8159" / "source" / "juris-search"

DOWNLOADS_BASE_DIR = os.environ.get("JURIS_SEARCH_DOWNLOAD_DIR", str(DEFAULT_DOWNLOADS_DIR))
SEARCH_HISTORY_DIR = os.environ.get("JURIS_SEARCH_HISTORY_DIR", str(DEFAULT_SEARCH_HISTORY_DIR))
DOCX_JURISPRUDENCE_DIR = os.environ.get("JURIS_SEARCH_DOCX_DIR", str(DEFAULT_DOCX_DIR))
JSON_JURISPRUDENCE_DIR = os.environ.get("JURIS_SEARCH_JSON_DIR", str(DEFAULT_JSON_DIR))

DOCX_INDEX_PATH = Path(DOCX_JURISPRUDENCE_DIR) / "index.json"
DOCX_STATE_PATH = Path(DOCX_JURISPRUDENCE_DIR) / ".watch_state.json"
JSON_INDEX_PATH = Path(JSON_JURISPRUDENCE_DIR) / "index.json"
JSON_STATE_PATH = Path(JSON_JURISPRUDENCE_DIR) / ".watch_state.json"

# ── Watcher settings ────────────────────────────────────────────────────────

DOCX_WATCH_ENABLED = _env_flag("JURIS_SEARCH_DOCX_WATCH", default=True)
DOCX_WATCH_INTERVAL_SECONDS = max(3, int(os.environ.get("JURIS_SEARCH_DOCX_WATCH_INTERVAL", "10")))
DOCX_NORMALIZE_FOR_COMPAT = _env_flag("JURIS_SEARCH_DOCX_NORMALIZE_COMPAT", default=True)

# ── Export links ────────────────────────────────────────────────────────────

EXPORT_LINKS_ENABLED = _env_flag("JURIS_SEARCH_EXPORT_LINKS", default=True)
SHARED_LINK_ROOT = os.environ.get("JURIS_SEARCH_SHARED_LINK_ROOT", str(DEFAULT_SHARED_LINK_ROOT))
AGENTS_LINK_ROOT = os.environ.get("JURIS_SEARCH_AGENTS_LINK_ROOT", str(DEFAULT_AGENTS_LINK_ROOT))

# ── Master indexer ──────────────────────────────────────────────────────────

MASTER_INDEXER_ENABLED = _env_flag("JURIS_SEARCH_MASTER_INDEX", default=True)

# ── Ensure directories exist ────────────────────────────────────────────────

os.makedirs(DOWNLOADS_BASE_DIR, exist_ok=True)
os.makedirs(SEARCH_HISTORY_DIR, exist_ok=True)
os.makedirs(DOCX_JURISPRUDENCE_DIR, exist_ok=True)
os.makedirs(JSON_JURISPRUDENCE_DIR, exist_ok=True)
