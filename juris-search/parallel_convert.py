#!/usr/bin/env python3
"""Parallel .doc → .docx converter using multiprocessing.

Scans jurisprudence_downloads/ for .doc files, converts them in parallel
using N LibreOffice workers, and mirrors the output to docx_jurisprudence/.
"""

import json
import os
import subprocess
import sys
import time
from multiprocessing import Pool, Manager, cpu_count
from pathlib import Path

SRC_DIR = Path("/home/disconzi1986_gmail_com/juris-search-VPS/jurisprudence_downloads")
DST_DIR = Path("/home/disconzi1986_gmail_com/juris-search-VPS/docx_jurisprudence")
STATE_PATH = DST_DIR / ".watch_state.json"
INDEX_PATH = DST_DIR / "index.json"
LIBREOFFICE = "/usr/bin/libreoffice"

# How many parallel LibreOffice instances to run
WORKERS = max(2, cpu_count())


def discover_docs():
    """Find all .doc files in SRC_DIR that have no corresponding .docx in DST_DIR."""
    pending = []
    for doc_path in sorted(SRC_DIR.rglob("*.doc")):
        rel = doc_path.relative_to(SRC_DIR)
        docx_path = DST_DIR / rel.with_suffix(".docx")
        if not docx_path.exists():
            pending.append((str(doc_path), str(docx_path)))
    return pending


def convert_one(args):
    """Convert a single .doc to .docx in an isolated temp directory."""
    doc_path, docx_path = args
    docx = Path(docx_path)
    docx.parent.mkdir(parents=True, exist_ok=True)

    import tempfile, shutil
    with tempfile.TemporaryDirectory(prefix="juris_docx_") as tmpdir:
        tmp_doc = Path(tmpdir) / Path(doc_path).name
        shutil.copy2(doc_path, tmp_doc)

        # Convert into the temp dir to avoid races with other workers
        tmp_outdir = Path(tmpdir) / "out"
        tmp_outdir.mkdir()
        cmd = [
            LIBREOFFICE,
            "--headless",
            "--convert-to", "docx",
            "--outdir", str(tmp_outdir),
            str(tmp_doc),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return (doc_path, False, "timeout (120s)")
        except Exception as e:
            return (doc_path, False, str(e))

        # Find the generated .docx in the temp output dir
        converted = list(tmp_outdir.glob("*.docx"))
        if converted:
            shutil.move(str(converted[0]), str(docx))
            return (doc_path, True, None)
        else:
            error = result.stderr.strip() or result.stdout.strip() or "unknown error"
            return (doc_path, False, f"rc={result.returncode}: {error[:120]}")


def update_watch_state(successful, failed_list):
    """Update .watch_state.json with conversion results."""
    state = {"processed": {}, "failed": {}, "updated_at": None}
    if STATE_PATH.exists():
        try:
            with open(STATE_PATH) as f:
                state = json.load(f)
        except Exception:
            pass

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    for src_path in successful:
        rel = str(Path(src_path).relative_to(SRC_DIR))
        state.setdefault("processed", {})[rel] = {
            "converted_at": now,
            "status": "ready",
        }
        state["failed"].pop(rel, None)

    for src_path, error in failed_list:
        rel = str(Path(src_path).relative_to(SRC_DIR))
        state.setdefault("failed", {})[rel] = {
            "error": error,
            "last_attempt": now,
        }

    state["updated_at"] = now
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def main():
    print(f"Scanning {SRC_DIR} for .doc files...")
    pending = discover_docs()
    total = len(pending)

    if total == 0:
        print("No .doc files need conversion.")
        return

    print(f"Found {total} .doc files to convert.")
    print(f"Using {WORKERS} parallel workers.\n")

    start = time.time()
    successful = []
    failed = []
    completed = 0

    with Pool(processes=WORKERS) as pool:
        for src_path, ok, error in pool.imap_unordered(convert_one, pending):
            completed += 1
            rel = str(Path(src_path).relative_to(SRC_DIR))
            if ok:
                successful.append(src_path)
                print(f"[{completed}/{total}] OK  {rel}")
            else:
                failed.append((src_path, error))
                print(f"[{completed}/{total}] FAIL {rel}: {error}")

    elapsed = time.time() - start
    update_watch_state(successful, failed)

    print(f"\n{'='*50}")
    print(f"Done in {elapsed:.1f}s ({total/elapsed:.1f} files/sec)")
    print(f"  Converted: {len(successful)}")
    print(f"  Failed:    {len(failed)}")
    print(f"  Total:     {total}")


if __name__ == "__main__":
    main()
