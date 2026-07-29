#!/usr/bin/env python3
"""
Batch ingest extracted jurisprudence documents into Qdrant juris_br_v1 collection.

Uses the management API's structured_ingest endpoint which handles
server-side embedding (768-dim).

Usage:
    cd /root/juris-search
    source .venv/bin/activate
    python ingest_to_qdrant.py --limit 10      # test with 10 docs
    python ingest_to_qdrant.py                  # all 706 docs
"""

import argparse
import json
import os
import sys
import time
import uuid
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Tuple

API_BASE = "http://localhost:8066"
COLLECTION = "juris_br_v1"
BATCH_SIZE = 50

# Use environment variable with fallback to project-relative path
_BASE = Path(__file__).resolve().parent
EXTRACTIONS_DIR = os.environ.get(
    "JURIS_SEARCH_EXTRACTIONS_DIR",
    str(_BASE / "extracted_documents")
)


def _doc_uuid(doc_id: str) -> str:
    """Deterministic UUID from document ID."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"juris-search:{doc_id}"))


def _http_post_json(url: str, payload: dict, timeout: int = 120) -> Tuple[int, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        try:
            return e.code, json.loads(body) if body else {"detail": str(e)}
        except json.JSONDecodeError:
            return e.code, {"detail": body[:500]}


def build_embedding_text(doc: dict) -> str:
    """Compose text for semantic embedding from structured fields."""
    parts = [f"Tribunal: {doc.get('tribunal') or 'N/D'}"]

    proc = doc.get("numero_processo") or doc.get("cnj_numero") or "N/D"
    parts.append(f"Processo: {proc}")

    if doc.get("classe"):
        parts.append(f"Classe: {doc['classe']}")
    if doc.get("relator"):
        parts.append(f"Relator: {doc['relator']}")
    if doc.get("orgao_julgador"):
        parts.append(f"Órgão julgador: {doc['orgao_julgador']}")
    if doc.get("comarca"):
        parts.append(f"Comarca: {doc['comarca']}")
    if doc.get("data_julgamento"):
        parts.append(f"Julgado em: {doc['data_julgamento']}")

    outcome = doc.get("outcome")
    if outcome:
        parts.append(f"Resultado: {', '.join(outcome) if isinstance(outcome, list) else outcome}")

    assuntos = doc.get("assuntos")
    if assuntos:
        parts.append(f"Assuntos: {', '.join(assuntos) if isinstance(assuntos, list) else assuntos}")

    header = " | ".join(parts)

    # Body: ementa + decisao
    body_parts = []
    ementa = doc.get("ementa", "")
    if ementa:
        body_parts.append(f"EMENTA:\n{ementa}")

    decisao = doc.get("decisao", "")
    if decisao:
        body_parts.append(f"DECISÃO:\n{decisao}")

    leg = doc.get("legislacao_citada")
    if leg:
        leg_str = ", ".join(leg) if isinstance(leg, list) else leg
        body_parts.append(f"LEGISLAÇÃO CITADA:\n{leg_str}")

    body = "\n\n".join(body_parts) if body_parts else ementa

    return f"{header}\n\n{body}"


def build_item(doc: dict, doc_id: str) -> dict:
    """Build a structured_ingest item from an extraction document."""
    text = build_embedding_text(doc)

    payload = {
        "doc_id": doc_id,
        "tribunal": doc.get("tribunal"),
        "numero_processo": doc.get("numero_processo"),
        "cnj_numero": doc.get("cnj_numero"),
        "classe": doc.get("classe"),
        "relator": doc.get("relator"),
        "orgao_julgador": doc.get("orgao_julgador"),
        "comarca": doc.get("comarca"),
        "data_julgamento": doc.get("data_julgamento"),
        "ementa": doc.get("ementa"),
        "decisao": doc.get("decisao"),
        "outcome": doc.get("outcome"),
        "assuntos": doc.get("assuntos"),
        "legislacao_citada": doc.get("legislacao_citada"),
        "partes": doc.get("partes"),
        "advogados": doc.get("advogados"),
        "votacao": doc.get("votacao"),
        "texto_length": doc.get("texto_length"),
        "source_file": doc.get("source_file"),
        "extracted_at": doc.get("extracted_at"),
        "court_specific": doc.get("court_specific"),
        "source": "juris-search-court-extractor",
    }

    # Remove None values
    payload = {k: v for k, v in payload.items() if v is not None}

    uid = _doc_uuid(doc_id)
    return {
        "id": uid,
        "doc_id": doc_id,
        "text": text,
        "content": text,
        "metadata": payload,
        **payload,
    }


def ensure_collection() -> bool:
    """Ensure juris_br_v1 exists and is connected."""
    # Connect first (required by management API)
    status, body = _http_post_json(f"{API_BASE}/v1/qdrant/connect", {})
    print(f"Connect: {status} -> {json.dumps(body)[:200]}")

    # Check existing collections
    status, body = _http_post_json(f"{API_BASE}/v1/qdrant/collections", {}, timeout=10)
    if status == 200:
        names = [c.get("name") for c in body.get("collections", [])]
        if COLLECTION not in names:
            # Create collection
            print(f"Creating collection '{COLLECTION}' ...")
            status, body = _http_post_json(
                f"{API_BASE}/v1/qdrant/collections",
                {"name": COLLECTION, "vector_size": 768},
            )
            print(f"Create: {status} -> {json.dumps(body)[:200]}")
            return status < 400
    return True


def ingest_batch(items: List[dict]) -> Tuple[int, str]:
    """Send a batch to structured_ingest."""
    payload = {
        "collection_name": COLLECTION,
        "data_type": "law",
        "items": items,
    }
    status, body = _http_post_json(
        f"{API_BASE}/v1/qdrant/collections/structured_ingest",
        payload,
        timeout=300,
    )
    error = ""
    if status >= 400:
        error = body.get("detail") or json.dumps(body)[:500]
    return status, error


def main():
    parser = argparse.ArgumentParser(description="Ingest extractions to Qdrant juris_br_v1")
    parser.add_argument("--limit", type=int, default=0, help="Max docs to ingest (0=all)")
    parser.add_argument("--dry-run", action="store_true", help="Show items without sending")
    args = parser.parse_args()

    # Load all extraction files
    ext_dir = Path(EXTRACTIONS_DIR)
    files = sorted(ext_dir.glob("*.json"))
    if args.limit:
        files = files[:args.limit]

    print(f"Found {len(files)} extraction files")

    if not args.dry_run:
        ensure_collection()

    # Build items
    items: List[dict] = []
    skipped = 0
    for fpath in files:
        try:
            with open(fpath) as f:
                doc = json.load(f)
        except Exception:
            skipped += 1
            continue

        doc_id = os.path.splitext(fpath.name)[0]
        item = build_item(doc, doc_id)
        items.append(item)

    print(f"Built {len(items)} items ({skipped} skipped)")

    if args.dry_run:
        # Show first item
        if items:
            print("\nSample item:")
            i = items[0]
            print(f"  id: {i['id']}")
            print(f"  doc_id: {i['doc_id']}")
            print(f"  text (first 300): {i['text'][:300]}...")
            print(f"  text length: {len(i['text'])}")
            print(f"  metadata keys: {list(i.get('metadata', {}).keys())}")
        return

    # Batch ingest
    total = len(items)
    ok_count = 0
    for i in range(0, total, BATCH_SIZE):
        batch = items[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"Batch {batch_num}/{total_batches}: {len(batch)} items ...", end=" ", flush=True)

        status, error = ingest_batch(batch)
        if status < 400:
            ok_count += len(batch)
            print(f"OK ({ok_count}/{total})")
        else:
            print(f"FAILED (status={status}): {error[:200]}")
            # Try one by one on failure
            print("  Retrying one-by-one...")
            for item in batch:
                s, e = ingest_batch([item])
                if s < 400:
                    ok_count += 1
                else:
                    print(f"    FAILED {item.get('doc_id','?')[:60]}: {e[:150]}")

    print(f"\nIngested: {ok_count}/{total}")

    # Verify
    status, body = _http_post_json(
        f"{API_BASE}/v1/qdrant/collections/{COLLECTION}/summary",
        {},
        timeout=10,
    )
    if status == 200:
        print(f"Collection '{COLLECTION}': {body.get('points_count', '?')} points")


def ingest_single(doc: dict, doc_id: str = None, collection: str = COLLECTION,
                  api_base: str = API_BASE) -> Dict[str, Any]:
    """Importable helper: ingest a single extracted document into Qdrant.

    Args:
        doc: Extracted document dict (from court_extractor).
        doc_id: Unique document ID.  Defaults to source_file or extracted file name.
        collection: Qdrant collection name.
        api_base: Qdrant management API base URL.

    Returns:
        {"ok": True, "point_id": str} or {"ok": False, "error": str}
    """
    if doc_id is None:
        doc_id = doc.get("source_file") or doc.get("numero_processo") or "unknown"
    item = build_item(doc, doc_id)
    payload = {
        "collection_name": collection,
        "data_type": "law",
        "items": [item],
    }
    status, body = _http_post_json(
        f"{api_base}/v1/qdrant/collections/structured_ingest",
        payload,
        timeout=120,
    )
    if 200 <= status < 300:
        return {"ok": True, "point_id": item["id"]}
    return {"ok": False, "error": body.get("detail") or str(body)[:500]}


if __name__ == "__main__":
    main()
