"""Tests for the bulk ingesters (jurisprudence, transcript, framework).

Uses the same in-memory `_FakeQdrantClient` pattern as test_extensions.py
so no network calls are made.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from violation_pack.embeddings import HashEmbedder


# ---------------------------------------------------------------------------
# Fake Qdrant (duplicated from test_extensions to keep this module self-
# contained; small enough not to be worth a shared conftest fixture).
# ---------------------------------------------------------------------------

class _FakeCollections:
    def __init__(self, names):
        self.collections = [type("C", (), {"name": n})() for n in names]


class _FakeQdrantClient:
    def __init__(self):
        self.points: dict[str, list[dict]] = {}

    def get_collections(self):
        return _FakeCollections(list(self.points.keys()))

    def get_collection(self, name):
        return type(
            "Info",
            (),
            {
                "config": type(
                    "Cfg",
                    (),
                    {"params": type("P", (), {"vectors": type("V", (), {"size": 64})()})()},
                )()
            },
        )()

    def create_collection(self, collection_name, vectors_config):
        self.points.setdefault(collection_name, [])

    def upsert(self, collection_name, points, wait=False):
        bucket = self.points.setdefault(collection_name, [])
        for p in points:
            bucket[:] = [x for x in bucket if x["id"] != p.id]
            bucket.append({"id": p.id, "vector": p.vector, "payload": p.payload})

    def search(self, collection_name, query_vector, limit, with_payload=True):
        bucket = self.points.get(collection_name, [])

        def cos(a, b):
            num = sum(x * y for x, y in zip(a, b))
            da = math.sqrt(sum(x * x for x in a)) or 1.0
            db = math.sqrt(sum(x * x for x in b)) or 1.0
            return num / (da * db)

        scored = [
            type(
                "H",
                (),
                {"id": p["id"], "score": cos(query_vector, p["vector"]), "payload": p["payload"]},
            )()
            for p in bucket
        ]
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:limit]


def _idx():
    pytest.importorskip("qdrant_client")
    from violation_pack.qdrant_index import QdrantVectorIndex

    return QdrantVectorIndex(
        url="http://fake",
        api_key=None,
        embedder=HashEmbedder(dim=64),
        client=_FakeQdrantClient(),
    )


# ---------------------------------------------------------------------------
# JurisprudenceIngester
# ---------------------------------------------------------------------------

def _make_ruling_files(tmp_path: Path, *, count: int = 3, with_url: bool = True) -> Path:
    """Build a fake juris-search corpus and return its index.json path."""
    json_dir = tmp_path / "json_jurisprudence"
    json_dir.mkdir()
    entries = []
    for i in range(count):
        json_path = json_dir / f"inteiro_teor_{i}.json"
        meta = {
            "downloaded_at": "2026-04-28T16:30:04Z",
            "numero_processo": f"7101000000{i}",
            "ano": "2024",
            "codigo": str(1000 + i),
            "search_params": {"tribunal": "TJRS"},
            "result_description": (
                f"Processo 7101000000{i} | Tipo: Apelação | "
                f"Relator: Test J{i} | Comarca: Porto Alegre"
            ),
        }
        if with_url:
            meta["source_url"] = f"https://example.test/r/{i}"
        body = (
            "RECURSO INOMINADO. " + ("texto " * 400)
            + "\n\nACÓRDÃO\n" + ("contenido " * 400)
        )
        json_path.write_text(
            json.dumps(
                {
                    "id": f"id-{i}",
                    "source_metadata": meta,
                    "text": body,
                    "text_chars": len(body),
                }
            ),
            encoding="utf-8",
        )
        entries.append(
            {
                "id": f"id-{i}",
                "status": "ready",
                "json_path": str(json_path),
            }
        )
    # One failed entry, to confirm it's skipped.
    entries.append({"id": "id-fail", "status": "failed", "json_path": None})

    index_path = json_dir / "index.json"
    index_path.write_text(
        json.dumps({"entries": entries, "total_entries": len(entries)}),
        encoding="utf-8",
    )
    return index_path


def test_jurisprudence_ingester_indexes_ready_entries(tmp_path):
    from violation_pack.ingesters import JurisprudenceIngester

    index_path = _make_ruling_files(tmp_path, count=3)
    idx = _idx()
    ing = JurisprudenceIngester(index=idx, chunk_chars=1500, max_chunks_per_ruling=3)
    stats = ing.ingest(index_path)

    assert stats.scanned == 3
    assert stats.failed == 0
    assert stats.upserted >= 3  # at least one chunk per ruling

    coll = idx.client.points[idx._jurisprudence_coll]
    payloads = [p["payload"] for p in coll]
    assert all(p["court"] == "TJRS" for p in payloads)
    assert all(p["primary_source_url"].startswith("https://example.test/r/") for p in payloads)
    assert all(p["relator"].startswith("Test J") for p in payloads)
    # chunk_count consistent within a ruling
    by_record = {}
    for p in payloads:
        by_record.setdefault(p["record_id"], []).append(p["chunk_index"])
    for chunks in by_record.values():
        assert sorted(chunks) == list(range(len(chunks)))

    # Re-ingest is idempotent (same point ids).
    before = len(coll)
    ing.ingest(index_path)
    assert len(idx.client.points[idx._jurisprudence_coll]) == before


def test_jurisprudence_ingester_max_chunks_per_ruling(tmp_path):
    from violation_pack.ingesters import JurisprudenceIngester

    index_path = _make_ruling_files(tmp_path, count=1)
    idx = _idx()
    ing = JurisprudenceIngester(index=idx, chunk_chars=200, max_chunks_per_ruling=2)
    stats = ing.ingest(index_path)
    assert stats.scanned == 1
    assert stats.upserted == 2  # capped


# ---------------------------------------------------------------------------
# TranscriptIngester
# ---------------------------------------------------------------------------

def _make_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "INCIDENT_TEST"
    forensics = bundle / "evidence" / "structured_data" / "_from_forensics"
    forensics.mkdir(parents=True)
    doc = {
        "title": "aeropuerto_TEST_1",
        "filename": "aeropuerto_TEST_1",
        "recordingdatetime": "2024-07-05T11:57",
        "location": "Aeropuerto",
        "content": [
            {"speaker": "Leandro", "start": 16.0, "end": 18.0, "text": "hola", "id": "0"},
            {"speaker": "Pilot", "start": 18.1, "end": 19.5, "text": "buenos dias", "id": "1"},
            {"speaker": "Leandro", "start": 19.6, "end": 21.0, "text": "", "id": "2"},  # empty
        ],
        "metadata": {"fileInfo": {"fileName": "aeropuerto_TEST_1.m4a"}},
    }
    (forensics / "aeropuerto_TEST_1.json").write_text(
        json.dumps(doc), encoding="utf-8"
    )
    return bundle


def test_transcript_ingester_skips_empty_and_tags_audio(tmp_path):
    from violation_pack.ingesters import TranscriptIngester

    bundle = _make_bundle(tmp_path)
    idx = _idx()
    ing = TranscriptIngester(index=idx)
    stats = ing.ingest_bundle(bundle)

    assert stats.scanned == 1
    assert stats.upserted == 2  # empty segment dropped
    coll = idx.client.points[idx._segments_coll]
    payloads = [p["payload"] for p in coll]
    assert {p["segment_id"] for p in payloads} == {
        "aeropuerto_TEST_1.seg-0",
        "aeropuerto_TEST_1.seg-1",
    }
    p0 = next(p for p in payloads if p["segment_id"].endswith("seg-0"))
    assert p0["audio_uri"] == "aeropuerto_TEST_1.m4a"
    assert p0["audio_offset_start"] == 16.0
    assert p0["violation_id"].startswith("TRANSCRIPT:")
    assert p0["bundle_id"] == "INCIDENT_TEST"


# ---------------------------------------------------------------------------
# FrameworkIngester
# ---------------------------------------------------------------------------

def test_framework_ingester_parses_article_headers(tmp_path):
    from violation_pack.ingesters import FrameworkIngester

    md = tmp_path / "framework.md"
    md.write_text(
        "# Código Penal\n\n"
        "### Art. 193 — Falsedad ideológica\n\n"
        "El que en ejercicio de su función...\n"
        "comete falsedad.\n\n"
        "### Art. 269 ter — Otro tipo\n\n"
        "El funcionario que omitiere...\n",
        encoding="utf-8",
    )
    idx = _idx()
    ing = FrameworkIngester(index=idx)
    stats = ing.ingest_markdown(md, framework_code="CHIPENCOD")
    assert stats.scanned == 2
    assert stats.upserted == 2
    payloads = [p["payload"] for p in idx.client.points[idx._articles_coll]]
    ids = {p["article_id"] for p in payloads}
    assert "CHIPENCOD.Art.193" in ids
    assert any("falsedad" in p["verbatim_excerpt"].lower() for p in payloads)
