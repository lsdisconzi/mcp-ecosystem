"""Admin script: reset Qdrant collections and the Neo4j database, then
re-index CL-005 with the current embedder.

Usage:
    python examples/reset_stores.py            # full wipe + re-ingest CL-005
    python examples/reset_stores.py --no-ingest

Both destructive operations only affect the violation-refiner namespace:
* Qdrant: collections prefixed with QDRANT_COLLECTION_PREFIX
* Neo4j:  the database named NEO4J_DATABASE
"""
from __future__ import annotations

import argparse
from pathlib import Path

from violation_pack import (
    Settings,
    Violation,
    get_knowledge_graph,
    get_vector_index,
)
from violation_pack.embeddings import default_embedder


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ingest", action="store_true",
                    help="Just reset; do not re-ingest CL-005 after.")
    ap.add_argument("--violation-json", type=Path, default=None)
    args = ap.parse_args()

    s = Settings.from_env()
    emb = default_embedder(s)
    print(f"Embedder: {getattr(emb, 'name', type(emb).__name__)}  dim={emb.dim}")
    print(f"Qdrant prefix : {s.qdrant_collection_prefix}")
    print(f"Neo4j database: {s.neo4j_database}")
    print()

    # ---- Qdrant
    if not s.qdrant_url:
        print("Skipping Qdrant: QDRANT_URL not set.")
    else:
        idx = get_vector_index(s)
        result = idx.reset_collections()
        print("Qdrant reset:")
        for name, info in result.items():
            print(f"  {name}: {info}")

    # ---- Neo4j
    if not (s.neo4j_uri and s.neo4j_user and s.neo4j_password):
        print("Skipping Neo4j: credentials not set.")
    else:
        with get_knowledge_graph(s) as kg:
            counts = kg.reset_database()
            print(f"Neo4j reset on {s.neo4j_database}: {counts}")

    # ---- Re-ingest
    if args.no_ingest:
        return 0
    root = Path(__file__).resolve().parent.parent
    if args.violation_json:
        v = Violation.model_validate_json(
            args.violation_json.read_text(encoding="utf-8")
        )
    else:
        out_json = root / "build" / "CL-005" / "CL-005.json"
        if not out_json.exists():
            import subprocess
            import sys
            subprocess.check_call(
                [sys.executable, str(root / "examples" / "refine_cl005.py")],
                cwd=root,
            )
        v = Violation.model_validate_json(out_json.read_text(encoding="utf-8"))

    print(f"\nIngesting {v.violation_id} ...")
    if s.qdrant_url:
        counts = get_vector_index(s).upsert_violation(v)
        print(f"  Qdrant: {counts}")
    if s.neo4j_uri and s.neo4j_user and s.neo4j_password:
        with get_knowledge_graph(s) as kg:
            kg.upsert_violation(v)
        print(f"  Neo4j:  upserted {v.violation_id}")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
