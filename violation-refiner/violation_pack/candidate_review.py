"""Review every candidate article, then propose per-candidate changes.

Candidates are the one part of a bundle that is *meant* to be wrong sometimes.
`models.CandidateArticle` exists precisely so a plausible-but-unverified article
can be recorded without contaminating `established_articles`, and the LLM
`candidates` stage writes each one with `framework_cache_status="not_in_bundle"`
as a standing invitation to go and check it.

This module answers that invitation in the shape this project already uses:

    data/candidate-reviews/<violation_id>.candidates.review.md

Those files are written by a reviewing agent that has BCN access, and they carry
their findings in a markdown table with fixed columns:

    Candidate ID (from file) | Law / Code | Article | Description (from file)
    | Validation | Correction / Notes | BCN Link (Norm)

So a review can arrive two ways, and both end in the same rows:

* **ready-made** — the file exists, so it is *parsed*. That file is the one a
  reviewer signed off on; re-running a model over it could only replace a
  checked verdict with a guess. It wins whenever it carries a usable table.
* **generated** — there is no file, so the model is asked for those same columns
  as JSON and :func:`render_review_markdown` rebuilds the file's own structure
  from what it returns. Nothing is written to `data/`: a generated review is a
  proposal, and promoting it to the review *of record* is a deliberate act
  (copy it into `data/candidate-reviews/`), not a side effect of a button.

Nothing here writes to a bundle. A review yields *proposals*; applying them is a
separate step driven by a reviewer's decisions (:func:`apply_decisions`), and
even that only returns an updated ``Violation`` — `write_violation_json_tool`
stays the only writer, exactly as it is for every other layer.

Three judgement calls are worth stating, because each one is a trap the real
files spring:

* **The table is the contract, not the prose.** CL-030's review opens with two
  paragraphs of findings and closes with a "Key Takeaways" list, and neither can
  be keyed on. Only the table rows carry an id.
* **The table also names established articles.** CL-030's review covers three
  established and three candidate articles in one table, and CL-005's mixes
  `CL.LPDC.Art.23` (established) with its candidates. A row is therefore matched
  against the bundle's *own* candidate list, never trusted on its own: a row for
  an article the bundle does not hold as a candidate is dropped, and a candidate
  no row covers is reported `not_reviewed` rather than quietly left alone.
* **Cell emphasis is markdown, and ids contain underscores.** The files write
  `` `CL.CPCL.C1.Art.269_ter` `` and ``**Correct**``, and markdown escaping turns
  that id into `269\\_ter` depending on the writer. Both are unwrapped by
  :func:`_split_row` / :func:`_cell_text`, so the key that reaches the matcher is
  the same string the bundle holds.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .models import CandidateArticle, ProvenanceEntry, Violation

#: Override the review directory (mainly for tests).
REVIEW_DIR_ENV_VAR = "VR_CANDIDATE_REVIEWS"

_REVIEWS_RELATIVE = ("data", "candidate-reviews")

#: The filename convention the ready-made reviews already use.
REVIEW_SUFFIX = ".candidates.review.md"

#: A bare bundle id: no separator, no ``..``. The same *safety* shape as
#: ``ui_server._BUNDLE_DIR_RE`` (a bare-name test, deliberately not a membership
#: test), repeated here because this module composes a path out of the id and
#: must not import the browser bridge to do it.
_SAFE_ID_RE = re.compile(r"(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9._-]*")

#: Table columns -> our field names. The header text is normalised (lowercased,
#: emphasis and parentheticals stripped, ``_`` read as a space) before lookup, so
#: ``**Candidate ID (from file)**`` and ``Candidate_ID`` both land here.
_COLUMNS = {
    "candidate id": "candidate_article_id",
    "candidate article id": "candidate_article_id",
    "candidate": "candidate_article_id",
    "law code": "law_code",
    "law": "law_code",
    "code": "law_code",
    "article": "article",
    "description": "description",
    "validation": "validation",
    "verdict": "validation",
    "correction notes": "correction",
    "correction": "correction",
    "notes": "correction",
    "bcn link norm": "link",
    "bcn link": "link",
    "link": "link",
}

#: Verdicts, most severe first. Order is load-bearing: a cell reading
#: "Incorrect / Not applicable" contains neither of the other keywords, but
#: "Correct provision, but limited agent class" contains *correct* and must not
#: be filed as a pass (see :func:`classify_validation`).
VERDICT_WITHDRAWN = "withdrawn"
VERDICT_INCORRECT = "incorrect"
VERDICT_UNCERTAIN = "uncertain"
VERDICT_CORRECT = "correct"
VERDICT_UNKNOWN = "unknown"
VERDICT_NOT_REVIEWED = "not_reviewed"

# ---------------------------------------------------------------------------
# Where the ready-made reviews live
# ---------------------------------------------------------------------------

def find_reviews_dir() -> Path | None:
    """Locate ``data/candidate-reviews/``, or ``None`` when it does not exist.

    Honours ``$VR_CANDIDATE_REVIEWS`` first, then walks up from this file. The
    walk-up is written out here rather than imported from ``ui_server`` for the
    same reason ``law_registry.find_registry_path`` writes its own: a domain
    module should not have to import the browser bridge to find its data.
    """
    override = os.environ.get(REVIEW_DIR_ENV_VAR)
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_dir() else None

    for base in Path(__file__).resolve().parent.parents:
        candidate = base.joinpath(*_REVIEWS_RELATIVE)
        if candidate.is_dir():
            return candidate
    return None


def review_path(violation_id: str, root: Path | str | None = None) -> Path | None:
    """``<reviews>/<violation_id>.candidates.review.md``, or ``None``.

    ``None`` means the path *could not be composed* — an unsafe id, or no
    ``data/candidate-reviews/`` anywhere up the tree. The file not existing is
    not a failure and does not come back as ``None``: the caller decides whether
    a missing review means "generate one" or "report it".
    """
    if not _SAFE_ID_RE.fullmatch(violation_id or ""):
        return None
    directory = Path(root) if root is not None else find_reviews_dir()
    if directory is None:
        return None
    return directory / f"{violation_id}{REVIEW_SUFFIX}"


def describe_path(path: Path) -> str:
    """Report a path relative to the repository root when it is inside it.

    A review is *about* a bundle but lives outside it, so the UI has to name a
    file the reviewer can go and open. An absolute path would leak the machine's
    home directory into the UI and the log; a workspace-relative one is the form
    every other path in this project's messages takes.
    """
    for base in Path(__file__).resolve().parent.parents:
        try:
            return str(path.relative_to(base))
        except ValueError:
            continue
    return str(path)


def read_review(violation_id: str, root: Path | str | None = None) -> str | None:
    """The ready-made review's text, or ``None`` when there is nothing to read.

    An **empty** file is treated as absent, not as an empty review. Measured:
    ``data/candidate-reviews/CL-030.candidates.review.md`` existed at 0 bytes
    for a while, and "the file is there, so trust it" would have meant reviewing
    a bundle against nothing at all and proposing the empty change set that
    follows. A file with whitespace in it is the same thing wearing a hat.
    """
    path = review_path(violation_id, root)
    if path is None or not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return text if text.strip() else None


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReviewRow:
    """One row of a validation table, as read.

    ``validation`` keeps the reviewer's own words ("Correct provision, but
    limited agent class.") because that sentence is what the UI shows and what
    the annotation quotes. ``verdict`` is the classification derived from it.
    """

    candidate_article_id: str
    law_code: str = ""
    article: str = ""
    description: str = ""
    validation: str = ""
    correction: str = ""
    link: str = ""

    @property
    def verdict(self) -> str:
        return classify_validation(self.validation)

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_article_id": self.candidate_article_id,
            "law_code": self.law_code,
            "article": self.article,
            "description": self.description,
            "validation": self.validation,
            "verdict": self.verdict,
            "correction": self.correction,
            "link": self.link,
        }


def _normalize_header(cell: str) -> str:
    """Fold a header cell down to its lookup key.

    Emphasis markers, backticks, parentheticals and a trailing colon all get
    dropped: the real files write ``Candidate ID (from file)``, ``**Validation**``
    and ``BCN Link (Norm)``, and all three have to resolve.
    """
    text = (cell or "").replace("*", " ").replace("`", " ")
    text = re.sub(r"\(.*?\)", " ", text)
    text = re.sub(r"[_/]+", " ", text)
    text = re.sub(r"[^A-Za-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _split_row(line: str) -> list[str]:
    """Split one pipe row into cells, honouring backslash escapes.

    Splitting on ``"|"`` alone would tear a cell containing an escaped pipe in
    two, and would leave the escape on an id (``Art.269\\_ter``) — which is the
    exact string the bundle does *not* hold, so the row would then fail to match
    its own candidate. Escapes are resolved here, once, on the way in.
    """
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]

    cells: list[str] = []
    buffer: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            buffer.append(text[index + 1])
            index += 2
            continue
        if char == "|":
            cells.append("".join(buffer))
            buffer = []
            index += 1
            continue
        buffer.append(char)
        index += 1
    cells.append("".join(buffer))
    return cells


def _cell_text(cell: str) -> str:
    """Unwrap a cell's markdown emphasis and code ticks, keep the words."""
    text = (cell or "").strip()
    # Both `**Correct**` and `` `CL.CPCL.T4.Art.255` `` appear in the real
    # files; a pair of markers is stripped repeatedly so `**x**` resolves to `x`.
    while len(text) >= 2 and text[0] == text[-1] and text[0] in "*_`":
        text = text[1:-1].strip()
    return text


def _prose(text: str) -> str:
    """Flatten a prose cell for a model field.

    Only the *free-text* cells (description, validation, correction) go through
    this: the real reviews emphasise phrases inside them (``**Agent-fit
    fails.**``) and those asterisks would land in `history_note`, which is
    prose. An id never passes through here — a stray underscore in
    ``Art.269_ter`` is part of the key, not formatting.
    """
    return " ".join((text or "").replace("*", "").split())


def _is_separator_row(cells: Sequence[str]) -> bool:
    """True for the ``| :--- | :--- |`` line under a markdown table header."""
    filled = [cell.strip() for cell in cells if cell.strip()]
    if not filled:
        return True
    return all(re.fullmatch(r":?-{2,}:?", cell) is not None for cell in filled)


def parse_review_table(markdown: str) -> list[ReviewRow]:
    """Parse the validation table out of a review's markdown, or return ``[]``.

    Header-driven, and tolerant about everything except the two columns this
    module cannot work without: an id, and a verdict. Column *order* therefore
    does not matter, an extra column is ignored, and a table missing either
    required column is reported as no table at all — because proposing changes
    from a table whose verdict column was not recognised would mean proposing
    whatever the correction text happened to look like.
    """
    lines = (markdown or "").splitlines()
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped.startswith("|"):
            continue
        header = _split_row(stripped)
        mapping: dict[int, str] = {}
        for position, cell in enumerate(header):
            name = _COLUMNS.get(_normalize_header(cell))
            if name and name not in mapping.values():
                mapping[position] = name
        if "candidate_article_id" not in mapping.values() or "validation" not in mapping.values():
            continue

        rows: list[ReviewRow] = []
        for row_line in lines[index + 1:]:
            # The separator is the first body line; a body stops at the first
            # line that is not a row. Both the prose above the table and the
            # "Key Takeaways" list below it are therefore skipped by structure
            # rather than by matching their text.
            if not row_line.lstrip().startswith("|"):
                break
            cells = _split_row(row_line)
            if _is_separator_row(cells):
                continue
            values = {
                mapping[position]: _cell_text(cell)
                for position, cell in enumerate(cells)
                if position in mapping
            }
            candidate_id = values.get("candidate_article_id", "").strip()
            if not candidate_id:
                continue
            rows.append(
                ReviewRow(
                    candidate_article_id=candidate_id,
                    law_code=values.get("law_code", ""),
                    article=values.get("article", ""),
                    description=_prose(values.get("description", "")),
                    validation=_prose(values.get("validation", "")),
                    correction=_prose(values.get("correction", "")),
                    link=values.get("link", ""),
                )
            )
        return rows
    return []


def classify_validation(text: str) -> str:
    """Classify one ``Validation`` cell into a verdict.

    The two traps are both real cells in the reviewed files:

    * ``Incorrect / Not applicable`` (CL-030, Art. 223) — a candidate whose cited
      provision does not cover the conduct at all.
    * ``Correct provision, but limited agent class.`` (CL-030, Art. 269_ter) — a
      *qualified* pass. Read as ``correct`` it would be filed as "no change",
      which is the opposite of what the reviewer wrote, so a qualifier ("but",
      "partial", "only", ...) demotes it to ``uncertain``.
    """
    normalized = re.sub(r"[^a-z ]+", " ", (text or "").lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return VERDICT_NOT_REVIEWED
    if "withdraw" in normalized:
        return VERDICT_WITHDRAWN
    if "incorrect" in normalized or "not applicable" in normalized:
        return VERDICT_INCORRECT
    if "uncertain" in normalized or "unverified" in normalized or "unclear" in normalized:
        return VERDICT_UNCERTAIN
    if "correct" in normalized:
        if re.search(r"\b(but|however|partial|partly|limited|only|except|unless)\b", normalized):
            return VERDICT_UNCERTAIN
        return VERDICT_CORRECT
    return VERDICT_UNKNOWN


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------

#: Marker every generated annotation carries, so a re-review can tell its own
#: earlier note from a human's and not stack a second copy.
NOTE_MARKER = "Candidate review:"

_MAX_NOTE = 600
_MAX_STEP = 300


@dataclass(frozen=True)
class CandidateProposal:
    """What a review suggests for one candidate.

    ``action`` is a *recommendation*; the reviewer picks. ``changes`` is the
    annotate payload computed from the same helpers :func:`apply_decisions`
    uses, so the preview in the UI and the applied edit cannot disagree.
    """

    candidate_article_id: str
    candidate_name: str
    verdict: str
    validation: str
    correction: str
    link: str
    action: str
    reason: str
    changes: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_article_id": self.candidate_article_id,
            "candidate_name": self.candidate_name,
            "verdict": self.verdict,
            "validation": self.validation,
            "correction": self.correction,
            "link": self.link,
            "action": self.action,
            "reason": self.reason,
            "changes": self.changes,
        }


def _trim(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def review_note(row: ReviewRow) -> str:
    """The sentence written into ``history_note`` for one reviewed candidate.

    Deliberately free of a timestamp: ``history_note`` is a string field with no
    separate date, and stamping it with "today" would make the annotation
    different on every re-review, so the idempotence check below could never
    recognise its own earlier note. The date lives in the provenance entry that
    applying a decision appends — which is what a provenance list is for.
    """
    parts = [f"{NOTE_MARKER} {row.validation or 'no verdict recorded'}"]
    if row.correction:
        parts.append(row.correction)
    note = " — ".join(part for part in parts if part)
    if row.link:
        note = f"{note} ({row.link})"
    return _trim(note, _MAX_NOTE)


def verification_step(row: ReviewRow) -> str | None:
    """The ``verification_required`` step a verdict implies, or ``None``.

    A ``correct`` verdict adds nothing: the candidate's existing steps already
    say how to flip it to established, and a step that says "this is fine" would
    be noise in the one list meant to be actionable.
    """
    verdict = row.verdict
    if verdict == VERDICT_CORRECT or verdict == VERDICT_NOT_REVIEWED:
        return None
    detail = row.correction or row.validation
    if verdict == VERDICT_WITHDRAWN:
        prefix = "Kept for the record only — the candidate review withdrew this citation:"
    elif verdict == VERDICT_INCORRECT:
        prefix = "Do not rely on this citation as recorded — the candidate review found it inapplicable:"
    else:
        prefix = "Resolve before relying on this candidate — the candidate review left it open:"
    return _trim(f"{prefix} {detail}", _MAX_STEP)


def _append_line(existing: str | None, line: str) -> str:
    """Append ``line`` unless it is already there (verbatim)."""
    current = (existing or "").strip()
    if not current:
        return line
    if line in current:
        return current
    return f"{current}\n{line}"


def _append_step(existing: Iterable[str], step: str) -> list[str]:
    steps = [str(item) for item in existing]
    if step not in steps:
        steps.append(step)
    return steps


def annotate_changes(candidate: CandidateArticle, row: ReviewRow) -> dict[str, Any]:
    """The field edits an ``annotate`` decision makes to one candidate.

    Only two fields, both of them lists-of-words/addenda: the appended note and
    the appended verification step. ``candidate_name`` and ``preliminary_view``
    are left alone because the review table carries no proposed replacement for
    either — inventing one here would be this module editing the analyst's
    prose. A candidate whose citation is simply wrong is a *withdrawal*.
    """
    changes: dict[str, Any] = {}
    note = review_note(row)
    if note:
        changes["history_note"] = _append_line(candidate.history_note, note)
    step = verification_step(row)
    if step:
        changes["verification_required"] = _append_step(candidate.verification_required, step)
    return changes


def _recommendation(verdict: str) -> tuple[str, str]:
    """``(action, reason)`` for one verdict."""
    if verdict == VERDICT_CORRECT:
        return "keep", "the review confirms this citation as recorded"
    if verdict == VERDICT_INCORRECT:
        return "withdraw", "the review found the cited provision inapplicable"
    if verdict == VERDICT_WITHDRAWN:
        return "withdraw", "the review withdrew this citation"
    if verdict == VERDICT_UNCERTAIN:
        return "annotate", "the review left this candidate open"
    if verdict == VERDICT_NOT_REVIEWED:
        return "keep", "the review carries no row for this candidate"
    return "keep", "the review's verdict was not recognised"


def propose_changes(
    candidates: Sequence[CandidateArticle],
    rows: Sequence[ReviewRow],
) -> list[CandidateProposal]:
    """One proposal per candidate, in the bundle's own order.

    Iterating the *candidates* (not the rows) is what makes a missing row and a
    stray row both visible: every candidate the bundle holds gets a proposal, so
    an unreviewed one is reported as such instead of silently disappearing, and
    a row for an article this bundle holds as *established* — CL-030's review
    lists Art. 255 and two LPDC articles, all established — is dropped, because
    it names no candidate to change.
    """
    by_id = {row.candidate_article_id: row for row in rows}
    proposals: list[CandidateProposal] = []
    for candidate in candidates:
        row = by_id.get(candidate.candidate_article_id)
        if row is None:
            action, reason = _recommendation(VERDICT_NOT_REVIEWED)
            proposals.append(
                CandidateProposal(
                    candidate_article_id=candidate.candidate_article_id,
                    candidate_name=candidate.candidate_name,
                    verdict=VERDICT_NOT_REVIEWED,
                    validation="",
                    correction="",
                    link="",
                    action=action,
                    reason=reason,
                    changes={},
                )
            )
            continue
        verdict = row.verdict
        action, reason = _recommendation(verdict)
        proposals.append(
            CandidateProposal(
                candidate_article_id=candidate.candidate_article_id,
                candidate_name=candidate.candidate_name,
                verdict=verdict,
                validation=row.validation,
                correction=row.correction,
                link=row.link,
                action=action,
                reason=reason,
                changes=annotate_changes(candidate, row),
            )
        )
    return proposals


def summarize(proposals: Sequence[CandidateProposal]) -> dict[str, int]:
    """Counts for the UI header and the log line."""
    counts = {
        "candidates": len(proposals),
        "correct": 0,
        VERDICT_INCORRECT: 0,
        VERDICT_UNCERTAIN: 0,
        VERDICT_WITHDRAWN: 0,
        VERDICT_UNKNOWN: 0,
        VERDICT_NOT_REVIEWED: 0,
        "withdrawals": 0,
        "annotations": 0,
    }
    for proposal in proposals:
        counts[proposal.verdict] = counts.get(proposal.verdict, 0) + 1
        if proposal.action == "withdraw":
            counts["withdrawals"] += 1
        elif proposal.action == "annotate":
            counts["annotations"] += 1
    return counts


# ---------------------------------------------------------------------------
# Applying a reviewer's decisions
# ---------------------------------------------------------------------------

def _safe_text(value: Any, limit: int) -> str:
    """Coerce a caller-supplied string, or refuse it.

    Every value that reaches a field of the Violation travels through here.
    The decisions arrive as JSON from a browser, and the tool that takes them is
    a write path; a non-string (a list, ``None``, a dict) must not be able to
    reach ``history_note`` and turn a later ``model_validate`` into a crash the
    reviewer cannot act on.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("decision text must be a string")
    return _trim(value, limit)


def apply_decisions(
    candidates: Sequence[CandidateArticle],
    decisions: Sequence[Mapping[str, Any]],
    *,
    actor: str = "legal_audit_human",
    when: datetime | None = None,
) -> tuple[list[CandidateArticle], ProvenanceEntry | None, dict[str, int]]:
    """Return the candidate list a reviewer's decisions produce.

    Returns ``(candidates, provenance, counts)``. The provenance entry is
    ``None`` when nothing changed — an "apply" that applied nothing must not
    append to the chronology, or the audit trail fills with no-ops.

    A decision names an ``action`` from a closed set:

    * ``keep`` — untouched;
    * ``annotate`` — the review's note (and, for a verdict that is not a pass,
      its verification step) appended to the candidate;
    * ``withdraw`` — the candidate is dropped from ``candidate_articles``.

    The decision carries the reviewer's own ``verdict``/``note``/``link`` rather
    than a field map, so the *shape* of an edit is decided here, by the same
    helpers that built the preview — a browser can choose what to do, but not
    what fields exist. An id the bundle does not hold, or an action outside the
    set, is an error rather than a silent skip: a typo that quietly applied
    nothing would look exactly like a decision that was already in place.
    """
    when = when or datetime.now(timezone.utc)
    total = len(list(candidates))
    allowed_actions = {"keep", "annotate", "withdraw"}
    by_id = {candidate.candidate_article_id: candidate for candidate in candidates}

    planned: dict[str, Mapping[str, Any]] = {}
    for decision in decisions or []:
        if not isinstance(decision, Mapping):
            raise ValueError("every decision must be an object")
        candidate_id = decision.get("candidate_article_id")
        if not isinstance(candidate_id, str) or candidate_id not in by_id:
            raise ValueError(f"no candidate {candidate_id!r} in this violation")
        action = decision.get("action", "keep")
        if action not in allowed_actions:
            raise ValueError(
                f"action {action!r} is not one of {sorted(allowed_actions)}"
            )
        if candidate_id in planned:
            raise ValueError(f"candidate {candidate_id!r} was decided twice")
        planned[candidate_id] = decision

    kept: list[CandidateArticle] = []
    counts = {"kept": 0, "annotated": 0, "withdrawn": 0}
    for candidate in candidates:
        decision = planned.get(candidate.candidate_article_id)
        action = (decision or {}).get("action", "keep")
        if action == "withdraw":
            counts["withdrawn"] += 1
            continue
        if action != "annotate":
            counts["kept"] += 1
            kept.append(candidate)
            continue

        # The reviewer's own verdict wording travels back, not the classification:
        # `annotate_changes` re-derives the verdict from the text, and the note it
        # writes quotes that text verbatim. A classification alone would lose the
        # sentence the reviewer actually read and approved.
        validation = _safe_text(decision.get("validation"), _MAX_NOTE) or _safe_text(
            decision.get("verdict"), _MAX_NOTE
        )
        row = ReviewRow(
            candidate_article_id=candidate.candidate_article_id,
            validation=validation,
            correction=_safe_text(decision.get("note"), _MAX_NOTE),
            link=_safe_text(decision.get("link"), _MAX_NOTE),
        )
        updated = candidate.model_copy(update=annotate_changes(candidate, row))
        if updated == candidate:
            # The note and step this decision would write are the ones the
            # candidate already carries — a re-apply of a review that has already
            # landed. Counted as a keep, because the provenance entry below
            # asserts an edit and "changed" has to mean the record differs, not
            # merely that a decision said `annotate`.
            counts["kept"] += 1
            kept.append(candidate)
            continue
        kept.append(updated)
        counts["annotated"] += 1

    if counts["annotated"] == 0 and counts["withdrawn"] == 0:
        return list(candidates), None, counts

    provenance = ProvenanceEntry(
        timestamp=when,
        actor=actor,
        operation="apply_candidate_review",
        layer=2,
        note=(
            f"candidate review confirmed: {counts['annotated']} candidate(s) annotated, "
            f"{counts['withdrawn']} withdrawn (of {total} recorded)"
        ),
    )
    return kept, provenance, counts


def with_provenance(violation: Violation, entry: ProvenanceEntry | None) -> Violation:
    """Return ``violation`` with one provenance entry appended (or unchanged)."""
    if entry is None:
        return violation
    return violation.model_copy(update={"provenance": [*violation.provenance, entry]})


# ---------------------------------------------------------------------------
# Generating a review when no ready-made one exists
# ---------------------------------------------------------------------------

#: The reviewer here has **no web access**. The ready-made files were written by
#: an agent reading bcn.cl; this prompt cannot pretend otherwise, so it is built
#: to make the model say "uncertain, fetch the text" instead of guessing — the
#: same failure mode (`Art. 497` invented as "denegación de auxilio") that
#: `CandidateArticle`'s own docstring exists to prevent.
_REVIEW_SYSTEM_PROMPT = """You review proposed article citations inside a \
legal violation pack. You are a checker, not an author.

Absolute rules:
- NEVER invent or paraphrase source text as if it were quoted. You may only
  describe an article's wording when that wording is present in the INPUT.
- NEVER invent case numbers, courts, dates, or URLs. The only URL you may
  return is one the INPUT already carries, or `https://www.bcn.cl/leychile` with
  no idNorma.
- You have no access to the internet. If judging a candidate needs the article's
  own text and it is not in the INPUT, the verdict is "Uncertain" and the
  correction must say which text has to be fetched.
- Judge agent fit: an article that applies only to a class the facts do not
  match (a judge, a police officer, an employer) is "Incorrect" for this
  violation even when the provision itself is real.
- Answer in the language the citation is written in; keep ids, article numbers
  and codes exactly as the INPUT spells them.

Return JSON only."""


def _rows_prompt(violation: Violation) -> str:
    """The user instruction for a generated review.

    The column list is stated once and reused by the parser, so a generated
    review and a ready-made one are read by the same code.
    """
    ids = [candidate.candidate_article_id for candidate in violation.candidate_articles]
    return f"""Review every candidate article in this violation pack against the \
official text of the provision it cites.

Candidates to review (use these ids EXACTLY, one row each, no others):
{chr(10).join(f'- {article_id}' for article_id in ids) or '- (none)'}

For each one answer:
- `validation`: ONE of "Correct", "Incorrect", "Uncertain", "Withdrawn".
  Add a short qualifier after it only when it changes the meaning — the pack
  reads a qualified "Correct" as an open candidate, not as a pass.
- `correction`: what is wrong, or what must be fetched to decide. Name the
  class of duty bearer the article applies to when that is the problem.
- `link`: the norm's page on bcn.cl when the INPUT carries it, otherwise "".

Also say, in `intro`, in two or three sentences, what the review found overall.

Return JSON of this shape:
{{
  "intro": "...",
  "candidates": [
    {{"candidate_article_id": "...", "law_code": "...", "article": "...",
      "description": "...", "validation": "...", "correction": "...",
      "link": "..."}}
  ]
}}"""


def rows_from_response(response: Mapping[str, Any]) -> list[ReviewRow]:
    """Build rows from a generated review's JSON."""
    rows: list[ReviewRow] = []
    for entry in response.get("candidates") or []:
        if not isinstance(entry, Mapping):
            continue
        candidate_id = str(entry.get("candidate_article_id") or "").strip()
        if not candidate_id:
            continue
        rows.append(
            ReviewRow(
                candidate_article_id=candidate_id,
                law_code=_prose(str(entry.get("law_code") or "")),
                article=_prose(str(entry.get("article") or "")),
                description=_prose(str(entry.get("description") or "")),
                validation=_prose(str(entry.get("validation") or "")),
                correction=_prose(str(entry.get("correction") or "")),
                link=str(entry.get("link") or "").strip(),
            )
        )
    return rows


def generate_review(
    violation: Violation,
    client: Any,
    *,
    max_tokens: int | None = None,
) -> tuple[list[ReviewRow], str]:
    """Ask the model to review the candidates; return ``(rows, intro)``.

    ``client`` is any `llm.LLMClient` (the same protocol every enrichment stage
    takes), which is what keeps this module testable without a network: the
    prompt is a function of the violation, and the parsing is a function of the
    response.
    """
    # One snapshot shape for every LLM stage in this package: a second one built
    # here would drift from the payload the `candidates` stage was tuned against.
    from .enrich import _violation_snapshot

    payload = _violation_snapshot(violation)
    response = client.chat_json(
        messages=[
            {
                "role": "user",
                "content": f"{_rows_prompt(violation)}\n\n--- INPUT ---\n"
                + json.dumps(payload, ensure_ascii=False, indent=2),
            }
        ],
        system=_REVIEW_SYSTEM_PROMPT,
        max_tokens=max_tokens,
    )
    rows = rows_from_response(response)
    intro = str(response.get("intro") or "").strip()
    return rows, intro


#: The columns a rendered review carries — the same seven the ready-made files
#: use, so a generated review can be dropped into `data/candidate-reviews/` and
#: read back by :func:`parse_review_table` without a single edit.
TABLE_COLUMNS = (
    "Candidate ID (from file)",
    "Law / Code",
    "Article",
    "Description (from file)",
    "Validation",
    "Correction / Notes",
    "BCN Link (Norm)",
)


def render_review_markdown(
    rows: Sequence[ReviewRow],
    *,
    intro: str = "",
    heading: str = "Validation Table",
) -> str:
    """Render rows in the ready-made files' own structure.

    Round-trips through :func:`parse_review_table` by construction, which is
    what `tests/test_candidate_review.py` pins: a generated review is only
    useful if the parser can read it back as the rows it came from.
    """
    def cell(text: str) -> str:
        # A pipe inside a cell would split the row; underscores stay bare, and
        # the parser unescapes, so `269_ter` survives the round trip either way.
        return (text or "").replace("|", "\\|").replace("\n", " ").strip()

    lines: list[str] = []
    if intro:
        lines.extend([intro.strip(), ""])
    lines.append(f"### {heading}")
    lines.append("")
    lines.append("| " + " | ".join(TABLE_COLUMNS) + " |")
    lines.append("| " + " | ".join(":---" for _ in TABLE_COLUMNS) + " |")
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                cell(value)
                for value in (
                    f"`{row.candidate_article_id}`",
                    row.law_code,
                    row.article,
                    row.description,
                    row.validation,
                    row.correction,
                    row.link,
                )
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)
