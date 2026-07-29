"""Pydantic models for the five enrichment layers.

Design notes
------------
* Every entity has a stable ID. This is the seam that makes future Neo4j
  ingestion mechanical: each model -> a node, each ID reference -> an edge.
* All bilingual prose lives in dedicated `_es` / `_en` fields. The validator
  V09 enforces this so the language sprawl I saw in the source bundle
  (PT README + ES JSON + EN translations buried in prose) can't recur.
* `_provenance` is structured, not narrative. Each refinement appends a
  ProvenanceEntry. That's the audit trail that makes the chronological /
  incremental story tractable later.
* No model takes a free-form `dict[str, Any]` payload. Schema drift gets
  caught at parse time, not at validation time.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

class ProvenanceEntry(BaseModel):
    """One step in the refinement history of a violation file.

    Append-only. The full list is the chronology — useful both for humans
    reading the file and for the future graph store, which can replay the
    history of any violation node.
    """
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    actor: str = Field(..., description="Who ran this refinement: 'automated_pipeline_v1', 'legal_audit_human', etc.")
    operation: str = Field(..., description="What was done: 'rebuild_evidence_layer', 'add_authority', 'reconcile_confidence'.")
    layer: int | None = Field(None, ge=1, le=5, description="Which enrichment layer was affected, if applicable.")
    note: str = Field(..., description="Short prose explanation; the actor's diff in words.")


# ---------------------------------------------------------------------------
# Layer 1 — Evidence anchoring
# ---------------------------------------------------------------------------

class EvidenceSegment(BaseModel):
    """A verbatim utterance from a source transcript, anchored to its origin."""
    model_config = ConfigDict(extra="forbid")
    segment_id: str = Field(..., description="Globally unique: <source_id>.<local_seg_id>, e.g. 'STG-7.seg-55'.")
    role_in_argument: str = Field(..., description="One-word/phrase tag for what this segment contributes to the case theory.")
    audio_offset_start: float
    audio_offset_end: float
    speaker: str
    verbatim_es: str = Field(..., description="Exact bytes from the source transcript. Idiosyncratic spelling preserved.")
    verbatim_sha256: str = Field(..., min_length=64, max_length=64)
    translation_en: str
    transcription_notes: str | None = None
    source_uri: str = Field(..., description="Bundle-relative path with #fragment, e.g. 'Transcripts/timeline_X.html#seg-55'.")
    source_sha256: str = Field(..., min_length=64, max_length=64)
    audio_uri: str | None = Field(
        None,
        description="Optional path/URI of the underlying audio file (e.g. 'audio/aeropuerto_STG_1.m4a'). When set, the audio_offset_* fields refer to seconds within this file.",
    )


# ---------------------------------------------------------------------------
# Layer 2 — Norm anchoring
# ---------------------------------------------------------------------------

class FrameworkCache(BaseModel):
    """A snapshot of a legal framework (penal code, constitution, statute)."""
    model_config = ConfigDict(extra="forbid")
    framework_code: str = Field(..., description="Short code: 'CHIPENCOD', 'LPDC', 'CONST', etc.")
    framework_name: str
    cache_file: str = Field(..., description="Bundle-relative path.")
    cache_file_sha256: str = Field(..., min_length=64, max_length=64)
    cache_self_reported_sha256: str | None = Field(
        None,
        description="SHA the cache file declares about itself in its header, if any. V03 checks this matches the actual.",
    )
    cache_source_url: str | None = None
    cache_fetched_at: datetime | None = None
    articles_cached: list[str] = Field(default_factory=list)


class CachedArticle(BaseModel):
    """An article (or numbered subsection) cited as legal basis, anchored to a framework cache."""
    model_config = ConfigDict(extra="forbid")
    article_id: str = Field(..., description="ELI-style: 'CL.CHIPENCOD.T4.C3.Art.193'.")
    article_name: str
    subsections_invoked: list[str] = Field(default_factory=list)
    verbatim_excerpt: str = Field(..., description="Exact substring quoted from the framework cache. V03 hashes this.")
    verbatim_excerpt_sha256: str = Field(..., min_length=64, max_length=64)
    framework_code: str = Field(..., description="Refers to FrameworkCache.framework_code.")
    framework_cache_status: Literal["verified_in_bundle", "not_in_bundle", "pending_fetch"]
    duty_bearer: str
    norm_type: Literal["prohibition", "penalty", "right", "liability", "definition", "exemption"]
    applicability: Literal["direct", "indirect_predicate", "supporting"]
    applicability_rationale: str


class CandidateArticle(BaseModel):
    """An article a theory could plausibly rest on but that hasn't been verified yet.

    The point of this class is to keep speculation OUT of `established_articles`
    while still recording the theory for future verification. The original
    CL-005 bundle's serial misciting (Art. 497 fabricated -> Art. 269_ter also
    misapplied) is exactly what this separation prevents: candidates can be
    wrong without contaminating the established legal basis.
    """
    model_config = ConfigDict(extra="forbid")
    candidate_article_id: str
    candidate_name: str
    framework_cache_status: Literal["not_in_bundle", "pending_fetch"]
    verification_required: list[str] = Field(..., description="Concrete steps to flip this to established.")
    preliminary_view: str | None = None
    history_note: str | None = Field(None, description="Where this theory came from, especially if it replaces a prior wrong citation.")


# ---------------------------------------------------------------------------
# Layer 3 — Element grid
# ---------------------------------------------------------------------------

ProofStatus = Literal["established", "strong", "contested", "weak", "missing", "not_applicable", "not_developed"]

PROOF_WEIGHTS: dict[str, float] = {
    "established": 1.0,
    "strong": 0.8,
    "contested": 0.5,
    "weak": 0.2,
    "missing": 0.0,
    "not_applicable": 1.0,  # treated as 'fully satisfied' for scoring (e.g. element not required)
    "not_developed": 0.0,   # not scored against this violation
}


class Element(BaseModel):
    """One doctrinal element of an article (mens rea, actus reus, etc.)."""
    model_config = ConfigDict(extra="forbid")
    element_id: str = Field(..., description="e.g. 'CL.CHIPENCOD.Art.193.8.elem.modalidad_ocultacion'.")
    label: str
    doctrinal_basis: str | None = None
    proof_status: ProofStatus
    proof_evidence_segments: list[str] = Field(default_factory=list, description="EvidenceSegment.segment_id values.")
    argument_es: str
    weaknesses: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list, description="OpenQuestion.id values.")


class ArticleElementGrid(BaseModel):
    """The full element grid for one article."""
    model_config = ConfigDict(extra="forbid")
    article_id: str
    article_short: str
    elements: list[Element]

    def weighted_score(self) -> float:
        """Arithmetic mean of element proof_status weights, ignoring not_developed."""
        scored = [e for e in self.elements if e.proof_status != "not_developed"]
        if not scored:
            return 0.0
        return sum(PROOF_WEIGHTS[e.proof_status] for e in scored) / len(scored)


# ---------------------------------------------------------------------------
# Layer 4 — Nexus matrix
# ---------------------------------------------------------------------------

NexusStrength = Literal["high", "medium", "low"]


class NexusEntry(BaseModel):
    """A typed link from a fact (segment) to a doctrinal element."""
    model_config = ConfigDict(extra="forbid")
    fact_id: str = Field(..., description="EvidenceSegment.segment_id.")
    norm_id: str = Field(..., description="Article ID this nexus belongs to.")
    element_id: str = Field(..., description="Element.element_id.")
    nexus_type: str = Field(..., description="Free-form category: 'direct_admission', 'corroborating_admission', etc.")
    strength: NexusStrength
    rationale_oneline: str


# ---------------------------------------------------------------------------
# Layer 5 — Authorities (jurisprudence / doctrine / comparative)
# ---------------------------------------------------------------------------

class VerificationProvenance(BaseModel):
    """Structured record of how an Authority's `verified` flag was flipped.

    This field is the safeguard between protocol-set evidence and LLM-set
    fabrication. It is populated EXCLUSIVELY by `verify_authority` (see
    `violation_pack/jurisprudence.py`); the LLM cannot write it because the
    enrichment seam strips `verification_provenance` from any LLM proposal.

    `protocol` must be one of the known protocol identifiers so V11 can
    re-validate the verification on read.
    """
    model_config = ConfigDict(extra="forbid")
    protocol: Literal[
        "statute_in_bundle_v1",
        "statute_external_fetch_v1",
        "human_attested_v1",
    ]
    source_uri: str = Field(..., description="Where the verification text came from (file path or URL).")
    source_sha256: str = Field(..., description="SHA256 of the source content at verification time (64 hex).")
    verified_at: datetime
    matched_quote: str = Field(..., description="Verbatim text from source supporting the proposition.")
    matched_offset: int = Field(..., description="Byte offset of the matched quote within source content.", ge=0)
    notes: str | None = None


class Authority(BaseModel):
    """A jurisprudence, doctrine, or comparative-law citation.

    `verified` is the load-bearing flag. Authorities are only allowed to assert
    a concrete rol/sala/fecha/holding when `verified=True`. While `verified=False`,
    only the research_query and proposition_to_verify are populated. This is the
    safeguard against auto-fabricated citations, which was the failure mode in
    the original CL-005 (the 'Art. 497 as denegación de auxilio' invention).

    When `verified=True`, `verification_provenance` MUST be populated — that is
    the audit trail proving the flag was flipped by a real protocol against a
    real source, not by an LLM. V11 enforces this invariant.
    """
    model_config = ConfigDict(extra="forbid")
    authority_id: str = Field(..., description="Stable internal ID for cross-referencing.")
    type: Literal["jurisprudence", "doctrine", "comparative", "statute"]
    supports: list[str] = Field(..., description="Element IDs this authority bolsters.")
    research_query: str = Field(..., description="What to look up. Required even when unverified.")
    proposition_to_verify: str

    # Populated only when verified=True; never auto-filled.
    court: str | None = None
    rol: str | None = None
    decision_date: datetime | None = None
    author: str | None = None
    work: str | None = None
    pages: str | None = None
    instrument: str | None = None
    holding_summary: str | None = None

    verified: bool = False
    verification_protocol: str | None = None
    verification_provenance: VerificationProvenance | None = None
    fabrication_risk_note: str | None = None


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

class ConfidenceDerivation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float = Field(..., ge=0.0, le=1.0)
    components: dict[str, float] = Field(default_factory=dict)
    authorities_verification_factor: float = Field(..., ge=0.0, le=1.0)
    derivation_formula: str
    derived_at: datetime
    history: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

CheckStatus = Literal["pass", "warn", "fail"]


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check_id: str
    name: str
    status: CheckStatus
    details: str


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pipeline_version: str
    ran_at: datetime
    violation_id: str
    checks: list[CheckResult]

    @property
    def summary(self) -> dict[str, int]:
        return {
            "total": len(self.checks),
            "pass": sum(1 for c in self.checks if c.status == "pass"),
            "warn": sum(1 for c in self.checks if c.status == "warn"),
            "fail": sum(1 for c in self.checks if c.status == "fail"),
        }


# ---------------------------------------------------------------------------
# Open questions
# ---------------------------------------------------------------------------

class OpenQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    question: str
    blocks_element: str | None = None
    priority: Literal["low", "medium", "high", "critical"]
    obtaining_method: str | None = None


# ---------------------------------------------------------------------------
# Cross-references
# ---------------------------------------------------------------------------

class CrossReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str = Field(..., description="Sibling violation_id, e.g. 'CL-001'.")
    relation: str = Field(..., description="Why these are linked. Becomes a typed edge in the future graph.")


# ---------------------------------------------------------------------------
# Top-level container
# ---------------------------------------------------------------------------

class Incident(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str  # ISO date string; full datetime if known
    location: str
    flight: str | None = None
    operator: str | None = None
    clock_time_estimate: str | None = None
    clock_time_confidence: Literal["verified", "estimated_from_audio_offset", "unknown"] = "unknown"


class Violation(BaseModel):
    """The top-level container — what gets serialized to <violation_id>.json."""
    model_config = ConfigDict(extra="forbid")

    violation_id: str
    title: str
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    schema_version: str = "3.0"

    incident: Incident

    # Layer 1
    segments: list[EvidenceSegment] = Field(default_factory=list)

    # Layer 2
    framework_caches: list[FrameworkCache] = Field(default_factory=list)
    established_articles: list[CachedArticle] = Field(default_factory=list)
    candidate_articles: list[CandidateArticle] = Field(default_factory=list)

    # Layer 3
    element_grids: list[ArticleElementGrid] = Field(default_factory=list)

    # Layer 4
    nexus_matrix: list[NexusEntry] = Field(default_factory=list)

    # Layer 5
    authorities: list[Authority] = Field(default_factory=list)

    # Derived
    confidence: ConfidenceDerivation | None = None

    # Auxiliary
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    cross_references: list[CrossReference] = Field(default_factory=list)

    # History
    provenance: list[ProvenanceEntry] = Field(default_factory=list)
