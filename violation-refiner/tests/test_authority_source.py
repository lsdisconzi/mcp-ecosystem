"""Tests for the authority-source store (`violation_pack.authority_source`).

This module exists because `authority_verification.py` is network-free and
filesystem-free by design: it verifies a quote against content it was *given*.
Somebody has to own the other half — fetching the page, decoding the upload,
deciding what happens to a scanned PDF with no text layer, and writing the proof
somewhere the bundle keeps it — without ever being able to flip `verified`.

Three invariants are worth a test each, because breaking any of them produces a
result that *looks* verified:

1. **No silent text loss.** An artefact that cannot be read is still stored and
   hashed, and the caller is told its text is missing. It is never dropped, and
   it never counts as an error.
2. **No network unless asked.** Recording a url and fetching a url are different
   operations; `/api/authority-source` must not reach out because a url appeared
   in a payload.
3. **No overwriting of proof.** Re-storing the same bytes reuses the file.
"""
from __future__ import annotations

import base64
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from violation_pack.authority_source import (
    MAX_UPLOAD_BYTES,
    PROOF_SCHEMA_VERSION,
    PROOF_SUFFIX,
    SOURCES_DIR,
    TEXT_SUFFIX,
    SourceError,
    _PDF_EXTRACTORS,
    collapse_whitespace,
    decode_base64_payload,
    delete_source,
    derive_reading,
    detect_gutter,
    extract_pdf_reading,
    extract_pdf_text,
    fetched_filename,
    ingest_source,
    name_from_url,
    proof_stem,
    sanitise_filename,
    split_columns,
    strip_markup,
    strip_repeated_furniture,
    url_refusal_reason,
)


# ---------------------------------------------------------------------------
# Filenames — the value that decides where a reviewer's upload lands
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("../../etc/passwd", "passwd"),
    ("C:\\tmp\\x.pdf", "x.pdf"),
    ("", "source"),
    (".hidden", "hidden"),
    ("a b/c.txt", "c.txt"),
    ("..", "source"),
    ("/", "source"),
    ("sentencia rol 16.622-2025.pdf", "sentencia-rol-16.622-2025.pdf"),
])
def test_sanitise_filename_never_yields_a_path(raw, expected):
    assert sanitise_filename(raw) == expected


def test_sanitise_filename_caps_the_stem_but_keeps_the_extension():
    out = sanitise_filename("x" * 300 + ".pdf")
    assert out.endswith(".pdf")
    assert len(out) < 100


def test_name_from_url_keeps_the_host_and_the_query_that_names_the_norma():
    # The query is kept because for bcn.cl the norma id *is* the query, and the
    # host is kept because two governments' /navegar paths are otherwise
    # indistinguishable in a bundle listing.
    assert name_from_url("https://www.bcn.cl/leychile/navegar?idNorma=123") == "www.bcn.cl-navegar-idNorma-123.txt"
    assert name_from_url("https://pjud.cl/").startswith("pjud.cl")
    assert name_from_url("https://pjud.cl/").endswith(".txt")
    assert name_from_url("").startswith("source")


# ---------------------------------------------------------------------------
# Host and scheme policy
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "ftp://example.com/x",
    "http://127.0.0.1/x",
    "http://localhost/x",
    "http://10.0.0.1/x",
    "http://192.168.1.5/x",
    "http://172.20.4.4/x",
    "http://169.254.169.254/latest/meta-data/",
    "http://box.local/x",
    "http://intranet.internal/x",
    "not a url",
])
def test_url_refusal_reason_refuses_non_public_targets(url):
    assert url_refusal_reason(url), f"{url} should be refused"


@pytest.mark.parametrize("url", [
    "https://www.bcn.cl/leychile/navegar?idNorma=123",
    "http://www.diariooficial.interior.gob.cl/x",
    "https://suprema.pjud.cl/",
])
def test_url_refusal_reason_allows_official_hosts(url):
    assert url_refusal_reason(url) is None


# ---------------------------------------------------------------------------
# Fetching — injectable, so none of this touches the network
# ---------------------------------------------------------------------------

class _FakeOpener:
    """Stands in for the ``opener`` seam and records what it was asked.

    The real signature is ``opener(url) -> (bytes, content_type, final_url)``;
    matching it here is the point — an injected opener that returns a response
    object would pass a test of a function the module never calls.
    """

    def __init__(self, data: bytes, *, content_type="text/html; charset=utf-8", final_url=None):
        self.data = data
        self.content_type = content_type
        self.final_url = final_url
        self.calls: list[str] = []

    def __call__(self, url):
        self.calls.append(url)
        return self.data, self.content_type, self.final_url or url


def test_ingest_can_fetch_through_an_injected_opener(tmp_path):
    """The whole fetch path is exercised without a socket: `opener` is the seam."""
    bundle = _bundle(tmp_path)
    opener = _FakeOpener("<html><body><h1>Artículo 193</h1></body></html>".encode("utf-8"))
    out = ingest_source(
        bundle, "AUTH-CL-001-01",
        source_url="https://www.bcn.cl/leychile/navegar?idNorma=1",
        do_fetch=True, opener=opener,
    )
    assert opener.calls == ["https://www.bcn.cl/leychile/navegar?idNorma=1"]
    assert out["ok"] is True
    assert out["text_source"] == "fetched"
    assert out["source_content"] == "Artículo 193"
    assert out["artefact"]["name"].endswith(".html")
    assert out["artefact"]["name"].startswith("AUTH-CL-001-01__")


def test_ingest_records_a_url_without_fetching_it(tmp_path):
    """Passing a url is not asking for a download — the two are separate calls."""
    bundle = _bundle(tmp_path)
    opener = _FakeOpener(b"never used")
    out = ingest_source(
        bundle, "AUTH-CL-001-01",
        source_url="https://www.bcn.cl/leychile/navegar?idNorma=1",
        text="El artículo 193 num. 8 del Código del Trabajo",
        opener=opener,
    )
    assert opener.calls == []
    assert out["text_source"] == "pasted"
    assert out["source_uri"] == "https://www.bcn.cl/leychile/navegar?idNorma=1"
    assert out["artefact"] is None


def test_an_upload_and_a_url_never_open_a_connection(tmp_path):
    """Both were supplied, so the url is provenance and the upload is the source."""
    bundle = _bundle(tmp_path)
    opener = _FakeOpener(b"never used")
    out = ingest_source(bundle, "AUTH-CL-001-01",
                        source_url="https://www.bcn.cl/leychile/navegar?idNorma=1",
                        filename="nota.txt", data=b"el art\xc3\xadculo 193", do_fetch=True,
                        opener=opener)
    assert opener.calls == []
    assert out["text_source"] == "upload"


@pytest.mark.parametrize("content_type,expected", [
    ("text/html; charset=UTF-8", ".html"),
    ("application/xhtml+xml", ".html"),
    ("application/pdf", ".pdf"),
    ("TEXT/PLAIN", ".txt"),
    ("application/octet-stream", ".bin"),
    (None, ".bin"),
])
def test_fetched_filename_takes_the_reader_from_the_served_type(content_type, expected):
    assert fetched_filename("https://x.cl/a", content_type, b"plain bytes").endswith(expected)


def test_fetched_filename_does_not_trust_a_content_type_that_lies():
    """A page served as text/plain, or as octet-stream, is still a page."""
    page = b"<!DOCTYPE html><html><body><p>hola</p></body></html>"
    assert fetched_filename("https://x.cl/a", "text/plain", page).endswith(".html")
    assert fetched_filename("https://x.cl/a", None, page).endswith(".html")
    assert fetched_filename("https://x.cl/a", None, b"%PDF-1.4\n").endswith(".pdf")


def test_a_served_page_is_stripped_of_markup_before_it_is_handed_over(tmp_path):
    """The extension selects the reader, and the reader decides what is quoted.

    A fetched page stored as `.txt` went to the protocol with its tags intact, so
    a quote the reviewer could see on the page matched nothing. The test asserts
    the *content*, not just the filename, because a name is not a reader.
    """
    bundle = _bundle(tmp_path)
    page = b"<html><head><style>p{}</style></head><body><h1>Art\xc3\xadculo 193</h1></body></html>"
    out = ingest_source(bundle, "AUTH-CL-001-01",
                        source_url="https://www.bcn.cl/leychile/navegar?idNorma=1",
                        do_fetch=True, opener=_FakeOpener(page, content_type="text/plain"))
    assert out["artefact"]["name"].endswith(".html")
    assert out["extractor"] == "html-strip"
    assert out["source_content"] == "Artículo 193"
    assert "Artículo 193" in (bundle / out["artefact"]["rel"]).read_text(encoding="utf-8")


def test_a_fetched_page_plus_a_pasted_passage_keeps_both(tmp_path):
    """Fetching the page *and* pasting its text is the normal way to work around
    a page that will not parse cleanly: the page is the proof, the paste is what
    the protocol searches, and both have to end up on disk."""
    bundle = _bundle(tmp_path)
    page = b"<html><body><p>art&iacute;culo   193</p></body></html>"
    out = ingest_source(bundle, "AUTH-CL-001-01",
                        source_url="https://www.bcn.cl/leychile/navegar?idNorma=1",
                        do_fetch=True, opener=_FakeOpener(page),
                        text="artículo 193 num. 8")
    assert out["text_source"] == "pasted"
    assert out["source_content"] == "artículo 193 num. 8"
    proof = json.loads((bundle / out["proof"]["rel"]).read_text(encoding="utf-8"))
    assert proof["fetched"] is True
    assert proof["final_url"] == "https://www.bcn.cl/leychile/navegar?idNorma=1"
    assert proof["artefact"]["rel"] == out["artefact"]["rel"]
    assert (bundle / proof["text_file"]).read_text(encoding="utf-8") == "artículo 193 num. 8"


# ---------------------------------------------------------------------------
# Reading what was handed in
# ---------------------------------------------------------------------------

def test_strip_markup_drops_scripts_and_cannot_fuse_paragraphs():
    html = ("<html><head><style>p{color:red}</style></head><body>"
            "<script>var x = 1;</script><p>uno</p><p>dos</p>"
            "<p>art&iacute;culo</p></body></html>")
    assert strip_markup(html) == "uno dos artículo"


def test_a_document_with_no_readable_text_keeps_its_file(tmp_path):
    """A scanned attachment is a legitimate ingest, not an error.

    Throwing away the reviewer's only copy of a judgment to protect a formatting
    rule is the wrong trade, so the bytes are stored and hashed and the caller is
    told `needs_text` — which the UI turns into "paste the passage instead".
    """
    bundle = _bundle(tmp_path)
    out = ingest_source(bundle, "AUTH-CL-001-01", filename="sentencia.zip",
                        data=b"PK\x03\x04 not actually a zip")
    assert out["ok"] is True
    assert out["needs_text"] is True
    assert out["source_content"] is None
    assert out["text_sha256"] is None
    assert out["artefact"]["bytes"] == len(b"PK\x03\x04 not actually a zip")
    assert (bundle / SOURCES_DIR / out["artefact"]["name"]).is_file()
    assert out["warnings"], "an unreadable artefact must say so"


def test_a_pdf_without_an_installed_reader_says_which_package_to_install(monkeypatch):
    monkeypatch.setattr("violation_pack.authority_source._PDF_EXTRACTORS", ())
    text, extractor, warnings = extract_pdf_text(b"%PDF-1.4\n")
    assert text is None and extractor is None
    assert any("pypdf" in w for w in warnings)
    assert any("install" in w for w in warnings), (
        "the warning has to name the fix, because the reviewer's only way out "
        "of this state is to install a reader and re-upload"
    )


def test_every_registered_pdf_reader_is_a_callable_not_a_name():
    """The registry holds the reader itself, so no name can drift out of step.

    This is the half of the guard that runs with no optional package installed.
    The registry used to pair a module name with the *string* `"read_pypdf"`
    and resolve it through `globals()`, while the function was `_read_pypdf` —
    one leading underscore apart. The lookup could only execute once an
    extractor was importable, so it raised `KeyError` on precisely the machines
    where a reviewer had already done what the warning told them to do.
    """
    assert _PDF_EXTRACTORS, "an empty registry reports every PDF as unreadable"
    for module_name, reader in _PDF_EXTRACTORS:
        assert isinstance(module_name, str) and module_name
        assert callable(reader), (
            f"{module_name} is paired with {reader!r}; a name here is looked up "
            "at extraction time and fails only on the machine that can extract"
        )


# ---------------------------------------------------------------------------
# PDF layout — the body column, and the account of moving it
# ---------------------------------------------------------------------------

#: Where the fixtures put the gutter. A middle-of-the-page number on purpose:
#: the detection has to *find* it, so a fixture that used column zero would pass
#: a split that cuts nothing off.
_GUTTER_COLUMN = 64

#: An article body and the margin citations that sit beside its lines, as an
#: official Chilean source is laid out. The body lines are all shorter than the
#: gutter and hold no wide gap of their own, so the only wide gap on the page is
#: the one the layout put there.
_ARTICLE_LINES = [
    "Corresponderá al legislador establecer siempre las",
    "garantías de un procedimiento y una investigación",
    "racionales y justos.",
    "La Constitución asegura a todas las personas",
    "El derecho a la vida y a la integridad física",
    "La igualdad ante la ley",
    "El respeto y protección a la vida privada",
    "La inviolabilidad del hogar",
    "La libertad de conciencia",
    "El derecho a la educación",
]
_ARTICLE_NOTES = [
    "CPR Art.19° D.O. 24.10.1980",
    "LEY N° 20.050 Art. 1° N° 10 letra a) D.O.",
    "26.08.2005",
    "LEY N° 19.519 Art. único",
    "D.O. 16.06.1999",
    "CPR Art. 19° N° 3 D.O. 24.10.1980",
    "LEY N° 18.825 Art. único",
    "D.O. 17.08.1989",
    "Ley 21568 Art. ÚNICO",
    "D.O. 03.05.2023",
]

#: The sentence those citations are threaded through, and the reason the whole
#: layout pass exists.
_SENTENCE = (
    "Corresponderá al legislador establecer siempre las garantías de un "
    "procedimiento y una investigación racionales y justos."
)

#: Four distinct lines, so that nothing in a fixture is repeated across pages by
#: accident — repetition is what the furniture rule keys on.
_DISTINCT_BODIES = [
    "La Constitución asegura a todas las personas el derecho a la vida",
    "La igualdad ante la ley es la base de todo sistema jurídico",
    "El respeto y protección a la vida privada de la persona",
    "La libertad de conciencia y el derecho a la educación",
]

#: Ten distinct paragraphs, one per page, every one of them indented.
#:
#: Ten and not four, because a paragraph indent is a gap and this fixture has to
#: carry enough of them that the *only* reason it is not read as two columns is
#: that an indent is nowhere near the gutter. At four pages the indents would be
#: too rare to look like a habit and the test would pass for the wrong reason.
_SINGLE_COLUMN_PARAGRAPHS = [
    "La Constitución asegura a todas las personas el derecho a la vida",
    "La igualdad ante la ley es la base de todo sistema jurídico",
    "El respeto y protección a la vida privada de la persona",
    "La libertad de conciencia y el derecho a la educación",
    "La inviolabilidad del hogar es una garantía del artículo diecinueve",
    "El derecho a la protección de la salud comprende el libre acceso",
    "La libertad de emitir opinión no tiene más límites que los señalados",
    "El derecho de reunión se ejerce sin permiso previo de la autoridad",
    "La libertad de trabajo y su protección son derechos de la persona",
    "El derecho a la seguridad social garantiza el acceso a prestaciones",
]


#: The paragraph indent the article fixture carries. A real page has both an
#: indent and a gutter, and that is the only combination in which "the gap at
#: the column" and "the first gap on the line" are different gaps.
_ARTICLE_INDENT = 5


def _two_column_page(body: list[str], notes: list[str], indent: int = 0) -> str:
    """One page as a flat extractor emits a two-column official document.

    The body column is padded out to the gutter and the margin note is written
    onto the same physical line. That is the whole defect: the extractor has no
    y-coordinate left to give, so a citation that sits *beside* a line of the
    article arrives wedged between two words of it.

    ``indent`` puts a run of spaces at the start of every body line, which is how
    a real page looks. It matters: with an indent present the first gap on a line
    is the indent, not the gutter, so a split that took the first gap it found
    would cut off the heading and leave the rest — including the citation — in
    the body.
    """
    out = []
    for index, line in enumerate(body):
        note = notes[index] if index < len(notes) else ""
        text = " " * indent + line
        out.append(text.ljust(_GUTTER_COLUMN) + note if note else text)
    return "\n".join(out) + "\n"


def _article_page() -> str:
    """One page of a two-column source, with a citation beside every line.

    Every line carries a note because that is what makes a gutter detectable: the
    support for the column comes from how many lines share it, and a page where
    only two of ten lines have a margin note is a page whose margin cannot be
    told from the spacing of a single stray line.
    """
    return _two_column_page(_ARTICLE_LINES, _ARTICLE_NOTES, indent=_ARTICLE_INDENT)


def _repeated_footer_page(body: str, footer: str) -> str:
    return f"{body}\n{footer}\n"


def test_a_margin_citation_is_not_read_into_the_sentence_it_annotates():
    """The defect, the fixture that has it, and the fix — in that order.

    The first assertion is the one that matters. Without it this test would still
    pass if the split were deleted and everything else stayed, because `in` on
    the clean text says nothing about whether anything was done to get there: a
    test that never checks the fixture is broken cannot show a fix.
    """
    pages = [_article_page()]

    assert _SENTENCE not in collapse_whitespace(" ".join(pages)), (
        "the fixture no longer reproduces the defect, so it cannot show the "
        "split repairing it"
    )
    reading = derive_reading(pages)
    assert reading.gutter == _GUTTER_COLUMN
    assert _SENTENCE in reading.text
    assert reading.text.startswith("Corresponderá al legislador")


def test_the_margin_citations_come_back_with_the_lines_they_sat_on():
    """The note column is moved, not deleted, and it keeps its address.

    On an official document the margin carries the amendment history of the very
    numeral being quoted — which law changed it, when, and in which edition of
    the Diario Oficial — so it is evidence for `instrument` and `version` rather
    than clutter. Deleting it to tidy the reading would throw away the answer to
    make the question easier to search.
    """
    reading = derive_reading([_article_page()])
    assert [note["text"] for note in reading.notes] == _ARTICLE_NOTES
    assert [note["line"] for note in reading.notes] == list(range(1, 11)), (
        "a note that cannot say which line it annotated cannot be checked "
        "against the page it came from"
    )
    assert {note["page"] for note in reading.notes} == {1}
    assert "26.08.2005" not in reading.text
    assert reading.text.count("26.08.2005") == 0


def test_the_layout_pass_moves_words_without_losing_any():
    """"Shorter" and "lossy" look identical in a string, so conservation is the check.

    The margin column is the one place a reader could be forgiven for accepting a
    deletion, so the assertion is that nothing anywhere was deleted: every word
    of the plain reading is still in the clean reading or in the notes, no more
    and no fewer.
    """
    pages = [_article_page()]
    raw = Counter(collapse_whitespace(" ".join(pages)).split())
    reading = derive_reading(pages)

    kept = Counter(reading.text.split())
    for note in reading.notes:
        kept.update(note["text"].split())

    assert sum(raw.values()) > 50, "the fixture is too small to prove anything"
    assert kept == raw


def test_a_single_column_page_is_not_read_as_two_columns():
    """The failure mode that makes splitting dangerous, and the guard against it.

    A paragraph indent is a gap too. Believing it is the gutter hands the whole
    line to the margin and leaves a body of nothing — which is a *valid* result
    for every function below, because a split that returns an empty left column
    still returns a string. The reading would be empty and nothing would raise.
    """
    paragraphs = _SINGLE_COLUMN_PARAGRAPHS
    pages = [
        f"    {paragraph}\n     1º.- {paragraph.lower()}\n" for paragraph in paragraphs
    ]
    reading = derive_reading(pages)

    assert detect_gutter(pages) is None
    assert reading.gutter is None
    assert reading.notes == ()
    assert reading.furniture == ()
    assert reading.text == collapse_whitespace(" ".join(pages))
    assert not reading.restructured, "a document with no columns must be left alone"


def test_one_wide_gap_on_a_page_is_not_a_gutter():
    """A gutter is a habit down the page, not one wide space somewhere on it.

    A table, a centred heading, an aligned signature block: each is a wide gap
    that occurs once. Believing one of them is the column break would hand the
    rest of that line to the margin, and there is nothing in the result to say
    so.
    """
    lines = ["El considerando se refiere a los hechos de la causa"] * 11
    lines.insert(4, "El considerando se refiere" + " " * 12 + "a los hechos")
    pages = ["\n".join(lines) + "\n"]

    assert detect_gutter(pages) is None


def test_a_wide_gap_near_the_right_edge_is_not_a_gutter():
    """The split is only believed if the body is still most of the page.

    Eight lines whose wide gap leaves twenty characters on the left and eighty
    on the right is a column break with the columns the wrong way round — or, as
    here, not a column break at all. Without this check, a document with one odd
    alignment would lose the body of every line it appears on.
    """
    pages = [("a" * 20 + " " * 20 + "b" * 80 + "\n") * 8]

    assert detect_gutter(pages) is None


def test_a_page_of_scattered_wide_gaps_has_no_gutter_to_find():
    """Justified text puts its extra spaces all over the page; a gutter is one line.

    Four wide-gap positions, each repeated often enough to look like a habit on
    its own. Taking the most common of them would cut every line at a different
    word — and the cut would pass the "the body is still the body" check, so this
    spread test is doing work nothing else does.
    """
    rows = ["a" * 60 + " " * (12 + 4 * index) + "b" * 10 for index in range(4)]
    pages = ["\n".join(rows * 8) + "\n"]

    assert detect_gutter(pages) is None
    assert derive_reading(pages).text.count("a" * 60) == 32, "the fixture lost rows"


def test_a_short_cell_index_is_not_a_two_column_layout():
    """The gutter has to be clear of the left margin, not merely consistent.

    Nine index lines whose cells are two spaces apart after the ninth character.
    The left cell is the longer one, so the body really is most of the text and
    the "the body is still the body" check passes — the *only* thing that says
    this is not a column break is that column eleven is where a paragraph indent
    lives. Split here and each line becomes an article number on a row of its own
    with the instrument it points at moved to the margin.

    The gap is eleven and not one of the obvious three or four, because a margin
    gap of one or two characters is caught by the body-share check instead. This
    fixture is the narrow band where the two guards disagree.
    """
    rows = [
        f"Art. 19.{digit}  Ley {letter}"
        for digit, letter in zip("123456789", "ABCDEFGHI")
    ]
    pages = ["\n".join(rows) + "\n"]

    assert detect_gutter(pages) is None
    assert derive_reading(pages).text == collapse_whitespace(" ".join(pages))


def test_a_line_repeated_on_every_page_is_dropped_as_furniture():
    """Repetition *defines* furniture, so no list of known footers is needed.

    A pattern list is written for the documents that already exist and misses the
    next authority's letterhead completely. It also matters for quoting: a footer
    lands between two words of any sentence that spans a page break, which makes
    the sentence unquotable for a reason nothing on screen explains.
    """
    footer = "Documento firmado digitalmente por Ignacio Rodríguez Álvarez"
    pages = [_repeated_footer_page(body, footer) for body in _DISTINCT_BODIES]
    reading = derive_reading(pages)

    assert footer not in reading.text
    for body in _DISTINCT_BODIES:
        assert body in reading.text
    assert reading.furniture == (footer,)
    assert reading.furniture_lines == 4
    assert reading.furniture_chars == len(footer) * 4


def test_a_long_passage_repeated_on_every_page_is_kept():
    """A short line repeating is a header; a paragraph repeating is the document.

    Statutes repeat their own formulations on purpose — transitional articles,
    closing provisos, the definition of a procedure the whole act is about — and
    a line long enough to be a paragraph is far more likely to be the act's text
    than to be stationery. Dropping it would delete exactly the content the
    reviewer came for, and it would do so on every page.
    """
    paragraph = (
        "El procedimiento administrativo se someterá a los principios de "
        "escrituración, conclusivo, celeridad, economía procedimental, "
        "inexcusabilidad, contradictoriedad, imparcialidad, abstención, no "
        "formalización, impugnabilidad, transparencia y publicidad, y será "
        "gratuito para el interesado, sin perjuicio de lo dispuesto en el "
        "artículo siguiente y en las leyes especiales que rijan la materia"
    )
    assert len(paragraph) > 160, "the fixture must be over the cap to test it"
    pages = [_repeated_footer_page(body, paragraph) for body in _DISTINCT_BODIES]

    reading = derive_reading(pages)

    assert reading.furniture == ()
    assert reading.text.count(paragraph) == len(_DISTINCT_BODIES)


def test_a_page_marker_that_changes_on_every_page_is_still_the_same_line():
    """Masking digits is what makes `página 1 de 4` and `página 4 de 4` one line.

    Without it the marker survives on all four pages, and a marker is not
    harmless noise: it is exactly what sits between two words of a sentence that
    runs over a page break.
    """
    pages = [
        _repeated_footer_page(body, f"página {number} de 4")
        for number, body in enumerate(_DISTINCT_BODIES, start=1)
    ]
    reading = derive_reading(pages)

    assert reading.furniture == ("página # de #",)
    assert reading.furniture_lines == 4
    assert "página" not in reading.text


def test_a_numeral_alone_on_its_line_is_not_mistaken_for_a_page_marker():
    """Digit masking collapses `1º.-` and `2º.-` to one key as well.

    A document that numbers its articles on lines of their own therefore looks
    exactly like a document whose every page carries the same marker. Without the
    letters guard the pass would delete the numbering of the whole statute — and
    a document that has silently lost its numbering still reads like a document.
    """
    pages = [
        f"{number}º.-\n{body}\n"
        for number, body in enumerate(_DISTINCT_BODIES, start=1)
    ]
    reading = derive_reading(pages)

    assert reading.furniture == ()
    for number in range(1, len(_DISTINCT_BODIES) + 1):
        assert f"{number}º.-" in reading.text


def test_a_clause_repeated_on_a_minority_of_pages_is_not_furniture():
    """Repetition alone is not enough: a running header is on *most* pages.

    Twenty pages of a judgment, three of which restate the same standard clause.
    The clause is the document's own text, and a rule that said "seen on three
    pages" would have deleted it three times over.
    """
    clause = "que el recurso debe ser fundado y tramitado conforme a la ley"
    pages = []
    for index, letter in enumerate("abcdefghijklmnopqrst"):
        lines = [f"el considerando {letter} de la sentencia", f"página {index + 1} de 20"]
        if index < 3:
            lines.insert(1, clause)
        pages.append("\n".join(lines) + "\n")
    reading = derive_reading(pages)

    assert reading.furniture == ("página # de #",)
    assert reading.text.count(clause) == 3


def test_furniture_is_reported_rather_than_quietly_removed():
    """The removed rows come back, because a reading must never just get shorter."""
    footer = "Documento firmado digitalmente por la Directora"
    rows = [(page, 1, footer) for page in range(1, 5)]
    rows += [(1, 2, "el derecho a la vida"), (2, 3, "la igualdad ante la ley")]

    kept, removed = strip_repeated_furniture(rows)

    assert [row[2] for row in removed] == [footer] * 4
    assert kept == [(1, 2, "el derecho a la vida"), (2, 3, "la igualdad ante la ley")]


def test_a_line_with_no_gap_near_the_gutter_stays_whole_in_the_body():
    """A long body line runs past the gutter, and cutting it there would be a lie.

    The conservative direction matters more than the tidy one: a body line that
    happened to hold a wide gap is kept intact, where a margin line mistaken for
    body would corrupt a sentence a reviewer is about to quote.
    """
    long_line = (
        "El legislador establecerá siempre las garantías de un procedimiento y "
        "una investigación racionales y justos, sin excepción alguna"
    )
    pages = [_two_column_page([long_line, "La Constitución asegura"], ["", "26.08.2005"])]
    body, notes = split_columns(pages, _GUTTER_COLUMN)

    assert [text for _, _, text in body] == [long_line, "La Constitución asegura"]
    assert [text for _, _, text in notes] == ["26.08.2005"]


def test_the_reading_records_the_extractor_version_that_produced_it():
    """Two releases of `pypdf` do not put the same characters on the same line.

    A bundle read by one and re-read by the other has a different text for the
    same file, and the version is the only thing in the record that makes that
    difference visible — otherwise it looks like the proof was altered.
    """
    pytest.importorskip("pypdf")
    reading, extractor, warnings = extract_pdf_reading(_minimal_pdf("ARTICULO 19"))

    assert extractor == "pypdf" and warnings == []
    assert reading.extractor == "pypdf"
    assert reading.extractor_version and reading.extractor_version[0].isdigit()
    assert reading.derivation()["extractor_version"] == reading.extractor_version


def test_extract_pdf_text_is_the_reading_without_the_account_of_it():
    """Callers with no opinion about columns keep the one-value answer.

    `extract_pdf_text` and `extract_pdf_reading` must not drift apart: the text
    the simple caller gets is the text the protocol will search, because the
    stored proof and the returned string are compared against each other.
    """
    pytest.importorskip("pypdf")
    payload = _minimal_pdf("ARTICULO 19.- La igual proteccion de la ley")
    text, extractor, warnings = extract_pdf_text(payload)
    reading, _, _ = extract_pdf_reading(payload)

    assert text == reading.text
    assert extractor == "pypdf"
    assert warnings == []


def test_the_sidecar_says_which_reading_the_protocol_searched(tmp_path):
    """A hash is only checkable if the record says what it is a hash *of*.

    `text_sha256` has always been the hash of the matched text; what was never
    recorded is what kind of text that was. An offset into a pasted passage
    proves the quote is inside the quote and nothing about the document, and
    nothing in the bundle used to say which of the two had been hashed.
    """
    bundle = _bundle(tmp_path)
    out = ingest_source(bundle, "AUTH-CL-001-01", filename="nota.txt",
                        data="El artículo 193 num. 8 del Código del Trabajo".encode("utf-8"))
    proof = json.loads((bundle / out["proof"]["rel"]).read_text(encoding="utf-8"))

    assert proof["schema_version"] == PROOF_SCHEMA_VERSION
    assert proof["readings"]["matched"] == {
        "sha256": proof["text_sha256"],
        "chars": proof["text_chars"],
        "basis": "text",
    }
    assert proof["readings"]["raw"] is None, "a text upload has no extraction to record"
    assert proof["readings"]["derivation"] is None
    assert proof["notes"] == []


def test_a_read_pdf_records_both_its_reading_and_the_raw_extraction(tmp_path):
    """The two hashes answer different questions, so both are written down.

    `raw` is what the extractor produced and `matched` is what the protocol
    searched; on a single-column one-line PDF they are the same string, and the
    test says so rather than leaving it to be assumed.
    """
    pytest.importorskip("pypdf")
    bundle = _bundle(tmp_path)
    out = ingest_source(
        bundle, "AUTH-CL-001-01", filename="constitucion.pdf",
        data=_minimal_pdf("ARTICULO 19.- La igual proteccion de la ley"),
    )
    proof = json.loads((bundle / out["proof"]["rel"]).read_text(encoding="utf-8"))

    assert proof["readings"]["matched"]["basis"] == "pdf"
    assert proof["readings"]["matched"]["chars"] == len(out["source_content"])
    assert proof["readings"]["raw"]["sha256"] == proof["text_sha256"]
    assert proof["readings"]["raw"]["chars"] == proof["text_chars"]
    derivation = proof["readings"]["derivation"]
    assert derivation["extractor"] == "pypdf"
    assert derivation["columns_split"] is False
    assert derivation["furniture"] == []
    assert proof["notes"] == []


def test_a_pasted_passage_over_a_pdf_keeps_the_pdfs_reading_on_record(tmp_path):
    """The case that made recorded offsets ambiguous, now recorded as such.

    A PDF proof plus a typed passage is the normal request, and the matched text
    is the paste — so an offset against it says nothing about the document, while
    the PDF *was* read and its reading is re-derivable from the artefact. One
    hash could not distinguish the two; `matched.basis` can.
    """
    pytest.importorskip("pypdf")
    bundle = _bundle(tmp_path)
    out = ingest_source(
        bundle, "AUTH-CL-001-01", filename="constitucion.pdf",
        data=_minimal_pdf("ARTICULO 19.- La igual proteccion de la ley"),
        text="artículo 19 num. 3",
    )
    proof = json.loads((bundle / out["proof"]["rel"]).read_text(encoding="utf-8"))

    assert proof["readings"]["matched"]["basis"] == "pasted"
    assert proof["readings"]["matched"]["sha256"] == proof["text_sha256"]
    assert proof["readings"]["raw"] is not None, "the PDF was still read"
    assert proof["readings"]["raw"]["chars"] != proof["readings"]["matched"]["chars"]
    assert (bundle / proof["text_file"]).read_text(encoding="utf-8") == "artículo 19 num. 3"


def test_a_layout_pass_that_changed_nothing_still_records_what_it_looked_for(tmp_path):
    """`columns_split: false` is a finding, not an absence of one.

    A reader of the record has to be able to tell "this document has one column
    and was left alone" from "this reading predates the layout pass" — otherwise
    the next person to meet an unquotable sentence has to re-derive the answer
    from the PDF before they can trust it.

    The pypdf assertion that produced the clean reading is *not* restated here.
    `pypdf` is what the test already skips on if it is missing, and claiming the
    text is whatever the reader returns would make this test pass against a
    registry that reads nothing.
    """
    pytest.importorskip("pypdf")
    bundle = _bundle(tmp_path)
    out = ingest_source(
        bundle, "AUTH-CL-001-01", filename="constitucion.pdf",
        data=_minimal_pdf("ARTICULO 19.- La igual proteccion de la ley"),
    )
    derivation = out["reading"]

    assert derivation["pages"] == 1
    assert derivation["columns_split"] is False
    assert derivation["gutter_column"] is None
    assert derivation["notes"] == 0 and derivation["notes_chars"] == 0
    assert derivation["furniture_lines"] == 0
    assert derivation["extractor"] == "pypdf"


def test_the_margin_citations_are_recorded_beside_the_reading_not_inside_it(
    tmp_path, monkeypatch
):
    """The stored proof keeps the notes, and keeps them *out of* the searched text.

    On an official document the margin carries the amendment history of the very
    numeral being quoted — which law changed it, when, and in which edition of
    the Diario Oficial — so it is evidence for `instrument` and `version`. It is
    also, wedged between two words, precisely what makes a sentence unquotable.
    So it has to be recorded *and* excluded, and neither assertion implies the
    other: dropping the notes from the sidecar would satisfy every quotation in
    the suite.

    The reader is stubbed rather than stubbed-around: the question here is what
    `ingest_source` writes, and a fixture whose layout the extractor has to
    reconstruct from coordinates would be testing the extractor instead.
    """
    def read_two_columns(_data: bytes) -> list[str]:
        return [_article_page()]

    # The registry pairs an *importable* module name with the reader, and the
    # loop imports the module before calling the reader — so a stand-in cannot
    # be named after itself. `json` is not imported anywhere on this path and is
    # not pretending to be an extractor; it is a name that resolves, which is
    # all the entry needs to be reached without the real `pypdf` deciding what
    # this test is about.
    monkeypatch.setattr(
        "violation_pack.authority_source._PDF_EXTRACTORS",
        (("json", read_two_columns),),
    )
    bundle = _bundle(tmp_path)
    out = ingest_source(bundle, "AUTH-CL-001-01", filename="dto-100.pdf",
                        data=b"%PDF-1.4 the reader below ignores these bytes")
    proof = json.loads((bundle / out["proof"]["rel"]).read_text(encoding="utf-8"))

    assert proof["readings"]["matched"]["basis"] == "pdf"
    assert [note["text"] for note in proof["notes"]] == _ARTICLE_NOTES
    assert len(proof["notes"]) == proof["readings"]["derivation"]["notes"]
    assert _SENTENCE in out["source_content"], "the body is what gets searched"
    assert "26.08.2005" not in out["source_content"], (
        "a citation left inside the matched text is a sentence nobody can quote"
    )
    assert "26.08.2005" in json.dumps(proof["notes"]), "recorded, not discarded"


def test_an_uploaded_pdf_is_read_by_the_installed_extractor(tmp_path):
    """An uploaded PDF comes back as searchable text, not as `needs_text`.

    Built here rather than committed as a fixture: the assertion is about pypdf
    reading a document, and a checked-in blob would only add a binary whose
    bytes nobody can review. Skips when the optional `pdf` extra is absent,
    which is a supported configuration — it is the one that reports
    `needs_text` instead.
    """
    pytest.importorskip("pypdf")
    bundle = _bundle(tmp_path)
    out = ingest_source(
        bundle, "AUTH-CL-001-01", filename="constitucion.pdf",
        data=_minimal_pdf("ARTICULO 19.- La igual proteccion de la ley"),
    )
    assert out["ok"] is True
    assert out["extractor"] == "pypdf"
    assert out["needs_text"] is False
    assert "ARTICULO 19.- La igual proteccion de la ley" in out["source_content"]
    assert out["warnings"] == [], "a PDF that read cleanly must not warn"
    assert out["text_sha256"], "the extracted text is what the protocol hashes"


def test_pasted_text_wins_over_the_artefact_and_is_kept_as_the_matched_text(tmp_path):
    """The reviewer's cleaned paste is what gets hashed, and it is written down.

    `source_content` is the exact string the protocol will find the quote in, so
    when it disagrees with the artefact the disagreement has to be on disk, not
    just in a return value that vanishes with the request.
    """
    bundle = _bundle(tmp_path)
    page = "<html><body><p>art&iacute;culo   193</p></body></html>".encode("utf-8")
    out = ingest_source(bundle, "AUTH-CL-001-01", filename="pagina.html", data=page,
                        text="artículo 193 num. 8 del Código del Trabajo")
    assert out["text_source"] == "pasted"
    assert out["source_content"] == "artículo 193 num. 8 del Código del Trabajo"
    assert out["source_uri"] == f"{SOURCES_DIR}/{out['artefact']['name']}"
    proof = json.loads((bundle / out["proof"]["rel"]).read_text(encoding="utf-8"))
    # The reading of the page and the matched text disagree, so both are on disk:
    # the artefact under its own hash, and the passage under the hash that counts.
    assert proof["text_file"] == f"{SOURCES_DIR}/{Path(out['artefact']['name']).stem}{TEXT_SUFFIX}"
    assert proof["text_sha256"] == hashlib.sha256(out["source_content"].encode("utf-8")).hexdigest()
    assert proof["artefact"]["sha256"] != proof["text_sha256"]
    assert (bundle / proof["text_file"]).read_text(encoding="utf-8") == "artículo 193 num. 8 del Código del Trabajo"


def test_the_stored_text_file_is_not_written_when_it_would_duplicate_the_artefact(tmp_path):
    """A reading that already *is* the artefact must not be copied beside it."""
    bundle = _bundle(tmp_path)
    out = ingest_source(bundle, "AUTH-CL-001-01", filename="nota.txt",
                        data="El artículo 193 num. 8".encode("utf-8"))
    assert out["source_uri"] == f"{SOURCES_DIR}/{out['artefact']['name']}"
    written = {p.name for p in (bundle / SOURCES_DIR).iterdir()}
    assert written == {
        out["artefact"]["name"],
        f"{Path(out['artefact']['name']).stem}{PROOF_SUFFIX}",
    }, "a reading identical to the artefact must not be copied beside it"
    proof = json.loads((bundle / out["proof"]["rel"]).read_text(encoding="utf-8"))
    assert proof["text_file"] is None


def test_text_read_out_of_a_pdf_is_written_beside_it_so_the_hash_can_be_rechecked(tmp_path):
    """A PDF that read cleanly must still get its text written down.

    The reading equals the content here — that is what "read cleanly" means — so
    a check that asks the reading whether the text is already on disk answers yes
    and stores nothing, leaving `text_sha256` naming a string that exists only
    inside the PDF. Anyone auditing the bundle then has to own the same parser to
    check the hash, which is the dependency the stored copy exists to remove.
    """
    pytest.importorskip("pypdf")
    bundle = _bundle(tmp_path)
    passage = "ARTICULO 19.- La igual proteccion de la ley"
    out = ingest_source(bundle, "AUTH-CL-001-01", filename="constitucion.pdf",
                        data=_minimal_pdf(passage))
    proof = json.loads((bundle / out["proof"]["rel"]).read_text(encoding="utf-8"))
    assert proof["text_file"] is not None, "the matched text has to be on disk"
    stored = (bundle / proof["text_file"]).read_text(encoding="utf-8")
    assert passage in stored
    assert proof["text_sha256"] == hashlib.sha256(stored.encode("utf-8")).hexdigest(), (
        "a recorded hash that nobody can re-derive from the bundle is not proof"
    )
    assert proof["artefact"]["sha256"] != proof["text_sha256"]


def test_re_ingesting_the_bundles_own_stored_copy_does_not_mint_a_second_artefact(tmp_path):
    """Picking the bundle's own copy back must be a no-op, not a second proof.

    A reviewer re-reading an existing bundle has no other file to pick: the
    stored copy is the only one left, and it is already named
    `<authority_id>__<original>`. The prefix used to be added unconditionally, so
    the name changed, `_unique_path` could not recognise the bytes, and the same
    document was stored twice with the sidecar pointing at the copy.
    """
    bundle = _bundle(tmp_path)
    payload = "El artículo 193 num. 8 del Código del Trabajo".encode("utf-8")
    first = ingest_source(bundle, "AUTH-CL-001-01", filename="nota.txt", data=payload)
    stored = bundle / first["artefact"]["rel"]
    again = ingest_source(bundle, "AUTH-CL-001-01", filename=stored.name,
                          data=stored.read_bytes())
    assert again["artefact"]["name"] == first["artefact"]["name"]
    assert again["artefact"]["reused"] is True
    kept = sorted(p.name for p in (bundle / SOURCES_DIR).glob("*.txt"))
    assert len(kept) == 1, f"the same document was stored twice: {kept}"


def test_collapsing_whitespace_is_opt_in_and_recorded(tmp_path):
    """A collapsed match is a real match, but the record has to admit it."""
    bundle = _bundle(tmp_path)
    raw = b"art\xc3\xadculo\n\n   193   num. 8"
    plain = ingest_source(bundle, "AUTH-CL-001-01", filename="a.txt", data=raw)
    assert "\n" in plain["source_content"]

    collapsed = ingest_source(bundle, "AUTH-CL-001-01", filename="b.txt", data=raw,
                              collapse=True)
    assert collapsed["source_content"] == "artículo 193 num. 8"
    proof = json.loads((bundle / collapsed["proof"]["rel"]).read_text(encoding="utf-8"))
    assert proof["whitespace_collapsed"] is True
    assert proof["text_chars"] == len("artículo 193 num. 8")


def test_the_proof_sidecar_pins_the_text_that_was_matched(tmp_path):
    bundle = _bundle(tmp_path)
    out = ingest_source(bundle, "AUTH-CL-001-01", filename="nota.txt",
                        data="El artículo 193 num. 8".encode("utf-8"))
    proof = json.loads((bundle / out["proof"]["rel"]).read_text(encoding="utf-8"))
    assert proof["authority_id"] == "AUTH-CL-001-01"
    assert proof["violation_id"] == "CL-001"
    assert proof["artefact"]["sha256"] == hashlib.sha256("El artículo 193 num. 8".encode("utf-8")).hexdigest()
    assert proof["text_sha256"] == proof["artefact"]["sha256"]
    assert proof["text_source"] == "upload"
    assert proof["needs_text"] is False
    assert proof["ingested_at"]


def test_re_storing_identical_bytes_reuses_the_file(tmp_path):
    """Proof is never overwritten with a second copy of itself."""
    bundle = _bundle(tmp_path)
    first = ingest_source(bundle, "AUTH-CL-001-01", filename="nota.txt", data=b"mismo")
    second = ingest_source(bundle, "AUTH-CL-001-01", filename="nota.txt", data=b"mismo")
    assert second["artefact"]["reused"] is True
    assert second["artefact"]["rel"] == first["artefact"]["rel"]
    assert len(list((bundle / SOURCES_DIR).glob("*.txt"))) == 1


def test_re_storing_different_bytes_does_not_clobber_the_first(tmp_path):
    bundle = _bundle(tmp_path)
    first = ingest_source(bundle, "AUTH-CL-001-01", filename="nota.txt", data=b"primero")
    second = ingest_source(bundle, "AUTH-CL-001-01", filename="nota.txt", data=b"segundo")
    assert second["artefact"]["rel"] != first["artefact"]["rel"]
    assert (bundle / first["artefact"]["rel"]).read_bytes() == b"primero"


# ---------------------------------------------------------------------------
# Refusals — every one of them must happen before anything is written
# ---------------------------------------------------------------------------

def test_ingest_refuses_a_directory_that_is_not_a_bundle(tmp_path):
    (tmp_path / "build" / "CL-001").mkdir(parents=True)
    with pytest.raises(SourceError, match="bundle"):
        ingest_source(tmp_path / "build" / "CL-001", "AUTH-CL-001-01", text="x")


def test_ingest_refuses_a_missing_authority_id(tmp_path):
    with pytest.raises(SourceError, match="authority_id"):
        ingest_source(_bundle(tmp_path), "", text="x")


def test_ingest_refuses_an_oversize_upload_before_writing(tmp_path):
    bundle = _bundle(tmp_path)
    with pytest.raises(SourceError) as exc:
        ingest_source(bundle, "AUTH-CL-001-01", filename="big.txt",
                      data=b"x" * (MAX_UPLOAD_BYTES + 1))
    assert "limit" in str(exc.value)
    assert not (bundle / SOURCES_DIR).exists() or not list((bundle / SOURCES_DIR).iterdir())


def test_ingest_refuses_a_host_it_cannot_reach(tmp_path):
    with pytest.raises(SourceError):
        ingest_source(_bundle(tmp_path), "AUTH-CL-001-01",
                      source_url="http://169.254.169.254/latest/meta-data/", do_fetch=True)


def test_ingest_with_nothing_to_store_is_refused(tmp_path):
    with pytest.raises(SourceError):
        ingest_source(_bundle(tmp_path), "AUTH-CL-001-01")


def test_decode_base64_payload_rejects_junk():
    assert decode_base64_payload(base64.b64encode(b"ok").decode()) == b"ok"
    with pytest.raises(SourceError):
        decode_base64_payload("!!! not base64 !!!")


# ---------------------------------------------------------------------------
# Removing a stored source — the only irreversible thing in this module
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("AUTH-1__nota.pdf", "AUTH-1__nota"),
    ("AUTH-1__nota.proof.json", "AUTH-1__nota"),
    ("AUTH-1__nota.text.txt", "AUTH-1__nota"),
    # No extension at all: the whole name is the stem.
    ("AUTH-1__nota", "AUTH-1__nota"),
    # Only the *last* extension goes: `.text.txt` is a companion, `.tar.gz` is
    # part of the document's own name.
    ("AUTH-1__archivo.tar.gz", "AUTH-1__archivo.tar"),
    # `-2` is a separate source, deliberately: `_unique_path` mints it so a
    # same-named upload with different bytes is not lost, and grouping by prefix
    # would delete it along with its neighbour.
    ("AUTH-1__nota-2.pdf", "AUTH-1__nota-2"),
])
def test_proof_stem_groups_a_source_with_its_companions(name, expected):
    assert proof_stem(name) == expected


def test_proof_stem_ignores_a_directory_that_came_along():
    """Only ever the last component, because the caller's string is a name."""
    assert proof_stem("Authority sources/AUTH-1__nota.proof.json") == "AUTH-1__nota"


def test_delete_source_removes_the_document_sidecar_and_text(tmp_path):
    bundle = _bundle(tmp_path)
    stored = ingest_source(bundle, "AUTH-CL-001-01", filename="pagina.html",
                           data=b"<html><body>el art\xc3\xadculo 19</body></html>")
    directory = bundle / SOURCES_DIR
    assert len(list(directory.iterdir())) == 3, "expected a document, a sidecar and a text file"

    out = delete_source(bundle, "AUTH-CL-001-01", stored["artefact"]["name"])
    assert out["ok"] is True
    assert out["deleted"] == sorted(
        [f"{SOURCES_DIR}/{stored['artefact']['name']}", stored["proof"]["rel"],
         f"{SOURCES_DIR}/{Path(stored['artefact']['name']).stem}{TEXT_SUFFIX}"],
    ), out
    assert out["freed_bytes"] > 0
    assert not list(directory.iterdir()), "a file of the removed source was left behind"
    # The directory itself stays: it belongs to the bundle, not to the source, and
    # the next store (the replacement) expects to find it.
    assert directory.is_dir()


def test_delete_source_leaves_a_sibling_of_the_same_stem(tmp_path):
    """`-2` is a different source, so it is not swept up."""
    bundle = _bundle(tmp_path)
    first = ingest_source(bundle, "AUTH-CL-001-01", filename="nota.txt", data=b"primero")
    second = ingest_source(bundle, "AUTH-CL-001-01", filename="nota.txt", data=b"segundo")
    assert second["artefact"]["name"] == first["artefact"]["name"].replace(".txt", "-2.txt")

    delete_source(bundle, "AUTH-CL-001-01", first["artefact"]["name"])
    assert (bundle / second["artefact"]["rel"]).is_file()
    assert (bundle / second["proof"]["rel"]).is_file()


def test_delete_source_leaves_another_stubs_proof_alone(tmp_path):
    bundle = _bundle(tmp_path)
    mine = ingest_source(bundle, "AUTH-CL-001-01", filename="nota.txt", data=b"mia")
    theirs = ingest_source(bundle, "AUTH-CL-001-02", filename="nota.txt", data=b"suya")

    delete_source(bundle, "AUTH-CL-001-01", mine["artefact"]["name"])
    assert (bundle / theirs["artefact"]["rel"]).is_file()
    assert not (bundle / mine["artefact"]["rel"]).exists()


def test_delete_source_refuses_a_name_that_belongs_to_another_stub(tmp_path):
    bundle = _bundle(tmp_path)
    theirs = ingest_source(bundle, "AUTH-CL-001-02", filename="nota.txt", data=b"suya")
    with pytest.raises(SourceError, match="AUTH-CL-001-01"):
        delete_source(bundle, "AUTH-CL-001-01", theirs["artefact"]["name"])
    assert (bundle / theirs["artefact"]["rel"]).is_file()


@pytest.mark.parametrize("name", [
    "../CL-001.json",
    "../../CL-001.json",
    f"{SOURCES_DIR}/AUTH-CL-001-01__nota.txt",
    "sub/AUTH-CL-001-01__nota.txt",
    "..\\AUTH-CL-001-01__nota.txt",
    "AUTH-CL-001-01__nota\x00.txt",
])
def test_delete_source_refuses_a_path(tmp_path, name):
    """Every way of spelling "a file name" that is not one."""
    bundle = _bundle(tmp_path)
    stored = ingest_source(bundle, "AUTH-CL-001-01", filename="nota.txt", data=b"mia")
    with pytest.raises(SourceError):
        delete_source(bundle, "AUTH-CL-001-01", name)
    assert (bundle / stored["artefact"]["rel"]).is_file()
    assert (bundle / "CL-001.json").is_file()


def test_delete_source_refuses_a_name_it_cannot_see(tmp_path):
    bundle = _bundle(tmp_path)
    ingest_source(bundle, "AUTH-CL-001-01", filename="nota.txt", data=b"mia")
    with pytest.raises(SourceError, match="no stored source"):
        delete_source(bundle, "AUTH-CL-001-01", "AUTH-CL-001-01__fantasma.txt")


def test_delete_source_is_not_idempotent_about_it(tmp_path):
    """The second call must say the file is gone, not report a success it did
    not have. The browser's two-click consent can arrive twice (a double click,
    a retry after a timeout) and a silent `ok: true` there would tell the
    reviewer a file was removed when nothing happened."""
    bundle = _bundle(tmp_path)
    stored = ingest_source(bundle, "AUTH-CL-001-01", filename="nota.txt", data=b"mia")
    delete_source(bundle, "AUTH-CL-001-01", stored["artefact"]["name"])
    with pytest.raises(SourceError, match="no stored source"):
        delete_source(bundle, "AUTH-CL-001-01", stored["artefact"]["name"])


def test_delete_source_works_without_a_sources_directory(tmp_path):
    """Nothing was ever stored here, which is not an error worth a stack trace."""
    bundle = _bundle(tmp_path)
    with pytest.raises(SourceError, match=SOURCES_DIR):
        delete_source(bundle, "AUTH-CL-001-01", "AUTH-CL-001-01__nota.txt")
    # `ingest_source` would create it; a read-only question must not.
    assert not (bundle / SOURCES_DIR).exists()


def test_delete_source_refuses_a_directory_that_is_not_a_bundle(tmp_path):
    plain = tmp_path / "build" / "CL-001"
    plain.mkdir(parents=True)
    with pytest.raises(SourceError, match="bundle"):
        delete_source(plain, "AUTH-CL-001-01", "AUTH-CL-001-01__nota.txt")


def test_delete_source_refuses_a_symlink_pointing_out_of_the_directory(tmp_path):
    """A link inside the directory is not a file of this bundle.

    `_unique_path` never writes one, so a symlink is either a leftover from
    something else or a deliberate attempt to make a stored source name resolve
    to a file outside `Authority sources/`. Neither is proof to delete, and both
    are cheap to refuse.
    """
    bundle = _bundle(tmp_path)
    directory = bundle / SOURCES_DIR
    directory.mkdir()
    (bundle / "CL-001.json").write_bytes(b"{}")
    secret = tmp_path / "outside.txt"
    secret.write_text("not proof", encoding="utf-8")
    link = directory / "AUTH-CL-001-01__nota.txt"
    link.symlink_to(secret)

    delete_source(bundle, "AUTH-CL-001-01", link.name)
    # The link goes; the file it points at is none of this module's business. What
    # must not happen is the *target* being followed and removed.
    assert secret.is_file(), "the unlink followed a symlink out of the directory"
    assert not link.exists()


def test_delete_source_makes_the_stored_source_storable_again(tmp_path):
    """The whole point: after this, the same document can be attached again."""
    bundle = _bundle(tmp_path)
    pdf = _minimal_pdf("El articulo 19 num 3")
    first = ingest_source(bundle, "AUTH-CL-001-01", filename="decreto.pdf", data=pdf)
    delete_source(bundle, "AUTH-CL-001-01", first["artefact"]["name"])

    again = ingest_source(bundle, "AUTH-CL-001-01", filename="decreto.pdf", data=pdf)
    assert again["artefact"]["name"] == first["artefact"]["name"], (
        "the replacement did not land on the old name, so the bundle now holds two"
    )
    assert again["artefact"]["reused"] is False, "the document was not actually removed"


# ---------------------------------------------------------------------------
# The route
# ---------------------------------------------------------------------------

def _bundle(root: Path, violation_id: str = "CL-001") -> Path:
    bundle = root / "build" / violation_id
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / f"{violation_id}.json").write_text("{}", encoding="utf-8")
    return bundle


def _minimal_pdf(text: str) -> bytes:
    """A one-page PDF whose only content is ``text``, with a real xref table.

    Hand-rolled because the repository has no PDF writer: pypdf can read a PDF
    but not author one, and a document without a `startxref` is rejected before
    any page is parsed — so the offsets have to be tracked as the objects are
    emitted rather than faked.

    Single-column on purpose. This is the fixture for the case where no gutter
    *may* be found, so the text it puts on the page must be one run of single
    spaces: a wide gap here would be a gutter the test would then be asserting
    the pass ignored, which is the opposite of what the fixture is for.
    """
    body = b"BT /F1 12 Tf 20 100 Td (" + text.encode("latin-1") + b") Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(body)).encode() + b" >>\nstream\n" + body + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)
