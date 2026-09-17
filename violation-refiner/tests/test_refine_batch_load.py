"""``<VID>.json`` is the bundle's violation; ``<VID>.json.bak`` is not.

The batch refiner used to load the ``.bak`` whenever one existed, on the theory
that a re-run should re-anchor against the un-normalized source. The theory
could not be escaped in practice: the backup is written only when one is
*absent*, so the first snapshot was frozen forever and every edit made since —
through ``write_violation_json_tool``, the UI, or a hand-edit — was silently
discarded by the next batch run.

The snapshot is now what its name says: the previous generation, read only when
the live file cannot be parsed. Both halves of that sentence are tested here,
because either one alone is not the fix — a fallback that is never refreshed is
not a backup, and a refresh that is only read second is not a recovery path.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from violation_pack.models import EvidenceSegment, Incident, Violation
from violation_pack.refine_batch_core import _load_violation, run

VID = "CL-900"
TRANSCRIPT_ID = "I-002_01_NAR-01_STG_1_pre_boarding"


def _segment(index: int, quote: str = "do cofre") -> EvidenceSegment:
    return EvidenceSegment(
        segment_id=f"{TRANSCRIPT_ID}.seg-{index}",
        role_in_argument="fact",
        audio_offset_start=float(index),
        audio_offset_end=index + 1.0,
        speaker="passenger",
        verbatim_es=quote,
        verbatim_sha256="a" * 64,
        translation_en=f"EN {quote}",
        source_uri=f"data/transcripts/json/{TRANSCRIPT_ID}.json#seg-{index}",
        source_sha256="b" * 64,
    )


def _violation(*segments: EvidenceSegment, title: str = "t") -> Violation:
    return Violation(
        violation_id=VID,
        title=title,
        severity="LOW",
        incident=Incident(date="2024-07-05", location="Santiago"),
        schema_version="4.0",
        segments=list(segments),
    )


def _bundle(root: Path) -> Path:
    """``<root>/build/CL-900`` with a live violation and its transcript corpus.

    The bundle sits under ``build/`` because ``segment_sync`` resolves the
    canonical transcript through ``<bundle>/../../data/transcripts/json/``.
    """
    bundle = root / "build" / VID
    (bundle / "Transcripts").mkdir(parents=True, exist_ok=True)
    corpus = root / "data" / "transcripts" / "json"
    corpus.mkdir(parents=True, exist_ok=True)
    (corpus / f"{TRANSCRIPT_ID}.json").write_text(
        json.dumps(
            {
                "transcript_id": TRANSCRIPT_ID,
                "language": "es",
                "provider": "test",
                "segments": [
                    {
                        "index": i,
                        "speaker": "passenger",
                        "start": float(i),
                        "end": i + 1.0,
                        "duration": 1.0,
                        "text": f"frase {i}",
                        "reviewed": True,
                    }
                    for i in range(3)
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return bundle


def _write(path: Path, violation: Violation) -> None:
    path.write_text(violation.model_dump_json(indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# The live file wins
# ---------------------------------------------------------------------------

def test_the_live_json_is_loaded_in_preference_to_a_beside_it_bak(tmp_path):
    """The bug, stated as a test: with both files present the loader must
    return the live violation, not the snapshot beside it."""
    bundle = _bundle(tmp_path)
    live = bundle / f"{VID}.json"
    _write(live, _violation(_segment(1, "live")))
    _write(live.with_suffix(".json.bak"), _violation(_segment(7, "snapshot")))

    violation, notes = _load_violation(live, {}, {})

    assert [s.segment_id for s in violation.segments] == [f"{TRANSCRIPT_ID}.seg-1"]
    assert notes == [], "the live file needs no explanation"


# ---------------------------------------------------------------------------
# The snapshot is still a recovery path
# ---------------------------------------------------------------------------

def test_a_live_json_that_is_not_parseable_is_recovered_from_the_bak(tmp_path):
    """A write interrupted mid-file must not lose the bundle. This is the only
    reason to read the snapshot, so it has to keep working — and it has to say
    so in the notes rather than quietly returning the older content."""
    bundle = _bundle(tmp_path)
    live = bundle / f"{VID}.json"
    good = _violation(_segment(1, "complete")).model_dump_json(indent=2)
    live.write_text(good[: len(good) // 2], encoding="utf-8")
    (live.with_suffix(".json.bak")).write_text(good, encoding="utf-8")

    violation, notes = _load_violation(live, {}, {})

    assert [s.segment_id for s in violation.segments] == [f"{TRANSCRIPT_ID}.seg-1"]
    assert any(
        f"{VID}.json could not be read" in n and f"{VID}.json.bak" in n for n in notes
    ), f"the recovery has to be visible in the run notes, got {notes}"


def test_a_live_json_that_is_valid_json_but_a_legacy_shape_is_normalized(tmp_path):
    """A pre-converter bundle is not a corrupt file: it parses, so it is loaded
    from the live path and its segments are re-anchored there — the fallback is
    not what makes legacy bundles work."""
    bundle = _bundle(tmp_path)
    live = bundle / f"{VID}.json"
    live.write_text(
        json.dumps(
            {
                "violation_id": VID,
                "title": "legacy",
                "facts": {
                    "segments": [
                        {
                            "segment_id": f"{TRANSCRIPT_ID}.seg-2",
                            "text": "from the vault",
                            "timeStart": "2.0",
                            "timeEnd": "3.0",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    _write(live.with_suffix(".json.bak"), _violation(_segment(7, "snapshot")))

    violation, _notes = _load_violation(live, {}, {})

    assert [s.segment_id for s in violation.segments] == [f"{TRANSCRIPT_ID}.seg-2"]
    assert [s.verbatim_es for s in violation.segments] == ["from the vault"]


# ---------------------------------------------------------------------------
# The snapshot is refreshed, so "previous generation" is true
# ---------------------------------------------------------------------------

def test_the_backup_holds_the_previous_generation_not_the_first_one(tmp_path):
    """Two runs with an edit in between. The second run must (a) consume the
    edit and (b) leave the edit in the backup, so the file stays a usable
    fallback. Under the old rule the run loaded the .bak, discarded the edit,
    and the .bak held the very first run's content forever."""
    bundle = _bundle(tmp_path)
    live = bundle / f"{VID}.json"
    _write(live, _violation(_segment(1, "first")))

    assert run(tmp_path / "build", True, [VID], None, True, False, enrich=False) == 0

    # An edit of the kind the write gate or the UI makes. The batch run after it
    # must keep it, not resurrect the pre-edit violation.
    doc = json.loads(live.read_text(encoding="utf-8"))
    doc["title"] = "edited-by-the-ui"
    live.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

    assert run(tmp_path / "build", True, [VID], None, True, False, enrich=False) == 0

    assert _load_violation(live, {}, {})[0].title == "edited-by-the-ui"
    bak = json.loads(live.with_suffix(".json.bak").read_text(encoding="utf-8"))
    assert bak["title"] == "edited-by-the-ui", (
        "the backup is refreshed from the live file on every run; if it still "
        "holds the first run's content it is not a previous generation"
    )


def test_no_backup_is_written_when_the_toggle_is_off(tmp_path):
    """The toggle still means what it says — the load order change did not turn
    backups into something that happens regardless."""
    bundle = _bundle(tmp_path)
    live = bundle / f"{VID}.json"
    _write(live, _violation(_segment(1, "first")))

    assert run(tmp_path / "build", True, [VID], None, False, False, enrich=False) == 0

    assert not live.with_suffix(".json.bak").exists()
