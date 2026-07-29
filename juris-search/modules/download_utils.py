"""Resilient file-download helper for court document scrapers.

The legacy download path did ``content = resp.content; f.write(content)`` with
no verification. When a connection drops mid-transfer, a truncated body is
written to disk and silently recorded as a successful download, producing
corrupt PDFs missing their ``%%EOF`` trailer.

This module provides ``download_to_file`` which:
  * streams the response in chunks (bounded memory regardless of file size),
  * writes to a ``.part`` temp file then atomically renames into place,
  * verifies the byte count against ``Content-Length`` (when present) and the
    full response length,
  * for PDFs, requires a trailing ``%%EOF`` marker,
  * retries on mismatch/error, and
  * on final failure removes any partial file so it is never mistaken for good.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("juris-search.download_utils")

PDF_EOF_RE = re.compile(rb"%%EOF\s*$")

DEFAULT_CHUNK_SIZE = 1 << 16          # 64 KiB
DEFAULT_TIMEOUT = 60
DEFAULT_RETRIES = 3


def _is_pdf_path(filepath: str) -> bool:
    return filepath.lower().endswith(".pdf")


def _has_pdf_eof(filepath: str) -> bool:
    try:
        with open(filepath, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            if size == 0:
                return False
            tail = min(size, 1024)
            fh.seek(size - tail)
            return bool(PDF_EOF_RE.search(fh.read()))
    except OSError:
        return False


def download_to_file(
    url: str,
    filepath: str,
    *,
    headers: Optional[dict] = None,
    cookies=None,
    timeout: int = DEFAULT_TIMEOUT,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    retries: int = DEFAULT_RETRIES,
    session: Optional[requests.Session] = None,
) -> int:
    """Stream *url* to *filepath*, verifying completeness.

    Returns the number of bytes written. Raises ``RuntimeError`` after all
    retries are exhausted (the partial ``.part`` file is cleaned up first).
    """
    filepath = str(filepath)
    part_path = filepath + ".part"
    requester = session if session is not None else requests

    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            resp = requester.get(
                url, headers=headers or {}, cookies=cookies,
                timeout=timeout, stream=True,
            )
            resp.raise_for_status()

            expected = resp.headers.get("content-length")
            expected = int(expected) if expected and expected.isdigit() else None

            written = 0
            with open(part_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    written += len(chunk)

            # Verify byte count (Content-Length takes priority, else the
            # response's own reported length is unavailable for streams, so we
            # only fail when Content-Length disagrees).
            if expected is not None and written != expected:
                raise RuntimeError(
                    f"truncated download: got {written} bytes, expected {expected}"
                )

            # PDFs must end with %%EOF; truncated streams often omit it.
            if _is_pdf_path(filepath) and not _has_pdf_eof(part_path):
                raise RuntimeError("PDF missing %%EOF trailer (truncated)")

            os.replace(part_path, filepath)
            return written

        except Exception as exc:  # network/verify/stream errors
            last_err = exc
            # remove any partial artifact from this attempt
            try:
                if os.path.exists(part_path):
                    os.remove(part_path)
            except OSError:
                pass
            if attempt < retries:
                logger.warning(
                    "Download attempt %d/%d failed for %s: %s",
                    attempt, retries, url, exc,
                )

    raise RuntimeError(f"download failed after {retries} attempts: {last_err}")


def _verify_pdf_complete(filepath: str) -> None:
    """Raise RuntimeError unless *filepath* is a non-truncated PDF.

    Checks the byte count against Content-Length (stored in the sidecar when
    available) and the presence of a trailing ``%%EOF`` marker.
    """
    path = Path(filepath)
    if not path.is_file():
        raise RuntimeError("file not written")
    size = path.stat().st_size
    if size == 0:
        raise RuntimeError("empty file (0 bytes)")

    # Compare against the expected size recorded in the sidecar, if present.
    sidecar_path = Path(str(filepath) + ".metadata.json")
    expected = None
    if sidecar_path.is_file():
        import json
        try:
            data = json.loads(sidecar_path.read_text(encoding="utf-8", errors="replace"))
            ev = data.get("file_size_bytes")
            if isinstance(ev, int) and ev > 0:
                expected = ev
        except Exception:
            pass
    if expected is not None and size != expected:
        raise RuntimeError(
            f"truncated PDF: {size} bytes on disk, expected {expected}"
        )
    if not _has_pdf_eof(str(path)):
        raise RuntimeError("PDF missing %%EOF trailer (truncated)")


def safe_download(
    url: str,
    filepath: str,
    *,
    headers: Optional[dict] = None,
    cookies=None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    session: Optional[requests.Session] = None,
) -> dict:
    """Convenience wrapper returning a result dict usable by scrapers.

    Mirrors the legacy behaviour of reporting {status, error, file_size_bytes}
    without raising, so callers can keep their current control flow.
    """
    try:
        size = download_to_file(
            url, filepath, headers=headers, cookies=cookies,
            timeout=timeout, retries=retries, session=session,
        )
        return {"status": "ok", "error": None, "file_size_bytes": size}
    except Exception as exc:
        return {"status": "error", "error": str(exc), "file_size_bytes": 0}
