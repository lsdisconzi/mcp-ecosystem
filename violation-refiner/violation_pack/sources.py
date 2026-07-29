"""Source-of-truth readers.

These are the only modules that know how to parse a transcript HTML file or
a framework Markdown cache. Everything else in the library asks for segments
or article bodies through the Protocol interfaces below, so when you wire
Qdrant or some other store later, you write one new class that satisfies the
same Protocol and the rest of the code is unaffected.

In particular: when a transcript or framework gets too large to read off
disk every time, the same TranscriptSource / FrameworkSource interface can
be satisfied by a Qdrant-backed reader that pulls segments by ID with
vector similarity helpers on top.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Protocols (the extension seam)
# ---------------------------------------------------------------------------

class ParsedSegment(dict):
    """Lightweight record returned by TranscriptSource.

    Intentionally a dict subclass rather than a Pydantic model so the
    Source layer stays decoupled from the canonical models. Layers.py
    converts these into EvidenceSegment instances after enrichment.

    Required keys:
        segment_id, audio_offset_start, audio_offset_end, speaker, verbatim
    """


@runtime_checkable
class TranscriptSource(Protocol):
    """Anything that can produce verbatim segments from some transcript artifact."""

    def source_id(self) -> str:
        """Stable identifier for this transcript, e.g. 'STG-7'."""

    def source_uri(self) -> str:
        """Bundle-relative URI for the source artifact."""

    def source_sha256(self) -> str:
        """SHA256 of the source artifact's raw bytes."""

    def get_segment(self, segment_id: str) -> ParsedSegment | None:
        """Fetch one segment by its local ID (e.g. 'seg-55'). Returns None if missing."""

    def all_segments(self) -> list[ParsedSegment]:
        """Return every segment, in transcript order."""


@runtime_checkable
class FrameworkSource(Protocol):
    """Anything that can produce article bodies from a legal framework cache."""

    def framework_code(self) -> str:
        """Short code: 'CHIPENCOD' etc."""

    def cache_uri(self) -> str:
        """Bundle-relative URI for the cache artifact."""

    def cache_sha256(self) -> str:
        """SHA256 of the cache artifact's raw bytes."""

    def declared_sha256(self) -> str | None:
        """SHA the cache file declares about itself in its header, if any.
        V03 in the validator uses this to surface header/content mismatches."""

    def get_article_body(self, article_number: str) -> str | None:
        """Return the full body of an article (e.g. for article_number='193'),
        or None if not in the cache."""

    def articles_cached(self) -> list[str]:
        """All article numbers present in the cache."""


# ---------------------------------------------------------------------------
# Concrete impl: rendered-HTML transcript
# ---------------------------------------------------------------------------

_SEGMENT_PATTERN = re.compile(
    r'<div class="transcript-segment" id="(seg-\d+)">'
    r'<div class="seg-time">([\d.]+)s\s*→\s*([\d.]+)s</div>'
    r'<div class="seg-speaker">([^<]+)</div>'
    r'<p class="seg-text">"([^"]*)"</p>'
)


class HtmlTranscriptSource:
    """Reads segments from a rendered-HTML transcript artifact.

    The parsing assumes the convention used in the project's
    `timeline_*.html` artifacts. If that template changes, this is the
    one place that needs to know.
    """

    def __init__(self, path: str | Path, source_id: str, bundle_uri: str):
        self._path = Path(path)
        self._source_id = source_id
        self._bundle_uri = bundle_uri
        self._raw_bytes = self._path.read_bytes()
        self._html = self._raw_bytes.decode("utf-8")
        self._sha256 = hashlib.sha256(self._raw_bytes).hexdigest()
        self._index: dict[str, ParsedSegment] = {}
        for m in _SEGMENT_PATTERN.finditer(self._html):
            sid, t0, t1, spk, txt = m.groups()
            seg = ParsedSegment(
                segment_id=sid,
                audio_offset_start=float(t0),
                audio_offset_end=float(t1),
                speaker=spk.strip(),
                verbatim=txt,
            )
            self._index[sid] = seg

    # Protocol methods --------------------------------------------------------

    def source_id(self) -> str:
        return self._source_id

    def source_uri(self) -> str:
        return self._bundle_uri

    def source_sha256(self) -> str:
        return self._sha256

    def get_segment(self, segment_id: str) -> ParsedSegment | None:
        return self._index.get(segment_id)

    def all_segments(self) -> list[ParsedSegment]:
        return list(self._index.values())

    # Extras for validation helpers ------------------------------------------

    def raw_text(self) -> str:
        """Used by V02 to verify a verbatim quote appears byte-for-byte."""
        return self._html


# ---------------------------------------------------------------------------
# Concrete impl: markdown legal-framework cache
# ---------------------------------------------------------------------------

# Match an article header. Captures:
#   group 1: the identifier — digits + optional sub-tokens (e.g. '1', '19.1',
#            '133 A', '3 letra b)') terminated by ' — ' (em dash) or ' - '.
# The body is everything between this header and the next '### ' (or EOF) and
# is sliced separately so we can strip the metadata block.
_ARTICLE_HEADER_PATTERN = re.compile(
    r'^###\s+Art\.\s*([^\n—\-]+?)\s*[—\-]\s+[^\n]+$',
    re.MULTILINE,
)
_METADATA_LINE_PATTERN = re.compile(
    r'^\s*(?:\*\*[A-Za-z][A-Za-z _]{0,30}:\*\*[^\n]*|---+|)\s*$'
)
_DECLARED_SHA_PATTERN = re.compile(r"\*\*Sha256:\*\*\s*([0-9a-f]{64})", re.IGNORECASE)


def _strip_metadata_block(body: str) -> str:
    """Drop leading metadata lines (Theme/ELI ID/Tags/...), trailing '---'
    separators, and surrounding blank lines so the returned string is the
    verbatim legal text only."""
    lines = body.splitlines()
    # leading metadata + blanks
    i = 0
    while i < len(lines) and _METADATA_LINE_PATTERN.match(lines[i]):
        i += 1
    # trailing '---' separators + blanks
    j = len(lines)
    while j > i and _METADATA_LINE_PATTERN.match(lines[j - 1]):
        j -= 1
    return "\n".join(lines[i:j]).strip()


class MarkdownFrameworkSource:
    """Reads articles from the per-framework Markdown cache files
    (the `CHIPENCOD_CP.md` style)."""

    def __init__(self, path: str | Path, framework_code: str, bundle_uri: str):
        self._path = Path(path)
        self._framework_code = framework_code
        self._bundle_uri = bundle_uri
        self._raw_bytes = self._path.read_bytes()
        self._md = self._raw_bytes.decode("utf-8")
        self._sha256 = hashlib.sha256(self._raw_bytes).hexdigest()
        m = _DECLARED_SHA_PATTERN.search(self._md)
        self._declared_sha = m.group(1).lower() if m else None
        # Header-bounded slicing: an article body is everything from its header
        # to the next '### Art.' header (or EOF), with the metadata block
        # stripped. Indexed by the header identifier (e.g. '1', '19.1',
        # '133 A', '3 letra b)').
        self._articles: dict[str, str] = {}
        headers = list(_ARTICLE_HEADER_PATTERN.finditer(self._md))
        for idx, am in enumerate(headers):
            identifier = am.group(1).strip()
            start = am.end()
            end = headers[idx + 1].start() if idx + 1 < len(headers) else len(self._md)
            body = _strip_metadata_block(self._md[start:end])
            if body:
                self._articles[identifier] = body

    # Protocol methods --------------------------------------------------------

    def framework_code(self) -> str:
        return self._framework_code

    def cache_uri(self) -> str:
        return self._bundle_uri

    def cache_sha256(self) -> str:
        return self._sha256

    def declared_sha256(self) -> str | None:
        return self._declared_sha

    def get_article_body(self, article_number: str) -> str | None:
        """Look up an article body by identifier.

        Accepts the exact header identifier ('19.1', '133 A', '3 letra b)')
        as well as a bare numeric form: if no exact match, returns the body of
        the cached article whose identifier starts with ``article_number``
        followed by a non-digit boundary (so '133' matches '133 A' only if
        '133' itself is not cached)."""
        if article_number in self._articles:
            return self._articles[article_number]
        prefix = f"{article_number} "
        prefix_dot = f"{article_number}."
        for key, body in self._articles.items():
            if key.startswith(prefix) or key.startswith(prefix_dot):
                return body
        return None

    def articles_cached(self) -> list[str]:
        def _sort_key(s: str) -> tuple:
            # Best-effort numeric sort; fall back to string when non-numeric.
            head = re.match(r"\d+", s)
            return (int(head.group(0)) if head else 10**9, s)
        return sorted(self._articles.keys(), key=_sort_key)

    # Extras for validation helpers ------------------------------------------

    def raw_text(self) -> str:
        return self._md
