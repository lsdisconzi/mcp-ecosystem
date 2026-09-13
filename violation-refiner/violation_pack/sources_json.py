"""JSON transcript source — the **authoritative** transcript reader.

Corpus
------
``transcription/data/transcripts/*.json`` (27 files), reached from this project
through the per-file symlinks under ``violation-refiner/data/transcripts/json/``.
See ``docs/data_source_of_truth.md`` for the ownership rule.

Why this supersedes the HTML reader
-----------------------------------
The rendered HTML under ``data/transcripts/html/`` is a *vendored snapshot*: it
can drift from the canonical JSON, and it carries strictly less information.
The JSON carries, and this reader exposes:

* the canonical ``transcript_id`` — which makes ``source_id()`` line up with the
  shared Qdrant collections. ``layers.py`` composes
  ``EvidenceSegment.segment_id`` as ``f"{source_id()}.{local_id}"``, so a JSON
  source yields ``"<transcript_id>.seg-<index>"`` — byte-identical to the
  ``reviewed_transcripts`` ``segment_id`` payload key. An HTML source yields
  ``"STG-1.seg-0"``, which joins to nothing.
* ``participants`` (with ``segment_labels``) — so a canonical ``SPK-…`` speaker id
  can be resolved offline instead of stopping at the raw segment label.
* per-segment ``reviewed`` / ``correction_note`` / ``backchannel_events``, and the
  parent ``case_id`` / ``narrative_id`` / ``violations_cited`` / ``forensic_clusters``.

Schema
------
Canonical v1 (verified against all 27 files on 2026-09-13)::

    {
      "transcript_id": str, "source_file": str, "source_path": str,
      "language": "pt"|"es"|"en", "title": str, "subtitle": str,
      "recording_datetime": iso8601, "location": str,
      "case_id": str, "narrative_id": str, "chronological_order": int,
      "prior_stage": str, "next_stage": str, "reviewed": bool,
      "participants": [{"canonical_name", "role", "speaker_label",
                        "speaker_id", "segment_labels": [str]}],
      "violations_cited": [str], "tags": [str],
      "forensic_clusters": [...], "key_evidentiary_findings": [...],
      "corrections_applied": [...],
      "segments": [{"index": int, "speaker": str, "start": float, "end": float,
                    "duration": float, "text": str, "reviewed": bool,
                    "segment_datetime": iso8601,        # 2152 / 3207 segments
                    "correction_note": [...],           # 2021 / 3207
                    "backchannel_events": [...]}]       # 2247 / 3207
    }

A document without a ``segments`` list is **rejected**, not read as empty. The
common failure mode is feeding this reader an OliviaLegal bundle recording
(``content[]``, camelCase) and getting silence.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .sources import ParsedSegment

__all__ = [
    "JsonTranscriptSource",
    "JsonTranscriptSchemaError",
    "discover_json_transcripts",
    "expand_segment_index_spec",
]


#: ``"seg-12"``, ``"seg_12"`` or ``"12"`` -> ``12``.
_SEGMENT_ID_RE = re.compile(r"^(?:seg[-_])?(\d+)$")
#: One token of a segment spec: ``"4"``, ``"seg-4"``, or a range ``"4-9"``/``"4..9"``.
_SPEC_RANGE_RE = re.compile(r"^(?:seg[-_])?(\d+)\s*(?:-|\.\.|:)\s*(?:seg[-_])?(\d+)$")


class JsonTranscriptSchemaError(ValueError):
    """Raised when a file is not a canonical transcript document."""


# ---------------------------------------------------------------------------
# Segment-spec expansion
# ---------------------------------------------------------------------------

def expand_segment_index_spec(spec: str) -> list[str]:
    """Expand a human segment spec into an ordered, de-duplicated id list.

    Accepted grammar (whitespace-insensitive, comma-separated tokens)::

        "3"             -> ["seg-3"]
        "seg-3"         -> ["seg-3"]
        "1-4"           -> ["seg-1", "seg-2", "seg-3", "seg-4"]
        "seg-1..seg-3"  -> ["seg-1", "seg-2", "seg-3"]
        "1,3-5"         -> ["seg-1", "seg-3", "seg-4", "seg-5"]

    Returns ids in ascending numeric order, matching what
    :meth:`JsonTranscriptSource.get_segment` and the HTML reader accept.

    Raises:
        ValueError: on an empty spec, a malformed token, or a descending range.
    """
    if spec is None or not str(spec).strip():
        raise ValueError("empty segment spec")

    picked: set[int] = set()
    for raw in str(spec).split(","):
        token = raw.strip()
        if not token:
            continue
        rng = _SPEC_RANGE_RE.match(token)
        if rng:
            lo, hi = int(rng.group(1)), int(rng.group(2))
            if hi < lo:
                raise ValueError(f"descending range in segment spec: {token!r}")
            picked.update(range(lo, hi + 1))
            continue
        single = _SEGMENT_ID_RE.match(token)
        if single:
            picked.add(int(single.group(1)))
            continue
        raise ValueError(f"unparseable segment spec token: {token!r}")

    if not picked:
        raise ValueError(f"segment spec matched nothing: {spec!r}")
    return [f"seg-{n}" for n in sorted(picked)]


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# The source
# ---------------------------------------------------------------------------

class JsonTranscriptSource:
    """Canonical-JSON implementation of the ``TranscriptSource`` Protocol.

    Also exposes the parent metadata and the participant -> speaker-id mapping
    that the HTML source cannot provide.
    """

    def __init__(
        self,
        path: str | Path,
        source_id: str | None = None,
        bundle_uri: str | None = None,
        speaker_index_path: str | Path | None = None,
    ) -> None:
        self._path = Path(path)
        self._raw_bytes = self._path.read_bytes()
        self._sha256 = hashlib.sha256(self._raw_bytes).hexdigest()
        try:
            doc = json.loads(self._raw_bytes.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise JsonTranscriptSchemaError(
                f"{self._path}: not valid JSON: {exc}"
            ) from exc
        if not isinstance(doc, dict) or not isinstance(doc.get("segments"), list):
            keys = sorted(doc)[:8] if isinstance(doc, dict) else type(doc).__name__
            raise JsonTranscriptSchemaError(
                f"{self._path}: not a canonical transcript document "
                f"(expected a top-level 'segments' list; got {keys})"
            )
        self._doc = doc

        #: Canonical id from the document. ``source_id`` only overrides the
        #: *label*; it never replaces the canonical id used to compose
        #: ``segment_id``, because that would break the join to
        #: ``reviewed_transcripts``.
        self._transcript_id = str(doc.get("transcript_id") or self._path.stem)
        self._source_id = source_id or self._transcript_id
        self._bundle_uri = bundle_uri or str(self._path)

        self._participants: list[dict] = list(doc.get("participants") or [])
        self._spk_by_segment = self._load_speaker_index(speaker_index_path)
        self._spk_by_label: dict[str, str] = {}
        for participant in self._participants:
            spk_id = participant.get("speaker_id")
            if not spk_id:
                continue
            labels = list(participant.get("segment_labels") or [])
            for key in (participant.get("role"), participant.get("speaker_label")):
                if key:
                    labels.append(key)
            for label in labels:
                self._spk_by_label.setdefault(str(label).strip().lower(), str(spk_id))

        self._index: dict[str, ParsedSegment] = {}
        for segment in doc["segments"]:
            try:
                index = int(segment["index"])
            except (KeyError, TypeError, ValueError):
                continue
            segment_id = f"seg-{index}"
            verbatim = (segment.get("text") or "").strip()
            self._index[segment_id] = ParsedSegment(
                segment_id=segment_id,
                audio_offset_start=_as_float(segment.get("start")),
                audio_offset_end=_as_float(segment.get("end")),
                speaker=(segment.get("speaker") or "unknown"),
                verbatim=verbatim,
                # Extras — ignored by the Protocol, consumed by the layers.
                index=index,
                duration=_as_float(segment.get("duration")),
                reviewed=bool(segment.get("reviewed")),
                speaker_id=self._speaker_id_for_index(index, segment.get("speaker")),
                segment_datetime=segment.get("segment_datetime"),
                correction_note=segment.get("correction_note"),
                backchannel_events=segment.get("backchannel_events"),
            )

    # -- speaker resolution ---------------------------------------------------

    def _load_speaker_index(self, path: str | Path | None) -> dict[int, str]:
        """Load ``transcription/data/speaker_index.json`` if one is supplied.

        That file is the authoritative resolver — ``transcription``'s own ingest
        consults it *before* falling back to participant labels. It is symlinked
        into this project as ``data/speaker_index.json`` (see
        ``docs/data_source_of_truth.md`` §3.3). Passing it in makes the
        ``speaker_id`` here agree with the indexed ``reviewed_transcripts`` by
        construction; without it we fall back to the participants array and may
        differ from the indexed value.
        """
        if path is None:
            return {}
        p = Path(path)
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        out: dict[int, str] = {}
        for spk_id, meta in (data.get("mapped_speakers") or {}).items():
            occurrences = meta if isinstance(meta, list) else meta.get("appearances", [])
            for occ in occurrences:
                if occ.get("transcript_id") != self._transcript_id:
                    continue
                for idx in occ.get("segment_indices") or []:
                    out[int(idx)] = str(spk_id)
        return out

    def _speaker_id_for_index(self, index: int, label: Any) -> str | None:
        """Three-tier resolution, mirroring ``transcription``'s ingest order:

        1. exact ``(transcript_id, segment_index)`` hit from ``speaker_index.json``
        2. ``segment_labels`` / role / speaker_label match on ``participants``
        3. ``None`` — the collection legitimately stores nulls too
        """
        exact = self._spk_by_segment.get(index)
        if exact:
            return exact
        key = str(label or "").strip().lower()
        if not key:
            return None
        return self._spk_by_label.get(key)

    # -- Protocol methods -----------------------------------------------------

    def source_id(self) -> str:
        return self._source_id

    def source_uri(self) -> str:
        return self._bundle_uri

    def source_sha256(self) -> str:
        return self._sha256

    def get_segment(self, segment_id: str) -> ParsedSegment | None:
        """Look up by ``"seg-<index>"``, or accept a bare ``"<index>"``."""
        if segment_id in self._index:
            return self._index[segment_id]
        m = _SEGMENT_ID_RE.match(str(segment_id))
        if m:
            return self._index.get(f"seg-{int(m.group(1))}")
        return None

    def all_segments(self) -> list[ParsedSegment]:
        return list(self._index.values())

    # -- Extras for validation helpers ---------------------------------------

    def raw_text(self) -> str:
        """Whole-file text as written.

        Kept for callers that need the raw document (troubleshooting, ad-hoc
        tooling). Validation compares quotes against the resolved segment
        instead, which is stricter — see ``v02_verbatim_quote_match``.
        """
        return self._raw_bytes.decode("utf-8")

    @property
    def path(self) -> Path:
        return self._path

    @property
    def transcript_id(self) -> str:
        """Canonical id. Equals ``source_id()`` unless a caller overrode the label."""
        return self._transcript_id

    @property
    def document(self) -> dict:
        """The parsed canonical document (read-only by convention)."""
        return self._doc

    @property
    def is_canonical(self) -> bool:
        """False when the document's ``transcript_id`` disagrees with its basename."""
        return self._path.stem == self._transcript_id

    def segment_count(self) -> int:
        return len(self._index)

    def reviewed_segments(self) -> list[ParsedSegment]:
        """Segments with ``reviewed == true`` — exactly the ``reviewed_transcripts`` set."""
        return [s for s in self._index.values() if s["reviewed"]]

    def unreviewed_segments(self) -> list[ParsedSegment]:
        return [s for s in self._index.values() if not s["reviewed"]]

    def speaker_ids(self) -> dict[str, str]:
        """``{segment_label: speaker_id}`` as resolved for this transcript."""
        return {
            str(seg["speaker"]).strip().lower(): seg["speaker_id"]
            for seg in self._index.values()
            if seg["speaker_id"]
        }

    def participants(self) -> list[dict]:
        return list(self._participants)

    def get(self, key: str, default: Any = None) -> Any:
        """Read any top-level document field (``title``, ``case_id``, ...)."""
        return self._doc.get(key, default)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"JsonTranscriptSource({self._transcript_id!r}, {self.segment_count()} segments)"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_json_transcripts(
    directory: str | Path,
    speaker_index_path: str | Path | None = None,
) -> dict[str, JsonTranscriptSource]:
    """Load every canonical ``*.json`` transcript in ``directory``.

    Keyed by ``transcript_id`` — the same key the shared Qdrant collections use.
    Non-canonical JSON (``*.bak``, manifests, index side-cars) is skipped rather
    than raising, so one stray file cannot take down source discovery.
    """
    root = Path(directory)
    found: dict[str, JsonTranscriptSource] = {}
    if not root.is_dir():
        return found
    for path in sorted(root.glob("*.json")):
        if path.name.startswith("."):
            continue
        try:
            source = JsonTranscriptSource(
                path,
                bundle_uri=str(path),
                speaker_index_path=speaker_index_path,
            )
        except (JsonTranscriptSchemaError, OSError):
            continue
        found[source.transcript_id] = source
    return found
