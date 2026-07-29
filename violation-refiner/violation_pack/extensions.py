"""Extension protocols — the seam for Qdrant / Neo4j / jurisprudence work.

The core library never imports `qdrant_client`, `neo4j`, or any
jurisprudence backend. It only knows the Protocol interfaces below.
When you implement one of these (in this package or in a separate one),
you wire it up at the application layer — `examples/refine_cl005.py`
shows where the wiring point is.

That decoupling is what keeps the install footprint small (pydantic only)
and what lets the extensions be developed and versioned independently.

This module deliberately uses Protocols rather than abstract base classes
so that an implementation doesn't have to inherit from anything — it just
needs the right methods. That makes the eventual MCP-tool wrapping
trivial: an MCP tool is "satisfies the protocol" without being told to.
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from .models import Authority, EvidenceSegment, NexusEntry, Violation


# ---------------------------------------------------------------------------
# 1. JurisprudenceProvider
# ---------------------------------------------------------------------------

@runtime_checkable
class JurisprudenceProvider(Protocol):
    """Looks up case law / doctrine and returns Authority records WITH evidence.

    The contract: when this returns an Authority with `verified=True`, the
    rol/sala/fecha/holding MUST come from a primary source the implementation
    can show. Implementations that LLM-fabricate any of these fields are in
    violation of the contract and must NOT set verified=True.

    Today: not implemented in this package. Wire your own.

    Tomorrow's implementations might include:
      * BCNJurisprudenceProvider — fetches from bcn.cl
      * PoderJudicialProvider    — fetches from pjud.cl
      * QdrantJurisprudenceIndex — runs vector similarity over an indexed
        corpus of cases, returns top-k with full provenance per hit.
    """

    def search(
        self,
        query: str,
        supports: list[str],
        max_results: int = 5,
    ) -> list[Authority]:
        """Return Authority records matching the query.

        Note: `supports` is the list of element IDs the authority would
        support; passing this in lets the provider rank cases by which
        elements they actually address.
        """

    def verify(self, authority: Authority) -> Authority:
        """Take an unverified Authority stub and attempt to verify it against
        a primary source. If the stub's `proposition_to_verify` cannot be
        substantiated, return the authority unchanged (verified stays False)."""


# ---------------------------------------------------------------------------
# 2. VectorIndex — Qdrant-shaped
# ---------------------------------------------------------------------------

@runtime_checkable
class VectorIndex(Protocol):
    """Index over the embeddable content in the bundle.

    Today: not implemented in this package.

    Why a separate Protocol from JurisprudenceProvider? Because a vector
    index is fundamentally a retrieval primitive — given an embedding,
    return nearest neighbours — while a JurisprudenceProvider is a
    higher-level service. A Qdrant-backed JurisprudenceProvider IS-A
    VectorIndex consumer, but VectorIndex itself can also be used to find
    "similar segments to seg-55 across all violations in the corpus" or
    "elements that look like this contested one, where they were
    established".

    Suggested collections:
      * `segments`     — one point per EvidenceSegment, payload includes
                         segment_id, role_in_argument, source_uri.
      * `articles`     — one point per CachedArticle.verbatim_excerpt.
      * `elements`     — one point per Element, with proof_status as filter.
      * `jurisprudence` — one point per indexed case excerpt.
    """

    def upsert_segment(self, segment: EvidenceSegment, violation_id: str) -> None: ...
    def search_segments(self, query_text: str, top_k: int = 5) -> list[dict]: ...

    def upsert_authority(self, authority: Authority, violation_id: str) -> None: ...
    def search_authorities(self, query_text: str, top_k: int = 5) -> list[dict]: ...


# ---------------------------------------------------------------------------
# 3. KnowledgeGraph — Neo4j-shaped
# ---------------------------------------------------------------------------

@runtime_checkable
class KnowledgeGraph(Protocol):
    """Graph view over the bundle for chronological / implication walks.

    Today: not implemented in this package.

    Suggested schema:
      Nodes
        (:Violation         {violation_id, title, severity})
        (:Segment           {segment_id, audio_offset_start, audio_offset_end, speaker})
        (:Article           {article_id, framework_code})
        (:Element           {element_id, proof_status})
        (:Authority         {authority_id, verified})
        (:OpenQuestion      {id, priority})

      Edges (typed)
        (:Violation)-[:HAS_SEGMENT]->(:Segment)
        (:Violation)-[:CITES]->(:Article)
        (:Element)-[:OF]->(:Article)
        (:Segment)-[:SUPPORTS {strength}]->(:Element)
        (:Authority)-[:SUPPORTS]->(:Element)
        (:Violation)-[:CROSS_REFERENCES {relation}]->(:Violation)
        (:OpenQuestion)-[:BLOCKS]->(:Element)

    The chronological / implication queries this enables:
      * "What other violations cite Art. 193 with a contested
        documento_oficial element?"  — find them, see if any have resolved
        that element and how.
      * "If OQ-CL005-PDI-PARTE flips to resolved, which elements upgrade
        and which violations' confidence values move?" — walk BLOCKS edges
        forward.
      * "Show the sequence of segments anchored to STG-7 in audio order
        for any violation that touches them."  — temporal walk.
    """

    def upsert_violation(self, violation: Violation) -> None: ...

    def link_cross_references(self, violation: Violation) -> None: ...

    def find_violations_citing(self, article_id: str) -> list[str]: ...

    def find_violations_with_contested_element(self, element_id_glob: str) -> list[str]: ...

    def walk_implications_of_open_question(self, open_question_id: str) -> list[dict]:
        """Return the chain: which elements would change, which confidence
        values would re-derive, which sibling violations would be affected."""
