#!/usr/bin/env python3
"""Pre-flight validation for CL violation pipeline execution.

Checks that all required source data, transcripts, framework caches, and
services are available before the pipeline starts. Designed to prevent the
"source not found" class of failures documented in the CL-007 incident.

Also compares each bundle's segment ids against the converter's
``segments_manifest.json``, which catches a stale ``<VID>.json.bak`` shadowing
the converted bundle (``refine_batch_core._load_violation`` prefers it) before
refinement bakes the wrong content in.

Reads the bundles the converter wrote (``build/<VID>/``), so run
``examples/vault_to_bundle.py`` first.

Usage:
    .venv/bin/python examples/validate_preflight.py --ids CL-007
    .venv/bin/python examples/validate_preflight.py --ids CL-005 CL-007 CL-016
    .venv/bin/python examples/validate_preflight.py --all   # scan all in --source

Exit codes:
    0 — all checks pass
    1 — one or more checks failed (errors printed to stderr)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

try:
    from violation_pack.config import Settings
except ImportError:
    Settings = None  # type: ignore[assignment]


# -- Default paths (override with CLI flags) ---------------------------------
# The converter writes the final bundle under build/, and both data trees are
# the repo's own, so a pre-flight run needs no server paths.
DEFAULT_SOURCE = Path("build")
DEFAULT_TRANSCRIPT_DIR = Path("data/transcripts/json")
DEFAULT_LAW_ROOT = Path("data/law")


# -- Framework code -> file resolution ---------------------------------------
# Derived from the law registry at run time. A hand-maintained table drifts
# silently: the retired FRAMEWORK_MD_MAP already mapped CL.CP to the Penal
# Code's chip-encoding section, which is a different law.
try:
    from vault_to_bundle import FrameworkResolver, _LEGACY_CODE_ALIASES
except ImportError:  # imported as ``examples.validate_preflight``
    from examples.vault_to_bundle import (  # type: ignore[no-redef]
        FrameworkResolver,
        _LEGACY_CODE_ALIASES,
    )


def _segment_src(seg_id: str) -> str | None:
    if "." not in seg_id:
        return None
    return seg_id.split(".", 1)[0]


def _segment_index(seg_id: str) -> int | None:
    """``"...seg-18"`` -> ``18``, the transcript JSON ``segments[].index`` field."""
    if ".seg-" not in seg_id:
        return None
    tail = seg_id.rsplit(".seg-", 1)[1]
    return int(tail) if tail.isdigit() else None


def check_source_data(source_root: Path, vid: str) -> list[str]:
    """Check contract.json and segments_manifest.json exist for a violation."""
    errors: list[str] = []
    src = source_root / vid
    if not src.is_dir():
        errors.append(f"[{vid}] Source directory not found: {src}")
        return errors
    for fname in ("contract.json", "segments_manifest.json"):
        if not (src / fname).exists():
            errors.append(f"[{vid}] Missing {fname} in {src}")
    return errors


def check_bundle_segments(source_root: Path, vid: str) -> list[str]:
    """Compare the bundle's segment ids against the converter's manifest.

    ``segments_manifest.json`` records both the canonical id
    (``<source>.seg-N``, what the converter writes into the bundle) and the
    vault's ``legacy_segment_id`` (``STG-7.seg-44``). Those two sets are the
    fingerprint of the one failure that is invisible downstream: a
    ``<VID>.json.bak`` left behind by an earlier refiner run is preferred by
    ``refine_batch_core._load_violation`` over the live JSON, so a stale bundle
    silently replaces the converted one and every later check passes against
    the wrong content (V01 resolves the legacy ids against the vendored HTML
    render, so nothing complains). Catching it here costs one dict comparison.
    """
    errors: list[str] = []
    src = source_root / vid
    sm_path = src / "segments_manifest.json"
    json_path = src / f"{vid}.json"
    if not sm_path.exists():
        return errors
    if not json_path.exists():
        return [f"[{vid}] Bundle violation JSON not found: {json_path}"]

    manifest = (json.loads(sm_path.read_text(encoding="utf-8")).get("segments")) or []
    if not manifest:
        return errors  # segment-less violation: nothing to compare

    canonical = {str(s.get("segment_id")) for s in manifest if isinstance(s, dict)}
    legacy = {
        str(s.get("legacy_segment_id"))
        for s in manifest
        if isinstance(s, dict) and s.get("legacy_segment_id")
    }
    try:
        doc = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"[{vid}] {json_path.name} is not valid JSON: {exc}"]

    actual = {
        str(s.get("segment_id")) for s in doc.get("segments") or [] if isinstance(s, dict)
    }
    if actual == canonical:
        return errors

    stale = actual & legacy
    if stale and not actual & canonical:
        errors.append(
            f"[{vid}] {json_path.name} holds the vault's legacy segment ids "
            f"({sorted(stale)[:3]}…) instead of the converter's canonical ids — "
            f"a stale {json_path.name}.bak shadowed the converted bundle. Delete "
            "it and re-run examples/vault_to_bundle.py before refining."
        )
    else:
        errors.append(
            f"[{vid}] {json_path.name} segment ids disagree with segments_manifest.json "
            f"({len(canonical)} canonical vs {len(actual)} in the bundle); "
            f"missing={sorted(canonical - actual)[:3]} extra={sorted(actual - canonical)[:3]}"
        )
    return errors


def check_transcripts(
    sm_path: Path, transcript_dir: Path
) -> tuple[list[str], list[str], list[str]]:
    """Check the manifest's transcript files exist and hold every referenced segment.

    ``segments_manifest.json`` carries the ``transcript_files`` map the converter
    wrote (source id -> JSON filename), so nothing here has to guess a filename or
    mirror a registry. Beyond existence this re-reads each transcript and confirms
    the referenced ``seg-N`` indexes are present, which is the failure the refiner
    would otherwise hit at ``JsonTranscriptSource.get_segment`` time.

    A bundle with no segments is legitimate (the vault violation matched no audio),
    so it reports nothing rather than failing.

    Returns (errors, found_paths, warnings).
    """
    errors: list[str] = []
    found: list[str] = []
    warnings: list[str] = []
    if not sm_path.exists():
        return errors, found, warnings

    sm = json.loads(sm_path.read_text(encoding="utf-8"))
    tmap = sm.get("transcript_files") or {}

    wanted: dict[str, set[int]] = {}
    for seg in sm.get("segments") or []:
        sid = str(seg.get("segment_id") or "") if isinstance(seg, dict) else str(seg)
        src = _segment_src(sid)
        idx = _segment_index(sid)
        if not src or idx is None:
            errors.append(f"[sm] Segment id '{sid}' is not of the form '<source>.seg-N'")
            continue
        wanted.setdefault(src, set()).add(idx)

    if not wanted:
        return errors, found, warnings
    if not tmap:
        return ["[sm] no transcript_files map, but segments reference sources"], found, warnings

    for src in sorted(wanted):
        fname = tmap.get(src)
        if not fname:
            errors.append(
                f"[sm] No transcript mapped for source '{src}'; re-run "
                "examples/vault_to_bundle.py to regenerate the manifest"
            )
            continue
        path = transcript_dir / fname
        if not path.exists():
            errors.append(f"[sm] Transcript JSON not found: {path}")
            continue
        found.append(str(path))
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"[sm] {path} is not valid JSON: {exc}")
            continue
        present = {
            s.get("index") for s in doc.get("segments") or [] if isinstance(s, dict)
        }
        missing = sorted(wanted[src] - present)
        if missing:
            errors.append(f"[sm] {fname} is missing referenced segment index(es): {missing}")
    return errors, found, warnings


def _extract_framework_codes(contract: dict, jurisdiction: str) -> set[str]:
    """Extract framework codes from any of three legacy legal_basis shapes."""
    codes: set[str] = set()

    def _fw_from_article(article_id: str) -> str | None:
        parts = article_id.split(".")
        if len(parts) >= 2 and parts[0] == jurisdiction:
            return parts[1]
        return None

    lb_raw = contract.get("legal_basis")
    if not lb_raw:
        return codes

    if isinstance(lb_raw, dict) and lb_raw.get("frameworks"):
        # Shape (c): {frameworks: [{framework_code, articles: [...]}]}
        for fw in lb_raw.get("frameworks") or []:
            code = str(fw.get("framework_code") or "").strip()
            if code:
                codes.add(code)
    elif isinstance(lb_raw, list):
        # Shape (b): [{article_id: "CL.XXX.Art.N", ...}, ...]
        for a in lb_raw:
            if isinstance(a, dict) and a.get("article_id"):
                code = _fw_from_article(str(a["article_id"]))
                if code:
                    codes.add(code)
    elif isinstance(lb_raw, dict) and lb_raw.get("article_id"):
        # Shape (a): {article_id: "CL.XXX.Art.N", ...}
        code = _fw_from_article(str(lb_raw["article_id"]))
        if code:
            codes.add(code)

    return codes


def check_framework_md(
    contract_path: Path,
    law_root: Path,
    jurisdiction: str,
) -> tuple[list[str], list[str], list[str]]:
    """Check that every framework code in the contract resolves to a corpus file.

    A code listed in ``_LEGACY_CODE_ALIASES`` with a ``None`` target is a known
    legacy code the corpus does not carry, so it is reported as a warning: the
    refiner only fails (V04) if an established article cites an uncached framework.

    Returns (errors, found_paths, warnings).
    """
    errors: list[str] = []
    found_mds: list[str] = []
    warnings: list[str] = []
    if not contract_path.exists():
        return errors, found_mds, warnings

    vid = contract_path.parent.name
    resolver = FrameworkResolver(law_root)
    if not resolver.codes:
        return [f"[law] no law registry at {law_root}/_mapping/law_registry.json"], found_mds, warnings

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    codes = _extract_framework_codes(contract, jurisdiction)
    if not codes:
        errors.append(f"[{vid}] contract: could not extract any framework codes from legal_basis")
        return errors, found_mds, warnings

    for code in sorted(codes):
        resolved_code, rel = resolver.resolve(code, jurisdiction)
        if rel is None:
            msg = (
                f"[{vid}] Framework '{code}' resolves to no file in the corpus "
                f"(registry code {resolved_code!r})"
            )
            if (jurisdiction, code.upper()) in _LEGACY_CODE_ALIASES:
                warnings.append(
                    msg + "; this is a deliberate _LEGACY_CODE_ALIASES -> None mapping, "
                    "so the refiner will warn (V03) rather than fail unless an article "
                    "of it becomes established"
                )
            else:
                errors.append(
                    msg + "; if this is a known legacy code add it to "
                    "_LEGACY_CODE_ALIASES in examples/vault_to_bundle.py"
                )
            continue
        target = law_root / rel
        if target.exists():
            found_mds.append(str(target))
        else:
            errors.append(f"[{vid}] Framework file missing: {target}")
    return errors, found_mds, warnings


def check_services() -> tuple[list[str], list[str]]:
    """Check health of dependent services."""
    errors: list[str] = []
    ok: list[str] = []

    # Qdrant connectivity
    if Settings:
        try:
            s = Settings.from_env()
            if s.qdrant_url:
                ok.append(f"Qdrant configured: {s.qdrant_url}")
            else:
                errors.append("Qdrant URL not configured")
        except Exception as e:
            errors.append(f"Qdrant config check failed: {e}")
    else:
        ok.append("Qdrant: config module not importable (skipped)")

    # Neo4j check (best-effort socket probe)
    import socket
    neo4j_host = "127.0.0.1"
    neo4j_port = 7687
    try:
        sock = socket.create_connection((neo4j_host, neo4j_port), timeout=3)
        sock.close()
        ok.append(f"Neo4j reachable at {neo4j_host}:{neo4j_port}")
    except OSError:
        errors.append(f"Neo4j NOT reachable at {neo4j_host}:{neo4j_port}")

    return errors, ok


def validate(
    source_root: Path,
    transcript_dir: Path,
    law_root: Path,
    jurisdiction: str,
    ids: list[str],
    check_services_flag: bool = True,
) -> int:
    """Run all pre-flight checks. Returns exit code (warnings do not fail the run)."""
    all_errors: list[str] = []
    all_warnings: list[str] = []
    all_ok: list[str] = []

    for vid in ids:
        # 1. Source data
        errs = check_source_data(source_root, vid)
        if not errs:
            all_ok.append(f"[{vid}] Source data: contract.json + segments_manifest.json OK")
        all_errors.extend(errs)

        sm_path = source_root / vid / "segments_manifest.json"
        contract_path = source_root / vid / "contract.json"

        # 2. Bundle segments vs the converter's manifest
        b_errs = check_bundle_segments(source_root, vid)
        if not b_errs:
            all_ok.append(f"[{vid}] Bundle segments: ids match segments_manifest.json")
        all_errors.extend(b_errs)

        # 3. Transcripts
        t_errs, t_found, t_warns = check_transcripts(sm_path, transcript_dir)
        if not t_errs and t_found:
            all_ok.append(f"[{vid}] Transcripts: {len(t_found)} file(s) cover every referenced segment")
        elif not t_errs:
            all_ok.append(f"[{vid}] Transcripts: no segments referenced")
        all_errors.extend(t_errs)
        all_warnings.extend(t_warns)

        # 4. Framework files
        f_errs, f_found, f_warns = check_framework_md(contract_path, law_root, jurisdiction)
        if not f_errs:
            all_ok.append(f"[{vid}] Framework files: {len(f_found)} found")
        all_errors.extend(f_errs)
        all_warnings.extend(f_warns)

    # 5. Services
    if check_services_flag:
        s_errs, s_ok = check_services()
        all_errors.extend(s_errs)
        all_ok.extend(s_ok)

    # Report
    print(f"Pre-flight validation for {len(ids)} violation(s) in {jurisdiction}")
    print(f"  Source:        {source_root}")
    print(f"  Transcripts:   {transcript_dir}")
    print(f"  Law root:      {law_root}")
    print()

    if all_errors:
        print(f"FAILURES ({len(all_errors)}):")
        for e in all_errors:
            print(f"  ✗ {e}")
        print()

    if all_warnings:
        print(f"WARNINGS ({len(all_warnings)}):")
        for w in all_warnings:
            print(f"  ! {w}")
        print()

    if all_ok:
        print(f"PASSED ({len(all_ok)}):")
        for o in all_ok:
            print(f"  ✓ {o}")
    else:
        print("No checks passed.")

    return 0 if not all_errors else 1


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pre-flight validation for CL pipeline")
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--transcript-dir", type=Path, default=DEFAULT_TRANSCRIPT_DIR)
    p.add_argument("--law-root", type=Path, default=DEFAULT_LAW_ROOT)
    p.add_argument("--jurisdiction", choices=["CL", "BR", "INT"], default="CL")
    p.add_argument("--ids", nargs="+", help="e.g. CL-005 CL-007")
    p.add_argument("--all", action="store_true", help="Validate all violations under --source")
    p.add_argument("--no-services", action="store_true", help="Skip service health checks")
    return p.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)

    if args.all:
        ids = sorted(
            d.name for d in args.source.iterdir()
            if d.is_dir() and d.name.startswith(f"{args.jurisdiction}-")
        )
        if not ids:
            print(f"No {args.jurisdiction}-* directories found under {args.source}", file=sys.stderr)
            return 1
        print(f"Auto-detected {len(ids)} violation(s): {', '.join(ids[:10])}"
              f"{'...' if len(ids) > 10 else ''}")
    elif args.ids:
        ids = args.ids
    else:
        print("Specify --ids or --all", file=sys.stderr)
        return 2

    return validate(
        source_root=args.source,
        transcript_dir=args.transcript_dir,
        law_root=args.law_root,
        jurisdiction=args.jurisdiction,
        ids=ids,
        check_services_flag=not args.no_services,
    )


if __name__ == "__main__":
    raise SystemExit(main())
