"""Ingest the juris-search Brazilian-PT jurisprudence corpus into Qdrant.

Reads `index.json` (default: $JURIS_INDEX or
/Users/dev/services/juris-search/json_jurisprudence/index.json), iterates
every `status=ready` ruling, chunks the body, embeds with the configured
provider (Voyage by default), and upserts into the
`<prefix>_jurisprudence` collection.

Usage:
    python examples/ingest_jurisprudence.py [--index PATH] [--limit N]
                                            [--skip N] [--batch 64]
                                            [--sleep 0.0]
                                            [--max-chunks 8]

For Voyage free tier (3 RPM) over the full 1040 rulings, use:
    --batch 128 --sleep 21.0 --max-chunks 4
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Allow running this script directly from the examples/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from violation_pack import (  # noqa: E402
    JurisprudenceIngester,
    Settings,
    get_vector_index,
    load_dotenv,
)


DEFAULT_INDEX = "/Users/dev/services/juris-search/json_jurisprudence/index.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--index",
        default=os.environ.get("JURIS_INDEX", DEFAULT_INDEX),
        help=f"Path to juris-search index.json (default: {DEFAULT_INDEX})",
    )
    ap.add_argument("--limit", type=int, default=None, help="Cap rulings processed.")
    ap.add_argument("--skip", type=int, default=0, help="Skip first N ready entries.")
    ap.add_argument("--batch", type=int, default=64, help="Embed batch size.")
    ap.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Seconds to sleep between batches (Voyage free tier: 21.0).",
    )
    ap.add_argument(
        "--max-chunks",
        type=int,
        default=8,
        help="Cap chunks per ruling (0 = no cap).",
    )
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

    max_chunks = args.max_chunks if args.max_chunks and args.max_chunks > 0 else None
    ing = JurisprudenceIngester(
        index=index,
        batch_size=args.batch,
        sleep_between_batches=args.sleep,
        max_chunks_per_ruling=max_chunks,
    )

    started = time.time()

    def _progress(stats):
        elapsed = time.time() - started
        rate = stats.upserted / elapsed if elapsed > 0 else 0.0
        print(
            f"[ingest] scanned={stats.scanned} upserted={stats.upserted} "
            f"failed={stats.failed} elapsed={elapsed:.1f}s "
            f"rate={rate:.1f} pts/s",
            file=sys.stderr,
        )

    stats = ing.ingest(
        args.index, limit=args.limit, skip=args.skip, on_progress=_progress
    )
    print(json.dumps(stats.as_dict(), indent=2, ensure_ascii=False))
    return 0 if stats.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
