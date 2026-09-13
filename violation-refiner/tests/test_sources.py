from __future__ import annotations

import json
from pathlib import Path

from violation_pack.sources import HtmlTranscriptSource


ROOT = Path(__file__).resolve().parents[1]
HTML_ROOT = ROOT / "data" / "transcripts" / "html"
JSON_ROOT = ROOT / "data" / "transcripts" / "json"


def test_rendered_transcripts_match_json_segment_counts() -> None:
    html_stems = {p.stem for p in HTML_ROOT.glob("*.html")}
    json_stems = {p.stem for p in JSON_ROOT.glob("*.json")}

    # Compare the two corpora as sets, not against a pinned size: the corpus
    # grows (27 -> 29 on 2026-09-13) and a magic number turns every new
    # transcript into a failure while still missing a one-sided gap.
    assert html_stems, "no rendered transcripts found"
    assert html_stems == json_stems, (
        "render/json corpus mismatch — "
        f"html-only: {sorted(html_stems - json_stems)} "
        f"json-only: {sorted(json_stems - html_stems)}"
    )

    for stem in sorted(html_stems):
        html_path = HTML_ROOT / f"{stem}.html"
        source = HtmlTranscriptSource(html_path, stem, html_path.name)
        expected = json.loads(
            (JSON_ROOT / f"{stem}.json").read_text(encoding="utf-8")
        )["segments"]

        assert len(source.all_segments()) == len(expected), html_path.name
        assert source.get_segment("seg-0") is not None, html_path.name


def test_rendered_transcript_decodes_entities_and_metadata() -> None:
    path = HTML_ROOT / "I-002_05_NAR-07_STG_7_post_removal_investigation.html"
    source = HtmlTranscriptSource(path, "STG-7", "Transcripts/STG-7.html")
    segment = source.get_segment("seg-0")

    assert segment is not None
    assert segment["audio_offset_start"] == 94.0
    assert segment["audio_offset_end"] == 95.3
    assert segment["speaker"] == "passenger"
    assert segment["verbatim"] == "Una pregunta?"
