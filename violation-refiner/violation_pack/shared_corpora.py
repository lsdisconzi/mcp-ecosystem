"""Read-only access to the two shared Qdrant collections owned by ``transcription``.

Both collections are **written only by ``transcription/``**. This project may read
them and must never write to them. The declarations here are the executable version
of the table in ``docs/data_source_of_truth.md`` §4 — they were verified against the
live collections on 2026-09-13 and are asserted by ``verify_contract()``, so drift
shows up as a failing check instead of a wrong answer months later.

The two corpora
---------------
``transcription_law``
    1119 law articles, 384-d (``all-MiniLM-L6-v2``). Point id is
    ``uuid5(NAMESPACE_DNS, original_id)``. Payload is *schema v1* (see
    ``transcription/src/infrastructure/qdrant_law_index.py::local_payload``),
    which is **not** the same shape as the canonical ``la8159_law`` payload:
    ``tags`` is a list, there is no ``original_data``/``metadata``, and
    ``schema_version`` is present. Verified: 1119/1119 point ids match the
    declared derivation, 1119 distinct ``original_id``, ``content == text``.

``reviewed_transcripts``
    3163 points, 384-d (``all-MiniLM-L6-v2``), point id
    ``UUID(md5("<transcript_id>:<segment_index>"))``. Exactly the set of canonical
    JSON segments with ``reviewed == true`` across the **27** ``I-002_*`` case
    transcripts. This is the only transcript corpus in contract.

``transcription_transcripts`` is deliberately **not** in contract, and it is
**not** a subset of ``reviewed_transcripts`` — an earlier note here claimed it
was, and that was wrong. It is ``transcription``'s own working index over raw
audio: 2272 points across **481** ad-hoc job ids (``denoise (25)_1788032405.wav``,
``stg_7_p2_1787952500``), with ``SPEAKER_00`` diarization labels and empty
``case_id``/``narrative_id``. Its transcript ids and the case corpus's share
**zero** overlap, so it is a disjoint corpus, not a superset. Do not read it, and
do not drop it: ``transcription`` recreates it at startup and its transcript
search depends on it.

The embedder trap
-----------------
These collections hold 384-d vectors. This project's default embedder is Voyage
(1024-d). A query vector from the wrong embedder is not a subtle degradation — it
is a dimension error or, if dimensions happen to match, silent nonsense. So
:class:`SharedCorpusReader` **refuses to vector-search** unless the embedder's
``dim`` matches the collection's declared dim. Exact reads (by point id, by
payload filter) need no embedder at all and are the preferred integration path.

Usage::

    from violation_pack.shared_corpora import SharedCorpusReader

    reader = SharedCorpusReader(url=..., api_key=...)
    article = reader.law_article("CL.CHIPENCOD.T4.C3.Art.193")  # no embedder needed
    segs    = reader.reviewed_segments("I-002_01_NAR-01_STG_1_pre_boarding")
    report  = reader.verify_contract()                          # drift detector

    # Semantic search needs a 384-d embedder — see MiniLmEmbedder.
    reader = SharedCorpusReader(url=..., api_key=..., embedder=MiniLmEmbedder())
    hits = reader.search_law("detención arbitraria", top_k=5)
"""
from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

__all__ = [
    "CollectionContract",
    "EmbedderMismatch",
    "MiniLmEmbedder",
    "SharedCorpusError",
    "SharedCorpusReader",
    "SHARED_COLLECTIONS",
    "TRANSCRIPTION_LAW",
    "REVIEWED_TRANSCRIPTS",
    "law_point_id",
    "transcript_point_id",
]


class SharedCorpusError(RuntimeError):
    """Base class for shared-corpus access failures."""


class EmbedderMismatch(SharedCorpusError):
    """Raised when a query embedder cannot produce vectors for a collection."""


# ---------------------------------------------------------------------------
# Point-id derivations (verified against the live collections)
# ---------------------------------------------------------------------------

def law_point_id(original_id: str) -> str:
    """``uuid5(NAMESPACE_DNS, original_id)`` — verified 1119/1119 on 2026-09-13."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, original_id))


def transcript_point_id(transcript_id: str, segment_index: int) -> str:
    """``UUID(md5("<transcript_id>:<segment_index>"))`` — verified 500/500.

    Qdrant stores and returns this in **dashed** form. Comparing it against the
    bare ``md5(...).hexdigest()`` (undashed) silently matches nothing, which is
    exactly the false negative this helper exists to prevent.
    """
    digest = hashlib.md5(f"{transcript_id}:{segment_index}".encode()).hexdigest()  # noqa: S324
    return str(uuid.UUID(digest))


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CollectionContract:
    """A declared, checkable description of a collection we only read."""

    name: str
    owner: str
    dim: int
    embed_model: str
    point_id_description: str
    point_id_fn: Callable[..., str] | None
    payload_keys: tuple[str, ...]
    keyed_by: str
    notes: str = ""
    #: Payload keys that are part of the *contract* — a missing one is drift.
    required_payload_keys: tuple[str, ...] = ()

    def check(self, client: Any, *, expect_points: int | None = None) -> dict[str, Any]:
        """Compare the live collection against this declaration.

        Never raises: returns ``{"ok": bool, "problems": [...]}`` so a caller can
        report on several collections at once.
        """
        problems: list[str] = []
        try:
            info = client.get_collection(self.name)
        except Exception as exc:  # noqa: BLE001 - surfaced as a problem, not a crash
            return {"name": self.name, "ok": False, "problems": [f"unreachable: {exc}"]}

        vectors = info.config.params.vectors
        if hasattr(vectors, "size"):
            dim = vectors.size
        elif isinstance(vectors, dict) and vectors:
            dim = next(iter(vectors.values())).size
        else:
            dim = None
            problems.append("collection has no single unnamed dense vector")
        if dim is not None and dim != self.dim:
            problems.append(f"dim={dim}, contract says {self.dim}")

        points = info.points_count
        if expect_points is not None and points != expect_points:
            problems.append(f"points={points}, expected {expect_points}")

        # Payload shape: sample one point and check the required keys.
        try:
            sample, _ = client.scroll(
                self.name, limit=1, with_payload=True, with_vectors=False
            )
        except Exception as exc:  # noqa: BLE001
            sample, problems = [], problems + [f"scroll failed: {exc}"]
        if sample:
            present = set(sample[0].payload or {})
            missing = [k for k in self.required_payload_keys if k not in present]
            if missing:
                problems.append(f"payload missing keys: {missing}")
            if self.point_id_fn is not None:
                # Re-derive the id from the payload and compare.
                try:
                    expected_id = self._expected_id_from_payload(sample[0].payload)
                except Exception:  # noqa: BLE001
                    expected_id = None
                if expected_id and str(sample[0].id) != expected_id:
                    problems.append(
                        f"point id {sample[0].id!r} != derived {expected_id!r}"
                    )

        return {
            "name": self.name,
            "owner": self.owner,
            "ok": not problems,
            "dim": dim,
            "points": points,
            "problems": problems,
        }

    def _expected_id_from_payload(self, payload: dict) -> str | None:
        if self.name == TRANSCRIPTION_LAW.name:
            oid = payload.get("original_id")
            return law_point_id(oid) if oid else None
        if self.name == REVIEWED_TRANSCRIPTS.name:
            tid, idx = payload.get("transcript_id"), payload.get("segment_index")
            if tid is None or idx is None:
                return None
            return transcript_point_id(tid, int(idx))
        return None


#: The law corpus, in its repo-owned schema-v1 form.
TRANSCRIPTION_LAW = CollectionContract(
    name="transcription_law",
    owner="transcription",
    dim=384,
    embed_model="all-MiniLM-L6-v2",
    point_id_description="uuid5(NAMESPACE_DNS, original_id)",
    point_id_fn=law_point_id,
    keyed_by='original_id — ELI-style, e.g. "CL.CHIPENCOD.T4.C3.Art.193"',
    required_payload_keys=(
        "original_id", "eli_id", "content", "text", "framework_code",
        "language", "schema_version", "record_kind", "source_sha256",
    ),
    payload_keys=(
        "eli_id", "original_id", "article_number", "framework_code", "jurisdiction",
        "title", "theme", "norm_type", "scope", "direction", "sanctions", "tags",
        "content", "text", "source_file", "source_path", "source_sha256",
        "language", "doc_type", "record_kind", "reference_only", "data_type",
        "schema_version", "ingested_at", "updated_at",
    ),
    notes=(
        "Schema v1 — NOT the la8159_law shape. tags is a list, no original_data/"
        "metadata, schema_version present. The same articles also exist as the "
        "Markdown corpus at data/law/, which is the offline route."
    ),
)

#: The reviewed transcript segments — the 27 canonical ``I-002_*`` case transcripts.
REVIEWED_TRANSCRIPTS = CollectionContract(
    name="reviewed_transcripts",
    owner="transcription",
    dim=384,
    embed_model="all-MiniLM-L6-v2",
    point_id_description='UUID(md5("<transcript_id>:<segment_index>"))',
    point_id_fn=lambda tid, idx: transcript_point_id(tid, idx),
    keyed_by="transcript_id + segment_index",
    required_payload_keys=(
        "transcript_id", "segment_id", "segment_index", "speaker", "text",
        "reviewed", "speaker_id", "source_file", "case_id", "narrative_id",
    ),
    payload_keys=(
        "transcript_id", "segment_id", "segment_index", "speaker", "speaker_id",
        "start", "end", "text", "source_file", "language", "reviewed",
        "correction_note", "backchannel_events", "local_time", "case_id",
        "narrative_id", "title", "location", "recording_datetime",
        "chronological_order", "prior_stage", "next_stage", "violations_cited",
        "tags", "forensic_cluster_ids", "key_finding_ids", "participants",
    ),
    notes=(
        "Exactly the canonical segments with reviewed == true, for the 27 "
        "I-002_* case transcripts. Carries the canonical SPK-… speaker_id "
        "(resolved via transcription's speaker_index.json) and segment_id. "
        "transcript_id equals the JSON basename == canonical id == "
        "JsonTranscriptSource.source_id(). NOT related to "
        "transcription_transcripts, which indexes raw audio under its own "
        "job ids (0 id overlap) and is out of contract."
    ),
)

#: The collections this project may read. Anything else is out of contract.
SHARED_COLLECTIONS: dict[str, CollectionContract] = {
    c.name: c for c in (TRANSCRIPTION_LAW, REVIEWED_TRANSCRIPTS)
}


# ---------------------------------------------------------------------------
# Embedders
# ---------------------------------------------------------------------------

class MiniLmEmbedder:
    """384-d ``all-MiniLM-L6-v2`` — the model that produced both shared collections.

    Lazily imports ``sentence-transformers``; violation-refiner does not depend on
    it (``pip install -e '.[qdrant]'`` installs only the client). The import error
    is annotated so the fix is obvious rather than a bare ImportError.
    """

    name = "all-MiniLM-L6-v2"
    dim = 384

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self.name = model_name
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise EmbedderMismatch(
                "MiniLmEmbedder needs sentence-transformers, which is not a "
                "violation-refiner dependency. Install it "
                "(pip install sentence-transformers) or use the exact-read "
                "methods (law_article / reviewed_segments), which need no "
                "embedder."
            ) from exc
        self._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.encode(texts)]


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------

@dataclass
class SharedCorpusReader:
    """Read-only reader over the shared collections owned by ``transcription``.

    Nothing in this class writes. There is deliberately no ``upsert``.

    ``url`` and ``api_key`` default to ``QDRANT_URL`` / ``QDRANT_API_KEY``, so
    ``SharedCorpusReader()`` is the normal construction. These are the same
    credentials `transcription` uses; violation-refiner keeps no ``.env`` of its
    own (see ``.env.example``).
    """

    url: str | None = None
    api_key: str | None = None
    embedder: Any | None = None
    client: Any | None = None
    _client: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.url is None:
            self.url = os.environ.get("QDRANT_URL") or None
        if self.api_key is None:
            self.api_key = os.environ.get("QDRANT_API_KEY") or None
        if self.url is None and self.client is None:
            raise SharedCorpusError(
                "QDRANT_URL is not set. Export it (or point at the shared .env) "
                "before constructing SharedCorpusReader()."
            )
        if self.client is not None:
            self._client = self.client
            return
        url = self.url
        assert url is not None  # narrowed by the guard above
        try:
            from qdrant_client import QdrantClient  # type: ignore
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise SharedCorpusError(
                "qdrant-client is required: pip install -e '.[qdrant]'"
            ) from exc
        # ``check_compatibility`` is left on for visibility: client and server
        # minor versions drift (1.19 client vs 1.16 server at the time of
        # writing) and the warning is the cheapest early signal of that.
        self._client = QdrantClient(url=url, api_key=self.api_key)

    # -- contract ------------------------------------------------------------

    @staticmethod
    def contracts() -> dict[str, CollectionContract]:
        """The declared contracts for the collections this project may read."""
        return dict(SHARED_COLLECTIONS)

    def contract(self, collection: str) -> CollectionContract:
        try:
            return SHARED_COLLECTIONS[collection]
        except KeyError as exc:
            raise SharedCorpusError(
                f"{collection!r} is not a declared shared collection; "
                f"known: {sorted(SHARED_COLLECTIONS)}"
            ) from exc

    def verify_contract(self, *, expect_points: dict[str, int] | None = None) -> dict[str, Any]:
        """Check every declared collection against its contract.

        Returns a report with ``ok`` at the top level and per-collection detail.
        Point counts are reported but only asserted when ``expect_points`` is
        given — counts legitimately change when ``transcription`` re-ingests.
        """
        expect_points = expect_points or {}
        results = [
            contract.check(self._client, expect_points=expect_points.get(name))
            for name, contract in SHARED_COLLECTIONS.items()
        ]
        return {"ok": all(r["ok"] for r in results), "collections": results}

    # -- exact reads (no embedder required) ----------------------------------

    def law_article(self, original_id: str) -> dict | None:
        """Fetch one law article by ``original_id``/``eli_id``. No embedder needed."""
        records = self._client.retrieve(
            collection_name=TRANSCRIPTION_LAW.name,
            ids=[law_point_id(original_id)],
            with_payload=True,
            with_vectors=False,
        )
        if not records:
            return None
        return dict(records[0].payload or {})

    def iter_law_articles(
        self,
        *,
        framework_code: str | None = None,
        language: str | None = None,
        jurisdiction: str | None = None,
        batch: int = 256,
    ) -> Iterator[dict]:
        """Scroll law articles with optional payload filters. No embedder needed."""
        flt = _filter(
            framework_code=framework_code, language=language, jurisdiction=jurisdiction
        )
        return self._scroll(TRANSCRIPTION_LAW.name, flt, batch)

    def reviewed_segments(
        self,
        transcript_id: str | None = None,
        *,
        case_id: str | None = None,
        speaker_id: str | None = None,
        batch: int = 256,
    ) -> list[dict]:
        """All reviewed segments, optionally narrowed by transcript/case/speaker.

        No embedder needed — this is the practical replacement for parsing the
        HTML snapshot when the question is "what did the reviewed record say".
        """
        values = {
            "transcript_id": transcript_id,
            "case_id": case_id,
            "speaker_id": speaker_id,
        }
        rows = list(
            self._scroll(
                REVIEWED_TRANSCRIPTS.name,
                _filter(**values),
                batch,
            )
        )
        rows.sort(key=lambda r: (r.get("transcript_id", ""), r.get("segment_index", 0)))
        return rows

    def reviewed_segment(self, transcript_id: str, segment_index: int) -> dict | None:
        """Fetch one reviewed segment by its exact point id."""
        records = self._client.retrieve(
            collection_name=REVIEWED_TRANSCRIPTS.name,
            ids=[transcript_point_id(transcript_id, segment_index)],
            with_payload=True,
            with_vectors=False,
        )
        return dict(records[0].payload or {}) if records else None

    # -- vector search (requires a dim-matched embedder) ---------------------

    def search_law(self, query: str, top_k: int = 5, **filters: Any) -> list[dict]:
        """Semantic search over ``transcription_law``."""
        return self._search(TRANSCRIPTION_LAW, query, top_k, **filters)

    def search_reviewed_segments(
        self, query: str, top_k: int = 5, **filters: Any
    ) -> list[dict]:
        """Semantic search over ``reviewed_transcripts``."""
        return self._search(REVIEWED_TRANSCRIPTS, query, top_k, **filters)

    def _search(
        self, contract: CollectionContract, query: str, top_k: int, **filters: Any
    ) -> list[dict]:
        self._require_matching_embedder(contract)
        _validate_filter_keys(contract, filters)
        vec = self._embedder_vector(query)
        flt = _filter(**filters) if filters else None
        query_points = getattr(self._client, "query_points", None)
        if callable(query_points):
            resp = query_points(
                collection_name=contract.name,
                query=vec,
                limit=top_k,
                with_payload=True,
                query_filter=flt,
            )
            hits = getattr(resp, "points", resp)
        else:  # pragma: no cover - older clients
            hits = self._client.search(
                collection_name=contract.name,
                query_vector=vec,
                limit=top_k,
                with_payload=True,
                query_filter=flt,
            )
        return [
            {"id": str(h.id), "score": float(h.score), "payload": dict(h.payload or {})}
            for h in hits
        ]

    def _embedder_vector(self, query: str) -> list[float]:
        vecs = self.embedder.embed([query])
        return list(vecs[0])

    def _require_matching_embedder(self, contract: CollectionContract) -> None:
        """Guard against the 1024-d Voyage default being pointed at a 384-d collection."""
        if self.embedder is None:
            raise EmbedderMismatch(
                f"{contract.name} is a {contract.dim}-d ({contract.embed_model}) "
                f"collection and no embedder was supplied. Semantic search must "
                f"use a {contract.dim}-d embedder — see MiniLmEmbedder — or use "
                f"the exact-read methods, which need no embedder."
            )
        dim = getattr(self.embedder, "dim", None)
        if dim != contract.dim:
            raise EmbedderMismatch(
                f"{contract.name} holds {contract.dim}-d vectors "
                f"({contract.embed_model}) but the supplied embedder "
                f"{getattr(self.embedder, 'name', type(self.embedder).__name__)!r} "
                f"produces dim={dim}. Querying across embedders returns "
                f"meaningless neighbours; pass a {contract.dim}-d embedder."
            )

    # -- internals -----------------------------------------------------------

    def _scroll(self, collection: str, flt: Any, batch: int) -> Iterator[dict]:
        offset = None
        while True:
            points, offset = self._client.scroll(
                collection_name=collection,
                scroll_filter=flt,
                limit=batch,
                with_payload=True,
                with_vectors=False,
                offset=offset,
            )
            for point in points:
                yield dict(point.payload or {})
            if offset is None:
                break


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_filter_keys(contract: CollectionContract, filters: dict[str, Any]) -> None:
    """Reject filter keys the collection does not have.

    The search methods accept ``**filters``, which would otherwise swallow a typo
    — ``search_law(q, limit=10)`` (the parameter is ``top_k``) builds a filter on
    a non-existent ``limit`` key and quietly returns **zero** rows, which reads
    like "no matches" rather than "you misspelled an argument".
    """
    known = set(contract.payload_keys) | set(contract.required_payload_keys)
    unknown = sorted(k for k in filters if k not in known)
    if unknown:
        raise SharedCorpusError(
            f"unknown filter key(s) {unknown} for {contract.name!r}. "
            f"Did you mean one of: {sorted(known)}? "
            f"(the result-count argument is ``top_k``, not ``limit``)"
        )


def _filter(**values: Any) -> Any | None:
    """Build a Qdrant ``Filter`` from ``{key: value}``, skipping ``None`` values."""
    pairs = {k: v for k, v in values.items() if v is not None}
    if not pairs:
        return None
    try:
        from qdrant_client.http import models as qm  # type: ignore
    except ImportError:  # pragma: no cover - dependency guard
        return None
    return qm.Filter(
        must=[
            qm.FieldCondition(key=key, match=qm.MatchValue(value=value))
            for key, value in pairs.items()
        ]
    )


def _main(argv: list[str] | None = None) -> int:
    """``python -m violation_pack.shared_corpora`` — print the live contract check."""
    import json
    import os
    import sys

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    from violation_pack.config import Settings  # local import; keeps module import-cheap

    settings = Settings.from_env()
    url = settings.qdrant_url or os.environ.get("QDRANT_URL")
    if not url:
        print("QDRANT_URL is not configured; set it in violation-refiner/.env")
        return 2
    reader = SharedCorpusReader(url=url, api_key=settings.qdrant_api_key)
    report = reader.verify_contract()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
