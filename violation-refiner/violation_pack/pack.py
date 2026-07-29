"""Bundle layout helpers.

Defines the canonical on-disk shape of a violation pack and produces the
MANIFEST. The layout matches the project's existing convention so refined
packs are drop-in replacements for unrefined ones.
"""
from __future__ import annotations

import hashlib
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .models import Violation


BUNDLE_LAYOUT = {
    # path inside <violation_id>/ : what kind of file goes there
    "violation_main":            "{violation_id}.json",
    "contract":                  "contract.json",
    "manifest":                  "MANIFEST.txt",
    "readme":                    "Violation bundle/README.md",
    "validation_report":         "Validation/validation_report.md",
    "validation_checks":         "Validation/checks.json",
    "element_grid":              "Schema/element_grid_{violation_id}.json",
    "transcripts_dir":           "Transcripts",
    "framework_dir":             "Legal framework",
}


def bundle_path(root: Path, kind: str, violation_id: str) -> Path:
    rel = BUNDLE_LAYOUT[kind].format(violation_id=violation_id)
    return root / rel


def write_violation_json(violation: Violation, root: Path) -> Path:
    """Serialize the canonical violation JSON to <root>/<violation_id>.json."""
    out = bundle_path(root, "violation_main", violation.violation_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(violation.model_dump_json(indent=2, exclude_none=False), encoding="utf-8")
    return out


def build_manifest(root: Path, schema_version: str = "3.0") -> Path:
    """Produce MANIFEST.txt with every file's size + sha256."""
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "MANIFEST.txt":
            data = p.read_bytes()
            files.append((p.relative_to(root.parent), len(data), hashlib.sha256(data).hexdigest()))

    lines = [
        f"Violation pack: {root.name}",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Schema version: {schema_version}",
        f"Files included: {len(files)}",
        "",
        "format: relative_path | bytes | sha256",
        "─" * 100,
    ]
    for rel, size, sha in files:
        lines.append(str(rel))
        lines.append(f"    bytes:  {size}")
        lines.append(f"    sha256: {sha}")
        lines.append("")
    out_text = "\n".join(lines).rstrip() + "\n"

    manifest_path = root / "MANIFEST.txt"
    manifest_path.write_text(out_text, encoding="utf-8")
    return manifest_path


def zip_bundle(root: Path, out_zip: Path) -> Path:
    """Zip the whole bundle directory."""
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    if out_zip.exists():
        out_zip.unlink()
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(root.rglob("*")):
            zf.write(p, arcname=p.relative_to(root.parent))
    return out_zip


def copy_source_into_bundle(source_path: Path, root: Path, kind: str) -> Path:
    """Copy a source-of-truth file into the bundle's canonical location."""
    dest_dir_rel = BUNDLE_LAYOUT[kind]
    dest_dir = root / dest_dir_rel
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / source_path.name
    shutil.copy2(source_path, dest)
    return dest
