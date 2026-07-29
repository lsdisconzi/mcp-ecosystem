"""The five enrichment layers as pure functions.

Each `build_*` function:
* Takes a current Violation state and refinement inputs.
* Returns a new Violation (Pydantic is immutable-ish — we use `.model_copy`).
* Appends one ProvenanceEntry recording what was done.
* Is idempotent given the same inputs: re-running won't duplicate segments,
  articles, etc. — it merges by ID.

This shape is what makes each function a clean MCP tool candidate later:
single responsibility, JSON-in / JSON-out, deterministic, no side effects.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from ._utils import sha256_text
from .models import (
    Authority,
    CachedArticle,
    CandidateArticle,
    EvidenceSegment,
    FrameworkCache,
    NexusEntry,
    ProvenanceEntry,
    Violation,
)
from .sources import FrameworkSource, TranscriptSource


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _merge_by_id(
    existing: list, incoming: list, id_attr: str
) -> list:
    """Replace-by-ID merge. Idempotent: re-running with same input is a no-op."""
    by_id = {getattr(x, id_attr): x for x in existing}
    for item in incoming:
        by_id[getattr(item, id_attr)] = item
    return list(by_id.values())


# ---------------------------------------------------------------------------
# Layer 1 — Evidence
# ---------------------------------------------------------------------------

def build_evidence_layer(
    violation: Violation,
    transcript: TranscriptSource,
    segment_specs: Iterable[dict],
) -> Violation:
    """Add EvidenceSegments anchored to a TranscriptSource.

    Parameters
    ----------
    violation
        Current violation state.
    transcript
        A source implementing the TranscriptSource Protocol.
    segment_specs
        Iterable of dicts shaping the segments to include. Each dict supplies
        the *enrichment* (role, translation, notes); the verbatim text and
        offsets come from the transcript itself, NEVER from the spec.

        Required keys per spec:
            segment_id, role_in_argument, translation_en
        Optional keys:
            transcription_notes
    """
    new_segments: list[EvidenceSegment] = []
    src_uri = transcript.source_uri()
    src_sha = transcript.source_sha256()
    src_id = transcript.source_id()

    for spec in segment_specs:
        local_id = spec["segment_id"]
        parsed = transcript.get_segment(local_id)
        if parsed is None:
            raise ValueError(
                f"Segment {local_id!r} not found in transcript {src_id!r}; "
                "refusing to fabricate."
            )
        verbatim = parsed["verbatim"]
        new_segments.append(
            EvidenceSegment(
                segment_id=f"{src_id}.{local_id}",
                role_in_argument=spec["role_in_argument"],
                audio_offset_start=parsed["audio_offset_start"],
                audio_offset_end=parsed["audio_offset_end"],
                speaker=parsed["speaker"],
                verbatim_es=verbatim,
                verbatim_sha256=sha256_text(verbatim),
                translation_en=spec["translation_en"],
                transcription_notes=spec.get("transcription_notes"),
                source_uri=f"{src_uri}#{local_id}",
                source_sha256=src_sha,
            )
        )

    merged = _merge_by_id(violation.segments, new_segments, "segment_id")
    return violation.model_copy(
        update={
            "segments": merged,
            "provenance": violation.provenance + [
                ProvenanceEntry(
                    timestamp=_now(),
                    actor="layers.build_evidence_layer",
                    operation="add_or_replace_segments",
                    layer=1,
                    note=f"Anchored {len(new_segments)} segment(s) to transcript {src_id} (sha={src_sha[:8]}).",
                )
            ],
        }
    )


# ---------------------------------------------------------------------------
# Layer 2 — Norms
# ---------------------------------------------------------------------------

def build_norms_layer(
    violation: Violation,
    framework: FrameworkSource,
    article_specs: Iterable[dict],
    candidate_specs: Iterable[dict] = (),
) -> Violation:
    """Register a FrameworkCache and add CachedArticles / CandidateArticles.

    Each article_spec must include:
        article_id, article_name, subsections_invoked (list),
        verbatim_excerpt (the EXACT bytes the case wants to quote — verified
            against the cache below), duty_bearer, norm_type, applicability,
        applicability_rationale.

    If `verbatim_excerpt` is not a substring of the framework cache article
    body, this raises. That's how Layer 2 prevents inlined paraphrase from
    masquerading as cited text.
    """
    fw_code = framework.framework_code()
    cache = FrameworkCache(
        framework_code=fw_code,
        framework_name=fw_code,  # caller can refine via separate op if desired
        cache_file=framework.cache_uri(),
        cache_file_sha256=framework.cache_sha256(),
        cache_self_reported_sha256=framework.declared_sha256(),
        articles_cached=framework.articles_cached(),
    )

    new_articles: list[CachedArticle] = []
    for spec in article_specs:
        # Article numbers in the ELI ID are after '.Art.'.
        art_num = spec["article_id"].rsplit(".Art.", 1)[-1].split(".")[0]
        body = framework.get_article_body(art_num)
        if body is None:
            raise ValueError(
                f"Article {art_num} not found in framework {fw_code}; "
                "use candidate_specs instead, or fetch the framework first."
            )
        excerpt = spec["verbatim_excerpt"]
        if excerpt not in body:
            raise ValueError(
                f"verbatim_excerpt for {spec['article_id']} is not a substring "
                f"of the cached article body. Refusing to inline a paraphrase."
            )
        new_articles.append(
            CachedArticle(
                article_id=spec["article_id"],
                article_name=spec["article_name"],
                subsections_invoked=spec.get("subsections_invoked", []),
                verbatim_excerpt=excerpt,
                verbatim_excerpt_sha256=sha256_text(excerpt),
                framework_code=fw_code,
                framework_cache_status="verified_in_bundle",
                duty_bearer=spec["duty_bearer"],
                norm_type=spec["norm_type"],
                applicability=spec["applicability"],
                applicability_rationale=spec["applicability_rationale"],
            )
        )

    new_candidates = [CandidateArticle(**s) for s in candidate_specs]

    merged_caches = _merge_by_id(violation.framework_caches, [cache], "framework_code")
    merged_articles = _merge_by_id(violation.established_articles, new_articles, "article_id")
    merged_candidates = _merge_by_id(
        violation.candidate_articles, new_candidates, "candidate_article_id"
    )

    return violation.model_copy(
        update={
            "framework_caches": merged_caches,
            "established_articles": merged_articles,
            "candidate_articles": merged_candidates,
            "provenance": violation.provenance + [
                ProvenanceEntry(
                    timestamp=_now(),
                    actor="layers.build_norms_layer",
                    operation="add_or_replace_articles",
                    layer=2,
                    note=(
                        f"Registered framework {fw_code} (sha={cache.cache_file_sha256[:8]}); "
                        f"established {len(new_articles)} article(s); "
                        f"recorded {len(new_candidates)} candidate(s)."
                    ),
                )
            ],
        }
    )


# ---------------------------------------------------------------------------
# Layer 3 — Element grid
#
# Already shaped via models.ArticleElementGrid. Layer 3's "builder" is just
# a merge helper; element libraries (which doctrinal elements an article
# has) are caller-supplied today but could be a separate ElementLibrary
# Protocol later.
# ---------------------------------------------------------------------------

def add_element_grid(violation: Violation, grid) -> Violation:
    """Add or replace an ArticleElementGrid (by article_id)."""
    merged = _merge_by_id(violation.element_grids, [grid], "article_id")
    return violation.model_copy(
        update={
            "element_grids": merged,
            "provenance": violation.provenance + [
                ProvenanceEntry(
                    timestamp=_now(),
                    actor="layers.add_element_grid",
                    operation="add_or_replace_element_grid",
                    layer=3,
                    note=f"Grid for {grid.article_id}: {len(grid.elements)} elements; weighted score {grid.weighted_score():.2f}.",
                )
            ],
        }
    )


# ---------------------------------------------------------------------------
# Layer 4 — Nexus matrix
# ---------------------------------------------------------------------------

def build_nexus_layer(violation: Violation, entries: Iterable[NexusEntry | dict]) -> Violation:
    """Append nexus entries. By design we keep duplicates collapsible only by
    the (fact_id, norm_id, element_id) triple — same triple = replace; new
    triple = append. This lets you incrementally enrich without dedup-fear."""
    incoming: list[NexusEntry] = [
        e if isinstance(e, NexusEntry) else NexusEntry(**e) for e in entries
    ]

    def key(n: NexusEntry) -> tuple[str, str, str]:
        return (n.fact_id, n.norm_id, n.element_id)

    by_key = {key(n): n for n in violation.nexus_matrix}
    for n in incoming:
        by_key[key(n)] = n

    return violation.model_copy(
        update={
            "nexus_matrix": list(by_key.values()),
            "provenance": violation.provenance + [
                ProvenanceEntry(
                    timestamp=_now(),
                    actor="layers.build_nexus_layer",
                    operation="add_or_replace_nexus_entries",
                    layer=4,
                    note=f"Upserted {len(incoming)} nexus entr{'y' if len(incoming) == 1 else 'ies'}.",
                )
            ],
        }
    )


# ---------------------------------------------------------------------------
# Layer 5 — Authorities (stubs only; never auto-fills rol numbers)
# ---------------------------------------------------------------------------

def add_authority_stub(
    violation: Violation,
    authority_id: str,
    type_: str,
    supports: list[str],
    research_query: str,
    proposition_to_verify: str,
    verification_protocol: str | None = None,
    fabrication_risk_note: str | None = None,
) -> Violation:
    """Add an unverified authority stub.

    Deliberately accepts ONLY the fields safe to assert without external
    verification (the research query and proposition). It does NOT accept
    court / rol / decision_date arguments — those can only come in via
    `verify_authority`, which is the protocol that runs against a real
    primary source.
    """
    stub = Authority(
        authority_id=authority_id,
        type=type_,
        supports=supports,
        research_query=research_query,
        proposition_to_verify=proposition_to_verify,
        verified=False,
        verification_protocol=verification_protocol,
        fabrication_risk_note=fabrication_risk_note,
    )
    merged = _merge_by_id(violation.authorities, [stub], "authority_id")
    return violation.model_copy(
        update={
            "authorities": merged,
            "provenance": violation.provenance + [
                ProvenanceEntry(
                    timestamp=_now(),
                    actor="layers.add_authority_stub",
                    operation="add_authority_stub",
                    layer=5,
                    note=f"Stubbed authority {authority_id} (verified=False).",
                )
            ],
        }
    )
