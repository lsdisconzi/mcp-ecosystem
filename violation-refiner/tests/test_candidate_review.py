r"""Tests for reviewing candidate articles and applying a reviewer's decisions.

`CandidateArticle` exists so a plausible-but-unverified citation can be recorded
without contaminating `established_articles`, and the review files in
`data/candidate-reviews/` are where those citations get checked. This module pins
the two things that can go wrong between a review file and a bundle:

* **Reading a review that is not a data file.** The real files are prose with a
  markdown table buried in them, written by a different agent in whatever format
  it chose. Every trap below is one a real file springs: emphasis inside cells
  (`**Agent-fit fails.**`), an id written with an escaped underscore
  (``Art.269\_ter``), a *qualified* pass ("Correct provision, but limited agent
  class.") that reads as `correct` to any naive substring test, and a table that
  also lists the bundle's **established** articles. A parser that mishandles any
  of them still returns rows — the failure is silent, and the verdicts are wrong.

* **Writing an annotation twice.** Applying a review is not idempotent by nature:
  each apply appends to `history_note` and `verification_required`, so a second
  confirm of the same review would stack a duplicate note and a duplicate step.
  The idempotence test is the one that says a re-apply is a no-op, and it is also
  what keeps `apply_candidate_review` out of the provenance chronology when
  nothing changed — an audit trail that records no-ops is worse than none.

The structured cases are required rather than sampled where they encode a trap no
real file happens to isolate, and against the real review file where it exists
(it is a working artifact, not a tracked fixture — see `needs_review_file`).
No network: the generation path is driven with a fake client.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from violation_pack import candidate_review as cr
from violation_pack.models import CandidateArticle, Incident, ProvenanceEntry, Violation

REAL_REVIEW = cr.review_path("CL-030")
needs_review_file = pytest.mark.skipif(
    REAL_REVIEW is None or not REAL_REVIEW.is_file(),
    reason="data/candidate-reviews/CL-030.candidates.review.md is a working artifact, not a tracked fixture",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _candidate(aid: str, *, note: str | None = None, steps: list[str] | None = None) -> CandidateArticle:
    return CandidateArticle(
        candidate_article_id=aid,
        candidate_name=f"Article {aid.rsplit('.', 1)[-1]}",
        framework_cache_status="not_in_bundle",
        verification_required=steps if steps is not None else [f"Fetch verbatim text for {aid} from bcn.cl/leychile"],
        preliminary_view=None,
        history_note=note,
    )


def _violation(*candidates: CandidateArticle) -> Violation:
    return Violation(
        violation_id="CL-TEST",
        title="Test violation",
        severity="LOW",
        incident=Incident(date="2025-01-01", location="SCL"),
        candidate_articles=list(candidates),
    )


#: A review table that isolates every textual trap in one place. Stipulated, not
#: transcribed: the real files contain these shapes but never all of them in one
#: row, and each row here is the narrowest input that decides one branch.
TRAP_TABLE = """\
## Findings

Some prose above the table, which is not a row and must not be read as one.

| Candidate ID (from file) | Law / Code | Article | Description (from file) | Validation | Correction / Notes | BCN Link (Norm) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `CL.CPCL.C1.Art.269_ter` | Código Penal | Art. 269 ter | Keep a record | Correct provision, but limited agent class. | **Agent-fit is partial.** | [CP](https://www.bcn.cl/leychile/navigate?idNorma=1984) |
| `CL.CPCL.T4.Art.223` | Código Penal | Art. 223 | A theory | Incorrect / Not applicable | **Agent-fit fails.** Use Art. 223 instead. | [CP](https://www.bcn.cl/leychile/navigate?idNorma=1984) |
| `CL.LPDC.Art.23` | LPDC | Art. 23 | Established elsewhere | Correct | Nothing to do | |
| `CL.CPCL.T4.Art.224` | Código Penal | Art. 224 | A withdrawn theory | Withdrawn — superseded | Use Art. 223 instead | |

### Key Takeaways

- This list is after the table and must not become a row.
"""


# ---------------------------------------------------------------------------
# Locating and reading a review
# ---------------------------------------------------------------------------

def test_review_path_is_refused_for_an_id_that_could_escape_the_directory():
    """The id reaches a path, and it arrives from a browser.

    `data/candidate-reviews/../x.candidates.review.md` would read a file outside
    the review directory, and `..` is the one thing a bare-name allow-list has to
    exclude by itself — `_SAFE_ID_RE` also refuses a leading dot, a slash, and an
    empty string for the same reason.
    """
    for bad in ("..", "../secrets", "a/../../b", ".hidden", "", "with space"):
        assert cr.review_path(bad) is None, bad


def test_review_path_is_composed_from_the_id():
    path = cr.review_path("CL-030", root=Path("/tmp/reviews"))
    assert path == Path("/tmp/reviews/CL-030.candidates.review.md")


def test_read_review_returns_none_for_a_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv(cr.REVIEW_DIR_ENV_VAR, str(tmp_path))
    assert cr.read_review("CL-TEST") is None


def test_read_review_treats_an_empty_or_blank_file_as_absent(tmp_path, monkeypatch):
    """Measured: the CL-030 review existed at 0 bytes for a while.

    "The file is there, so trust it" would have meant proposing the empty change
    set that follows from an empty review — a button that reports success and
    does nothing — so an empty file has to read as "no ready-made review" and
    send the caller to generate one.
    """
    monkeypatch.setenv(cr.REVIEW_DIR_ENV_VAR, str(tmp_path))
    path = tmp_path / "CL-TEST.candidates.review.md"
    for content in ("", "   \n\n\t\n"):
        path.write_text(content, encoding="utf-8")
        assert cr.read_review("CL-TEST") is None, repr(content)


def test_read_review_returns_the_text_of_a_file_that_has_some(tmp_path, monkeypatch):
    monkeypatch.setenv(cr.REVIEW_DIR_ENV_VAR, str(tmp_path))
    (tmp_path / "CL-TEST.candidates.review.md").write_text(TRAP_TABLE, encoding="utf-8")
    assert cr.read_review("CL-TEST") == TRAP_TABLE


def test_find_reviews_dir_honours_the_env_override_only_when_it_is_a_directory(tmp_path, monkeypatch):
    monkeypatch.setenv(cr.REVIEW_DIR_ENV_VAR, str(tmp_path / "nope"))
    assert cr.find_reviews_dir() is None
    monkeypatch.setenv(cr.REVIEW_DIR_ENV_VAR, str(tmp_path))
    assert cr.find_reviews_dir() == tmp_path


def test_describe_path_is_relative_to_the_repository_root():
    """A review lives *outside* the bundle it is about, so the UI has to name it.

    An absolute path would put the machine's home directory into a log line and
    into the modal; every other path this project prints is workspace-relative.
    """
    described = cr.describe_path(Path(cr.__file__).resolve())
    assert not described.startswith("/"), described
    assert described.endswith("candidate_review.py")


# ---------------------------------------------------------------------------
# Parsing the table
# ---------------------------------------------------------------------------

def test_parse_review_table_reads_the_trap_table():
    rows = {row.candidate_article_id: row for row in cr.parse_review_table(TRAP_TABLE)}
    assert sorted(rows) == [
        "CL.CPCL.C1.Art.269_ter",
        "CL.CPCL.T4.Art.223",
        "CL.CPCL.T4.Art.224",
        "CL.LPDC.Art.23",
    ]
    # The prose above the table and the list below it are outside the body.
    assert len(rows) == 4


def test_parse_review_table_keeps_the_underscore_in_the_id():
    """``Art.269_ter`` is a key, not formatting.

    The real file writes the id in backticks and a markdown writer would escape
    it as ``269\\_ter``; the parser resolves the escape and unwraps the ticks, so
    the string that reaches the matcher is the one the bundle holds. An id that
    came back as `269ter` or `269\\_ter` would match no candidate at all, and the
    review would silently propose nothing.
    Note what is *not* asserted: that the id skips the prose flattener. It does
    not, and it need not — `_prose` only removes `*` and collapses whitespace,
    neither of which an article id contains. Routing the id through it is an
    equivalent mutation, so there is nothing here to guard.    """
    rows = cr.parse_review_table(TRAP_TABLE)
    assert any(row.candidate_article_id == "CL.CPCL.C1.Art.269_ter" for row in rows)

    escaped = TRAP_TABLE.replace("`CL.CPCL.C1.Art.269_ter`", "CL.CPCL.C1.Art.269\\_ter")
    assert any(
        row.candidate_article_id == "CL.CPCL.C1.Art.269_ter"
        for row in cr.parse_review_table(escaped)
    )


def test_parse_review_table_strips_emphasis_from_prose_cells_only():
    """`history_note` is prose, so `**Agent-fit fails.**` must lose its asterisks;
    the id must not lose its underscore. Same function, opposite treatment.

    The cell is emphasized *inside* a longer sentence on purpose. A cell whose
    whole body is `**...**` is already unwrapped by `_cell_text`, so a fixture
    like that would leave `_prose` — the thing this test exists to check —
    unexercised. Verified: neutering `_prose` turns this test red.
    """
    row = {r.candidate_article_id: r for r in cr.parse_review_table(TRAP_TABLE)}["CL.CPCL.T4.Art.223"]
    assert row.correction == "Agent-fit fails. Use Art. 223 instead."
    assert "*" not in row.correction
    assert row.candidate_article_id == "CL.CPCL.T4.Art.223"


def test_parse_review_table_returns_nothing_without_a_table():
    """A review that is pure prose is not a review with zero findings."""
    for text in ("", "no table here\n\njust words\n", "| not | a | table |\n| a | b | c |\n"):
        assert cr.parse_review_table(text) == [], repr(text)


def test_parse_review_table_requires_both_an_id_column_and_a_verdict_column():
    """Header-driven, so column order and extra columns do not matter — but a
    table missing the verdict column must not be read as a table of blanks: the
    caller would then propose "keep" for everything and call it a review.
    """
    no_verdict = """\
| Candidate ID | Law | Article | Notes |
| :--- | :--- | :--- | :--- |
| `CL.CPCL.T4.Art.223` | CP | 223 | something |
"""
    assert cr.parse_review_table(no_verdict) == []

    reordered = """\
| Validation | BCN Link | Candidate ID | Extra |
| :--- | :--- | :--- | :--- |
| Incorrect | http://x | `CL.CPCL.T4.Art.223` | ignored |
"""
    rows = cr.parse_review_table(reordered)
    assert [row.candidate_article_id for row in rows] == ["CL.CPCL.T4.Art.223"]
    assert rows[0].validation == "Incorrect"


def test_parse_review_table_skips_a_row_with_no_id():
    """A continuation row (an empty first cell) is not a candidate."""
    text = """\
| Candidate ID | Validation |
| :--- | :--- |
| `CL.CPCL.T4.Art.223` | Incorrect |
|  | a note that continues the row above |
"""
    assert [row.candidate_article_id for row in cr.parse_review_table(text)] == ["CL.CPCL.T4.Art.223"]


@pytest.mark.parametrize(
    "cell,expected",
    [
        ("Withdrawn", cr.VERDICT_WITHDRAWN),
        ("Withdrawn — superseded by Art. 223", cr.VERDICT_WITHDRAWN),
        ("Incorrect / Not applicable", cr.VERDICT_INCORRECT),
        ("Not applicable to this agent", cr.VERDICT_INCORRECT),
        ("Uncertain — needs the verbatim text", cr.VERDICT_UNCERTAIN),
        ("Unverified", cr.VERDICT_UNCERTAIN),
        ("Correct", cr.VERDICT_CORRECT),
        # The real CL-030 cell. Filed as `correct` it would mean "no change",
        # which is the opposite of what the reviewer wrote.
        ("Correct provision, but limited agent class.", cr.VERDICT_UNCERTAIN),
        ("Correct, however only for police officers", cr.VERDICT_UNCERTAIN),
        ("Correct for the DGAC but not for PDI", cr.VERDICT_UNCERTAIN),
        ("Maybe?", cr.VERDICT_UNKNOWN),
        ("", cr.VERDICT_NOT_REVIEWED),
        ("   ", cr.VERDICT_NOT_REVIEWED),
    ],
)
def test_classify_validation(cell, expected):
    assert cr.classify_validation(cell) == expected


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------

def test_proposals_iterate_the_candidates_not_the_rows():
    """Both directions of mismatch have to be visible.

    A row for an article this bundle holds as *established* (CL-030's review lists
    three) names no candidate and is dropped; a candidate no row covers is
    reported `not_reviewed` rather than quietly omitted, because "the review did
    not mention it" and "the review cleared it" are different facts.
    """
    violation = _violation(_candidate("CL.CPCL.T4.Art.223"), _candidate("CL.CPCL.T4.Art.999_zz"))
    rows = cr.parse_review_table(TRAP_TABLE)
    proposals = {p.candidate_article_id: p for p in cr.propose_changes(violation.candidate_articles, rows)}

    assert sorted(proposals) == ["CL.CPCL.T4.Art.223", "CL.CPCL.T4.Art.999_zz"]
    # `CL.LPDC.Art.23` is in the table and in no candidate list.
    assert "CL.LPDC.Art.23" not in proposals
    assert proposals["CL.CPCL.T4.Art.999_zz"].verdict == cr.VERDICT_NOT_REVIEWED
    assert proposals["CL.CPCL.T4.Art.999_zz"].action == "keep"


def test_a_proposal_for_a_candidate_with_no_steps_offers_a_real_change():
    """A candidate the analyst left with nothing to verify must still gain the
    step the review implies — otherwise the annotation is a note with no action
    attached, which is the failure mode the review exists to fix.
    """
    candidate = _candidate("CL.CPCL.C1.Art.269_ter", steps=[])
    proposals = cr.propose_changes([candidate], cr.parse_review_table(TRAP_TABLE))
    assert proposals[0].action == "annotate"
    assert proposals[0].changes["verification_required"]


def test_summarize_counts_verdicts_and_actions():
    violation = _violation(
        _candidate("CL.CPCL.T4.Art.223"),
        _candidate("CL.CPCL.T4.Art.224"),
        _candidate("CL.CPCL.C1.Art.269_ter"),
    )
    counts = cr.summarize(cr.propose_changes(violation.candidate_articles, cr.parse_review_table(TRAP_TABLE)))
    assert counts["candidates"] == 3
    assert counts[cr.VERDICT_INCORRECT] == 1
    assert counts[cr.VERDICT_WITHDRAWN] == 1
    assert counts[cr.VERDICT_UNCERTAIN] == 1
    assert counts["withdrawals"] == 2
    assert counts["annotations"] == 1


# ---------------------------------------------------------------------------
# Annotating
# ---------------------------------------------------------------------------

def test_annotate_changes_appends_the_note_and_the_step():
    candidate = _candidate("CL.CPCL.T4.Art.223", note="Legacy import candidate.")
    row = {r.candidate_article_id: r for r in cr.parse_review_table(TRAP_TABLE)}["CL.CPCL.T4.Art.223"]
    changes = cr.annotate_changes(candidate, row)
    assert changes["history_note"].startswith("Legacy import candidate.\n")
    assert cr.NOTE_MARKER in changes["history_note"]
    assert "Agent-fit fails." in changes["history_note"]
    assert len(changes["verification_required"]) == len(candidate.verification_required) + 1


def test_annotate_changes_is_idempotent():
    """Applying the same review twice must not stack two notes.

    `history_note` is the field a human reads, and the whole point of the
    candidate list is that it can be reviewed again later. A second identical
    note is not an audit trail, it is noise that hides the first one.
    """
    candidate = _candidate("CL.CPCL.T4.Art.223")
    row = {r.candidate_article_id: r for r in cr.parse_review_table(TRAP_TABLE)}["CL.CPCL.T4.Art.223"]
    once = candidate.model_copy(update=cr.annotate_changes(candidate, row))
    twice = once.model_copy(update=cr.annotate_changes(once, row))
    assert twice.history_note == once.history_note
    assert twice.verification_required == once.verification_required


def test_a_correct_verdict_adds_no_verification_step():
    """`correct` means the candidate's own steps already say how to establish it.
    A step that says "this is fine" is noise in the one list meant to be actionable.

    The note is still written when a reviewer overrides a `correct` candidate to
    `annotate`: the record should say the review looked at it. What must not
    happen is a verification step, which is the field a later reader acts on.
    """
    row = {r.candidate_article_id: r for r in cr.parse_review_table(TRAP_TABLE)}["CL.LPDC.Art.23"]
    assert row.verdict == cr.VERDICT_CORRECT
    assert cr.verification_step(row) is None
    changes = cr.annotate_changes(_candidate("CL.LPDC.Art.23"), row)
    assert "verification_required" not in changes
    assert changes["history_note"] == "Candidate review: Correct — Nothing to do"


# ---------------------------------------------------------------------------
# Applying decisions
# ---------------------------------------------------------------------------

_KEEP = {"candidate_article_id": "CL.CPCL.T4.Art.223", "action": "keep"}
_WITHDRAW = {"candidate_article_id": "CL.CPCL.T4.Art.223", "action": "withdraw"}
_ANNOTATE = {
    "candidate_article_id": "CL.CPCL.T4.Art.223",
    "action": "annotate",
    "validation": "Incorrect / Not applicable",
    "note": "Agent-fit fails.",
    "link": "[CP](https://www.bcn.cl/leychile/navigate?idNorma=1984)",
}


def test_apply_keeps_everything_and_reports_no_change():
    candidates = [_candidate("CL.CPCL.T4.Art.223")]
    kept, entry, counts = cr.apply_decisions(candidates, [_KEEP])
    assert [c.candidate_article_id for c in kept] == ["CL.CPCL.T4.Art.223"]
    assert kept[0] == candidates[0]
    # No provenance: an "apply" that applied nothing must not fill the chronology
    # with no-ops.
    assert entry is None
    assert counts == {"kept": 1, "annotated": 0, "withdrawn": 0}


def test_apply_with_no_decisions_at_all_changes_nothing():
    candidates = [_candidate("CL.CPCL.T4.Art.223"), _candidate("CL.CPCL.T4.Art.224")]
    kept, entry, counts = cr.apply_decisions(candidates, [])
    assert kept == candidates
    assert entry is None
    assert counts["kept"] == 2


def test_apply_withdraws_a_candidate():
    candidates = [_candidate("CL.CPCL.T4.Art.223"), _candidate("CL.CPCL.T4.Art.224")]
    kept, entry, counts = cr.apply_decisions(candidates, [_WITHDRAW])
    assert [c.candidate_article_id for c in kept] == ["CL.CPCL.T4.Art.224"]
    assert counts == {"kept": 1, "annotated": 0, "withdrawn": 1}
    assert entry is not None
    assert entry.operation == "apply_candidate_review"
    assert entry.actor == "legal_audit_human"
    assert "1 withdrawn (of 2 recorded)" in entry.note


def test_apply_annotates_from_the_reviewers_own_wording():
    candidates = [_candidate("CL.CPCL.T4.Art.223", steps=[])]
    kept, entry, counts = cr.apply_decisions(candidates, [_ANNOTATE])
    assert counts == {"kept": 0, "annotated": 1, "withdrawn": 0}
    assert "Incorrect / Not applicable" in kept[0].history_note
    assert "Agent-fit fails." in kept[0].history_note
    assert kept[0].verification_required
    assert entry is not None and "1 candidate(s) annotated" in entry.note


def test_apply_reads_the_verdict_from_a_verdict_key_too():
    """The UI sends `validation`; a hand-written decision may send `verdict`."""
    candidates = [_candidate("CL.CPCL.T4.Art.223", steps=[])]
    kept, _, counts = cr.apply_decisions(
        candidates,
        [{"candidate_article_id": "CL.CPCL.T4.Art.223", "action": "annotate", "verdict": "Uncertain"}],
    )
    assert counts["annotated"] == 1
    assert "Uncertain" in kept[0].history_note


def test_reapplying_a_review_that_already_landed_is_a_no_op():
    """The confirm button can be reached twice, and the second time must cost
    nothing: not a duplicate note, and not a provenance entry claiming an edit
    that did not happen.
    """
    candidates = [_candidate("CL.CPCL.T4.Art.223", steps=[])]
    once, first_entry, _ = cr.apply_decisions(candidates, [_ANNOTATE])
    assert first_entry is not None

    twice, second_entry, counts = cr.apply_decisions(once, [_ANNOTATE])
    assert twice == once
    assert counts == {"kept": 1, "annotated": 0, "withdrawn": 0}
    assert second_entry is None, "a re-apply of the same review must not append to the chronology"


def test_apply_refuses_an_id_the_bundle_does_not_hold():
    """A typo that quietly applied nothing would look exactly like a decision
    already in place, which is the one outcome a reviewer cannot detect.
    """
    with pytest.raises(ValueError, match="no candidate"):
        cr.apply_decisions([_candidate("CL.CPCL.T4.Art.223")], [
            {"candidate_article_id": "CL.CPCL.T4.Art.224", "action": "withdraw"},
        ])


def test_apply_refuses_an_action_outside_the_closed_set():
    with pytest.raises(ValueError, match="not one of"):
        cr.apply_decisions([_candidate("CL.CPCL.T4.Art.223")], [
            {"candidate_article_id": "CL.CPCL.T4.Art.223", "action": "delete"},
        ])


def test_apply_refuses_the_same_candidate_decided_twice():
    with pytest.raises(ValueError, match="decided twice"):
        cr.apply_decisions([_candidate("CL.CPCL.T4.Art.223")], [_KEEP, _WITHDRAW])


def test_apply_refuses_a_non_string_decision_text():
    """The decisions arrive as JSON from a browser and land in a string field of
    a persisted model, so a list or a dict must be refused here rather than turn
    a later `model_validate` into a crash the reviewer cannot act on.
    """
    with pytest.raises(ValueError, match="must be a string"):
        cr.apply_decisions([_candidate("CL.CPCL.T4.Art.223")], [
            {"candidate_article_id": "CL.CPCL.T4.Art.223", "action": "annotate", "validation": ["a", "b"]},
        ])


def test_apply_never_touches_the_established_articles():
    """The separation `CandidateArticle` exists for: a review of the candidates
    may not promote one, because promotion means carrying a byte-exact excerpt
    verified separately.
    """
    violation = _violation(_candidate("CL.CPCL.T4.Art.223"))
    candidates, entry, _ = cr.apply_decisions(violation.candidate_articles, [_WITHDRAW])
    updated = cr.with_provenance(violation.model_copy(update={"candidate_articles": candidates}), entry)
    assert updated.established_articles == violation.established_articles == []
    assert updated.candidate_articles == []


def test_with_provenance_appends_exactly_one_entry():
    violation = _violation(_candidate("CL.CPCL.T4.Art.223"))
    entry = ProvenanceEntry(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        actor="legal_audit_human",
        operation="apply_candidate_review",
        layer=2,
        note="n",
    )
    after = cr.with_provenance(violation, entry)
    assert after.provenance == [entry]
    assert violation.provenance == [], "the input must not be mutated in place"


def test_with_provenance_with_no_entry_leaves_the_violation_alone():
    violation = _violation(_candidate("CL.CPCL.T4.Art.223"))
    assert cr.with_provenance(violation, None) == violation


# ---------------------------------------------------------------------------
# Generating a review when there is no file
# ---------------------------------------------------------------------------

class _FakeLLM:
    """Returns one canned response and records the call it was given."""

    def __init__(self, response: Any):
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def chat_json(self, *, messages, system=None, max_tokens=None):
        self.calls.append({"messages": messages, "system": system, "max_tokens": max_tokens})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_generate_review_returns_rows_and_an_intro():
    client = _FakeLLM({
        "intro": "Six citations were checked.",
        "candidates": [
            {"candidate_article_id": "CL.CPCL.T4.Art.223", "law_code": "Código Penal",
             "article": "223", "description": "d", "validation": "Incorrect",
             "correction": "**fails**", "link": "https://www.bcn.cl/leychile"},
        ],
    })
    rows, intro = cr.generate_review(_violation(_candidate("CL.CPCL.T4.Art.223")), client)
    assert intro == "Six citations were checked."
    assert [row.candidate_article_id for row in rows] == ["CL.CPCL.T4.Art.223"]
    # Generation goes through the same prose normalisation as parsing, so a
    # generated review cannot introduce emphasis the ready-made files are spared.
    assert rows[0].correction == "fails"
    assert client.calls[0]["system"] == cr._REVIEW_SYSTEM_PROMPT


def test_generate_review_states_the_candidates_it_expects_reviewed():
    client = _FakeLLM({"candidates": []})
    cr.generate_review(_violation(_candidate("CL.CPCL.T4.Art.223")), client)
    prompt = client.calls[0]["messages"][0]["content"]
    assert "CL.CPCL.T4.Art.223" in prompt


def test_the_system_prompt_forbids_inventing_source_text():
    """The model has no web access, so the only honest verdict for a candidate
    whose text it cannot see is "uncertain, fetch it". The failure this prevents
    is measured: an earlier stage invented `Art. 497` as "denegación de auxilio".
    """
    prompt = cr._REVIEW_SYSTEM_PROMPT.lower()
    assert "never invent" in prompt
    assert "no access to the internet" in prompt


def test_rows_from_response_skips_entries_without_an_id():
    rows = cr.rows_from_response({"candidates": [
        {"candidate_article_id": "", "validation": "Correct"},
        {"validation": "Correct"},
        "not an object",
        {"candidate_article_id": "CL.CPCL.T4.Art.223", "validation": "Correct"},
    ]})
    assert [row.candidate_article_id for row in rows] == ["CL.CPCL.T4.Art.223"]


def test_render_review_markdown_round_trips_through_the_parser():
    """A generated review is only useful if the parser reads it back as the rows
    it came from — that is what makes it droppable into `data/candidate-reviews/`.
    """
    original = cr.parse_review_table(TRAP_TABLE)
    rendered = cr.render_review_markdown(original, intro="Generated, not signed off.", heading="Validation Table")
    again = cr.parse_review_table(rendered)
    assert again == original


def test_render_review_markdown_escapes_a_pipe_inside_a_cell():
    rows = [cr.ReviewRow(
        candidate_article_id="CL.CPCL.T4.Art.223",
        validation="a | b",
        correction="x | y",
    )]
    again = cr.parse_review_table(cr.render_review_markdown(rows))
    assert again[0].validation == "a | b"
    assert again[0].correction == "x | y"


# ---------------------------------------------------------------------------
# Against the real review (skipped when the artifact is absent)
# ---------------------------------------------------------------------------

@needs_review_file
def test_the_real_cl030_review_parses_to_its_six_rows():
    rows = cr.parse_review_table(cr.read_review("CL-030"))
    assert len(rows) == 6
    by_id = {row.candidate_article_id: row for row in rows}
    assert set(by_id) >= {
        "CL.CPCL.T4.Art.255", "CL.LPDC.Art.3.b", "CL.LPDC.Art.23",
        "CL.CPCL.T4.Art.223", "CL.CPCL.T4.Art.224", "CL.CPCL.C1.Art.269_ter",
    }
    # The qualified pass is the one classification a substring test gets wrong.
    assert by_id["CL.CPCL.C1.Art.269_ter"].verdict == cr.VERDICT_UNCERTAIN
    assert by_id["CL.CPCL.T4.Art.223"].verdict == cr.VERDICT_INCORRECT
    assert by_id["CL.CPCL.T4.Art.224"].verdict == cr.VERDICT_INCORRECT
    assert by_id["CL.CPCL.T4.Art.255"].verdict == cr.VERDICT_CORRECT


@needs_review_file
def test_the_real_cl030_review_proposes_withdrawals_and_one_annotation():
    violation = _violation(
        _candidate("CL.CPCL.T4.Art.223"),
        _candidate("CL.CPCL.T4.Art.224"),
        _candidate("CL.CPCL.C1.Art.269_ter"),
    )
    proposals = cr.propose_changes(violation.candidate_articles, cr.parse_review_table(cr.read_review("CL-030")))
    actions = {p.candidate_article_id: p.action for p in proposals}
    assert actions == {
        "CL.CPCL.T4.Art.223": "withdraw",
        "CL.CPCL.T4.Art.224": "withdraw",
        "CL.CPCL.C1.Art.269_ter": "annotate",
    }
    # The three established articles in the same table are not proposals.
    assert len(proposals) == 3


@needs_review_file
def test_the_real_review_survives_a_render_and_parse_round_trip():
    original = cr.parse_review_table(cr.read_review("CL-030"))
    assert cr.parse_review_table(cr.render_review_markdown(original)) == original


@needs_review_file
def test_the_real_review_leaves_no_markdown_in_the_note_it_writes():
    """`history_note` is prose a human reads in the bundle. The real table cell
    is `**Agent-fit fails.** …` and the asterisks must not survive into it.
    """
    row = {r.candidate_article_id: r for r in cr.parse_review_table(cr.read_review("CL-030"))}
    for candidate in (
        "CL.CPCL.T4.Art.223", "CL.CPCL.T4.Art.224", "CL.CPCL.C1.Art.269_ter",
    ):
        note = cr.review_note(row[candidate])
        assert "**" not in note, note
        assert len(note) <= cr._MAX_NOTE
