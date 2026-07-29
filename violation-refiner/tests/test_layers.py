from __future__ import annotations

import pytest

from violation_pack import (
    ArticleElementGrid,
    Element,
    Incident,
    NexusEntry,
    Violation,
    add_authority_stub,
    add_element_grid,
    build_evidence_layer,
    build_nexus_layer,
    build_norms_layer,
)


def _blank_violation() -> Violation:
    return Violation(
        violation_id="CL-005",
        title="test",
        severity="CRITICAL",
        incident=Incident(date="2024-07-05", location="SCL"),
    )


# ---------------------------------------------------------------------------
# Layer 1
# ---------------------------------------------------------------------------

def test_layer1_anchors_segment_with_real_offsets_and_hashes(transcript):
    v = _blank_violation()
    v = build_evidence_layer(v, transcript, [
        {"segment_id": "seg-55", "role_in_argument": "core", "translation_en": "no aggression"},
    ])
    assert len(v.segments) == 1
    s = v.segments[0]
    assert s.segment_id == "STG-7.seg-55"
    assert s.audio_offset_start == 445.0
    assert s.audio_offset_end == 450.1
    assert "agresion a una persona" in s.verbatim_es
    assert len(s.verbatim_sha256) == 64
    # The provenance trail should have been appended.
    assert any(p.layer == 1 for p in v.provenance)


def test_layer1_rejects_unknown_segment(transcript):
    v = _blank_violation()
    with pytest.raises(ValueError, match="refusing to fabricate"):
        build_evidence_layer(v, transcript, [
            {"segment_id": "seg-9999", "role_in_argument": "x", "translation_en": "y"},
        ])


def test_layer1_is_idempotent(transcript):
    v = _blank_violation()
    spec = {"segment_id": "seg-55", "role_in_argument": "core", "translation_en": "x"}
    v1 = build_evidence_layer(v, transcript, [spec])
    v2 = build_evidence_layer(v1, transcript, [spec])
    assert len(v2.segments) == 1, "Re-running with same input should not duplicate."


# ---------------------------------------------------------------------------
# Layer 2
# ---------------------------------------------------------------------------

def test_layer2_anchors_article_excerpt_to_cache(framework):
    v = _blank_violation()
    v = build_norms_layer(v, framework, [
        {
            "article_id": "CL.CHIPENCOD.T4.C3.Art.193",
            "article_name": "Falsedad por empleado público",
            "subsections_invoked": ["8"],
            "verbatim_excerpt": "8.° Ocultando en perjuicio del Estado o de un particular cualquier documento oficial.",
            "duty_bearer": "state",
            "norm_type": "penalty",
            "applicability": "direct",
            "applicability_rationale": "see test",
        }
    ])
    assert len(v.established_articles) == 1
    assert v.established_articles[0].framework_cache_status == "verified_in_bundle"
    # Framework cache registered too.
    assert len(v.framework_caches) == 1
    assert v.framework_caches[0].framework_code == "CHIPENCOD"


def test_layer2_rejects_paraphrase_masquerading_as_excerpt(framework):
    v = _blank_violation()
    with pytest.raises(ValueError, match="not a substring"):
        build_norms_layer(v, framework, [
            {
                "article_id": "CL.CHIPENCOD.T4.C3.Art.193",
                "article_name": "Falsedad",
                "subsections_invoked": ["8"],
                "verbatim_excerpt": "Public officials shall not conceal documents.",  # paraphrase!
                "duty_bearer": "state",
                "norm_type": "penalty",
                "applicability": "direct",
                "applicability_rationale": "test",
            }
        ])


def test_layer2_rejects_article_not_in_cache(framework):
    v = _blank_violation()
    with pytest.raises(ValueError, match="not found in framework"):
        build_norms_layer(v, framework, [
            {
                "article_id": "CL.CHIPENCOD.T4.C3.Art.497",
                "article_name": "Made up",
                "subsections_invoked": [],
                "verbatim_excerpt": "anything",
                "duty_bearer": "state",
                "norm_type": "penalty",
                "applicability": "direct",
                "applicability_rationale": "test",
            }
        ])


# ---------------------------------------------------------------------------
# Layer 3 + 4
# ---------------------------------------------------------------------------

def test_layer3_and_4_compose(transcript, framework):
    v = _blank_violation()
    v = build_evidence_layer(v, transcript, [
        {"segment_id": "seg-55", "role_in_argument": "core", "translation_en": "x"},
    ])
    grid = ArticleElementGrid(
        article_id="CL.CHIPENCOD.T4.C3.Art.193",
        article_short="Art 193",
        elements=[
            Element(
                element_id="CL.CHIPENCOD.Art.193.8.elem.modalidad_ocultacion",
                label="Modalidad",
                proof_status="strong",
                proof_evidence_segments=["STG-7.seg-55"],
                argument_es="x",
            ),
        ],
    )
    v = add_element_grid(v, grid)
    v = build_nexus_layer(v, [
        NexusEntry(
            fact_id="STG-7.seg-55",
            norm_id="CL.CHIPENCOD.T4.C3.Art.193",
            element_id="CL.CHIPENCOD.Art.193.8.elem.modalidad_ocultacion",
            nexus_type="direct_admission",
            strength="high",
            rationale_oneline="ok",
        ),
    ])
    assert len(v.element_grids) == 1
    assert len(v.nexus_matrix) == 1


# ---------------------------------------------------------------------------
# Layer 5
# ---------------------------------------------------------------------------

def test_layer5_stubs_are_unverified():
    v = _blank_violation()
    v = add_authority_stub(
        v, authority_id="A1", type_="jurisprudence",
        supports=["E1"], research_query="search", proposition_to_verify="p",
    )
    assert len(v.authorities) == 1
    assert v.authorities[0].verified is False
    assert v.authorities[0].court is None  # never auto-set
    assert v.authorities[0].rol is None
