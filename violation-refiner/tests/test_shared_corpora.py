"""Tests for the read-only shared-collection reader.

Everything here runs against an in-memory fake — **no network, no credentials**,
so the suite stays runnable offline and in CI. The fake is shaped to the exact
subset of the Qdrant client surface that ``shared_corpora`` uses
(``get_collection`` / ``scroll`` / ``retrieve`` / ``search``).

The properties pinned here are the ones that were actually gotten wrong during
implementation, both silently:

* ``transcript_point_id`` must return the **dashed** uuid form; comparing it
  against the bare ``md5(...).hexdigest()`` matches nothing at all.
* semantic search must refuse to run without a dimension-matched embedder,
  because the shared collections are 384-d while violation-refiner's own
  default is a 1024-d Voyage model. Querying across them "succeeds" and returns
  meaningless neighbours.
"""
from __future__ import annotations

import hashlib
import math
import uuid
from pathlib import Path

import pytest

from violation_pack.shared_corpora import (
    REVIEWED_TRANSCRIPTS,
    SHARED_COLLECTIONS,
    TRANSCRIPTION_LAW,
    EmbedderMismatch,
    SharedCorpusError,
    SharedCorpusReader,
    law_point_id,
    transcript_point_id,
)


ROOT = Path(__file__).resolve().parents[1]
SPEAKER_INDEX = ROOT / "data" / "speaker_index.json"


# ---------------------------------------------------------------------------
# Fake Qdrant client — only the surface shared_corpora touches
# ---------------------------------------------------------------------------

class _Hit:
    def __init__(self, point):
        self.id = point["id"]
        self.payload = point["payload"]
        self.vector = point.get("vector")


class _Info:
    def __init__(self, dim: int, points: int):
        self.config = type(
            "Cfg", (), {"params": type("P", (), {"vectors": type("V", (), {"size": dim})()})()}
        )()
        self.points_count = points


class FakeSharedClient:
    def __init__(self, collections: dict[str, dict]):
        self.collections = collections  # name -> {"dim": int, "points": [...]}

    def get_collection(self, name):
        if name not in self.collections:
            raise ValueError(f"collection {name!r} not found")
        spec = self.collections[name]
        return _Info(spec["dim"], len(spec["points"]))

    def scroll(self, collection_name, limit=10, offset=None, with_payload=True,
               with_vectors=False, scroll_filter=None, **kwargs):
        points = self.collections[collection_name]["points"]
        if scroll_filter is not None:
            points = [p for p in points if _matches(scroll_filter, p["payload"])]
        window = points[(offset or 0): (offset or 0) + limit]
        nxt = (offset or 0) + limit
        return [_Hit(p) for p in window], (nxt if nxt < len(points) else None)

    def retrieve(self, collection_name, ids, with_payload=True, **kwargs):
        wanted = {str(i) for i in ids}
        return [
            _Hit(p)
            for p in self.collections[collection_name]["points"]
            if str(p["id"]) in wanted
        ]

    def search(self, collection_name, query_vector, limit=10, query_filter=None, **kwargs):
        points = self.collections[collection_name]["points"]
        if query_filter is not None:
            points = [p for p in points if _matches(query_filter, p["payload"])]

        def cos(a, b):
            num = sum(x * y for x, y in zip(a, b))
            da = math.sqrt(sum(x * x for x in a)) or 1.0
            db = math.sqrt(sum(x * x for x in b)) or 1.0
            return num / (da * db)

        hits = [
            type("H", (), {"id": p["id"], "score": cos(query_vector, p["vector"]),
                           "payload": p["payload"]})()
            for p in points
        ]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]


def _matches(qdrant_filter, payload: dict) -> bool:
    """Evaluate the subset of ``Filter`` that ``_filter()`` builds (must/must_not)."""
    for condition in getattr(qdrant_filter, "must", None) or []:
        key = condition.key
        if key is None:
            continue
        wanted = condition.match.value
        if payload.get(key) != wanted:
            return False
    for condition in getattr(qdrant_filter, "must_not", None) or []:
        key = condition.key
        if key is None:
            continue
        if payload.get(key) == condition.match.value:
            return False
    return True


class FakeEmbedder:
    def __init__(self, name: str, dim: int):
        self.name = name
        self.dim = dim

    def embed(self, texts):
        return [[0.0] * self.dim for _ in texts]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _law_point(original_id: str, *, framework_code="CHIPENCOD", language="en", n=0):
    return {
        "id": law_point_id(original_id),
        "vector": [1.0] + [0.0] * 383,
        "payload": {
            "original_id": original_id,
            "eli_id": original_id,
            "content": f"body {n}",
            "text": f"body {n}",
            "framework_code": framework_code,
            "language": language,
            "schema_version": "1",
            "record_kind": "article",
            "source_sha256": "d" * 64,
            "article_number": original_id.rsplit(".Art.", 1)[-1],
            "title": f"Article {n}",
        },
    }


def _segment_point(transcript_id: str, index: int, **overrides):
    payload = {
        "transcript_id": transcript_id,
        "segment_id": f"{transcript_id}.seg-{index}",
        "segment_index": index,
        "speaker": "passenger",
        "text": f"verbatim {index}",
        "reviewed": True,
        "speaker_id": "SPK-passenger-leandro",
        "source_file": "audio.m4a",
        "case_id": "I-002",
        "narrative_id": "NAR-01",
    }
    payload.update(overrides)
    return {
        "id": transcript_point_id(transcript_id, index),
        "vector": [0.5] + [0.0] * 383,
        "payload": payload,
    }


@pytest.fixture
def client():
    return FakeSharedClient(
        {
            "transcription_law": {
                "dim": 384,
                "points": [
                    _law_point("CL.CHIPENCOD.T4.C3.Art.193", n=1),
                    _law_point("CL.CHIPENCOD.T4.C3.Art.194", n=2),
                    _law_point(
                        "BR.ABEAR_COC.SA.I", framework_code="ABEAR_COC", language="pt", n=3
                    ),
                ],
            },
            "reviewed_transcripts": {
                "dim": 384,
                "points": [
                    _segment_point("T-1", 0),
                    _segment_point("T-1", 1, speaker="airline_pilot",
                                   speaker_id="SPK-pilot-ruiz"),
                    _segment_point("T-2", 0, case_id="I-003"),
                ],
            },
        }
    )


@pytest.fixture
def reader(client):
    return SharedCorpusReader(client=client)


# ---------------------------------------------------------------------------
# Point-id derivation
# ---------------------------------------------------------------------------

def test_law_point_id_is_a_namespace_uuid5() -> None:
    expected = str(uuid.uuid5(uuid.NAMESPACE_DNS, "CL.CHIPENCOD.T4.C3.Art.193"))
    assert law_point_id("CL.CHIPENCOD.T4.C3.Art.193") == expected
    assert law_point_id("a") != law_point_id("b")


def test_transcript_point_id_is_dashed_and_matches_md5() -> None:
    """The dashed form is the whole point — the bare hexdigest matches nothing."""
    digest = hashlib.md5("T-1:7".encode()).hexdigest()
    assert transcript_point_id("T-1", 7) == str(uuid.UUID(digest))
    assert transcript_point_id("T-1", 7) != digest
    assert transcript_point_id("T-1", 7).count("-") == 4


def test_transcript_point_id_is_injectivity_per_transcript() -> None:
    assert transcript_point_id("T-1", 0) != transcript_point_id("T-2", 0)
    assert transcript_point_id("T-1", 0) != transcript_point_id("T-1", 1)


# ---------------------------------------------------------------------------
# Declared contracts
# ---------------------------------------------------------------------------

def test_both_shared_collections_are_declared_384d() -> None:
    assert set(SHARED_COLLECTIONS) == {"transcription_law", "reviewed_transcripts"}
    for contract in SHARED_COLLECTIONS.values():
        assert contract.dim == 384
        assert contract.embed_model == "all-MiniLM-L6-v2"
        assert contract.owner == "transcription"


def test_reviewed_transcripts_contract_requires_the_join_keys() -> None:
    """``segment_id`` and ``speaker_id`` are what make it the right read target."""
    for key in ("transcript_id", "segment_index", "segment_id", "speaker_id", "reviewed"):
        assert key in REVIEWED_TRANSCRIPTS.required_payload_keys, key
    assert "original_id" in TRANSCRIPTION_LAW.required_payload_keys


def test_contract_check_passes_on_a_conforming_collection(client) -> None:
    report = TRANSCRIPTION_LAW.check(client)
    assert report["ok"] is True
    assert report["problems"] == []
    assert report["dim"] == 384
    assert report["points"] == 3


def test_contract_check_reports_drift_without_raising() -> None:
    client = FakeSharedClient(
        {
            "transcription_law": {
                "dim": 768,
                "points": [{"id": "x", "vector": [0.0] * 768, "payload": {"original_id": "a"}}],
            }
        }
    )
    report = TRANSCRIPTION_LAW.check(client)

    assert report["ok"] is False
    assert any("dim=768" in p for p in report["problems"])
    assert any("payload missing keys" in p for p in report["problems"])


def test_contract_check_reports_an_unreachable_collection() -> None:
    report = TRANSCRIPTION_LAW.check(FakeSharedClient({}))
    assert report["ok"] is False
    assert report["problems"] and "unreachable" in report["problems"][0]


def test_contract_check_reports_a_mismatched_point_id(client) -> None:
    client.collections["transcription_law"]["points"][0]["id"] = "not-a-uuid5"
    report = TRANSCRIPTION_LAW.check(client)
    assert report["ok"] is False
    assert any("!= derived" in p for p in report["problems"])


def test_verify_contract_aggregates_and_can_assert_counts(client) -> None:
    reader_ok = SharedCorpusReader(client=client).verify_contract()
    assert reader_ok["ok"] is True
    assert {c["name"] for c in reader_ok["collections"]} == set(SHARED_COLLECTIONS)

    expected = SharedCorpusReader(client=client).verify_contract(
        expect_points={"transcription_law": 999}
    )
    assert expected["ok"] is False


# ---------------------------------------------------------------------------
# Exact reads — no embedder needed
# ---------------------------------------------------------------------------

def test_law_article_reads_by_original_id(reader) -> None:
    article = reader.law_article("CL.CHIPENCOD.T4.C3.Art.193")
    assert article is not None
    assert article["original_id"] == "CL.CHIPENCOD.T4.C3.Art.193"
    assert article["framework_code"] == "CHIPENCOD"


def test_law_article_returns_none_for_an_unknown_id(reader) -> None:
    assert reader.law_article("NOPE") is None


def test_law_article_survives_a_bare_hexdigest_id_lookup(reader) -> None:
    """Regression: an undashed id used to match nothing, silently."""
    original_id = "CL.CHIPENCOD.T4.C3.Art.193"
    bare = hashlib.md5(original_id.encode()).hexdigest()
    # Not how ids are built here, but a lookup with junk must return None rather
    # than raising — a false negative must be visible as ``None``, not a crash.
    assert reader.law_article(bare) is None
    assert reader.law_article(original_id) is not None


def test_iter_law_articles_filters(reader) -> None:
    assert len(list(reader.iter_law_articles())) == 3
    assert len(list(reader.iter_law_articles(framework_code="CHIPENCOD"))) == 2
    assert len(list(reader.iter_law_articles(language="pt"))) == 1
    assert len(list(reader.iter_law_articles(framework_code="CHIPENCOD", language="en"))) == 2
    assert list(reader.iter_law_articles(framework_code="NOPE")) == []


def test_reviewed_segment_reads_by_pair(reader) -> None:
    segment = reader.reviewed_segment("T-1", 0)
    assert segment is not None
    assert segment["segment_id"] == "T-1.seg-0"
    assert segment["speaker_id"] == "SPK-passenger-leandro"


def test_reviewed_segment_returns_none_for_an_unknown_pair(reader) -> None:
    assert reader.reviewed_segment("T-1", 999) is None
    assert reader.reviewed_segment("NOPE", 0) is None


def test_reviewed_segments_returns_the_whole_transcript(reader) -> None:
    segments = reader.reviewed_segments("T-1")
    assert [s["segment_index"] for s in segments] == [0, 1]
    assert len(reader.reviewed_segments()) == 3  # all transcripts


def test_reviewed_segments_filters(reader) -> None:
    assert len(reader.reviewed_segments(case_id="I-002")) == 2
    assert len(reader.reviewed_segments(case_id="I-003")) == 1
    assert len(reader.reviewed_segments(speaker_id="SPK-pilot-ruiz")) == 1


# ---------------------------------------------------------------------------
# Semantic search — embedder guard
# ---------------------------------------------------------------------------

def test_search_without_an_embedder_raises_embedder_mismatch(reader) -> None:
    with pytest.raises(EmbedderMismatch):
        reader.search_law("detención arbitraria")


def test_search_with_a_wrong_dimension_raises_embedder_mismatch(client) -> None:
    """violation-refiner's own default is 1024-d Voyage — the real trap."""
    reader = SharedCorpusReader(client=client, embedder=FakeEmbedder("voyage-3-large", 1024))
    with pytest.raises(EmbedderMismatch) as excinfo:
        reader.search_law("detención arbitraria")
    assert "1024" in str(excinfo.value)
    assert "384" in str(excinfo.value)


def test_search_with_a_matching_embedder_runs(client) -> None:
    reader = SharedCorpusReader(client=client, embedder=FakeEmbedder("all-MiniLM-L6-v2", 384))
    hits = reader.search_law("anything", top_k=2)
    assert len(hits) == 2
    assert all("original_id" in h["payload"] for h in hits)

    segs = reader.search_reviewed_segments("anything", top_k=1)
    assert len(segs) == 1


def test_search_rejects_an_unknown_filter_key(client) -> None:
    """A typo must raise, not silently return zero rows.

    ``limit`` vs ``top_k`` is the concrete case: ``**filters`` used to absorb the
    mistake and build a filter on a key the collection does not have, so the call
    returned ``[]`` and looked like "no matches".
    """
    reader = SharedCorpusReader(client=client, embedder=FakeEmbedder("all-MiniLM-L6-v2", 384))
    with pytest.raises(SharedCorpusError) as excinfo:
        reader.search_law("anything", limit=2)  # type: ignore[call-arg]
    assert "limit" in str(excinfo.value)
    assert "top_k" in str(excinfo.value)


def test_search_accepts_a_real_filter_key(client) -> None:
    reader = SharedCorpusReader(client=client, embedder=FakeEmbedder("all-MiniLM-L6-v2", 384))
    hits = reader.search_reviewed_segments("anything", top_k=5, case_id="I-003")
    assert len(hits) == 1
    assert hits[0]["payload"]["case_id"] == "I-003"


def test_search_guard_names_the_missing_dependency(reader) -> None:
    with pytest.raises(EmbedderMismatch) as excinfo:
        reader.search_reviewed_segments("x")
    message = str(excinfo.value)
    assert "384" in message


# ---------------------------------------------------------------------------
# Construction + read-only guarantee
# ---------------------------------------------------------------------------

def test_reader_defaults_to_qdrant_env_vars(monkeypatch, client) -> None:
    monkeypatch.setenv("QDRANT_URL", "http://example.invalid:6333")
    monkeypatch.setenv("QDRANT_API_KEY", "secret")
    # Pass a client too, so no real QdrantClient is constructed (no warning noise).
    reader = SharedCorpusReader(client=client)
    assert reader.url == "http://example.invalid:6333"
    assert reader.api_key == "secret"


def test_reader_requires_a_url_when_nothing_is_supplied(monkeypatch) -> None:
    monkeypatch.delenv("QDRANT_URL", raising=False)
    with pytest.raises(SharedCorpusError):
        SharedCorpusReader()


def test_reader_exposes_no_write_path() -> None:
    """Read-only is a structural property, not a convention."""
    for forbidden in ("upsert", "delete", "create_collection", "recreate_collection"):
        assert not hasattr(SharedCorpusReader, forbidden), forbidden


def test_contract_lookup_rejects_an_undeclared_collection(reader) -> None:
    with pytest.raises(SharedCorpusError):
        reader.contract("transcription_transcripts")
    with pytest.raises(SharedCorpusError):
        reader.contract("la8159_law")
