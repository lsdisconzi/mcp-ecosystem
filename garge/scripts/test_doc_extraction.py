"""Quick script to test DOC extraction with DocumentProcessor.

Usage:
    python scripts/test_doc_extraction.py /path/to/file.doc

Prints available extractors and the first 2000 characters of extracted text.
"""
import sys
from core.ingestion.document_processor import DocumentProcessor


def main(path: str):
    dp = DocumentProcessor()
    print("Detected DOC extractors:", getattr(dp, 'available_doc_extractors', []))
    text = dp._read_doc(path) if path.lower().endswith('.doc') else None
    if text is None:
        print("No extraction attempted (not a .doc file).")
        return
    if not text.strip():
        print("Extraction failed or returned empty text.")
    else:
        print("--- Extracted text preview ---")
        print(text[:2000])


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_doc_extraction.py /path/to/file.doc")
        sys.exit(1)
    main(sys.argv[1])