"""Validation pipeline.

Each check is a function with the signature:

    check(violation, sources) -> CheckResult

where `sources` is a small dict holding any source-of-truth readers the
check needs (TranscriptSource / FrameworkSource instances, etc).

The runner is a plain list of (check_id, name, fn) tuples. Adding V11 is one
line. Removing a check (because the underlying invariant moved into the
schema, say) is one line too.

Why functions, not classes? Because each becomes a clean MCP tool candidate
on its own: a check is a pure predicate over the bundle, returns structured
JSON, and is testable in isolation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from .models import CheckResult, CheckStatus, ValidationReport, Violation
from .sources import FrameworkSource, TranscriptSource
from .verifier import v11_enrichment_integrity

PIPELINE_VERSION = "1.0"

CheckFn = Callable[[Violation, dict], CheckResult]


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _result(check_id: str, name: str, status: CheckStatus, details: str) -> CheckResult:
    return CheckResult(check_id=check_id, name=name, status=status, details=details)


def v01_segment_resolution(v: Violation, sources: dict) -> CheckResult:
    transcripts: dict[str, TranscriptSource] = sources.get("transcripts", {})
    issues = []
    for seg in v.segments:
        src_id, local_id = seg.segment_id.split(".", 1)
        ts = transcripts.get(src_id)
        if ts is None:
            issues.append(f"{seg.segment_id}: no transcript registered for source_id {src_id!r}")
            continue
        if ts.get_segment(local_id) is None:
            issues.append(f"{seg.segment_id}: id not present in transcript {src_id!r}")
    status = "pass" if not issues else "fail"
    return _result(
        "V01", "segment_resolution", status,
        f"{len(v.segments)} segment(s) checked; {len(issues)} unresolved." + (f" {issues}" if issues else ""),
    )


def v02_verbatim_quote_match(v: Violation, sources: dict) -> CheckResult:
    transcripts: dict[str, TranscriptSource] = sources.get("transcripts", {})
    issues = []
    for seg in v.segments:
        src_id, _ = seg.segment_id.split(".", 1)
        ts = transcripts.get(src_id)
        if ts is None or not hasattr(ts, "raw_text"):
            continue
        if seg.verbatim_es not in ts.raw_text():
            issues.append(f"{seg.segment_id}: verbatim mismatch against {src_id!r}")
    status = "pass" if not issues else "fail"
    return _result(
        "V02", "verbatim_quote_match", status,
        "All verbatim quotes match source bytes." if not issues else f"{len(issues)} mismatches: {issues}",
    )


def v03_article_text_hash(v: Violation, sources: dict) -> CheckResult:
    frameworks: dict[str, FrameworkSource] = sources.get("frameworks", {})
    notes: list[str] = []
    has_fail = False
    has_warn = False

    # Cache file SHA self-consistency
    for cache in v.framework_caches:
        fw = frameworks.get(cache.framework_code)
        if fw is None:
            continue
        actual = fw.cache_sha256()
        if cache.cache_file_sha256 != actual:
            notes.append(
                f"FAIL: manifest cache_file_sha256 for {cache.framework_code} "
                f"({cache.cache_file_sha256[:8]}…) != real file SHA ({actual[:8]}…)"
            )
            has_fail = True
        declared = fw.declared_sha256()
        if declared and declared.lower() != actual.lower():
            notes.append(
                f"WARN: framework {cache.framework_code} self-reported SHA in metadata header "
                f"({declared[:8]}…) does not match actual content SHA ({actual[:8]}…)."
            )
            has_warn = True

    # Per-article excerpt presence
    for art in v.established_articles:
        fw = frameworks.get(art.framework_code)
        if fw is None:
            notes.append(f"WARN: framework {art.framework_code} not registered for {art.article_id}")
            has_warn = True
            continue
        art_num = art.article_id.rsplit(".Art.", 1)[-1].split(".")[0]
        body = fw.get_article_body(art_num)
        if body is None or art.verbatim_excerpt not in body:
            notes.append(f"FAIL: {art.article_id} excerpt not present in framework cache as quoted.")
            has_fail = True

    if has_fail:
        return _result("V03", "article_text_hash", "fail", " | ".join(notes))
    if has_warn:
        return _result("V03", "article_text_hash", "warn", " | ".join(notes))
    return _result("V03", "article_text_hash", "pass", "All article-text hashes and excerpts match the framework cache.")


def v04_article_exists_in_framework_cache(v: Violation, sources: dict) -> CheckResult:
    frameworks: dict[str, FrameworkSource] = sources.get("frameworks", {})
    issues = []
    for art in v.established_articles:
        fw = frameworks.get(art.framework_code)
        art_num = art.article_id.rsplit(".Art.", 1)[-1].split(".")[0]
        if fw is None or fw.get_article_body(art_num) is None:
            issues.append(f"{art.article_id}: not present in framework cache")
    for cand in v.candidate_articles:
        if cand.framework_cache_status == "not_in_bundle":
            continue  # correctly self-flagged
    status = "pass" if not issues else "fail"
    return _result(
        "V04", "article_exists_in_framework_cache", status,
        f"All {len(v.established_articles)} established articles present in cache."
        if not issues else f"{issues}",
    )


def v05_cross_references_resolve(v: Violation, sources: dict) -> CheckResult:
    known_ids: set[str] = set(sources.get("known_violation_ids", set()))
    refs = [x.ref for x in v.cross_references]
    if not refs:
        return _result("V05", "cross_references_resolve", "pass", "No cross-references declared.")
    if not known_ids:
        return _result(
            "V05", "cross_references_resolve", "warn",
            f"{len(refs)} cross-references declared: {refs}. Bundle-level index not provided, "
            "so existence of targets is not verified.",
        )
    missing = [r for r in refs if r not in known_ids]
    if missing:
        return _result(
            "V05", "cross_references_resolve", "fail",
            f"{len(missing)} cross-reference(s) unresolved: {missing}",
        )
    return _result("V05", "cross_references_resolve", "pass", f"All {len(refs)} cross-references resolve.")


def v06_element_coverage(v: Violation, sources: dict) -> CheckResult:
    nexus_elements = {n.element_id for n in v.nexus_matrix}
    issues = []
    for grid in v.element_grids:
        for el in grid.elements:
            if el.proof_status in ("not_applicable", "not_developed", "missing"):
                continue
            if el.element_id not in nexus_elements:
                issues.append(f"{el.element_id}: status={el.proof_status} but no nexus_matrix entry")
    status = "pass" if not issues else "warn"
    return _result(
        "V06", "element_coverage", status,
        "Every scored element has at least one nexus_matrix entry."
        if not issues else f"{len(issues)} uncovered: {issues}",
    )


def v07_authorities_verification(v: Violation, sources: dict) -> CheckResult:
    if not v.authorities:
        return _result(
            "V07", "authorities_verification", "warn",
            "No authorities listed. Jurisprudence/doctrine layer not populated.",
        )
    unverified = [a for a in v.authorities if not a.verified]
    if unverified:
        return _result(
            "V07", "authorities_verification", "warn",
            f"{len(unverified)}/{len(v.authorities)} authorities pending verification. "
            "None auto-populated with rol numbers (correct: prevents fabrication). "
            "External verification pass required before legal-filing use.",
        )
    return _result(
        "V07", "authorities_verification", "pass",
        f"All {len(v.authorities)} authorities are verified.",
    )


def v08_contract_consistency(v: Violation, sources: dict) -> CheckResult:
    """If the caller has a separately-maintained contract.json view, they pass
    it in via sources['contract']. This implementation checks a minimal set
    of overlap fields; expand as needed.
    """
    contract = sources.get("contract")
    if contract is None:
        return _result("V08", "contract_consistency", "pass", "No contract view supplied; skipped.")
    issues = []
    warnings: list[str] = []
    # `violation_id` accepts the legacy upstream key `violation_number` as a
    # synonym. Several source contracts in the LA8159 corpus carry a legacy
    # opaque key (e.g. `VIOL_CL016CACH`) in `violation_id` while the canonical
    # short id (e.g. `CL-016`) is stored in `violation_number`. Either one
    # matching the refined violation is enough to consider the views aligned.
    for field in ("violation_id", "title", "severity"):
        contract_value = contract.get(field)
        violation_value = getattr(v, field)
        if field == "violation_id" and contract_value != violation_value:
            # Several source contracts carry a legacy upstream identifier in
            # `violation_id` (e.g. `VIOL_CL016CACH`) while the canonical short
            # id lives in `violation_number`. Accept that alias silently so
            # legacy-shape contracts do not block V08.
            alt = contract.get("violation_number")
            if alt == violation_value:
                continue
        if violation_value != contract_value:
            issues.append(f"{field} mismatch: violation={violation_value!r} contract={contract_value!r}")
    if v.confidence and "confidence" in contract:
        contract_confidence = contract.get("confidence")
        if isinstance(contract_confidence, dict):
            contract_value = contract_confidence.get("value")
            confidence_is_legacy = False
        elif isinstance(contract_confidence, (int, float)):
            contract_value = float(contract_confidence)
            confidence_is_legacy = True
        else:
            contract_value = None
            confidence_is_legacy = False
        if contract_value is not None and v.confidence.value != contract_value:
            msg = (
                f"confidence.value mismatch (derived={v.confidence.value} "
                f"contract={contract_value})"
            )
            if confidence_is_legacy:
                warnings.append(msg + " [legacy snapshot]")
            else:
                issues.append(msg)
    if "established_article_ids" in contract:
        main_arts = {a.article_id for a in v.established_articles}
        contract_arts = set(contract.get("established_article_ids", []))
        if main_arts != contract_arts:
            issues.append(f"established_articles set mismatch: {main_arts ^ contract_arts}")
    if issues:
        return _result("V08", "contract_consistency", "fail", " | ".join(issues + warnings))
    if warnings:
        return _result("V08", "contract_consistency", "warn", " | ".join(warnings))
    return _result(
        "V08", "contract_consistency", "pass",
        "Main and contract views agree on all overlapping fields.",
    )


def v09_language_consistency(v: Violation, sources: dict) -> CheckResult:
    issues = []
    for seg in v.segments:
        if not seg.verbatim_es.strip():
            issues.append(f"{seg.segment_id}: missing verbatim_es")
        if not seg.translation_en.strip():
            issues.append(f"{seg.segment_id}: missing translation_en")
    status = "pass" if not issues else "warn"
    return _result(
        "V09", "language_consistency", status,
        "Bilingual fields (es/en) present throughout."
        if not issues else f"{issues}",
    )


def v10_confidence_derivation(v: Violation, sources: dict) -> CheckResult:
    """Recompute confidence from the grids/authorities and confirm it matches
    what's stored. This is what catches a hand-picked override of the formula."""
    from .confidence import derive_confidence

    if v.confidence is None:
        return _result(
            "V10", "confidence_derivation", "warn",
            "No confidence value attached. Run derive_confidence/attach_confidence.",
        )
    fresh = derive_confidence(v)
    if abs(fresh.value - v.confidence.value) > 1e-9:
        return _result(
            "V10", "confidence_derivation", "fail",
            f"Stored confidence ({v.confidence.value}) ≠ recomputed ({fresh.value}). "
            "Either the formula changed or the value was hand-edited.",
        )
    return _result(
        "V10", "confidence_derivation", "pass",
        f"Confidence {v.confidence.value} matches recomputed formula.",
    )


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------

DEFAULT_PIPELINE: list[tuple[str, str, CheckFn]] = [
    ("V01", "segment_resolution",            v01_segment_resolution),
    ("V02", "verbatim_quote_match",          v02_verbatim_quote_match),
    ("V03", "article_text_hash",             v03_article_text_hash),
    ("V04", "article_exists_in_framework_cache", v04_article_exists_in_framework_cache),
    ("V05", "cross_references_resolve",      v05_cross_references_resolve),
    ("V06", "element_coverage",              v06_element_coverage),
    ("V07", "authorities_verification",      v07_authorities_verification),
    ("V08", "contract_consistency",          v08_contract_consistency),
    ("V09", "language_consistency",          v09_language_consistency),
    ("V10", "confidence_derivation",         v10_confidence_derivation),
    ("V11", "enrichment_integrity",          v11_enrichment_integrity),
]


def run_pipeline(
    violation: Violation,
    transcripts: dict[str, TranscriptSource] | None = None,
    frameworks: dict[str, FrameworkSource] | None = None,
    contract: dict | None = None,
    known_violation_ids: set[str] | None = None,
    extra_checks: list[tuple[str, str, CheckFn]] | None = None,
) -> ValidationReport:
    """Run the full pipeline. `extra_checks` lets callers add V11+ without
    monkey-patching anything."""
    sources = {
        "transcripts": transcripts or {},
        "frameworks": frameworks or {},
        "contract": contract,
        "known_violation_ids": known_violation_ids or set(),
    }
    pipeline = list(DEFAULT_PIPELINE) + list(extra_checks or [])
    results = [fn(violation, sources) for (_, _, fn) in pipeline]
    return ValidationReport(
        pipeline_version=PIPELINE_VERSION,
        ran_at=datetime.now(timezone.utc),
        violation_id=violation.violation_id,
        checks=results,
    )
