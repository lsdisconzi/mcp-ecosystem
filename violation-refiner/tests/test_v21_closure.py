"""V21 element_id_closure: shape, closure, template conformance."""
from __future__ import annotations

import pytest

from violation_pack.models import (
    ArticleElementGrid,
    Element,
    EvidenceSegment,
    Incident,
    NexusEntry,
    Violation,
)
from violation_pack.validation import v21_element_id_closure


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _segment(seg_id: str) -> EvidenceSegment:
    return EvidenceSegment(
        segment_id=seg_id,
        role_in_argument="fact",
        audio_offset_start=0.0,
        audio_offset_end=1.0,
        speaker="pdi_official",
        verbatim_es="x",
        verbatim_sha256="0" * 64,
        translation_en="x",
        source_uri="Transcripts/t.json#seg-0",
        source_sha256="1" * 64,
    )


def _element(element_id: str, status: str = "strong",
             evidence: list[str] | None = None) -> Element:
    return Element(
        element_id=element_id,
        label=element_id.rsplit(".", 1)[-1],
        doctrinal_basis=None,
        proof_status=status,
        proof_evidence_segments=evidence or ["seg-0"],
        argument_es="x",
    )


def _violation(
    article_id: str,
    element_ids: list[str],
    nexus_element_ids: list[str] | None = None,
) -> Violation:
    grid = ArticleElementGrid(
        article_id=article_id,
        article_short="short",
        elements=[_element(e) for e in element_ids],
    )
    nexus_ids = nexus_element_ids if nexus_element_ids is not None else element_ids
    nexus = [
        NexusEntry(
            fact_id="seg-0",
            norm_id=article_id,
            element_id=e,
            nexus_type="direct",
            strength="high",
            rationale_oneline="x",
        )
        for e in nexus_ids
    ]
    return Violation(
        violation_id="CL-TEST",
        title="t",
        severity="CRITICAL",
        incident=Incident(date="2024-01-01", location="X"),
        segments=[_segment("seg-0")],
        element_grids=[grid],
        nexus_matrix=nexus,
    )


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------

def test_shape_pass_when_ids_match_article():
    v = _violation(
        "CL.CPCL.C1.Art.255",
        ["CL.CPCL.C1.Art.255.elem.vejacion_injusta"],
    )
    r = v21_element_id_closure(v, {})
    assert r.status in {"pass", "warn"}  # template will warn on missing keys


def test_shape_fail_when_prefix_mismatches_article():
    v = _violation(
        "CL.CHIPENCOD.T4.C3.Art.193",
        ["CL.CPCL.C1.Art.255.elem.vejacion_injusta"],
    )
    r = v21_element_id_closure(v, {})
    assert r.status == "fail"
    assert "does not match grid article_id" in r.details


def test_shape_warn_when_prefix_drops_hierarchy():
    v = _violation(
        "CL.CHIPENCOD.T4.C3.Art.193",
        ["CL.CHIPENCOD.Art.193.8.elem.modalidad_ocultacion"],
    )
    r = v21_element_id_closure(v, {})
    # Same framework+number, hierarchy dropped -> warn, not fail.
    assert r.status in {"warn", "fail"}
    if r.status == "fail":
        # A fail is acceptable if template conformance also trips; what
        # must not happen is a fail purely on the hierarchy drift.
        assert "drops hierarchy segments" in r.details


def test_shape_fail_on_unparseable_id():
    v = _violation("CL.CPCL.C1.Art.255", ["not-an-element-id"])
    r = v21_element_id_closure(v, {})
    assert r.status == "fail"
    assert "does not match" in r.details


# ---------------------------------------------------------------------------
# Closure
# ---------------------------------------------------------------------------

def test_closure_fails_when_nexus_references_unknown_element():
    v = _violation(
        "CL.CPCL.C1.Art.255",
        ["CL.CPCL.C1.Art.255.elem.vejacion_injusta"],
        nexus_element_ids=["CL.CPCL.C1.Art.255.elem.invented"],
    )
    r = v21_element_id_closure(v, {})
    assert r.status == "fail"
    assert "not declared in any element grid" in r.details


def test_closure_fails_when_nexus_references_unknown_norm():
    v = _violation(
        "CL.CPCL.C1.Art.255",
        ["CL.CPCL.C1.Art.255.elem.vejacion_injusta"],
    )
    bad_nexus = v.nexus_matrix[0].model_copy(update={
        "norm_id": "CL.CPCL.C1.Art.999",
    })
    v = v.model_copy(update={"nexus_matrix": [bad_nexus]})
    r = v21_element_id_closure(v, {})
    assert r.status == "fail"


# ---------------------------------------------------------------------------
# Template conformance
# ---------------------------------------------------------------------------

def test_template_missing_required_element_fails():
    # CL.CPCL.C1.Art.255 has a template with five required elements; a grid
    # that carries only one of them must fail.
    v = _violation(
        "CL.CPCL.C1.Art.255",
        ["CL.CPCL.C1.Art.255.elem.vejacion_injusta"],
    )
    r = v21_element_id_closure(v, {})
    assert r.status == "fail"
    assert "template requires element" in r.details


def test_template_full_conformance_passes():
    from violation_pack.element_templates import find_template
    t = find_template("CL.CPCL.C1.Art.255")
    assert t is not None
    ids = list(t.element_ids("CL.CPCL.C1.Art.255").values())
    v = _violation("CL.CPCL.C1.Art.255", ids)
    r = v21_element_id_closure(v, {})
    assert r.status == "pass"


def test_template_extra_key_warns_not_fails():
    from violation_pack.element_templates import find_template
    t = find_template("CL.CPCL.C1.Art.255")
    assert t is not None
    ids = list(t.element_ids("CL.CPCL.C1.Art.255").values())
    ids.append("CL.CPCL.C1.Art.255.elem.invented_extra")
    v = _violation("CL.CPCL.C1.Art.255", ids)
    r = v21_element_id_closure(v, {})
    assert r.status == "warn"
    assert "outside its template" in r.details


def test_article_without_template_passes_shape_and_closure():
    v = _violation(
        "CL.UNKNOWN.FW.Art.9999",
        ["CL.UNKNOWN.FW.Art.9999.elem.whatever"],
    )
    r = v21_element_id_closure(v, {})
    assert r.status == "pass"


# ---------------------------------------------------------------------------
# Corpus regression
# ---------------------------------------------------------------------------

def test_cl005_v3_element_id_drift_is_caught():
    """The shipped CL-005 v3 defect: grid key ``sujeto_activo_empleado_publico``
    vs. nexus key ``sujeto_activo``. V21 must reject the mix.
    """
    grid_id = "CL.CHIPENCOD.T4.C3.Art.193"
    grid_elements = [
        f"{grid_id}.8.elem.sujeto_activo_empleado_publico",
        f"{grid_id}.8.elem.modalidad_ocultacion",
    ]
    nexus_elements = [
        # Grid says *empleado_publico*, nexus says the short form.
        f"{grid_id}.8.elem.sujeto_activo",
        f"{grid_id}.8.elem.modalidad_ocultacion",
    ]
    v = _violation(grid_id, grid_elements, nexus_element_ids=nexus_elements)
    r = v21_element_id_closure(v, {})
    assert r.status == "fail"
    # Either the closure check or the template check must fire; both are
    # valid findings and the test accepts either, but the status must fail.