#!/usr/bin/env python3
"""Simple script to test chunking for a given file using project utilities.
Usage:
  PYTHONPATH=. ./scripts/test_chunking.py /path/to/file.md
"""
import sys
from pathlib import Path
from utils.document_ingestor import process_file_for_ingestion


def main():
    if len(sys.argv) < 2:
        print("Usage: test_chunking.py /path/to/file")
        sys.exit(2)

    path = Path(sys.argv[1])
    if not path.exists():
        print("File not found:", path)
        sys.exit(2)

    content = path.read_text(encoding='utf-8', errors='ignore')
    items = process_file_for_ingestion(str(path), content, embedding_dim=384)

    print(f"File: {path}")
    print(f"Chunks: {len(items)}")
    sizes = [len(i['text']) for i in items]
    print(f"Chunk sizes (min/avg/max): {min(sizes)}/{sum(sizes)/len(sizes):.1f}/{max(sizes)}")
    print('\nSample chunks:')
    for i in items[:5]:
        print(f"- index={i['chunk_index']}, size={i['metadata']['chunk_size']}, header_path={i['metadata'].get('header_path')}")


if __name__ == '__main__':
    main()
