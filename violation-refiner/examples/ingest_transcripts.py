"""Ingest an OliviaLegal incident bundle's transcripts into Qdrant.

Default bundle: $TRANSCRIPT_BUNDLE or the LATAM 2024-07-05 incident.

Usage:
    python examples/ingest_transcripts.py [--bundle PATH] [--bundle-id NAME]
                                          [--limit-segments N] [--batch 64]
                                          [--sleep 0.0]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from violation_pack import (  # noqa: E402
    Settings,
    TranscriptIngester,
    get_vector_index,
    load_dotenv,
)


DEFAULT_BUNDLE = (
    "/Users/leandrodisconzi/work/business/OliviaLegal/"
    "cases/INCIDENTS/INCIDENT_2024-07-05"
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--bundle",
        default=os.environ.get("TRANSCRIPT_BUNDLE", DEFAULT_BUNDLE),
        help=f"Bundle root (default: {DEFAULT_BUNDLE})",
    )
    ap.add_argument("--bundle-id", default=None, help="Override bundle id tag.")
    ap.add_argument("--limit-segments", type=int, default=None)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--sleep", type=float, default=0.0)
    args = ap.parse_args()

    load_dotenv()
    settings = Settings.from_env()
    print(
        f"[ingest] qdrant={settings.qdrant_url}  prefix={settings.qdrant_collection_prefix}",
        file=sys.stderr,
    )

    index = get_vector_index(settings)
    index.ensure_collections()
    print(
        f"[ingest] embedder={index.embedder.name}  dim={index.embedder.dim}",
        file=sys.stderr,
    )

    ing = TranscriptIngester(
        index=index, batch_size=args.batch, sleep_between_batches=args.sleep
    )
    started = time.time()
    stats = ing.ingest_bundle(
        args.bundle,
        bundle_id=args.bundle_id,
        limit_segments=args.limit_segments,
    )
    print(
        f"[ingest] done in {time.time() - started:.1f}s",
        file=sys.stderr,
    )
    print(json.dumps(stats.as_dict(), indent=2, ensure_ascii=False))
    return 0 if stats.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
