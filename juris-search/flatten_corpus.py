#!/usr/bin/env python3
"""
Flatten deeply nested jurisprudence directories into a clean corpus_flat/ structure.

Walks:
  - docx_jurisprudence/   (~50 .docx files, 6+ levels deep)
  - json_jurisprudence/   (~955 .json files, same nesting)
  - jurisprudence_downloads/ (PDF + .metadata.json sidecars)
  - jurisprudence_STF/    (PDFs + markdown, flat but messy names)
  - jurisprudence_CL/     (PDFs + markdown)

Deduplicates by content hash (SHA-256). Symlinks unique files to:
  corpus_flat/{tribunal}/{canonical_filename}

Outputs flatten_report.json with original→flattened path mappings.
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CORPUS_FLAT = BASE_DIR / "corpus_flat"

SOURCE_DIRS = {
    "docx": BASE_DIR / "docx_jurisprudence",
    "json": BASE_DIR / "json_jurisprudence",
    "downloads": BASE_DIR / "jurisprudence_downloads",
    "stf": BASE_DIR / "jurisprudence_STF",
    "cl": BASE_DIR / "jurisprudence_CL",
}

# ── Tribunal detection from filename ────────────────────────────────────────

# 5-field TJRS: inteiro_teor_70084126507_2020_649456
TJRS_FNAME_RE = re.compile(
    r"inteiro_teor_(?P<numero>\d+)_(?P<ano>\d{4})_(?P<codigo>\d+)",
    re.IGNORECASE,
)
# 3-field TJSP: inteiro_teor_19436885
TJSP_FNAME_RE = re.compile(
    r"inteiro_teor_(?P<cdacordao>\d{6,})",
    re.IGNORECASE,
)


def detect_tribunal(filepath: Path) -> str:
    """Detect tribunal from filename or parent directory context."""
    fname = filepath.name

    # Check parent context first
    path_str = str(filepath).lower()
    if "stf" in path_str and "jurisprudence_stf" in path_str:
        return "STF"
    if "cl" in path_str and "jurisprudence_cl" in path_str:
        return "CL"

    # Filename pattern matching
    tjrs_match = TJRS_FNAME_RE.search(fname)
    if tjrs_match:
        return "TJRS"

    tjsp_match = TJSP_FNAME_RE.search(fname)
    if tjsp_match:
        return "TJSP"

    # "downloadPeca" in STF dir
    if "downloadpeca" in fname.lower() or "paginador" in fname.lower():
        return "STF"

    # Fallback: try to infer from directory
    if "jurisprudence_stf" in path_str:
        return "STF"
    if "jurisprudence_cl" in path_str:
        return "CL"
    if "turma" in path_str.lower():
        return "Turmas Recursais"

    return "UNKNOWN"


def compute_sha256(filepath: Path) -> str:
    """Compute SHA-256 hash of file contents."""
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def collect_files(source_dir: Path) -> list[Path]:
    """Walk a directory and collect all non-hidden files of relevant types."""
    if not source_dir.exists():
        print(f"  [skip] {source_dir} does not exist")
        return []

    relevant_exts = {".docx", ".doc", ".pdf", ".json", ".md"}
    files = []
    for root, dirs, filenames in os.walk(source_dir):
        # Skip hidden dirs and node_modules
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
        for fname in filenames:
            if fname.startswith("."):
                continue
            fpath = Path(root) / fname
            ext = fpath.suffix.lower()
            if ext in relevant_exts:
                files.append(fpath)
    return files


def deduplicate(files: list[Path]) -> dict[str, list[Path]]:
    """
    Group files by content hash.
    Returns {sha256_hash: [list_of_paths]}
    """
    by_hash: dict[str, list[Path]] = {}
    for fpath in files:
        try:
            h = compute_sha256(fpath)
        except (OSError, PermissionError) as e:
            print(f"  [warn] Cannot hash {fpath}: {e}")
            continue
        by_hash.setdefault(h, []).append(fpath)
    return by_hash


def canonical_name(fpath: Path, tribunal: str) -> str:
    """Generate a canonical filename from the original path."""
    fname = fpath.name

    # For metadata sidecars, keep the original name paired with its document
    # e.g., inteiro_teor_19436885.pdf.metadata.json → same base dir
    if fname.endswith(".metadata.json"):
        return fname

    # For STF's generic numbered PDFs, try to extract a better name
    if tribunal == "STF":
        # Keep original for now; manual renaming via metadata would be better
        return fname

    return fname


def main():
    print("=" * 60)
    print("Flattening jurisprudence corpus")
    print(f"  Started: {datetime.now().isoformat()}")
    print(f"  Target:  {CORPUS_FLAT}")
    print("=" * 60)

    CORPUS_FLAT.mkdir(parents=True, exist_ok=True)

    all_files: list[Path] = []
    source_stats: dict[str, int] = {}

    # ── Phase 1: Collect all files ─────────────────────────────────────────
    print("\n[1/4] Collecting files from source directories...")
    for label, sdir in SOURCE_DIRS.items():
        files = collect_files(sdir)
        source_stats[label] = len(files)
        all_files.extend(files)
        print(f"  {label:12s}: {len(files):5d} files from {sdir}")

    total_collected = len(all_files)
    print(f"  {'TOTAL':12s}: {total_collected:5d} files")

    # ── Phase 2: Deduplicate by content hash ───────────────────────────────
    print(f"\n[2/4] Computing content hashes and deduplicating...")
    by_hash = deduplicate(all_files)
    unique_hashes = len(by_hash)
    duplicates = total_collected - unique_hashes
    print(f"  Unique hashes:  {unique_hashes}")
    print(f"  Duplicates:     {duplicates} ({duplicates/total_collected*100:.1f}%)")

    # ── Phase 3: Create flattened structure ────────────────────────────────
    print(f"\n[3/4] Creating flattened corpus...")
    report_entries: list[dict] = []
    tribunal_counts: dict[str, int] = {}

    for sha_hash, paths in sorted(by_hash.items()):
        # Use the shortest path as canonical original
        original = min(paths, key=lambda p: len(str(p)))
        tribunal = detect_tribunal(original)
        cname = canonical_name(original, tribunal)

        # Create target: corpus_flat/{tribunal}/{filename}
        target_dir = CORPUS_FLAT / tribunal.lower().replace(" ", "_")
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / cname

        # Handle name collisions (different content, same derived name)
        if target.exists():
            # Check if existing file is same content (hash match)
            existing_hash = compute_sha256(target)
            if existing_hash == sha_hash:
                report_entries.append({
                    "sha256": sha_hash,
                    "original": str(original),
                    "flattened": str(target),
                    "tribunal": tribunal,
                    "status": "already_present",
                    "duplicate_paths": [str(p) for p in paths if p != original],
                })
                tribunal_counts[tribunal] = tribunal_counts.get(tribunal, 0) + 1
                continue
            else:
                # Different content, same name — add hash prefix
                stem = target.stem
                suffix = target.suffix
                target = target_dir / f"{stem}_{sha_hash[:8]}{suffix}"

        # Create symlink
        try:
            if target.exists() or target.is_symlink():
                target.unlink()
            os.symlink(original, target)
        except OSError as e:
            print(f"  [warn] Cannot symlink {original} → {target}: {e}")
            continue

        report_entries.append({
            "sha256": sha_hash,
            "original": str(original),
            "flattened": str(target),
            "tribunal": tribunal,
            "status": "symlinked",
            "duplicate_paths": [str(p) for p in paths if p != original],
        })
        tribunal_counts[tribunal] = tribunal_counts.get(tribunal, 0) + 1

    # ── Phase 4: Report ─────────────────────────────────────────────────────
    print(f"\n[4/4] Writing report...")
    report = {
        "generated_at": datetime.now().isoformat(),
        "source_stats": source_stats,
        "total_collected": total_collected,
        "unique_by_hash": unique_hashes,
        "duplicates_removed": duplicates,
        "flattened_count": len(report_entries),
        "by_tribunal": tribunal_counts,
        "corpus_flat_path": str(CORPUS_FLAT),
        "entries": report_entries,
    }

    report_path = BASE_DIR / "flatten_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"Flatten complete.")
    print(f"  Report: {report_path}")
    print(f"  Corpus: {CORPUS_FLAT}")
    print(f"\nBy tribunal:")
    for trib, count in sorted(tribunal_counts.items(), key=lambda x: -x[1]):
        print(f"  {trib:20s}: {count:5d} documents")
    print(f"  {'TOTAL':20s}: {len(report_entries):5d} documents")
    print(f"{'='*60}")

    return report


if __name__ == "__main__":
    main()
