#!/usr/bin/env python
"""Recompute one bundle's derived artifacts from the violation JSON on disk.

``Validation/checks.json``, ``Validation/validation_report.md`` and
``MANIFEST.txt`` are *snapshots*, not the current verdict: they keep reporting
whatever an earlier run computed, including ``pass`` for content that has since
changed. So any hand-edit of ``<VID>.json`` leaves them describing a different
bundle, and ``MANIFEST.txt`` holds sha256s of the previous generation.

This replays the writer's own sequence — the tail of
``refine_batch_core._process_one`` — against the *live* file:

    run_pipeline (read-only) -> checks.json -> validation_report.md
                             -> sync_segment_artifacts -> reconcile_contract
                             -> build_manifest

Two deliberate differences from ``_process_one``:

* ``attach_confidence`` is **not** called. It refreshes ``confidence.derived_at``
  and appends the previous value to ``confidence.history`` on every pass, so it
  would make the file differ from itself for provenance reasons that have
  nothing to do with the edit being refreshed. Recompute a confidence value by
  running the real pipeline stage, not by refreshing a snapshot.
* The violation JSON is never written. This script reports; it does not patch.

Usage:
    python scripts/refresh_bundle_artifacts.py CL-030 [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from violation_pack.pack import build_manifest, project_contract, reconcile_contract  # noqa: E402
from violation_pack.refine_batch_core import (  # noqa: E402
    _collect_known_ids,
    _discover_frameworks,
    _discover_transcripts,
    _load_violation,
    _write_validation_markdown,
)
from violation_pack.segment_sync import sync_segment_artifacts  # noqa: E402
from violation_pack.validation import run_pipeline  # noqa: E402

TRACKED_ARTIFACTS = ("Validation/checks.json", "Validation/validation_report.md", "contract.json", "MANIFEST.txt")


def _digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("violation_id")
    ap.add_argument("--dry-run", action="store_true", help="report the verdict and the file deltas, write nothing")
    args = ap.parse_args()

    bundle = REPO / "build" / args.violation_id
    if not bundle.is_dir():
        raise SystemExit(f"no such bundle: {bundle}")
    vio_json = next((p for p in sorted(bundle.glob("*.json")) if p.stem == args.violation_id), None)
    if vio_json is None:
        raise SystemExit(f"no {args.violation_id}.json in {bundle}")

    before = {rel: _digest(bundle / rel) for rel in TRACKED_ARTIFACTS}

    transcripts = _discover_transcripts(bundle)
    frameworks = _discover_frameworks(bundle)
    violation, notes = _load_violation(vio_json, transcripts, frameworks)
    contract = project_contract(
        __import__("json").loads((bundle / "contract.json").read_text(encoding="utf-8")), violation
    )
    known = _collect_known_ids(sorted(p for p in (REPO / "build").iterdir() if p.is_dir()))
    report = run_pipeline(
        violation,
        transcripts=transcripts,
        frameworks=frameworks,
        contract=contract,
        known_violation_ids=known,
    )

    print(f"== {args.violation_id} ==")
    print(f"summary: {report.summary}")
    print(f"confidence: {violation.confidence.value if violation.confidence else None}")
    print(f"caches: {[c.framework_code for c in violation.framework_caches]}")
    for note in notes:
        print(f"loader note: {note}")
    for check in report.checks:
        if check.status != "pass":
            print(f"  {check.status.upper():4s} {check.check_id} {check.name}: {str(check.details)[:200]}")

    if args.dry_run:
        print("\n(--dry-run: nothing written)")
        return 0

    checks_path = bundle / "Validation" / "checks.json"
    checks_path.parent.mkdir(parents=True, exist_ok=True)
    checks_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    _write_validation_markdown(
        bundle, violation.violation_id, [c.model_dump() for c in report.checks], report.summary
    )

    sync = sync_segment_artifacts(violation, bundle)
    for warning in sync.get("warnings", []):
        print(f"segment_sync warning: {warning}")
    contract_sync = reconcile_contract(bundle, violation)
    build_manifest(bundle, schema_version=violation.schema_version)

    after = {rel: _digest(bundle / rel) for rel in TRACKED_ARTIFACTS}
    print("\nfile deltas:")
    for rel in TRACKED_ARTIFACTS:
        state = "unchanged" if before[rel] == after[rel] else ("written" if after[rel] else "missing")
        print(f"  {state:10s} {rel}")
    print(f"contract reconcile: {contract_sync}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
