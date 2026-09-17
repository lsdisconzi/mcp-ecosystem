"""Reconcile a bundle's derived segment artifacts with its violation JSON.

``<bundle>/<violation_id>.json`` is the only statement of which segments a pack
cites. Two other artifacts in the bundle describe the same set:

  * ``segments_manifest.json`` — one row per cited segment (the canonical id, the
    vault's ``legacy_segment_id`` it was re-anchored from, the role in the
    argument, both texts, the anchor's notes) plus the ``transcript_files`` map
    from source id to bundle filename.
  * ``Transcripts/<transcript_id>.json`` — the transcript itself.

Both were produced once, by ``examples/vault_to_bundle.py`` at conversion time,
and nothing rewrote them afterwards. So every segment added in S2 with
``build_evidence_layer_tool`` (whose ``source_uri`` names
``data/transcripts/json/…`` rather than ``Transcripts/…``) landed in the
violation alone: the manifest kept its conversion-time row set and ``Transcripts/``
gained no file for the transcript that segment came from.
``examples/validate_preflight.py`` treats exactly that as a failure —
``check_bundle_segments`` wants the two id sets to be *equal*, and
``check_transcripts`` wants every referenced ``seg-N`` present in the file
``transcript_files`` names.

This module is the writer that puts them back in step, derived from the
violation, which makes it idempotent: run it twice and the second run writes
nothing (the files are compared byte-for-byte first, so mtimes stay put too).

Choices worth knowing before changing it:

  * The manifest is rebuilt **strictly** from ``violation["segments"]``. A row
    the violation no longer cites is dropped, because equality is the contract
    ``check_bundle_segments`` enforces and a manifest row with no segment behind
    it is the drift S2 renders as "not in violation JSON".
  * ``legacy_segment_id`` is never *derived* — it is carried across from the
    manifest already on disk, joined by canonical id. A segment with no manifest
    ancestor gets ``""``, which every reader treats as "no legacy id".
  * The transcript written into the bundle holds **only the cited segments**, so
    the bundle is self-contained and the file can never disagree with the
    manifest about which segments exist.
  * Deleting a segment rewrites the manifest but does **not** delete the
    transcript file it came from; that is reported as a warning rather than done
    behind the caller's back.
  * A transcript whose bundle path is a symlink into the shared corpus is
    *unlinked* before the subset is written. Writing through the link would
    overwrite ``data/transcripts/json/<name>.json`` for every bundle at once.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import Violation

#: Bundle subdirectory holding the transcripts this pack cites.
TRANSCRIPTS_DIR = "Transcripts"
#: The converter's per-segment provenance record.
MANIFEST_NAME = "segments_manifest.json"
#: Used only when neither the manifest on disk nor the violation states one.
MANIFEST_SCHEMA_VERSION = "4.0"

#: Free-form slot in a canonical transcript document (``"metadata"`` is already
#: arbitrary, so the subset marker needs no schema change).
_SUBSET_KEY = "violation_refiner_subset"


def sync_segment_artifacts(violation: Violation | dict, bundle_root: Path | str) -> dict:
    """Rewrite ``segments_manifest.json`` and ``Transcripts/`` from `violation`.

    Returns ``{"segments_manifest", "manifest_segments", "manifest_changed",
    "transcripts": [{"transcript_id", "path", "segments", "changed"}],
    "warnings"}``. Nothing is written when the violation cites no segments, so a
    bundle that has no segment artifacts never grows an empty manifest.
    """
    doc = _as_doc(violation)
    root = Path(bundle_root)
    manifest_path = root / MANIFEST_NAME
    warnings: list[str] = []
    result: dict[str, Any] = {
        "segments_manifest": None,
        "manifest_segments": 0,
        "manifest_changed": False,
        "transcripts": [],
        "warnings": warnings,
    }

    previous = _read_json(manifest_path)
    previous = previous if isinstance(previous, dict) else {}
    prev_rows = {
        str(row.get("segment_id")): row
        for row in (previous.get("segments") or [])
        if isinstance(row, dict) and row.get("segment_id")
    }
    prev_files = {
        str(k): str(v)
        for k, v in (previous.get("transcript_files") or {}).items()
        if k and v
    }

    grouped = _group_by_transcript(doc, warnings)
    if not grouped:
        if previous:
            warnings.append(
                f"the violation cites no segments but the bundle still carries {MANIFEST_NAME}; "
                "it was left as it is rather than emptied"
            )
        return result

    stale = _legacy_id_collision(grouped, prev_rows)
    if stale:
        shown = ", ".join(stale[:3]) + ("…" if len(stale) > 3 else "")
        warnings.append(
            "nothing was written: the violation cites the vault's legacy segment ids "
            f"({shown}) while {MANIFEST_NAME} records the converter's canonical ones, "
            "so this violation did not come from examples/vault_to_bundle.py. Re-run "
            "the converter for this bundle before refining it again."
        )
        return result

    rows = [
        _manifest_row(seg, prev_rows.get(str(seg.get("segment_id"))))
        for src_id in grouped
        for seg in grouped[src_id]
    ]

    transcripts_dir = root / TRANSCRIPTS_DIR
    files: dict[str, str] = {}
    entries: list[dict] = []
    for src_id, segs in grouped.items():
        filename = _transcript_filename(src_id, segs, prev_files)
        dest = transcripts_dir / filename
        payload = _subset_document(
            src_id, segs, dest, root, doc.get("violation_id"), warnings
        )
        files[src_id] = filename
        entries.append({
            "transcript_id": src_id,
            "path": str(dest),
            "segments": [seg["_local_id"] for seg in segs],
            "changed": _write_json(dest, payload),
        })

    _warn_about_uncited_transcripts(transcripts_dir, files, warnings)

    manifest = {
        "schema_version": (
            previous.get("schema_version")
            or str(doc.get("schema_version") or MANIFEST_SCHEMA_VERSION)
        ),
        "violation_id": str(doc.get("violation_id") or ""),
        "matched_audio_sources": sorted(grouped),
        "total_segments_matched": len(rows),
        "segments": rows,
        "clip_offset_deltas": previous.get("clip_offset_deltas") or {},
        "transcript_files": files,
    }
    result.update(
        segments_manifest=str(manifest_path),
        manifest_segments=len(rows),
        manifest_changed=_write_json(manifest_path, manifest),
        transcripts=entries,
    )
    return result


# ---------------------------------------------------------------------------
# The violation's side
# ---------------------------------------------------------------------------

def _as_doc(violation: Violation | dict) -> dict:
    if isinstance(violation, Violation):
        return json.loads(violation.model_dump_json())
    return dict(violation or {})


def _group_by_transcript(doc: dict, warnings: list[str]) -> dict[str, list[dict]]:
    """``{transcript_id: [segment, …]}`` in the violation's own order.

    A segment whose id is not ``<transcript_id>.<local_id>`` cannot be placed in
    a transcript, so it is reported and skipped rather than guessed at — the same
    split ``validation.v01_segment_resolution`` and
    ``validate_preflight._segment_src`` use (first dot).
    """
    grouped: dict[str, list[dict]] = {}
    for seg in doc.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        scoped = str(seg.get("segment_id") or "")
        src_id, sep, local_id = scoped.partition(".")
        if not (sep and src_id and local_id):
            warnings.append(
                f"segment id {scoped!r} is not '<transcript_id>.<local_id>' — "
                "it is in no manifest row and no transcript"
            )
            continue
        grouped.setdefault(src_id, []).append({**seg, "_local_id": local_id})
    return grouped


def _legacy_id_collision(grouped: dict[str, list[dict]], prev_rows: dict[str, dict]) -> list[str]:
    """The cited ids the manifest records *only* as legacy ids.

    ``validate_preflight.check_bundle_segments`` reports a bundle whose violation
    holds the vault's pre-re-anchor ids and none of the converter's — the
    fingerprint of a violation that was never converted, whether a legacy tool
    wrote it or the loader recovered it from a ``.bak`` after a failed write.
    Rebuilding the manifest from that violation would make the check agree with
    the drift and the one silent failure it exists to catch would go unseen, so
    the sync stops instead: the manifest is the pipeline's independent record of
    the conversion, not a copy of whatever JSON is in the bundle.
    """
    actual = {
        str(seg.get("segment_id") or "")
        for segs in grouped.values()
        for seg in segs
    }
    canonical = set(prev_rows)
    legacy = {
        str(row.get("legacy_segment_id"))
        for row in prev_rows.values()
        if row.get("legacy_segment_id")
    }
    if not legacy or actual & canonical:
        return []
    return sorted(actual & legacy)


def _manifest_row(seg: dict, previous: dict | None) -> dict:
    """One manifest row, in the converter's field order.

    Everything but ``legacy_segment_id`` comes from the violation; that one field
    is the vault's pre-re-anchor id, which no live artifact states, so it is
    carried over from the manifest already on disk and never re-derived.
    """
    return {
        "segment_id": str(seg.get("segment_id") or ""),
        "legacy_segment_id": (previous or {}).get("legacy_segment_id") or "",
        "role_in_argument": seg.get("role_in_argument"),
        "audio_offset_start": seg.get("audio_offset_start"),
        "audio_offset_end": seg.get("audio_offset_end"),
        "verbatim_es": seg.get("verbatim_es"),
        "translation_en": seg.get("translation_en"),
        "transcription_notes": seg.get("transcription_notes"),
    }


# ---------------------------------------------------------------------------
# The transcript's side
# ---------------------------------------------------------------------------

def _transcript_filename(src_id: str, segs: list[dict], prev_files: dict[str, str]) -> str:
    """The bundle filename for `src_id`'s transcript.

    The previous manifest wins — it is what ``transcript_files`` promised, and
    what the segments' ``source_uri`` already point at. Then the ``source_uri``
    the segments carry (``Transcripts/<name>.json`` in a converted bundle,
    ``data/transcripts/json/<name>.json`` for one added in S2), then the corpus
    convention ``<transcript_id>.json``, which is the same string either way.
    """
    promised = prev_files.get(src_id)
    if promised and promised.endswith(".json"):
        return promised
    for seg in segs:
        rel = str(seg.get("source_uri") or "").split("#", 1)[0]
        name = Path(rel).name if rel else ""
        if name.endswith(".json"):
            return name
    return f"{src_id}.json"


def _source_candidates(bundle_root: Path, dest: Path, src_id: str, segs: list[dict]) -> list[Path]:
    """Where a full copy of this transcript can be read from, best first.

    The bundle's own links and the repo's corpus are the same file, so both are
    listed; `_subset_document` only uses them for metadata and per-segment extras
    and then overrides the plan-relevant fields anyway. The point of the corpus
    candidate is stability: the first sync replaces the link with a *subset*, so
    without it the second run would read the subset and report
    ``source_segment_count`` as the cited count instead of the transcript's. The
    file would keep changing on every run.
    """
    out: list[Path] = []

    def add(path: Path | None) -> None:
        if path is not None and path not in out:
            out.append(path)

    if dest.is_symlink():
        try:
            add(dest.resolve())  # the link's target, i.e. the corpus
        except OSError:  # broken link: nothing to read through it
            pass
    add(bundle_root.parent.parent / "data" / "transcripts" / "json" / f"{src_id}.json")
    add(dest)
    repo_root = bundle_root.parent.parent
    for seg in segs:
        rel = str(seg.get("source_uri") or "").split("#", 1)[0]
        if not rel or rel.startswith("/"):
            continue
        add(bundle_root / rel)
        add(repo_root / rel)
    return out


def _subset_document(
    src_id: str,
    segs: list[dict],
    dest: Path,
    bundle_root: Path,
    violation_id: str | None,
    warnings: list[str],
) -> dict:
    """A canonical transcript document holding only the segments `segs` cites.

    Text, offsets and speaker come from the violation, so the file can never
    disagree with the segment it exists for (V02 substring-matches the cited
    ``verbatim_es`` against this file). Everything else — the top-level
    ``source_file``/``participants``/… metadata, and per-segment extras such as
    ``segment_datetime`` — is carried over from the fullest source available.
    """
    sources: list[dict] = []
    for cand in _source_candidates(bundle_root, dest, src_id, segs):
        loaded = _read_json(cand)
        if isinstance(loaded, dict) and isinstance(loaded.get("segments"), list):
            sources.append(loaded)
    base = sources[0] if sources else {}
    if not sources:
        warnings.append(
            f"{src_id}: no full transcript was found for it, so the bundle's "
            f"Transcripts/{dest.name} holds the cited segments and the text the "
            "violation states, with no other transcript metadata"
        )

    by_local_id: dict[str, dict] = {}
    for source in sources:
        for row in source.get("segments") or []:
            if isinstance(row, dict) and "index" in row:
                by_local_id.setdefault(f"seg-{row['index']}", row)

    out = {k: v for k, v in base.items() if k not in ("segments", "metadata")}
    out["transcript_id"] = src_id

    kept: list[dict] = []
    for seg in segs:
        local_id = seg["_local_id"]
        row = dict(by_local_id.get(local_id) or {})
        index = _local_index(local_id)
        if index is None:
            warnings.append(
                f"{src_id}: local id {local_id!r} is not 'seg-<n>', so the bundle's "
                "transcript has no index to file it under and V01 cannot resolve it"
            )
        else:
            row["index"] = index
        row["speaker"] = seg.get("speaker") or row.get("speaker") or "unknown"
        start = seg.get("audio_offset_start")
        end = seg.get("audio_offset_end")
        if start is not None:
            row["start"] = start
        if end is not None:
            row["end"] = end
        if start is not None and end is not None:
            row["duration"] = round(float(end) - float(start), 3)
        row.setdefault("reviewed", True)
        row["text"] = seg.get("verbatim_es") or row.get("text") or ""
        kept.append(row)
    kept.sort(key=lambda r: (r.get("index") is None, r.get("index") or 0))
    out["segments"] = kept

    metadata = dict(base.get("metadata")) if isinstance(base.get("metadata"), dict) else {}
    metadata[_SUBSET_KEY] = {
        "note": (
            "The segments of this transcript that the pack cites. The full "
            "transcript is not part of the bundle."
        ),
        "violation_id": violation_id,
        "segments": [seg["_local_id"] for seg in segs],
        "source_segment_count": _source_segment_count(sources),
    }
    out["metadata"] = metadata
    return out


def _source_segment_count(sources: list[dict]) -> int | None:
    """How many segments the full transcript has, or ``None`` if it was not found.

    Read from a *full* copy only. Once the sync has run, the bundle's file is a
    subset of itself, so the second run would otherwise read its own output and
    report the cited count (2) where the first run reported the transcript's (6)
    — a file that changes on every run with identical input. When no full copy is
    reachable the previous subset's own marker is carried forward instead, which
    keeps "unknown" unknown rather than promoting it to a number later.
    """
    full = [s for s in sources if not _is_subset(s)]
    if full:
        return max(len(s.get("segments") or []) for s in full)
    for source in sources:
        marker = (source.get("metadata") or {}).get(_SUBSET_KEY)
        if isinstance(marker, dict) and marker.get("source_segment_count"):
            return int(marker["source_segment_count"])
    return None


def _is_subset(doc: dict) -> bool:
    """True when `doc` is a copy this module wrote, not a full transcript."""
    return isinstance((doc.get("metadata") or {}).get(_SUBSET_KEY), dict)


def _local_index(local_id: str) -> int | None:
    """``"seg-12"`` → ``12``, the canonical document's ``segments[].index``."""
    prefix, _, tail = local_id.partition("-")
    if prefix != "seg" or not tail.isdigit():
        return None
    return int(tail)


def _warn_about_uncited_transcripts(
    transcripts_dir: Path, files: dict[str, str], warnings: list[str]
) -> None:
    if not transcripts_dir.is_dir():
        return
    cited = set(files.values())
    strays = sorted(
        p.name for p in transcripts_dir.iterdir() if p.is_file() or p.is_symlink()
    )
    strays = [name for name in strays if name not in cited]
    if not strays:
        return
    shown = ", ".join(strays[:4]) + ("…" if len(strays) > 4 else "")
    warnings.append(
        f"{len(strays)} file(s) in {TRANSCRIPTS_DIR}/ are cited by no segment "
        f"({shown}) — left in place rather than deleted"
    )


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _dumps(payload: Any) -> bytes:
    """The converter's exact JSON style, minus the trailing newline it omits."""
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _write_json(path: Path, payload: Any) -> bool:
    """Write `payload` as JSON, replacing a symlink instead of following it.

    ``Path.write_bytes`` writes *through* a symlink, so a filtered transcript
    written over the bundle's link into the shared corpus would rewrite
    ``data/transcripts/json/<name>.json`` — for every bundle at once. Returns
    False when the file already holds exactly these bytes, so a re-run leaves
    the file (and its mtime, and MANIFEST.txt's hashes) untouched.
    """
    blob = _dumps(payload)
    if path.is_symlink():
        path.unlink()
    else:
        try:
            if path.read_bytes() == blob:
                return False
        except OSError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(blob)
    os.replace(tmp, path)
    return True
