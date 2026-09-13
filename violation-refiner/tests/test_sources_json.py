"""Tests for the canonical-JSON transcript reader.

The point of this source (as opposed to the HTML render) is that its segment
ids join to the shared ``reviewed_transcripts`` collection. These tests pin the
two halves of that claim:

1. the composed id is ``"<transcript_id>.seg-<index>"``, and
2. that id is the one the collection stores (checked against the collection's
   own point-id derivation, ``transcription``'s ``md5(f"{tid}:{idx}")``).

They also pin ``speaker_index.json`` precedence, because that file is what
``transcription`` itself uses to resolve ``SPK-…`` ids, so any other order here
would produce payloads that disagree with the indexed corpus.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from violation_pack.sources import TranscriptSource
from violation_pack.sources_json import (
    JsonTranscriptSchemaError,
    JsonTranscriptSource,
    discover_json_transcripts,
    expand_segment_index_spec,
)


ROOT = Path(__file__).resolve().parents[1]
JSON_ROOT = ROOT / "data" / "transcripts" / "json"
SPEAKER_INDEX = ROOT / "data" / "speaker_index.json"
FIRST = "I-002_01_NAR-01_STG_1_pre_boarding"


# ---------------------------------------------------------------------------
# Segment spec grammar
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("3", ["seg-3"]),
        ("seg-3", ["seg-3"]),
        ("1-4", ["seg-1", "seg-2", "seg-3", "seg-4"]),
        ("seg-1..seg-3", ["seg-1", "seg-2", "seg-3"]),
        ("1,3-5", ["seg-1", "seg-3", "seg-4", "seg-5"]),
        ("0-2", ["seg-0", "seg-1", "seg-2"]),
        (" 2 , 1 ", ["seg-1", "seg-2"]),  # whitespace + dedup + sort
        ("5,5,5", ["seg-5"]),
    ],
)
def test_expand_segment_index_spec(spec: str, expected: list[str]) -> None:
    assert expand_segment_index_spec(spec) == expected


@pytest.mark.parametrize("spec", ["", "   ", ",", "abc", "1,x", "5-2", "1-" ])
def test_expand_segment_index_spec_rejects_bad_input(spec: str) -> None:
    with pytest.raises(ValueError):
        expand_segment_index_spec(spec)


def test_expansion_feeds_get_segment_directly() -> None:
    source = JsonTranscriptSource(JSON_ROOT / f"{FIRST}.json")
    for segment_id in expand_segment_index_spec("0,2-3"):
        assert source.get_segment(segment_id) is not None


# ---------------------------------------------------------------------------
# Protocol conformance + id composition
# ---------------------------------------------------------------------------

def test_json_source_satisfies_transcript_source_protocol() -> None:
    source = JsonTranscriptSource(JSON_ROOT / f"{FIRST}.json")
    assert isinstance(source, TranscriptSource)


def test_source_id_is_the_transcript_id_not_a_display_label() -> None:
    """``source_id`` must be the canonical id — ``layers.py`` composes with it.

    For the HTML reader ``source_id`` is a display label (``"STG-1"``), which
    produces ids that join to nothing. For this reader it must be the
    ``transcript_id`` so ``f"{source_id()}.{seg-N}"`` matches the collection.
    """
    source = JsonTranscriptSource(JSON_ROOT / f"{FIRST}.json")
    assert source.source_id() == FIRST
    assert source.transcript_id == FIRST


def test_composed_segment_id_matches_the_collection_form() -> None:
    """The composed id equals what ``reviewed_transcripts`` stores.

    The source reports the *local* id (``"seg-0"``), exactly like the HTML
    reader; ``layers.py`` composes the final id as
    ``f"{source_id()}.{local_id}"``. That composed string is what
    ``transcription`` stores as ``segment_id`` and what its point id is derived
    from, so both are reproduced here from the indexed side.
    """
    import hashlib
    import uuid

    from violation_pack.shared_corpora import transcript_point_id

    source = JsonTranscriptSource(JSON_ROOT / f"{FIRST}.json")
    for segment in source.all_segments():
        index = segment["index"]
        local_id = segment["segment_id"]

        # 1. The source reports the local id, per the TranscriptSource protocol.
        assert local_id == f"seg-{index}"

        # 2. Composition yields the identifier the collection stores.
        composed = f"{source.source_id()}.{local_id}"
        assert composed == f"{FIRST}.seg-{index}"

        # 3. The point id derived from that pair matches the dashed uuid.
        point_id = transcript_point_id(source.transcript_id, index)
        dashed = str(uuid.UUID(hashlib.md5(f"{FIRST}:{index}".encode()).hexdigest()))
        assert point_id == dashed
        assert point_id.count("-") == 4


def test_constructed_source_id_does_not_change_the_canonical_id() -> None:
    """A caller-supplied label is a label, not an identity override.

    Passing ``source_id="STG-1"`` (the HTML convention) must not change
    ``transcript_id``, and the composed id must therefore still join — but it
    *does* change the composed string, which is precisely why the HTML corpus
    cannot produce collection-aligned ids.
    """
    labelled = JsonTranscriptSource(JSON_ROOT / f"{FIRST}.json", source_id="STG-1")
    assert labelled.source_id() == "STG-1"
    assert labelled.transcript_id == FIRST
    assert labelled.all_segments()[0]["segment_id"] == "seg-0"
    # Composed id is now the non-joining HTML form...
    assert f"{labelled.source_id()}.seg-0" == "STG-1.seg-0"

    # ...whereas the unlabelled source composes to the collection form.
    plain = JsonTranscriptSource(JSON_ROOT / f"{FIRST}.json")
    assert f"{plain.source_id()}.seg-0" == f"{FIRST}.seg-0"


# ---------------------------------------------------------------------------
# Segment shape
# ---------------------------------------------------------------------------

def test_segments_carry_the_protocol_keys() -> None:
    source = JsonTranscriptSource(JSON_ROOT / f"{FIRST}.json")
    segment = source.get_segment("seg-0")
    assert segment is not None
    for key in ("segment_id", "audio_offset_start", "audio_offset_end", "speaker", "verbatim"):
        assert key in segment, key
    assert isinstance(segment["audio_offset_start"], float)
    assert isinstance(segment["audio_offset_end"], float)


def test_get_segment_accepts_all_three_id_spellings() -> None:
    source = JsonTranscriptSource(JSON_ROOT / f"{FIRST}.json")
    by_id = source.get_segment("seg-0")
    assert by_id is not None
    assert source.get_segment("0") == by_id
    assert source.get_segment(0) == by_id  # type: ignore[arg-type]
    assert source.get_segment("seg-9999") is None


def test_source_sha256_is_a_real_digest() -> None:
    import hashlib

    path = JSON_ROOT / f"{FIRST}.json"
    source = JsonTranscriptSource(path)
    assert source.source_sha256() == hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Speaker resolution — must mirror transcription's precedence
# ---------------------------------------------------------------------------

def test_speaker_id_resolves_from_the_shared_index() -> None:
    source = JsonTranscriptSource(JSON_ROOT / f"{FIRST}.json", speaker_index_path=SPEAKER_INDEX)
    segment = source.get_segment("seg-0")
    assert segment is not None
    assert segment["speaker_id"] == "SPK-passenger-leandro"


def test_index_beats_participant_labels() -> None:
    """Priority order must match ``QdrantTranscriptIndex._spk_by_seg``.

    ``speaker_index.json`` groups by speaker id, then by appearance, so the
    fixture is the first ``(speaker, transcript)`` appearance that actually
    lists a segment index.
    """
    index = json.loads(SPEAKER_INDEX.read_text(encoding="utf-8"))

    expected: str | None = None
    index_position: int | None = None
    for speaker_id, meta in index["mapped_speakers"].items():
        for appearance in meta.get("appearances") or []:
            if appearance.get("transcript_id") != FIRST:
                continue
            indices = appearance.get("segment_indices") or []
            if indices:
                expected = speaker_id
                index_position = int(min(indices))
                break
        if expected:
            break

    if expected is None:
        pytest.skip("speaker_index.json has no indexed appearance for the fixture")

    source = JsonTranscriptSource(JSON_ROOT / f"{FIRST}.json", speaker_index_path=SPEAKER_INDEX)
    assert source.get_segment(f"seg-{index_position}")["speaker_id"] == expected

    # The second tier (participant labels) must still work without the index.
    without = JsonTranscriptSource(JSON_ROOT / f"{FIRST}.json")
    assert without.get_segment(f"seg-{index_position}")["speaker_id"]
    assert without.participants()


# ---------------------------------------------------------------------------
# Schema guard
# ---------------------------------------------------------------------------

def test_rejects_an_olivialegal_bundle(tmp_path: Path) -> None:
    """An OliviaLegal export (``content[]``, camelCase) is not a transcript."""
    bundle = tmp_path / "bundle.json"
    bundle.write_text(
        json.dumps({"filename": "x", "content": [{"id": 0, "text": "hola"}]}),
        encoding="utf-8",
    )
    with pytest.raises(JsonTranscriptSchemaError):
        JsonTranscriptSource(bundle)


def test_rejects_a_document_without_segments(tmp_path: Path) -> None:
    path = tmp_path / "no_segments.json"
    path.write_text(json.dumps({"transcript_id": "T-1"}), encoding="utf-8")
    with pytest.raises(JsonTranscriptSchemaError):
        JsonTranscriptSource(path)


def test_accepts_an_empty_but_present_segments_list(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text(
        json.dumps({"transcript_id": "T-1", "segments": []}), encoding="utf-8"
    )
    source = JsonTranscriptSource(path)
    assert source.segment_count() == 0
    assert source.all_segments() == []
    assert source.get_segment("seg-0") is None


# ---------------------------------------------------------------------------
# Whole-corpus invariants
# ---------------------------------------------------------------------------

def test_discovery_returns_the_whole_canonical_corpus() -> None:
    sources = discover_json_transcripts(JSON_ROOT, speaker_index_path=SPEAKER_INDEX)

    # Parity with the corpus on disk rather than a pinned size: the corpus grows
    # (27 -> 29 on 2026-09-13) and a magic number fails on every new transcript
    # while still missing a one-sided gap.
    on_disk = {p.stem for p in JSON_ROOT.glob("*.json")}
    assert {s.path.stem for s in sources.values()} == on_disk
    # Magnitude check — a deliberate snapshot, bumped when the corpus grows.
    assert sum(s.segment_count() for s in sources.values()) == 3576
    # The reviewed count moves without the segment count when the transcription
    # pipeline republishes the two Guarulhos transcripts (3163 -> 3532 on
    # 2026-09-13), so it detects review-flag drift rather than growth.
    assert sum(len(s.reviewed_segments()) for s in sources.values()) == 3532
    assert all(s.is_canonical for s in sources.values())
    assert all(s.source_id() == s.transcript_id for s in sources.values())


def test_discovery_skips_non_canonical_files(tmp_path: Path) -> None:
    """A stray JSON must be skipped, not fatal — discovery walks directories."""
    good = json.loads((JSON_ROOT / f"{FIRST}.json").read_text(encoding="utf-8"))
    (tmp_path / f"{FIRST}.json").write_text(json.dumps(good), encoding="utf-8")
    (tmp_path / "not_a_transcript.json").write_text(json.dumps({"hello": "world"}), encoding="utf-8")

    sources = discover_json_transcripts(tmp_path)
    assert list(sources) == [FIRST]


def test_participants_and_speaker_ids_are_consistent() -> None:
    source = JsonTranscriptSource(JSON_ROOT / f"{FIRST}.json", speaker_index_path=SPEAKER_INDEX)
    participants = source.participants()
    assert participants
    known = {p["speaker_id"] for p in participants if p.get("speaker_id")}
    resolved = {sid for sid in source.speaker_ids().values() if sid}
    assert resolved <= known, (resolved - known)
