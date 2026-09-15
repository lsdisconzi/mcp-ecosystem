"""Tests for the candidate-article stage's output bound.

This stage is the only one of the eight whose items come from OUTSIDE the
input: `segments`, `nexus`, `cross_references` etc. can only propose things the
bundle already holds, while "articles a careful analyst would propose" ranges
over every article of every code in the corpus. An unbounded request against an
unbounded space is an unbounded reply, and the reply grew until the output
budget ran out. Measured live on CL-030 with `deepseek-chat`, the model walked
the Chilean Penal Code in ascending order (Art. 150, 151, 250, 251, 292, 293,
296, 297, 411, ...) and was still emitting when the 64,000-token escalation cut
it mid-string, which aborted the whole run at stage 5 of 8.

No network here: the stage is driven with a fake client that returns a list of
whatever length the test needs.
"""
from __future__ import annotations

from typing import Any

from violation_pack.enrich import (
    MAX_CANDIDATES,
    _CANDIDATES_PROMPT,
    propose_candidates,
)
from violation_pack.models import CachedArticle, EvidenceSegment, Incident, Violation

SHA = "a" * 64


class _FakeLLM:
    """Answers `chat_json` from a queue and records what it was asked."""

    def __init__(self, *responses: Any):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def chat_json(self, *, messages, system=None, max_tokens=None):
        self.calls.append({"messages": messages, "system": system})
        if not self.responses:
            raise AssertionError("unexpected extra LLM call")
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _violation(**overrides: Any) -> Violation:
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
        **overrides,
    )


def _candidate(n: int, *, framework: str = "CPCL") -> dict[str, Any]:
    """A candidate the parser accepts, numbered so its order is visible."""
    aid = f"CL.{framework}.C1.Art.{n}"
    return {
        "candidate_article_id": aid,
        "candidate_name": f"Article {n}",
        "framework_cache_status": "not_in_bundle",
        "verification_required": [f"Fetch verbatim text for {aid} from bcn.cl/leychile"],
        "preliminary_view": f"Plausible under STG-1.seg-1 for reason {n}.",
        "history_note": None,
    }


# ---------------------------------------------------------------------------
# The cap
# ---------------------------------------------------------------------------

def test_a_runaway_reply_is_capped_at_max_candidates():
    """The reported failure: hundreds of proposals, each one 'valid'."""
    llm = _FakeLLM({"candidates": [_candidate(n) for n in range(1, 301)]})
    out = propose_candidates(_violation(), llm)
    assert len(out) == MAX_CANDIDATES


def test_the_cap_keeps_the_first_candidates_not_the_last():
    """The prompt asks for 'most material first', so the head of the list is
    the part worth keeping; trimming the tail is the whole point."""
    llm = _FakeLLM({"candidates": [_candidate(n) for n in range(1, 51)]})
    out = propose_candidates(_violation(), llm)
    assert [c.candidate_article_id for c in out] == [
        f"CL.CPCL.C1.Art.{n}" for n in range(1, MAX_CANDIDATES + 1)
    ]


def test_a_short_list_is_returned_whole():
    """Guards the off-by-one: the cap is a ceiling, not a truncation-to-N."""
    llm = _FakeLLM({"candidates": [_candidate(n) for n in (10, 20, 30)]})
    out = propose_candidates(_violation(), llm)
    assert [c.candidate_article_id for c in out] == [
        "CL.CPCL.C1.Art.10",
        "CL.CPCL.C1.Art.20",
        "CL.CPCL.C1.Art.30",
    ]


def test_rejected_candidates_do_not_consume_the_cap():
    """The ceiling counts *accepted* items, not list positions.

    A model that pads its list with placeholder frameworks (`CL.FW.Art.N`) or
    with candidates that carry no verification step must not thereby push the
    usable ones past the cap — otherwise a long bad prefix silently empties the
    stage.
    """
    junk = []
    for n in range(1, 41):
        junk.append(_candidate(n, framework="FW"))            # rejected: prefix
    for n in range(100, 140):
        bad = _candidate(n)
        bad["verification_required"] = []                     # rejected: no steps
        junk.append(bad)
    llm = _FakeLLM({"candidates": junk + [_candidate(n) for n in range(200, 230)]})
    out = propose_candidates(_violation(), llm)
    assert [c.candidate_article_id for c in out] == [
        f"CL.CPCL.C1.Art.{n}" for n in range(200, 200 + MAX_CANDIDATES)
    ]


def test_an_established_article_does_not_consume_the_cap():
    """Same rule as the junk above, for the other rejection reason: an article
    the bundle already holds is filtered out before the ceiling is counted."""
    already = CachedArticle(
        article_id="CL.CPCL.C1.Art.255",
        article_name="Obstruction of justice",
        verbatim_excerpt="El que...",
        verbatim_excerpt_sha256=SHA,
        framework_code="CPCL",
        framework_cache_status="verified_in_bundle",
        duty_bearer="funcionario publico",
        norm_type="prohibition",
        applicability="direct",
        applicability_rationale="Anchored to STG-1.seg-1.",
    )
    llm = _FakeLLM({"candidates": [
        {**_candidate(255), "candidate_article_id": "CL.CPCL.C1.Art.255"},
        *[_candidate(n) for n in range(1, 30)],
    ]})
    out = propose_candidates(_violation(established_articles=[already]), llm)
    ids = [c.candidate_article_id for c in out]
    assert "CL.CPCL.C1.Art.255" not in ids
    assert ids == [f"CL.CPCL.C1.Art.{n}" for n in range(1, MAX_CANDIDATES + 1)]


# ---------------------------------------------------------------------------
# The contract the code cap backstops
# ---------------------------------------------------------------------------

def test_the_prompt_states_the_cap_the_code_enforces():
    """Drift guard: the code ceiling only ever fires when the model ignores
    the prompt, so the two numbers must not diverge."""
    assert f"AT MOST {MAX_CANDIDATES}" in _CANDIDATES_PROMPT


def test_the_prompt_forbids_enumerating_a_code():
    """The measured failure mode was an ascending walk of the statute, so the
    rule that forbids it is load-bearing — not decoration."""
    assert "enumerate" in _CANDIDATES_PROMPT
    assert "walking a statute" in _CANDIDATES_PROMPT
