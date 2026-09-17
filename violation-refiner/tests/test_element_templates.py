"""Element template registry: shape, lookup, composition, drift."""
from __future__ import annotations

import pytest

from violation_pack.element_templates import (
    ArticleTemplate,
    ElementSpec,
    TEMPLATES,
    _split_article,
    find_template,
    parse_element_id,
    template_drift,
)


# ---------------------------------------------------------------------------
# parse_element_id
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("element_id, expected", [
    (
        "CL.CHIPENCOD.T4.C3.Art.193.8.elem.modalidad_ocultacion",
        ("CL.CHIPENCOD.T4.C3.Art.193", "8", "modalidad_ocultacion"),
    ),
    (
        "CL.CPCL.C1.Art.255.elem.vejacion_injusta",
        ("CL.CPCL.C1.Art.255", None, "vejacion_injusta"),
    ),
    (
        "CL.CPCL.C1.Art.269_ter.elem.conocimiento_inocencia",
        ("CL.CPCL.C1.Art.269_ter", None, "conocimiento_inocencia"),
    ),
    (
        "CL.CC.Art.2314.elem.nexo_causal",
        ("CL.CC.Art.2314", None, "nexo_causal"),
    ),
])
def test_parse_element_id_accepts_canonical_forms(element_id, expected):
    assert parse_element_id(element_id) == expected


@pytest.mark.parametrize("bad", [
    "",
    "no-elem-marker",
    "CL.CHIPENCOD.Art.193.elem.",           # empty key
    "CL.CHIPENCOD.Art.193.elem.Bad-Key",    # hyphen in key
    "CL.CHIPENCOD.Art.193.8.elemento.foo",  # wrong separator
])
def test_parse_element_id_rejects_malformed(bad):
    assert parse_element_id(bad) is None


# ---------------------------------------------------------------------------
# Article lookup
# ---------------------------------------------------------------------------

def test_find_template_resolves_hierarchy_variants():
    a = find_template("CL.CHIPENCOD.T4.C3.Art.193", numeral="8")
    b = find_template("CL.CHIPENCOD.Art.193", numeral="8")
    assert a is not None and b is not None
    assert a is b, "hierarchy segments must not create a second registry entry"


def test_find_template_falls_back_to_numeral_less():
    # 269_ter has no numeral; asking with one must still resolve.
    assert find_template("CL.CPCL.C1.Art.269_ter", numeral=None) is not None


def test_find_template_returns_none_for_unregistered():
    assert find_template("CL.UNKNOWN.FW.Art.9999") is None


def test_split_article_on_unshaped_input():
    assert _split_article("not.an.art") is None
    assert _split_article("") is None
    assert _split_article("X.Y") is None


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

def test_element_id_includes_numeral_when_present():
    t = find_template("CL.CHIPENCOD.Art.193", numeral="8")
    assert t is not None
    spec = t.spec_for("modalidad_ocultacion")
    assert spec is not None
    assert t.element_id("CL.CHIPENCOD.T4.C3.Art.193", spec) == (
        "CL.CHIPENCOD.T4.C3.Art.193.8.elem.modalidad_ocultacion"
    )


def test_element_id_omits_numeral_when_absent():
    t = find_template("CL.CPCL.C1.Art.255")
    assert t is not None
    spec = t.spec_for("vejacion_injusta")
    assert spec is not None
    assert t.element_id("CL.CPCL.C1.Art.255", spec) == (
        "CL.CPCL.C1.Art.255.elem.vejacion_injusta"
    )


def test_prompt_block_carries_final_ids():
    t = find_template("CL.CHIPENCOD.T4.C3.Art.193", numeral="8")
    block = t.as_prompt_block("CL.CHIPENCOD.T4.C3.Art.193")
    ids = [e["element_id"] for e in block["elements"]]
    assert all(i.startswith("CL.CHIPENCOD.T4.C3.Art.193.8.elem.") for i in ids)
    assert all(parse_element_id(i) is not None for i in ids)


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------

def test_template_drift_reports_missing_required():
    t = find_template("CL.CPCL.C1.Art.255")
    drift = template_drift("CL.CPCL.C1.Art.255",
                           element_keys=[s.key for s in t.elements[:-1]])
    assert drift is not None
    assert drift.missing_required == (t.elements[-1].key,)
    assert not drift.clean


def test_template_drift_reports_extras():
    t = find_template("CL.CPCL.C1.Art.255")
    keys = [s.key for s in t.elements] + ["invented_element"]
    drift = template_drift("CL.CPCL.C1.Art.255", element_keys=keys)
    assert drift is not None
    assert drift.extra_keys == ("invented_element",)


def test_template_drift_returns_none_for_unknown_article():
    assert template_drift("CL.UNKNOWN.FW.Art.9999", element_keys=["whatever"]) is None


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------

def test_every_registered_template_has_unique_keys():
    for template in TEMPLATES.values():
        keys = [s.key for s in template.elements]
        assert len(keys) == len(set(keys)), (
            f"duplicate element keys in {template.framework} Art. {template.number}"
        )


def test_every_registered_element_key_is_snake_case():
    import re
    pat = re.compile(r"^[a-z][a-z0-9_]*$")
    for template in TEMPLATES.values():
        for spec in template.elements:
            assert pat.match(spec.key), (
                f"{spec.key!r} in {template.framework} Art. {template.number} "
                "is not snake_case"
            )


def test_every_registered_template_has_at_least_one_required_element():
    for template in TEMPLATES.values():
        assert template.required_keys(), (
            f"{template.framework} Art. {template.number} declares no required "
            "element; a template that requires nothing cannot be checked"
        )