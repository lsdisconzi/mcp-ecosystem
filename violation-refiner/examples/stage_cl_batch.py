"""Stage CL-XXX legacy bundles for refine_batch.py.

For each CL-XXX folder under --source, this script materializes a
self-contained bundle under --out/CL-XXX/ with the layout refine_batch.py
expects:

    <out>/CL-XXX/
        CL-XXX.json            <- canonical Violation JSON (anchorable)
        contract.json          <- copy of the legacy contract (read by validators)
        Transcripts/           <- symlinks to the timeline_aeropuerto_STG_*.html
                                  files referenced by this violation
        Legal framework/       <- symlink to CHIPENCOD_CP.md

The canonical CL-XXX.json carries the minimum fields needed for
refine_batch.py's _normalize() to anchor segments and articles:
  - facts.segments[]: just {segment_id, role_in_argument} pairs harvested
    from segments_manifest.json (refine_batch resolves verbatim text and
    audio offsets from the HTML transcript)
  - legal_basis.frameworks[].articles[]: built from contract.json's
    legal_basis (single article) wrapped in the schema _normalize expects
  - incident, cross_references: copied through

Usage:
  python3 examples/stage_cl_batch.py --ids CL-001 CL-002 CL-003 CL-004 \\
      CL-005 CL-006 CL-007 CL-008 CL-009 CL-010

Pre-requisites:
- The CL-XXX source folders under --source, each with contract.json and segments_manifest.json. These are the legacy bundles exported from the
  Airtable base, with minimal manual cleanup (mostly around the legal_basis shape, which is quite inconsistent across violations).
- The rendered transcript HTML files under --rendered, named timeline_aeropuerto_STG_*.html or timeline_latam_STG_*.html as per the _src_to_html() mapping in this script.
- The framework markdown file (e.g. CHIPENCOD_CP.md) under --framework-md. This is the same file for all violations, so we just symlink it into each bundle.

The script outputs a JSON report with the staging results for each violation, including any missing referenced files. The canonical CL-XXX.json files it produces are ready for refine_batch.py's _normalize() to process and anchor segments and articles.

Example output:
{
  "out_root": "build/cl_batch",
  "results": [
    {
      "violation_id": "CL-001",
      "ok": true,
      "segments_count": 5,
      "articles_count": 1,
      "frameworks": ["CHIPENCOD"],
      "transcript_sources": ["STG-1", "STG-2"],
      "missing_html": [],
      "bundle": "build/cl_batch/CL-001"
    },
    {
      "violation_id": "CL-002",
      "ok": false,
      "error": "missing contract.json"      
    },
    ...
    ]
    }

Notes:
- The script is designed to be idempotent; you can run it multiple times and it will overwrite the bundles under --out without issue.
- The canonicalization logic in _build_canonical() is based on the specific shapes observed in the legacy contract.json files. It may need adjustments if there are significant variations in the source data.
- The segment_id to HTML mapping in _src_to_html() is based on the observed naming patterns. Adjust as needed if there are variations.  
- The script focuses on staging the data for refine_batch.py; it does not perform any validation or normalization beyond structuring the canonical CL-XXX.json as expected by refine_batch.py's _normalize().


"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Iterable


DEFAULT_SOURCE = Path(
    "/Users/leandrodisconzi/work/business/OliviaLegal/cases/VIOLATIONS/by_id"
)
DEFAULT_RENDERED = Path(
    "/Users/leandrodisconzi/work/business/OliviaLegal/cases/INCIDENTS/"
    "INCIDENT_2024-07-05/transcripts/rendered"
)
DEFAULT_FRAMEWORK_MD_ROOT = Path(
    "/Users/leandrodisconzi/work/business/OliviaLegal/cases/LEGAL_FRAMEWORK/source_laws/law_md"
)
DEFAULT_OUT = Path("build/cl_batch")

# Per-jurisdiction map: framework_code (as it appears in article_id 'CL.CODE.…')
# -> markdown filename under <framework-md-root>/<jurisdiction>/. The symlink
# created inside each bundle's 'Legal framework/' is named '<CODE>.md' so that
# refine_batch.py's md.stem.split('_')[0].upper() resolves to CODE.
FRAMEWORK_MD_MAP: dict[str, dict[str, str]] = {
    "CL": {
        "CHIPENCOD":  "CHIPENCOD_CP.md",
        "CPCL":       "CodigoPenal.md",
        "CP":         "CHIPENCOD_CP.md",   # alias used by sonnet4/opus47 outputs
        "CONST":      "Constitucion.md",
        "CPR":        "Constitucion.md",   # "Constitucion Politica de la Republica"
        "DAN17":      "DAN17_DGAC.md",
        "L18575":     "DFL1_19653_L18575.md",
        "DFL1":       "DFL1_19653_L18575.md",
        "DSO":        "DGAC_DSO.md",
        "IVAAF":      "DGAC_IVAAF.md",
        "DGAC_IVAAF": "DGAC_IVAAF.md",
        "PREVAC":     "DGAC_PREVAC.md",
        "DGAC_PREVAC":"DGAC_PREVAC.md",
        "DTO2421":    "DTO2421_CGR.md",
        "L16752":     "L16752_DGAC.md",
        "CACH":       "L18916_CACH.md",
        "L18916":     "L18916_CACH.md",
        "LPDC":       "L19496_LPDC.md",
        "LPC":        "L19496_LPDC.md",    # alias frequently emitted by models
        "L19496":     "L19496_LPDC.md",
        "L20285":     "L20285_Transparencia.md",
        "INDH":       "L20405_INDH.md",
        "L20405":     "L20405_INDH.md",
        "L20880":     "L20880_Probidad.md",
        "R218":       "R218_JAC_DerechosPasajeros.md",
        # Frameworks newly bundled (see steps below). These keys MUST point at
        # files that exist on disk before staging will pick them up; the
        # entries are added here so stage_cl_batch wires up the symlink.
        "CC":         "CC_CodigoCivil.md",
        "CCCL":       "CC_CodigoCivil.md",
        "L19628":     "L19628_LPDP.md",
        "LPDP":       "L19628_LPDP.md",
        "DS113":      "DS113_RegistroEvidenciaIncidentes.md",
    },
    "BR": {
        "CBA":     "L7565_CBA.md",
        "L7565":   "L7565_CBA.md",
        "CDC":     "L8078_CDC.md",
        "L8078":   "L8078_CDC.md",
        "CC":      "L10406_CC.md",
        "L10406":  "L10406_CC.md",
        "CPB":     "DL2848_CP.md",
        "DL2848":  "DL2848_CP.md",
        "CF88":    "CF88.md",
        "CONST":   "CF88.md",
        "L9784":   "L9784.md",
        "L7716":   "L7716_RacialCrime.md",
        "L12527":  "L12527_LAI.md",
        "LAI":     "L12527_LAI.md",
        "L13460":  "L13460_UsuarioServicoPublico.md",
        "L8429":   "L8429_Improbidade.md",
        "L12846":  "L12846_Anticorrupcao.md",
        "L12813":  "L12813_ConflitoInteresses.md",
        "L8906":   "L8906_OAB.md",
        "OAB":     "CodEtica_OAB.md",
        "D11129":  "D11129_PNDH3.md",
        "D2181":   "D2181_SNDC.md",
        "D7203":   "D7203_Nepotismo.md",
        "D7724":   "D7724_LAI_Regulamento.md",
        "R400":    "R400_ANAC.md",
        "ANAC":    "R400_ANAC.md",
        "ABEAR":   "ABEAR_Code.md",
    },
    "INT": {
        "ACHR":    "ACHR_1969.md",
        "CHICAGO": "Chicago_1944.md",
        "HAGUE":   "Hague_1980.md",
        "IATA":    "IATA_GC.md",
        "IATA_GC": "IATA_GC.md",
        "AN6":     "ICAO_Annex6.md",
        "AN6I":    "ICAO_Annex6.md",
        "AN9":     "ICAO_Annex9.md",
        "AN10":    "ICAO_Annex10.md",
        "AN11":    "ICAO_Annex11.md",
        "AN13":    "ICAO_Annex13.md",
        "AN14":    "ICAO_Annex14.md",
        "AN17":    "ICAO_Annex17.md",
        "AN18":    "ICAO_Annex18.md",
        "DOC4444": "ICAO_DOC4444.md",
        "DOC8168": "ICAO_DOC8168.md",
        "DOC9284": "ICAO_DOC9284.md",
        "ILC_ARSIWA": "ILC_ARSIWA.md",
        "MC99":    "MC99_1999.md",
        "UNCRC":   "UNCRC_1989.md",
        "UNGCP":   "UNGCP.md",
        "VCCR":    "VCCR_1963.md",
        "VCLT":    "VCLT_1969.md",
    },
}


def _src_to_html_candidates(src_id: str) -> list[str]:
    """Return candidate HTML filenames for a source ID, trying multiple naming
    conventions (macOS developer machine and server).

    STG-7 -> ['timeline_aeropuerto_STG_7.html',
              'timeline_aeropuerto_arturo_merino_benitez_7.html']
    LATAM-2 -> ['timeline_latam_STG_2.html', 'timeline_latam_stg_2.html']
    """
    candidates: list[str] = []
    if src_id.startswith("LATAM-"):
        n = src_id.split("-", 1)[1]
        candidates.append(f"timeline_latam_STG_{n}.html")   # macOS convention
        candidates.append(f"timeline_latam_stg_{n}.html")   # server convention
    else:
        candidates.append(f"timeline_aeropuerto_{src_id.replace('-', '_')}.html")  # macOS
        n = src_id.split("-", 1)[1] if "-" in src_id else src_id
        candidates.append(f"timeline_aeropuerto_arturo_merino_benitez_{n}.html")   # server
    return candidates


def _resolve_html(src_id: str, rendered_dir: Path) -> str | None:
    """Return the first candidate filename that exists in rendered_dir, or None."""
    for html_name in _src_to_html_candidates(src_id):
        if (rendered_dir / html_name).exists():
            return html_name
    return None


def _segment_src(seg_id: str) -> str | None:
    if "." not in seg_id:
        return None
    return seg_id.split(".", 1)[0]


def _expand_segment_id(raw: str) -> list[str]:
    """Expand a single manifest entry into one-or-more canonical segment ids.

    The legacy upstream manifests occasionally encode a *span* of consecutive
    segments as a range id, e.g. ``STG-7.seg-44-48`` (meaning seg-44, seg-45,
    seg-46, seg-47, seg-48). The HtmlTranscriptSource parser only knows
    discrete ``seg-N`` ids, so V01 segment_resolution flags every range as
    unresolved. This helper expands ranges deterministically so downstream
    code never has to know the convention existed.

    Inputs that are already single ids (``STG-7.seg-44``) pass through
    unchanged. Inputs without a ``.`` separator also pass through (defensive).
    """
    if "." not in raw:
        return [raw]
    prefix, local = raw.split(".", 1)
    # Match ``seg-<start>-<end>`` where both ends are integers and end >= start.
    m = re.match(r"^seg-(\d+)-(\d+)$", local.strip())
    if not m:
        return [raw]
    start, end = int(m.group(1)), int(m.group(2))
    if end < start:
        return [raw]  # malformed; leave for V01 to surface as unresolved
    # Defensive upper bound: refuse to expand spans larger than 50 segments to
    # avoid runaway manifests. Real LA8159 ranges are tight (2-5 segments).
    if end - start > 50:
        return [raw]
    return [f"{prefix}.seg-{n}" for n in range(start, end + 1)]


def _build_canonical(
    contract: dict,
    segments_manifest: dict,
    jurisdiction: str,
) -> dict:
    violation_id = contract.get("violation_number") or contract.get("violation_id")
    title = (contract.get("title") or violation_id or "").strip()
    severity = (contract.get("severity") or "MEDIUM").upper()

    # Incident -------------------------------------------------------------
    ts_display = contract.get("incident_timestamp_display") or "2024-07-05"
    case_raw = contract.get("case")
    case = case_raw if isinstance(case_raw, dict) else {}
    inc_raw = contract.get("incident") if isinstance(contract.get("incident"), dict) else {}
    incident = {
        "date": inc_raw.get("date") or ts_display,
        "location": inc_raw.get("location") or "Santiago Airport (SCL), Chile",
        "flight": inc_raw.get("flight") or "LA8159",
        "operator": inc_raw.get("operator") or "LATAM Airlines",
        "clock_time_estimate": inc_raw.get("clock_time_estimate") or contract.get("incident_timestamp"),
    }
    # Preserve optional clock_time_confidence if the contract supplies one.
    if inc_raw.get("clock_time_confidence"):
        incident["clock_time_confidence"] = inc_raw["clock_time_confidence"]
    _ = case  # case carries id/name; reserved for future expansion

    # Segments -------------------------------------------------------------
    # Range ids like ``STG-7.seg-44-48`` are expanded to the underlying
    # discrete segments so V01 segment_resolution can match against the HTML
    # source. De-dup while preserving manifest order.
    raw_ids: list[str] = []
    for s in segments_manifest.get("segments") or []:
        if isinstance(s, str):
            raw_ids.append(s)
        elif isinstance(s, dict):
            sid = s.get("segment_id") or s.get("id")
            if sid:
                raw_ids.append(str(sid))
    seg_ids: list[str] = []
    _seen: set[str] = set()
    for raw in raw_ids:
        for expanded in _expand_segment_id(raw):
            if expanded not in _seen:
                _seen.add(expanded)
                seg_ids.append(expanded)
    canonical_segments = [
        {"segment_id": sid, "role_in_argument": "fact"} for sid in seg_ids
    ]

    # Legal basis ----------------------------------------------------------
    # Three legacy shapes observed:
    #   (a) dict with article_id at root  -> single article
    #   (b) list of article dicts         -> many articles, single framework
    #   (c) dict with primary_jurisdiction + frameworks[].articles[]
    lb_raw = contract.get("legal_basis")
    frameworks_out: list[dict] = []

    def _infer_subsections(excerpt: str) -> list[str]:
        """Pull numeral hints like '8.°' / 'N° 8' / 'inciso 2' out of a legacy
        excerpt so the canonical bundle carries the specific subsection the
        contract intended. Returns an empty list when no hint is detectable."""
        import re as _re
        hits: list[str] = []
        for m in _re.finditer(r"(?<!\d)(\d{1,2})\s*\.?\s*(?:°|º)", excerpt or ""):
            hits.append(m.group(1))
        for m in _re.finditer(r"N\s*[°º]\s*(\d{1,2})", excerpt or "", flags=_re.IGNORECASE):
            hits.append(m.group(1))
        # Letras like 'letra b)' or 'b)'
        for m in _re.finditer(r"letra\s+([a-z])\b", excerpt or "", flags=_re.IGNORECASE):
            hits.append(m.group(1).lower())
        # Deduplicate while preserving order.
        seen: set[str] = set()
        out: list[str] = []
        for h in hits:
            if h not in seen:
                seen.add(h)
                out.append(h)
        return out

    def _coerce_article(a: dict, default_fw_code: str) -> dict:
        article_id = str(a.get("article_id") or "").strip()
        excerpt = (a.get("article_text") or a.get("excerpt") or "").strip()
        rationale = (a.get("applicability_rationale") or a.get("nexus") or "").strip()
        subs_raw = a.get("subsections_invoked")
        if isinstance(subs_raw, list):
            subsections = [str(x).strip() for x in subs_raw if str(x).strip()]
        else:
            subsections = _infer_subsections(excerpt)
        return {
            "article_id": article_id,
            "article_name": a.get("article_name") or article_id,
            "article_text": excerpt,
            "applicability_rationale": rationale,
            "duty_bearer": a.get("duty_bearer") or "state",
            "norm_type": a.get("norm_type") or "definition",
            "applicability": a.get("applicability") or "primary",
            "subsections_invoked": subsections,
        }

    def _fw_from_article(article_id: str, fallback: str = "") -> str:
        parts = article_id.split(".")
        return parts[1] if len(parts) >= 2 and parts[0] == jurisdiction else (fallback or jurisdiction)

    if isinstance(lb_raw, dict) and lb_raw.get("frameworks"):
        # Shape (c)
        for fw in lb_raw.get("frameworks") or []:
            fw_code = str(fw.get("framework_code") or "CHIPENCOD").strip()
            fw_name = fw.get("framework_name") or fw_code
            arts = [
                _coerce_article(a, fw_code)
                for a in (fw.get("articles") or [])
                if isinstance(a, dict) and a.get("article_id")
            ]
            frameworks_out.append({
                "framework_code": fw_code,
                "framework_name": fw_name,
                "articles": arts,
            })
    elif isinstance(lb_raw, list):
        # Shape (b) — flat list; group by derived framework code
        grouped: dict[str, list[dict]] = {}
        for a in lb_raw:
            if not (isinstance(a, dict) and a.get("article_id")):
                continue
            fw_code = _fw_from_article(str(a["article_id"]))
            grouped.setdefault(fw_code, []).append(_coerce_article(a, fw_code))
        for fw_code, arts in grouped.items():
            frameworks_out.append({
                "framework_code": fw_code,
                "framework_name": fw_code,
                "articles": arts,
            })
    elif isinstance(lb_raw, dict) and lb_raw.get("article_id"):
        # Shape (a)
        fw_code = _fw_from_article(str(lb_raw["article_id"]))
        frameworks_out.append({
            "framework_code": fw_code,
            "framework_name": fw_code,
            "articles": [_coerce_article(lb_raw, fw_code)],
        })

    legal_basis_canonical = {"frameworks": frameworks_out}

    canonical: dict = {
        "schema_version": "3.0",
        "violation_id": violation_id,
        "title": title,
        "severity": severity if severity in {"LOW", "MEDIUM", "HIGH", "CRITICAL"} else "HIGH",
        "incident": incident,
        "facts": {
            "allegation_summary": contract.get("allegation_summary"),
            "segments": canonical_segments,
        },
        "legal_basis": legal_basis_canonical,
        "cross_references": contract.get("cross_references") or [],
    }
    return canonical


def _ensure_symlink(target: Path, link: Path) -> None:
    if link.exists() or link.is_symlink():
        link.unlink()
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)


def _hydrate_verbatim_bodies(canonical: dict, fw_dir: Path) -> list[str]:
    """For each article in the canonical violation, look up the verbatim body
    in the corresponding framework MD (already symlinked into ``fw_dir`` as
    ``<CODE>.md``). When found and the legacy paraphrase is not already a
    substring of the body, replace ``article_text`` with the verbatim body and
    move the paraphrase into ``applicability_rationale`` so the
    `excerpt in body` invariant in refine_batch.py can promote the article to
    ``established`` instead of demoting it to ``candidate``.

    Returns a list of human-readable notes describing what changed."""
    from violation_pack.sources import MarkdownFrameworkSource  # local import

    notes: list[str] = []
    for fw in canonical["legal_basis"]["frameworks"]:
        code = fw["framework_code"]
        md_path = fw_dir / f"{code}.md"
        if not md_path.exists():
            continue
        try:
            reader = MarkdownFrameworkSource(md_path, code, f"Legal framework/{code}.md")
        except Exception as exc:
            notes.append(f"{code}: MD parse failed ({exc})")
            continue
        for art in fw.get("articles") or []:
            article_id = art.get("article_id") or ""
            # Strip the leading "<JUR>.<CODE>.Art." prefix to get the
            # identifier (e.g. '193', '19.7', '3.b', '133').
            ident = article_id.rsplit(".Art.", 1)[-1] if ".Art." in article_id else article_id
            body = reader.get_article_body(ident)
            if body is None:
                # Try progressively trimming sub-tokens from the right.
                tokens = ident.split(".")
                for n in range(len(tokens) - 1, 0, -1):
                    body = reader.get_article_body(".".join(tokens[:n]))
                    if body is not None:
                        break
            if body is None:
                continue
            paraphrase = (art.get("article_text") or "").strip()
            if paraphrase and paraphrase in body:
                continue  # already verbatim
            art["article_text"] = body
            if paraphrase:
                existing = (art.get("applicability_rationale") or "").strip()
                combined = (
                    f"{existing} | legacy paraphrase: {paraphrase}"
                    if existing else f"legacy paraphrase: {paraphrase}"
                )
                art["applicability_rationale"] = combined
            notes.append(f"{article_id}: hydrated verbatim body ({len(body)} chars)")
    return notes


def stage_one(
    source_dir: Path,
    out_dir: Path,
    rendered_dir: Path,
    framework_md_root: Path,
    jurisdiction: str,
) -> dict:
    cid = source_dir.name
    contract_path = source_dir / "contract.json"
    sm_path = source_dir / "segments_manifest.json"
    if not contract_path.exists():
        return {"violation_id": cid, "ok": False, "error": "missing contract.json"}
    if not sm_path.exists():
        return {"violation_id": cid, "ok": False, "error": "missing segments_manifest.json"}

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    sm = json.loads(sm_path.read_text(encoding="utf-8"))

    bundle = out_dir / cid
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "Transcripts").mkdir(exist_ok=True)
    fw_dir = bundle / "Legal framework"
    fw_dir.mkdir(exist_ok=True)

    # Symlink the referenced transcript HTMLs ------------------------------
    referenced_srcs: set[str] = set()
    for s in sm.get("segments") or []:
        sid = s if isinstance(s, str) else (s.get("segment_id") or s.get("id"))
        src = _segment_src(str(sid)) if sid else None
        if src:
            referenced_srcs.add(src)

    missing_html: list[str] = []
    for src in sorted(referenced_srcs):
        html_name = _resolve_html(src, rendered_dir)
        if html_name is None:
            missing_html.append(_src_to_html_candidates(src)[0])
            continue
        _ensure_symlink(rendered_dir / html_name, bundle / "Transcripts" / html_name)

    # Build canonical to learn which framework codes are referenced --------
    canonical = _build_canonical(contract, sm, jurisdiction)
    referenced_fws: list[str] = [
        fw["framework_code"] for fw in canonical["legal_basis"]["frameworks"]
    ]

    # Symlink each referenced framework MD as '<CODE>.md' so that
    # refine_batch.py's md.stem.split('_')[0].upper() yields CODE.
    md_map = FRAMEWORK_MD_MAP.get(jurisdiction, {})
    md_root = framework_md_root / jurisdiction
    missing_md: list[str] = []
    linked_md: list[str] = []
    for code in referenced_fws:
        md_name = md_map.get(code)
        if not md_name:
            missing_md.append(f"{code}:no-mapping")
            continue
        target = md_root / md_name
        if not target.exists():
            missing_md.append(f"{code}:missing-{md_name}")
            continue
        _ensure_symlink(target, fw_dir / f"{code}.md")
        linked_md.append(f"{code}->{md_name}")

    # Hydrate verbatim article bodies from MD ------------------------------
    # The contract's article_text is a paraphrase; refine_batch.py only
    # promotes articles to "established" when the original excerpt is a
    # substring of the body returned by the source. So we pull the verbatim
    # body from each linked MD and store the paraphrase in
    # applicability_rationale.
    hydration_notes = _hydrate_verbatim_bodies(canonical, fw_dir)

    # Out-of-range segment diagnostic --------------------------------------
    # Surface segment ids that reference a transcript HTML but point past
    # the last rendered ``seg-N``. These cannot be auto-corrected without
    # ground-truth audio mapping, but listing them at staging time makes
    # the upstream manifest bug visible long before V01 runs.
    unresolved_segments: list[str] = []
    try:
        from violation_pack.sources import HtmlTranscriptSource  # local import
        src_caches: dict[str, set[str]] = {}
        for sid in (s["segment_id"] for s in canonical["facts"]["segments"]):
            if "." not in sid:
                continue
            src, local = sid.split(".", 1)
            if src not in src_caches:
                html_name = _resolve_html(src, bundle / "Transcripts")
                html_path = (bundle / "Transcripts" / html_name) if html_name else None
                if html_path is None or not html_path.exists():
                    src_caches[src] = set()
                else:
                    try:
                        ts = HtmlTranscriptSource(html_path, src, f"Transcripts/{html_name}")
                        src_caches[src] = {seg["segment_id"] for seg in ts.all_segments()}
                    except Exception:
                        src_caches[src] = set()
            if src_caches[src] and local not in src_caches[src]:
                unresolved_segments.append(sid)
    except Exception:
        # Diagnostic is best-effort; never block staging.
        unresolved_segments = []

    # Copy contract.json (validators read it for cross-checks) -------------
    shutil.copyfile(contract_path, bundle / "contract.json")

    # Write canonical CL-XXX.json ------------------------------------------
    (bundle / f"{cid}.json").write_text(
        json.dumps(canonical, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "violation_id": cid,
        "ok": True,
        "segments_count": len(canonical["facts"]["segments"]),
        "articles_count": sum(
            len(fw.get("articles") or [])
            for fw in canonical["legal_basis"]["frameworks"]
        ),
        "frameworks": [
            fw["framework_code"] for fw in canonical["legal_basis"]["frameworks"]
        ],
        "linked_md": linked_md,
        "missing_md": missing_md,
        "hydrated": hydration_notes,
        "transcript_sources": sorted(referenced_srcs),
        "missing_html": missing_html,
        "unresolved_segments": unresolved_segments,
        "bundle": str(bundle),
    }


def run(
    source_root: Path,
    out_root: Path,
    rendered_dir: Path,
    framework_md_root: Path,
    jurisdiction: str,
    ids: Iterable[str],
) -> int:
    out_root.mkdir(parents=True, exist_ok=True)
    results = []
    for cid in ids:
        src = source_root / cid
        if not src.is_dir():
            results.append({"violation_id": cid, "ok": False, "error": "source not found"})
            continue
        results.append(stage_one(src, out_root, rendered_dir, framework_md_root, jurisdiction))

    print(json.dumps({"out_root": str(out_root), "results": results}, indent=2, ensure_ascii=False))
    failed = [r for r in results if not r.get("ok")]
    return 0 if not failed else 1


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stage legacy violation bundles for refine_batch")
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--rendered", type=Path, default=DEFAULT_RENDERED)
    p.add_argument("--framework-md-root", type=Path, default=DEFAULT_FRAMEWORK_MD_ROOT,
                   help="Root containing <jurisdiction>/<framework>.md files")
    p.add_argument("--jurisdiction", choices=sorted(FRAMEWORK_MD_MAP.keys()), default="CL")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--ids", nargs="+", required=True, help="e.g. CL-001 CL-002 ...")
    return p.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args.source, args.out, args.rendered, args.framework_md_root, args.jurisdiction, args.ids)


if __name__ == "__main__":
    raise SystemExit(main())
