"""Validation pipeline.

Each check is a function with the signature:

    check(violation, sources) -> CheckResult

where `sources` is a small dict holding any source-of-truth readers the
check needs (TranscriptSource / FrameworkSource instances, etc).

The runner is a plain list of (check_id, name, fn) tuples. Adding a check is
one line. Removing a check (because the underlying invariant moved into the
schema, say) is one line too.

Why functions, not classes? Because each becomes a clean MCP tool candidate
on its own: a check is a pure predicate over the bundle, returns structured
JSON, and is testable in isolation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from .models import CheckResult, CheckStatus, OpenQuestion, ValidationReport, Violation
from .sources import FrameworkSource, TranscriptSource
from .verifier import v11_enrichment_integrity

PIPELINE_VERSION = "1.0"

CheckFn = Callable[[Violation, dict], CheckResult]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _nullable_field_names(model) -> set[str]:
    """Field names a Pydantic model itself declares as optional.

    Read from the model rather than hardcoded, so a field's nullability can
    change in one place. Used by the cross-view checks: JSON spells "no value"
    as both `null` and `""`, and a contract projection uses whichever the
    upstream writer produced, so the comparison must not call that drift.
    """
    return {
        name for name, info in model.model_fields.items() if not info.is_required()
    }


def _cross_view_equal(bundle_value: object, contract_value: object, *, nullable: bool) -> bool:
    """Compare one field across views, tolerating the two spellings of "absent"."""
    if nullable and bundle_value in (None, "") and contract_value in (None, ""):
        return True
    return bundle_value == contract_value


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
    """Each quote must appear verbatim in the segment it claims to come from.

    The comparison is intentionally scoped to the *cited* segment rather than
    the whole transcript file. Substring-matching the raw artifact is unsound:
    it passes when a quote was copied from a neighbouring segment (or from the
    framework text), and it fails on quotes that are genuinely present but whose
    escaping differs between the raw artifact and the parsed segment text
    (``&amp;`` in HTML, ``\\u2014`` escapes in JSON). Verifying against the
    resolved segment is strictly stricter — a quote that matches the segment
    always matched the file — and it is what V01 already resolves for us.
    """
    transcripts: dict[str, TranscriptSource] = sources.get("transcripts", {})
    issues: list[str] = []
    checked = 0
    skipped = 0
    for seg in v.segments:
        quote = seg.verbatim_es.strip()
        if not quote:
            skipped += 1
            continue
        src_id, local_id = seg.segment_id.split(".", 1)
        ts = transcripts.get(src_id)
        resolved = ts.get_segment(local_id) if ts is not None else None
        if resolved is None:
            # Unresolvable ids are V01's finding; a quote cannot be checked here.
            skipped += 1
            continue
        checked += 1
        if quote not in (resolved.get("verbatim") or ""):
            issues.append(f"{seg.segment_id}: verbatim mismatch against {src_id!r}")
    status = "pass" if not issues else "fail"
    note = f"{checked} quote(s) checked against their cited segment"
    if skipped:
        note += f", {skipped} skipped (unresolved id or empty quote)"
    if issues:
        return _result(
            "V02", "verbatim_quote_match", status,
            f"{len(issues)} mismatch(es): {issues}. {note}.",
        )
    return _result("V02", "verbatim_quote_match", status, f"All {note}.")


def v03_article_text_hash(v: Violation, sources: dict) -> CheckResult:
    frameworks: dict[str, FrameworkSource] = sources.get("frameworks", {})
    notes: list[str] = []
    declared_notes: list[str] = []
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
            # Informational, never a warning. The `**Sha256:**` header records
            # the hash of the *upstream document* the article text was taken
            # from; it is not a claim about this cache file's own bytes, and it
            # cannot be: a file cannot contain its own SHA256. Comparing the two
            # therefore warned on every cache that declared the header while
            # staying silent on the ~20 that simply omit it, i.e. the warning
            # tracked whether the header was present, not whether anything was
            # wrong. Cache drift is caught by the `cache_file_sha256` branch
            # above, which really does compare a recorded manifest hash against
            # the file on disk.
            declared_notes.append(
                f"INFO: framework {cache.framework_code} declares source SHA "
                f"{declared[:8]}… (cache bytes: {actual[:8]}…)."
            )

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
        return _result(
            "V03", "article_text_hash", "warn", " | ".join(notes + declared_notes)
        )
    detail = "All article-text hashes and excerpts match the framework cache."
    if declared_notes:
        detail = f"{detail} {' '.join(declared_notes)}"
    return _result("V03", "article_text_hash", "pass", detail)


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


# Fields of a source participant record that legitimately count as a declared
# speaker label. The bundle's own `speaker` values are the aliases carried in
# `segment_labels` (e.g. `dgac_official`), so that field is what normally
# matches; the human-readable name/role/label fields are accepted too, because
# a bundle may quote the source's own diarization label verbatim.
_SPEAKER_LABEL_FIELDS = ("canonical_name", "role", "speaker_label")


def _declared_speaker_labels(ts: TranscriptSource) -> set[str]:
    """The speaker vocabulary a source itself declares.

    Returns an empty set when the source cannot describe its participants
    (old HTML corpora), which makes the caller skip rather than guess.
    """
    getter = getattr(ts, "participants", None)
    if not callable(getter):
        return set()
    labels: set[str] = set()

    def add(value: object) -> None:
        if isinstance(value, str) and value.strip():
            labels.add(value.strip().casefold())

    for participant in getter() or []:
        for field in _SPEAKER_LABEL_FIELDS:
            add(participant.get(field))
        # `segment_labels` lists further aliases for the same participant.
        # Accept a list of labels or a mapping whose keys are labels.
        segment_labels = participant.get("segment_labels") or ()
        for value in segment_labels if isinstance(segment_labels, (list, tuple)) else segment_labels.keys():
            add(value)
    return labels


def v12_speaker_attribution(v: Violation, sources: dict) -> CheckResult:
    """Every cited segment's `speaker` should be a label its own source declares.

    V01 only proves the segment id resolves, so a bundle can invent a speaker
    vocabulary that the source never declared and still resolve cleanly. This
    check compares the stored label against the participant record.

    Sources that cannot describe their participants (e.g. the rendered HTML
    corpora) are skipped, so the check is opt-in per source rather than a gate
    on the whole corpus. Severity is `warn`: a mismatched label is an
    attribution weakness to declare, not a reason to block a bundle.
    """
    transcripts: dict[str, TranscriptSource] = sources.get("transcripts", {})
    checked = 0
    unresolved: list[str] = []
    for seg in v.segments:
        src_id, _ = seg.segment_id.split(".", 1)
        ts = transcripts.get(src_id)
        if ts is None:
            continue  # V01 owns unresolved sources; don't double-report.
        labels = _declared_speaker_labels(ts)
        if not labels:
            continue  # Source has no participant record; nothing to compare.
        checked += 1
        if seg.speaker.strip().casefold() not in labels:
            unresolved.append(
                f"{seg.segment_id}: speaker {seg.speaker!r} is not declared by {src_id!r}"
            )
    status: CheckStatus = "warn" if unresolved else "pass"
    return _result(
        "V12", "speaker_attribution", status,
        f"{checked} cited segment(s) had a declarable source; "
        f"{len(unresolved)} with an undeclared speaker."
        + (f" {unresolved}" if unresolved else ""),
    )


def v13_evidence_nexus_coherence(v: Violation, sources: dict) -> CheckResult:
    """A nexus row's `fact_id` should be listed as evidence by its own element.

    `norm_id` + `element_id` is the join key, and `fact_id` is the segment the
    row claims to support that element with. Nothing else ties the two
    together: V06 only asks whether *some* nexus row covers a scored element,
    so a row can cite a segment the element never lists and still read as
    coverage. Severity is `warn` because the bundle is merely self-inconsistent
    here (the segment exists and resolves); the citation is what needs fixing.
    """
    evidence = {
        (grid.article_id, element.element_id): set(element.proof_evidence_segments)
        for grid in v.element_grids
        for element in grid.elements
    }
    orphans: list[str] = []
    for row in v.nexus_matrix:
        key = (row.norm_id, row.element_id)
        if key not in evidence:
            continue  # V06/V11 own unknown norms and elements.
        if row.fact_id not in evidence[key]:
            orphans.append(f"{row.element_id} <- {row.fact_id}")
    status: CheckStatus = "warn" if orphans else "pass"
    return _result(
        "V13", "evidence_nexus_coherence", status,
        f"{len(v.nexus_matrix)} nexus row(s) checked; "
        f"{len(orphans)} cite a segment their element does not list as evidence."
        + (f" {orphans}" if orphans else ""),
    )


def v14_dead_weight_articles(v: Violation, sources: dict) -> CheckResult:
    """An established article should contribute something to the derivation.

    Confidence is a weighted mean over the element grids, so an established
    article whose grid scores 0 is pure denominator: it dilutes every other
    article while adding nothing. That is usually a bundled citation that the
    evidence never supported, and the honest fix is to demote it to a
    candidate (or an open question) rather than carry it as established.

    The threshold is exactly 0.0, not "low": a `contested` or `weak` element
    is legitimately weak *and present*, and flagging those would be noise.
    Articles scoring <= 0.2 are reported in the details of a passing check so
    a reviewer still sees them.
    """
    zero: list[str] = []
    marginal: list[str] = []
    for grid in v.element_grids:
        if not grid.elements:
            continue
        score = grid.weighted_score()
        if score == 0.0:
            zero.append(f"{grid.article_id} (score 0.0 over {len(grid.elements)} element(s))")
        elif score <= 0.2:
            marginal.append(f"{grid.article_id} (score {score:.3f})")
    if zero:
        return _result(
            "V14", "dead_weight_articles", "warn",
            f"{len(zero)} established article(s) score 0 and only dilute the "
            f"weighted mean: {zero}. Demote to a candidate or record as an "
            "open question."
            + (f" Also marginally scored: {marginal}." if marginal else ""),
        )
    return _result(
        "V14", "dead_weight_articles", "pass",
        f"No established article scores 0 over {len(v.element_grids)} grid(s)."
        + (f" Marginally scored (<= 0.2): {marginal}." if marginal else ""),
    )


def v15_verbatim_hash_integrity(v: Violation, sources: dict) -> CheckResult:
    """`verbatim_sha256` must be the digest of the `verbatim_es` beside it.

    This is the one field in the schema that asserts its own content, and
    nothing else recomputes it: `_load_violation` short-circuits on
    `model_validate_json`, so `_normalize` (the only writer that re-derives
    quotes and hashes) runs only for bundles that fail to parse. A stored
    bundle therefore keeps whatever hash it arrived with. V02 does not cover
    this either - it substring-checks the quote against the resolved segment
    and never re-hashes. Severity is `fail`: the invariant is exact, the field
    is required (64 chars) and the whole corpus satisfies it.
    """
    from ._utils import sha256_text

    bad: list[str] = []
    for seg in v.segments:
        fresh = sha256_text(seg.verbatim_es)
        if fresh != seg.verbatim_sha256:
            bad.append(
                f"{seg.segment_id}: stored {seg.verbatim_sha256[:12]}... "
                f"!= sha256(verbatim_es) {fresh[:12]}..."
            )
    status: CheckStatus = "fail" if bad else "pass"
    return _result(
        "V15", "verbatim_hash_integrity", status,
        f"{len(v.segments)} verbatim hash(es) recomputed; {len(bad)} mismatch."
        + (f" {bad}" if bad else ""),
    )


def v16_authority_verification_coherence(v: Violation, sources: dict) -> CheckResult:
    """The two-state authority rule, as a property of the *aggregate* view.

    V11 guards one authority at a time (bibliographic fields must be empty while
    `verified=False`; `verified=True` needs a protocol provenance). This check
    guards the claims that refer to the whole set, which nothing recomputes:

    1. `confidence.authorities_verification_factor` is *derived* from the
       verified ratio and then *stored*, but V10 only compares
       `confidence.value`. A factor edited in place therefore survives V10:
       measured, a bundle with ratio 0/8 and `authorities_verification_factor
       = 0.89` (instead of 0.85) returns V10 `pass`, because V10 re-derives the
       factor from the authorities and never looks at the stored one. A stored
       derivation field that contradicts its own derivation is the same defect
       class as V10's value mismatch, so it is a `fail` here.
    2. An unverified authority may populate *only* `research_query` and
       `proposition_to_verify`. If both are blank the stub asserts nothing and
       is indistinguishable from a placeholder, so the pending state is not
       actionable. `warn`.
    3. `verification_provenance.source_sha256` is documented as a pin that
       "lets V11 detect cache drift later", but V11 never re-checks it. When
       the pinned source is a bundled framework whose current bytes differ, the
       stored citation no longer matches the corpus it was verified against.
       `warn`: the fix is to re-verify, not to discard the bundle.
    4. `verified=True` with a blank `verification_protocol`. This field is the
       human-readable counterpart of the machine-readable
       `verification_provenance.protocol` enum (the jurisprudence path writes
       e.g. `"Qdrant-record=…; primary_source_url=…"`), and *no* check reads it
       at all. They are deliberately NOT asserted equal — one is prose, the
       other an enum — so the only defect that can be stated from the schema is
       "verified but names no protocol anywhere a human reads". `warn`, not
       `fail`: the machine audit trail is still intact, so nothing is
       *contradicted*, the record is merely incomplete for a reviewer.

    Deliberately NOT asserted: `fabrication_risk_note` (20 of 28 corpus stubs
    omit it, so it is optional in practice — reporting it as a finding would
    invent a convention retroactively), the prose/enum protocol fields being
    *equal* (see finding 4), and any per-type vocabulary (protocols already own
    that). Schema-agnostic: reads only declared model fields, and the expected
    factor comes from `derive_confidence` rather than a second copy of the
    formula. Sources that cannot be resolved are skipped, never guessed.
    Severity mirrors V03/V08: `fail` only for a contradictory stored
    derivation, otherwise `warn`.
    """
    from .confidence import derive_confidence

    issues: list[str] = []
    warnings: list[str] = []

    # --- 1. The stored verification factor must equal its own derivation ---
    if v.confidence is not None:
        fresh = derive_confidence(v)
        stored = v.confidence.authorities_verification_factor
        if abs(fresh.authorities_verification_factor - stored) > 1e-9:
            n_verified = sum(1 for a in v.authorities if a.verified)
            issues.append(
                f"confidence.authorities_verification_factor={stored} "
                f"but {n_verified}/{len(v.authorities)} authorities are verified, "
                f"which derives {fresh.authorities_verification_factor} "
                "(V10 compares only confidence.value, so a factor edited in "
                "place is not caught there)"
            )

    frameworks: dict[str, FrameworkSource] = sources.get("frameworks", {})

    for a in v.authorities:
        prov = a.verification_provenance
        if not a.verified:
            # --- 2. a stub must say what would settle it ---
            if not a.research_query.strip() and not a.proposition_to_verify.strip():
                warnings.append(
                    f"{a.authority_id}: unverified and both research_query and "
                    "proposition_to_verify are blank, so the stub asserts nothing"
                )
            continue
        if prov is None:
            continue  # E_AUTH_VERIFIED_BY_LLM is V11's finding, not duplicated here.
        # --- 3. the pinned source must still hash the same ---
        pinned = prov.source_uri
        for fw in frameworks.values():
            uri_getter = getattr(fw, "cache_uri", None)
            if not callable(uri_getter):
                continue
            if uri_getter() != pinned:
                continue
            sha_getter = getattr(fw, "cache_sha256", None)
            if not callable(sha_getter):
                continue
            actual = sha_getter()
            if actual != prov.source_sha256:
                warnings.append(
                    f"{a.authority_id}: pinned source {pinned} has changed since "
                    f"verification (pinned {prov.source_sha256[:8]}…, now "
                    f"{actual[:8]}…); re-verify against the current bytes"
                )
            break
        # --- 4. a verified record must name its protocol in prose too ---
        if not (a.verification_protocol or "").strip():
            warnings.append(
                f"{a.authority_id}: verified=True but verification_protocol is "
                f"blank; the provenance records {prov.protocol!r} but no check "
                "reads that field, and a reviewer reading the authority sees no "
                "statement of how it was verified"
            )

    if issues:
        return _result("V16", "authority_verification_coherence", "fail",
                       " | ".join(issues + warnings))
    if warnings:
        return _result("V16", "authority_verification_coherence", "warn",
                       " | ".join(warnings))
    return _result(
        "V16", "authority_verification_coherence", "pass",
        f"{len(v.authorities)} authorit(ies) coherent with the stored verification "
        "factor; every unverified stub states what would settle it and every "
        "verified authority names its protocol.",
    )


def v17_cross_view_consistency(v: Violation, sources: dict) -> CheckResult:
    """The bundle and its `contract.json` projection must not disagree.

    The pipeline *reads* the contract (V08) but never rewrites it, so the two
    views are maintained separately and can drift silently. V08 compares
    `violation_id`/`title`/`severity`/`confidence` and the established-article
    set; it does not look at `open_questions` or `cross_references` at all,
    which is exactly how CL-030 carried two different wordings of the same
    question for three review rounds while every check stayed green.

    The comparison is driven by what each view *declares*: for every id present
    in both, only the fields the contract also carries are compared, and the
    values must match exactly. So a contract that legitimately omits a
    bundle-only field (e.g. `obtaining_method`) is not a defect, while a
    reworded question or a divergent reference list is.

    Nullability is read from the model (`Violation.model_fields`), not
    hardcoded: JSON has two spellings of "no value" (`null` and `""`) and the
    contract projection uses both, so an optional field spelled `""` in one
    view and omitted in the other is not drift. Required fields (`question`,
    `priority`, `ref`, `relation`) are compared byte-for-byte.

    Deliberately NOT asserted: `related_violations` and edge reciprocity. Both
    are corpus facts that defeat a per-bundle check - measured, 18 of 81
    bundles list a `related_violation` that is not among their own
    cross-references (so it is a narrower curated relation, not a projection),
    and 446 of 1081 cross-reference edges are one-directional. Reciprocity is a
    property of the graph, so it belongs to a corpus-level audit, not here.
    """
    contract = sources.get("contract")
    if contract is None:
        return _result(
            "V17", "cross_view_consistency", "warn",
            "No contract view supplied; cross-view consistency not checked.",
        )

    issues: list[str] = []

    # --- open_questions: same ids, matching declared fields ---
    oq_nullable = _nullable_field_names(OpenQuestion)
    bundle_oq = {q.id: q.model_dump() for q in v.open_questions}
    contract_oq = {
        q.get("id"): q
        for q in (contract.get("open_questions") or [])
        if isinstance(q, dict)
    }
    for oid in sorted(set(bundle_oq) - set(contract_oq)):
        issues.append(f"open_questions[{oid}] is in the bundle but not in the contract")
    for oid in sorted(set(contract_oq) - set(bundle_oq)):
        issues.append(f"open_questions[{oid}] is in the contract but not in the bundle")
    for oid in sorted(set(bundle_oq) & set(contract_oq)):
        for field, bundle_value in bundle_oq[oid].items():
            if field not in contract_oq[oid]:
                continue  # Contract declares a narrower projection on purpose.
            contract_value = contract_oq[oid][field]
            if not _cross_view_equal(
                bundle_value, contract_value, nullable=field in oq_nullable
            ):
                issues.append(
                    f"open_questions[{oid}].{field} differs: "
                    f"bundle={bundle_value!r} contract={contract_value!r}"
                )

    # --- cross_references: same targets, same relation ---
    bundle_refs = {x.ref: x.relation for x in v.cross_references}
    contract_refs = {
        x.get("ref"): x.get("relation")
        for x in (contract.get("cross_references") or [])
        if isinstance(x, dict)
    }
    for ref in sorted(set(bundle_refs) - set(contract_refs)):
        issues.append(f"cross_references[{ref}] is in the bundle but not in the contract")
    for ref in sorted(set(contract_refs) - set(bundle_refs)):
        issues.append(f"cross_references[{ref}] is in the contract but not in the bundle")
    for ref in sorted(set(bundle_refs) & set(contract_refs)):
        if bundle_refs[ref] != contract_refs[ref]:
            issues.append(
                f"cross_references[{ref}].relation differs: "
                f"bundle={bundle_refs[ref]!r} contract={contract_refs[ref]!r}"
            )

    if issues:
        return _result("V17", "cross_view_consistency", "fail", " | ".join(issues))

    related = contract.get("related_violations")
    compared = len(bundle_oq) + len(bundle_refs)
    note = (
        f"Bundle and contract agree on {len(bundle_oq)} open question(s) and "
        f"{len(bundle_refs)} cross-reference(s) ({compared} item(s) compared)."
    )
    if isinstance(related, list):
        note += (
            f" Contract-only related_violations: {len(related)} (not asserted "
            "against cross_references; reciprocity is a graph-level audit)."
        )
    return _result("V17", "cross_view_consistency", "pass", note)


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
    ("V12", "speaker_attribution",           v12_speaker_attribution),
    ("V13", "evidence_nexus_coherence",      v13_evidence_nexus_coherence),
    ("V14", "dead_weight_articles",          v14_dead_weight_articles),
    ("V15", "verbatim_hash_integrity",       v15_verbatim_hash_integrity),
    ("V16", "authority_verification_coherence", v16_authority_verification_coherence),
    ("V17", "cross_view_consistency",        v17_cross_view_consistency),
]


def run_pipeline(
    violation: Violation,
    transcripts: dict[str, TranscriptSource] | None = None,
    frameworks: dict[str, FrameworkSource] | None = None,
    contract: dict | None = None,
    known_violation_ids: set[str] | None = None,
    extra_checks: list[tuple[str, str, CheckFn]] | None = None,
) -> ValidationReport:
    """Run the full pipeline. `extra_checks` lets callers append further checks
    without monkey-patching anything."""
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
