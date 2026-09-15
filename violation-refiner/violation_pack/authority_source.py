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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
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

#: Optional PDF extractors, tried in this order. `pypdf` is the maintained
#: successor of `PyPDF2`; `fitz` is PyMuPDF. None is a hard dependency of this
#: project, so a PDF upload without one of them still stores the artefact and
#: its hash and simply reports that no text was extracted.
_PDF_EXTRACTORS: tuple[tuple[str, str], ...] = (
    ("pypdf", "read_pypdf"),
    ("PyPDF2", "read_pypdf"),
    ("fitz", "read_fitz"),
)


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


def _read_pypdf(data: bytes) -> str:
    import io

    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:  # pragma: no cover - depends on the installed extras
        from PyPDF2 import PdfReader  # type: ignore

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _read_fitz(data: bytes) -> str:
    import fitz  # type: ignore

    with fitz.open(stream=data, filetype="pdf") as doc:  # pragma: no cover - optional extra
        return "\n".join(page.get_text() for page in doc)


def extract_pdf_text(data: bytes) -> tuple[str | None, str | None, list[str]]:
    """Extract a PDF's text with whichever optional reader is installed.

    Returns ``(text, extractor, warnings)``. With no reader installed the text
    is ``None`` and the warning names the install — but the artefact is still
    ingested by the caller, so the proof is never lost just because the venv
    is missing a parser.
    """
    tried: list[str] = []
    for module_name, helper in _PDF_EXTRACTORS:
        try:
            __import__(module_name)
        except ImportError:
            tried.append(module_name)
            continue
        try:
            text = globals()[helper](data)
        except Exception as exc:  # noqa: BLE001 - a broken PDF must not 500
            return None, module_name, [
                f"{module_name} is installed but could not read this PDF "
                f"({type(exc).__name__}: {exc}); paste the section text instead",
            ]
        return collapse_whitespace(text), module_name, []
    return None, None, [
        "no PDF text extractor is installed (" + ", ".join(tried) + "); the PDF "
        "is stored and hashed as proof, but paste the passage you want matched "
        "or install pypdf to have it read here",
    ]


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
    elif data is not None:
        # Prefix the reviewer's filename with the authority id. Two stubs
        # verified against two different sentencias otherwise land as
        # `sentencia.pdf` and `sentencia-2.pdf`, and the bundle no longer says
        # which proof belongs to which proposition — the one question this
        # directory exists to answer.
        filename = f"{authority_id}__{filename}"
    filename = sanitise_filename(filename)
    suffix = Path(filename).suffix.lower()

    artefact_text: str | None = None
    extractor: str | None = None
    if data is not None:
        if suffix == ".pdf" or data[:5] == b"%PDF-":
            artefact_text, extractor, pdf_warnings = extract_pdf_text(data)
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
    # own bytes — a PDF, or an upload whose reading disagreed with what the
    # reviewer pasted. Without this the bundle would hold a document whose
    # SHA256 is nowhere in the record and a hash whose text is nowhere on disk.
    text_rel: str | None = None
    if content is not None and (data is None or artefact_text != content):
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


def decode_base64_payload(value: str) -> bytes:
    """Decode a JSON-carried upload, refusing the two shapes that mean "empty"."""
    if not isinstance(value, str) or not value.strip():
        raise SourceError("content_base64 is empty")
    try:
        return base64.b64decode(value, validate=True)
    except Exception as exc:  # noqa: BLE001 - any decode failure is a client error
        raise SourceError(f"content_base64 is not valid base64 ({exc})") from exc
