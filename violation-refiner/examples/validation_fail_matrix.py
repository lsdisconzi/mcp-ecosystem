#!/usr/bin/env python3
"""Summarize validator outcomes from bundle Validation/checks.json files.

Examples:
  python3 examples/validation_fail_matrix.py --input build/cl_batch
  python3 examples/validation_fail_matrix.py --input build/cl_batch --only CL-008 CL-010
  python3 examples/validation_fail_matrix.py --input build/cl_batch --include-warns
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a fail matrix from Validation/checks.json")
    parser.add_argument("--input", type=Path, required=True, help="Root folder containing CL-* bundle dirs")
    parser.add_argument("--only", nargs="*", default=[], help="Process only selected bundle ids")
    parser.add_argument(
        "--include-warns",
        action="store_true",
        help="Also include warning checks in the output matrix",
    )
    parser.add_argument(
        "--max-details",
        type=int,
        default=140,
        help="Max characters per check details field in console output",
    )
    return parser.parse_args()


def _iter_bundle_dirs(root: Path) -> list[Path]:
    dirs = [p for p in root.iterdir() if p.is_dir() and p.name.startswith("CL-")]
    return sorted(dirs, key=lambda p: p.name)


def _short(text: str, max_len: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _load_checks(checks_path: Path) -> dict | None:
    if not checks_path.exists():
        return None
    try:
        return json.loads(checks_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def main() -> int:
    args = parse_args()
    root = args.input
    if not root.is_dir():
        raise SystemExit(f"Input path does not exist or is not a directory: {root}")

    only = set(args.only)
    rows: list[dict] = []

    for bundle in _iter_bundle_dirs(root):
        if only and bundle.name not in only:
            continue

        checks_path = bundle / "Validation" / "checks.json"
        payload = _load_checks(checks_path)
        if not payload:
            rows.append(
                {
                    "violation_id": bundle.name,
                    "pass": None,
                    "warn": None,
                    "fail": None,
                    "issues": ["missing Validation/checks.json"],
                }
            )
            continue

        checks = payload.get("checks") or []
        issues = []
        p_count = w_count = f_count = 0
        for check in checks:
            status = str(check.get("status") or "").lower()
            if status == "pass":
                p_count += 1
            elif status == "warn":
                w_count += 1
            elif status == "fail":
                f_count += 1
            if status == "fail" or (args.include_warns and status == "warn"):
                check_id = str(check.get("check_id") or "?")
                details = _short(str(check.get("details") or ""), args.max_details)
                issues.append(f"{status.upper()}:{check_id}:{details}")

        rows.append(
            {
                "violation_id": bundle.name,
                "pass": p_count,
                "warn": w_count,
                "fail": f_count,
                "issues": issues,
            }
        )

    header = f"{'Violation':<10} {'P':>2} {'W':>2} {'F':>2}  Issues"
    print(header)
    print("-" * len(header))

    total_fails = 0
    for row in rows:
        p = "-" if row["pass"] is None else str(row["pass"])
        w = "-" if row["warn"] is None else str(row["warn"])
        f = "-" if row["fail"] is None else str(row["fail"])
        if isinstance(row["fail"], int):
            total_fails += row["fail"]
        issues = " | ".join(row["issues"]) if row["issues"] else "-"
        print(f"{row['violation_id']:<10} {p:>2} {w:>2} {f:>2}  {issues}")

    print()
    print(f"Bundles: {len(rows)}")
    print(f"Total fail count (derived): {total_fails}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
