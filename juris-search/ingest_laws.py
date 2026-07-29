#!/usr/bin/env python3
"""
Ingest legal framework articles into Qdrant via the management API.

Reads structured JSON articles from source_laws/law_json/{BR,CL,INT}/json/.
Each article becomes a vector point in the 'legal_framework' collection.
Uses the Qdrant management API at port 8066 (proxies to GCP Cloud Qdrant).

Usage:
    python ingest_laws.py                                       # ingest all (uses $LEGAL_FRAMEWORK_SOURCE_DIR or ./source_laws/law_json)
    python ingest_laws.py --source-dir /data/laws/json          # ingest from custom path
    python ingest_laws.py --dry-run                             # validate without pushing
    python ingest_laws.py --force                               # force re-ingest all
"""

import argparse
import glob
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime

# ── Config ───────────────────────────────────────────────────────────────────

LAW_JSON_DIR = os.environ.get(
    "LEGAL_FRAMEWORK_SOURCE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "source_laws", "law_json"),
)
QDRANT_API = os.environ.get("QDRANT_MANAGEMENT_API", "http://localhost:8066")
COLLECTION_NAME = "legal_framework"
VECTOR_SIZE = 768
DISTANCE_METRIC = "cosine"
UUID_NAMESPACE = uuid.NAMESPACE_URL
BATCH_SIZE = 100

# ── Utilities ────────────────────────────────────────────────────────────────


def _doc_uuid(doc_id: str) -> str:
    return str(uuid.uuid5(UUID_NAMESPACE, f"olivia-legal://law/{doc_id}"))


def _http_get_json(url: str, timeout: float = 15.0):
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        return exc.code, {"detail": str(exc)}
    except Exception as exc:
        return 0, {"detail": str(exc)}


def _http_post_json(url: str, payload: dict, timeout: float = 30.0):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", errors="replace")
            return exc.code, json.loads(raw) if raw else {"detail": str(exc)}
        except Exception:
            return exc.code, {"detail": str(exc)}
    except Exception as exc:
        return 0, {"detail": str(exc)}


def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


# ── Collection Management ────────────────────────────────────────────────────


def ensure_collection():
    """Ensure the legal_framework collection exists in Qdrant."""
    info_url = f"{QDRANT_API}/v1/qdrant/collections/{COLLECTION_NAME}/summary"
    status, body = _http_get_json(info_url)
    if 200 <= status < 300:
        print(f"  Collection '{COLLECTION_NAME}' already exists")
        return True

    print(f"  Creating collection '{COLLECTION_NAME}'...")
    create_url = f"{QDRANT_API}/v1/qdrant/collections"
    payload = {
        "name": COLLECTION_NAME,
        "vector_size": VECTOR_SIZE,
        "distance_metric": DISTANCE_METRIC,
        "description": "International and domestic aviation legal framework (BR/CL/INT)",
        "metadata": {
            "source": "olivia-legal",
            "schema_version": 1,
            "jurisdictions": ["BR", "CL", "INT"],
            "article_count": 658,
        },
    }
    status, body = _http_post_json(create_url, payload)
    if 200 <= status < 300 or status == 409:  # 409 = already exists
        print(f"  Collection '{COLLECTION_NAME}' ready (status={status})")
        return True
    print(f"  ERROR creating collection: {body}")
    return False


# ── Article Loading ──────────────────────────────────────────────────────────


def load_articles(source_dir: str = "") -> list[dict]:
    """Load all articles from JSON law files."""
    base = source_dir or LAW_JSON_DIR
    articles = []
    loaded_files = 0

    for jd in ["BR", "CL", "INT"]:
        json_dir = os.path.join(base, jd, "json")
        if not os.path.isdir(json_dir):
            # Try alternate structure (no json/ subdir)
            json_dir = os.path.join(base, jd)
        pattern = os.path.join(json_dir, "*.json")
        for fpath in sorted(glob.glob(pattern)):
            if ".gitkeep" in fpath:
                continue
            try:
                with open(fpath, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    articles.extend(data)
                    loaded_files += 1
                elif isinstance(data, dict):
                    # Single doc or wrapped
                    if "articles" in data:
                        articles.extend(data["articles"])
                    else:
                        articles.append(data)
                    loaded_files += 1
            except Exception as exc:
                print(f"  [warn] Cannot read {fpath}: {exc}")

    return articles


# ── Article → Qdrant Item ────────────────────────────────────────────────────


def build_qdrant_item(article: dict) -> dict:
    """Transform an article into a Qdrant ingest item."""
    # Canonical ID: jurisdiction_framework_article
    jd = article.get("jurisdiction", "XX")
    fw = article.get("framework_code", "UNKNOWN")
    art = article.get("article_number", "0")
    doc_id = f"{jd}_{fw}_Art{art}"

    # Structured embedding text
    parts = [
        f"Jurisdiction: {jd}",
        f"Framework: {article.get('framework_name', 'N/D')} ({fw})",
        f"Article: {art}",
        f"Theme: {article.get('theme', 'N/D')}",
        f"Reference: {article.get('reference', 'N/D')}",
    ]
    hierarchy = article.get("hierarchy") or {}
    if hierarchy.get("title"):
        parts.append(f"Title: {hierarchy['title']}")
    if hierarchy.get("chapter"):
        parts.append(f"Chapter: {hierarchy['chapter']}")
    if article.get("norm_type"):
        parts.append(f"Norm type: {article['norm_type']}")
    if article.get("norm_scope"):
        parts.append(f"Scope: {article['norm_scope']}")
    if article.get("regulated_subject"):
        parts.append(f"Subject: {article['regulated_subject']}")
    if article.get("duty_bearer_roles"):
        parts.append(f"Duty bearers: {', '.join(article['duty_bearer_roles'])}")
    if article.get("right_holder_roles"):
        parts.append(f"Right holders: {', '.join(article['right_holder_roles'])}")

    header = " | ".join(parts)
    text = f"{header}\n\nARTICLE TEXT:\n{article.get('text', '')}"

    metadata = {
        "jurisdiction": article.get("jurisdiction"),
        "framework_code": article.get("framework_code"),
        "framework_name": article.get("framework_name"),
        "article_number": article.get("article_number"),
        "hierarchy": article.get("hierarchy"),
        "reference": article.get("reference"),
        "theme": article.get("theme"),
        "eli_id": article.get("eli_id"),
        "hierarchy_label": article.get("hierarchy_label"),
        "norm_type": article.get("norm_type"),
        "norm_direction": article.get("norm_direction"),
        "norm_scope": article.get("norm_scope"),
        "duty_bearer_roles": article.get("duty_bearer_roles") or [],
        "right_holder_roles": article.get("right_holder_roles") or [],
        "regulated_subject": article.get("regulated_subject"),
        "sanctions": article.get("sanctions") or [],
    }

    return {
        "id": _doc_uuid(doc_id),
        "doc_id": doc_id,
        "text": text,
        "content": text,
        "metadata": metadata,
        # Also top-level for direct Qdrant filtering
        "jurisdiction": article.get("jurisdiction"),
        "framework_code": article.get("framework_code"),
        "article_number": article.get("article_number"),
        "norm_type": article.get("norm_type"),
        "norm_scope": article.get("norm_scope"),
        "regulated_subject": article.get("regulated_subject"),
        "source": "legal-framework",
    }


# ── Ingestion ────────────────────────────────────────────────────────────────


def ingest_articles(articles: list[dict], dry_run: bool = False, force: bool = False):
    """Push articles to Qdrant in batches."""
    total = len(articles)
    ingested = 0
    errors = []

    for i in range(0, total, BATCH_SIZE):
        batch = articles[i : i + BATCH_SIZE]
        items = [build_qdrant_item(a) for a in batch]

        if dry_run:
            print(f"  [dry-run] Would ingest {len(items)} articles "
                  f"(batch {i // BATCH_SIZE + 1}/{(total + BATCH_SIZE - 1) // BATCH_SIZE})")
            ingested += len(items)
            continue

        url = f"{QDRANT_API}/v1/qdrant/collections/structured_ingest"
        payload = {
            "collection_name": COLLECTION_NAME,
            "data_type": "law",
            "items": items,
            "force": force,
        }

        try:
            status, body = _http_post_json(url, payload, timeout=60.0)
            if 200 <= status < 300:
                ingested += len(items)
                print(f"  Batch {i // BATCH_SIZE + 1}: {len(items)} articles ingested (status={status})")
            else:
                err = body.get("detail") or json.dumps(body)[:300]
                errors.append(f"Batch {i // BATCH_SIZE + 1}: {err}")
                print(f"  Batch {i // BATCH_SIZE + 1}: FAILED — {err}")
        except Exception as exc:
            errors.append(f"Batch {i // BATCH_SIZE + 1}: {exc}")
            print(f"  Batch {i // BATCH_SIZE + 1}: EXCEPTION — {exc}")

    return ingested, errors


# ── Report ───────────────────────────────────────────────────────────────────


def generate_report(articles: list[dict], ingested: int, source_dir: str = ""):
    """Generate a summary JSON for the ingestion."""
    by_jurisdiction = {}
    by_framework = {}
    by_norm_type = {}
    by_scope = {}

    for a in articles:
        jd = a.get("jurisdiction", "XX")
        fw = a.get("framework_code", "UNKNOWN")
        nt = a.get("norm_type", "unknown")
        sc = a.get("norm_scope", "unknown")

        by_jurisdiction[jd] = by_jurisdiction.get(jd, 0) + 1
        by_framework[fw] = by_framework.get(fw, 0) + 1
        by_norm_type[nt] = by_norm_type.get(nt, 0) + 1
        by_scope[sc] = by_scope.get(sc, 0) + 1

    return {
        "generated_at": now_iso(),
        "collection": COLLECTION_NAME,
        "total_articles": len(articles),
        "ingested": ingested,
        "by_jurisdiction": dict(sorted(by_jurisdiction.items(), key=lambda x: -x[1])),
        "by_framework": dict(sorted(by_framework.items(), key=lambda x: -x[1])),
        "by_norm_type": dict(sorted(by_norm_type.items(), key=lambda x: -x[1])),
        "by_scope": dict(sorted(by_scope.items(), key=lambda x: -x[1])),
        "source_dir": source_dir or LAW_JSON_DIR,
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Ingest legal framework articles into Qdrant")
    parser.add_argument("--source-dir", type=str, default="",
                        help="Path to law_json source directory (overrides $LEGAL_FRAMEWORK_SOURCE_DIR)")
    parser.add_argument("--dry-run", action="store_true", help="Validate without pushing to Qdrant")
    parser.add_argument("--force", action="store_true", help="Force re-ingestion of all articles")
    parser.add_argument("--output", type=str, default=None, help="Output report JSON path")
    args = parser.parse_args()

    source_dir = args.source_dir or LAW_JSON_DIR

    print("=" * 60)
    print("Legal Framework Ingestion")
    print(f"  Started: {datetime.now().isoformat()}")
    print(f"  Source:  {source_dir}")
    print(f"  Target:  {QDRANT_API} → {COLLECTION_NAME}")
    print(f"  Mode:    {'dry-run' if args.dry_run else 'live'}")
    print("=" * 60)

    # 1. Load articles
    print("\n[1/4] Loading articles...")
    articles = load_articles(source_dir)
    print(f"  Loaded {len(articles)} articles from {len(set(a.get('framework_code') for a in articles))} frameworks")

    if not articles:
        print("  ERROR: No articles found")
        sys.exit(1)

    # 2. Ensure collection
    print(f"\n[2/4] Ensuring collection '{COLLECTION_NAME}'...")
    if not args.dry_run:
        if not ensure_collection():
            print("  FATAL: Cannot create/verify collection")
            sys.exit(1)
    else:
        print("  [dry-run] Skipping collection creation")

    # 3. Ingest
    print(f"\n[3/4] Ingesting {len(articles)} articles...")
    ingested, errors = ingest_articles(articles, dry_run=args.dry_run, force=args.force)

    # 4. Report
    print(f"\n[4/4] Generating report...")
    report = generate_report(articles, ingested, source_dir)

    report_path = args.output or os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "law_ingestion_report.json",
    )
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 60}")
    print(f"Ingestion {'[dry-run]' if args.dry_run else ''} complete.")
    print(f"  Articles total:    {len(articles)}")
    print(f"  Ingested:          {ingested}")
    print(f"  Errors:            {len(errors)}")
    print(f"  Report:            {report_path}")
    print(f"\nBy jurisdiction:")
    for jd, n in report["by_jurisdiction"].items():
        print(f"  {jd:5s}: {n:4d} articles")
    print(f"\nBy norm type:")
    for nt, n in sorted(report["by_norm_type"].items(), key=lambda x: -x[1])[:8]:
        print(f"  {nt:20s}: {n:4d}")
    print(f"{'=' * 60}")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
