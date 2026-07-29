"""DOCX storage pipeline: converts source documents to normalized DOCX."""

import shutil
import subprocess
import tempfile
import logging
from pathlib import Path
from typing import Dict, Any

from modules.config import (
    DOWNLOADS_BASE_DIR,
    DOCX_JURISPRUDENCE_DIR,
    DOCX_STATE_PATH,
    DOCX_INDEX_PATH,
    DOCX_NORMALIZE_FOR_COMPAT,
)
from modules import state as _state
from modules.utils import _utc_now, _read_json_file, _write_json_file
from modules.file_extraction import _find_libreoffice_binary
from modules.storage_utils import (
    _source_signature,
    _discover_doc_sources,
    _resolve_docx_target,
    _load_source_sidecar,
    _build_docx_entry,
)

logger = logging.getLogger("juris-search.storage_docx")


def _normalize_docx_for_compatibility(source_docx: Path, target_docx: Path) -> bool:
    libreoffice = _find_libreoffice_binary()
    if not libreoffice:
        return False

    with tempfile.TemporaryDirectory(prefix="juris_docx_norm_") as tmpdir:
        tmp_root = Path(tmpdir)
        tmp_input = tmp_root / source_docx.name
        tmp_outdir = tmp_root / "out"
        tmp_outdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_docx, tmp_input)

        cmd = [
            libreoffice,
            "--headless",
            "--convert-to", "docx",
            "--outdir", str(tmp_outdir),
            str(tmp_input),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if proc.returncode != 0:
            error_text = (proc.stderr or proc.stdout or "unknown LibreOffice error").strip()
            logger.warning("DOCX normalization failed for %s: %s", source_docx, error_text)
            return False

        normalized_docx = tmp_outdir / (tmp_input.stem + ".docx")
        if not normalized_docx.is_file():
            logger.warning("DOCX normalization produced no output for %s", source_docx)
            return False

        shutil.copy2(normalized_docx, target_docx)
        return True


def _convert_source_to_docx_copy(source_path: Path, target_docx: Path) -> None:
    target_docx.parent.mkdir(parents=True, exist_ok=True)
    source_suffix = source_path.suffix.lower()

    if source_suffix == ".docx":
        if DOCX_NORMALIZE_FOR_COMPAT and _normalize_docx_for_compatibility(source_path, target_docx):
            return
        shutil.copy2(source_path, target_docx)
        return

    if source_suffix != ".doc":
        raise RuntimeError(f"Unsupported source extension: {source_suffix}")

    libreoffice = _find_libreoffice_binary()
    if not libreoffice:
        raise RuntimeError("LibreOffice not found; install it to convert .doc to .docx")

    with tempfile.TemporaryDirectory(prefix="juris_docx_") as tmpdir:
        tmp_input = Path(tmpdir) / source_path.name
        shutil.copy2(source_path, tmp_input)

        cmd = [
            libreoffice,
            "--headless",
            "--convert-to", "docx",
            "--outdir", str(target_docx.parent),
            str(tmp_input),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if proc.returncode != 0:
            error_text = (proc.stderr or proc.stdout or "unknown LibreOffice error").strip()
            raise RuntimeError(f"LibreOffice conversion failed: {error_text}")

    generated_docx = target_docx.parent / (source_path.stem + ".docx")
    if not generated_docx.is_file():
        raise RuntimeError(f"Converted file not found at {generated_docx}")

    if generated_docx != target_docx:
        if target_docx.exists():
            target_docx.unlink()
        generated_docx.replace(target_docx)


def _process_docx_pipeline(force_rebuild: bool = False) -> Dict[str, Any]:
    with _state._docx_watch_lock:
        state = _read_json_file(DOCX_STATE_PATH, {"processed": {}, "failed": {}})
        if not isinstance(state, dict):
            state = {"processed": {}, "failed": {}}
        processed = state.get("processed") if isinstance(state.get("processed"), dict) else {}
        failed = state.get("failed") if isinstance(state.get("failed"), dict) else {}

        converted = 0
        skipped = 0
        failed_count = 0
        entries = []
        current_rel_paths = set()

        for source_path in _discover_doc_sources():
            source_rel = str(source_path.relative_to(Path(DOWNLOADS_BASE_DIR)))
            current_rel_paths.add(source_rel)
            source_sig = _source_signature(source_path)
            target_docx = _resolve_docx_target(source_path)

            already_processed = processed.get(source_rel) == source_sig and target_docx.is_file()
            previous_failure = failed.get(source_rel)
            unchanged_failed = (
                isinstance(previous_failure, dict)
                and previous_failure.get("sig") == source_sig
                and not force_rebuild
                and not target_docx.is_file()
            )

            if already_processed and not force_rebuild:
                skipped += 1
                entries.append(_build_docx_entry(source_path, source_sig, target_docx, status="ready"))
                continue

            if unchanged_failed:
                failed_count += 1
                entries.append(
                    _build_docx_entry(
                        source_path,
                        source_sig,
                        target_docx,
                        status="failed",
                        error=previous_failure.get("error"),
                    )
                )
                continue

            try:
                _convert_source_to_docx_copy(source_path, target_docx)
                processed[source_rel] = source_sig
                failed.pop(source_rel, None)
                converted += 1
                entries.append(_build_docx_entry(source_path, source_sig, target_docx, status="ready"))
            except Exception as exc:
                failed[source_rel] = {
                    "sig": source_sig,
                    "error": str(exc),
                    "last_attempt": _utc_now(),
                }
                failed_count += 1
                entries.append(
                    _build_docx_entry(
                        source_path,
                        source_sig,
                        target_docx,
                        status="failed",
                        error=str(exc),
                    )
                )

        processed = {k: v for k, v in processed.items() if k in current_rel_paths}
        failed = {k: v for k, v in failed.items() if k in current_rel_paths}

        index_payload = {
            "generated_at": _utc_now(),
            "source_download_dir": DOWNLOADS_BASE_DIR,
            "docx_dir": DOCX_JURISPRUDENCE_DIR,
            "watch_enabled": True,
            "watch_interval_seconds": 10,
            "normalize_compat": DOCX_NORMALIZE_FOR_COMPAT,
            "total_entries": len(entries),
            "ready_entries": sum(1 for e in entries if e.get("status") == "ready"),
            "failed_entries": sum(1 for e in entries if e.get("status") == "failed"),
            "entries": entries,
        }

        _write_json_file(DOCX_INDEX_PATH, index_payload)
        _write_json_file(DOCX_STATE_PATH, {
            "processed": processed,
            "failed": failed,
            "updated_at": _utc_now(),
        })

        return {
            "scanned": len(entries),
            "converted": converted,
            "skipped": skipped,
            "failed": failed_count,
            "index_file": str(DOCX_INDEX_PATH),
            "docx_dir": DOCX_JURISPRUDENCE_DIR,
            "normalize_compat": DOCX_NORMALIZE_FOR_COMPAT,
        }
