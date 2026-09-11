"""Unit tests for the optional extensions.

These tests use lightweight in-memory fakes for qdrant-client and the neo4j
driver, so they run without contacting real services. Integration tests
against the actual cloud Qdrant / local Neo4j live separately.
"""
from __future__ import annotations

from typing import Any

import pytest

from violation_pack.embeddings import HashEmbedder
from violation_pack.models import (
    Authority,
    CachedArticle,
    EvidenceSegment,
    Incident,
    Violation,
)

from _fakes import FakeQdrantClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_violation() -> Violation:
    seg = EvidenceSegment(
        segment_id="STG-1.seg-1",
        role_in_argument="admission",
        audio_offset_start=1.0,
        audio_offset_end=2.0,
        speaker="Officer A",
        verbatim_es="reconozco la falta",
        verbatim_sha256="a" * 64,
        translation_en="I admit the fault",
        source_uri="Transcripts/t.html#seg-1",
        source_sha256="b" * 64,
    )
    art = CachedArticle(
        article_id="CL.CHIPENCOD.Art.193",
        article_name="Falsedad ideológica",
        verbatim_excerpt="comete falsedad",
        verbatim_excerpt_sha256="c" * 64,
        framework_code="CHIPENCOD",
        framework_cache_status="verified_in_bundle",
        duty_bearer="empleado público",
        norm_type="prohibition",
        applicability="direct",
        applicability_rationale="apt",
    )
    auth = Authority(
        authority_id="AUTH-1",
        type="jurisprudence",
        supports=["E1"],
        research_query="falsedad ideologica empleado publico",
        proposition_to_verify="public official falsifies → criminal",
    )
    return Violation(
        violation_id="CL-TEST",
        title="test",
        severity="LOW",
        incident=Incident(date="2024-01-01", location="X"),
        segments=[seg],
        established_articles=[art],
        authorities=[auth],
    )


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

def test_hash_embedder_is_deterministic():
    e = HashEmbedder(dim=64)
    a = e.embed(["hello world", "goodbye world"])
    b = e.embed(["hello world", "goodbye world"])
    assert a == b
    assert len(a[0]) == 64
    # Vectors should be normalised.
    assert abs(sum(x * x for x in a[0]) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Qdrant — shared in-memory fake (see tests/_fakes.py)
# ---------------------------------------------------------------------------


def test_qdrant_vector_index_upserts_and_searches(minimal_violation):
    pytest.importorskip("qdrant_client")
    from violation_pack.qdrant_index import QdrantVectorIndex

    fake = FakeQdrantClient()
    idx = QdrantVectorIndex(
        url="http://fake",
        api_key=None,
        embedder=HashEmbedder(dim=64),
        client=fake,
    )
    counts = idx.upsert_violation(minimal_violation)
    assert counts == {"segments": 1, "articles": 1, "authorities": 1}

    hits = idx.search_segments("reconozco la falta", top_k=5)
    assert hits and hits[0]["payload"]["segment_id"] == "STG-1.seg-1"

    # Idempotence: second upsert does not duplicate.
    idx.upsert_violation(minimal_violation)
    assert len(fake.points["violationrefiner_v1_segments"]) == 1


def test_jurisprudence_provider_returns_unverified_stubs(minimal_violation):
    pytest.importorskip("qdrant_client")
    from violation_pack.jurisprudence import QdrantJurisprudenceProvider
    from violation_pack.qdrant_index import QdrantVectorIndex

    fake = FakeQdrantClient()
    idx = QdrantVectorIndex(
        url="http://fake",
        api_key=None,
        embedder=HashEmbedder(dim=64),
        client=fake,
    )
    idx.upsert_jurisprudence_record(
        "ROL-123-2024",
        text="empleado público comete falsedad ideológica",
        payload={
            "court": "Corte Suprema",
            "rol": "ROL-123-2024",
            "decision_date": "2024-03-15",
            "primary_source_url": "https://pjud.cl/.../ROL-123-2024",
            "holding": "el empleado público que altera registros comete falsedad",
        },
    )
    prov = QdrantJurisprudenceProvider(idx)

    stubs = prov.search("falsedad empleado público", ["E1"], max_results=3)
    assert stubs
    a = stubs[0]
    assert a.verified is False
    assert a.court is None and a.rol is None

    verified = prov.verify(a)
    assert verified.verified is True
    assert verified.rol == "ROL-123-2024"
    assert "primary_source_url" in (verified.verification_protocol or "")


def test_jurisprudence_verify_refuses_when_no_primary_source():
    pytest.importorskip("qdrant_client")
    from violation_pack.jurisprudence import QdrantJurisprudenceProvider
    from violation_pack.qdrant_index import QdrantVectorIndex

    fake = FakeQdrantClient()
    idx = QdrantVectorIndex(
        url="http://fake",
        api_key=None,
        embedder=HashEmbedder(dim=64),
        client=fake,
    )
    idx.upsert_jurisprudence_record(
        "ROL-NO-URL",
        text="some holding",
        payload={"court": "X", "rol": "ROL-NO-URL", "holding": "h"},
    )
    prov = QdrantJurisprudenceProvider(idx)
    stubs = prov.search("some holding", ["E1"], max_results=1)
    result = prov.verify(stubs[0])
    assert result.verified is False  # contract upheld


# ---------------------------------------------------------------------------
# Neo4j — fake driver
# ---------------------------------------------------------------------------

class _FakeSession:
    def __init__(self, ran: list[tuple[str, dict]]):
        self.ran = ran

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def run(self, query, **params):
        self.ran.append((query.strip(), dict(params)))

        # Return canned shapes for the read queries used in tests.
        q = query.strip().lower()
        if "match (v:violation)-[:cites]->" in q:
            return [type("R", (), {"data": lambda self_: {"vid": "CL-TEST"}})()]
        if "match (e:element)" in q and "contested" in q:
            return [type("R", (), {"data": lambda self_: {"vid": "CL-TEST"}})()]
        if "[:blocks]" in q:
            return []
        return []


class _FakeDriver:
    def __init__(self):
        self.ran: list[tuple[str, dict]] = []

    def session(self, database=None):
        return _FakeSession(self.ran)

    def close(self):
        pass


def test_neo4j_graph_upsert_runs_expected_queries(minimal_violation):
    pytest.importorskip("neo4j")
    from violation_pack.neo4j_graph import Neo4jKnowledgeGraph

    drv = _FakeDriver()
    kg = Neo4jKnowledgeGraph(
        uri="bolt://fake", user="u", password="p", driver=drv
    )
    kg.upsert_violation(minimal_violation)

    queries = [q for q, _ in drv.ran]
    # MERGE Violation issued.
    assert any("merge (vi:violation" in q.lower() for q in queries)
    # MERGE Segment + HAS_SEGMENT edge.
    assert any("has_segment" in q.lower() for q in queries)
    # MERGE Article + CITES edge.
    assert any(":cites" in q.lower() for q in queries)

    # find_violations_citing returns the canned answer.
    assert kg.find_violations_citing("CL.CHIPENCOD.Art.193") == ["CL-TEST"]
