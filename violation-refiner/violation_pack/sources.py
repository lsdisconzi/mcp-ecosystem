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
import html as _html
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

    def get_article_body(self, article_id: str) -> str | None:
        """Return an article body by canonical ELI id or by identifier
        (e.g. article_id='CL.LPDC.Art.3.b'), or None if not in the cache.

        Implementations must prefer the id: a cache can hold two articles with
        the same number — an earlier edition of a law cached beside the current
        one, or two letras of one article — and only the id tells them apart.
        A citation that matches nothing must still fall back to the identifier
        lookup, because callers holding a bare number are supported."""

    def articles_cached(self) -> list[str]:
        """All article numbers present in the cache."""


# ---------------------------------------------------------------------------
# Concrete impl: rendered-HTML transcript
# ---------------------------------------------------------------------------

_SEGMENT_PATTERN = re.compile(
    r'<div\b'
    r'(?=[^>]*\bclass="[^"]*\btranscript-segment\b[^"]*")'
    r'(?=[^>]*\bid="(?P<sid>seg-\d+)")[^>]*>\s*'
    r'(?:<div\b[^>]*\bclass="[^"]*\bseg-datetime\b[^"]*"[^>]*>.*?</div>\s*)?'
    r'<div\b[^>]*\bclass="[^"]*\bseg-time\b[^"]*"[^>]*>\s*'
    r'(?P<t0>[\d.]+)s\s*(?:→|&rarr;|&#8594;)\s*(?P<t1>[\d.]+)s\s*</div>\s*'
    r'<div\b[^>]*\bclass="[^"]*\bseg-speaker\b[^"]*"[^>]*>'
    r'(?P<spk>.*?)</div>\s*'
    r'<p\b[^>]*\bclass="[^"]*\bseg-text\b[^"]*"[^>]*>\s*"'
    r'(?P<txt>.*?)"\s*</p>',
    re.DOTALL,
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
            sid = m.group("sid")
            t0 = m.group("t0")
            t1 = m.group("t1")
            spk = _html.unescape(m.group("spk"))
            txt = _html.unescape(m.group("txt"))
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
        """Whole-artifact text.

        Kept for callers that need the raw render (troubleshooting, ad-hoc
        tooling). Validation must *not* substring against this: preferring the
        cited segment is stricter and escape-insensitive — see
        ``v02_verbatim_quote_match``.
        """
        return self._html


# ---------------------------------------------------------------------------
# Concrete impl: markdown legal-framework cache
# ---------------------------------------------------------------------------

# Match an article header. Captures:
#   group 1: the identifier — digits + optional sub-tokens (e.g. '1', '19.1',
#            '133 A', '3 letra b)') terminated by ' — ' (em dash) or ' - '.
#   group 2: the human title to the end of the line.
# The body is everything between this header and the next '### ' (or EOF) and
# is sliced separately so we can strip the metadata block.
_ARTICLE_HEADER_PATTERN = re.compile(
    r'^###\s+Art\.\s*([^\n—\-]+?)\s*[—\-]\s+([^\n]+)$',
    re.MULTILINE,
)
_METADATA_LINE_PATTERN = re.compile(
    r'^\s*(?:\*\*[A-Za-z][A-Za-z _]{0,30}:\*\*[^\n]*|---+|)\s*$'
)
_DECLARED_SHA_PATTERN = re.compile(r"\*\*Sha256:\*\*\s*([0-9a-f]{64})", re.IGNORECASE)
# The caches declare the canonical id in the article's own metadata block, e.g.
# '**ELI ID:** `CL.CPCL.C1.Art.269_ter`' for the header '### Art. 269 ter'. That
# declaration is authoritative: it is the only place that knows the hierarchy
# segments ('C1', 'T2.P6') the header omits, so the UI shows it rather than
# reconstructing an id from the article number.
_ELI_ID_PATTERN = re.compile(r"\*\*ELI ID:\*\*\s*`([^`]+)`")


def _normalize_article_key(identifier: str) -> str:
    """Casefold and drop spaces/underscores so an ELI id and the cache header
    identifier it was derived from can be compared: the caches declare
    ``CL.CPCL.C1.Art.269_ter`` for the header ``### Art. 269 ter``,
    ``CL.LPDC.Art.23bis`` for ``### Art. 23 bis`` and ``CL.LPDC.Art.50A`` for
    ``### Art. 50 A``."""
    return re.sub(r"[\s_]+", "", identifier).casefold()


def _eli_article_tail(article_id: str) -> str:
    """The article a canonical ELI id names, sub-token included.

    ``CL.L20285.T1.C1.Art.3`` -> ``'3'`` and ``CL.LPDC.T1.Art.3.b`` ->
    ``'3.b'``. A value that is not a canonical id — a bare header identifier
    like ``'19.4'`` or ``'3 letra b)'`` — is returned unchanged, because the
    legacy lookup understands those forms and must keep receiving them
    verbatim."""
    _, sep, tail = article_id.partition(".Art.")
    return tail if sep else article_id


def _eli_article_number(article_id: str) -> str:
    """The bare article number the legacy (identifier-keyed) lookup uses."""
    return _eli_article_tail(article_id).split(".")[0]


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
        # The declared ELI id and human title per identifier. Kept beside the
        # bodies (same keys) so a caller can label an article without a second
        # parse of the cache.
        self._article_meta: dict[str, dict[str, str]] = {}
        # Articles in file order, plus an index from the canonical id each one
        # declares. `_articles` is keyed by header identifier, so two articles
        # sharing a number overwrite one another there and only the last
        # survives: `CL/L20285_Transparencia.md` caches the current
        # transparency law beside an earlier edition of it, and
        # `CL/L19496_LPDC.md` caches Art. 3 letra b) beside letra e). Those ids
        # are distinct, so indexing by them is what lets a citation say which
        # article it means instead of being answered with whichever header came
        # last in the file.
        self._ordered: list[tuple[str, str, dict[str, str]]] = []
        self._declared_eli: dict[str, int] = {}
        headers = list(_ARTICLE_HEADER_PATTERN.finditer(self._md))
        for idx, am in enumerate(headers):
            identifier = am.group(1).strip()
            start = am.end()
            end = headers[idx + 1].start() if idx + 1 < len(headers) else len(self._md)
            raw = self._md[start:end]
            body = _strip_metadata_block(raw)
            if body:
                meta = {"title": am.group(2).strip()}
                eli = _ELI_ID_PATTERN.search(raw)
                if eli:
                    meta["eli_id"] = eli.group(1).strip()
                    # First declaration wins: a corpus file that declares the
                    # same id twice is malformed, and keeping the earlier
                    # article makes that visible rather than silently letting
                    # the later duplicate take the citation over.
                    self._declared_eli.setdefault(
                        _normalize_article_key(meta["eli_id"]), len(self._ordered)
                    )
                self._ordered.append((identifier, body, meta))
                self._articles[identifier] = body
                self._article_meta[identifier] = meta

    # Protocol methods --------------------------------------------------------

    def framework_code(self) -> str:
        return self._framework_code

    def cache_uri(self) -> str:
        return self._bundle_uri

    def cache_sha256(self) -> str:
        return self._sha256

    def declared_sha256(self) -> str | None:
        return self._declared_sha

    def _resolve_article_key(self, article_number: str) -> str | None:
        """Resolve a caller's article reference to a cached header identifier.

        Three attempts, in order:

        1. an exact header identifier ('19.1', '133 A', '3 letra b)');
        2. a spelling-insensitive match, which is what lets a canonical ELI id
           ('Art.269_ter', 'Art.23bis') find a header that keeps the spaces
           ('269 ter', '23 bis');
        3. a prefix match, so a bare number finds its sub-tokened article
           ('133' -> '133 A') *after* an exact '133' has been ruled out.

        Every accessor goes through this, so a body, its declared ELI id and
        its title can never resolve to different articles.

        This maps a *string* to one header key, so it cannot tell apart two
        articles that share a number — see :meth:`_resolve_citation`, which
        consults the declared ids before falling back here.
        """
        if article_number in self._articles:
            return article_number
        wanted = _normalize_article_key(article_number)
        for key in self._articles:
            if _normalize_article_key(key) == wanted:
                return key
        prefix = f"{article_number} "
        prefix_dot = f"{article_number}."
        for key in self._articles:
            if key.startswith(prefix) or key.startswith(prefix_dot):
                return key
        return None

    def _resolve_citation(self, article_id: str) -> int | None:
        """Index into ``self._ordered`` for a citation naming a canonical ELI id.

        Two attempts, in order:

        1. the id exactly as some article declares it in its ``**ELI ID:**``
           line — this is what lets ``CL.L20285.T1.Art.3`` (the current
           transparency law) and ``CL.L20285.T1.C1.Art.3`` (an earlier edition
           cached in the same file) be told apart, and likewise
           ``CL.LPDC.Art.3.b`` from ``CL.LPDC.Art.3.e``;
        2. the same article *and* sub-token with the hierarchy segments the
           citation omits, so ``CL.LPDC.Art.3.b`` finds the declared
           ``CL.LPDC.T1.Art.3.b``. Accepted only when exactly one article
           matches: an omitted segment is resolved, never guessed.

        ``None`` means the citation names no declared id, and the caller should
        fall back to the identifier lookup — which is also what happens for the
        bare numbers and header identifiers the older callers still pass.
        """
        exact = self._declared_eli.get(_normalize_article_key(article_id))
        if exact is not None:
            return exact
        if ".Art." not in article_id:
            return None
        wanted = _eli_article_tail(article_id)
        matches = [
            index
            for index, (_, _, meta) in enumerate(self._ordered)
            if meta.get("eli_id") and _eli_article_tail(meta["eli_id"]) == wanted
        ]
        return matches[0] if len(matches) == 1 else None

    def get_article_body(self, article_id: str) -> str | None:
        """Look up an article body by citation.

        Accepts the exact header identifier ('19.1', '133 A', '3 letra b)'),
        a bare numeric form (if no exact match, returns the body of the cached
        article whose identifier starts with ``article_id`` followed by a
        non-digit boundary, so '133' matches '133 A' only if '133' itself is
        not cached), and a canonical ELI id.

        The canonical ELI id is matched against the id each article *declares*
        before the identifier is consulted, and it is the only form that can
        name an article when the cache holds two with the same number — the
        identifier-keyed lookup can only ever reach the last of them. A
        citation that matches no declared id falls back to the identifier
        lookup, so callers holding only a number keep working unchanged.
        """
        index = self._resolve_citation(article_id)
        if index is not None:
            return self._ordered[index][1]
        key = self._resolve_article_key(
            _eli_article_number(article_id) if ".Art." in article_id else article_id
        )
        return self._articles[key] if key is not None else None

    def get_article_eli_id(self, article_number: str) -> str | None:
        """The canonical id the cache declares for an article, if it declares one.

        ``None`` means the cache carries no ``**ELI ID:**`` line for this
        article — a real possibility, since the metadata block is optional.
        Callers must not invent an id in that case: the hierarchy segments
        ('C1', 'T2.P6') are not derivable from the header."""
        key = self._resolve_article_key(article_number)
        return self._article_meta.get(key, {}).get("eli_id") if key else None

    def get_article_title(self, article_number: str) -> str | None:
        """The human title from the article's header, e.g. 'Vejaciones injustas
        por empleado publico'."""
        key = self._resolve_article_key(article_number)
        return self._article_meta.get(key, {}).get("title") if key else None

    def articles_cached(self) -> list[str]:
        def _sort_key(s: str) -> tuple:
            # Best-effort numeric sort; fall back to string when non-numeric.
            head = re.match(r"\d+", s)
            return (int(head.group(0)) if head else 10**9, s)
        return sorted(self._articles.keys(), key=_sort_key)

    # Extras for validation helpers ------------------------------------------

    def raw_text(self) -> str:
        return self._md
