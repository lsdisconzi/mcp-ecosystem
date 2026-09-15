"""Official-source ingestion for authority verification.

``authority_verification.py`` disposes of an authority stub against a primary
source, and it is built on one deliberate restriction: it never opens the
network and never opens a file. The caller hands it ``source_content`` as a
string and it hashes *exactly that string*, so ``source_sha256`` pins the text
that actually matched rather than a file that might have been re-saved under
it. Every question about where the text came from therefore lands here:

* downloading an authoritative page (bcn.cl, pjud.cl, …) so the fetch stays
  out of the verification module, exactly as that module's docstring
  prescribes;
* reading an uploaded document — plain text as-is, PDF through an optional
  extractor if one happens to be installed;
* storing the artefact under the bundle so the proof travels with the pack
  instead of living in the reviewer's Downloads folder;
* writing the sidecar that ties the two together, because
  ``VerificationProvenance`` has ``extra="forbid"`` and can only carry one
  ``source_uri``: an authority whose proof is *both* a canonical URL and an
  uploaded PDF needs a second place to record the second half.

The one invariant this module keeps is that ``source_content`` comes back to
the caller byte-identical to the text whose SHA256 is reported. Callers pass
that string straight into ``verify_statute_external_fetch`` /
``verify_human_attested``, and the protocol recomputes the hash, so a
mismatch shows up as a failed verification rather than as a quiet lie in the
audit trail.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib import error as _urlerr
from urllib import parse as _urlparse
from urllib import request as _urlreq

from .pack import BUNDLE_LAYOUT

#: Directory inside the bundle that holds the ingested official sources. Read
#: from the layout table so the MANIFEST and the zip pick it up automatically
#: and so there is exactly one statement of the bundle's shape.
SOURCES_DIR = BUNDLE_LAYOUT["authority_sources_dir"]

#: Pluralisation trap: this is a directory *name*, so it is compared against a
#: path component, never split on the space it contains.
PROOF_SUFFIX = ".proof.json"
TEXT_SUFFIX = ".text.txt"

#: Version of the sidecar's shape. Absent means the flat v1 record, which is
#: still readable: every field v1 has kept its meaning, and everything v2 adds
#: (`readings`, `notes`) is additive. The version exists because v2 changes what
#: `text_sha256` is a hash *of* — v1 hashed the extractor's entire output, v2
#: hashes the body reading with the margin citations and the running furniture
#: taken out — so a stored hash that no longer matches a re-read PDF is expected
#: across versions, and is not on its own evidence that the proof was altered.
PROOF_SCHEMA_VERSION = "2.0.0"

MAX_FETCH_BYTES = 8 * 1024 * 1024
MAX_UPLOAD_BYTES = 16 * 1024 * 1024
FETCH_TIMEOUT = 20.0

#: Extensions whose bytes are already the text we want to match against. A page
#: saved from the browser lands here as ``.html``; a copy-paste of the
#: "save as text" dialog lands as ``.txt``.
TEXT_SUFFIXES = frozenset({
    ".txt", ".text", ".md", ".markdown", ".rst", ".log",
    ".json", ".csv", ".tsv", ".xml", ".yaml", ".yml",
    ".html", ".htm", ".xhtml",
})

MARKUP_SUFFIXES = frozenset({".html", ".htm", ".xhtml", ".xml"})


class SourceError(Exception):
    """Raised when an official source cannot be ingested.

    Like ``VerificationError``, a raise means nothing was written to the
    bundle: the caller gets an error instead of a half-stored proof.
    """


# ---------------------------------------------------------------------------
# Text hygiene
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")
_DROPPED_RE = re.compile(r"<(script|style|noscript)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_BLOCK_RE = re.compile(
    r"</?(?:p|div|br|tr|li|h[1-6]|section|article|blockquote|table|ul|ol)\b[^>]*>",
    re.IGNORECASE,
)


def collapse_whitespace(text: str) -> str:
    """Collapse every whitespace run to one space and trim the ends.

    Verbatim quoting out of a reflowed PDF or an HTML body is otherwise
    impossible: a human copies "el plazo de 30 días" and the source holds a
    newline where the space was, so the protocol's byte-for-byte search fails
    on a quote that is visually correct. Collapsing both sides — the text that
    is hashed is the collapsed text returned to the caller — makes the quote
    the reviewer can see the quote the protocol can find.
    """
    return _WS_RE.sub(" ", text).strip()


def strip_markup(text: str) -> str:
    """Reduce an HTML/XML document to its visible text.

    Dependency-free on purpose (``bs4`` is not installed anywhere in this
    repo), and deliberately crude in one respect: block-level tags become
    spaces *before* the remaining tags are dropped, so ``<p>a</p><p>b</p>``
    cannot fuse into ``ab``. Entities are unescaped because ``bcn.cl`` writes
    accented Spanish as numeric entities, and an unescaped quote would never
    match the words on screen.
    """
    out = _DROPPED_RE.sub(" ", text)
    out = _BLOCK_RE.sub(" ", out)
    out = _TAG_RE.sub("", out)
    return collapse_whitespace(html.unescape(out))


def decode_bytes(data: bytes) -> tuple[str, list[str]]:
    """Decode an uploaded/fetched payload as text, never raising.

    UTF-8 first (the whole corpus is UTF-8), then Latin-1, which cannot fail
    and is what older Chilean institutional pages still emit. The second path
    is reported as a warning rather than hidden: a mojibake transcript is
    exactly the kind of thing that makes a quote un-matchable for reasons the
    reviewer cannot see.
    """
    try:
        return data.decode("utf-8"), []
    except UnicodeDecodeError:
        pass
    return data.decode("latin-1"), [
        "the payload is not valid UTF-8; decoded as Latin-1, so accented words "
        "may not match a quote copied from the rendered page",
    ]


def _read_pypdf(data: bytes) -> list[str]:
    """Extract one string per page, in page order.

    *Per page*, not one joined blob. A page is the unit the layout pass below
    reasons about — "this line is on all ten pages, so it is a running header,
    not a paragraph" — and joining here would throw away the only boundary that
    fact is available at. Joining is still what the caller ends up doing; it just
    happens after the pages have been looked at, instead of before.
    """
    import io

    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:  # pragma: no cover - depends on the installed extras
        from PyPDF2 import PdfReader  # type: ignore

    reader = PdfReader(io.BytesIO(data))
    return [(page.extract_text() or "") for page in reader.pages]


def _read_fitz(data: bytes) -> list[str]:
    """Same contract as `_read_pypdf`: page text, one string per page."""
    import fitz  # type: ignore

    with fitz.open(stream=data, filetype="pdf") as doc:  # pragma: no cover - optional extra
        return [page.get_text() for page in doc]


#: Optional PDF extractors, tried in this order. `pypdf` is the maintained
#: successor of `PyPDF2`; `fitz` is PyMuPDF. Installing one is optional (see the
#: `pdf` extra), so a PDF upload without any of them still stores the artefact
#: and its hash and simply reports that no text was extracted.
#:
#: The reader is stored as the *callable*, not as its name. The previous form
#: paired a module name with a string and resolved it through `globals()`, so
#: `_read_pypdf` vs `read_pypdf` — a single leading underscore — was the
#: difference between reading a PDF and a `KeyError` reported as "pypdf is
#: installed but could not read this PDF". That lookup could only ever run once
#: an extractor was importable, which is to say only after a reviewer did what
#: the warning told them to do and installed one. Holding the function removes
#: the name entirely, so there is nothing left to drift.
_PDF_EXTRACTORS: tuple[tuple[str, Callable[[bytes], list[str]]], ...] = (
    ("pypdf", _read_pypdf),
    ("PyPDF2", _read_pypdf),
    ("fitz", _read_fitz),
)


# ---------------------------------------------------------------------------
# PDF layout — getting the body column out of a two-column official PDF
# ---------------------------------------------------------------------------
#
# A flat PDF extraction is a rectangle of words with the page's geometry gone,
# and official Chilean sources are laid out in two columns: the article body
# runs down the left, and the right margin carries the legislative history
# ("LEY N° 20.050 Art. 1° N° 10 letra a) D.O. 26.08.2005"). Both columns are
# flattened onto the same physical line, so the citation lands *between* two
# words of the sentence it annotates:
#
#     'Corresponderá al legislador establecer siempre las            26.08.2005'
#     'garantías de un procedimiento y una investigación'
#
# The sentence is intact on the page and destroyed in the reading, which is
# worse than a sentence that is simply missing: the reviewer is shown text that
# looks like the document and cannot quote a line of it, with nothing on screen
# to say why. Everything below exists to undo that flattening — and to leave an
# account of what was moved, because a reading nobody can audit is the same
# problem one level down.

#: A run of two or more spaces is the only mark of a column break that survives
#: extraction: the geometry is gone, so the spacing that produced the visual
#: gutter is all that is left to reason about.
_GAP_RE = re.compile(r"[ \t]{2,}")

#: How far a gap may sit from the detected gutter and still be it. Zero would
#: work on the document this was written against and would break on the next
#: one that pads a line differently, because the gutter is a visual alignment
#: rather than an integer the producer of the PDF ever agreed on.
_GUTTER_TOLERANCE = 2

#: A gutter has to be a habit rather than an accident. A handful of widely
#: spaced lines is a table or a signature block, and splitting there cuts the
#: body in half.
_MIN_GUTTER_SUPPORT = 8

#: Indentation is a gap too, and it is always near the left edge. A position
#: this close to column zero is a paragraph indent, never a column break.
_MIN_GUTTER_COLUMN = 12

#: How many *distinct* wide-gap positions a page may have before it stops
#: looking like two columns. A real gutter is one line down the whole page; a
#: run of justified text scatters its extra spaces across dozens of columns,
#: and that scatter is the signal that there is no gutter to find.
_MAX_GUTTER_CANDIDATES = 3

#: After cutting, the body has to still be the body. Cutting at a paragraph
#: indent hands the entire line to the "margin" — and a split that returns an
#: empty left column still returns a string, so the failure would be silent.
_MIN_BODY_SHARE = 0.6

#: Furniture is a line that repeats across pages. Two pages are not enough to
#: tell a running header from a clause a statute repeats on purpose, and the
#: cost of being wrong is a sentence that becomes unquotable.
_MIN_FURNITURE_PAGES = 3

#: ...and it has to be short. A paragraph that genuinely repeats on three
#: separate pages is far more likely to be the document's text than its
#: letterhead, so a long line is left alone however often it recurs.
_FURNITURE_MAX_CHARS = 160

#: ...and it has to read as a line of text rather than as a number. Masking
#: digits is what lets one page marker match its ten variants, so a numeral
#: alone on its line (``1º.-``, ``2º.-``, ``3º.-``) collapses to a single key
#: too, and a document that numbers its articles across pages would lose them
#: all as furniture.
_MIN_FURNITURE_LETTERS = 3

_DIGITS_RE = re.compile(r"\d+")

#: ``(page, line, text)``, both numbers 1-based. Every row carries its address
#: so that a line taken out of the body can be *reported* with where it came
#: from, instead of merely being absent.
Row = tuple[int, int, str]

#: The vocabulary a margin citation opens with. The margin is a *column*, so its
#: text wraps on its own grid: one citation arrives as two to four rows, and the
#: row that opens it is the one naming the law. ``Art.`` is deliberately absent —
#: an article reference is part of a citation and never the whole of one, so it
#: continues the citation it belongs to by not opening a new one.
#: ``^`` is absent for the same reason: this is used only through ``.match``, and
#: a pattern that anchors twice cannot be tested for anchoring once.
_CITATION_START_RE = re.compile(r"(?:cpr|ley|dfl|dl|decreto|constituci)", re.IGNORECASE)

#: ``1º.-`` … ``26º.-``: an article's numerals, each opening its own body row.
#: Nothing else marks where a numeral begins — its text is not indented, and its
#: end is simply the next numeral's marker — so this shape is the only thing in
#: the body that says where one numeral stops and the next starts.
#: Used through ``.match``, so it carries no ``^`` of its own.
_NUMERAL_MARK_RE = re.compile(r"(?P<number>\d{1,2})\s*[.º°]\s*\.?\s*-")

#: The numeral a citation names in its own words — ``CPR Art. 19° N° 13``. It is
#: anchored on ``Art. 19`` rather than on ``N°`` alone, because every amending
#: law in the margin numbers its own articles too (``LEY N° 19.611 Art. único
#: Nº 2``), and those numbers belong to the law rather than to the Constitution.
_CITATION_NUMERAL_RE = re.compile(
    r"art\.?\s*19\s*[.º°]?\s*n\s*[.º°]?\s*(?P<number>\d{1,2})", re.IGNORECASE
)


def _gap_ends(pages: Sequence[str]) -> Counter[int]:
    """Count, per column, how many whitespace runs end there."""
    ends: Counter[int] = Counter()
    for page in pages:
        for line in page.split("\n"):
            if not line.strip():
                continue
            for match in _GAP_RE.finditer(line):
                ends[match.end()] += 1
    return ends


def _body_share(body_rows: Sequence[Row], note_rows: Sequence[Row]) -> float:
    """How much of the split line content stayed on the left.

    The guard that turns a wrong gutter into no gutter at all.
    """
    body = sum(len(text) for _, _, text in body_rows)
    notes = sum(len(text) for _, _, text in note_rows)
    total = body + notes
    return 1.0 if not total else body / total


def split_columns(
    pages: Sequence[str], column: int | None = None
) -> tuple[list[Row], list[Row]]:
    """Cut every line at the gutter; return ``(body_rows, note_rows)``.

    ``column=None`` means no gutter was found, and then every row is a body row.
    Both outcomes have the same shape so the caller has no branch to forget, and
    so "the split found nothing" cannot be confused with "the split was never
    attempted".

    The right-hand side is *returned*, never dropped. On an official document it
    is the amendment history — which law changed this numeral, when, and in which
    edition of the Diario Oficial — which is the answer to the question the
    verification modal asks. Deleting it to tidy the reading would throw away the
    evidence in order to make the evidence easier to search.

    A line with no gap near the gutter stays whole in the body. That is the
    conservative direction: a body line that happened to contain a wide gap is
    kept intact, where a margin line mistaken for body would corrupt a sentence.
    """
    body: list[Row] = []
    notes: list[Row] = []
    for page_number, page in enumerate(pages, start=1):
        for line_number, line in enumerate(page.split("\n"), start=1):
            cut: int | None = None
            if column is not None:
                for match in _GAP_RE.finditer(line):
                    if abs(match.end() - column) <= _GUTTER_TOLERANCE:
                        cut = match.end()
                        break
            head = (line[:cut] if cut is not None else line).strip()
            tail = (line[cut:] if cut is not None else "").strip()
            if head:
                body.append((page_number, line_number, head))
            if tail:
                notes.append((page_number, line_number, tail))
    return body, notes


def detect_gutter(pages: Sequence[str]) -> tuple[int, int] | None:
    """Find the column that separates the body from a margin column.

    Returns ``(column, support)``, or ``None`` when the pages do not look like a
    two-column layout. ``None`` is the answer this should give most of the time,
    because the two ways of being wrong are not symmetrical: not splitting a
    document leaves the reading exactly as it is today, whereas splitting one
    that has no gutter produces a reading missing part of every line — which
    still looks like a document, and so cannot be noticed.

    Three things have to hold before a column is believed: the gap ends there
    often enough to be a habit, the position is well clear of the left margin,
    and there is essentially only one such position. The last is what rules out
    justified text, whose extra spaces land all over the place — a gutter is one
    line down the whole page, and nothing else is.
    """
    wide = Counter({
        column: count
        for column, count in _gap_ends(pages).items()
        if column >= _MIN_GUTTER_COLUMN and count >= _MIN_GUTTER_SUPPORT
    })
    if not wide or len(wide) > _MAX_GUTTER_CANDIDATES:
        return None
    # Most-supported first: when two wide gaps compete, the one that repeats
    # down the page is the column break and the other is something inside the
    # body, such as a table or an aligned list. Ties go to the smaller column,
    # which keeps the most content in the body.
    for column, support in sorted(wide.items(), key=lambda item: (-item[1], item[0])):
        body, notes = split_columns(pages, column)
        if _body_share(body, notes) >= _MIN_BODY_SHARE:
            return column, support
    return None


def _repeat_key(text: str) -> str:
    """The form in which two lines count as the same line.

    Digits become ``#`` because a page marker is the one piece of furniture that
    is *supposed* to change from page to page: ``página 1 de 10`` and
    ``página 2 de 10`` are one line printed ten times, and an exact comparison
    would see ten different lines and keep every one of them.
    """
    return _DIGITS_RE.sub("#", collapse_whitespace(text))


def _has_words(text: str) -> bool:
    """Whether a line carries enough letters to be a line of text.

    The companion to digit masking, and the reason it cannot be let loose on
    its own: ``1º.-`` masks to one key, and a document whose articles are
    numbered on lines of their own would have every one of them dropped as
    furniture. Requiring letters keeps the masking available for the page
    marker it was for — ``página 1 de 10`` — without letting it swallow bare
    numbering.
    """
    return sum(1 for char in text if char.isalpha()) >= _MIN_FURNITURE_LETTERS


def strip_repeated_furniture(rows: Sequence[Row]) -> tuple[list[Row], list[Row]]:
    """Drop lines that repeat across pages; return ``(kept, removed)``.

    No list of known footers is involved, and that is the point: a pattern list
    is written for the documents that already exist and silently misses the next
    authority's letterhead. Repetition is the property that *defines* furniture
    on any document, and it needs no vocabulary to recognise.

    It matters for quoting as much as for tidiness. A running footer sits
    between two words of a sentence that spans a page break — ``…comisiones
    especiales, Documento generado el 15-Sep-2026 página 2 de 10 sino por el
    tribunal…`` — so the footer does not merely add noise, it makes the sentence
    unquotable, and a reviewer looking at the screen has no way to see that.

    Removed rows come back rather than being deleted here, because "quietly
    shorter" is what a reading must never become.

    There is no separate "too few pages" early return, and adding one back would
    be dead code: a key can only be seen on pages that exist, so requiring three
    sightings is already a requirement of three pages, and a branch no input can
    reach is a branch no test can hold still.
    """
    page_count = len({page for page, _, _ in rows})
    pages_by_key: dict[str, set[int]] = {}
    for page, _, text in rows:
        key = _repeat_key(text)
        if len(key) > _FURNITURE_MAX_CHARS or not _has_words(key):
            continue
        pages_by_key.setdefault(key, set()).add(page)
    # "On most pages", not merely "on three of them": a running header is by
    # definition on nearly every page, whereas a line that recurs on three pages
    # of twenty is far more likely to be a clause the document repeats on
    # purpose, and dropping it would delete the document's own text.
    repeated = {
        key
        for key, seen_on in pages_by_key.items()
        if len(seen_on) >= _MIN_FURNITURE_PAGES and len(seen_on) * 2 >= page_count
    }
    if not repeated:
        return list(rows), []
    kept = [row for row in rows if _repeat_key(row[2]) not in repeated]
    removed = [row for row in rows if _repeat_key(row[2]) in repeated]
    return kept, removed


# ---------------------------------------------------------------------------
# The margin column: what was set aside, and what it says
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Citation:
    """One margin citation, joined from the rows it was printed as.

    ``page``/``first_line`` and ``last_page``/``last_line`` are the span it
    occupies in the raw extraction, so the rows it was made of can be found
    again. The end of the span carries its own page rather than sharing the
    start's, because a citation really is printed across a page break:
    ``Art. ÚNICO Nº 1 b)`` on one page and ``D.O. 11.07.2011`` on the next are
    one citation, and a single ``line`` pair cannot say that.

    ``beside`` and ``named`` are two different answers, kept apart on purpose;
    see `attribute_citations`.
    """

    text: str
    page: int
    first_line: int
    last_page: int
    last_line: int
    beside: int | None = None
    named: int | None = None

    @property
    def crosses_page(self) -> bool:
        """Whether the citation was printed across a page break."""
        return self.last_page != self.page

    @property
    def agrees(self) -> bool | None:
        """Whether the numeral it sits beside is the one it names.

        ``None`` when either is unknown, which is not the same as a
        disagreement: most citations name no numeral of the article at all —
        ``CPR Art.19° D.O. 24.10.1980`` says where the text came from, not what
        it amends — and calling those disagreements would bury the real ones.
        """
        if self.beside is None or self.named is None:
            return None
        return self.beside == self.named

    def as_dict(self) -> dict[str, Any]:
        """The sidecar's form of this citation."""
        return {
            "text": self.text,
            "page": self.page,
            "first_line": self.first_line,
            "last_page": self.last_page,
            "last_line": self.last_line,
            "crosses_page": self.crosses_page,
            "beside": self.beside,
            "named": self.named,
            "agrees": self.agrees,
        }


def join_source_notes(rows: Sequence[Row]) -> list[Citation]:
    """Join margin rows into the citations they were printed as.

    A margin row on its own is a fragment that names nothing, and handing those
    rows to a reader as ``source_notes`` does not merely lose the citation — it
    invents several. ``'único'`` and ``'16.06.1999'`` read as notes in their own
    right, and so does ``'2'`` from ``Art. ÚNICO N° 1 y 2``.

    A citation opens where a row *begins* with the law it cites and runs to the
    row before the next such row, which is the whole rule. It is the row's first
    token that decides and not any token the row contains: a citation is a run of
    rows that has already opened, so a law named further along a row is a law
    being cited by the citation that is running, and reading the row from
    anywhere would cut that citation's tail off as a record of its own.

    Nothing is dropped: a row that opens no citation either continues the one
    above it or, when nothing is open, opens one itself, so the first row of a
    margin never goes missing.

    The rule is biased towards joining on purpose. A law token outside the
    vocabulary merges two citations into one, where splitting on a guess would
    invent a citation the document does not contain — and inventing is the
    failure this function exists to prevent.
    """
    citations: list[Citation] = []
    opened: Row | None = None
    closed: Row | None = None
    parts: list[str] = []

    def flush() -> None:
        nonlocal opened, closed, parts
        if opened is not None and closed is not None:
            citations.append(Citation(
                text=collapse_whitespace(" ".join(parts)),
                page=opened[0],
                first_line=opened[1],
                last_page=closed[0],
                last_line=closed[1],
            ))
        opened = closed = None
        parts = []

    for row in rows:
        if opened is None or _CITATION_START_RE.match(row[2]):
            flush()
            opened = row
        closed = row
        parts.append(row[2])
    flush()
    return citations


def article_numerals(rows: Sequence[Row]) -> list[tuple[int, int, int]]:
    """``(page, row, number)`` for every body row that opens a numeral.

    This shape is a hint about layout and is used only to say which numeral a
    citation *sits beside*. A body line that merely begins like a numeral — a
    numbered list inside a numeral's own text — moves a label, and a label a few
    rows out is a smaller wrong than a body line taken for a heading.
    """
    marks: list[tuple[int, int, int]] = []
    for page, line, text in rows:
        match = _NUMERAL_MARK_RE.match(text)
        if match:
            marks.append((page, line, int(match.group("number"))))
    return marks


def _numeral_at(
    marks: Sequence[tuple[int, int, int]], page: int, row: int
) -> int | None:
    """The number of the numeral whose text ``(page, row)`` falls inside.

    ``None`` before the article's first numeral, which is where a decree's
    promulgation clause and its title sit — those rows are body text, and giving
    them a numeral would invent one.
    """
    best: tuple[int, int] | None = None
    found: int | None = None
    for mark_page, mark_row, number in marks:
        position = (mark_page, mark_row)
        if position > (page, row):
            continue
        if best is None or position > best:
            best, found = position, number
    return found


def attribute_citations(
    citations: Sequence[Citation], marks: Sequence[tuple[int, int, int]]
) -> list[Citation]:
    """Record which numeral each citation sits beside, and which it names.

    Two answers, kept apart because on a real document they are different
    questions and not always the same answer. The margin column flows on its own
    grid, so a citation is printed a few rows past the numeral it belongs to:
    measured on the reference decree, ``CPR Art. 19° N° 13`` sits beside numeral
    14 and ``CPR Art. 19° N° 14`` beside 15. Collapsing the two into one
    ``numeral`` field would have made four of that document's fifty-six
    citations silently wrong, with nothing in the record to say which four.

    The disagreement is kept rather than resolved, because it is true and it is
    useful: it says the margin is an index and not an authority, so a reader who
    needs to know which numeral a law amended has to go and look rather than
    trust the column position.
    """
    attributed: list[Citation] = []
    for citation in citations:
        match = _CITATION_NUMERAL_RE.search(citation.text)
        attributed.append(replace(
            citation,
            beside=_numeral_at(marks, citation.page, citation.first_line),
            named=int(match.group("number")) if match else None,
        ))
    return attributed


@dataclass(frozen=True)
class PdfReading:
    """What was read out of a PDF, and what was done to get there.

    ``text`` is the reading handed to the verification protocol, so it is the
    only field anything matches against. Everything else is the account of it:
    which extractor and version produced it, which gutter was found, which
    margin citations were set aside, and how much furniture was dropped. The
    account is not decoration — a `matched_offset` in a verification record
    means nothing without knowing which string it was measured in, and the
    difference between a raw reading and a restructured one is exactly the kind
    of change that makes a stored offset quietly wrong.
    """

    text: str
    page_count: int
    raw_chars: int
    raw_sha256: str
    gutter: int | None = None
    gutter_support: int = 0
    notes: tuple[dict[str, Any], ...] = ()
    notes_chars: int = 0
    citations: tuple[Citation, ...] = ()
    numerals: tuple[tuple[int, int, int], ...] = ()
    furniture: tuple[str, ...] = ()
    furniture_lines: int = 0
    furniture_chars: int = 0
    extractor: str | None = None
    extractor_version: str | None = None

    @property
    def restructured(self) -> bool:
        """Whether the reading differs from the plain extraction at all."""
        return self.gutter is not None or bool(self.furniture)

    def derivation(self) -> dict[str, Any]:
        """The sidecar's account of how ``text`` was produced."""
        return {
            "extractor": self.extractor,
            "extractor_version": self.extractor_version,
            "pages": self.page_count,
            "columns_split": self.gutter is not None,
            "gutter_column": self.gutter,
            "gutter_support": self.gutter_support,
            "notes": len(self.notes),
            "notes_chars": self.notes_chars,
            "citations": [citation.as_dict() for citation in self.citations],
            "numerals": [
                {"page": page, "row": row, "number": number}
                for page, row, number in self.numerals
            ],
            "furniture_lines": self.furniture_lines,
            "furniture_chars": self.furniture_chars,
            "furniture": list(self.furniture),
        }


def derive_reading(
    pages: Sequence[str],
    *,
    extractor: str | None = None,
    extractor_version: str | None = None,
) -> PdfReading:
    """Turn pages of extracted text into the reading the protocol searches.

    ``raw_chars``/``raw_sha256`` describe the plain extraction — every word the
    reader saw, joined and collapsed — so the restructured reading can always be
    compared against what it came from. They are what let a stored proof be
    recognised as *the same document, read better*, which a single hash of the
    cleaned text cannot say.
    """
    raw = collapse_whitespace(" ".join(pages))
    gutter = detect_gutter(pages)
    body_rows, note_rows = split_columns(pages, gutter[0] if gutter else None)
    kept, removed = strip_repeated_furniture(body_rows)
    # The numerals are found in the body that is left, so a numeral whose marker
    # was itself running furniture is never offered as an anchor. The citations
    # are joined *before* they are attributed, because a fragment names no
    # numeral: attributing rows instead of citations attaches the `2` of
    # `Art. ÚNICO N° 1 y 2` to whichever numeral happened to be above it.
    numerals = article_numerals(kept)
    citations = attribute_citations(join_source_notes(note_rows), numerals)
    return PdfReading(
        text=collapse_whitespace(" ".join(text for _, _, text in kept)),
        page_count=len(pages),
        raw_chars=len(raw),
        raw_sha256=_sha256(raw.encode("utf-8")),
        gutter=gutter[0] if gutter else None,
        gutter_support=gutter[1] if gutter else 0,
        notes=tuple(
            {"page": page, "line": line, "text": text} for page, line, text in note_rows
        ),
        notes_chars=sum(len(text) for _, _, text in note_rows),
        citations=tuple(citations),
        numerals=tuple(numerals),
        furniture=tuple(dict.fromkeys(_repeat_key(text) for _, _, text in removed)),
        furniture_lines=len(removed),
        furniture_chars=sum(len(text) for _, _, text in removed),
        extractor=extractor,
        extractor_version=extractor_version,
    )


def _module_version(module_name: str) -> str | None:
    """The reader's own version, or ``None`` when it cannot be determined.

    Recorded because the reading depends on it: two releases of ``pypdf`` do not
    place the same characters on the same line, so a bundle read by one and
    re-read by the other has a different text for the same file. The version is
    the only thing in the record that makes that difference visible.
    """
    from importlib import metadata

    for candidate in (module_name, module_name.lower()):
        try:
            return metadata.version(candidate)
        except (metadata.PackageNotFoundError, ValueError):
            continue
    return None


def extract_pdf_reading(data: bytes) -> tuple[PdfReading | None, str | None, list[str]]:
    """Read a PDF into a `PdfReading` with whichever optional reader is installed.

    Returns ``(reading, extractor, warnings)``. With no reader installed the
    reading is ``None`` and the warning names the install — but the artefact is
    still ingested by the caller, so the proof is never lost just because the
    venv is missing a parser.
    """
    tried: list[str] = []
    for module_name, reader in _PDF_EXTRACTORS:
        try:
            __import__(module_name)
        except ImportError:
            tried.append(module_name)
            continue
        try:
            pages = reader(data)
        except Exception as exc:  # noqa: BLE001 - a broken PDF must not 500
            return None, module_name, [
                f"{module_name} is installed but could not read this PDF "
                f"({type(exc).__name__}: {exc}); paste the section text instead",
            ]
        return derive_reading(
            pages, extractor=module_name, extractor_version=_module_version(module_name)
        ), module_name, []
    return None, None, [
        "no PDF text extractor is installed (" + ", ".join(tried) + "); the PDF "
        "is stored and hashed as proof, but paste the passage you want matched "
        "or install pypdf (`pip install pypdf`, or the pdf extra) to have it "
        "read here",
    ]


def extract_pdf_text(data: bytes) -> tuple[str | None, str | None, list[str]]:
    """The reading alone, for callers that do not need the account of it.

    Kept because "give me the text of this PDF" is the question most callers are
    asking, and threading a `PdfReading` through all of them would spread the
    layout pass into code that has no opinion about columns. `ingest_source`
    uses `extract_pdf_reading` instead, because a stored proof is precisely the
    caller that does need the account.
    """
    reading, extractor, warnings = extract_pdf_reading(data)
    return (reading.text if reading is not None else None), extractor, warnings


# ---------------------------------------------------------------------------
# Filenames
# ---------------------------------------------------------------------------

_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_STEM = 80
_MAX_SUFFIX = 8


def sanitise_filename(name: str, *, fallback: str = "source") -> str:
    """Reduce a client-supplied filename to a safe single path component.

    The browser controls this string entirely, so it is treated as hostile:
    both separators are handled (a Windows client sends ``C:\\\\tmp\\\\x.pdf``),
    any remaining punctuation outside ``[A-Za-z0-9._-]`` becomes ``-``, and a
    leading dot is stripped so a name can never be a dotfile or a ``..`` hop.
    The extension is preserved because it decides how the bytes are read.
    """
    raw = str(name or "").replace("\\", "/")
    base = raw.rsplit("/", 1)[-1]
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    suffix = Path(base).suffix.lower()
    if len(suffix) > _MAX_SUFFIX or not re.fullmatch(r"\.[a-z0-9]+", suffix or ""):
        suffix = ""
    stem = base[: len(base) - len(Path(base).suffix)] if suffix else base
    stem = _UNSAFE_RE.sub("-", stem).strip("-.")
    if not stem:
        stem = fallback
    return (stem[:_MAX_STEM] or fallback) + suffix


def name_from_url(url: str) -> str:
    """A readable filename for a fetched page, derived from the URL.

    The host is included because two governments' ``/navegar?idNorma=…`` paths
    are otherwise indistinguishable in a bundle listing, and the query string
    is included because for ``bcn.cl`` the norma id *is* the query. The
    extension here is only a default: ``fetched_filename`` replaces it from the
    served content type, because the extension is what selects the reader.
    """
    parts = _urlparse.urlsplit(url)
    host = (parts.netloc or "source").replace(":", "-")
    tail = parts.path.rstrip("/").rsplit("/", 1)[-1] or "index"
    query = parts.query.replace("&", "-").replace("=", "-")
    stem = "-".join(part for part in (host, tail, query) if part)
    name = sanitise_filename(stem + ".txt")
    return Path(name).stem[:_MAX_STEM] + ".txt"


#: What a served content type means for the file this module stores. A served
#: page is kept as ``.html`` rather than the ``.txt`` default so the same reader
#: that handles an uploaded page handles it — a page whose tags survive reaches
#: the verification protocol as markup and no quote the reviewer can *see* will
#: match it.
_CONTENT_TYPE_SUFFIX = {
    "text/html": ".html",
    "application/xhtml+xml": ".html",
    "application/xml": ".xml",
    "text/xml": ".xml",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "application/json": ".json",
    "text/csv": ".csv",
    "application/pdf": ".pdf",
    "application/x-pdf": ".pdf",
}


def _suffix_for_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    return _CONTENT_TYPE_SUFFIX.get(content_type.split(";", 1)[0].strip().lower())


def _looks_like_markup(data: bytes | None) -> bool:
    """Whether the bytes open as a tag — i.e. are a page served as text/plain."""
    if not data:
        return False
    head = data[:1024]
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    return head.lstrip().startswith(b"<") and b">" in data[:4096]


def fetched_filename(url: str, content_type: str | None, data: bytes) -> str:
    """The name a fetched response is stored under.

    The content type wins, then the bytes get a say: an unmapped or dishonest
    content type is common enough (``application/octet-stream`` for a PDF,
    ``text/plain`` for a page) that trusting the header alone would silently
    pick the wrong reader.
    """
    stem = Path(name_from_url(url)).stem
    suffix = _suffix_for_content_type(content_type)
    if suffix is None and (data or b"")[:5] == b"%PDF-":
        suffix = ".pdf"
    if _looks_like_markup(data) and suffix not in MARKUP_SUFFIXES:
        suffix = ".html"
    return f"{stem}{suffix or '.bin'}"


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

#: Hosts the server refuses to call. The verification workflow only ever wants
#: public legal sources, so a URL that points back into the machine running the
#: server has no legitimate use — and this route is reachable by anything that
#: can reach the port.
_BLOCKED_HOST_RE = re.compile(
    r"^(?:localhost|0\.0\.0\.0|\[?::1\]?|127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+"
    r"|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+|169\.254\.\d+\.\d+)"
    r"|\.local$|\.internal$",
    re.IGNORECASE,
)


def url_refusal_reason(url: str) -> str | None:
    """Explain why a URL may not be fetched, or ``None`` when it may.

    Host checks only, and that is stated plainly rather than papered over: a
    public hostname that resolves to a loopback address still gets through,
    because closing that needs a DNS lookup and a pinned IP. This guard exists
    to refuse the obvious shortcuts, not to be an SSRF boundary.
    """
    if not isinstance(url, str) or not url.strip():
        return "no url was supplied"
    parts = _urlparse.urlsplit(url.strip())
    if parts.scheme not in {"http", "https"}:
        return (
            f"url scheme {parts.scheme or '(none)'!r} is not fetchable; "
            "only http and https are accepted"
        )
    if not parts.netloc:
        return "the url has no host"
    host = parts.netloc.rsplit("@", 1)[-1].split(":")[0]
    if _BLOCKED_HOST_RE.search(host):
        return f"refusing to fetch {host!r} — loopback and private hosts are not source material"
    return None


def fetch_url(
    url: str,
    *,
    timeout: float = FETCH_TIMEOUT,
    max_bytes: int = MAX_FETCH_BYTES,
    opener: Callable[[str], tuple[bytes, str, str]] | None = None,
) -> dict[str, Any]:
    """Fetch an authoritative page and return its bytes plus provenance.

    ``opener`` is injectable so the whole ingest path can be tested without a
    network, the same seam ``llm.py`` uses for its transport. The default
    opener is ``urllib`` (already used by ``embeddings.py``) so this feature
    adds no dependency, and it sends a browser-shaped User-Agent: several
    Chilean institutional hosts answer the bare ``Python-urllib`` agent with a
    403 that reads like an authorisation problem.
    """
    reason = url_refusal_reason(url)
    if reason:
        raise SourceError(reason)

    if opener is None:
        def opener(target: str) -> tuple[bytes, str, str]:  # noqa: E306 - local default
            request = _urlreq.Request(target, headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9,*/*;q=0.5",
                "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
            })
            with _urlreq.urlopen(request, timeout=timeout) as response:  # noqa: S310 - scheme checked above
                return (
                    response.read(max_bytes + 1),
                    response.headers.get_content_type(),
                    response.geturl(),
                )

    try:
        data, content_type, final_url = opener(url)
    except _urlerr.HTTPError as exc:
        raise SourceError(
            f"the source answered HTTP {exc.code} for {url} — open the page in a "
            "browser, save it, and upload the file instead"
        ) from exc
    except _urlerr.URLError as exc:
        raise SourceError(f"could not reach {url} ({exc.reason})") from exc
    except Exception as exc:  # noqa: BLE001 - injected openers raise anything
        raise SourceError(f"could not fetch {url} ({type(exc).__name__}: {exc})") from exc

    if len(data) > max_bytes:
        raise SourceError(
            f"{url} returned more than {max_bytes // (1024 * 1024)} MiB; "
            "save the relevant part and upload it instead"
        )
    return {
        "bytes": data,
        "content_type": content_type,
        "final_url": final_url,
        "status": 200,
    }


# ---------------------------------------------------------------------------
# Storing the proof inside the bundle
# ---------------------------------------------------------------------------

def sources_dir(bundle_dir: Path) -> Path:
    """``<bundle>/Authority sources/``, created on demand."""
    directory = bundle_dir / SOURCES_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _unique_path(directory: Path, stem: str, suffix: str, data: bytes) -> tuple[Path, bool]:
    """Pick a free name for ``stem+suffix``, or reuse the identical file.

    Returns ``(path, reused)``. Re-uploading the same document must not mint a
    second copy, and re-uploading a *different* document under the same name
    must not destroy the proof that was stored first — an overwrite here would
    erase the artefact a previous verification pinned.
    """
    candidate = directory / f"{stem}{suffix}"
    counter = 2
    while candidate.exists():
        if candidate.read_bytes() == data:
            return candidate, True
        candidate = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate, False


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def ingest_source(
    bundle_dir: Path,
    authority_id: str,
    *,
    source_url: str | None = None,
    filename: str | None = None,
    data: bytes | None = None,
    text: str | None = None,
    do_fetch: bool = False,
    collapse: bool = False,
    opener: Callable[[str], tuple[bytes, str, str]] | None = None,
) -> dict[str, Any]:
    """Store the official source for one authority and return the text to verify.

    Exactly one of ``data`` (an uploaded document), ``text`` (pasted) or
    ``do_fetch`` (download ``source_url``) supplies the content, and any
    combination is allowed: an uploaded PDF plus pasted text is the normal case
    for jurisprudence, where the PDF is the proof and the pasted passage is what
    the protocol can actually search.

    Nothing is written until the content is in hand, so a failed fetch or a
    refused URL leaves the bundle exactly as it was.
    """
    warnings: list[str] = []
    if not isinstance(bundle_dir, Path):
        raise SourceError("bundle_dir must be a Path")
    if not bundle_dir.is_dir():
        raise SourceError(f"bundle directory {bundle_dir} does not exist")
    if not (bundle_dir / f"{bundle_dir.name}.json").is_file():
        raise SourceError(f"{bundle_dir.name} is not a bundle (no {bundle_dir.name}.json)")
    if not str(authority_id or "").strip():
        raise SourceError("authority_id is required")

    if data is not None and len(data) > MAX_UPLOAD_BYTES:
        raise SourceError(
            f"the upload is {len(data) // (1024 * 1024)} MiB, over the "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit"
        )

    fetched: dict[str, Any] | None = None
    # Only fetch what is not already in hand: a request carrying both an upload
    # and a url is asking to record the url, not to make a pointless request.
    if do_fetch and data is None:
        if not source_url:
            raise SourceError("do_fetch needs a source_url")
        fetched = fetch_url(source_url, opener=opener)
        data = fetched["bytes"]
        if filename is None:
            filename = fetched_filename(
                fetched["final_url"] or source_url, fetched.get("content_type"), data
            )

    if data is None and not (text or "").strip():
        raise SourceError("supply an uploaded document, pasted text, or a url to fetch")

    # --- the artefact ------------------------------------------------------
    # The extension decides how the bytes are read, so it is never dropped: a
    # client that sends no filename at all still gets a `.pdf` when the payload
    # sniffs as one, which is the only case where the bytes are self-describing.
    if not filename:
        if data is not None and data[:5] == b"%PDF-":
            filename = f"{authority_id}__upload.pdf"
        else:
            filename = f"{authority_id}__{'upload.bin' if data is not None else 'note.txt'}"
    elif data is not None and not filename.startswith(f"{authority_id}__"):
        # Prefix the reviewer's filename with the authority id. Two stubs
        # verified against two different sentencias otherwise land as
        # `sentencia.pdf` and `sentencia-2.pdf`, and the bundle no longer says
        # which proof belongs to which proposition — the one question this
        # directory exists to answer.
        #
        # Skipped when the name already carries it, because the file the
        # reviewer just picked may *be* this bundle's own stored copy: re-reading
        # a bundle then prefixed it a second time, and since the name differs
        # `_unique_path` cannot recognise the bytes, so the same document was
        # stored twice and the sidecar pointed at the copy.
        filename = f"{authority_id}__{filename}"
    filename = sanitise_filename(filename)
    suffix = Path(filename).suffix.lower()

    artefact_text: str | None = None
    extractor: str | None = None
    reading: PdfReading | None = None
    if data is not None:
        if suffix == ".pdf" or data[:5] == b"%PDF-":
            reading, extractor, pdf_warnings = extract_pdf_reading(data)
            artefact_text = reading.text if reading is not None else None
            warnings.extend(pdf_warnings)
        elif suffix in TEXT_SUFFIXES:
            artefact_text, warnings_dec = decode_bytes(data)
            warnings.extend(warnings_dec)
            if suffix in MARKUP_SUFFIXES:
                artefact_text = strip_markup(artefact_text)
                extractor = "html-strip"
        else:
            warnings.append(
                f"{suffix or 'a binary file'} is stored as proof but carries no "
                "readable text; paste the passage you want matched"
            )
    elif fetched is not None:
        # Unreachable: a fetch always supplies `data` above. Kept explicit so the
        # branches read symmetrically if that ever changes.
        artefact_text = None

    pasted = (text or "").strip() or None
    content = pasted or artefact_text
    if collapse and content:
        content = collapse_whitespace(content)
    # An artefact with no readable text is a legitimate outcome, not a failure:
    # a scanned PDF is proof of the source even though nothing here can quote
    # it, and refusing it would throw away the only copy the reviewer has. The
    # caller is told (`needs_text`) instead of being handed an error that
    # describes a document the bundle would then not contain.
    needs_text = content is None
    content_sha = _sha256(content.encode("utf-8")) if content is not None else None

    # What kind of string `content` is. A reader of the record has to be able to
    # tell a reading of the artefact from a passage a human typed, because the
    # first can be reproduced from the bundle and the second cannot: an offset
    # into a pasted string proves the quote is *in the quote*, and nothing about
    # the document. That distinction was previously visible only to whoever
    # remembered which request they had sent.
    if pasted is not None:
        basis = "pasted"
    elif reading is not None:
        basis = "pdf"
    elif extractor == "html-strip":
        basis = "markup"
    elif artefact_text is not None:
        basis = "text"
    else:
        basis = None

    # --- write everything --------------------------------------------------
    directory = sources_dir(bundle_dir)
    artefact: dict[str, Any] | None = None
    if data is not None:
        path, reused = _unique_path(directory, Path(filename).stem, suffix, data)
        if not reused:
            path.write_bytes(data)
        artefact = {
            "name": path.name,
            "rel": f"{SOURCES_DIR}/{path.name}",
            "path": str(path),
            "sha256": _sha256(data),
            "bytes": len(data),
            "reused": reused,
        }
        stem = path.name[: len(path.name) - len(suffix)]
    else:
        stem = Path(filename).stem

    # The text is stored separately whenever it is not already the artefact's
    # own bytes — a PDF, an HTML page, an upload whose reading disagreed with
    # what the reviewer pasted. Without this the bundle would hold a document
    # whose SHA256 is nowhere in the record and a hash whose text is nowhere on
    # disk, and `text_sha256` would only be checkable by re-running the very
    # reader a reviewer may not have installed.
    #
    # The comparison is against the bytes, not against `artefact_text`: a PDF
    # that reads *cleanly* has `artefact_text == content`, so asking the reading
    # whether the text is already on disk answers "yes" for the one format where
    # the text is certainly not on disk. Only bytes can answer that question.
    text_rel: str | None = None
    if content is not None and (data is None or data != content.encode("utf-8")):
        text_name = f"{stem}{TEXT_SUFFIX}"
        (directory / text_name).write_text(content, encoding="utf-8")
        text_rel = f"{SOURCES_DIR}/{text_name}"

    if source_url:
        source_uri = source_url
    elif artefact is not None:
        source_uri = artefact["rel"]
    else:
        source_uri = text_rel or f"{SOURCES_DIR}/{filename}"

    proof = {
        "authority_id": authority_id,
        "violation_id": bundle_dir.name,
        "source_url": source_url,
        "source_uri": source_uri,
        "fetched": bool(fetched),
        "final_url": (fetched or {}).get("final_url"),
        "content_type": (fetched or {}).get("content_type"),
        "artefact": artefact,
        "text_file": text_rel,
        "text_sha256": content_sha,
        "text_chars": len(content) if content is not None else 0,
        "needs_text": needs_text,
        "text_source": (
            "pasted" if pasted is not None else
            "fetched" if fetched is not None else
            "upload"
        ),
        "extractor": extractor,
        "whitespace_collapsed": bool(collapse),
        "schema_version": PROOF_SCHEMA_VERSION,
        # The one thing a stored proof must never leave to inference: which
        # string the quote was searched for in. `matched` is the reading the
        # protocol hashed — it is the text file on disk — and `raw` is what the
        # extractor produced before this module touched it, so a recording whose
        # reading was restructured can always be compared against the reading it
        # was restructured from.
        "readings": {
            "matched": {
                "sha256": content_sha,
                "chars": len(content) if content is not None else 0,
                "basis": basis,
            },
            "raw": (
                {"sha256": reading.raw_sha256, "chars": reading.raw_chars}
                if reading is not None else None
            ),
            "derivation": reading.derivation() if reading is not None else None,
        },
        # The margin column, kept rather than discarded: it is the amendment
        # history of the very numeral the reviewer is quoting, so it is evidence
        # for `instrument` and `version`, and it is also the text that had to be
        # taken out of the body reading to make that reading quotable at all.
        "notes": list(reading.notes) if reading is not None else [],
        # The same column, joined into the records it was printed as. `notes`
        # above is the audit trail — every row that was set aside, so nothing can
        # go missing quietly — and this is what those rows say, which is what a
        # reader actually wants. A citation carries the span it came from, so it
        # can always be taken back to the rows it was joined from.
        "citations": (
            [citation.as_dict() for citation in reading.citations]
            if reading is not None
            else []
        ),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "warnings": warnings,
    }
    proof_path = write_json(directory / f"{stem}{PROOF_SUFFIX}", proof)

    return {
        "ok": True,
        "authority_id": authority_id,
        "source_uri": source_uri,
        # The exact string the caller must hand the verification protocol: the
        # protocol re-hashes it, and this hash is what the sidecar records, so
        # the two can only agree if the text is passed through untouched. It is
        # None when nothing readable came out of the artefact, and the caller is
        # then expected to send text back rather than guess a quote.
        "source_content": content,
        "needs_text": needs_text,
        "text_sha256": content_sha,
        "chars": len(content) if content is not None else 0,
        "text_source": proof["text_source"],
        "extractor": extractor,
        "artefact": artefact,
        # How the reading was arrived at, for the modal to be able to say what it
        # did — "read as two columns, 151 margin citations recorded separately"
        # is the difference between a reviewer trusting a quote and a reviewer
        # wondering why the text on screen is not the text in the PDF.
        "reading": reading.derivation() if reading is not None else None,
        # The fetch provenance is repeated here because the modal has to be able
        # to say where the text came from — the content type is what chose the
        # reader, and a redirect means the page fetched is not the page named.
        # The sidecar stays the durable record; this is the same facts, readable
        # without a second request.
        "fetched": proof["fetched"],
        "final_url": proof["final_url"],
        "content_type": proof["content_type"],
        "proof": {
            "name": proof_path.name,
            "rel": f"{SOURCES_DIR}/{proof_path.name}",
            "path": str(proof_path),
        },
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Removing a stored proof
# ---------------------------------------------------------------------------

def proof_stem(name: str) -> str:
    """The stem shared by every file of one stored source.

    Both companions of an artefact are multi-part suffixes, and ``Path.suffix``
    peels off only the last component of one: ``X.proof.json`` would come back as
    ``X.proof``, so the sidecar would look like a source of its own and deleting
    the document would leave it behind pointing at a file that is no longer
    there. The two known companions are therefore stripped first, longest first so
    ``.proof.json`` cannot be read as a bare ``.json``, and only then the
    artefact's own extension.

    The rule is deliberately *not* injective: an upload whose own name ends in
    ``.text.txt`` shares a stem with its companions only by accident, so its files
    show as two entries rather than one. Two entries a reviewer can each delete is
    the safe failure — guessing harder means a prefix rule, and a prefix rule lets
    deleting ``X.pdf`` take an unrelated ``X.anexo.pdf`` with it.
    """
    base = Path(str(name or "")).name
    for suffix in (PROOF_SUFFIX, TEXT_SUFFIX):
        if base.endswith(suffix) and len(base) > len(suffix):
            return base[: -len(suffix)]
    return base[: len(base) - len(Path(base).suffix)]


def proof_group(directory: Path, name: str) -> list[Path]:
    """The files that make up the source one of whose files is ``name``.

    Ingest writes the artefact, its ``.proof.json`` sidecar and — whenever the
    text is not the artefact's own bytes — the matched ``.text.txt``, all three
    off one stem. Scanning the directory and comparing stems, rather than
    rebuilding the three names, is what keeps this right for a source with no text
    file at all (pasted text, a PDF handed to the protocol as the artefact itself)
    and for the second copy ``_unique_path`` mints as ``X-2.pdf``: a distinct stem
    is a distinct source, and is deleted on its own.

    Files that do not exist are never returned, so the caller's list is exactly
    what is about to be removed.
    """
    stem = proof_stem(name)
    if not stem or stem in {".", ".."}:
        return []
    return sorted(
        (path for path in directory.iterdir()
         if path.is_file() and proof_stem(path.name) == stem),
        key=lambda path: path.name,
    )


def _stored_source_group(
    bundle_dir: Path, authority_id: str, name: str, *, action: str
) -> tuple[Path, str, list[Path]]:
    """Resolve one stored source of ``authority_id`` from any one of its file names.

    Shared by the two verbs that reach a source already on disk — reading it back
    and removing it — because "which files are this stub's source" has to be one
    answer. Two copies of the rule drift, and the copy that drifts *downwards* is
    the one that hands `delete_source` a name it should have refused.

    Every refusal here is about what may be reached rather than about the request
    being well formed, and ``action`` only supplies the verb those refusals are
    worded with (the messages go straight to the browser). It is the past
    participle, in a passive: ``read`` and ``removed`` are the two callers, and
    both have to read as the answer to a click a reviewer just made.

    - The name must be a plain file name. A NUL byte, ``a/b`` and ``..\\x`` are all
      traversal attempts arriving as "a filename", and `Path()` raises on the first
      of them rather than returning it, so all three are checked before `Path()`
      sees the string.
    - It must carry the ``<authority_id>__`` prefix ingest writes. A name belonging
      to another stub is a real limit and not an oversight: a stub whose id was
      edited after its proof was stored keeps that proof on disk, and it has to be
      reached on the filesystem rather than from here.
    - The path built from it must still be a direct child of ``Authority sources/``.
      Belt and braces, exactly as `resolve_bundle_dir` does it: the name is
      separator-free by now, and this confirms the resolution anyway before
      anything is read or unlinked.
    - The file it names must exist. This is *not* redundant with the group being
      non-empty, because the group is found by *stem*: naming a companion that was
      never written — ``X.proof.json`` for a source stored as ``X.pdf`` alone —
      resolves to the very group the real document is in. Without this check the
      name given is never verified against the filesystem at all, and a request for
      a file that does not exist reaches one that does. The action is named in the
      past tense because a repeated click on Remove must be told the file is gone
      rather than handed a success it did not have.
    """
    if not isinstance(bundle_dir, Path):
        raise SourceError("bundle_dir must be a Path")
    if not bundle_dir.is_dir():
        raise SourceError(f"bundle directory {bundle_dir} does not exist")
    if not (bundle_dir / f"{bundle_dir.name}.json").is_file():
        # The same gate `ingest_source` applies. Here it is not about where a file
        # would be written but about what may be reached: `delete_source` is the
        # only function in the module that destroys anything, so it refuses to
        # touch a directory that is not a bundle even if it happens to hold an
        # `Authority sources/` of its own.
        raise SourceError(f"{bundle_dir.name} is not a bundle (no {bundle_dir.name}.json)")
    if not str(authority_id or "").strip():
        raise SourceError("authority_id is required")
    authority_id = authority_id.strip()

    raw = str(name or "")
    if (
        not raw.strip()
        or any(char in raw for char in ("/", "\\", "\x00"))
        or raw != Path(raw).name
    ):
        raise SourceError(f"{raw!r} is not a file name — no source was {action}")
    if not raw.startswith(f"{authority_id}__"):
        raise SourceError(
            f"{raw} is not a stored source of {authority_id}; only a file this "
            f"stub wrote can be {action} from here"
        )

    directory = bundle_dir / SOURCES_DIR
    if not directory.is_dir():
        raise SourceError(f"no {SOURCES_DIR}/ directory in {bundle_dir.name}")
    if (directory / raw).parent.resolve() != directory.resolve():
        raise SourceError(f"{raw!r} does not resolve inside {SOURCES_DIR}/")
    if not (directory / raw).is_file():
        # `is_file` follows a symlink, so a link to a real file inside the bundle
        # resolves and a dangling one does not; `delete_source` unlinks the link
        # itself and never its target, which is covered where that happens.
        raise SourceError(f"no stored source named {raw} under {SOURCES_DIR}/")

    return directory, raw, proof_group(directory, raw)


def delete_source(bundle_dir: Path, authority_id: str, name: str) -> dict[str, Any]:
    """Remove one stored source: the document, its sidecar and its matched text.

    The three go together because the two companions are meaningless without the
    document. A sidecar left behind names a file the bundle no longer holds, so it
    would go on claiming a proof that is not there — the one question this
    directory exists to answer.

    The caller names *one* file and this function decides what else goes with it,
    from the bundle. That matters because deleting proof is irreversible and the
    bundle may hold the only copy: a browser that got the grouping wrong — or that
    sent a name on purpose — must not be able to reach a file the reviewer was
    never shown. The guards that stand in front of the unlink are therefore about
    *what may be deleted* rather than about the request being well formed, and they
    live in `_stored_source_group` because reading a source back needs exactly the
    same ones.

    Refusing a name that belongs to another stub is a real limit, not an oversight:
    a stub whose id was edited after its proof was stored keeps that proof on disk
    and it is listed bundle-wide in the modal, but it has to be removed from the
    filesystem rather than from here.
    """
    directory, raw, group = _stored_source_group(
        bundle_dir, authority_id, name, action="removed"
    )

    removed: list[str] = []
    freed = 0
    for path in group:
        try:
            freed += path.stat().st_size
            path.unlink()
        except OSError as exc:
            raise SourceError(
                f"could not remove {path.name} ({exc}); {len(removed)} of "
                f"{len(group)} file(s) of this source are already gone"
            ) from exc
        removed.append(f"{SOURCES_DIR}/{path.name}")

    return {
        "ok": True,
        "authority_id": authority_id,
        "name": raw,
        # Bundle-relative, in the same shape as `artefact.rel`. That makes them
        # directly comparable with the `source_uri` a verification records, which
        # is how a caller can tell that a saved provenance now points at nothing.
        # A source that was fetched by url records the *url* as its `source_uri`,
        # however, so nothing here matches it — correctly: the local copy is gone
        # but the page it cites is not.
        "deleted": removed,
        "freed_bytes": freed,
    }


# ---------------------------------------------------------------------------
# Reading a stored proof back
# ---------------------------------------------------------------------------

def read_source(bundle_dir: Path, authority_id: str, name: str) -> dict[str, Any]:
    """Read back one stored source: its sidecar record and the text it was searched in.

    `ingest_source` returns the text it has just read, so the modal could show a
    source the reviewer had loaded a moment ago — and nothing else. A source stored
    in an earlier session is on disk and listed under "Proof on disk", but there was
    no way to ask the bundle what it says, which made the reading, the margin
    citations and the numerals *write-only*: legible by opening the `.proof.json` in
    an editor, and invisible to the page that had just recorded them. That is
    backwards. The recorder is where someone would go to check the recording.

    Two fields deserve saying out loud, because they are the two ways a caller can
    be misled and neither is visible from the file listing:

    - ``reading_recorded``. A sidecar written before the reading was recorded has no
      ``readings`` key at all, and an empty citation list then means "nothing was
      looked for" rather than "nothing was there". A reader handed those two as one
      would conclude this document has no margin, which is a claim about the
      document that this record does not make.
    - ``warnings``. The text is returned with the hash of the bytes on disk *and*
      the hash the record gives, and the comparison is made here rather than left to
      the caller. A text file that no longer hashes to its own record is the one
      failure this function can meet that a reviewer cannot see for themselves: the
      sidecar would go on naming a SHA256 that the file under it does not have, and
      every quote matched against that text would be attributed to a document the
      record does not describe. The text is still returned — a caller that cannot
      see it can do nothing at all with the file — but it is never returned silently.

    Read-only: nothing here writes. The name is resolved by `_stored_source_group`,
    the same rule `delete_source` uses, so "a stored source of this stub" is one
    sentence in the module rather than one per verb.
    """
    directory, raw, group = _stored_source_group(
        bundle_dir, authority_id, name, action="read"
    )
    warnings: list[str] = []

    sidecar = next((path for path in group if path.name.endswith(PROOF_SUFFIX)), None)
    record: dict[str, Any] = {}
    if sidecar is None:
        # A document dropped into the directory by hand, or one whose sidecar was
        # removed on its own. The document is still listed and is still readable;
        # what is missing is the account of how it was read, and saying so is the
        # only honest answer — silently reporting "no margin citations" would be a
        # claim about a document nothing has read.
        warnings.append(
            f"no {PROOF_SUFFIX} beside {raw}, so there is no record of how this "
            "document was read"
        )
    else:
        try:
            loaded = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            warnings.append(f"could not read {sidecar.name} ({exc})")
        else:
            if isinstance(loaded, dict):
                record = loaded
            else:
                warnings.append(f"{sidecar.name} does not hold a record")

    readings = record.get("readings") if isinstance(record.get("readings"), dict) else {}
    derivation = readings.get("derivation") if isinstance(readings.get("derivation"), dict) else None

    # Where the text lives. Ingest writes it beside the document whenever the
    # reading is not the document's own bytes, and records `needs_text` when nothing
    # readable came out at all, so these two fields answer the question without the
    # reader having to guess a reader for the artefact.
    #
    # Both names come out of a file on disk, which makes them data and not
    # instructions: a sidecar edited by hand could name `../../etc/passwd`. The name
    # is therefore required to be exactly `Authority sources/<basename>` — the shape
    # this module writes — and anything else is reported rather than followed.
    def _sibling(rel: Any) -> Path | None:
        if not isinstance(rel, str) or not rel:
            return None
        wanted = Path(rel).name
        if rel != f"{SOURCES_DIR}/{wanted}" or not (directory / wanted).is_file():
            warnings.append(f"the record names {rel}, which is not a file of this source")
            return None
        return directory / wanted

    content: str | None = None
    text_rel = record.get("text_file") if isinstance(record.get("text_file"), str) else None
    if isinstance(text_rel, str) and text_rel:
        text_path = _sibling(text_rel)
        if text_path is not None:
            try:
                content = text_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                warnings.append(f"could not read {text_path.name} ({exc})")
    elif record and not record.get("needs_text"):
        # No text file and nothing recorded as unreadable, so the document *is* the
        # text: ingest writes a companion only when the reading differs from the
        # artefact's bytes, which is why this branch can only be reached for an
        # upload of plain text. The hash check below is what proves that reading of
        # the record rather than trusting it — bytes that are not the text the
        # record hashes cannot pass it.
        artefact = record.get("artefact") if isinstance(record.get("artefact"), dict) else {}
        artefact_path = _sibling(artefact.get("rel"))
        if artefact_path is not None:
            try:
                content, decode_warnings = decode_bytes(artefact_path.read_bytes())
            except OSError as exc:
                warnings.append(f"could not read {artefact_path.name} ({exc})")
            else:
                warnings.extend(decode_warnings)

    text_sha256 = _sha256(content.encode("utf-8")) if content is not None else None
    recorded_sha = record.get("text_sha256")
    if content is not None and isinstance(recorded_sha, str) and recorded_sha != text_sha256:
        warnings.append(
            "the text on disk no longer hashes to the SHA256 the record gives "
            f"({recorded_sha[:12]}… recorded, {str(text_sha256)[:12]}… on disk); "
            "the quote this source was verified with was matched in the other one"
        )

    # The document: everything of this stem that is neither the record nor the text
    # taken out of the document. Chosen from the group rather than from the record's
    # own `artefact.rel`, so a sidecar removed by hand does not also hide the file it
    # was written about.
    document = next(
        (
            path
            for path in group
            if path is not sidecar and not path.name.endswith(TEXT_SUFFIX)
        ),
        None,
    )

    return {
        "ok": True,
        "authority_id": authority_id,
        "name": raw,
        "stem": proof_stem(raw),
        "files": [f"{SOURCES_DIR}/{path.name}" for path in group],
        # The document itself, not the record of it, and found the way the group
        # knows it rather than by trusting the record's own copy of the name. The
        # page names the stored file from this — `stored as Authority sources/…` —
        # and a read that reported only the sidecar left that line blank on every
        # source stored in an earlier session. An `artefact` hashed here would be a
        # second opinion about a file the sidecar already hashes, so the record's
        # digest is repeated rather than recomputed.
        "artefact": (
            {
                "name": document.name,
                "rel": f"{SOURCES_DIR}/{document.name}",
                "path": str(document),
                "sha256": (
                    record["artefact"].get("sha256")
                    if isinstance(record.get("artefact"), dict) else None
                ),
                "bytes": document.stat().st_size,
            }
            if document is not None
            else None
        ),
        "sidecar": (
            {
                "name": sidecar.name,
                "rel": f"{SOURCES_DIR}/{sidecar.name}",
                "path": str(sidecar),
                "bytes": sidecar.stat().st_size,
            }
            if sidecar is not None
            else None
        ),
        # The record as written, for a caller that wants a field this function does
        # not lift out. The lifted fields below exist so the common case does not
        # have to know the sidecar's shape.
        "record": record,
        "source_uri": record.get("source_uri"),
        "source_url": record.get("source_url"),
        "text_file": text_rel,
        "source_content": content,
        "chars": len(content) if content is not None else 0,
        "text_sha256": text_sha256,
        # Asked separately from the warning above because it is asked by a
        # different caller. A reviewer checking the record can be told what to look
        # at; a *verification* about to run must be stopped, and it is stopped on
        # this and not on the presence of a sentence: `verifyProofStub` reads
        # `source_content` and, without this, would record a `source_sha256` of the
        # drifted text while the sidecar beside it went on stating the other. One of
        # the two would be wrong and neither would say so.
        #
        # True when there is nothing to compare: a missing text is reported by
        # `needs_text`, and warning twice about one absence is how a caller learns to
        # ignore warnings.
        "text_matches_record": (
            content is None or not isinstance(recorded_sha, str) or recorded_sha == text_sha256
        ),
        "needs_text": content is None,
        "reading": derivation,
        # Which of the two accounts this record actually contains. Both keys are
        # written by every current record, so they agree today — each is checked on
        # its own key because the sentence the reader is shown is about the thing it
        # names, and the two can diverge in a record written by a build between the
        # two.
        #
        # The distinction is not pedantry. A record written before the margin was
        # kept has no `citations` key at all, and an empty citation list then means
        # "nothing was looked for" rather than "nothing was there" — the second is a
        # claim about the document, and this record does not make it.
        "reading_recorded": isinstance(record.get("readings"), dict),
        "citations_recorded": "citations" in record,
        "citations": (derivation or {}).get("citations") or [],
        "numerals": (derivation or {}).get("numerals") or [],
        "notes": record.get("notes") or [],
        "schema_version": record.get("schema_version"),
        "warnings": warnings,
    }


def decode_base64_payload(value: str) -> bytes:
    """Decode a JSON-carried upload, refusing the two shapes that mean "empty"."""
    if not isinstance(value, str) or not value.strip():
        raise SourceError("content_base64 is empty")
    try:
        return base64.b64decode(value, validate=True)
    except Exception as exc:  # noqa: BLE001 - any decode failure is a client error
        raise SourceError(f"content_base64 is not valid base64 ({exc})") from exc
