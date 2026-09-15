"""Tests for the progress slot and the hook that fills it.

Two halves of one mechanism. `violation_pack.progress` is how the freed event
loop learns what the worker thread is doing, and `enrich_violation`'s
`on_stage` hook is its only writer. Both are tested here because a progress
channel that silently stops reporting is indistinguishable, from the page, from
a run that has hung — the spinner looks the same.
"""
from __future__ import annotations

from typing import Any

import pytest

from violation_pack import progress
from violation_pack.enrich import _log_stage, enrich_violation
from violation_pack.llm import LLMError
from violation_pack.models import EvidenceSegment, Incident, Violation

SHA = "a" * 64


@pytest.fixture(autouse=True)
def _clean_slot():
    """The slot is process-wide, so a leaked run would make the next test's
    `begin` assertions vacuous rather than failing."""
    progress._slot.clear()
    yield
    progress._slot.clear()


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


class _FakeLLM:
    """Answers `chat_json` from a queue and records what it was asked.

    Deliberately not a `MagicMock`: these assertions are about *what the stages
    handed the model*, and a double that answers anything also hides a stage
    that quietly stopped being called.
    """

    def __init__(self, *responses: Any):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def chat_json(self, *, messages, system=None, max_tokens=None):
        self.calls.append(
            {"messages": messages, "system": system, "max_tokens": max_tokens}
        )
        if not self.responses:
            raise AssertionError("unexpected extra LLM call")
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _ops(v: Violation) -> list[str]:
    return [p.operation for p in v.provenance]


# ---------------------------------------------------------------------------
# progress — the slot
# ---------------------------------------------------------------------------

def test_nothing_has_run_yet_is_an_empty_snapshot():
    assert progress.snapshot() == {}


def test_stage_without_begin_is_a_no_op():
    """A tool that reports progress outside begin/end must not invent a run."""
    progress.stage("segments", 1, 8)
    assert progress.snapshot() == {}


def test_begin_then_stage_reports_the_stage_in_flight():
    progress.begin("enrich_violation_tool", total=8)
    progress.stage("segments", 1, 8)
    snap = progress.snapshot()
    assert snap["tool"] == "enrich_violation_tool"
    assert snap["stage"] == "segments"
    assert snap["index"] == 1
    assert snap["total"] == 8
    assert snap["running"] is True
    assert snap["error"] is None
    assert snap["elapsed_seconds"] >= 0


def test_a_bare_stage_call_keeps_the_index_it_was_given():
    """`stage(name)` with no index must not reset the count.

    The caller in `mcp_server` always passes all three, but a zero index would
    read in the panel as the pipeline going *backwards*, which is worse than
    showing nothing.
    """
    progress.begin("t", total=3)
    progress.stage("a", 2, 3)
    progress.stage("b")
    snap = progress.snapshot()
    assert snap["stage"] == "b"
    assert snap["index"] == 2
    assert snap["total"] == 3


def test_end_closes_the_run_and_freezes_the_clock():
    progress.begin("t", total=1)
    progress.end("t")
    snap = progress.snapshot()
    assert snap["running"] is False
    assert snap["error"] is None
    # `finished` is set, so elapsed is a fixed subtraction, not a live clock.
    frozen = snap["elapsed_seconds"]
    assert progress.snapshot()["elapsed_seconds"] == frozen


def test_end_records_the_error_message():
    progress.begin("t", total=1)
    progress.end("t", error="LLMError: model did not return valid JSON")
    assert progress.snapshot()["error"] == "LLMError: model did not return valid JSON"


def test_end_ignores_a_mismatched_tool():
    """A late finisher must not close a run someone else has since claimed."""
    progress.begin("newer", total=1)
    progress.end("older", error="stale")
    snap = progress.snapshot()
    assert snap["tool"] == "newer"
    assert snap["running"] is True
    assert snap["error"] is None


def test_begin_discards_the_previous_run():
    progress.begin("first", total=1)
    progress.stage("a", 1, 1)
    progress.begin("second", total=2)
    snap = progress.snapshot()
    assert snap["tool"] == "second"
    assert snap["stage"] is None
    assert snap["index"] == 0
    assert snap["total"] == 2


def test_a_snapshot_is_a_copy():
    """The poll handler serialises this outside the lock; a live reference
    would let a concurrent stage update mutate a response mid-encode."""
    progress.begin("t", total=1)
    snap = progress.snapshot()
    snap["stage"] = "mutated"
    assert progress.snapshot()["stage"] is None


# ---------------------------------------------------------------------------
# enrich — the stage hook and its provenance
# ---------------------------------------------------------------------------

def test_log_stage_appends_one_entry_and_leaves_layer_empty():
    v = _log_stage(_violation(), "segments", 2)
    assert len(v.provenance) == 1
    entry = v.provenance[0]
    assert entry.operation == "enrich_violation:segments"
    assert entry.actor == "enrich.enrich_violation"
    assert entry.note == "2 item(s)"
    # Not one of the five canonical layers: claiming one would make the trail
    # lie about which layer function actually wrote the payload.
    assert entry.layer is None


def test_log_stage_is_append_only_and_keeps_the_order():
    v = _log_stage(_violation(), "segments", 1)
    v = _log_stage(v, "nexus", 0)
    assert _ops(v) == ["enrich_violation:segments", "enrich_violation:nexus"]
    assert v.provenance[1].note == "0 item(s)"


def test_log_stage_folds_a_note_into_the_count():
    v = _log_stage(_violation(), "authorities", 3, note="2 stubs unresolved")
    assert v.provenance[0].note == "3 item(s) — 2 stubs unresolved"


def test_log_stage_does_not_mutate_the_input():
    original = _violation()
    _log_stage(original, "segments", 1)
    assert original.provenance == []


def test_on_stage_fires_once_per_selected_stage_with_position_and_total():
    seen: list[tuple[str, int, int]] = []
    client = _FakeLLM({"segments": []})
    enrich_violation(
        _violation(),
        client=client,
        stages=["segments", "subsections"],
        on_stage=lambda *a: seen.append(a),
    )
    # `subsections` runs, has no established articles to tighten, calls nothing
    # — and is still announced.
    assert seen == [("segments", 1, 2), ("subsections", 2, 2)]


def test_progress_reports_the_stage_it_is_on_not_only_the_total():
    """The bound hook: this is the wiring `mcp_server` relies on."""
    progress.begin("enrich_violation_tool", total=2)
    client = _FakeLLM({"segments": []})
    enrich_violation(
        _violation(),
        client=client,
        stages=["segments", "subsections"],
        on_stage=progress.stage,
    )
    snap = progress.snapshot()
    assert snap["stage"] == "subsections"
    assert snap["index"] == 2
    assert snap["total"] == 2


def test_every_stage_that_ran_is_logged_even_when_it_produced_nothing():
    client = _FakeLLM(
        {"segments": [{"segment_id": "STG-1.seg-1", "role_in_argument": "r",
                       "translation_en": "x"}]}
    )
    v = enrich_violation(
        _violation(), client=client, stages=["segments", "subsections"]
    )
    assert _ops(v) == ["enrich_violation:segments", "enrich_violation:subsections"]
    # "ran and found nothing" and "never ran" are different facts; the panel
    # used to present the first as the second.
    assert [p.note for p in v.provenance] == ["1 item(s)", "0 item(s)"]


def test_a_failing_stage_is_announced_but_raises_labelled():
    """`on_stage` fires on entry; provenance only on success.

    Logging a crashed stage would put "0 item(s)" in the trail and the panel
    would read the stage as complete.
    """
    seen: list[tuple[str, int, int]] = []
    client = _FakeLLM(LLMError("model did not return valid JSON"))
    with pytest.raises(LLMError) as excinfo:
        enrich_violation(
            _violation(),
            client=client,
            stages=["segments"],
            on_stage=lambda *a: seen.append(a),
        )
    assert "enrichment stage 'segments'" in str(excinfo.value)
    assert seen == [("segments", 1, 1)]


def test_the_operation_strings_match_what_the_ui_filters_on():
    """The page keys on this exact prefix; the panel had zero runs forever
    because no operation string in the corpus contained "enrich"."""
    v = enrich_violation(_violation(), client=_FakeLLM({"segments": []}),
                         stages=["segments"])
    assert all(op.startswith("enrich_violation:") for op in _ops(v))
