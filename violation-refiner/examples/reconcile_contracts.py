#!/usr/bin/env python3
"""Rewrite every bundle's ``contract.json`` as the projection of its violation.

``contract.json`` is written once by ``examples/vault_to_bundle.py`` and was then
kept in step by a reconciler that rewrote only the four fields V08 and V17
compare. Everything else — ``legal_basis`` above all — stayed as the vault wrote
it, so a bundle could publish an article as ``status: "established"`` with an
empty ``article_text`` while the violation beside it held that article as a
*candidate*. ``pack.project_contract`` is the rule that ends this, and the two
writers of a violation call it on every write. This script applies it to the
bundles that were written before that rule existed.

Dry run by default; pass ``--write`` to land the changes::

    .venv/bin/python examples/reconcile_contracts.py            # report only
    .venv/bin/python examples/reconcile_contracts.py --write    # apply

Two things it deliberately does not do.

*It does not back anything up.* A backup step inside a re-runnable script is only
a backup on its first run — the second copies the new file over it and the
"before" state is gone. The ``build/`` tree is tracked, so the authoritative
previous version of every file is ``git show HEAD:build/<id>/contract.json`` and
needs no discipline to keep::

    git diff --stat -- build/*/contract.json
    git checkout HEAD -- build/CL-030/contract.json     # one bundle back

*It does not rebuild MANIFEST.txt.* The hashes there describe the generation of
the bundle the file was written with, and the UI write path leaves the manifest
stale after every edit for the same reason: ``<id>.json`` changes on every write
(``confidence.derived_at`` is refreshed), so a manifest is a snapshot rather than
a stable artifact id. Rebuilding 81 of them would rewrite 81 more tracked files
for a value nothing checks.

A symlinked ``contract.json`` is refused rather than written through: the layout
artifacts in this corpus (``Legal framework/*.md``, ``speaker_index.json``) are
symlinks into other trees, and following one would edit the corpus instead of the
bundle.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from violation_pack.models import Violation  # noqa: E402
from violation_pack.pack import project_contract  # noqa: E402


def _bundle_dirs(build_root: Path) -> list[Path]:
    """Every directory holding a ``<name>.json`` violation.

    Structural, not ``CL-\\d{3}``-shaped: the corpus carries ``BR-``, ``INT-`` and
    one opaque ``CL-f7dd941e`` bundle, and a naming filter would quietly skip
    them. A bundle with a contract but no ``<name>.json`` (``build/CL-0301``)
    has nothing to project from and is reported as such.
    """
    if not build_root.is_dir():
        return []
    return sorted(p for p in build_root.iterdir() if p.is_dir() and (p / f"{p.name}.json").is_file())


def _changed_keys(before: dict, after: dict) -> list[str]:
    return [
        key
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key)
    ]


def reconcile_bundle(bundle: Path, *, write: bool) -> tuple[str, list[str]]:
    """Project one bundle's contract. Returns ``(outcome, changed_keys)``."""
    violation_path = bundle / f"{bundle.name}.json"
    contract_path = bundle / "contract.json"

    if not contract_path.exists():
        return "no contract", []
    if contract_path.is_symlink():
        return "refused: contract.json is a symlink", []
    try:
        violation = Violation.model_validate_json(violation_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - reported, not raised: one bad bundle
        return f"unreadable violation: {exc}", []
    try:
        before_text = contract_path.read_text(encoding="utf-8")
        before = json.loads(before_text)
    except ValueError as exc:
        return f"unreadable contract: {exc}", []
    if not isinstance(before, dict):
        return "contract is not an object", []

    after = project_contract(json.loads(before_text), violation)
    changed = _changed_keys(before, after)
    if not changed:
        return "unchanged", []
    if write:
        contract_path.write_text(
            json.dumps(after, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return "rewritten", changed
    return "would rewrite", changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--build-root", default="build", type=Path)
    parser.add_argument(
        "--write",
        action="store_true",
        help="land the changes (default: report what would change)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="list every bundle, not just the ones that changed",
    )
    args = parser.parse_args()

    if not args.build_root.is_dir():
        print(f"no such build root: {args.build_root}", file=sys.stderr)
        return 2

    bundles = _bundle_dirs(args.build_root)
    outcomes: dict[str, int] = {}
    failures: list[str] = []
    for bundle in bundles:
        outcome, changed = reconcile_bundle(bundle, write=args.write)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        if outcome.startswith("unreadable") or outcome.startswith("refused"):
            failures.append(f"{bundle.name}: {outcome}")
        if args.all or changed:
            detail = f" ({len(changed)} key(s): {', '.join(changed)})" if changed else ""
            print(f"{bundle.name}: {outcome}{detail}")

    verb = "rewritten" if args.write else "would be rewritten"
    print()
    print(f"bundles: {len(bundles)}")
    for outcome in sorted(outcomes):
        print(f"  {outcome}: {outcomes[outcome]}")
    changed_any = outcomes.get("rewritten" if args.write else "would rewrite", 0)
    print(f"{changed_any} contract(s) {verb}.")
    if not args.write and changed_any:
        print("Re-run with --write to land them.")
    for failure in failures:
        print(f"FAILED {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
