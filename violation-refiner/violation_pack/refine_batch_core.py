"""Core batch refiner for CL violation folders — library code.

Loads each violation bundle (legacy or canonical schema), anchors segments
against the real transcript HTML, verifies article excerpts against the real
framework cache, re-derives confidence, runs the full validation pipeline, and
writes normalized outputs in place.

This module is the shared library; the CLI wrapper lives in
``examples/refine_batch.py``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

from ._utils import sha256_text
from .confidence import attach_confidence
from .models import (
    CachedArticle,
    CandidateArticle,
    CrossReference,
    EvidenceSegment,
    FrameworkCache,
    Incident,
    OpenQuestion,
    Violation,
)
from .pack import build_manifest, zip_bundle
from .sources import HtmlTranscriptSource, MarkdownFrameworkSource, TranscriptSource
from .sources_json import JsonTranscriptSchemaError, JsonTranscriptSource
from .validation import run_pipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TRANSCRIPT_SOURCE_ID = re.compile(r"timeline_aeropuerto_(STG_\d+)\.html", re.IGNORECASE)
# Server naming: timeline_aeropuerto_arturo_merino_benitez_7.html → STG-7
_TRANSCRIPT_SOURCE_ID_SERVER = re.compile(
    r"timeline_aeropuerto_arturo_merino_benitez_(\d+)\.html", re.IGNORECASE
)
_TRANSCRIPT_SOURCE_ID_LATAM = re.compile(r"timeline_latam_STG_(\d+)\.html", re.IGNORECASE)
_VALID_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
_VALID_NORM_TYPES = {
    "prohibition", "penalty", "right", "liability", "definition", "exemption",
}
_VALID_APPLICABILITY = {"direct", "indirect_predicate", "supporting"}
_VALID_PRIORITY = {"low", "medium", "high", "critical"}


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _bundle_local_id(name: str) -> str:
    """The part of a bundle name after the jurisdiction prefix.

    ``CL-001`` -> ``001``, ``BR-030`` -> ``030``, ``INT-001`` -> ``001``.
    Splitting on the last ``-`` instead of slicing a fixed width keeps
    two- and three-letter jurisdictions working: ``name[3:]`` turns
    ``INT-001`` into ``-001`` and silently drops it.
    """
    return name.rsplit("-", 1)[-1]


def _iter_violation_dirs(root: Path) -> list[Path]:
    """Bundle directories, discovered structurally rather than by prefix.

    A violation bundle is any directory carrying its own ``<dirname>.json``
    payload. The previous ``startswith("CL-")`` filter mirrored a jurisdiction
    list that drifts silently: the BR and INT bundles produced by
    ``vault_to_bundle.py`` were invisible to the validator and skipped with no
    warning at all.
    """
    dirs = [
        p for p in root.iterdir()
        if p.is_dir() and _find_violation_json(p) is not None
    ]
    return sorted(dirs, key=lambda p: p.name)


def _find_violation_json(bundle_dir: Path) -> Path | None:
    named = bundle_dir / f"{bundle_dir.name}.json"
    if named.exists():
        return named
    candidates = [
        p for p in bundle_dir.glob("*.json")
        if p.name.lower() not in {"contract.json"}
        and not p.name.endswith(".bak")
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _parse_time_seconds(value: str | float | int | None) -> float:
    """Parse '12.80s', '15:16', 12.8, etc into seconds. Returns 0.0 on failure."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lower()
    if s.endswith("s"):
        s = s[:-1].strip()
    if ":" in s:
        parts = s.split(":")
        try:
            if len(parts) == 2:
                return float(parts[0]) * 60.0 + float(parts[1])
            if len(parts) == 3:
                return float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2])
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# Fixture discovery
# ---------------------------------------------------------------------------

def _discover_transcripts(bundle_dir: Path) -> dict[str, TranscriptSource]:
    """Discover transcript sources in a bundle directory.

    Two forms are supported and may coexist:

    ``*.json``
        Canonical transcript documents. Keyed by ``transcript_id``, which makes
        the composed segment ids identical to ``reviewed_transcripts``.
    ``*.html``
        Vendored renders. The source id is inferred from the legacy filenames
        because the render itself carries no identifier.
    """
    transcripts: dict[str, TranscriptSource] = {}
    tdir = bundle_dir / "Transcripts"
    if not tdir.is_dir():
        return transcripts
    for json_path in sorted(tdir.glob("*.json")):
        try:
            source = JsonTranscriptSource(
                path=json_path,
                bundle_uri=f"Transcripts/{json_path.name}",
                speaker_index_path=_speaker_index_path(bundle_dir),
            )
        except JsonTranscriptSchemaError:
            continue
        transcripts[source.transcript_id] = source
    for html in sorted(tdir.glob("*.html")):
        m = _TRANSCRIPT_SOURCE_ID.search(html.name)
        if m:
            source_id = m.group(1).replace("_", "-")
        else:
            m_server = _TRANSCRIPT_SOURCE_ID_SERVER.search(html.name)
            if m_server:
                source_id = f"STG-{m_server.group(1)}"
            else:
                m_latam = _TRANSCRIPT_SOURCE_ID_LATAM.search(html.name)
                if m_latam:
                    source_id = f"LATAM-{m_latam.group(1)}"
                else:
                    source_id = html.stem
        transcripts[source_id] = HtmlTranscriptSource(
            path=html,
            source_id=source_id,
            bundle_uri=f"Transcripts/{html.name}",
        )
    return transcripts


def _speaker_index_path(bundle_dir: Path) -> Path | None:
    """Locate ``speaker_index.json`` for a bundle, if one ships with it."""
    for candidate in (bundle_dir / "speaker_index.json", bundle_dir.parent / "speaker_index.json"):
        if candidate.is_file():
            return candidate
    return None


def _discover_frameworks(bundle_dir: Path) -> dict[str, MarkdownFrameworkSource]:
    frameworks: dict[str, MarkdownFrameworkSource] = {}
    fdir = bundle_dir / "Legal framework"
    if not fdir.is_dir():
        return frameworks
    for md in sorted(fdir.glob("*.md")):
        code = md.stem.split("_")[0].upper()
        frameworks[code] = MarkdownFrameworkSource(
            path=md,
            framework_code=code,
            bundle_uri=f"Legal framework/{md.name}",
        )
    return frameworks


def _framework_for(
    framework_code: str,
    article_id: str,
    frameworks: dict[str, MarkdownFrameworkSource],
) -> MarkdownFrameworkSource | None:
    """Pick a framework reader matching the article. Legacy codes vary
    (CHIPENCOD vs CPCL both mean Codigo Penal de Chile), so we accept a
    direct match first and then fall back to any reader whose article body
    actually contains the article number."""
    if framework_code in frameworks:
        return frameworks[framework_code]
    art_num = article_id.rsplit(".Art.", 1)[-1].split(".")[0]
    for reader in frameworks.values():
        if reader.get_article_body(art_num) is not None:
            return reader
    if frameworks:
        return next(iter(frameworks.values()))
    return None


# ---------------------------------------------------------------------------
# Legacy schema normalizer with anchoring
# ---------------------------------------------------------------------------

def _normalize(
    data: dict,
    transcripts: dict[str, HtmlTranscriptSource],
    frameworks: dict[str, MarkdownFrameworkSource],
) -> tuple[Violation, list[str]]:
    """Convert legacy or canonical bundle JSON into a Violation, anchoring
    segments and article excerpts to the real source artifacts when possible.
    Returns (violation, notes)."""
    notes: list[str] = []

    violation_id = data.get("violation_id") or "UNKNOWN"
    title = (data.get("title") or violation_id).strip()
    severity = str(data.get("severity") or "MEDIUM").upper().strip()
    if severity not in _VALID_SEVERITIES:
        severity = "MEDIUM"

    incident_data = data.get("incident") or {}
    incident = Incident(
        date=str(incident_data.get("date") or "unknown"),
        location=str(incident_data.get("location") or "unknown"),
        flight=incident_data.get("flight"),
        operator=incident_data.get("operator"),
        clock_time_estimate=incident_data.get("clock_time_estimate"),
    )

    # Segments ---------------------------------------------------------------
    raw_segments = (data.get("facts") or {}).get("segments") or data.get("segments") or []
    anchored: list[EvidenceSegment] = []
    legacy_kept: list[EvidenceSegment] = []
    for seg in raw_segments:
        seg_id = str(seg.get("segment_id") or "").strip()
        if not seg_id or "." not in seg_id:
            notes.append(f"segment skipped (missing or unscoped id): {seg!r}")
            continue
        src_id, local_id = seg_id.split(".", 1)
        legacy_text = str(seg.get("text") or seg.get("verbatim_es") or "")
        translation = str(seg.get("translation_en") or "")

        reader = transcripts.get(src_id)
        parsed = reader.get_segment(local_id) if reader else None
        if reader and parsed:
            verbatim = parsed["verbatim"]
            if not str(verbatim).strip() and legacy_text.strip():
                # Some transcript fixtures have sparse/blank text on valid
                # segment IDs. Preserve prior bundle text instead of emitting
                # empty bilingual fields.
                verbatim = legacy_text
            anchored.append(
                EvidenceSegment(
                    segment_id=seg_id,
                    role_in_argument=str(seg.get("role_in_argument") or "legacy_fact"),
                    audio_offset_start=parsed["audio_offset_start"],
                    audio_offset_end=parsed["audio_offset_end"],
                    speaker=parsed["speaker"],
                    verbatim_es=verbatim,
                    verbatim_sha256=sha256_text(verbatim),
                    translation_en=translation or legacy_text or verbatim,
                    transcription_notes=seg.get("transcription_notes"),
                    source_uri=f"{reader.source_uri()}#{local_id}",
                    source_sha256=reader.source_sha256(),
                )
            )
            continue

        # Could not anchor — keep legacy as a non-resolving record so the
        # validator surfaces it. Audio offsets unknown.
        notes.append(f"segment {seg_id}: not present in transcript fixtures")
        legacy_kept.append(
            EvidenceSegment(
                segment_id=seg_id,
                role_in_argument=str(seg.get("role_in_argument") or "legacy_fact"),
                audio_offset_start=_parse_time_seconds(seg.get("timeStart")),
                audio_offset_end=_parse_time_seconds(seg.get("timeEnd")),
                speaker=str(seg.get("speaker") or "unknown"),
                verbatim_es=legacy_text,
                verbatim_sha256=sha256_text(legacy_text),
                translation_en=translation or legacy_text,
                transcription_notes=(
                    (seg.get("transcription_notes") or "")
                    + " | legacy-unanchored"
                ).strip(" |"),
                source_uri=f"legacy://{violation_id}/{seg_id}",
                source_sha256=sha256_text(seg_id),
            )
        )

    segments = anchored + legacy_kept

    # Articles & frameworks --------------------------------------------------
    legal_basis = data.get("legal_basis") or {}
    fw_blocks = legal_basis.get("frameworks") or []

    framework_caches: list[FrameworkCache] = []
    seen_caches: set[str] = set()
    established_articles: list[CachedArticle] = []
    candidate_articles: list[CandidateArticle] = []

    for fw in fw_blocks:
        fw_code = str(fw.get("framework_code") or "LEGACY").strip()
        reader = _framework_for(fw_code, "", frameworks)
        if reader is not None and fw_code not in seen_caches:
            framework_caches.append(
                FrameworkCache(
                    framework_code=fw_code,
                    framework_name=str(fw.get("framework_name") or fw_code),
                    cache_file=reader.cache_uri(),
                    cache_file_sha256=reader.cache_sha256(),
                    cache_self_reported_sha256=reader.declared_sha256(),
                    articles_cached=reader.articles_cached(),
                )
            )
            seen_caches.add(fw_code)

        for article in fw.get("articles") or []:
            article_id = str(article.get("article_id") or "").strip()
            if not article_id:
                continue
            excerpt = str(article.get("article_text") or "").strip()
            duty = str(article.get("duty_bearer") or "state").strip() or "state"
            norm_type = str(article.get("norm_type") or "definition").strip()
            if norm_type not in _VALID_NORM_TYPES:
                norm_type = "definition"
            applicability = str(article.get("applicability") or "supporting").strip()
            if applicability not in _VALID_APPLICABILITY:
                applicability = "supporting"
            rationale = str(
                article.get("applicability_rationale")
                or article.get("correction_note")
                or "legacy import"
            )

            art_reader = _framework_for(fw_code, article_id, frameworks)
            art_num = article_id.rsplit(".Art.", 1)[-1].split(".")[0]
            body = art_reader.get_article_body(art_num) if art_reader else None

            verified = bool(body and excerpt and excerpt in body)
            if verified:
                effective_code = art_reader.framework_code() if art_reader else fw_code
                established_articles.append(
                    CachedArticle(
                        article_id=article_id,
                        article_name=str(article.get("article_name") or article_id),
                        subsections_invoked=article.get("subsections_invoked") or [],
                        verbatim_excerpt=excerpt,
                        verbatim_excerpt_sha256=sha256_text(excerpt),
                        framework_code=effective_code,
                        framework_cache_status="verified_in_bundle",
                        duty_bearer=duty,
                        norm_type=norm_type,
                        applicability=applicability,
                        applicability_rationale=rationale,
                    )
                )
                # Make sure the framework reader is registered too.
                if art_reader and effective_code not in seen_caches:
                    framework_caches.append(
                        FrameworkCache(
                            framework_code=effective_code,
                            framework_name=str(fw.get("framework_name") or effective_code),
                            cache_file=art_reader.cache_uri(),
                            cache_file_sha256=art_reader.cache_sha256(),
                            cache_self_reported_sha256=art_reader.declared_sha256(),
                            articles_cached=art_reader.articles_cached(),
                        )
                    )
                    seen_caches.add(effective_code)
            else:
                reason = []
                if body is None:
                    reason.append("article body not in any cache")
                elif not excerpt:
                    reason.append("no excerpt supplied")
                else:
                    reason.append("excerpt not a substring of cache body")
                notes.append(f"article {article_id}: demoted to candidate ({'; '.join(reason)})")
                candidate_articles.append(
                    CandidateArticle(
                        candidate_article_id=article_id,
                        candidate_name=str(article.get("article_name") or article_id),
                        framework_cache_status="not_in_bundle",
                        verification_required=[
                            f"Fetch verbatim text for {article_id} and confirm excerpt",
                        ],
                        preliminary_view=excerpt[:240] if excerpt else None,
                        history_note=rationale[:512],
                    )
                )

    # Open questions ---------------------------------------------------------
    open_questions: list[OpenQuestion] = []
    for oq in data.get("open_questions") or []:
        priority = str(oq.get("priority") or "medium").lower()
        if priority not in _VALID_PRIORITY:
            priority = "medium"
        open_questions.append(
            OpenQuestion(
                id=str(oq.get("id") or "legacy-oq"),
                question=str(oq.get("question") or oq.get("detail") or oq.get("label") or "legacy question"),
                blocks_element=oq.get("blocks_element"),
                priority=priority,
                obtaining_method=oq.get("obtaining_method"),
            )
        )

    # Cross-references -------------------------------------------------------
    raw_refs = data.get("cross_references") or []
    seen_refs: set[str] = set()
    cross_refs: list[CrossReference] = []
    for ref in raw_refs:
        if isinstance(ref, dict):
            ref_id = str(ref.get("ref") or "").strip()
            relation = str(ref.get("relation") or "legacy_reference")
        else:
            ref_id = str(ref).strip()
            relation = "legacy_reference"
        if not ref_id or ref_id in seen_refs:
            continue
        seen_refs.add(ref_id)
        cross_refs.append(CrossReference(ref=ref_id, relation=relation))

    violation = Violation(
        violation_id=violation_id,
        title=title or violation_id,
        severity=severity,
        schema_version="3.0",
        incident=incident,
        segments=segments,
        framework_caches=framework_caches,
        established_articles=established_articles,
        candidate_articles=candidate_articles,
        open_questions=open_questions,
        cross_references=cross_refs,
    )
    return violation, notes


def _load_violation(
    path: Path,
    transcripts: dict[str, HtmlTranscriptSource],
    frameworks: dict[str, MarkdownFrameworkSource],
) -> tuple[Violation, list[str]]:
    # Prefer the original legacy bundle when a .bak snapshot exists, so
    # re-runs re-anchor against the source instead of inheriting a
    # previously-normalized (and possibly incomplete) Violation JSON.
    bak = path.with_suffix(path.suffix + ".bak")
    source_path = bak if bak.exists() else path
    raw_text = source_path.read_text(encoding="utf-8")
    try:
        return Violation.model_validate_json(raw_text), []
    except Exception:
        data = json.loads(raw_text)
        return _normalize(data, transcripts, frameworks)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _write_validation_markdown(bundle_dir: Path, violation_id: str, checks: list[dict], summary: dict) -> None:
    lines = [
        f"# Validation Report {violation_id}",
        "",
        f"Total: {summary['total']}  ",
        f"Pass: {summary['pass']}  ",
        f"Warn: {summary['warn']}  ",
        f"Fail: {summary['fail']}",
        "",
        "## Checks",
        "",
    ]
    for c in checks:
        lines.append(f"- **{c['check_id']} {c['name']}**: {c['status']} - {c['details']}")
    out = bundle_dir / "Validation" / "validation_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Per-bundle processing
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Per-bundle processing
# ---------------------------------------------------------------------------

def _reconcile_contract_after_enrichment(
    bundle_dir: Path, violation: Violation, contract: dict
) -> dict:
    """Rewrite the contract fields enrichment is allowed to change.

    ``vault_to_bundle`` writes the contract at bundle-creation time, from the
    vault's snapshot of the violation. Enrichment then re-derives confidence
    from the enriched element grid, and expands ``cross_references`` and
    ``open_questions``. V08 and V17 compare those fields between the bundle
    and the contract, so a stale contract is a guaranteed V08/V17 failure that
    no amount of enrichment quality can fix.

    Only the fields V08 and V17 actually compare are rewritten:

    - ``confidence`` — V08 compares ``.value``
    - ``established_article_ids`` — V08 compares the set
    - ``cross_references`` — V17 compares ref + relation
    - ``open_questions`` — V17 compares id, question, blocks_element, priority

    Everything else — ``legal_basis``, ``candidate_articles``, the incident
    metadata, the provenance block — is left as the vault converter wrote it,
    on purpose: those fields are the *record of what the vault said* and are
    not supposed to reflect enrichment. A future migration can widen this
    reconciler; today it stays minimal so the diff is auditable.

    A missing or unreadable ``contract.json`` is not an error: ``--inputs-only``
    runs skip the contract entirely, and a bundle whose contract was removed by
    hand should not fail the pipeline here. The reconciler is a fixup, not a
    gate.
    """
    # Update the in-memory contract (passed by caller) with the fields
    # enrichment is allowed to change, then persist to disk.
    if violation.confidence is not None:
        contract["confidence"] = json.loads(violation.confidence.model_dump_json())
    else:
        contract.pop("confidence", None)
    contract["established_article_ids"] = sorted(
        a.article_id for a in violation.established_articles
    )
    contract["cross_references"] = [
        {"ref": x.ref, "relation": x.relation} for x in violation.cross_references
    ]
    contract["open_questions"] = [
        {
            "id": q.id,
            "question": q.question,
            "blocks_element": q.blocks_element or "",
            "priority": q.priority,
        }
        for q in violation.open_questions
    ]
    contract_path = bundle_dir / "contract.json"
    if contract_path.exists():
        try:
            contract_path.write_text(
                json.dumps(contract, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except (OSError, TypeError):
            pass
    return contract


def _process_one(
    bundle_dir: Path,
    known_ids: set[str],
    write_backup: bool,
    zip_output: bool,
    enrich: bool = False,
    enrich_stages: list[str] | None = None,
    llm_override: dict | None = None,
    known_titles: dict[str, str] | None = None,
) -> tuple[bool, dict, list[str]]:
    vio_json_path = _find_violation_json(bundle_dir)
    if vio_json_path is None:
        return False, {"violation_id": bundle_dir.name, "error": "violation JSON not found"}, []

    transcripts = _discover_transcripts(bundle_dir)
    frameworks = _discover_frameworks(bundle_dir)

    try:
        v, notes = _load_violation(vio_json_path, transcripts, frameworks)
    except Exception as exc:
        return False, {"violation_id": bundle_dir.name, "error": f"parse failed: {exc}"}, []

    contract = _read_json(bundle_dir / "contract.json")
    v = attach_confidence(v)
    # Enrichment owns the nexus matrix. A bundle carries nexus rows from the
    # previous enrichment run (they are written into <VID>.json), and those
    # rows reference element_ids composed before the templates were wired in.
    # Upserting new rows alongside them leaves both, and V11/V21 correctly
    # reject the survivors. Clear the matrix here so the nexus stage
    # regenerates it from scratch. The vault's own nexus rows (if any) are
    # cleared too — enrichment is about to propose the same theory with
    # conformant element_ids, and keeping both would be a merge of two
    # proposals rather than a single coherent record.
    if enrich:
        v = v.model_copy(update={"nexus_matrix": []})

    enrich_info: dict | None = None
    if enrich:
        try:
            from .config import Settings
            from .enrich import ENRICHMENT_STAGES, enrich_violation
            s = Settings.from_env()
            client = s.llm_client(
                provider=(llm_override or {}).get("provider"),
                model=(llm_override or {}).get("model"),
                api_key=(llm_override or {}).get("api_key"),
                base_url=(llm_override or {}).get("base_url"),
            )
            selected_stages = list(enrich_stages or ENRICHMENT_STAGES)
            provider = getattr(client, "provider", "unknown")
            model = getattr(client, "model", "unknown")
            print(
                f"    enrich: provider={provider} model={model} "
                f"stages={','.join(selected_stages)}",
                flush=True,
            )
            for idx, stage in enumerate(selected_stages, start=1):
                print(f"    enrich [{idx}/{len(selected_stages)}]: {stage} ...", flush=True)
                v = enrich_violation(
                    v,
                    client=client,
                    frameworks=frameworks,
                    known_violation_ids=known_ids,
                    known_violation_titles=known_titles,
                    stages=[stage],
                )
                print(f"    enrich [{idx}/{len(selected_stages)}]: {stage} done", flush=True)
            enrich_info = {
                "stages": selected_stages,
                "ok": True,
            }
        except Exception as exc:
            notes.append(f"enrichment_failed: {exc}")
            enrich_info = {"ok": False, "error": str(exc)}

    # Reconcile the contract with the enriched violation BEFORE the pipeline
    # runs, so V08 and V17 evaluate the reconciled state. The reconciler
    # returns the updated dict; the pipeline must receive *that*, not the
    # pre-enrichment copy read at the top of this function.
    contract = _reconcile_contract_after_enrichment(bundle_dir, v, contract or {})

    report = run_pipeline(
        v,
        transcripts=transcripts,
        frameworks=frameworks,
        contract=contract,
        known_violation_ids=known_ids,
    )

    if write_backup:
        bak = vio_json_path.with_suffix(vio_json_path.suffix + ".bak")
        if not bak.exists():
            bak.write_text(vio_json_path.read_text(encoding="utf-8"), encoding="utf-8")

    vio_json_path.write_text(
        v.model_dump_json(indent=2, exclude_none=False), encoding="utf-8"
    )

    checks_path = bundle_dir / "Validation" / "checks.json"
    checks_path.parent.mkdir(parents=True, exist_ok=True)
    checks_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    _write_validation_markdown(
        bundle_dir,
        v.violation_id,
        [c.model_dump() for c in report.checks],
        report.summary,
    )

    build_manifest(bundle_dir, schema_version=v.schema_version)
    if zip_output:
        zip_bundle(bundle_dir, bundle_dir.parent / f"{bundle_dir.name}_refined_pack.zip")

    return True, {
        "violation_id": v.violation_id,
        "summary": report.summary,
        "confidence": v.confidence.value if v.confidence else None,
        "notes": notes,
    }, notes


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def _collect_known_ids(dirs: list[Path]) -> set[str]:
    """Union of folder names and every cross_ref string found across bundles."""
    ids: set[str] = {d.name for d in dirs}
    for d in dirs:
        vp = _find_violation_json(d)
        if not vp:
            continue
        data = _read_json(vp) or {}
        for ref in data.get("cross_references") or []:
            if isinstance(ref, dict):
                rid = str(ref.get("ref") or "").strip()
            else:
                rid = str(ref).strip()
            if rid:
                ids.add(rid)
    return ids


def _collect_known_titles(dirs: list[Path]) -> dict[str, str]:
    """Map violation_id -> title for every bundle discovered on disk."""
    titles: dict[str, str] = {}
    for d in dirs:
        vp = _find_violation_json(d)
        if not vp:
            continue
        data = _read_json(vp) or {}
        vid = str(data.get("violation_id") or d.name).strip()
        title = str(data.get("title") or "").strip()
        if vid and title:
            titles[vid] = title
    return titles


def run(
    root: Path,
    include_extra: bool,
    only: list[str],
    limit: int | None,
    write_backup: bool,
    zip_output: bool,
    enrich: bool = False,
    enrich_stages: list[str] | None = None,
    llm_override: dict | None = None,
) -> int:
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Input path does not exist or is not a directory: {root}")

    dirs = _iter_violation_dirs(root)
    if not include_extra:
        dirs = [d for d in dirs if _bundle_local_id(d.name).isdigit()]
    # Collect known_ids from ALL discovered bundles BEFORE --only filtering,
    # so cross-reference enrichment can see sibling violations even when
    # processing a single bundle.
    known_ids = _collect_known_ids(dirs)
    known_titles = _collect_known_titles(dirs)
    if only:
        only_set = set(only)
        dirs = [d for d in dirs if d.name in only_set]
    if limit is not None:
        dirs = dirs[:limit]

    results: list[dict] = []
    ok = 0
    failed = 0
    for d in dirs:
        success, info, _notes = _process_one(
            d, known_ids, write_backup=write_backup, zip_output=zip_output,
            enrich=enrich, enrich_stages=enrich_stages, llm_override=llm_override,
            known_titles=known_titles,
        )
        results.append(info)
        if success:
            ok += 1
        else:
            failed += 1

    print(f"Processed: {ok} succeeded, {failed} failed, total={len(dirs)}")
    for info in results:
        if "error" in info:
            print(f"- {info['violation_id']}: ERROR {info['error']}")
            continue
        s = info["summary"]
        print(
            f"- {info['violation_id']}: pass={s['pass']} warn={s['warn']} fail={s['fail']}"
            f" confidence={info['confidence']}"
        )

    (root / "refine_batch_summary.json").write_text(
        json.dumps({
            "root": str(root),
            "total": len(dirs),
            "succeeded": ok,
            "failed": failed,
            "results": results,
        }, indent=2),
        encoding="utf-8",
    )

    return 0 if failed == 0 else 1
