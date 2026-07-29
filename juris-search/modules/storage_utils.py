"""Shared storage utilities for DOCX and JSON pipelines."""

import os
import re
import json
import hashlib
import mimetypes
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

from modules.config import (
    DOWNLOADS_BASE_DIR,
    DOCX_JURISPRUDENCE_DIR,
    JSON_JURISPRUDENCE_DIR,
    SEARCH_HISTORY_DIR,
    DOCX_INDEX_PATH,
    JSON_INDEX_PATH,
    EXPORT_LINKS_ENABLED,
    SHARED_LINK_ROOT,
    AGENTS_LINK_ROOT,
)
from modules import state as _state
from modules.utils import (
    _utc_now,
    _read_json_file,
    _write_json_file,
    _ensure_named_symlink,
)
from modules.file_extraction import (
    _extract_text_from_docx_path,
    _extract_text_from_pdf_path,
    _extract_text_from_html_bytes,
)


# ── Symlink export ──────────────────────────────────────────────────────────

def _sync_export_links() -> List[Dict[str, Any]]:
    if not EXPORT_LINKS_ENABLED:
        _state._link_sync_report = [{
            "status": "disabled",
            "link": None,
            "target": None,
        }]
        return _state._link_sync_report

    links_to_create = {
        "downloads": Path(DOWNLOADS_BASE_DIR),
        "docx": Path(DOCX_JURISPRUDENCE_DIR),
        "json": Path(JSON_JURISPRUDENCE_DIR),
        "searches_history": Path(SEARCH_HISTORY_DIR),
    }

    target_roots = []
    for root_raw in [SHARED_LINK_ROOT, AGENTS_LINK_ROOT]:
        root_clean = (root_raw or "").strip()
        if root_clean:
            target_roots.append(Path(root_clean))

    report: List[Dict[str, Any]] = []
    for root in target_roots:
        for name, source in links_to_create.items():
            entry = _ensure_named_symlink(source, root / name)
            entry["root"] = str(root)
            entry["name"] = name
            report.append(entry)

    _state._link_sync_report = report
    return report


# ── Source discovery ────────────────────────────────────────────────────────

def _source_signature(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _discover_doc_sources() -> List[Path]:
    root = Path(DOWNLOADS_BASE_DIR)
    if not root.is_dir():
        return []

    sources = []
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        suffix = file_path.suffix.lower()
        if suffix in {".doc", ".docx"}:
            sources.append(file_path)

    sources.sort(key=lambda p: str(p))
    return sources


def _discover_json_sources() -> List[Path]:
    root = Path(DOWNLOADS_BASE_DIR)
    if not root.is_dir():
        return []

    supported = {
        ".doc", ".docx", ".pdf", ".html", ".htm", ".txt",
        ".rtf", ".md", ".json", ".xml",
    }

    sources: List[Path] = []
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.name.endswith(".metadata.json"):
            continue
        if file_path.suffix.lower() in supported:
            sources.append(file_path)

    sources.sort(key=lambda p: str(p))
    return sources


# ── Path resolution ─────────────────────────────────────────────────────────

def _resolve_docx_target(source_path: Path) -> Path:
    rel = source_path.relative_to(Path(DOWNLOADS_BASE_DIR))
    return Path(DOCX_JURISPRUDENCE_DIR) / rel.with_suffix(".docx")


def _resolve_json_target(source_path: Path) -> Path:
    rel = source_path.relative_to(Path(DOWNLOADS_BASE_DIR))
    return Path(JSON_JURISPRUDENCE_DIR) / rel.with_suffix(".json")


# ── Sidecar loading ─────────────────────────────────────────────────────────

def _load_source_sidecar(source_path: Path) -> Dict[str, Any]:
    sidecar_path = Path(str(source_path) + ".metadata.json")
    payload = _read_json_file(sidecar_path, {})
    return payload if isinstance(payload, dict) else {}


# ── Text extraction bridge (used by JSON pipeline) ──────────────────────────

def _extract_text_for_json_source(source_path: Path) -> Tuple[str, str, Optional[str]]:
    suffix = source_path.suffix.lower()

    if suffix == ".doc":
        fallback_docx = _resolve_docx_target(source_path)
        if not fallback_docx.is_file():
            raise RuntimeError("No DOCX fallback available for DOC source")
        text = _extract_text_from_docx_path(fallback_docx)
        return text, "doc_via_docx", str(fallback_docx)

    if suffix == ".docx":
        return _extract_text_from_docx_path(source_path), "docx", None

    if suffix == ".pdf":
        return _extract_text_from_pdf_path(source_path), "pdf", None

    if suffix in {".html", ".htm"}:
        with open(source_path, "rb") as f:
            raw = f.read()
        text, parser = _extract_text_from_html_bytes(raw)
        return text, parser, None

    if suffix in {".txt", ".rtf", ".md", ".json", ".xml"}:
        with open(source_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(), "plain_text", None

    raise RuntimeError(f"Unsupported source extension for JSON conversion: {suffix}")


# ── Entry builders ──────────────────────────────────────────────────────────

def _build_docx_entry(
    source_path: Path,
    source_sig: str,
    target_docx: Path,
    status: str,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    source_rel = str(source_path.relative_to(Path(DOWNLOADS_BASE_DIR)))
    target_rel = str(target_docx.relative_to(Path(DOCX_JURISPRUDENCE_DIR))) if target_docx.exists() else None
    source_metadata = _load_source_sidecar(source_path)

    return {
        "id": hashlib.sha1(source_rel.encode("utf-8")).hexdigest()[:16],
        "status": status,
        "error": error,
        "source_doc_path": str(source_path),
        "source_doc_relative": source_rel,
        "source_signature": source_sig,
        "source_sidecar_path": str(Path(str(source_path) + ".metadata.json")),
        "source_metadata": source_metadata,
        "docx_path": str(target_docx) if target_docx.exists() else None,
        "docx_relative": target_rel,
        "processed_at": _utc_now(),
    }


def _build_json_entry(
    source_path: Path,
    source_sig: str,
    target_json: Path,
    status: str,
    parser: Optional[str] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    source_rel = str(source_path.relative_to(Path(DOWNLOADS_BASE_DIR)))
    target_rel = str(target_json.relative_to(Path(JSON_JURISPRUDENCE_DIR))) if target_json.exists() else None

    return {
        "id": hashlib.sha1(source_rel.encode("utf-8")).hexdigest()[:16],
        "status": status,
        "error": error,
        "parser": parser,
        "source_path": str(source_path),
        "source_relative": source_rel,
        "source_signature": source_sig,
        "source_sidecar_path": str(Path(str(source_path) + ".metadata.json")),
        "json_path": str(target_json) if target_json.exists() else None,
        "json_relative": target_rel,
        "processed_at": _utc_now(),
    }


# ── Stats collectors ────────────────────────────────────────────────────────

def _collect_download_stats(base_dir: str) -> Dict[str, Any]:
    file_count = 0
    total_size = 0

    for root, _, files in os.walk(base_dir):
        for name in files:
            path = os.path.join(root, name)
            if not os.path.isfile(path):
                continue
            file_count += 1
            total_size += os.path.getsize(path)

    return {
        "downloaded_files": file_count,
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "save_directory": base_dir,
        "jobs_total": len(_state.search_jobs),
        "jobs_running": sum(1 for j in _state.search_jobs.values() if j.get("status") in {"running", "queued"}),
        "jobs_completed": sum(1 for j in _state.search_jobs.values() if j.get("status") == "completed"),
        "jobs_error": sum(1 for j in _state.search_jobs.values() if j.get("status") == "error"),
    }


def _collect_history_stats() -> Dict[str, Any]:
    history_dir = Path(SEARCH_HISTORY_DIR)
    history_dir.mkdir(parents=True, exist_ok=True)

    items = [p for p in history_dir.glob("search_*.json") if p.is_file()]
    items.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    return {
        "search_history_dir": str(history_dir),
        "search_history_count": len(items),
        "latest_search_history": str(items[0]) if items else None,
    }


def _collect_docx_stats() -> Dict[str, Any]:
    payload = _read_json_file(DOCX_INDEX_PATH, {})
    if not isinstance(payload, dict):
        payload = {}

    return {
        "docx_dir": DOCX_JURISPRUDENCE_DIR,
        "docx_index_file": str(DOCX_INDEX_PATH),
        "docx_total_entries": payload.get("total_entries", 0),
        "docx_ready_entries": payload.get("ready_entries", 0),
        "docx_failed_entries": payload.get("failed_entries", 0),
        "docx_index_generated_at": payload.get("generated_at"),
    }


def _collect_json_stats() -> Dict[str, Any]:
    payload = _read_json_file(JSON_INDEX_PATH, {})
    if not isinstance(payload, dict):
        payload = {}

    return {
        "json_dir": JSON_JURISPRUDENCE_DIR,
        "json_index_file": str(JSON_INDEX_PATH),
        "json_total_entries": payload.get("total_entries", 0),
        "json_ready_entries": payload.get("ready_entries", 0),
        "json_failed_entries": payload.get("failed_entries", 0),
        "json_index_generated_at": payload.get("generated_at"),
    }


def _collect_link_stats() -> Dict[str, Any]:
    return {
        "links_enabled": EXPORT_LINKS_ENABLED,
        "shared_link_root": SHARED_LINK_ROOT,
        "agents_link_root": AGENTS_LINK_ROOT,
        "link_sync_report": _state._link_sync_report,
    }
