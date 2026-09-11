"""Shared test doubles.

Kept in one module so the Qdrant fake cannot drift between test suites. It
previously existed as two near-identical copies, one in ``test_extensions.py``
and one in ``test_ingesters.py``, which had already diverged (only one of them
implemented ``get_collection``).
"""
from __future__ import annotations

import math


class FakeCollections:
    """Return shape of ``QdrantClient.get_collections()``."""

    def __init__(self, names: list[str]):
        self.collections = [type("C", (), {"name": n})() for n in names]


class FakeQdrantClient:
    """Minimal Qdrant-shaped fake.

    Stores points per collection and scores hits with cosine similarity over
    the supplied (already normalised) vectors. No network access.
    """

    def __init__(self):
        self.points: dict[str, list[dict]] = {}

    # -- lifecycle -----------------------------------------------------------
    def get_collections(self):
        return FakeCollections(list(self.points.keys()))

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

    # -- writes --------------------------------------------------------------
    def upsert(self, collection_name, points, wait=False):
        bucket = self.points.setdefault(collection_name, [])
        for p in points:
            # Upsert semantics: replace any existing point with the same id.
            bucket[:] = [x for x in bucket if x["id"] != p.id]
            bucket.append({"id": p.id, "vector": p.vector, "payload": p.payload})

    # -- reads ---------------------------------------------------------------
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
                {
                    "id": p["id"],
                    "score": cos(query_vector, p["vector"]),
                    "payload": p["payload"],
                },
            )()
            for p in bucket
        ]
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:limit]
