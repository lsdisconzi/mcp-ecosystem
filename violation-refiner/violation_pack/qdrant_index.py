"""Qdrant-backed implementation of the `VectorIndex` Protocol.

Four collections are managed under a configurable name prefix:

  <prefix>_segments       — one point per EvidenceSegment
  <prefix>_articles       — one point per CachedArticle
  <prefix>_authorities    — one point per Authority (verified or stub)
  <prefix>_jurisprudence  — corpus of indexed cases (populated by the user)

The class deliberately stays small: it offers the methods on the
`VectorIndex` Protocol plus a couple of helpers (`upsert_violation`,
`ensure_collections`) so callers can index a whole bundle in one call.
"""
from __future__ import annotations

import uuid
from typing import Any

from .embeddings import Embedder, default_embedder
from .models import Authority, CachedArticle, EvidenceSegment, Violation


def _stable_point_id(*parts: str) -> str:
    """Qdrant accepts unsigned ints or UUIDs. We synthesise a UUID5 in a
    fixed namespace so the same logical key always maps to the same point id
    and upserts are idempotent."""
    ns = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # DNS namespace
    return str(uuid.uuid5(ns, "|".join(parts)))


class QdrantVectorIndex:
    """Implements `violation_pack.extensions.VectorIndex`."""

    def __init__(
        self,
        url: str,
        api_key: str | None = None,
        collection_prefix: str = "violationrefiner_v1",
        embedder: Embedder | None = None,
        client: Any | None = None,
    ) -> None:
        try:
            from qdrant_client import QdrantClient  # type: ignore
        except ImportError as exc:
            raise SystemExit(
                "qdrant-client is required. Install with: "
                "pip install -e '.[qdrant]'  (or: pip install qdrant-client)"
            ) from exc
        self._QdrantClient = QdrantClient
        self.client = client or QdrantClient(url=url, api_key=api_key)
        self.prefix = collection_prefix
        self.embedder = embedder or default_embedder()
        self._ensured: set[str] = set()

    # ------------------------------------------------------------------ utils

    @property
    def _segments_coll(self) -> str:
        return f"{self.prefix}_segments"

    @property
    def _articles_coll(self) -> str:
        return f"{self.prefix}_articles"

    @property
    def _authorities_coll(self) -> str:
        return f"{self.prefix}_authorities"

    @property
    def _jurisprudence_coll(self) -> str:
        return f"{self.prefix}_jurisprudence"

    @property
    def collections(self) -> list[str]:
        return [
            self._segments_coll,
            self._articles_coll,
            self._authorities_coll,
            self._jurisprudence_coll,
        ]

    def ensure_collections(self) -> None:
        """Create the four collections if they don't exist.

        If a collection exists with a different vector size than the current
        embedder produces, raises RuntimeError directing the caller to
        `reset_collections()`. This catches the silent-corruption case where
        the embedder is changed without resetting the index.
        """
        from qdrant_client.http import models as qm  # type: ignore

        dim = self.embedder.dim
        existing = {c.name for c in self.client.get_collections().collections}
        for name in self.collections:
            if name in self._ensured:
                continue
            if name in existing:
                info = self.client.get_collection(name)
                existing_dim = info.config.params.vectors.size
                if existing_dim != dim:
                    raise RuntimeError(
                        f"Collection {name!r} has dim={existing_dim} but the "
                        f"current embedder ({self.embedder.name}) produces "
                        f"dim={dim}. Call reset_collections() to recreate."
                    )
            else:
                self.client.create_collection(
                    collection_name=name,
                    vectors_config=qm.VectorParams(
                        size=dim, distance=qm.Distance.COSINE
                    ),
                )
            self._ensured.add(name)

    def reset_collections(self) -> dict[str, str]:
        """Delete and recreate every namespaced collection. Returns the new
        dim per collection. ONLY affects this prefix; other tenants are safe."""
        from qdrant_client.http import models as qm  # type: ignore

        existing = {c.name for c in self.client.get_collections().collections}
        for name in self.collections:
            if name in existing:
                self.client.delete_collection(collection_name=name)
        self._ensured.clear()
        dim = self.embedder.dim
        for name in self.collections:
            self.client.create_collection(
                collection_name=name,
                vectors_config=qm.VectorParams(
                    size=dim, distance=qm.Distance.COSINE
                ),
            )
            self._ensured.add(name)
        return {name: f"dim={dim} embedder={self.embedder.name}" for name in self.collections}

    def _embed_one(self, text: str) -> list[float]:
        return self.embedder.embed([text])[0]

    def _upsert(self, collection: str, point_id: str, vector: list[float], payload: dict) -> None:
        from qdrant_client.http import models as qm  # type: ignore

        self.client.upsert(
            collection_name=collection,
            points=[qm.PointStruct(id=point_id, vector=vector, payload=payload)],
            wait=False,
        )

    def _search(
        self, collection: str, query_text: str, top_k: int
    ) -> list[dict]:
        vec = self._embed_one(query_text)
        # qdrant-client >= 1.13 prefers query_points; fall back to search for
        # older versions and in-memory fakes.
        query_points = getattr(self.client, "query_points", None)
        if callable(query_points):
            resp = query_points(
                collection_name=collection,
                query=vec,
                limit=top_k,
                with_payload=True,
            )
            hits = getattr(resp, "points", resp)
        else:
            hits = self.client.search(
                collection_name=collection,
                query_vector=vec,
                limit=top_k,
                with_payload=True,
            )
        return [
            {"id": str(h.id), "score": float(h.score), "payload": dict(h.payload or {})}
            for h in hits
        ]

    # ------------------------------------------------------- VectorIndex API

    def upsert_segment(self, segment: EvidenceSegment, violation_id: str) -> None:
        self.ensure_collections()
        text = f"{segment.verbatim_es}\n\n{segment.translation_en}"
        pid = _stable_point_id("segment", violation_id, segment.segment_id)
        self._upsert(
            self._segments_coll,
            pid,
            self._embed_one(text),
            {
                "violation_id": violation_id,
                "segment_id": segment.segment_id,
                "role_in_argument": segment.role_in_argument,
                "speaker": segment.speaker,
                "audio_offset_start": segment.audio_offset_start,
                "audio_offset_end": segment.audio_offset_end,
                "source_uri": segment.source_uri,
                "audio_uri": segment.audio_uri,
                "verbatim_es": segment.verbatim_es,
                "translation_en": segment.translation_en,
            },
        )

    def search_segments(self, query_text: str, top_k: int = 5) -> list[dict]:
        self.ensure_collections()
        return self._search(self._segments_coll, query_text, top_k)

    def upsert_authority(self, authority: Authority, violation_id: str) -> None:
        self.ensure_collections()
        text = f"{authority.research_query}\n{authority.proposition_to_verify}"
        if authority.holding_summary:
            text += f"\n{authority.holding_summary}"
        pid = _stable_point_id("authority", violation_id, authority.authority_id)
        self._upsert(
            self._authorities_coll,
            pid,
            self._embed_one(text),
            {
                "violation_id": violation_id,
                "authority_id": authority.authority_id,
                "type": authority.type,
                "supports": list(authority.supports),
                "research_query": authority.research_query,
                "proposition_to_verify": authority.proposition_to_verify,
                "verified": authority.verified,
                "court": authority.court,
                "rol": authority.rol,
                "holding_summary": authority.holding_summary,
            },
        )

    def search_authorities(self, query_text: str, top_k: int = 5) -> list[dict]:
        self.ensure_collections()
        return self._search(self._authorities_coll, query_text, top_k)

    # ------------------------------------------------------------- helpers

    def upsert_article(self, article: CachedArticle, violation_id: str) -> None:
        self.ensure_collections()
        pid = _stable_point_id("article", violation_id, article.article_id)
        self._upsert(
            self._articles_coll,
            pid,
            self._embed_one(article.verbatim_excerpt),
            {
                "violation_id": violation_id,
                "article_id": article.article_id,
                "article_name": article.article_name,
                "framework_code": article.framework_code,
                "verbatim_excerpt": article.verbatim_excerpt,
                "duty_bearer": article.duty_bearer,
                "norm_type": article.norm_type,
            },
        )

    def search_articles(self, query_text: str, top_k: int = 5) -> list[dict]:
        self.ensure_collections()
        return self._search(self._articles_coll, query_text, top_k)

    def search_jurisprudence(self, query_text: str, top_k: int = 5) -> list[dict]:
        """Search the jurisprudence corpus. Populated by ingestion scripts
        outside this package; this method does not write to it."""
        self.ensure_collections()
        return self._search(self._jurisprudence_coll, query_text, top_k)

    def upsert_jurisprudence_record(
        self,
        record_id: str,
        text: str,
        payload: dict,
    ) -> None:
        """Ingest one jurisprudence excerpt. `payload` should include at
        minimum: court, rol, decision_date, primary_source_url, holding."""
        self.ensure_collections()
        self._upsert(
            self._jurisprudence_coll,
            _stable_point_id("jurisprudence", record_id),
            self._embed_one(text),
            {"record_id": record_id, "text": text, **payload},
        )

    def upsert_violation(self, violation: Violation) -> dict[str, int]:
        """Index every segment, article and authority on a violation.

        Embeddings for ALL items are computed in a single batched call to
        minimise API quota usage (important for rate-limited providers like
        Voyage). Returns counts per collection.
        """
        from qdrant_client.http import models as qm  # type: ignore

        self.ensure_collections()
        vid = violation.violation_id

        # 1. Collect (collection, point_id, payload, text) for every item.
        jobs: list[tuple[str, str, dict, str]] = []

        for seg in violation.segments:
            text = f"{seg.verbatim_es}\n\n{seg.translation_en}"
            jobs.append((
                self._segments_coll,
                _stable_point_id("segment", vid, seg.segment_id),
                {
                    "violation_id": vid,
                    "segment_id": seg.segment_id,
                    "role_in_argument": seg.role_in_argument,
                    "speaker": seg.speaker,
                    "audio_offset_start": seg.audio_offset_start,
                    "audio_offset_end": seg.audio_offset_end,
                    "source_uri": seg.source_uri,
                    "audio_uri": seg.audio_uri,
                    "verbatim_es": seg.verbatim_es,
                    "translation_en": seg.translation_en,
                },
                text,
            ))

        for art in violation.established_articles:
            jobs.append((
                self._articles_coll,
                _stable_point_id("article", vid, art.article_id),
                {
                    "violation_id": vid,
                    "article_id": art.article_id,
                    "article_name": art.article_name,
                    "framework_code": art.framework_code,
                    "verbatim_excerpt": art.verbatim_excerpt,
                    "duty_bearer": art.duty_bearer,
                    "norm_type": art.norm_type,
                },
                art.verbatim_excerpt,
            ))

        for auth in violation.authorities:
            text = f"{auth.research_query}\n{auth.proposition_to_verify}"
            if auth.holding_summary:
                text += f"\n{auth.holding_summary}"
            jobs.append((
                self._authorities_coll,
                _stable_point_id("authority", vid, auth.authority_id),
                {
                    "violation_id": vid,
                    "authority_id": auth.authority_id,
                    "type": auth.type,
                    "supports": list(auth.supports),
                    "research_query": auth.research_query,
                    "proposition_to_verify": auth.proposition_to_verify,
                    "verified": auth.verified,
                    "court": auth.court,
                    "rol": auth.rol,
                    "holding_summary": auth.holding_summary,
                },
                text,
            ))

        if not jobs:
            return {"segments": 0, "articles": 0, "authorities": 0}

        # 2. One batched embed call. The Embedder Protocol handles its own
        #    internal batching when a single batch exceeds provider limits.
        vectors = self.embedder.embed([t for _, _, _, t in jobs])

        # 3. Group by collection and upsert in batches.
        by_coll: dict[str, list] = {}
        for (coll, pid, payload, _), vec in zip(jobs, vectors):
            by_coll.setdefault(coll, []).append(
                qm.PointStruct(id=pid, vector=vec, payload=payload)
            )
        for coll, pts in by_coll.items():
            self.client.upsert(collection_name=coll, points=pts, wait=False)

        return {
            "segments": len(violation.segments),
            "articles": len(violation.established_articles),
            "authorities": len(violation.authorities),
        }
