from __future__ import annotations

import json
from pathlib import Path

from violation_pack.sources import HtmlTranscriptSource


ROOT = Path(__file__).resolve().parents[1]
HTML_ROOT = ROOT / "data" / "transcripts" / "html"
JSON_ROOT = ROOT / "data" / "transcripts" / "json"


def test_rendered_transcripts_match_json_segment_counts() -> None:
    html_files = sorted(HTML_ROOT.glob("*.html"))
    json_files = sorted(JSON_ROOT.glob("*.json"))

    assert len(html_files) == len(json_files) == 27

    for html_path in html_files:
        source = HtmlTranscriptSource(html_path, html_path.stem, html_path.name)
        json_path = JSON_ROOT / f"{html_path.stem}.json"
        expected = json.loads(json_path.read_text(encoding="utf-8"))["segments"]

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
