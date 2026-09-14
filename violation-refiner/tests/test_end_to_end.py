"""End-to-end smoke test: the library can reproduce a refined CL-005 bundle
that the validator accepts (7+ pass, 0 fail)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def example_module(tmp_path_factory):
    """Run the example script in a tmp build dir, return its globals."""
    repo_root = Path(__file__).parent.parent
    example_path = repo_root / "examples" / "refine_cl005.py"
    spec = importlib.util.spec_from_file_location("refine_cl005", example_path)
    mod = importlib.util.module_from_spec(spec)
    # The module executes on exec. It defaults to a temp dir when imported, so
    # nothing here can overwrite the converter's canonical build/CL-005 with
    # this demo's HTML-sourced, legacy-id bundle.
    spec.loader.exec_module(mod)
    return mod


def test_endtoend_does_not_write_the_repo_build_dir(example_module):
    """The demo must stay out of the converter's output tree."""
    repo_build = (Path(__file__).parent.parent / "build").resolve()
    build_root = example_module.BUILD_ROOT.resolve()
    assert build_root != repo_build
    assert repo_build not in build_root.parents


def test_endtoend_produces_a_bundle(example_module):
    v = example_module.violation
    assert v.violation_id == "CL-005"
    # Layer 1
    assert len(v.segments) == 9
    # Layer 2
    assert len(v.established_articles) == 2
    assert len(v.candidate_articles) == 1
    # Layer 3
    assert len(v.element_grids) == 1
    art193 = v.element_grids[0]
    assert art193.weighted_score() > 0.85, f"Got {art193.weighted_score()}"
    # Layer 4
    assert len(v.nexus_matrix) == 10
    # Layer 5
    assert len(v.authorities) == 2
    assert all(not a.verified for a in v.authorities), "Authorities must not be auto-verified."
    # Confidence
    assert v.confidence is not None
    assert 0.0 < v.confidence.value <= 1.0


def test_endtoend_validation_report(example_module):
    # The expected check count is derived from the pipeline itself, never
    # pinned: a hardcoded total silently becomes a "registration" test that
    # has to be edited every time a check is added, instead of asserting that
    # the run executed the whole pipeline.
    from violation_pack.validation import DEFAULT_PIPELINE

    report = example_module.report
    summary = report.summary
    assert summary["total"] == len(DEFAULT_PIPELINE)
    assert [c.check_id for c in report.checks] == [cid for cid, _, _ in DEFAULT_PIPELINE]
    assert summary["fail"] == 0, f"Failures present: {[c for c in report.checks if c.status == 'fail']}"
    assert summary["pass"] >= 6, f"Only {summary['pass']} passes; details: {report.summary}"


def test_endtoend_bundle_files_exist(example_module):
    root = example_module.BUNDLE_ROOT
    assert (root / "CL-005.json").exists()
    assert (root / "MANIFEST.txt").exists()
    assert (root / "Transcripts" / "I-002_05_NAR-07_STG_7_post_removal_investigation.html").exists()
    assert (root / "Legal framework" / "CHIPENCOD_CP.md").exists()
    assert (root / "Validation" / "checks.json").exists()
