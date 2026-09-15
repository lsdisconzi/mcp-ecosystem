"""Tests for the V01-V17 validation pipeline.

Focused on V02, whose contract is subtle enough to have shipped wrong: it used
to substring-match the *whole* transcript artifact, which cannot tell a quote
taken from the cited segment apart from one lifted from a neighbouring segment,
and which fails on quotes that are present but escaped differently in the file.

V12-V17 are covered below for the same reason: each one asserts a join or an
invariant that no other check owns, so each needs a case that proves it is not
vacuously green (an undeclared speaker, an unlisted evidence segment, a
dead-weight article, a stale digest, a factor edited in place, a reworded
question). V16's failing case is written *against* V10 passing the same input,
which pins the seam between them.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from violation_pack._utils import sha256_text
from violation_pack.confidence import attach_confidence
from violation_pack.models import (
    ArticleElementGrid,
    Authority,
    CrossReference,
    Element,
    EvidenceSegment,
    Incident,
    NexusEntry,
    OpenQuestion,
    VerificationProvenance,
    Violation,
)
from violation_pack.sources import ParsedSegment
from violation_pack.validation import (
    v02_verbatim_quote_match,
    v10_confidence_derivation,
    v11_enrichment_integrity,
    v12_speaker_attribution,
    v13_evidence_nexus_coherence,
    v14_dead_weight_articles,
    v15_verbatim_hash_integrity,
    v16_authority_verification_coherence,
    v17_cross_view_consistency,
)

_EM_DASH = "\u2014"


class _FakeTranscript:
    """Minimal TranscriptSource over an in-memory ``local_id -> text`` map."""

    def __init__(self, segments: dict[str, str], raw_text: str | None = None):
        self._segments = segments
        self._raw_text = raw_text

    def source_id(self) -> str:
        return "STG-7"

    def source_uri(self) -> str:
        return "Transcripts/timeline_aeropuerto_STG_7.html"

    def source_sha256(self) -> str:
        return "0" * 64

    def get_segment(self, segment_id: str) -> ParsedSegment | None:
        text = self._segments.get(segment_id)
        if text is None:
            return None
        return ParsedSegment(
            segment_id=segment_id,
            audio_offset_start=0.0,
            audio_offset_end=1.0,
            speaker="SPK",
            verbatim=text,
        )

    def all_segments(self) -> list[ParsedSegment]:
        return [self.get_segment(sid) for sid in self._segments]

    def raw_text(self) -> str:
        if self._raw_text is not None:
            return self._raw_text
        return "\n".join(self._segments.values())


class _FakeFramework:
    """Minimal FrameworkSource exposing only the two pin accessors V16 reads."""

    def __init__(self, *, uri: str, sha: str):
        self._uri = uri
        self._sha = sha

    def cache_uri(self) -> str:
        return self._uri

    def cache_sha256(self) -> str:
        return self._sha


def _segment(local_id: str, quote: str) -> EvidenceSegment:
    return EvidenceSegment(
        segment_id=f"STG-7.{local_id}",
        role_in_argument="test",
        audio_offset_start=0.0,
        audio_offset_end=1.0,
        speaker="SPK",
        verbatim_es=quote,
        verbatim_sha256="a" * 64,
        translation_en="",
        source_uri=f"Transcripts/timeline_aeropuerto_STG_7.html#{local_id}",
        source_sha256="b" * 64,
    )


def _violation(*segments: EvidenceSegment) -> Violation:
    return Violation(
        violation_id="CL-999",
        title="t",
        severity="LOW",
        incident=Incident(date="2024-01-01", location="Santiago"),
        segments=list(segments),
    )


def _run(v: Violation, transcripts: dict) -> tuple[str, str]:
    result = v02_verbatim_quote_match(v, {"transcripts": transcripts})
    return result.status, result.details


def test_passes_when_quote_is_in_the_cited_segment():
    ts = _FakeTranscript({"seg-10": "hola, buenos dias"})
    status, _ = _run(_violation(_segment("seg-10", "hola, buenos dias")), {"STG-7": ts})
    assert status == "pass"


def test_fails_when_quote_only_exists_in_another_segment():
    """The property ``raw_text()`` could not enforce.

    A quote copied from a neighbouring segment is present in the artifact but
    not in the segment it claims to come from. Scoping the comparison to the
    cited segment is what makes this a failure.
    """
    ts = _FakeTranscript(
        {"seg-10": "no recuerdo nada de eso", "seg-11": "yo cargue la maleta"},
        raw_text="no recuerdo nada de eso yo cargue la maleta",
    )
    v = _violation(_segment("seg-10", "yo cargue la maleta"))
    # Guard against the fixture going vacuous: the quote IS in the raw artifact,
    # so the old artifact-wide comparison would have passed this bundle.
    assert "yo cargue la maleta" in ts.raw_text()
    status, details = _run(v, {"STG-7": ts})
    assert status == "fail"
    assert "seg-10" in details


def test_is_escape_insensitive_but_artifact_bytes_are_not():
    """A JSON artifact stores ``\\u2014`` where the segment holds a real em dash."""
    quote = f"el acta {_EM_DASH} firmada"
    ts = _FakeTranscript(
        {"seg-20": quote},
        raw_text='"verbatim": "el acta \\u2014 firmada"',  # literal escape sequence
    )
    assert quote not in ts.raw_text()
    status, _ = _run(_violation(_segment("seg-20", quote)), {"STG-7": ts})
    assert status == "pass"


def test_unresolved_segment_ids_are_skipped_not_failed():
    """V01 owns unresolvable ids; V02 must not double-report them."""
    ts = _FakeTranscript({"seg-30": "texto"})
    v = _violation(_segment("seg-999", "texto"), _segment("seg-30", "texto"))
    status, details = _run(v, {"STG-7": ts})
    assert status == "pass"
    assert "1 quote(s) checked" in details
    assert "1 skipped" in details


def test_missing_transcript_registration_is_skipped():
    v = _violation(_segment("seg-40", "texto"))
    status, details = _run(v, {})
    assert status == "pass"
    assert "1 skipped" in details


@pytest.mark.parametrize("empty", ["", "   ", "\n\t "])
def test_empty_quotes_are_skipped_rather_than_passing_vacuously(empty):
    ts = _FakeTranscript({"seg-50": "algo"})
    status, details = _run(_violation(_segment("seg-50", empty)), {"STG-7": ts})
    assert status == "pass"
    assert "0 quote(s) checked" in details
    assert "1 skipped" in details


def test_reports_every_mismatch():
    ts = _FakeTranscript({"seg-60": "aaa", "seg-61": "bbb"})
    v = _violation(_segment("seg-60", "zzz"), _segment("seg-61", "yyy"))
    status, details = _run(v, {"STG-7": ts})
    assert status == "fail"
    assert "2 mismatch(es)" in details
    assert "seg-60" in details and "seg-61" in details


# ---------------------------------------------------------------------------
# V12 — speaker_attribution
# ---------------------------------------------------------------------------

class _FakeSpeakerTranscript(_FakeTranscript):
    """A fake source that declares its participants, like the JSON corpus."""

    def __init__(self, segments: dict[str, str], participants: list[dict], **kw):
        super().__init__(segments, **kw)
        self._participants = participants

    def participants(self) -> list[dict]:
        return self._participants


def _speaker_segment(local_id: str, speaker: str) -> EvidenceSegment:
    seg = _segment(local_id, "texto")
    seg.speaker = speaker
    return seg


def _v12(v: Violation, transcripts: dict):
    return v12_speaker_attribution(v, {"transcripts": transcripts})


def test_v12_passes_when_speaker_matches_a_declared_alias():
    """``segment_labels`` holds the aliases the bundle's ``speaker`` field uses."""
    ts = _FakeSpeakerTranscript(
        {"seg-10": "texto"},
        [{"canonical_name": "DGAC", "role": "DGAC Officials",
          "speaker_label": "DGAC", "segment_labels": ["dgac_official"]}],
    )
    v = _violation(_speaker_segment("seg-10", "dgac_official"))
    res = _v12(v, {"STG-7": ts})
    assert res.status == "pass"
    assert "1 cited segment(s) had a declarable source" in res.details
    assert "0 with an undeclared speaker" in res.details


def test_v12_warns_when_speaker_is_not_declared():
    """The corpus-wide case: a bundle labels a segment ``multi_party_audio``
    while the source's own participant record names nobody by that label."""
    ts = _FakeSpeakerTranscript(
        {"seg-11": "texto"},
        [{"canonical_name": "DGAC", "role": "DGAC Officials",
          "speaker_label": "DGAC", "segment_labels": ["dgac_official"]}],
    )
    v = _violation(_speaker_segment("seg-11", "multi_party_audio"))
    res = _v12(v, {"STG-7": ts})
    assert res.status == "warn"
    assert "multi_party_audio" in res.details


def test_v12_accepts_a_mapping_form_of_segment_labels():
    """The field is a list of aliases today, but a label->segments map is a
    plausible shape and this helper used to assume it."""
    ts = _FakeSpeakerTranscript(
        {"seg-12": "texto"},
        [{"segment_labels": {"dgac_official": ["seg-12"]}}],
    )
    v = _violation(_speaker_segment("seg-12", "dgac_official"))
    assert _v12(v, {"STG-7": ts}).status == "pass"


def test_v12_matches_the_human_readable_fields_case_insensitively():
    ts = _FakeSpeakerTranscript(
        {"seg-13": "texto"},
        [{"canonical_name": "DGAC", "role": "DGAC Officials"}],
    )
    v = _violation(_speaker_segment("seg-13", "dgac officials"))
    assert _v12(v, {"STG-7": ts}).status == "pass"


def test_v12_skips_sources_that_cannot_describe_participants():
    """Rendered-HTML corpora declare no participants; skipping keeps the check
    opt-in per source instead of failing every legacy bundle."""
    ts = _FakeTranscript({"seg-14": "texto"})  # no participants() at all
    v = _violation(_speaker_segment("seg-14", "anyone"))
    res = _v12(v, {"STG-7": ts})
    assert res.status == "pass"
    assert "0 cited segment(s) had a declarable source" in res.details


def test_v12_leaves_unresolved_sources_to_v01():
    """An unregistered source is V01's finding; re-reporting it here would
    count one defect twice. Note the id must name a *missing source*, not just
    a missing segment id within a registered one."""
    ts = _FakeSpeakerTranscript({}, [{"segment_labels": ["dgac_official"]}])
    seg = _speaker_segment("seg-1", "nobody")
    seg.segment_id = "STG-404.seg-1"
    res = _v12(_violation(seg), {"STG-7": ts})
    assert res.status == "pass"
    assert "0 cited segment(s)" in res.details


# ---------------------------------------------------------------------------
# V13 — evidence_nexus_coherence
# ---------------------------------------------------------------------------

_ART255 = "CL.CPCL.C1.Art.255"


def _grid(element_id: str, evidence: list[str], proof_status: str = "established") -> ArticleElementGrid:
    return ArticleElementGrid(
        article_id=_ART255,
        article_short="Art. 255",
        elements=[
            Element(
                element_id=element_id,
                label="label",
                proof_status=proof_status,
                proof_evidence_segments=list(evidence),
                argument_es="argument",
            )
        ],
    )


def _nexus(fact_id: str, element_id: str, norm_id: str = _ART255) -> NexusEntry:
    return NexusEntry(
        fact_id=fact_id,
        norm_id=norm_id,
        element_id=element_id,
        nexus_type="direct_admission",
        strength="high",
        rationale_oneline="rationale",
    )


def _gridded_violation(*, grids=(), nexus=()) -> Violation:
    return Violation(
        violation_id="CL-999",
        title="t",
        severity="LOW",
        incident=Incident(date="2024-01-01", location="Santiago"),
        element_grids=list(grids),
        nexus_matrix=list(nexus),
    )


def test_v13_passes_when_nexus_cites_listed_evidence():
    v = _gridded_violation(
        grids=[_grid("A.elem.x", ["STG-7.seg-1"])],
        nexus=[_nexus("STG-7.seg-1", "A.elem.x")],
    )
    res = v13_evidence_nexus_coherence(v, {})
    assert res.status == "pass"
    assert "1 nexus row(s) checked" in res.details


def test_v13_warns_when_element_does_not_list_the_cited_segment():
    """The row resolves and V06 sees coverage, so nothing else can catch this."""
    v = _gridded_violation(
        grids=[_grid("A.elem.x", ["STG-7.seg-1"])],
        nexus=[_nexus("STG-7.seg-9", "A.elem.x")],
    )
    res = v13_evidence_nexus_coherence(v, {})
    assert res.status == "warn"
    assert "A.elem.x <- STG-7.seg-9" in res.details


def test_v13_leaves_unknown_joins_to_v06_and_v11():
    """``norm_id`` + ``element_id`` is the join key, so a row whose element is
    unknown (or known under a different norm) is not this check's business."""
    v = _gridded_violation(
        grids=[_grid("A.elem.x", ["STG-7.seg-1"])],
        nexus=[
            _nexus("STG-7.seg-9", "B.elem.absent"),
            _nexus("STG-7.seg-9", "A.elem.x", norm_id="CL.OTHER.Art.1"),
        ],
    )
    res = v13_evidence_nexus_coherence(v, {})
    assert res.status == "pass"
    assert "0 cite a segment their element does not list" in res.details


# ---------------------------------------------------------------------------
# V14 — dead_weight_articles
# ---------------------------------------------------------------------------

def test_v14_warns_when_an_established_article_scores_zero():
    v = _gridded_violation(grids=[_grid("A.elem.x", [], proof_status="missing")])
    res = v14_dead_weight_articles(v, {})
    assert res.status == "warn"
    assert "score 0.0" in res.details
    assert "Demote to a candidate" in res.details


def test_v14_counts_an_unscored_grid_as_dead_weight():
    """``weighted_score`` is 0.0 when every element is ``not_developed``, not
    only when elements are weak: the article is pure denominator either way."""
    v = _gridded_violation(grids=[_grid("A.elem.x", [], proof_status="not_developed")])
    assert v.element_grids[0].weighted_score() == 0.0
    assert v14_dead_weight_articles(v, {}).status == "warn"


def test_v14_reports_marginal_articles_but_still_passes():
    """A ``weak`` element is legitimately weak *and present*: surfacing it as a
    warning would drown the signal the zero threshold carries."""
    v = _gridded_violation(grids=[_grid("A.elem.x", ["STG-7.seg-1"], proof_status="weak")])
    res = v14_dead_weight_articles(v, {})
    assert res.status == "pass"
    assert "Marginally scored" in res.details
    assert "0.200" in res.details


# ---------------------------------------------------------------------------
# V15 — verbatim_hash_integrity
# ---------------------------------------------------------------------------

def _hashed_segment(local_id: str, quote: str) -> EvidenceSegment:
    seg = _segment(local_id, quote)
    seg.verbatim_sha256 = sha256_text(quote)
    return seg


def test_v15_passes_when_the_digest_matches_the_quote():
    res = v15_verbatim_hash_integrity(_violation(_hashed_segment("seg-1", "hola")), {})
    assert res.status == "pass"
    assert "1 verbatim hash(es) recomputed; 0 mismatch" in res.details


def test_v15_fails_when_the_quote_is_edited_but_the_digest_is_stale():
    """The reachable failure: a hand-edit of ``verbatim_es`` leaves the stored
    digest behind, and neither ``_load_violation`` nor V02 ever re-hashes it."""
    seg = _hashed_segment("seg-1", "hola")
    seg.verbatim_es = "hola, editado"
    res = v15_verbatim_hash_integrity(_violation(seg), {})
    assert res.status == "fail"
    assert "seg-1" in res.details
    assert "1 mismatch" in res.details


# ---------------------------------------------------------------------------
# V16 — authority_verification_coherence
# ---------------------------------------------------------------------------

def _authority(
    authority_id: str = "AUTH-1",
    *,
    verified: bool = False,
    research_query: str = "Buscar sentencia sobre el punto.",
    proposition_to_verify: str = "La proposición a verificar.",
    provenance=None,
    protocol: str | None = None,
) -> Authority:
    return Authority(
        authority_id=authority_id,
        type="jurisprudence",
        supports=[_ART255],
        research_query=research_query,
        proposition_to_verify=proposition_to_verify,
        verified=verified,
        verification_protocol=protocol,
        verification_provenance=provenance,
    )


def _authored_violation(*authorities: Authority) -> Violation:
    """A violation with one scored grid, so the verification factor is real.

    With no grids ``derive_confidence`` short-circuits to a factor of 0.0,
    which would make the factor comparison vacuous.
    """
    v = _gridded_violation(grids=[_grid("A.elem.x", ["STG-7.seg-1"])])
    return v.model_copy(update={
        "authorities": list(authorities),
        "nexus_matrix": [_nexus("STG-7.seg-1", "A.elem.x")],
    })


def test_v16_passes_when_the_stored_factor_matches_its_derivation():
    v = attach_confidence(_authored_violation(_authority()))
    assert v.confidence.authorities_verification_factor == 0.85
    res = v16_authority_verification_coherence(v, {})
    assert res.status == "pass"
    assert "1 authorit(ies) coherent" in res.details


def test_v16_fails_when_the_stored_factor_is_edited_in_place():
    """The exact shape a review proposed: a factor of 0.89 at a verified ratio
    of 0/8. V10 re-derives the factor from the authorities and only compares
    ``confidence.value``, so it passes this input — which is why V16 exists."""
    v = attach_confidence(_authored_violation(_authority()))
    edited = v.model_copy(update={
        "confidence": v.confidence.model_copy(
            update={"authorities_verification_factor": 0.89}
        )
    })
    assert v10_confidence_derivation(edited, {}).status == "pass"  # the hole
    res = v16_authority_verification_coherence(edited, {})
    assert res.status == "fail"
    assert "0.89" in res.details and "0.85" in res.details


def test_v16_does_not_fail_when_the_value_moved_with_the_factor():
    """Editing *both* fields is caught by V10 (value), not by V16; V16 still
    reports the factor it can prove is wrong."""
    v = attach_confidence(_authored_violation(_authority()))
    edited = v.model_copy(update={
        "confidence": v.confidence.model_copy(
            update={"authorities_verification_factor": 0.89, "value": 0.70}
        )
    })
    assert v10_confidence_derivation(edited, {}).status == "fail"
    assert v16_authority_verification_coherence(edited, {}).status == "fail"


def test_v16_warns_when_an_unverified_stub_states_nothing():
    """An unverified authority may populate only these two fields, so blank
    both and the pending state is not actionable."""
    v = attach_confidence(_authored_violation(
        _authority(research_query="", proposition_to_verify="")
    ))
    res = v16_authority_verification_coherence(v, {})
    assert res.status == "warn"
    assert "asserts nothing" in res.details


def test_v16_warns_when_the_pinned_source_has_changed():
    """`source_sha256` is documented as a drift pin but nothing re-checked it."""
    prov = VerificationProvenance(
        protocol="statute_in_bundle_v1",
        source_uri="LawCache/CPR.md",
        source_sha256="c" * 64,
        verified_at=datetime.now(timezone.utc),
        matched_quote="la Constitución asegura a todas las personas",
        matched_offset=0,
    )
    v = attach_confidence(_authored_violation(_authority(verified=True, provenance=prov)))
    frameworks = {"CPR": _FakeFramework(uri="LawCache/CPR.md", sha="d" * 64)}
    res = v16_authority_verification_coherence(v, {"frameworks": frameworks})
    assert res.status == "warn"
    assert "has changed since verification" in res.details


def test_v16_skips_sources_it_cannot_resolve():
    prov = VerificationProvenance(
        protocol="statute_external_fetch_v1",
        source_uri="https://www.bcn.cl/leychile/navegar?idNorma=242302",
        source_sha256="c" * 64,
        verified_at=datetime.now(timezone.utc),
        matched_quote="quote",
        matched_offset=0,
    )
    v = attach_confidence(_authored_violation(
        _authority(verified=True, provenance=prov, protocol="statute_external_fetch_v1")
    ))
    res = v16_authority_verification_coherence(
        v, {"frameworks": {"CPR": _FakeFramework(uri="LawCache/CPR.md", sha="d" * 64)}}
    )
    assert res.status == "pass"  # An unfetched URL cannot be re-hashed here.


def test_v16_warns_when_a_verified_authority_names_no_protocol():
    """`verification_protocol` is the human-readable counterpart of the
    ``verification_provenance.protocol`` enum and *no* check read it at all.
    The two are deliberately not asserted equal (prose vs enum), so the only
    statable defect is a verified record that names no protocol a human reads.

    Measured on the real corpus: this fires on exactly the two authorities that
    ``verify_statute_in_bundle`` produced before it was fixed to populate the
    field, and on no others (they are the only ``verified=True`` authorities in
    the 81-bundle corpus). ``verify_statute_external_fetch`` and
    ``verify_human_attested`` were blank in the same way and were fixed with it,
    so all three protocols now name themselves; the authorities they produce are
    not in the corpus yet.
    """
    prov = VerificationProvenance(
        protocol="statute_in_bundle_v1",
        source_uri="LawCache/CPR.md",
        source_sha256="c" * 64,
        verified_at=datetime.now(timezone.utc),
        matched_quote="la Constitución asegura a todas las personas",
        matched_offset=0,
    )
    blank = attach_confidence(_authored_violation(
        _authority(verified=True, provenance=prov)
    ))
    res = v16_authority_verification_coherence(blank, {})
    assert res.status == "warn"
    assert "verification_protocol is blank" in res.details

    named = attach_confidence(_authored_violation(
        _authority(verified=True, provenance=prov, protocol="statute_in_bundle_v1; source=…")
    ))
    assert v16_authority_verification_coherence(named, {}).status == "pass"


def test_v16_leaves_verified_without_provenance_to_v11():
    """Division of labour: V11 owns the per-authority flag invariants, V16 owns
    the aggregate claims. A flag with no provenance is V11's finding."""
    v = attach_confidence(_authored_violation(_authority(verified=True)))
    assert v11_enrichment_integrity(v, {}).status == "fail"
    assert v16_authority_verification_coherence(v, {}).status == "pass"


# ---------------------------------------------------------------------------
# V17 — cross_view_consistency
# ---------------------------------------------------------------------------

def _cross_view_violation() -> Violation:
    return _violation().model_copy(update={
        "open_questions": [
            OpenQuestion(id="OQ-1", question="¿Pregunta?", priority="high"),
        ],
        "cross_references": [CrossReference(ref="CL-001", relation="related")],
    })


def _contract(**overrides) -> dict:
    contract = {
        "open_questions": [
            {"id": "OQ-1", "question": "¿Pregunta?", "blocks_element": "", "priority": "high"}
        ],
        "cross_references": [{"ref": "CL-001", "relation": "related"}],
    }
    contract.update(overrides)
    return contract


def test_v17_passes_when_the_views_agree():
    res = v17_cross_view_consistency(_cross_view_violation(), {"contract": _contract()})
    assert res.status == "pass"
    assert "2 item(s) compared" in res.details


def test_v17_tolerates_the_two_spellings_of_absent():
    """The contract writes ``""`` where the model yields ``None``; treating
    that as drift flagged 17 of 81 corpus bundles for a formatting choice."""
    res = v17_cross_view_consistency(_cross_view_violation(), {"contract": _contract()})
    assert res.status == "pass"


def test_v17_fails_when_a_required_field_is_reworded():
    contract = _contract()
    contract["open_questions"][0]["question"] = "Otra redacción."
    res = v17_cross_view_consistency(_cross_view_violation(), {"contract": contract})
    assert res.status == "fail"
    assert "OQ-1].question differs" in res.details


def test_v17_fails_when_a_reference_is_only_in_one_view():
    contract = _contract()
    contract["cross_references"].append({"ref": "CL-002", "relation": "related"})
    res = v17_cross_view_consistency(_cross_view_violation(), {"contract": contract})
    assert res.status == "fail"
    assert "CL-002" in res.details


def test_v17_flags_a_question_missing_from_the_contract():
    contract = _contract()
    contract["open_questions"] = []
    res = v17_cross_view_consistency(_cross_view_violation(), {"contract": contract})
    assert res.status == "fail"
    assert "not in the contract" in res.details


def test_v17_ignores_a_field_the_contract_does_not_declare():
    """`obtaining_method` is bundle-only in the corpus, so its absence from the
    contract must not be a finding."""
    v = _cross_view_violation().model_copy(update={
        "open_questions": [
            OpenQuestion(
                id="OQ-1",
                question="¿Pregunta?",
                priority="high",
                obtaining_method="Request the DGAC file.",
            )
        ]
    })
    res = v17_cross_view_consistency(v, {"contract": _contract()})
    assert res.status == "pass"


def test_v17_does_not_assert_related_violations_against_cross_references():
    """Measured corpus fact: 18 of 81 bundles list a `related_violation` that is
    not among their own cross-references, so the two are different relations."""
    contract = _contract(related_violations=["CL-002"])
    res = v17_cross_view_consistency(_cross_view_violation(), {"contract": contract})
    assert res.status == "pass"
    assert "related_violations: 1" in res.details


def test_v17_warns_when_no_contract_view_is_supplied():
    res = v17_cross_view_consistency(_cross_view_violation(), {})
    assert res.status == "warn"
    assert "not checked" in res.details
