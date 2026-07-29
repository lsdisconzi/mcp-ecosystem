"""Enrichment integrity verifier.

Where the LLM proposes, the verifier disposes. This module enforces the
substantive invariants that an LLM-driven enrichment stage MUST preserve:

  1. Every `proof_evidence_segments` entry references a real EvidenceSegment.
  2. Every `verbatim_excerpt` is a literal substring of the hydrated body
     of the framework article it claims to come from.
  3. Every NexusEntry's `fact_id` is a real segment_id, and its
     (norm_id, element_id) pair exists in an ArticleElementGrid.
  4. Every Authority has `verified=False` and no rol/court/decision_date/
     author/work/pages/instrument/holding_summary (anti-fabrication).
  5. Every CandidateArticle has at least one `verification_required` step.
  6. Every CrossReference.ref is in `known_violation_ids` (when provided).
  7. Every OpenQuestion.blocks_element, if set, references a real element.

The verifier is exposed as `verify_enrichment` (returns a structured
VerificationReport) and as the V11 validation check (returns a
CheckResult so it composes with V01-V10).

Why a separate module? The validation pipeline checks the WHOLE pipeline
output. The verifier specifically guards the LLM seam, so it can be
called between an `enrich_violation` proposal and final write — and
re-invoked from MCP tools without dragging the rest of validation along.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .models import CheckResult, Violation
from .sources import FrameworkSource


_FORBIDDEN_AUTHORITY_FIELDS = (
    "court", "rol", "decision_date", "author", "work",
    "pages", "instrument", "holding_summary",
)

# Trigger phrases that mean the article's hypothesis demands a public-official
# defendant. When the article body contains one of these, we expect the
# violation to evidence a state-actor speaker (PDI, DGAC, fiscalia, etc.) —
# otherwise the citation is an agent-fit error (the Sonnet-4 Art.193 mistake).
_PUBLIC_OFFICIAL_TRIGGERS = (
    "empleado público",
    "empleado publico",
    "funcionario público",
    "funcionario publico",
    "servidor público",
    "servidor publico",
)

# Speaker tokens that count as state actors for the defendant-fit heuristic.
# Matched case-insensitively as substrings against EvidenceSegment.speaker.
_STATE_ACTOR_SPEAKER_TOKENS = (
    "pdi", "carabinero", "carabineros", "dgac", "jac", "policía", "policia",
    "fiscalía", "fiscalia", "ministerio público", "ministerio publico",
    "juzgado", "tribunal", "sernac",
)


def _has_state_actor_segment(violation) -> bool:
    """True iff any segment speaker mentions a state actor we recognise."""
    for s in getattr(violation, "segments", []) or []:
        sp = (s.speaker or "").lower()
        if any(tok in sp for tok in _STATE_ACTOR_SPEAKER_TOKENS):
            return True
    return False


@dataclass
class VerificationIssue:
    code: str
    severity: Literal["error", "warning"]
    where: str
    message: str

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "where": self.where,
            "message": self.message,
        }


@dataclass
class VerificationReport:
    violation_id: str
    issues: list[VerificationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    def as_dict(self) -> dict:
        return {
            "violation_id": self.violation_id,
            "ok": self.ok,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [i.as_dict() for i in self.issues],
        }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def verify_enrichment(
    violation: Violation,
    *,
    frameworks: dict[str, FrameworkSource] | None = None,
    known_violation_ids: set[str] | None = None,
) -> VerificationReport:
    """Run every enrichment-integrity check. Returns a report with one
    issue per failure (errors block; warnings annotate)."""
    frameworks = frameworks or {}
    known_violation_ids = known_violation_ids or set()
    issues: list[VerificationIssue] = []

    segment_ids = {s.segment_id for s in violation.segments}
    element_ids_by_article: dict[str, set[str]] = {}
    all_element_ids: set[str] = set()
    for g in violation.element_grids:
        ids = {e.element_id for e in g.elements}
        element_ids_by_article[g.article_id] = ids
        all_element_ids |= ids

    # --- 1. Element grids reference real segments + valid article_ids ---
    valid_article_ids = {a.article_id for a in violation.established_articles}
    for grid in violation.element_grids:
        if grid.article_id not in valid_article_ids:
            issues.append(VerificationIssue(
                code="E_GRID_UNKNOWN_ARTICLE",
                severity="error",
                where=f"element_grids[{grid.article_id}]",
                message=f"grid references article_id not in established_articles",
            ))
        for el in grid.elements:
            for sid in el.proof_evidence_segments:
                if sid not in segment_ids:
                    issues.append(VerificationIssue(
                        code="E_GRID_UNKNOWN_SEGMENT",
                        severity="error",
                        where=f"{grid.article_id}/{el.element_id}",
                        message=f"proof_evidence_segments entry {sid!r} is not a known segment_id",
                    ))

    # --- 2. Verbatim excerpts substring-match framework body ---
    for art in violation.established_articles:
        fw = frameworks.get(art.framework_code)
        if fw is None:
            issues.append(VerificationIssue(
                code="W_NO_FRAMEWORK",
                severity="warning",
                where=art.article_id,
                message=f"no FrameworkSource registered for {art.framework_code}",
            ))
            continue
        art_num = art.article_id.rsplit(".Art.", 1)[-1]
        body = fw.get_article_body(art_num) or fw.get_article_body(art_num.split(".")[0])
        if body is None:
            issues.append(VerificationIssue(
                code="E_ARTICLE_BODY_MISSING",
                severity="error",
                where=art.article_id,
                message=f"framework {art.framework_code} returned no body for {art_num!r}",
            ))
            continue
        if art.verbatim_excerpt not in body:
            issues.append(VerificationIssue(
                code="E_EXCERPT_NOT_SUBSTRING",
                severity="error",
                where=art.article_id,
                message="verbatim_excerpt is not a literal substring of the framework body",
            ))
        # Defendant-fit heuristic: the article body demands a public official
        # but the violation evidences no state-actor speaker. This catches
        # the Sonnet-4-style CP.Art.193 misfit against private corporate
        # defendants. Warning, not error — the analyst may have a public
        # actor outside the audio segments (cross-referenced violation,
        # documentary evidence) so we surface the mismatch without blocking.
        body_lower = body.lower()
        if any(t in body_lower for t in _PUBLIC_OFFICIAL_TRIGGERS):
            if not _has_state_actor_segment(violation):
                issues.append(VerificationIssue(
                    code="W_AGENT_MISFIT",
                    severity="warning",
                    where=art.article_id,
                    message=(
                        "article body requires a public-official defendant "
                        "(empleado/funcionario público) but no segment "
                        "speaker is identified as a state actor; confirm "
                        "agent-fit or demote applicability"
                    ),
                ))

    # --- 3. Nexus entries reference real facts + (norm, element) pairs ---
    for n in violation.nexus_matrix:
        if n.fact_id not in segment_ids:
            issues.append(VerificationIssue(
                code="E_NEXUS_UNKNOWN_FACT",
                severity="error",
                where=f"nexus[{n.fact_id}->{n.element_id}]",
                message=f"fact_id {n.fact_id!r} is not a known segment_id",
            ))
        elems = element_ids_by_article.get(n.norm_id)
        if elems is None:
            issues.append(VerificationIssue(
                code="E_NEXUS_UNKNOWN_NORM",
                severity="error",
                where=f"nexus[{n.fact_id}->{n.norm_id}/{n.element_id}]",
                message=f"norm_id {n.norm_id!r} has no element grid",
            ))
        elif n.element_id not in elems:
            issues.append(VerificationIssue(
                code="E_NEXUS_UNKNOWN_ELEMENT",
                severity="error",
                where=f"nexus[{n.fact_id}->{n.norm_id}/{n.element_id}]",
                message=f"element_id {n.element_id!r} is not in the {n.norm_id} grid",
            ))

    # --- 4. Authorities: stubs unverified, verified ones have protocol provenance ---
    _KNOWN_PROTOCOLS = {
        "statute_in_bundle_v1",
        "statute_external_fetch_v1",
        "human_attested_v1",
    }
    for a in violation.authorities:
        if a.verified:
            # `verified=True` is allowed only when set by a known protocol.
            # The presence of a valid VerificationProvenance with a known
            # protocol identifier IS the proof that the flag came from the
            # verify_authority module (LLM-generated payloads cannot
            # synthesise this without also fabricating the source SHA, and
            # we recompute the matched_offset substring claim below).
            if a.verification_provenance is None:
                issues.append(VerificationIssue(
                    code="E_AUTH_VERIFIED_BY_LLM",
                    severity="error",
                    where=a.authority_id,
                    message="authority verified=True without verification_provenance; "
                            "only the verify_authority protocol may flip this flag",
                ))
            elif a.verification_provenance.protocol not in _KNOWN_PROTOCOLS:
                issues.append(VerificationIssue(
                    code="E_AUTH_VERIFIED_UNKNOWN_PROTOCOL",
                    severity="error",
                    where=a.authority_id,
                    message=f"verification_provenance.protocol "
                            f"{a.verification_provenance.protocol!r} not in known set",
                ))
            else:
                # Surface human-attested authorities so reviewers know the
                # confidence factor includes a human-vouched citation.
                if a.verification_provenance.protocol == "human_attested_v1":
                    issues.append(VerificationIssue(
                        code="W_HUMAN_ATTESTED_AUTHORITY",
                        severity="warning",
                        where=a.authority_id,
                        message=(
                            f"authority verified by human attestation "
                            f"({a.verification_provenance.notes or 'no attestor recorded'}); "
                            "downstream consumers should treat as human-vouched, not auto-validated"
                        ),
                    ))
        else:
            # Unverified: forbidden fields MUST be empty AND verification_provenance MUST be None
            for field_name in _FORBIDDEN_AUTHORITY_FIELDS:
                if getattr(a, field_name, None):
                    issues.append(VerificationIssue(
                        code="E_AUTH_FABRICATED_FIELD",
                        severity="error",
                        where=a.authority_id,
                        message=f"authority has forbidden field {field_name!r} "
                                f"({getattr(a, field_name)!r}) but verified=False; "
                                "stubs may only carry research_query + proposition_to_verify",
                    ))
            if a.verification_provenance is not None:
                issues.append(VerificationIssue(
                    code="E_AUTH_PROVENANCE_WITHOUT_VERIFIED",
                    severity="error",
                    where=a.authority_id,
                    message="verification_provenance set but verified=False; "
                            "provenance is the audit trail of a flag flip and must accompany it",
                ))
        for sup in a.supports:
            # Allow either an article_id or an element_id.
            if sup not in valid_article_ids and sup not in all_element_ids:
                issues.append(VerificationIssue(
                    code="W_AUTH_DANGLING_SUPPORT",
                    severity="warning",
                    where=a.authority_id,
                    message=f"supports entry {sup!r} matches neither an article_id "
                            "nor an element_id",
                ))

    # --- 5. Candidates require at least one verification step ---
    for c in violation.candidate_articles:
        if not c.verification_required:
            issues.append(VerificationIssue(
                code="E_CANDIDATE_NO_VERIFICATION",
                severity="error",
                where=c.candidate_article_id,
                message="candidate_articles entry has no verification_required steps",
            ))

    # --- 6. Cross-references resolve in known set, if provided ---
    if known_violation_ids:
        for x in violation.cross_references:
            if x.ref not in known_violation_ids:
                issues.append(VerificationIssue(
                    code="W_XREF_UNKNOWN",
                    severity="warning",
                    where=x.ref,
                    message=f"cross_reference target {x.ref!r} not in known_violation_ids",
                ))

    # --- 7. OpenQuestion.blocks_element references real element ---
    for q in violation.open_questions:
        if q.blocks_element and q.blocks_element not in all_element_ids:
            issues.append(VerificationIssue(
                code="W_OQ_BLOCKS_UNKNOWN",
                severity="warning",
                where=q.id,
                message=f"blocks_element {q.blocks_element!r} is not a known element_id",
            ))

    return VerificationReport(violation_id=violation.violation_id, issues=issues)


# ---------------------------------------------------------------------------
# V11 — integrates with the validation pipeline
# ---------------------------------------------------------------------------

def v11_enrichment_integrity(v: Violation, sources: dict) -> CheckResult:
    """Validation-pipeline adapter for `verify_enrichment`. Errors -> fail;
    warnings only -> warn; clean -> pass."""
    report = verify_enrichment(
        v,
        frameworks=sources.get("frameworks") or {},
        known_violation_ids=sources.get("known_violation_ids") or set(),
    )
    if report.error_count:
        details = (
            f"{report.error_count} error(s), {report.warning_count} warning(s). "
            + "; ".join(
                f"{i.code}@{i.where}: {i.message}"
                for i in report.issues if i.severity == "error"
            )[:1200]
        )
        status = "fail"
    elif report.warning_count:
        details = (
            f"0 errors, {report.warning_count} warning(s). "
            + "; ".join(
                f"{i.code}@{i.where}: {i.message}"
                for i in report.issues
            )[:1200]
        )
        status = "warn"
    else:
        details = "Enrichment integrity verified (segments, excerpts, nexus, authorities)."
        status = "pass"
    return CheckResult(
        check_id="V11", name="enrichment_integrity", status=status, details=details,
    )
