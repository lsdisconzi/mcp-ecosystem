#!/usr/bin/env python3
"""Pre-flight validation for CL violation pipeline execution.

Checks that all required source data, transcripts, framework caches, and
services are available before the pipeline starts. Designed to prevent the
"source not found" class of failures documented in the CL-007 incident.

Usage:
    python3 examples/validate_preflight.py --jurisdiction CL --id CL-007
    python3 examples/validate_preflight.py --jurisdiction CL --ids CL-005 CL-007 CL-016
    python3 examples/validate_preflight.py --jurisdiction CL --all   # scan all in --source

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

try:
    from violation_pack.refine_batch_core import (
        _TRANSCRIPT_SOURCE_ID,
        _TRANSCRIPT_SOURCE_ID_LATAM,
        _TRANSCRIPT_SOURCE_ID_SERVER,
    )
except ImportError:
    _TRANSCRIPT_SOURCE_ID = None
    _TRANSCRIPT_SOURCE_ID_LATAM = None
    _TRANSCRIPT_SOURCE_ID_SERVER = None


# -- Default paths (mirror staging defaults; override with CLI flags) --------
DEFAULT_SOURCE = Path("/awareness/shared/violations")
DEFAULT_RENDERED = Path("/awareness/shared/transcripts_rendered")
DEFAULT_FRAMEWORK_MD_ROOT = Path("/awareness/shared/source_laws/law_md")


# -- Framework MD map (mirrors stage_cl_batch.FRAMEWORK_MD_MAP) --------------
FRAMEWORK_MD_MAP: dict[str, dict[str, str]] = {
    "CL": {
        "CHIPENCOD": "CHIPENCOD_CP.md",
        "CPCL": "CodigoPenal.md",
        "CP": "CHIPENCOD_CP.md",
        "CONST": "Constitucion.md",
        "CPR": "Constitucion.md",
        "DAN17": "DAN17_DGAC.md",
        "L18575": "DFL1_19653_L18575.md",
        "DFL1": "DFL1_19653_L18575.md",
        "DSO": "DGAC_DSO.md",
        "IVAAF": "DGAC_IVAAF.md",
        "DGAC_IVAAF": "DGAC_IVAAF.md",
        "PREVAC": "DGAC_PREVAC.md",
        "DGAC_PREVAC": "DGAC_PREVAC.md",
        "DTO2421": "DTO2421_CGR.md",
        "L16752": "L16752_DGAC.md",
        "CACH": "L18916_CACH.md",
        "L18916": "L18916_CACH.md",
        "LPDC": "L19496_LPDC.md",
        "LPC": "L19496_LPDC.md",
        "L19496": "L19496_LPDC.md",
        "L20285": "L20285_Transparencia.md",
        "INDH": "L20405_INDH.md",
        "L20405": "L20405_INDH.md",
        "L20880": "L20880_Probidad.md",
        "R218": "R218_JAC_DerechosPasajeros.md",
        "CC": "CC_CodigoCivil.md",
        "CCCL": "CC_CodigoCivil.md",
        "L19628": "L19628_LPDP.md",
        "LPDP": "L19628_LPDP.md",
    },
    "BR": {
        "CBA": "L7565_CBA.md",
        "L7565": "L7565_CBA.md",
        "CDC": "L8078_CDC.md",
        "L8078": "L8078_CDC.md",
        "CC": "L10406_CC.md",
        "L10406": "L10406_CC.md",
        "CPB": "DL2848_CP.md",
        "DL2848": "DL2848_CP.md",
        "CF88": "CF88.md",
        "CONST": "CF88.md",
        "L9784": "L9784.md",
        "L7716": "L7716_RacialCrime.md",
        "L12527": "L12527_LAI.md",
        "LAI": "L12527_LAI.md",
        "L13460": "L13460_UsuarioServicoPublico.md",
        "L8429": "L8429_Improbidade.md",
        "L12846": "L12846_Anticorrupcao.md",
        "L12813": "L12813_ConflitoInteresses.md",
        "L8906": "L8906_OAB.md",
        "OAB": "CodEtica_OAB.md",
        "D11129": "D11129_PNDH3.md",
        "D2181": "D2181_SNDC.md",
        "D7203": "D7203_Nepotismo.md",
        "D7724": "D7724_LAI_Regulamento.md",
        "R400": "R400_ANAC.md",
        "ANAC": "R400_ANAC.md",
        "ABEAR": "ABEAR_Code.md",
    },
    "INT": {
        "ACHR": "ACHR_1969.md",
        "CHICAGO": "Chicago_1944.md",
        "HAGUE": "Hague_1980.md",
        "IATA": "IATA_GC.md",
        "IATA_GC": "IATA_GC.md",
        "AN6": "ICAO_Annex6.md",
        "AN6I": "ICAO_Annex6.md",
        "AN9": "ICAO_Annex9.md",
        "AN10": "ICAO_Annex10.md",
        "AN11": "ICAO_Annex11.md",
        "AN13": "ICAO_Annex13.md",
        "AN14": "ICAO_Annex14.md",
        "AN17": "ICAO_Annex17.md",
        "AN18": "ICAO_Annex18.md",
        "DOC4444": "ICAO_DOC4444.md",
        "DOC8168": "ICAO_DOC8168.md",
        "DOC9284": "ICAO_DOC9284.md",
        "ILC_ARSIWA": "ILC_ARSIWA.md",
        "MC99": "MC99_1999.md",
        "UNCRC": "UNCRC_1989.md",
        "UNGCP": "UNGCP.md",
        "VCCR": "VCCR_1963.md",
        "VCLT": "VCLT_1969.md",
    },
}


def _segment_src(seg_id: str) -> str | None:
    if "." not in seg_id:
        return None
    return seg_id.split(".", 1)[0]


def _src_to_html_candidates(src_id: str) -> list[str]:
    """Candidate HTML filenames for a source ID (both macOS and server conventions)."""
    candidates: list[str] = []
    if src_id.startswith("LATAM-"):
        n = src_id.split("-", 1)[1]
        candidates.append(f"timeline_latam_STG_{n}.html")
        candidates.append(f"timeline_latam_stg_{n}.html")
    else:
        candidates.append(f"timeline_aeropuerto_{src_id.replace('-', '_')}.html")
        n = src_id.split("-", 1)[1] if "-" in src_id else src_id
        candidates.append(f"timeline_aeropuerto_arturo_merino_benitez_{n}.html")
    return candidates


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


def check_transcripts(
    sm_path: Path, rendered_dirs: list[Path]
) -> tuple[list[str], list[str]]:
    """Check that all referenced transcript HTMLs exist somewhere in rendered_dirs.

    Returns (errors, found_htmls).
    """
    errors: list[str] = []
    found_htmls: list[str] = []
    if not sm_path.exists():
        return errors, found_htmls

    sm = json.loads(sm_path.read_text(encoding="utf-8"))
    referenced_srcs: set[str] = set()
    for s in sm.get("segments") or []:
        sid = s if isinstance(s, str) else (s.get("segment_id") or s.get("id"))
        src = _segment_src(str(sid)) if sid else None
        if src:
            referenced_srcs.add(src)

    for src in sorted(referenced_srcs):
        candidates = _src_to_html_candidates(src)
        found = False
        for html_name in candidates:
            for rdir in rendered_dirs:
                if (rdir / html_name).exists():
                    found_htmls.append(str(rdir / html_name))
                    found = True
                    break
            if found:
                break
        if not found:
            errors.append(
                f"[sm] Transcript HTML not found for source '{src}'. "
                f"Tried: {', '.join(candidates)} in {rendered_dirs}"
            )
    return errors, found_htmls


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
    framework_md_root: Path,
    jurisdiction: str,
) -> tuple[list[str], list[str]]:
    """Check referenced framework MD files exist."""
    errors: list[str] = []
    found_mds: list[str] = []
    if not contract_path.exists():
        return errors, found_mds

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    md_map = FRAMEWORK_MD_MAP.get(jurisdiction, {})
    md_root = framework_md_root / jurisdiction

    codes = _extract_framework_codes(contract, jurisdiction)
    if not codes:
        errors.append("[contract] Could not extract any framework codes from legal_basis")
        return errors, found_mds

    for code in sorted(codes):
        md_name = md_map.get(code)
        if not md_name:
            errors.append(f"[contract] Framework '{code}' has no MD mapping for {jurisdiction}")
            continue
        target = md_root / md_name
        if target.exists():
            found_mds.append(str(target))
        else:
            errors.append(f"[contract] Framework MD missing: {target}")
    return errors, found_mds


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
    rendered_roots: list[Path],
    framework_md_root: Path,
    jurisdiction: str,
    ids: list[str],
    check_services_flag: bool = True,
) -> int:
    """Run all pre-flight checks. Returns exit code."""
    all_errors: list[str] = []
    all_ok: list[str] = []

    for vid in ids:
        # 1. Source data
        errs = check_source_data(source_root, vid)
        if not errs:
            all_ok.append(f"[{vid}] Source data: contract.json + segments_manifest.json OK")
        all_errors.extend(errs)

        sm_path = source_root / vid / "segments_manifest.json"
        contract_path = source_root / vid / "contract.json"

        # 2. Transcript HTMLs
        t_errs, t_found = check_transcripts(sm_path, rendered_roots)
        if not t_errs:
            all_ok.append(f"[{vid}] Transcript HTMLs: {len(t_found)} found")
        all_errors.extend(t_errs)

        # 3. Framework MD
        f_errs, f_found = check_framework_md(contract_path, framework_md_root, jurisdiction)
        if not f_errs:
            all_ok.append(f"[{vid}] Framework MD: {len(f_found)} found")
        all_errors.extend(f_errs)

    # 4. Services
    if check_services_flag:
        s_errs, s_ok = check_services()
        all_errors.extend(s_errs)
        all_ok.extend(s_ok)

    # Report
    print(f"Pre-flight validation for {len(ids)} violation(s) in {jurisdiction}")
    print(f"  Source:        {source_root}")
    print(f"  Rendered:      {rendered_roots}")
    print(f"  Framework MD:  {framework_md_root}")
    print()

    if all_errors:
        print(f"FAILURES ({len(all_errors)}):")
        for e in all_errors:
            print(f"  ✗ {e}")
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
    p.add_argument("--rendered", type=Path, nargs="+", default=[DEFAULT_RENDERED])
    p.add_argument("--framework-md-root", type=Path, default=DEFAULT_FRAMEWORK_MD_ROOT)
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

    # Expand rendered roots: if a root contains numbered subdirs (I-001, I-002),
    # include all of them for transcript discovery.
    expanded_rendered: list[Path] = []
    for r in args.rendered:
        if r.is_dir():
            sub = sorted(d for d in r.iterdir() if d.is_dir())
            if sub:
                expanded_rendered.extend(sub)
            else:
                expanded_rendered.append(r)
        else:
            expanded_rendered.append(r)

    return validate(
        source_root=args.source,
        rendered_roots=expanded_rendered,
        framework_md_root=args.framework_md_root,
        jurisdiction=args.jurisdiction,
        ids=ids,
        check_services_flag=not args.no_services,
    )


if __name__ == "__main__":
    raise SystemExit(main())
