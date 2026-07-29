"""Targeted tests for `violation_pack.verifier`. The end-to-end test
covers the happy path; these tests cover the failure modes."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from violation_pack.models import Authority, CandidateArticle, NexusEntry
from violation_pack.verifier import verify_enrichment


REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def violation():
    """Reuse the refine_cl005 example to build a fully-enriched violation."""
    spec = importlib.util.spec_from_file_location(
        "refine_cl005", REPO_ROOT / "examples" / "refine_cl005.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.violation


@pytest.fixture(scope="module")
def frameworks():
    spec = importlib.util.spec_from_file_location(
        "refine_cl005", REPO_ROOT / "examples" / "refine_cl005.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {mod.framework.framework_code(): mod.framework}


def test_clean_violation_passes(violation, frameworks):
    report = verify_enrichment(
        violation, frameworks=frameworks, known_violation_ids={"CL-005"}
    )
    assert report.ok, report.as_dict()
    assert report.error_count == 0


def test_authority_with_rol_is_rejected(violation, frameworks):
    poisoned = violation.model_copy(update={
        "authorities": [
            Authority(
                authority_id="AUTH-FAKE",
                type="jurisprudence",
                supports=["CL.CHIPENCOD.T4.C3.Art.193"],
                research_query="x",
                proposition_to_verify="y",
                rol="Rol-12345-2024",
                verified=False,
            )
        ]
    })
    report = verify_enrichment(poisoned, frameworks=frameworks)
    codes = {i.code for i in report.issues}
    assert "E_AUTH_FABRICATED_FIELD" in codes
    assert not report.ok


def test_authority_verified_by_llm_is_rejected(violation, frameworks):
    poisoned = violation.model_copy(update={
        "authorities": [
            Authority(
                authority_id="AUTH-FAKE",
                type="doctrine",
                supports=["CL.CHIPENCOD.T4.C3.Art.193"],
                research_query="x",
                proposition_to_verify="y",
                verified=True,
            )
        ]
    })
    report = verify_enrichment(poisoned, frameworks=frameworks)
    codes = {i.code for i in report.issues}
    assert "E_AUTH_VERIFIED_BY_LLM" in codes


def test_nexus_with_unknown_segment_is_rejected(violation, frameworks):
    grid_id = violation.element_grids[0].article_id
    elem_id = violation.element_grids[0].elements[0].element_id
    poisoned = violation.model_copy(update={
        "nexus_matrix": list(violation.nexus_matrix) + [
            NexusEntry(
                fact_id="STG-9.seg-999",  # does not exist
                norm_id=grid_id,
                element_id=elem_id,
                nexus_type="direct_admission",
                strength="high",
                rationale_oneline="hallucinated",
            )
        ]
    })
    report = verify_enrichment(poisoned, frameworks=frameworks)
    codes = {i.code for i in report.issues}
    assert "E_NEXUS_UNKNOWN_FACT" in codes


def test_candidate_without_verification_required_is_rejected(violation, frameworks):
    # CandidateArticle's Pydantic schema requires verification_required, so
    # we must build with at least one item then strip it via model_copy.
    cand = CandidateArticle(
        candidate_article_id="CL.FAKE.Art.999",
        candidate_name="x",
        framework_cache_status="not_in_bundle",
        verification_required=["placeholder"],
    )
    cand = cand.model_copy(update={"verification_required": []})
    poisoned = violation.model_copy(update={
        "candidate_articles": list(violation.candidate_articles) + [cand]
    })
    report = verify_enrichment(poisoned, frameworks=frameworks)
    codes = {i.code for i in report.issues}
    assert "E_CANDIDATE_NO_VERIFICATION" in codes


def test_cross_reference_unknown_is_warning(violation, frameworks):
    report = verify_enrichment(
        violation,
        frameworks=frameworks,
        known_violation_ids={"CL-005"},  # cross-refs in fixture not present
    )
    # Cross-refs are warnings, not errors — ok must still be True.
    assert report.ok
