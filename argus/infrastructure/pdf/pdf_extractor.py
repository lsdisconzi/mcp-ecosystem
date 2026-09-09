# -*- coding: utf-8 -*-
"""
infrastructure/pdf/pdf_extractor.py

Wraps PDF text extraction (pdfminer.six with PyPDF2 fallback).
This is the only place in the codebase that imports PDF libraries.
"""
import os
import tempfile
from typing import IO


class PdfExtractor:
    """Extract plain text from PDF file objects."""

    def extract(self, file_obj: IO[bytes]) -> str:
        """
        Extract text from an open binary file object.
        Tries pdfminer.six first; falls back to PyPDF2.
        Raises ImportError if neither library is available.
        """
        fd, temp_path = tempfile.mkstemp(suffix=".pdf")
        try:
            os.close(fd)
            with open(temp_path, "wb") as f:
                f.write(file_obj.read())
            return self._extract_from_path(temp_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def _extract_from_path(self, path: str) -> str:
        try:
            from pdfminer.high_level import extract_text  # type: ignore
            return extract_text(path)
        except ImportError:
            pass

        try:
            import PyPDF2  # type: ignore
            parts = []
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        parts.append(text)
            return "\n".join(parts)
        except ImportError:
            pass

        raise ImportError(
            "No PDF extraction library found. Install pdfminer.six or PyPDF2."
        )
