"""End-to-end wiring of the Qdrant + Neo4j extensions over CL-005.

Usage:
    python examples/wire_extensions.py            # uses env-configured services
    python examples/wire_extensions.py --no-neo4j # skip the graph leg
    python examples/wire_extensions.py --no-qdrant

Pre-requisites: see .env.example. The script loads .env automatically.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from violation_pack import (
    Settings,
    Violation,
    get_knowledge_graph,
    get_vector_index,
)


def _load_demo_violation() -> Violation:
    """Build CL-005 via the canonical example, then read its JSON."""
    import subprocess
    import sys

    root = Path(__file__).resolve().parent.parent
    demo = root / "examples" / "refine_cl005.py"
    out_json = root / "build" / "CL-005" / "CL-005.json"
    if not out_json.exists():
        subprocess.check_call([sys.executable, str(demo)], cwd=root)
    return Violation.model_validate_json(out_json.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-qdrant", action="store_true")
    ap.add_argument("--no-neo4j", action="store_true")
    ap.add_argument("--violation-json", type=Path, default=None,
                    help="Path to an existing <vid>.json. Defaults to CL-005.")
    args = ap.parse_args()

    settings = Settings.from_env()
    print("Settings:")
    print(f"  qdrant_url = {settings.qdrant_url or '(unset)'}")
    print(f"  neo4j_uri  = {settings.neo4j_uri  or '(unset)'}")
    print(f"  ollama_host= {settings.ollama_host or '(unset)'}")
    print()

    v = (
        Violation.model_validate_json(args.violation_json.read_text(encoding="utf-8"))
        if args.violation_json
        else _load_demo_violation()
    )
    print(f"Loaded violation: {v.violation_id} — {v.title}")
    print(
        f"  segments={len(v.segments)}  articles={len(v.established_articles)}  "
        f"authorities={len(v.authorities)}"
    )

    if not args.no_qdrant:
        if not settings.qdrant_url:
            print("Skipping Qdrant: QDRANT_URL is not set.")
        else:
            print("\n-- Qdrant --")
            idx = get_vector_index(settings)
            counts = idx.upsert_violation(v)
            print(f"  upserted: {counts}")
            seg_query = (
                v.segments[0].verbatim_es[:80] if v.segments else "Carabineros"
            )
            hits = idx.search_segments(seg_query, top_k=3)
            print(f"  top segments for query={seg_query!r}:")
            for h in hits:
                print(
                    f"    {h['score']:.3f}  "
                    f"{h['payload'].get('violation_id')}/"
                    f"{h['payload'].get('segment_id')}"
                )

    if not args.no_neo4j:
        if not (settings.neo4j_uri and settings.neo4j_user and settings.neo4j_password):
            print("Skipping Neo4j: NEO4J_LOCAL_* not configured.")
        else:
            print("\n-- Neo4j --")
            with get_knowledge_graph(settings) as kg:
                kg.upsert_violation(v)
                print(f"  upserted {v.violation_id}")
                for art in v.established_articles[:3]:
                    cites = kg.find_violations_citing(art.article_id)
                    print(f"  citing {art.article_id}: {cites}")
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
