"""Bulk ingesters for the three corpora that drive retrieval quality.

* `JurisprudenceIngester` — walks the juris-search corpus (one JSON per
  ruling, indexed by `index.json`) and pushes each ready ruling into the
  `<prefix>_jurisprudence` Qdrant collection with full provenance payload.
* `TranscriptIngester`     — walks an OliviaLegal incident bundle's
  `transcripts/raw/` segmented JSONs and pushes every utterance into the
  `<prefix>_segments` collection, anchored to its audio offsets. Unlike
  `QdrantVectorIndex.upsert_segment`, this does NOT require an upstream
  Violation: the whole transcript is indexed for retrieval and analysis
  pattern matching, not just the segments cited in the bundle.
* `FrameworkIngester`      — walks a Markdown framework file and pushes
  every `### Art. N — title` block into `<prefix>_articles`.

Design notes
------------
* Each ingester chunks long texts (default 1500 chars with 200 overlap) so
  embedding payloads stay under provider limits and per-chunk retrieval is
  precise; the parent record id is preserved in the payload via
  `record_id` / `parent_id` so callers can re-assemble.
* All ingest calls are idempotent: the Qdrant `_stable_point_id` UUID5 in
  `QdrantVectorIndex._upsert` means rerunning the ingester upserts in
  place rather than duplicating.
* Embedding cost is the dominant runtime; ingesters embed in batches of
  `batch_size` texts per call (default 64). For Voyage free tier (3 RPM),
  set `batch_size=128` and `sleep_between_batches=21.0`.
* Failures on a single record are logged via the `on_error` callback and
  do not abort the run; final stats include `failed` count.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .qdrant_index import QdrantVectorIndex, _stable_point_id


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

def _chunk_text(text: str, max_chars: int = 1500, overlap: int = 200) -> list[str]:
    """Split `text` into overlapping windows on paragraph/sentence boundaries.

    Tries to break at the last paragraph break, then last sentence end,
    then hard-cuts at `max_chars`. Returns at least one chunk; empty/None
    input yields [''].
    """
    text = (text or "").strip()
    if not text:
        return [""]
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        end = min(n, i + max_chars)
        if end < n:
            # Prefer paragraph break, then sentence end, within last 30% of window.
            window_start = i + int(max_chars * 0.7)
            soft_end = -1
            for sep in ("\n\n", ". ", "; ", "\n", " "):
                idx = text.rfind(sep, window_start, end)
                if idx > soft_end:
                    soft_end = idx + len(sep)
            if soft_end > 0:
                end = soft_end
        chunks.append(text[i:end].strip())
        if end >= n:
            break
        i = max(i + 1, end - overlap)
    return [c for c in chunks if c]


def _sha256_short(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


@dataclass
class IngestStats:
    """Summary returned by every ingester run."""

    scanned: int = 0
    upserted: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "upserted": self.upserted,
            "skipped": self.skipped,
            "failed": self.failed,
            "failures": self.failures[:20],  # keep payload small
        }


# ---------------------------------------------------------------------------
# JurisprudenceIngester
# ---------------------------------------------------------------------------

# `result_description` example:
#   "Processo 71010364404 | Tipo: Pedido de Uniformização de Interpretação
#    de Lei Cível | Relator: Daniel Henrique Dummer | Comarca: de Origem: OUTRA"
_RESULT_FIELD = re.compile(r"\s*\|\s*(?P<key>[^:|]+):\s*(?P<val>[^|]*)")


def _parse_result_description(desc: str | None) -> dict[str, str]:
    if not desc:
        return {}
    out: dict[str, str] = {}
    for m in _RESULT_FIELD.finditer(desc):
        key = m.group("key").strip().lower()
        val = m.group("val").strip()
        if key and val:
            out[key] = val
    return out


class JurisprudenceIngester:
    """Walk a juris-search `index.json` and upsert every ready ruling.

    Output Qdrant payload schema (per chunk point):
      record_id           — stable juris-search id (entry["id"])
      chunk_index         — 0-based int
      chunk_count         — total chunks for the ruling
      court               — TJRS / TJSP / STF (from search_params.tribunal)
      numero_processo, ano, codigo
      relator             — parsed from result_description
      tipo                — parsed from result_description
      comarca             — parsed from result_description
      primary_source_url  — source_metadata.source_url (REQUIRED for Authority
                            verification — see JurisprudenceProvider contract)
      downloaded_at       — ISO timestamp
      text                — the chunk text (verbatim slice of ruling text)
      text_chars          — ruling total chars
      json_path           — absolute path of the parsed JSON
    """

    def __init__(
        self,
        index: QdrantVectorIndex,
        chunk_chars: int = 1500,
        chunk_overlap: int = 200,
        batch_size: int = 64,
        sleep_between_batches: float = 0.0,
        max_chunks_per_ruling: int | None = 8,
    ) -> None:
        self.index = index
        self.chunk_chars = chunk_chars
        self.chunk_overlap = chunk_overlap
        self.batch_size = max(1, batch_size)
        self.sleep_between_batches = sleep_between_batches
        self.max_chunks_per_ruling = max_chunks_per_ruling

    # ---------------------------------------------------------------- public

    def ingest(
        self,
        index_path: str | Path,
        limit: int | None = None,
        skip: int = 0,
        on_progress: Callable[[IngestStats], None] | None = None,
    ) -> IngestStats:
        """Process every ready entry in `index.json`.

        `limit` caps the number of *rulings* processed (not chunks).
        `skip` skips the first N ready entries.
        """
        index_path = Path(index_path)
        with index_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
        entries: list[dict] = manifest.get("entries", [])
        ready = [e for e in entries if e.get("status") == "ready" and e.get("json_path")]
        if skip:
            ready = ready[skip:]
        if limit is not None:
            ready = ready[:limit]

        stats = IngestStats()
        self.index.ensure_collections()

        # Batch buffer: list of (point_id, payload, text) for one Qdrant upsert.
        buf: list[tuple[str, dict, str]] = []

        for entry in ready:
            stats.scanned += 1
            try:
                ruling_chunks = self._build_chunks(entry)
            except Exception as exc:  # noqa: BLE001
                stats.failed += 1
                stats.failures.append({"id": entry.get("id"), "error": str(exc)})
                continue
            if not ruling_chunks:
                stats.skipped += 1
                continue
            buf.extend(ruling_chunks)
            while len(buf) >= self.batch_size:
                self._flush(buf[: self.batch_size], stats)
                buf = buf[self.batch_size :]
                if self.sleep_between_batches:
                    time.sleep(self.sleep_between_batches)
                if on_progress:
                    on_progress(stats)

        if buf:
            self._flush(buf, stats)
            if on_progress:
                on_progress(stats)

        return stats

    # --------------------------------------------------------------- helpers

    def _build_chunks(self, entry: dict) -> list[tuple[str, dict, str]]:
        """Return list of (point_id, payload, text) for one ruling."""
        json_path = Path(entry["json_path"])
        if not json_path.exists():
            return []
        with json_path.open("r", encoding="utf-8") as f:
            doc = json.load(f)
        text = (doc.get("text") or "").strip()
        if not text:
            return []
        meta = doc.get("source_metadata") or {}
        parsed = _parse_result_description(meta.get("result_description"))
        court = (
            (meta.get("search_params") or {}).get("tribunal")
            or parsed.get("tribunal")
            or "unknown"
        )
        chunks = _chunk_text(text, self.chunk_chars, self.chunk_overlap)
        if self.max_chunks_per_ruling is not None:
            chunks = chunks[: self.max_chunks_per_ruling]
        record_id = doc.get("id") or entry.get("id") or _sha256_short(text)
        base_payload = {
            "record_id": record_id,
            "court": court,
            "numero_processo": meta.get("numero_processo"),
            "ano": meta.get("ano"),
            "codigo": meta.get("codigo"),
            "relator": parsed.get("relator"),
            "tipo": parsed.get("tipo"),
            "comarca": parsed.get("comarca"),
            "primary_source_url": meta.get("source_url")
            or meta.get("source_page_url")
            or meta.get("download_url"),
            "downloaded_at": meta.get("downloaded_at"),
            "text_chars": doc.get("text_chars") or len(text),
            "json_path": str(json_path),
        }
        out: list[tuple[str, dict, str]] = []
        total = len(chunks)
        for i, chunk in enumerate(chunks):
            pid = _stable_point_id("jurisprudence", record_id, str(i))
            payload = dict(base_payload, chunk_index=i, chunk_count=total, text=chunk)
            out.append((pid, payload, chunk))
        return out

    def _flush(
        self,
        items: list[tuple[str, dict, str]],
        stats: IngestStats,
    ) -> None:
        if not items:
            return
        texts = [t for (_pid, _p, t) in items]
        try:
            vectors = self.index.embedder.embed(texts)
        except Exception as exc:  # noqa: BLE001
            stats.failed += len(items)
            stats.failures.append({"batch_size": len(items), "error": str(exc)})
            return
        try:
            from qdrant_client.http import models as qm  # type: ignore

            points = [
                qm.PointStruct(id=pid, vector=vec, payload=payload)
                for (pid, payload, _t), vec in zip(items, vectors)
            ]
            self.index.client.upsert(
                collection_name=self.index._jurisprudence_coll,
                points=points,
                wait=False,
            )
            stats.upserted += len(items)
        except Exception as exc:  # noqa: BLE001
            stats.failed += len(items)
            stats.failures.append({"batch_size": len(items), "error": str(exc)})


# ---------------------------------------------------------------------------
# TranscriptIngester
# ---------------------------------------------------------------------------

class TranscriptIngester:
    """Walk an OliviaLegal incident bundle and upsert every transcript segment.

    Input layout (OliviaLegal forensics export):
        <bundle>/transcripts/raw/<segment_name>/<segment_name>.json
        # symlinks → ../../../LA8159_files/main_latam_case_version/<segment_name>.json
    OR a flat directory of forensics JSONs:
        <bundle>/evidence/structured_data/_from_forensics/<segment_name>.json

    Per-JSON schema (as confirmed against the LATAM case):
        title, subtitle, filename, recordingdatetime, location
        content: [{speaker, start, end, text, id}, ...]
        metadata.fileInfo.fileName  -> audio file basename

    Each utterance becomes one point in `<prefix>_segments` with payload
    keyed so that retrieval results can be re-anchored in audio:
        violation_id     — "TRANSCRIPT:<filename>" (synthetic; not a real
                           Violation. Filter by has_violation_id=False or by
                           prefix when surfacing in MCP tools.)
        segment_id       — "<filename>.seg-<id>"
        audio_uri        — relative path to the m4a, if discoverable
        audio_offset_start/end, speaker, source_uri
        verbatim_es, translation_en (translation absent in raw → '')
        bundle_id        — incident id (caller-supplied)
        recording_datetime
        location
    """

    def __init__(
        self,
        index: QdrantVectorIndex,
        batch_size: int = 64,
        sleep_between_batches: float = 0.0,
    ) -> None:
        self.index = index
        self.batch_size = max(1, batch_size)
        self.sleep_between_batches = sleep_between_batches

    def ingest_bundle(
        self,
        bundle_root: str | Path,
        bundle_id: str | None = None,
        limit_segments: int | None = None,
    ) -> IngestStats:
        bundle_root = Path(bundle_root)
        if bundle_id is None:
            bundle_id = bundle_root.name
        jsons = self._discover_json_transcripts(bundle_root)
        return self._ingest_paths(jsons, bundle_id, bundle_root, limit_segments)

    def ingest_paths(
        self,
        json_paths: Iterable[str | Path],
        bundle_id: str,
        bundle_root: str | Path | None = None,
        limit_segments: int | None = None,
    ) -> IngestStats:
        return self._ingest_paths(
            [Path(p) for p in json_paths],
            bundle_id,
            Path(bundle_root) if bundle_root else None,
            limit_segments,
        )

    # --------------------------------------------------------------- private

    def _discover_json_transcripts(self, bundle_root: Path) -> list[Path]:
        """Locate transcript JSONs in priority order.

        1. `<bundle>/evidence/structured_data/_from_forensics/*.json` (canonical
           OliviaLegal forensics export — real files, not symlinks).
        2. `<bundle>/transcripts/raw/<seg>/<seg>.json` (symlinks; resolved).
        """
        candidates: list[Path] = []
        forensics = bundle_root / "evidence" / "structured_data" / "_from_forensics"
        if forensics.is_dir():
            for p in sorted(forensics.glob("*.json")):
                if p.name.startswith(".") or p.name == "manifest.json":
                    continue
                candidates.append(p)
        if candidates:
            return candidates
        raw = bundle_root / "transcripts" / "raw"
        if raw.is_dir():
            for sub in sorted(raw.iterdir()):
                if not sub.is_dir():
                    continue
                for p in sub.glob("*.json"):
                    if p.name == "manifest.json":
                        continue
                    try:
                        resolved = p.resolve()
                    except OSError:
                        continue
                    if resolved.exists():
                        candidates.append(resolved)
        return candidates

    def _ingest_paths(
        self,
        paths: list[Path],
        bundle_id: str,
        bundle_root: Path | None,
        limit_segments: int | None,
    ) -> IngestStats:
        stats = IngestStats()
        self.index.ensure_collections()
        buf: list[tuple[str, dict, str]] = []
        total_seg = 0
        for p in paths:
            stats.scanned += 1
            try:
                items = self._build_segment_points(p, bundle_id, bundle_root)
            except Exception as exc:  # noqa: BLE001
                stats.failed += 1
                stats.failures.append({"path": str(p), "error": str(exc)})
                continue
            if not items:
                stats.skipped += 1
                continue
            for it in items:
                if limit_segments is not None and total_seg >= limit_segments:
                    break
                buf.append(it)
                total_seg += 1
            while len(buf) >= self.batch_size:
                self._flush(buf[: self.batch_size], stats)
                buf = buf[self.batch_size :]
                if self.sleep_between_batches:
                    time.sleep(self.sleep_between_batches)
            if limit_segments is not None and total_seg >= limit_segments:
                break
        if buf:
            self._flush(buf, stats)
        return stats

    def _build_segment_points(
        self,
        json_path: Path,
        bundle_id: str,
        bundle_root: Path | None,
    ) -> list[tuple[str, dict, str]]:
        with json_path.open("r", encoding="utf-8") as f:
            doc = json.load(f)
        content = doc.get("content") or []
        if not isinstance(content, list) or not content:
            return []
        filename = doc.get("filename") or json_path.stem
        recording = doc.get("recordingdatetime") or doc.get("recordingDateTime")
        location = doc.get("location")
        audio_name = (
            (doc.get("metadata") or {}).get("fileInfo", {}).get("fileName")
            or f"{filename}.m4a"
        )
        try:
            source_rel = (
                str(json_path.relative_to(bundle_root))
                if bundle_root
                else str(json_path)
            )
        except ValueError:
            source_rel = str(json_path)
        synthetic_vid = f"TRANSCRIPT:{filename}"
        out: list[tuple[str, dict, str]] = []
        for seg in content:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            seg_local_id = str(seg.get("id"))
            segment_id = f"{filename}.seg-{seg_local_id}"
            pid = _stable_point_id("segment", synthetic_vid, segment_id)
            payload = {
                "violation_id": synthetic_vid,
                "segment_id": segment_id,
                "role_in_argument": "transcript_corpus",
                "speaker": seg.get("speaker") or "unknown",
                "audio_offset_start": float(seg.get("start") or 0.0),
                "audio_offset_end": float(seg.get("end") or 0.0),
                "source_uri": f"{source_rel}#seg-{seg_local_id}",
                "audio_uri": audio_name,
                "verbatim_es": text,
                "translation_en": "",
                "bundle_id": bundle_id,
                "recording_datetime": recording,
                "location": location,
                "transcript_filename": filename,
            }
            out.append((pid, payload, text))
        return out

    def _flush(
        self,
        items: list[tuple[str, dict, str]],
        stats: IngestStats,
    ) -> None:
        if not items:
            return
        texts = [t for (_pid, _p, t) in items]
        try:
            vectors = self.index.embedder.embed(texts)
        except Exception as exc:  # noqa: BLE001
            stats.failed += len(items)
            stats.failures.append({"batch_size": len(items), "error": str(exc)})
            return
        try:
            from qdrant_client.http import models as qm  # type: ignore

            points = [
                qm.PointStruct(id=pid, vector=vec, payload=payload)
                for (pid, payload, _t), vec in zip(items, vectors)
            ]
            self.index.client.upsert(
                collection_name=self.index._segments_coll,
                points=points,
                wait=False,
            )
            stats.upserted += len(items)
        except Exception as exc:  # noqa: BLE001
            stats.failed += len(items)
            stats.failures.append({"batch_size": len(items), "error": str(exc)})


# ---------------------------------------------------------------------------
# FrameworkIngester
# ---------------------------------------------------------------------------

# Match a markdown article header like:
#   ### Art. 193 — Falsedad en documento público
#   ### Art. 193 - Falsedad en documento público
#   ### Artículo 5 — Definiciones
_ARTICLE_HEADER = re.compile(
    r"^#{1,6}\s+(?:Art\.?|Artículo|Article|Artigo)\s*"
    r"([0-9]+[A-Za-z\-_°ºª]*(?:\s+(?:bis|ter|quater|quinquies))?)"
    r"\s*[—\-–:]+\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)


class FrameworkIngester:
    """Parse a Markdown framework cache file and index each article block.

    Expected input: a Markdown file where each article begins with a header
    matching `_ARTICLE_HEADER`. The article body is everything from that
    header up to (but not including) the next article header or EOF.

    Each block is indexed as one point in `<prefix>_articles`:
        article_id      — "<framework_code>.Art.<num>"
        article_name    — header title text
        framework_code  — caller-supplied
        verbatim_excerpt — the article body
        sha256_short    — short hash of excerpt
    """

    def __init__(
        self,
        index: QdrantVectorIndex,
        batch_size: int = 64,
        sleep_between_batches: float = 0.0,
    ) -> None:
        self.index = index
        self.batch_size = max(1, batch_size)
        self.sleep_between_batches = sleep_between_batches

    def ingest_markdown(
        self,
        markdown_path: str | Path,
        framework_code: str,
        framework_name: str | None = None,
    ) -> IngestStats:
        markdown_path = Path(markdown_path)
        text = markdown_path.read_text(encoding="utf-8")
        blocks = list(self._iter_article_blocks(text))
        stats = IngestStats()
        stats.scanned = len(blocks)
        self.index.ensure_collections()
        buf: list[tuple[str, dict, str]] = []
        for num, title, body in blocks:
            num_clean = re.sub(r"\s+", "_", num.strip())
            article_id = f"{framework_code}.Art.{num_clean}"
            pid = _stable_point_id("article", framework_code, article_id)
            payload = {
                "article_id": article_id,
                "article_name": title.strip(),
                "framework_code": framework_code,
                "framework_name": framework_name or framework_code,
                "verbatim_excerpt": body.strip(),
                "sha256_short": _sha256_short(body),
                "source_path": str(markdown_path),
            }
            buf.append((pid, payload, f"{title}\n\n{body}"))
            if len(buf) >= self.batch_size:
                self._flush(buf, stats)
                buf = []
                if self.sleep_between_batches:
                    time.sleep(self.sleep_between_batches)
        if buf:
            self._flush(buf, stats)
        return stats

    def _iter_article_blocks(self, text: str) -> Iterator[tuple[str, str, str]]:
        matches = list(_ARTICLE_HEADER.finditer(text))
        for i, m in enumerate(matches):
            num = m.group(1)
            title = m.group(2)
            body_start = m.end()
            body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[body_start:body_end].strip()
            if body:
                yield num, title, body

    def _flush(
        self,
        items: list[tuple[str, dict, str]],
        stats: IngestStats,
    ) -> None:
        if not items:
            return
        texts = [t for (_pid, _p, t) in items]
        try:
            vectors = self.index.embedder.embed(texts)
        except Exception as exc:  # noqa: BLE001
            stats.failed += len(items)
            stats.failures.append({"batch_size": len(items), "error": str(exc)})
            return
        try:
            from qdrant_client.http import models as qm  # type: ignore

            points = [
                qm.PointStruct(id=pid, vector=vec, payload=payload)
                for (pid, payload, _t), vec in zip(items, vectors)
            ]
            self.index.client.upsert(
                collection_name=self.index._articles_coll,
                points=points,
                wait=False,
            )
            stats.upserted += len(items)
        except Exception as exc:  # noqa: BLE001
            stats.failed += len(items)
            stats.failures.append({"batch_size": len(items), "error": str(exc)})


__all__ = [
    "IngestStats",
    "JurisprudenceIngester",
    "TranscriptIngester",
    "FrameworkIngester",
]
