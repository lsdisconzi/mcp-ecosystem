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
    #: Official sources ingested while verifying an authority (the uploaded
    #: PDF, a copy of the fetched page, and the `.proof.json` sidecar that
    #: records both hashes). Listed here rather than hardcoded in
    #: `authority_source.py` so MANIFEST.txt and the bundle zip pick it up like
    #: every other artefact.
    "authority_sources_dir":     "Authority sources",
}


#: The layout keys that name a **folder a source is copied into**. Every other
#: key names one file, so a source staged there replaces that file rather than
#: being dropped beside it: ``contract`` means ``contract.json``, and the older
#: behaviour created a *directory* of that name and copied into it.
#:
#: Declared rather than inferred from the template's shape. "Has no suffix" fits
#: today's layout, but it would silently misplace a future folder whose name
#: carries a dot — so `tests/test_pack_layout.py` pins this set against the
#: suffix-free keys and a new bare folder key either lands here or fails loudly.
SOURCE_DIRECTORY_KINDS = frozenset({
    "transcripts_dir",
    "framework_dir",
    "authority_sources_dir",
})


def is_layout_kind(kind: object) -> bool:
    """True when ``kind`` names a destination in `BUNDLE_LAYOUT`."""
    return isinstance(kind, str) and kind in BUNDLE_LAYOUT


def bundle_path(root: Path, kind: str, violation_id: str) -> Path:
    rel = BUNDLE_LAYOUT[kind].format(violation_id=violation_id)
    return root / rel


def staged_source_path(root: Path, kind: str, source_name: str) -> Path:
    """Where a staged source of truth lands inside the bundle.

    Two shapes, because `BUNDLE_LAYOUT` holds two:

    * a folder key (``transcripts_dir`` → ``Transcripts``) — the source keeps its
      own name inside it;
    * a file key (``contract`` → ``contract.json``) — the destination *is* the
      file, so the source replaces it.

    The bundle id is read off ``root``'s name (``build/CL-030`` → ``CL-030``),
    the same convention ``resolve_bundle_dir`` and the UI's bundle root use — the
    directory name *is* the violation id, so the ``{violation_id}`` templates
    resolve without a second argument.

    ``source_name`` is reduced to its basename, stripped, and an empty or dot
    name is refused: a staged source must not be able to write outside the bundle,
    whatever a request body or a drag-and-drop says. The strip is not cosmetic —
    ``"   "`` is a legal POSIX file name, so without it a request could stage a
    file that no listing, manifest or bug report can distinguish from the
    directory around it.
    """
    if not is_layout_kind(kind):
        raise KeyError(kind)
    name = Path(source_name or "").name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("a staged source needs a file name")
    template = BUNDLE_LAYOUT[kind]
    if kind in SOURCE_DIRECTORY_KINDS:
        return root / template / name
    return root / Path(template.format(violation_id=root.name))


def write_violation_json(violation: Violation, root: Path) -> Path:
    """Serialize the canonical violation JSON to <root>/<violation_id>.json."""
    out = bundle_path(root, "violation_main", violation.violation_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(violation.model_dump_json(indent=2, exclude_none=False), encoding="utf-8")
    return out


def build_manifest(root: Path, schema_version: str = "3.0") -> Path:
    """Produce MANIFEST.txt with every file's size + sha256.

    The hashes describe **one generation** of the bundle, not its identity. A
    re-run rewrites ``Generated`` and therefore every hash, and ``<id>.json`` is
    not byte-stable across runs: ``confidence.derived_at`` is refreshed and
    ``confidence.attach_confidence`` appends the previous value to
    ``confidence.history`` on every pass. So compare a manifest against a fresh
    manifest of the same tree, never against a hash recorded from an earlier run
    — the bundle sha is a snapshot, not a stable artifact id.
    """
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
        "note: `bytes` is the UTF-8 *byte* length (len(p.read_bytes())), not a character count.",
        "      The two differ for any non-ASCII text:",
        "      'Authority sources/CL.CPR.Art.19.N3__DTO-100_03-MAY-2023.text.txt' is 28326 bytes and",
        "      27763 characters, and its sidecar's text_chars field records the 27763. Verify a file",
        "      against `bytes`; compare a character count against `text_chars`.",
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


def clear_linked_destination(dest: Path) -> None:
    """Remove a **symlink** at ``dest`` so the write creates a real file there.

    Both writers open ``dest`` for writing, and both therefore *follow* a link:
    ``shutil.copy2`` and ``Path.write_bytes`` resolve the destination before
    truncating it. A bundle whose layout is a set of links to the canonical
    corpus — ``build/CL-030/Legal framework/CPCL.md -> ../../../data/law/CL/
    CodigoPenal.md``, which is the real convention — makes that a write **outside
    the workspace**: staging a source named ``CPCL.md`` rewrites
    ``data/law/CL/CodigoPenal.md``, and the caller is told it wrote
    ``Legal framework/CPCL.md`` with a sha256 of the corpus file.

    Only a link is cleared. A real file at the destination is the ordinary
    replace case (reported as ``overwritten``), and a directory is left alone so
    the writer raises rather than silently discarding a tree.
    """
    if dest.is_symlink():
        dest.unlink()


def copy_source_into_bundle(source_path: Path, root: Path, kind: str) -> Path:
    """Copy a source-of-truth file into the bundle's canonical location."""
    dest = staged_source_path(root, kind, source_path.name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    clear_linked_destination(dest)
    shutil.copy2(source_path, dest)
    return dest


def write_source_into_bundle(root: Path, kind: str, source_name: str, data: bytes) -> Path:
    """Write an uploaded source into the bundle's canonical location.

    The upload counterpart of `copy_source_into_bundle`, and deliberately the
    same destination rule: a reviewer who drags a PDF in and one who picks the
    same file out of ``data/law`` must not end up with two different layouts.
    """
    dest = staged_source_path(root, kind, source_name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    clear_linked_destination(dest)
    dest.write_bytes(data)
    return dest
