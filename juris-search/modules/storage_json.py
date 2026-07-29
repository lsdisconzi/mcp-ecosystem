"""JSON storage pipeline: extracts text from source files into JSON records."""

import hashlib
import mimetypes
import logging
from pathlib import Path
from typing import Dict, Any, List

from modules.config import (
    DOWNLOADS_BASE_DIR,
    JSON_JURISPRUDENCE_DIR,
    JSON_STATE_PATH,
    JSON_INDEX_PATH,
)
from modules import state as _state
from modules.utils import _utc_now, _read_json_file, _write_json_file
from modules.storage_utils import (
    _source_signature,
    _discover_json_sources,
    _resolve_json_target,
    _load_source_sidecar,
    _extract_text_for_json_source,
    _build_json_entry,
)

logger = logging.getLogger("juris-search.storage_json")


def _process_json_pipeline(force_rebuild: bool = False) -> Dict[str, Any]:
    with _state._docx_watch_lock:
        state = _read_json_file(JSON_STATE_PATH, {"processed": {}, "failed": {}})
        if not isinstance(state, dict):
            state = {"processed": {}, "failed": {}}
        processed = state.get("processed") if isinstance(state.get("processed"), dict) else {}
        failed = state.get("failed") if isinstance(state.get("failed"), dict) else {}

        converted = 0
        skipped = 0
        failed_count = 0
        entries: List[Dict[str, Any]] = []
        current_rel_paths = set()

        for source_path in _discover_json_sources():
            source_rel = str(source_path.relative_to(Path(DOWNLOADS_BASE_DIR)))
            current_rel_paths.add(source_rel)
            source_sig = _source_signature(source_path)
            target_json = _resolve_json_target(source_path)

            already_processed = processed.get(source_rel) == source_sig and target_json.is_file()
            previous_failure = failed.get(source_rel)
            unchanged_failed = (
                isinstance(previous_failure, dict)
                and previous_failure.get("sig") == source_sig
                and not force_rebuild
                and not target_json.is_file()
            )

            if already_processed and not force_rebuild:
                skipped += 1
                entries.append(
                    _build_json_entry(
                        source_path,
                        source_sig,
                        target_json,
                        status="ready",
                        parser=(previous_failure or {}).get("parser"),
                    )
                )
                continue

            if unchanged_failed:
                failed_count += 1
                entries.append(
                    _build_json_entry(
                        source_path,
                        source_sig,
                        target_json,
                        status="failed",
                        parser=previous_failure.get("parser"),
                        error=previous_failure.get("error"),
                    )
                )
                continue

            try:
                text, parser, docx_fallback = _extract_text_for_json_source(source_path)
                source_metadata = _load_source_sidecar(source_path)
                content_type = (
                    source_metadata.get("content_type")
                    or mimetypes.guess_type(source_path.name)[0]
                    or "application/octet-stream"
                )

                payload = {
                    "id": hashlib.sha1(source_rel.encode("utf-8")).hexdigest()[:16],
                    "generated_at": _utc_now(),
                    "source_path": str(source_path),
                    "source_relative": source_rel,
                    "source_signature": source_sig,
                    "source_metadata": source_metadata,
                    "source_sidecar_path": str(Path(str(source_path) + ".metadata.json")),
                    "content_type": content_type,
                    "parser": parser,
                    "docx_fallback": docx_fallback,
                    "text": text,
                    "text_chars": len(text),
                }

                _write_json_file(target_json, payload)
                processed[source_rel] = source_sig
                failed.pop(source_rel, None)
                converted += 1
                entries.append(_build_json_entry(source_path, source_sig, target_json, status="ready", parser=parser))
            except Exception as exc:
                failed[source_rel] = {
                    "sig": source_sig,
                    "parser": failed.get(source_rel, {}).get("parser"),
                    "error": str(exc),
                    "last_attempt": _utc_now(),
                }
                failed_count += 1
                entries.append(_build_json_entry(source_path, source_sig, target_json, status="failed", error=str(exc)))

        processed = {k: v for k, v in processed.items() if k in current_rel_paths}
        failed = {k: v for k, v in failed.items() if k in current_rel_paths}

        index_payload = {
            "generated_at": _utc_now(),
            "source_download_dir": DOWNLOADS_BASE_DIR,
            "json_dir": JSON_JURISPRUDENCE_DIR,
            "total_entries": len(entries),
            "ready_entries": sum(1 for e in entries if e.get("status") == "ready"),
            "failed_entries": sum(1 for e in entries if e.get("status") == "failed"),
            "entries": entries,
        }

        _write_json_file(JSON_INDEX_PATH, index_payload)
        _write_json_file(JSON_STATE_PATH, {
            "processed": processed,
            "failed": failed,
            "updated_at": _utc_now(),
        })

        return {
            "scanned": len(entries),
            "converted": converted,
            "skipped": skipped,
            "failed": failed_count,
            "index_file": str(JSON_INDEX_PATH),
            "json_dir": JSON_JURISPRUDENCE_DIR,
        }
