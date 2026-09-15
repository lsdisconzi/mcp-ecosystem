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
from pathlib import Path

import pytest

from violation_pack.authority_source import (
    MAX_UPLOAD_BYTES,
    PROOF_SUFFIX,
    SOURCES_DIR,
    TEXT_SUFFIX,
    SourceError,
    _PDF_EXTRACTORS,
    decode_base64_payload,
    delete_source,
    extract_pdf_text,
    fetched_filename,
    ingest_source,
    name_from_url,
    proof_stem,
    sanitise_filename,
    strip_markup,
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
