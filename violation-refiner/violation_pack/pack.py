"""Bundle layout helpers.

Defines the canonical on-disk shape of a violation pack and produces the
MANIFEST. The layout matches the project's existing convention so refined
packs are drop-in replacements for unrefined ones.
"""
from __future__ import annotations

import hashlib
import json
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


#: Contract keys `project_contract` derives from the violation, overwriting
#: whatever the contract held.
#:
#: Declared as a set so the split is testable. A key in neither this set nor
#: `CONTRACT_VAULT_ONLY_KEYS` is a field nobody has classified, and
#: ``tests/test_contract_projection.py`` fails on it rather than letting a field
#: a newer converter emitted sit quietly unprojected forever.
CONTRACT_PROJECTED_KEYS = frozenset({
    "violation_id",
    "violation_number",
    "title",
    "severity",
    "framework",
    "confidence",
    "incident",
    "legal_basis",
    "candidate_articles",
    "cross_references",
    "open_questions",
    "established_article_ids",
})

#: Contract keys the violation has no counterpart for — the vault's own record.
#: `project_contract` leaves them exactly as found.
#:
#: ``schema_version`` is here because the two sides version *different* documents:
#: every bundle in this repo has ``violation.schema_version == "3.0"`` (the bundle
#: schema) against ``contract.schema_version == "4.0"`` (the vault document's own,
#: which `vault_to_bundle` copies through). They are not meant to agree, so
#: projecting one over the other would replace a vault fact with an unrelated
#: number.
#:
#: ``_vault_confidence`` belongs here even though it sits beside ``confidence``:
#: `examples/vault_to_bundle.py` parks the *pre-conversion* confidence snapshot
#: in it when the bundle's own data contradicts that snapshot, so it records what
#: the vault said. ``confidence`` itself is the derived value the bundle stands
#: behind, and that one is projected.
CONTRACT_VAULT_ONLY_KEYS = frozenset({
    "schema_version",
    "case",
    "jurisdiction",
    "category",
    "allegation_summary",
    "incident_timestamp",
    "incident_timestamp_display",
    "related_violations",
    "tags",
    "_provenance",
    "_vault_confidence",
})


def _contract_framework_meta(contract: dict) -> tuple[dict[str, str | None], dict[str, str]]:
    """Read back the framework files/names the contract already carries.

    `project_contract` rebuilds ``legal_basis`` from the violation, and
    ``CachedArticle.framework_code`` is the *short* code the bundle groups by.
    What the violation does **not** carry is the corpus-relative file the
    contract records: a ``FrameworkCache.cache_file`` is bundle-relative
    (``Legal framework/CPCL.md``), a different namespace from the contract's
    ``CL/CodigoPenal.md``. So the file mapping is read off the contract being
    projected rather than invented from a path that would not resolve.
    """
    files: dict[str, str | None] = {}
    names: dict[str, str] = {}
    legal_basis = contract.get("legal_basis")
    frameworks = legal_basis.get("frameworks") if isinstance(legal_basis, dict) else None
    for fw in frameworks if isinstance(frameworks, list) else []:
        if not isinstance(fw, dict):
            continue
        code = fw.get("framework_code")
        if not isinstance(code, str) or not code:
            continue
        files.setdefault(code, fw.get("framework_file"))
        name = fw.get("framework_name")
        if isinstance(name, str) and name:
            names.setdefault(code, name)
    return files, names


def project_contract(contract: dict, violation: Violation) -> dict:
    """Overwrite every ``contract`` field the violation determines, in place.

    The contract is a *view* of the violation, for consumers that read one flat
    document; the violation is the record every other artifact in the bundle is
    derived from. Reconciling only the four fields V08/V17 compare (confidence,
    established ids, cross references, open questions) left the view asserting
    things the bundle contradicts: ``legal_basis`` was frozen at conversion time,
    so an article the violation holds as a *candidate* was still published as
    ``status: "established"`` with an empty ``article_text``, and a title edited
    in the UI never reached the contract at all. V08 only compares
    ``established_article_ids``, so nothing caught the contradiction between the
    two lists living in the same file.

    Two groups of keys, and the split is the design:

    * `CONTRACT_PROJECTED_KEYS` — derived from the violation, overwritten here.
    * `CONTRACT_VAULT_ONLY_KEYS` — the vault's own record (case file,
      jurisdiction, allegation summary, provenance, the pre-conversion
      confidence snapshot). The violation has no counterpart, so these are left
      exactly as found.

    A key in neither set is left alone as well: a contract written by a newer
    converter must not lose a field this module has never heard of.

    ``article_text`` comes from ``CachedArticle.verbatim_excerpt`` — the cache
    text the bundle actually carries and V03 hashes — not from the vault's
    conversion-time paraphrase.

    Returns ``contract`` so a caller can thread it back through the dict it read;
    the mutation is in place so a caller holding the pre-enrichment dict (the
    batch pipeline passes it straight to ``run_pipeline``) sees the projection.
    """
    contract["violation_id"] = violation.violation_id
    contract["violation_number"] = violation.violation_id
    contract["title"] = violation.title
    contract["severity"] = violation.severity
    contract["incident"] = json.loads(violation.incident.model_dump_json())

    if violation.confidence is None:
        # Absent, not null: the contract's own shape leaves the key out when
        # there is nothing derived to record, and V08 reads a missing key and a
        # null key the same way.
        contract.pop("confidence", None)
    else:
        contract["confidence"] = json.loads(violation.confidence.model_dump_json())

    # legal_basis is rebuilt rather than patched, so an article that stopped
    # being established disappears from the operative list instead of surviving
    # as a stale "established" row with no text behind it.
    files, names = _contract_framework_meta(contract)
    for cache in violation.framework_caches:
        if cache.framework_name:
            names.setdefault(cache.framework_code, cache.framework_name)

    groups: dict[str, list[dict]] = {}
    for article in violation.established_articles:
        groups.setdefault(article.framework_code, []).append({
            "article_id": article.article_id,
            "article_name": article.article_name,
            "article_text": article.verbatim_excerpt,
            "applicability_rationale": article.applicability_rationale,
            "duty_bearer": article.duty_bearer,
            "norm_type": article.norm_type,
            "applicability": article.applicability,
            "subsections_invoked": list(article.subsections_invoked),
            "status": "established",
        })

    codes = sorted(groups)
    contract["legal_basis"] = {
        "frameworks": [
            {
                "framework_code": code,
                "framework_name": names.get(code) or code,
                "framework_file": files.get(code),
                "articles": groups[code],
            }
            for code in codes
        ]
    }
    # Kept consistent with the rebuilt legal_basis, the same way the converter
    # derives both from one dict: `codes` is the set the operative articles
    # cite, and `files` maps each of those to its corpus file.
    #
    # A code the contract never carried gets ``None`` rather than the violation's
    # ``FrameworkCache.cache_file``: the two are different namespaces
    # ("CL/CodigoPenal.md" against "Legal framework/CPCL.md") and
    # ``examples/vault_to_bundle.py`` joins ``framework_file`` back onto the law
    # corpus root, so a bundle-relative path here would read as "no law file in
    # the corpus" and demote that framework's articles to candidates.
    contract["framework"] = {
        "codes": codes,
        "files": {code: files.get(code) for code in codes},
    }

    contract["candidate_articles"] = [
        json.loads(c.model_dump_json()) for c in violation.candidate_articles
    ]
    contract["cross_references"] = [
        {"ref": x.ref, "relation": x.relation} for x in violation.cross_references
    ]
    # Four keys, not the model's five: the contract has never carried
    # `obtaining_method`, and V17 compares only the fields both sides declare.
    contract["open_questions"] = [
        {
            "id": q.id,
            "question": q.question,
            "blocks_element": q.blocks_element or "",
            "priority": q.priority,
        }
        for q in violation.open_questions
    ]
    # A set, not a list: this field is an *index* of which articles are
    # established, and V08 reads it as one (``set(contract[...])`` against
    # ``{a.article_id for a in v.established_articles}``). Several bundles
    # establish one article once per applicable inciso — BR-004 carries four
    # distinct rows for ``BR.CDC.T3.Art.6``, each with its own rationale — so a
    # list would repeat the id where the rows do not. The rows below keep every
    # one of those rationale; this collapses to the ids.
    contract["established_article_ids"] = sorted(
        {a.article_id for a in violation.established_articles}
    )
    return contract


def reconcile_contract(root: Path, violation: Violation) -> dict:
    """Rewrite ``<root>/contract.json`` as the projection of ``violation``.

    Returns ``{"contract_path": str | None, "contract_changed": bool}`` — the
    shape ``segment_sync.sync_segment_artifacts`` reports, so a writer folds both
    summaries into one result and the UI can say what it touched.

    A missing contract is left missing (``contract_path: None``): the contract is
    written by the vault converter, and inventing one here would publish a view
    for a bundle that never had one. An unreadable one is the same case —
    reported, not raised, because this runs inside the write gate and an optional
    artifact that cannot be parsed must not fail a write that already landed.

    Idempotent: the file is rewritten only when the projection differs, so a
    second write of the same violation leaves the bundle byte-identical.
    """
    path = bundle_path(root, "contract", violation.violation_id)
    if not path.is_file():
        return {"contract_path": None, "contract_changed": False}
    try:
        before = path.read_text(encoding="utf-8")
        contract = json.loads(before)
    except (OSError, ValueError):
        return {"contract_path": None, "contract_changed": False}
    if not isinstance(contract, dict):
        return {"contract_path": None, "contract_changed": False}

    text = json.dumps(project_contract(contract, violation), indent=2, ensure_ascii=False)
    if text == before:
        return {"contract_path": str(path), "contract_changed": False}
    try:
        path.write_text(text, encoding="utf-8")
    except OSError:
        return {"contract_path": str(path), "contract_changed": False}
    return {"contract_path": str(path), "contract_changed": True}


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
