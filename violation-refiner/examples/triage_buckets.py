#!/usr/bin/env python3
"""Classify CL violations into action buckets and emit ready-to-run commands.

Reads Validation/checks.json for each canonical CL-XXX bundle (no suffix),
groups violations by failure class, and prints a concrete remediation
command list per bucket.

Usage:
    python3 examples/triage_buckets.py --input build/cl_batch
    python3 examples/triage_buckets.py --input build/cl_batch --emit-script remediate.sh
"""
from __future__ import annotations

import argparse
import json
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    check_id: str
    name: str
    status: str  # pass | warn | fail
    details: str


@dataclass
class BundleReport:
    violation_id: str
    p: int = 0
    w: int = 0
    f: int = 0
    missing_checks: bool = False
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def failing_ids(self) -> list[str]:
        return [c.check_id for c in self.checks if c.status == "fail"]

    @property
    def warn_ids(self) -> list[str]:
        return [c.check_id for c in self.checks if c.status == "warn"]

    def check(self, cid: str) -> CheckResult | None:
        for c in self.checks:
            if c.check_id == cid:
                return c
        return None


# ---------------------------------------------------------------------------
# V01 detail parser
# ---------------------------------------------------------------------------

_SEG_DETAIL = re.compile(r'"(?P<entry>[A-Z]+-\d+\.seg-\d+: [^"]+)"')


def _parse_v01_details(details: str) -> list[dict]:
    """Extract individual unresolved segment entries from V01 details string."""
    out = []
    for m in _SEG_DETAIL.finditer(details):
        entry = m.group("entry")
        left, sep, reason = entry.partition(": ")
        if not sep or "." not in left:
            continue
        src, seg = left.split(".", 1)
        out.append({
            "source": src,
            "segment": seg,
            "reason": reason.strip(),
        })
    return out


# ---------------------------------------------------------------------------
# Bucket classification
# ---------------------------------------------------------------------------


BUCKET_CLEAN = "CLEAN"
BUCKET_WARN_ONLY = "WARN_ONLY"
BUCKET_V01_UNRESOLVED = "V01_UNRESOLVED"
BUCKET_OTHER_FAIL = "OTHER_FAIL"


def classify(report: BundleReport) -> str:
    if report.missing_checks:
        return BUCKET_OTHER_FAIL
    if report.f == 0 and report.w == 0:
        return BUCKET_CLEAN
    if report.f == 0:
        return BUCKET_WARN_ONLY
    if "V01" in report.failing_ids:
        return BUCKET_V01_UNRESOLVED
    return BUCKET_OTHER_FAIL


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _canonical_dirs(root: Path) -> list[Path]:
    """Return only canonical CL-NNN dirs (no suffix variants)."""
    pattern = re.compile(r"^CL-\d{3}$")
    return sorted(
        [p for p in root.iterdir() if p.is_dir() and pattern.match(p.name)],
        key=lambda p: p.name,
    )


def load_report(bundle: Path) -> BundleReport:
    checks_path = bundle / "Validation" / "checks.json"
    br = BundleReport(violation_id=bundle.name)
    if not checks_path.exists():
        br.missing_checks = True
        return br
    try:
        data = json.loads(checks_path.read_text(encoding="utf-8"))
    except Exception:
        br.missing_checks = True
        return br
    for c in data.get("checks") or []:
        br.checks.append(CheckResult(
            check_id=c.get("check_id", "?"),
            name=c.get("name", ""),
            status=c.get("status", "pass"),
            details=c.get("details", ""),
        ))
    # summary is a @property on ValidationReport and is NOT serialized into
    # checks.json, so we always derive counts from the check list itself.
    br.p = sum(1 for c in br.checks if c.status == "pass")
    br.w = sum(1 for c in br.checks if c.status == "warn")
    br.f = sum(1 for c in br.checks if c.status == "fail")
    return br


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------

_BUCKET_LABELS = {
    BUCKET_CLEAN: "✅ CLEAN (0 fail, 0 warn)",
    BUCKET_WARN_ONLY: "⚠️  WARN-ONLY (0 fail, warns accepted)",
    BUCKET_V01_UNRESOLVED: "❌ V01 UNRESOLVED SEGMENTS (needs upstream fix + rerun)",
    BUCKET_OTHER_FAIL: "❌ OTHER FAIL (non-V01 failure)",
}

_BUCKET_ORDER = [BUCKET_CLEAN, BUCKET_WARN_ONLY, BUCKET_V01_UNRESOLVED, BUCKET_OTHER_FAIL]


def _print_matrix(reports: list[BundleReport]) -> None:
    header = f"{'Violation':<10} {'P':>2} {'W':>2} {'F':>2}  {'Bucket':<28} Failing checks"
    print(header)
    print("─" * max(len(header), 90))
    for r in reports:
        bucket = classify(r)
        if r.missing_checks:
            fails = "missing Validation/checks.json"
        else:
            fails = ", ".join(r.failing_ids) if r.failing_ids else "—"
        tag = bucket.replace("_", " ")
        print(f"{r.violation_id:<10} {r.p:>2} {r.w:>2} {r.f:>2}  {tag:<28} {fails}")
    print()


def _print_buckets(buckets: dict[str, list[BundleReport]]) -> None:
    for btype in _BUCKET_ORDER:
        members = buckets.get(btype, [])
        if not members:
            continue
        ids = [r.violation_id for r in members]
        print(f"\n{'═' * 72}")
        print(f"  {_BUCKET_LABELS[btype]}")
        print(f"  Members: {', '.join(ids)}")
        print(f"{'═' * 72}")

        if btype == BUCKET_CLEAN:
            print("  → No action needed. These violations are fully passing.\n")

        elif btype == BUCKET_WARN_ONLY:
            print("  → No rerun needed. Remaining warns are non-blocking:")
            for r in members:
                for c in r.checks:
                    if c.status == "warn":
                        short = c.details[:100] + "…" if len(c.details) > 100 else c.details
                        print(f"    {r.violation_id} {c.check_id} {c.name}: {short}")
            print()
            print("  Warn classes explanation:")
            print("    V03 (SHA mismatch)  — cosmetic header drift; FAIL-level cache check still passes.")
            print("    V07 (authorities)   — zero-fabrication policy; populate when filing.")
            print("    V08 (contract)      — legacy ID alias accepted; confidence.value from old schema.")
            print("    V09 (language)      — some segments missing translation_en (correlates with V01).")
            print()

        elif btype == BUCKET_V01_UNRESOLVED:
            # Parse V01 details for each member to show transcript-level breakdown
            print()
            print("  Unresolved segments by transcript:")
            transcript_index: dict[str, list[str]] = {}  # src -> [(vid, seg, reason)]
            for r in members:
                v01 = r.check("V01")
                if not v01:
                    continue
                entries = _parse_v01_details(v01.details)
                for e in entries:
                    key = e["source"]
                    transcript_index.setdefault(key, [])
                    transcript_index[key].append(
                        f"{r.violation_id}  {key}.{e['segment']}  ({e['reason']})"
                    )
            for src in sorted(transcript_index):
                print(f"\n    📄 {src}:")
                for line in transcript_index[src]:
                    print(f"       {line}")
            print()

        elif btype == BUCKET_OTHER_FAIL:
            for r in members:
                if r.missing_checks:
                    print(f"    {r.violation_id}: missing Validation/checks.json")
                    continue
                for c in r.checks:
                    if c.status == "fail":
                        print(f"    {r.violation_id} {c.check_id} {c.name}: {c.details[:120]}")
            print()


def _print_commands(buckets: dict[str, list[BundleReport]]) -> None:
    print()
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║                     READY-TO-RUN COMMANDS                           ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")

    # --- Bucket: WARN_ONLY → no commands needed but offer optional contract refresh
    warn_ids = [r.violation_id for r in buckets.get(BUCKET_WARN_ONLY, [])]
    if warn_ids:
        print()
        print("── WARN-ONLY: No mandatory action ──────────────────────────────────")
        print("   These are passing (fail=0). Warns are accepted by policy.")
        print("   Optional: to suppress V08 confidence.value warn, regenerate contracts:")
        ids_str = " ".join(warn_ids)
        print(f"   # for v in {ids_str}; do")
        print(f"   #   python3 examples/sync_contract.py --input build/cl_batch --only $v")
        print(f"   # done")
        print()

    # --- Bucket: V01_UNRESOLVED → validation-only after upstream manifest fix
    v01_members = buckets.get(BUCKET_V01_UNRESOLVED, [])
    if v01_members:
        v01_ids = [r.violation_id for r in v01_members]

        # Sub-classify: which need restaging (manifest segment_id fix) vs just revalidation
        # For now, all V01 failures need the source manifest corrected first,
        # then re-stage + validation-only rerun (enrichment already present).
        print()
        print("── V01 UNRESOLVED: Upstream manifest fix → restage → revalidate ────")
        print("   These violations reference segment IDs that don't exist in the")
        print("   transcript HTML. Fix the segments_manifest.json for each case,")
        print("   then run the commands below.")
        print()
        print("   Step 1: Fix source manifests (manual — per transcript above)")
        print()
        print("   Step 2: Restage + validation-only rerun (no LLM cost):")
        ids_str = " ".join(v01_ids)
        print(f"   for v in {ids_str}; do")
        print(f"     echo \"=== $v ===\"")
        print(f"     # Restage from corrected source manifest")
        print(f"     python3 examples/stage_cl_batch.py --jurisdiction CL --ids $v")
        print(f"     # Revalidate without enrichment (preserves existing LLM output)")
        print(f"     python3 examples/refine_batch.py --input build/cl_batch --only $v --no-enrich")
        print(f"   done")
        print()
        print("   Step 2-ALT: If segment IDs were expanded (new segments need enrichment):")
        for vid in v01_ids:
            print(f"   ./examples/run_one.sh {vid} --no-enrich   # or full run if new segments added")
        print()

        # Also emit a targeted full-rerun command for cases where manifest fix
        # adds new segments that need LLM enrichment
        print("   Step 3 (only if new segments were added by manifest fix):")
        print(f"   for v in {ids_str}; do")
        print(f"     ./examples/run_one.sh $v")
        print(f"   done")
        print()

    # --- Bucket: OTHER_FAIL → case-by-case
    other_members = buckets.get(BUCKET_OTHER_FAIL, [])
    if other_members:
        print()
        print("── OTHER FAIL: Case-by-case investigation ──────────────────────────")
        for r in other_members:
            if r.missing_checks:
                print(f"   {r.violation_id}: missing Validation/checks.json")
                print("     # Generate validation artifacts first:")
                print(f"     ./examples/run_one.sh {r.violation_id} --no-enrich")
                print()
                continue
            for c in r.checks:
                if c.status == "fail":
                    print(f"   {r.violation_id}: {c.check_id} {c.name}")
                    print(f"     Details: {c.details[:200]}")
                    print(f"     # Revalidate after fix:")
                    print(f"     python3 examples/refine_batch.py --input build/cl_batch --only {r.violation_id} --no-enrich")
                    print()

    # --- Summary
    clean = len(buckets.get(BUCKET_CLEAN, []))
    warn = len(buckets.get(BUCKET_WARN_ONLY, []))
    v01 = len(v01_members)
    other = len(other_members)
    total = clean + warn + v01 + other
    print()
    print("── SUMMARY ─────────────────────────────────────────────────────────")
    print(f"   Total canonical bundles:    {total}")
    print(f"   ✅ Clean (0F/0W):           {clean}")
    print(f"   ⚠️  Warn-only (0F):          {warn}")
    print(f"   ❌ V01 unresolved:           {v01}")
    print(f"   ❌ Other fail:               {other}")
    blocked = v01 + other
    if blocked == 0:
        print(f"\n   🎉 All violations are at fail=0. Ready for new full runs!")
    else:
        print(f"\n   🔧 {blocked} violation(s) need correction before new full runs.")
    print()


# ---------------------------------------------------------------------------
# Script output (optional)
# ---------------------------------------------------------------------------


def _emit_script(path: Path, buckets: dict[str, list[BundleReport]]) -> None:
    """Write a ready-to-execute shell script for unresolved buckets."""
    lines = [
        "#!/usr/bin/env bash",
        "# Auto-generated by triage_buckets.py",
        "# Revalidation commands for V01-affected violations.",
        "# PREREQUISITE: fix source segments_manifest.json files first!",
        "set -euo pipefail",
        "",
        'cd "$(dirname "$0")/.."',
        "source .venv/bin/activate",
        "",
    ]
    v01_members = buckets.get(BUCKET_V01_UNRESOLVED, [])
    if v01_members:
        ids = [r.violation_id for r in v01_members]
        lines.append(f"VIOLATIONS=({' '.join(ids)})")
        lines.append("")
        lines.append("for v in \"${VIOLATIONS[@]}\"; do")
        lines.append("  # refine_batch prefers <id>.json.bak when present; clear stale snapshots")
        lines.append("  rm -f \"build/cl_batch/$v/$v.json.bak\"")
        lines.append("  echo \"=== Restaging $v ===\"")
        lines.append("  python3 examples/stage_cl_batch.py --jurisdiction CL --ids \"$v\"")
        lines.append("  echo \"=== Revalidating $v ===\"")
        lines.append("  python3 examples/refine_batch.py --input build/cl_batch --only \"$v\" --no-enrich")
        lines.append("done")
        lines.append("")
    else:
        lines.append("echo 'No V01 violations to process.'")

    missing_or_other = buckets.get(BUCKET_OTHER_FAIL, [])
    actionable_other = [r for r in missing_or_other if r.missing_checks]
    if actionable_other:
        lines.append("")
        lines.append("# Generate validation artifacts for bundles missing checks.json")
        for r in actionable_other:
            lines.append(f"echo \"=== Validating {r.violation_id} ===\"")
            lines.append(f"./examples/run_one.sh {r.violation_id} --no-enrich")

    lines.append("")
    lines.append("echo")
    lines.append("echo \"Remediation run complete. Run triage_buckets.py again to verify.\"")
    lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o755)
    print(f"\n📝 Shell script written to: {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Classify violations into action buckets and emit remediation commands"
    )
    parser.add_argument("--input", type=Path, required=True, help="Root folder with CL-* bundles")
    parser.add_argument(
        "--emit-script",
        type=Path,
        default=None,
        help="Also write a ready-to-run .sh script for V01 remediation",
    )
    args = parser.parse_args()

    root = args.input
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    dirs = _canonical_dirs(root)
    reports = [load_report(d) for d in dirs]

    # Build bucket map
    buckets: dict[str, list[BundleReport]] = {}
    for r in reports:
        b = classify(r)
        buckets.setdefault(b, []).append(r)

    # Output
    _print_matrix(reports)
    _print_buckets(buckets)
    _print_commands(buckets)

    if args.emit_script:
        _emit_script(args.emit_script, buckets)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
