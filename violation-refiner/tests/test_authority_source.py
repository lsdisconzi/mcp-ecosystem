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
    decode_base64_payload,
    extract_pdf_text,
    fetched_filename,
    ingest_source,
    name_from_url,
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
# The route
# ---------------------------------------------------------------------------

def _bundle(root: Path, violation_id: str = "CL-001") -> Path:
    bundle = root / "build" / violation_id
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / f"{violation_id}.json").write_text("{}", encoding="utf-8")
    return bundle
