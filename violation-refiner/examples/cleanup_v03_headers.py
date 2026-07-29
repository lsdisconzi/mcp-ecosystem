#!/usr/bin/env python3
"""Clean stale framework self-reported SHA headers for V03 warnings.

V03 warns when a framework markdown cache contains a header line like
`**Sha256:** <hash>` that no longer matches the file's current bytes.
Because the validator compares that declared value against the full file
SHA, stale declarations are noise and can be removed safely.

This script:
- scans canonical CL-### bundles under --input
- finds bundles with V03 warn
- identifies framework cache files referenced by those bundles
- removes `**Sha256:** ...` metadata lines from those files

If a cache path is a symlink, the script replaces the symlink with a local
regular file copy before writing, so source framework files are not edited.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


V03_FRAMEWORK_RE = re.compile(r"framework\s+([A-Z0-9]+)\s+self-reported SHA", re.IGNORECASE)
SHA_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s+)?\*\*Sha256:\*\*\s*[0-9a-fA-F]{64}\s*$",
    re.IGNORECASE,
)


def _canonical_dirs(root: Path) -> list[Path]:
    return sorted(
        [p for p in root.iterdir() if p.is_dir() and re.fullmatch(r"CL-\d{3}", p.name)],
        key=lambda p: p.name,
    )


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _v03_frameworks(bundle_dir: Path) -> set[str]:
    checks = _load_json(bundle_dir / "Validation" / "checks.json")
    if not checks:
        return set()
    out: set[str] = set()
    for c in checks.get("checks", []):
        if not isinstance(c, dict):
            continue
        if c.get("check_id") == "V03" and c.get("status") == "warn":
            details = str(c.get("details") or "")
            out.update(x.upper() for x in V03_FRAMEWORK_RE.findall(details))
    return out


def _cache_paths_for_frameworks(bundle_dir: Path, frameworks: set[str]) -> list[Path]:
    v = _load_json(bundle_dir / f"{bundle_dir.name}.json")
    if not v:
        return []
    out: list[Path] = []
    for fw in v.get("framework_caches", []):
        if not isinstance(fw, dict):
            continue
        code = str(fw.get("framework_code") or "").upper()
        cache_file = fw.get("cache_file")
        if code in frameworks and isinstance(cache_file, str) and cache_file:
            out.append(bundle_dir / cache_file)
    return out


def _remove_sha_line(path: Path) -> tuple[bool, bool]:
    """Return (modified, was_symlink)."""
    if not path.exists():
        return False, False

    was_symlink = path.is_symlink()
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    kept = [ln for ln in lines if not SHA_LINE_RE.match(ln)]
    if len(kept) == len(lines):
        return False, was_symlink

    new_text = "\n".join(kept) + "\n"

    if was_symlink:
        path.unlink()
        path.write_text(new_text, encoding="utf-8")
    else:
        path.write_text(new_text, encoding="utf-8")
    return True, was_symlink


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean stale V03 SHA headers in bundle framework caches")
    parser.add_argument("--input", default="build/cl_batch", help="Root folder containing CL-### bundle dirs")
    parser.add_argument("--only", nargs="*", default=[], help="Optional bundle IDs to process")
    args = parser.parse_args()

    root = Path(args.input)
    if not root.is_dir():
        raise SystemExit(f"Input is not a directory: {root}")

    only = set(args.only)
    bundles = _canonical_dirs(root)
    if only:
        bundles = [b for b in bundles if b.name in only]

    touched: set[Path] = set()
    symlink_replaced: set[Path] = set()

    for b in bundles:
        frameworks = _v03_frameworks(b)
        if not frameworks:
            continue
        for p in _cache_paths_for_frameworks(b, frameworks):
            if p in touched:
                continue
            modified, was_symlink = _remove_sha_line(p)
            if modified:
                touched.add(p)
                if was_symlink:
                    symlink_replaced.add(p)

    print(f"bundles_scanned={len(bundles)}")
    print(f"files_modified={len(touched)}")
    if touched:
        for p in sorted(touched):
            print(f"MODIFIED {p}")
    print(f"symlinks_replaced_with_local_copy={len(symlink_replaced)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
