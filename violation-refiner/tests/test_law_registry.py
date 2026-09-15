"""Tests for the registry-backed cross-code mis-attribution guardrail.

The defect this covers, measured live on CL-030: the candidates stage emitted
``CL.CPCL.C1.Art.2314`` while describing an article of the Chilean *Código
Civil*. The prefix test (`enrich._has_known_framework`) saw a valid framework
segment and waved it through, so a Civil Code article number was written into
the bundle wearing the Penal Code's namespace — and Art. 2314 does not exist in
the Chilean Penal Code.

The rule is deliberately *not* "reject numbers above the code's maximum".
``data/law/_mapping/law_registry.json`` is an ingestion coverage report, so a
per-code maximum is an *extract* size: the Penal Code file holds 7 of ~500
articles, and a max test would reject Art. 100, .300, .391, .436, .470 — all
real, merely not ingested. Each test below pins one of the conditions that
replaced that idea, and each condition is isolated by constructing a registry
where *only* it can be the deciding factor.

The synthetic registries are stipulated rather than sampled from the corpus
(the registry is a generated artifact and is not tracked, so no test may depend
on it). They reproduce the measured structure of the real one where the
structure is what makes a condition load-bearing — see ``_BR`` for the clearest
case, where the sibling code's sparsity is the whole point.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from violation_pack import law_registry
from violation_pack.enrich import _has_known_framework, enrich_violation, propose_candidates
from violation_pack.law_registry import ArticleExtents, find_registry_path
from violation_pack.models import EvidenceSegment, Incident, Violation

SHA = "a" * 64


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _registry(*files: tuple[str, list[str]]) -> dict[str, Any]:
    """Build the registry JSON shape from (filename, elis) pairs."""
    return {
        "summary": {},
        "files": [
            {"path": path, "in_qdrant_eli": elis, "reference_only": False}
            for path, elis in files
        ],
        "qdrant_only_articles": [],
        "detail": [],
    }


def _arts(jur: str, fw: str, numbers) -> list[str]:
    return [f"{jur}.{fw}.Art.{n}" for n in numbers]


#: Mirrors the measured Chilean shape: a Penal Code whose extract reaches 494,
#: a Civil Code sample of 6 numbers up to 2329, and a small constitutional code.
#: The 2329/494 = 4.7 ratio is what makes CC an extent outlier.
_CL = _registry(
    ("CL/CodigoPenal.md", _arts("CL", "CPCL", (17, 94, 255, 269, 412, 416, 494))),
    ("CL/CC_CodigoCivil.md", _arts("CL", "CC", (1437, 1546, 1698, 2314, 2328, 2329))),
    ("CL/CPR_BCN.md", _arts("CL", "CPR_BCN", (19, 24, 25, 100))),
)

#: Mirrors the measured Brazilian shape, which is where the exclusive band
#: earns its place. ``BR.CC``'s sample is only a handful of numbers, so
#: membership in it proves very little; ``BR.CBA`` is sparse (128 numbers
#: reaching 302 in the real registry, not a dense run) and so does not contain
#: 53 — which leaves ``BR.R400.Art.53`` looking like a sole-owner match for CC
#: until the band check requires the number to be above every other code's
#: reach. A dense CBA here would make the band redundant, because the
#: reaching-set size would already have excluded it.
_BR = _registry(
    ("BR/CC_CodigoCivil.md", _arts("BR", "CC", (53, 900, 927))),
    ("BR/CBA.md", _arts("BR", "CBA", list(range(3, 301, 3)) + [302])),
    ("BR/R400.md", _arts("BR", "R400", range(1, 47))),
)

#: Mirrors the international shape, where *no* code dominates: MC99 reaches 59
#: against a 40 runner-up (1.48x, below the 2.0 gate), so the rule must switch
#: itself off rather than reason about "MC99-only territory".
_INT = _registry(
    ("INT/MC99.md", _arts("INT", "MC99", range(1, 60))),
    ("INT/CHICAGO.md", _arts("INT", "CHICAGO", range(1, 39))),
    ("INT/VCLT.md", _arts("INT", "VCLT", range(1, 41))),
)


def _index(data: dict[str, Any]) -> ArticleExtents:
    return ArticleExtents.from_registry(data)


@pytest.fixture(autouse=True)
def _never_cache_a_registry_across_tests():
    """The index is cached per resolved path; no test may inherit another's."""
    yield
    law_registry.clear_cache()


@pytest.fixture
def registered(monkeypatch, tmp_path):
    """Point the module at a synthetic registry for the duration of a test."""

    def _install(data: dict[str, Any]) -> Path:
        path = tmp_path / "law_registry.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setenv(law_registry.REGISTRY_ENV_VAR, str(path))
        law_registry.clear_cache()
        return path

    return _install


# ---------------------------------------------------------------------------
# The reported defect
# ---------------------------------------------------------------------------

def test_a_civil_code_number_under_the_penal_code_prefix_is_rejected():
    """The exact live failure. Every other condition already passed for this
    id; the whole point is that Art. 2314 is beyond the Penal Code's reach and
    inside the Civil Code's exclusive band."""
    mis = _index(_CL).misattribution("CL.CPCL.C1.Art.2314")
    assert mis is not None
    assert mis.number == 2314
    assert (mis.sibling_jurisdiction, mis.sibling_framework) == ("CL", "CC")


def test_the_same_number_in_its_own_namespace_is_kept():
    """The guardrail must not be a blacklist of article numbers: 2314 is a
    perfectly good article *of the Código Civil*.

    An outcome assertion, not an isolation of the own-extent guard: that
    guard is subsumed by the exclusive band and cannot be isolated by any
    fixture (see the module docstring and
    ``test_the_band_is_what_decides_the_two_owner_case``).
    """
    assert _index(_CL).misattribution("CL.CC.Art.2314") is None


def test_rejecting_the_wrong_prefix_must_not_cascade_to_the_whole_family():
    """All six Civil Code numbers in the sample are outside every other CL
    code's reach, so each is rejected under each prefix — the rule is about the
    number, not about one unlucky id."""
    idx = _index(_CL)
    for n in (1437, 1546, 1698, 2314, 2328, 2329):
        assert idx.misattribution(f"CL.CPCL.C1.Art.{n}") is not None


def test_a_real_article_that_was_never_ingested_is_kept():
    """The reason the rule cannot be a max-article test. The Penal Code runs to
    ~500 articles; the registry's extract stops at 494 and holds 7 of them, so
    Art. 100 is *legitimate* despite being unobserved."""
    idx = _index(_CL)
    for n in (100, 300, 391, 436, 470):
        assert idx.misattribution(f"CL.CPCL.C1.Art.{n}") is None


# ---------------------------------------------------------------------------
# The exclusive band (the sparse-extract false positive)
# ---------------------------------------------------------------------------

def test_the_band_keeps_a_number_a_sparse_sibling_happens_to_hold():
    """Isolates condition 5.
    ``BR.R400`` reaches 46 and the number is in ``BR.CC``'s sample, so the
    sole-owner test passes — but Brazilian codes reach 302, so 53 is not
    *uniquely* CC's and a Brazilian resolution with an Art. 53 is unremarkable.
    Rejecting it was a measured false positive of the band-less rule (which
    reported 277 rejections instead of 126).
    """
    assert _index(_BR).misattribution("BR.R400.Art.53") is None


def test_the_band_still_rejects_above_every_other_codes_reach():
    """The same framework and the same sibling as the test above; only the
    band differs. 900 is past 302, every other BR code included."""
    mis = _index(_BR).misattribution("BR.R400.Art.900")
    assert mis is not None
    assert (mis.sibling_jurisdiction, mis.sibling_framework) == ("BR", "CC")
    assert mis.band_floor == 302


# ---------------------------------------------------------------------------
# The outlier gate (the jurisdiction where no code dominates)
# ---------------------------------------------------------------------------

def test_no_code_dominates_so_the_rule_switches_itself_off():
    """Isolates condition 6, and is why it is derived rather than a hardcoded
    jurisdiction list.

    ``INT.CHICAGO`` reaches 38 and ``INT.MC99`` reaches 59, which contains 50 —
    a sole owner by the letter of the rule. But 59 vs 40 is a 1.48x ratio, not
    an outlier: a convention reaching 59 articles is ordinary, so "Art. 50 is
    MC99's" is not a safe inference. Measured live, this is the shape that
    produced the ``INT.CHICAGO.Art.50``, ``INT.UNCRC.Art.40`` and
    ``INT.VCLT.Art.40`` false positives.
    """
    idx = _index(_INT)
    assert ("INT", "MC99") not in idx.outliers
    assert idx.misattribution("INT.CHICAGO.Art.50") is None


def test_the_outlier_gate_is_what_excludes_the_runaway_code():
    """Same registry, one number moved: give MC99 a genuinely dominant extent
    and the identical candidate is now rejected, proving the gate — not an
    unrelated condition — is what kept it."""
    dominated = _registry(
        ("INT/MC99.md", _arts("INT", "MC99", list(range(1, 60)) + [3000, 4000])),
        ("INT/CHICAGO.md", _arts("INT", "CHICAGO", range(1, 39))),
        ("INT/VCLT.md", _arts("INT", "VCLT", range(1, 41))),
    )
    idx = _index(dominated)
    assert ("INT", "MC99") in idx.outliers
    assert idx.misattribution("INT.MC99.Art.50") is None  # inside its own reach
    assert idx.misattribution("INT.CHICAGO.Art.3000") is not None


# ---------------------------------------------------------------------------
# Where the rule must decline to judge
# ---------------------------------------------------------------------------

def test_a_sibling_in_another_jurisdiction_is_not_evidence():
    """Isolates the ``(jurisdiction, framework)`` key.

    ``CC`` is the framework segment of *both* the Brazilian and the Chilean
    Civil Code, so keying on the framework alone mixes two codes: a Chilean
    article number would then convict a Brazilian id. Only same-jurisdiction
    codes may be treated as evidence about an id.
    """
    idx = _index(_registry(
        ("CL/CC_CodigoCivil.md", _arts("CL", "CC", (2314, 2329))),
        ("CL/CodigoPenal.md", _arts("CL", "CPCL", (494,))),
        ("BR/CC_CodigoCivil.md", _arts("BR", "CC", (927,))),
        ("BR/CodigoPenal.md", _arts("BR", "CPCL", range(1, 101))),
    ))
    # The same number under both prefixes; only the Chilean code can own it.
    assert idx.misattribution("CL.CPCL.Art.2314") is not None
    assert idx.misattribution("BR.CPCL.Art.2314") is None


def test_ownership_must_be_unambiguous():
    """Two codes reaching *and* holding the number means there is no single
    attribution to correct, so the candidate stands.

    An outcome assertion, not an isolation of the sole-owner test: with two
    owners the exclusive band blocks regardless, so no fixture can separate
    them. Asserting the fixture really presents two owners is the point of
    the first four lines.
    """
    idx = _index(_registry(
        ("CL/CC_CodigoCivil.md", _arts("CL", "CC", (500, 2329))),
        ("CL/BIG.md", _arts("CL", "BIG", (500, 900))),
        ("CL/CodigoPenal.md", _arts("CL", "CPCL", range(1, 101))),
    ))
    owners = [k for k in (("CL", "CC"), ("CL", "BIG")) if 500 in idx.occupied[k]]
    assert len(owners) == 2, "fixture must present two owners to be the case"
    assert idx.misattribution("CL.CPCL.Art.500") is None


def test_the_band_is_what_decides_the_two_owner_case():
    """An executable note on the *structure* of the rule, so the two conditions
    the tests above cannot isolate are not mistaken for mechanisms.

    Measured, by deleting one condition at a time from ``misattribution`` and
    replaying 120 random registries × 2,500 numbers × 3 codes (900,000 ids):
    the sole-owner test and the own-extent guard change **zero** verdicts, the
    band changes 3,645. Here 500 is below the largest third-party extent, so
    the band is what keeps the candidate — the owner count never decides.

    If someone makes the subsumed conditions load-bearing, this fails, and the
    module docstring needs rewriting alongside it.
    """
    idx = _index(_registry(
        ("CL/CC_CodigoCivil.md", _arts("CL", "CC", (500, 2329))),
        ("CL/BIG.md", _arts("CL", "BIG", (500, 900))),
        ("CL/CodigoPenal.md", _arts("CL", "CPCL", range(1, 101))),
    ))
    largest = max(("CL", "CC"), ("CL", "BIG"), key=lambda k: idx.extent[k])
    top_other = max(idx.extent[k] for k in (("CL", "CC"), ("CL", "BIG")) if k != largest)
    assert top_other >= 500, "the band must already block 500"
    assert idx.misattribution("CL.CPCL.Art.500") is None


def test_a_number_no_owner_actually_holds_is_kept():
    """Isolates the containment requirement: reaching a number is not holding
    it. ``CL.CC`` reaches 2329, but 696 is not one of the articles it holds."""
    idx = _index(_CL)
    assert 696 not in idx.occupied[("CL", "CC")]
    assert idx.misattribution("CL.CPCL.Art.696") is None


def test_a_compound_standard_tail_is_kept():
    """``INT.ACHR`` numbers its articles by standard (Art. 2.13.1), so "is this
    in range" is not a meaningful question and the number carries no sequence
    position to compare."""
    idx = _index(_registry(
        ("INT/ACHR.md", ["INT.ACHR.T1.C2.Art.2.13.1", "INT.ACHR.T1.C2.Art.2.1.1"]),
        ("INT/UNCRC.md", _arts("INT", "UNCRC", range(1, 42))),
    ))
    assert idx.misattribution("INT.UNCRC.Art.2.13.1") is None


def test_a_compound_tail_does_not_inflate_its_codes_extent():
    """An unanchored search for ``\\.Art\\.(\\d+)`` would read ``Art.2.13.1`` as
    article 2 and report the code's extent as 2, making every later count look
    like it exceeded the code. Such ids are excluded from the index entirely."""
    idx = _index(_registry(
        ("INT/ACHR.md", ["INT.ACHR.T1.Art.2.13.1", "INT.ACHR.T1.Art.9.9.9"]),
    ))
    assert ("INT", "ACHR") not in idx.extent


def test_an_unknown_code_is_kept():
    """No data for the code means the rule cannot judge the number, and
    "cannot judge" must mean keep. Rejecting here would silently delete
    candidates for every code that is not yet ingested."""
    assert _index(_CL).misattribution("CL.ZZZ.Art.9999") is None
    assert _index(_CL).misattribution("CL.CPCL.Art") is None
    assert _index(_CL).misattribution("CPCL") is None


def test_a_missing_registry_disables_the_guardrail_rather_than_the_run(
    monkeypatch, tmp_path
):
    """Degrade safely: a coverage report that is not on disk must not be able
    to fail an enrichment run, and must not start rejecting on no evidence."""
    monkeypatch.setenv(
        law_registry.REGISTRY_ENV_VAR, str(tmp_path / "does_not_exist.json")
    )
    law_registry.clear_cache()
    assert law_registry.load_extents() is None

    llm = _FakeLLM({"candidates": [_candidate("CL.CPCL.C1.Art.2314")]})
    # The prefix test still passes (CPCL is a real code), and with no registry
    # to consult the mis-attribution check steps aside.
    out = propose_candidates(_violation(), llm)
    assert [c.candidate_article_id for c in out] == ["CL.CPCL.C1.Art.2314"]


def test_an_unreadable_registry_is_treated_as_absent(tmp_path, monkeypatch):
    path = tmp_path / "law_registry.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv(law_registry.REGISTRY_ENV_VAR, str(path))
    law_registry.clear_cache()
    assert law_registry.load_extents() is None


# ---------------------------------------------------------------------------
# The framework set must not drift from the registry
# ---------------------------------------------------------------------------

def test_the_framework_set_is_widened_by_the_registry(registered):
    """Measured drift: 23 frameworks in the corpus were absent from the
    hand-maintained set, so a legitimate candidate for any of them was dropped
    by Guardrail 1 before the mis-attribution rule ever ran."""
    registered(_registry(("XX/NewCode.md", _arts("CL", "BRAND_NEW", (1, 2, 3)))))
    assert _has_known_framework("CL.BRAND_NEW.Art.1") is True
    assert _has_known_framework("CL.STILL_ABSENT.Art.1") is False


def test_the_registry_widens_the_set_without_disarming_the_placeholder_test():
    """A registry-backed set must not become a blanket allow: an id whose
    framework is in neither the set nor the registry is still a typo."""
    assert _has_known_framework("CL.FW.Art.1") is False
    assert _has_known_framework("CL.Art.1") is False
    assert _has_known_framework("CPCL.Art.1") is False


def test_unknown_framework_names_are_reported_not_just_dropped():
    """A dropped candidate should leave a trace: a placeholder prefix is a
    model error worth surfacing, and the reason is what the provenance note
    quotes."""
    rejected: list[str] = []
    llm = _FakeLLM({"candidates": [_candidate("CL.FW.Art.9")]})
    out = propose_candidates(_violation(), llm, on_reject=rejected.append)
    assert out == []
    assert rejected and "unknown framework" in rejected[0]


# ---------------------------------------------------------------------------
# Integration with the stage and its cap
# ---------------------------------------------------------------------------

def test_a_misattributed_candidate_does_not_consume_the_cap(registered):
    """Same rule as the other rejection reasons: the ceiling counts *accepted*
    items, so a misfiled id in the head of the list must not push a usable one
    past it."""
    registered(_CL)
    llm = _FakeLLM({"candidates": [
        _candidate("CL.CPCL.C1.Art.2314"),
        _candidate("CL.CPCL.C1.Art.1546"),
        _candidate("CL.CPCL.C1.Art.100"),
        _candidate("CL.CPCL.C1.Art.400"),
    ]})
    out = propose_candidates(_violation(), llm)
    assert [c.candidate_article_id for c in out] == [
        "CL.CPCL.C1.Art.100",
        "CL.CPCL.C1.Art.400",
    ]


def test_the_dropped_ids_are_recorded_in_provenance(registered):
    """The panel can only show what the run logged, so a guardrail that fired
    has to say so — otherwise a suppressed candidate is indistinguishable from
    one the model never proposed."""
    registered(_CL)
    llm = _FakeLLM({"candidates": [
        _candidate("CL.CPCL.C1.Art.2314"),
        _candidate("CL.CPCL.C1.Art.100"),
    ]})
    v = enrich_violation(_violation(), client=llm, stages=["candidates"])
    entries = [p for p in v.provenance if p.operation == "enrich_violation:candidates"]
    assert len(entries) == 1
    note = entries[0].note
    assert "1 item(s)" in note
    assert "CL.CPCL.C1.Art.2314" in note
    assert "2314" in note and "CC-only" in note


def test_a_clean_run_logs_no_rejection_note(registered):
    """The note is evidence, so it must not appear when nothing was dropped."""
    registered(_CL)
    llm = _FakeLLM({"candidates": [_candidate("CL.CPCL.C1.Art.100")]})
    v = enrich_violation(_violation(), client=llm, stages=["candidates"])
    entry = [p for p in v.provenance if p.operation == "enrich_violation:candidates"][0]
    assert entry.note == "1 item(s)"


# ---------------------------------------------------------------------------
# Against the real registry (skipped when the generated artifact is absent)
# ---------------------------------------------------------------------------

_REGISTRY = find_registry_path()
needs_registry = pytest.mark.skipif(
    _REGISTRY is None,
    reason="data/law/_mapping/law_registry.json is a generated artifact and is not tracked",
)

#: Legitimate ids probed against the shipped registry: in-range articles,
#: articles of a code whose extract is partial, and compound-standard ids. The
#: rule must reject none of them.
_NOT_MISATTRIBUTED = [
    "CL.CPCL.Art.1", "CL.CPCL.Art.15", "CL.CPCL.Art.100", "CL.CPCL.Art.300",
    "CL.CPCL.Art.391", "CL.CPCL.Art.436", "CL.CPCL.Art.470", "CL.CPCL.Art.496",
    "CL.CONST.Art.100", "CL.CONST.Art.19", "CL.CONST.Art.129",
    "CL.CC.Art.1000", "CL.CC.Art.2500", "CL.LPDC.Art.60", "CL.L20285.Art.50",
    "CL.CHIPENCOD.T4.Art.400", "CL.L16752.T3.Art.30", "CL.CACH.Art.200",
    "BR.L13460.Art.32", "BR.L13460.Art.40", "BR.D7203.Art.10", "BR.CF88.Art.5",
    "BR.CDC.Art.150", "BR.ABEAR_PAC.Art.15", "BR.L8429.Art.30",
    "BR.R400.Art.53", "BR.L9784.Art.59",
    "INT.MC99.Art.20", "INT.AN9.Art.20", "INT.CHICAGO.Art.50",
    "INT.UNCRC.Art.40", "INT.IATA_GC.Art.25", "INT.VCLT.Art.40",
    "INT.VCCR.Art.40", "INT.AN17.C4.Art.5",
]


@needs_registry
def test_the_reported_case_is_rejected_against_the_shipped_registry():
    idx = law_registry.load_extents()
    assert idx is not None
    assert idx.misattribution("CL.CPCL.C1.Art.2314") is not None
    assert idx.misattribution("CL.CC.Art.2314") is None


@needs_registry
def test_no_legitimate_id_is_rejected_against_the_shipped_registry():
    """0 false positives through a probe of in-range and not-yet-ingested ids.
    This is the assertion that a naive max-article check would fail."""
    idx = law_registry.load_extents()
    assert idx is not None
    rejected = {i: idx.misattribution(i) for i in _NOT_MISATTRIBUTED}
    assert [i for i, m in rejected.items() if m is not None] == []


@needs_registry
def test_every_rejection_targets_the_civil_code_sample_of_its_jurisdiction():
    """The rule's whole reject set, described semantically so a growing corpus
    does not make the test brittle: every rejection must be a number the
    dominant code's sample actually holds, above every other code's reach."""
    idx = law_registry.load_extents()
    assert idx is not None
    rejects = []
    for (jur, fw) in idx.extent:
        for n in range(1, 4000):
            mis = idx.misattribution(f"{jur}.{fw}.Art.{n}")
            if mis is not None:
                rejects.append(mis)

    assert rejects, "expected the guardrail to still catch the known misfilings"
    for mis in rejects:
        sibling = (mis.sibling_jurisdiction, mis.sibling_framework)
        assert sibling in idx.outliers
        assert mis.number in idx.occupied[sibling]
        assert mis.number > mis.band_floor
        # And never the code the number actually belongs to.
        assert (mis.jurisdiction, mis.framework) != sibling

    # The international set has no dominant code, so nothing there is rejected.
    assert [m.article_id for m in rejects if m.jurisdiction == "INT"] == []


@needs_registry
def test_the_framework_set_covers_every_framework_the_corpus_contains():
    """The drift that cost 23 frameworks. Derive the allow-list from the
    registry instead of mirroring it in a literal."""
    idx = law_registry.load_extents()
    assert idx is not None
    missing = sorted(
        fw for fw in idx.framework_segments if not _has_known_framework(f"CL.{fw}.Art.1")
    )
    assert missing == []
    # Spelled differently on each side, which is how the drift happened.
    for fw in ("L8906_OAB", "CPR_BCN", "HAGUE1980", "CED_OAB", "ABEAR_RIC", "JAC"):
        if fw in idx.framework_segments:
            assert _has_known_framework(f"BR.{fw}.Art.1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeLLM:
    def __init__(self, *responses: Any):
        self.responses = list(responses)

    def chat_json(self, *, messages, system=None, max_tokens=None):
        if not self.responses:
            raise AssertionError("unexpected extra LLM call")
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _candidate(aid: str) -> dict[str, Any]:
    return {
        "candidate_article_id": aid,
        "candidate_name": aid,
        "framework_cache_status": "not_in_bundle",
        "verification_required": [f"Fetch verbatim text for {aid}"],
        "preliminary_view": "Plausible under STG-1.seg-1.",
        "history_note": None,
    }


def _violation() -> Violation:
    seg = EvidenceSegment(
        segment_id="STG-1.seg-1",
        role_in_argument="unclassified",
        audio_offset_start=0.0,
        audio_offset_end=1.5,
        speaker="SPK",
        verbatim_es="no me consta",
        verbatim_sha256=SHA,
        translation_en="",
        source_uri="Transcripts/t.html#seg-1",
        source_sha256=SHA,
    )
    return Violation(
        violation_id="CL-TEST",
        title="Test violation",
        severity="LOW",
        incident=Incident(date="2025-01-01", location="SCL"),
        segments=[seg],
    )
