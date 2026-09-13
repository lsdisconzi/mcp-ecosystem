"""Tests for the V01-V11 validation pipeline.

Focused on V02, whose contract is subtle enough to have shipped wrong: it used
to substring-match the *whole* transcript artifact, which cannot tell a quote
taken from the cited segment apart from one lifted from a neighbouring segment,
and which fails on quotes that are present but escaped differently in the file.
"""
from __future__ import annotations

import pytest

from violation_pack.models import EvidenceSegment, Incident, Violation
from violation_pack.sources import ParsedSegment
from violation_pack.validation import v02_verbatim_quote_match

_EM_DASH = "\u2014"


class _FakeTranscript:
    """Minimal TranscriptSource over an in-memory ``local_id -> text`` map."""

    def __init__(self, segments: dict[str, str], raw_text: str | None = None):
        self._segments = segments
        self._raw_text = raw_text

    def source_id(self) -> str:
        return "STG-7"

    def source_uri(self) -> str:
        return "Transcripts/timeline_aeropuerto_STG_7.html"

    def source_sha256(self) -> str:
        return "0" * 64

    def get_segment(self, segment_id: str) -> ParsedSegment | None:
        text = self._segments.get(segment_id)
        if text is None:
            return None
        return ParsedSegment(
            segment_id=segment_id,
            audio_offset_start=0.0,
            audio_offset_end=1.0,
            speaker="SPK",
            verbatim=text,
        )

    def all_segments(self) -> list[ParsedSegment]:
        return [self.get_segment(sid) for sid in self._segments]

    def raw_text(self) -> str:
        if self._raw_text is not None:
            return self._raw_text
        return "\n".join(self._segments.values())


def _segment(local_id: str, quote: str) -> EvidenceSegment:
    return EvidenceSegment(
        segment_id=f"STG-7.{local_id}",
        role_in_argument="test",
        audio_offset_start=0.0,
        audio_offset_end=1.0,
        speaker="SPK",
        verbatim_es=quote,
        verbatim_sha256="a" * 64,
        translation_en="",
        source_uri=f"Transcripts/timeline_aeropuerto_STG_7.html#{local_id}",
        source_sha256="b" * 64,
    )


def _violation(*segments: EvidenceSegment) -> Violation:
    return Violation(
        violation_id="CL-999",
        title="t",
        severity="LOW",
        incident=Incident(date="2024-01-01", location="Santiago"),
        segments=list(segments),
    )


def _run(v: Violation, transcripts: dict) -> tuple[str, str]:
    result = v02_verbatim_quote_match(v, {"transcripts": transcripts})
    return result.status, result.details


def test_passes_when_quote_is_in_the_cited_segment():
    ts = _FakeTranscript({"seg-10": "hola, buenos dias"})
    status, _ = _run(_violation(_segment("seg-10", "hola, buenos dias")), {"STG-7": ts})
    assert status == "pass"


def test_fails_when_quote_only_exists_in_another_segment():
    """The property ``raw_text()`` could not enforce.

    A quote copied from a neighbouring segment is present in the artifact but
    not in the segment it claims to come from. Scoping the comparison to the
    cited segment is what makes this a failure.
    """
    ts = _FakeTranscript(
        {"seg-10": "no recuerdo nada de eso", "seg-11": "yo cargue la maleta"},
        raw_text="no recuerdo nada de eso yo cargue la maleta",
    )
    v = _violation(_segment("seg-10", "yo cargue la maleta"))
    # Guard against the fixture going vacuous: the quote IS in the raw artifact,
    # so the old artifact-wide comparison would have passed this bundle.
    assert "yo cargue la maleta" in ts.raw_text()
    status, details = _run(v, {"STG-7": ts})
    assert status == "fail"
    assert "seg-10" in details


def test_is_escape_insensitive_but_artifact_bytes_are_not():
    """A JSON artifact stores ``\\u2014`` where the segment holds a real em dash."""
    quote = f"el acta {_EM_DASH} firmada"
    ts = _FakeTranscript(
        {"seg-20": quote},
        raw_text='"verbatim": "el acta \\u2014 firmada"',  # literal escape sequence
    )
    assert quote not in ts.raw_text()
    status, _ = _run(_violation(_segment("seg-20", quote)), {"STG-7": ts})
    assert status == "pass"


def test_unresolved_segment_ids_are_skipped_not_failed():
    """V01 owns unresolvable ids; V02 must not double-report them."""
    ts = _FakeTranscript({"seg-30": "texto"})
    v = _violation(_segment("seg-999", "texto"), _segment("seg-30", "texto"))
    status, details = _run(v, {"STG-7": ts})
    assert status == "pass"
    assert "1 quote(s) checked" in details
    assert "1 skipped" in details


def test_missing_transcript_registration_is_skipped():
    v = _violation(_segment("seg-40", "texto"))
    status, details = _run(v, {})
    assert status == "pass"
    assert "1 skipped" in details


@pytest.mark.parametrize("empty", ["", "   ", "\n\t "])
def test_empty_quotes_are_skipped_rather_than_passing_vacuously(empty):
    ts = _FakeTranscript({"seg-50": "algo"})
    status, details = _run(_violation(_segment("seg-50", empty)), {"STG-7": ts})
    assert status == "pass"
    assert "0 quote(s) checked" in details
    assert "1 skipped" in details


def test_reports_every_mismatch():
    ts = _FakeTranscript({"seg-60": "aaa", "seg-61": "bbb"})
    v = _violation(_segment("seg-60", "zzz"), _segment("seg-61", "yyy"))
    status, details = _run(v, {"STG-7": ts})
    assert status == "fail"
    assert "2 mismatch(es)" in details
    assert "seg-60" in details and "seg-61" in details
