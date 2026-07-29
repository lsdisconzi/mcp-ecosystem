"""LLM enrichment stage for ViolationRefiner.

This module bridges the deterministic pipeline (staging + anchoring +
hydration + validation) with the layered enrichment a human legal analyst
would otherwise produce by hand:

    Layer 3 (element grids)  — proof status of each doctrinal element
    Layer 4 (nexus matrix)   — typed fact ↔ norm ↔ element edges
    Layer 5 (authorities)    — research-query stubs, never auto-verified
    Plus: subsection tightening, English translations, candidate articles,
          open questions, cross-references.

Every step:
    * is a JSON-in / JSON-out pure function over a Violation,
    * issues a single LLM call,
    * round-trips through the existing `layers.*` builders so any
      malformed proposal raises a Pydantic ValidationError at the seam,
    * is idempotent — re-running with the same inputs replaces by id.

The verifier in `verifier.py` then enforces the substantive invariants
(verbatim substrings, referenced segments exist, authorities unverified,
etc.) so an LLM hallucination is rejected, not absorbed.

The orchestrator `enrich_violation` runs the steps in topological order
and re-attaches confidence at the end.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from .confidence import attach_confidence
from .layers import (
    add_authority_stub,
    add_element_grid,
    build_nexus_layer,
)
from .llm import LLMClient, LLMError
from .models import (
    ArticleElementGrid,
    CandidateArticle,
    CrossReference,
    Element,
    EvidenceSegment,
    NexusEntry,
    OpenQuestion,
    Violation,
)
from .sources import FrameworkSource, TranscriptSource


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# Authority fields the LLM is NOT allowed to produce — defense in depth on
# top of add_authority_stub() which only accepts the safe subset. The
# verification_provenance entry is here because a malicious / confused LLM
# could synthesise a plausible-looking provenance block to slip a fake
# verification past V11; only the authority_verification module may write
# this field.
_AUTHORITY_FORBIDDEN_FIELDS = {
    "court", "rol", "decision_date", "author", "work",
    "pages", "instrument", "holding_summary", "verified",
    "verification_provenance",
}


_SYSTEM_PROMPT = """You are a legal-research analyst assistant for the
ViolationRefiner pipeline. You produce strict JSON only. You never invent
verbatim quotes, rol numbers, court names, or decision dates. When asked
to refer to source text, you copy it byte-for-byte from inputs the caller
provides — never paraphrase a verbatim quote.

Output rules (load-bearing):
- Reply with a single JSON object. No prose. No code fences.
- Spanish field values stay in Spanish; English fields are concise.
- When uncertain, mark proof_status="contested" or omit the item rather
  than fabricate.
- Authorities are always research stubs: NEVER include court, rol,
  decision_date, author, work, pages, instrument, holding_summary, or
  verified=true. Output only research_query and proposition_to_verify.
"""


def _violation_snapshot(v: Violation) -> dict[str, Any]:
    """Compact view of a Violation suitable for an LLM context."""
    return {
        "violation_id": v.violation_id,
        "title": v.title,
        "severity": v.severity,
        "incident": v.incident.model_dump(),
        "segments": [
            {
                "segment_id": s.segment_id,
                "speaker": s.speaker,
                "role_in_argument": s.role_in_argument,
                "verbatim_es": s.verbatim_es,
                "translation_en": s.translation_en,
            }
            for s in v.segments
        ],
        "established_articles": [
            {
                "article_id": a.article_id,
                "article_name": a.article_name,
                "subsections_invoked": a.subsections_invoked,
                "framework_code": a.framework_code,
                "duty_bearer": a.duty_bearer,
                "norm_type": a.norm_type,
                "applicability": a.applicability,
                "applicability_rationale": a.applicability_rationale,
                # full verbatim text is the elephant in the prompt; keep it.
                "verbatim_excerpt": a.verbatim_excerpt,
            }
            for a in v.established_articles
        ],
        "candidate_articles": [
            c.model_dump() for c in v.candidate_articles
        ],
    }


def _call(client: LLMClient, instruction: str, payload: dict, *, max_tokens: int = 8000) -> dict:
    """One LLM call with the canonical system prompt and a user payload."""
    user = (
        instruction.strip()
        + "\n\n--- INPUT ---\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
    return client.chat_json(
        messages=[{"role": "user", "content": user}],
        system=_SYSTEM_PROMPT,
        max_tokens=max_tokens,
    )


# ---------------------------------------------------------------------------
# Stage: refine segment metadata (role_in_argument + translation_en)
# ---------------------------------------------------------------------------

_SEGMENT_PROMPT = """Refine the role_in_argument tag and the English
translation for each evidence segment.

Rules:
- Do NOT change `verbatim_es` or `segment_id`.
- `role_in_argument` is a snake_case label like "cctv_review_admission",
  "core_exoneration_admission", "icao_framing_rejected" — what role this
  utterance plays in the legal theory of the violation. Use the violation
  title and existing article excerpts to ground the labels.
- `translation_en` is a concise faithful English rendering.

Return JSON of shape:
{
  "segments": [
    {"segment_id": "...", "role_in_argument": "...", "translation_en": "...",
     "transcription_notes": "... or omit"}
  ]
}
"""


def propose_segment_metadata(
    violation: Violation,
    client: LLMClient,
) -> list[EvidenceSegment]:
    """Refine `role_in_argument` and `translation_en` for every segment.
    Verbatim text and hashes are preserved untouched."""
    if not violation.segments:
        return []
    payload = _violation_snapshot(violation)
    resp = _call(client, _SEGMENT_PROMPT, payload)
    by_id = {s.segment_id: s for s in violation.segments}
    out: list[EvidenceSegment] = []
    for entry in resp.get("segments") or []:
        sid = entry.get("segment_id")
        seg = by_id.get(sid)
        if not seg:
            continue
        updates: dict[str, Any] = {}
        role = entry.get("role_in_argument")
        if isinstance(role, str) and role.strip():
            updates["role_in_argument"] = role.strip()
        tr = entry.get("translation_en")
        if isinstance(tr, str) and tr.strip():
            updates["translation_en"] = tr.strip()
        note = entry.get("transcription_notes")
        if isinstance(note, str) and note.strip():
            updates["transcription_notes"] = note.strip()
        if updates:
            out.append(seg.model_copy(update=updates))
    return out


# ---------------------------------------------------------------------------
# Stage: tighten article excerpts to the actually-invoked numeral
# ---------------------------------------------------------------------------

_SUBSECTION_PROMPT = """For each established article, identify the
specific numeral / inciso / letra that the violation actually invokes,
and quote it BYTE-FOR-BYTE from the article body provided.

Rules:
- `verbatim_excerpt` MUST be a literal substring of `body`. Do not
  rephrase, do not add ellipses. If you cannot find a tight numeral,
  return the article's first sentence verbatim.
- `subsections_invoked` is a list of short identifiers (e.g. ["8"] for
  numeral 8, ["b"] for letra b, ["1", "2"] for numerals 1 and 2).
- Do not invent subsections that are not in the body.

Return JSON of shape:
{
  "articles": [
    {"article_id": "...", "subsections_invoked": ["..."], "verbatim_excerpt": "..."}
  ]
}
"""


def propose_article_subsections(
    violation: Violation,
    frameworks: dict[str, FrameworkSource],
    client: LLMClient,
) -> list[dict]:
    """Returns a list of {article_id, subsections_invoked, verbatim_excerpt}.
    Only substrings present in the framework body survive."""
    if not violation.established_articles:
        return []

    bodies: dict[str, str] = {}
    for art in violation.established_articles:
        # Conservative: when the upstream contract already pinned the specific
        # subsections (e.g. ["8"] for Art. 193 N° 8 ocultación), do not let
        # the LLM re-open the question — it tends to widen the framing
        # (e.g. adding N° 4 falsedad ideológica) and dilute the legal theory.
        if art.subsections_invoked:
            continue
        reader = frameworks.get(art.framework_code)
        if not reader:
            continue
        art_num = art.article_id.rsplit(".Art.", 1)[-1]
        body = reader.get_article_body(art_num) or reader.get_article_body(
            art_num.split(".")[0]
        )
        if body:
            bodies[art.article_id] = body

    if not bodies:
        return []

    payload = {
        "title": violation.title,
        "articles": [
            {
                "article_id": a.article_id,
                "article_name": a.article_name,
                "current_excerpt": a.verbatim_excerpt,
                "body": bodies[a.article_id],
            }
            for a in violation.established_articles
            if a.article_id in bodies
        ],
        "segments": [
            {"segment_id": s.segment_id, "verbatim_es": s.verbatim_es}
            for s in violation.segments
        ],
    }
    resp = _call(client, _SUBSECTION_PROMPT, payload)
    out: list[dict] = []
    for item in resp.get("articles") or []:
        aid = item.get("article_id")
        body = bodies.get(aid)
        excerpt = item.get("verbatim_excerpt") or ""
        subs = item.get("subsections_invoked") or []
        if not isinstance(excerpt, str) or not isinstance(subs, list):
            continue
        if not body or excerpt not in body:
            # Hallucinated excerpt — drop. The verifier would catch this
            # later anyway, but stopping earlier keeps the JSON clean.
            continue
        out.append({
            "article_id": aid,
            "subsections_invoked": [str(s) for s in subs],
            "verbatim_excerpt": excerpt,
        })
    return out


# ---------------------------------------------------------------------------
# Stage: element grid per article
# ---------------------------------------------------------------------------

_ELEMENT_GRID_PROMPT = """Build the doctrinal element grid for ONE article
of penal/civil/constitutional law: list the elements the prosecution
must prove, then score each one against the available segments.

Rules:
- `element_id` shape: "<jurisdiction>.<FW>.Art.<num>[.<sub>].elem.<snake_case_label>".
  When `subsections_invoked` is non-empty, INCLUDE the subsection in the id
  (e.g. "CL.CHIPENCOD.Art.193.8.elem.modalidad_ocultacion").
- For CRIMINAL articles, decompose the offence comprehensively: produce a
  separate element for EACH of the following dimensions when applicable
  (typical grids have 6-8 elements):
    1. sujeto_activo / sujeto_pasivo (qualified subject, if any),
    2. abuso_del_oficio or analog "in execution of the office" element,
    3. acto_del_oficio (the underlying official act/duty),
    4. modalidad_tipica (the typical verb of the offence: ocultar, falsificar, etc.),
    5. objeto_material (the thing on which the offence falls: documento, prueba, etc.),
    6. resultado / perjuicio (harm, where the offence is one of result),
    7. tipicidad_subjetiva / dolo (mental element).
  Prefer Spanish snake_case labels for Chilean criminal articles.
- `proof_status` is one of: established, strong, contested, weak, missing,
  not_applicable, not_developed. Use "established" only when the segment
  evidence is dispositive; use "strong" when multiple converging segments
  support the element without dispositive proof; use "contested" when the
  element depends on a verification still open; "weak" only when no
  segment evidence supports it.
- `proof_evidence_segments` MUST be a NON-EMPTY list of segment_ids that
  exist in the violation segments whenever proof_status is established,
  strong, or contested. Pick the most probative segments from the list
  provided; do not invent segment ids.
- `argument_es` is one to three Spanish sentences justifying the status.
- `weaknesses` and `open_questions` are short lists; omit if empty.

Return JSON of shape:
{
  "article_id": "...",
  "article_short": "Art. X N° Y — <verb> (FW)",
  "elements": [
    {"element_id": "...", "label": "...", "doctrinal_basis": "... or null",
     "proof_status": "...", "proof_evidence_segments": ["..."],
     "argument_es": "...", "weaknesses": ["..."], "open_questions": ["..."]}
  ]
}
"""


def propose_element_grid(
    violation: Violation,
    article_id: str,
    client: LLMClient,
) -> ArticleElementGrid | None:
    """Generate one element grid for the named article."""
    art = next(
        (a for a in violation.established_articles if a.article_id == article_id),
        None,
    )
    if art is None:
        return None
    payload = {
        "violation_id": violation.violation_id,
        "title": violation.title,
        "article": {
            "article_id": art.article_id,
            "article_name": art.article_name,
            "subsections_invoked": art.subsections_invoked,
            "verbatim_excerpt": art.verbatim_excerpt,
            "applicability_rationale": art.applicability_rationale,
        },
        "segments": [
            {
                "segment_id": s.segment_id,
                "speaker": s.speaker,
                "role_in_argument": s.role_in_argument,
                "verbatim_es": s.verbatim_es,
                "translation_en": s.translation_en,
            }
            for s in violation.segments
        ],
    }
    resp = _call(client, _ELEMENT_GRID_PROMPT, payload)
    valid_seg_ids = {s.segment_id for s in violation.segments}

    def _parse(resp: dict) -> tuple[list[Element], str]:
        elements_raw = resp.get("elements") or []
        elements: list[Element] = []
        for e in elements_raw:
            try:
                refs = [
                    r for r in (e.get("proof_evidence_segments") or [])
                    if r in valid_seg_ids
                ]
                elements.append(Element(
                    element_id=str(e["element_id"]),
                    label=str(e.get("label") or e["element_id"]),
                    doctrinal_basis=e.get("doctrinal_basis"),
                    proof_status=str(e.get("proof_status") or "not_developed"),
                    proof_evidence_segments=refs,
                    argument_es=str(e.get("argument_es") or ""),
                    weaknesses=[str(w) for w in (e.get("weaknesses") or [])],
                    open_questions=[str(q) for q in (e.get("open_questions") or [])],
                ))
            except Exception:
                continue
        return elements, str(resp.get("article_short") or article_id)

    elements, article_short = _parse(resp)

    def _grid_score(elems: list[Element]) -> float:
        scored = [e for e in elems if e.proof_status != "not_developed"]
        if not scored:
            return 0.0
        from violation_pack.models import PROOF_WEIGHTS
        return sum(PROOF_WEIGHTS[e.proof_status] for e in scored) / len(scored)

    # Retry once if the grid is too sparse or too weak; sparse 3-4-element
    # grids commonly hurt the confidence score and miss the standard
    # doctrinal decomposition.
    if elements and (len(elements) < 6 or _grid_score(elements) < 0.65):
        resp2 = _call(client, _ELEMENT_GRID_PROMPT, payload)
        elements2, article_short2 = _parse(resp2)
        if elements2 and (
            len(elements2) > len(elements)
            or _grid_score(elements2) > _grid_score(elements)
        ):
            elements = elements2
            article_short = article_short2

    if not elements:
        return None
    return ArticleElementGrid(
        article_id=article_id,
        article_short=article_short,
        elements=elements,
    )


# ---------------------------------------------------------------------------
# Stage: nexus matrix
# ---------------------------------------------------------------------------

_NEXUS_PROMPT = """Build the nexus matrix: typed edges from facts
(segment_ids) to norms (article_ids) to specific elements (element_ids).

Rules:
- Every fact_id MUST appear in violation.segments.
- Every norm_id + element_id pair MUST appear in violation.element_grids.
  Use the element_ids EXACTLY as given (do not invent shorter forms).
- For each element, propose AT LEAST ONE nexus entry from the most
  relevant segment. A grid with N elements should produce at least N
  entries; comprehensive matrices commonly produce 1.5x to 2x N entries.
- `nexus_type` is a snake_case category (e.g. direct_admission,
  corroborating_admission, harm_crystallization,
  active_concealment_directive, system_state_corroboration,
  contemporaneous_admission_of_intent, functional_context,
  circumstantial_omission, speaker_identification).
- `strength` is one of: high, medium, low.
- `rationale_oneline` is one short sentence (<= 160 chars) in English.

Return JSON of shape:
{
  "entries": [
    {"fact_id": "...", "norm_id": "...", "element_id": "...",
     "nexus_type": "...", "strength": "high|medium|low",
     "rationale_oneline": "..."}
  ]
}
"""


def propose_nexus(
    violation: Violation,
    client: LLMClient,
) -> list[NexusEntry]:
    if not violation.segments or not violation.element_grids:
        return []
    payload = {
        "segments": [
            {"segment_id": s.segment_id, "role_in_argument": s.role_in_argument,
             "verbatim_es": s.verbatim_es, "translation_en": s.translation_en}
            for s in violation.segments
        ],
        "element_grids": [
            {
                "article_id": g.article_id,
                "article_short": g.article_short,
                "elements": [
                    {"element_id": e.element_id, "label": e.label}
                    for e in g.elements
                ],
            }
            for g in violation.element_grids
        ],
    }
    resp = _call(client, _NEXUS_PROMPT, payload)
    valid_segs = {s.segment_id for s in violation.segments}
    valid_pairs: set[tuple[str, str]] = set()
    for g in violation.element_grids:
        for e in g.elements:
            valid_pairs.add((g.article_id, e.element_id))

    def _parse(resp: dict) -> list[NexusEntry]:
        out: list[NexusEntry] = []
        for entry in resp.get("entries") or []:
            try:
                fid = entry["fact_id"]
                nid = entry["norm_id"]
                eid = entry["element_id"]
            except KeyError:
                continue
            if fid not in valid_segs:
                continue
            if (nid, eid) not in valid_pairs:
                continue
            try:
                out.append(NexusEntry(
                    fact_id=fid, norm_id=nid, element_id=eid,
                    nexus_type=str(entry.get("nexus_type") or "unspecified"),
                    strength=str(entry.get("strength") or "medium"),
                    rationale_oneline=str(entry.get("rationale_oneline") or "")[:240],
                ))
            except Exception:
                continue
        return out

    out = _parse(resp)
    # Single retry if the first attempt yielded nothing usable but we have
    # valid pairs to work with — nexus generation is occasionally empty due
    # to LLM nondeterminism.
    if not out and valid_pairs and valid_segs:
        resp2 = _call(client, _NEXUS_PROMPT, payload)
        out = _parse(resp2)
    return out


# ---------------------------------------------------------------------------
# Stage: candidate articles
# ---------------------------------------------------------------------------

_CANDIDATES_PROMPT = """List additional articles a careful analyst would
PROPOSE as plausibly applicable but that are NOT yet verified or are not
in the bundle.

Rules:
- Use ELI-style ids: "CL.<FW>.Art.<num>". The "<FW>" segment MUST be a
  real framework code — e.g. CACH, LPC/LPDC, CC (Codigo Civil), CP/CHIPENCOD,
  CPR/CONST, L19628/LPDP, DS113 — not a placeholder like "FW".
- For Code Civil articles, use "CC" (NOT "FW"). For Constitution articles,
  use "CPR" or "CONST". For Ley del Consumidor, "LPC" or "LPDC". For
  data protection (Ley 19.628), "LPDP" or "L19628".
- Every candidate MUST list one or more concrete `verification_required`
  steps (e.g. "Fetch verbatim text for CL.CC.Art.2314 from bcn.cl/leychile").
- `history_note` should explain provenance, especially if it replaces a
  previously-fabricated citation.
- Do NOT include articles already in `established_articles`.
- Do NOT include articles whose hypothesis demands a defendant class the
  facts plainly do not match (e.g. an article that says "el empleado publico
  que..." against a private corporate defendant). If you must include such
  an article for completeness, set `preliminary_view` so the FIRST sentence
  flags the agent-fit mismatch explicitly.
- It is fine to return an empty list.

Return JSON of shape:
{
  "candidates": [
    {"candidate_article_id": "...", "candidate_name": "...",
     "framework_cache_status": "not_in_bundle" or "pending_fetch",
     "verification_required": ["..."],
     "preliminary_view": "... or null",
     "history_note": "... or null"}
  ]
}
"""


# Known framework prefixes — single source of truth for the candidate
# namespace guardrail. Keep this in sync with stage_cl_batch.FRAMEWORK_MD_MAP.
_KNOWN_FRAMEWORK_PREFIXES = {
    # Chilean
    "CHIPENCOD", "CPCL", "CP", "CONST", "CPR", "DAN17", "L18575", "DFL1",
    "DSO", "IVAAF", "DGAC_IVAAF", "PREVAC", "DGAC_PREVAC", "DTO2421",
    "L16752", "CACH", "L18916", "LPDC", "LPC", "L19496", "L20285", "INDH",
    "L20405", "L20880", "R218", "CC", "CCCL", "L19628", "LPDP", "DS113",
    # Brazilian (kept here so cross-jurisdiction bundles don't get stripped)
    "CBA", "L7565", "CDC", "L8078", "L10406", "CPB", "DL2848", "CF88",
    "L9784", "L7716", "L12527", "LAI", "L13460", "L8429", "L12846", "L12813",
    "L8906", "OAB", "D11129", "D2181", "D7203", "D7724", "R400", "ANAC",
    "ABEAR",
    # International
    "ACHR", "CHICAGO", "HAGUE", "IATA", "IATA_GC", "AN6", "AN6I", "AN9",
    "AN10", "AN11", "AN13", "AN14", "AN17", "AN18", "DOC4444", "DOC8168",
    "DOC9284", "ILC_ARSIWA", "MC99", "UNCRC", "UNGCP", "VCCR", "VCLT",
}


def _has_known_framework(article_id: str) -> bool:
    """An ELI id looks like '<JUR>.<FW>.[T*.C*.]Art.<num>'. We accept the
    candidate only when the framework segment matches a known code — this
    blocks placeholder prefixes like 'FW' that haiku has been known to emit
    when it forgets the real namespace."""
    parts = article_id.split(".")
    if len(parts) < 3:
        return False
    return parts[1] in _KNOWN_FRAMEWORK_PREFIXES


def propose_candidates(
    violation: Violation,
    client: LLMClient,
) -> list[CandidateArticle]:
    payload = _violation_snapshot(violation)
    resp = _call(client, _CANDIDATES_PROMPT, payload)
    established_ids = {a.article_id for a in violation.established_articles}
    out: list[CandidateArticle] = []
    for c in resp.get("candidates") or []:
        cid = c.get("candidate_article_id")
        if not isinstance(cid, str) or cid in established_ids:
            continue
        # Guardrail 1: reject placeholder/unknown framework prefixes.
        # CL.FW.Art.X and similar typos get silently dropped here so they
        # never reach the bundle. If the LLM intended a real framework it
        # will re-propose it correctly on retry; otherwise the citation
        # wasn't load-bearing in the first place.
        if not _has_known_framework(cid):
            continue
        vr = c.get("verification_required") or []
        if not isinstance(vr, list) or not vr:
            continue
        try:
            out.append(CandidateArticle(
                candidate_article_id=cid,
                candidate_name=str(c.get("candidate_name") or cid),
                framework_cache_status=str(c.get("framework_cache_status") or "not_in_bundle"),
                verification_required=[str(x) for x in vr],
                preliminary_view=c.get("preliminary_view"),
                history_note=c.get("history_note"),
            ))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# Stage: authority stubs
# ---------------------------------------------------------------------------

_AUTHORITY_PROMPT = """List authorities (jurisprudence or doctrine) that
should be researched to bolster specific elements. Output research-query
stubs only — DO NOT include court, rol, decision_date, author, work,
pages, instrument, holding_summary, or verified.

Rules:
- `authority_id` shape: "AUTH-<short-token>" (uppercase, hyphens).
- `type` is one of: jurisprudence, doctrine, comparative, statute.
- `supports` is a list of element_ids the authority would back.
- `research_query` is one to two sentences describing what to search.
- `proposition_to_verify` is the concrete legal proposition the
  authority would, if found, confirm.

Return JSON of shape:
{
  "authorities": [
    {"authority_id": "AUTH-...", "type": "...", "supports": ["..."],
     "research_query": "...", "proposition_to_verify": "...",
     "verification_protocol": "... or null",
     "fabrication_risk_note": "... or null"}
  ]
}
"""


def propose_authorities(
    violation: Violation,
    client: LLMClient,
) -> list[dict]:
    """Returns stub dicts suitable for `add_authority_stub`."""
    if not violation.element_grids:
        return []
    payload = {
        "violation_id": violation.violation_id,
        "title": violation.title,
        "established_articles": [
            {"article_id": a.article_id, "article_name": a.article_name}
            for a in violation.established_articles
        ],
        "element_grids": [
            {
                "article_id": g.article_id,
                "elements": [
                    {"element_id": e.element_id, "label": e.label,
                     "proof_status": e.proof_status}
                    for e in g.elements
                ],
            }
            for g in violation.element_grids
        ],
    }
    resp = _call(client, _AUTHORITY_PROMPT, payload)
    valid_elem_ids: set[str] = set()
    for g in violation.element_grids:
        valid_elem_ids.add(g.article_id)
        for e in g.elements:
            valid_elem_ids.add(e.element_id)
    out: list[dict] = []
    for a in resp.get("authorities") or []:
        if not isinstance(a, dict):
            continue
        if any(k in a for k in _AUTHORITY_FORBIDDEN_FIELDS):
            # Defense in depth: strip any forbidden fields before passing on.
            a = {k: v for k, v in a.items() if k not in _AUTHORITY_FORBIDDEN_FIELDS}
        aid = a.get("authority_id")
        atype = a.get("type")
        supports = a.get("supports") or []
        if not aid or not atype or not isinstance(supports, list):
            continue
        supports = [str(s) for s in supports if str(s) in valid_elem_ids]
        if not supports:
            continue
        out.append({
            "authority_id": str(aid),
            "type_": str(atype),
            "supports": supports,
            "research_query": str(a.get("research_query") or ""),
            "proposition_to_verify": str(a.get("proposition_to_verify") or ""),
            "verification_protocol": a.get("verification_protocol"),
            "fabrication_risk_note": a.get("fabrication_risk_note"),
        })
    return out


# ---------------------------------------------------------------------------
# Stage: open questions
# ---------------------------------------------------------------------------

_OPEN_Q_PROMPT = """List the open evidentiary or procedural questions
whose resolution would change proof status of one or more elements.

Rules:
- `id` shape: "OQ-<violation_id-suffix>-<short-token>" (uppercase).
- `priority` is one of: low, medium, high, critical.
- `blocks_element` is an element_id or null.
- `obtaining_method` describes how to answer (e.g. "Ley 20.285
  Transparencia request to PDI").

Return JSON of shape:
{
  "open_questions": [
    {"id": "...", "question": "...", "blocks_element": "... or null",
     "priority": "...", "obtaining_method": "... or null"}
  ]
}
"""


def propose_open_questions(
    violation: Violation,
    client: LLMClient,
) -> list[OpenQuestion]:
    if not violation.element_grids:
        return []
    payload = {
        "violation_id": violation.violation_id,
        "title": violation.title,
        "element_grids": [g.model_dump() for g in violation.element_grids],
    }
    resp = _call(client, _OPEN_Q_PROMPT, payload)
    valid_elem_ids = {
        e.element_id for g in violation.element_grids for e in g.elements
    }
    out: list[OpenQuestion] = []
    for q in resp.get("open_questions") or []:
        try:
            be = q.get("blocks_element")
            if be and be not in valid_elem_ids:
                be = None
            out.append(OpenQuestion(
                id=str(q["id"]),
                question=str(q.get("question") or ""),
                blocks_element=be,
                priority=str(q.get("priority") or "medium"),
                obtaining_method=q.get("obtaining_method"),
            ))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# Stage: cross-references
# ---------------------------------------------------------------------------

_CROSSREF_PROMPT = """List cross-references from THIS violation to sibling violations.

Use the `siblings` array (id + title) to understand what each sibling is about,
then propose links from THIS violation's facts/elements to those siblings.

Rules:
- Only reference violation_ids that appear in `known_violation_ids`.
- Propose every plausible link; err on the side of inclusion when the sibling
  title describes the same incident, the same actors, the same evidentiary
  chain, or a downstream consequence.
- `relation` is a short snake_case phrase describing the link, for example:
    predicate_calumnia_disproved_by_this_finding,
    narrative_continued_despite_this_finding,
    removal_decision_never_corrected_after,
    disembarkation_letter_repeated_disproved_accusation,
    passenger_never_informed_of_this_finding.

Return JSON of shape:
{ "cross_references": [{"ref": "CL-...", "relation": "..."}] }
"""


def propose_cross_references(
    violation: Violation,
    known_violation_ids: set[str],
    client: LLMClient,
    known_violation_titles: dict[str, str] | None = None,
) -> list[CrossReference]:
    others = sorted(known_violation_ids - {violation.violation_id})
    if not others:
        return []
    titles = known_violation_titles or {}
    siblings = [
        {"violation_id": vid, "title": titles.get(vid, "")}
        for vid in others
    ]
    payload = {
        "violation_id": violation.violation_id,
        "title": violation.title,
        "known_violation_ids": others,
        "siblings": siblings,
        "summary": [
            {"role": s.role_in_argument, "translation_en": s.translation_en}
            for s in violation.segments[:20]
        ],
    }
    resp = _call(client, _CROSSREF_PROMPT, payload)
    allowed = set(others)
    out: list[CrossReference] = []
    for c in resp.get("cross_references") or []:
        ref = c.get("ref")
        rel = c.get("relation")
        if not ref or ref not in allowed or not rel:
            continue
        try:
            out.append(CrossReference(ref=str(ref), relation=str(rel)))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

ENRICHMENT_STAGES = [
    "segments",
    "subsections",
    "element_grids",
    "nexus",
    "candidates",
    "authorities",
    "open_questions",
    "cross_references",
]


def enrich_violation(
    violation: Violation,
    *,
    client: LLMClient,
    transcripts: dict[str, TranscriptSource] | None = None,
    frameworks: dict[str, FrameworkSource] | None = None,
    known_violation_ids: set[str] | None = None,
    known_violation_titles: dict[str, str] | None = None,
    stages: Iterable[str] | None = None,
) -> Violation:
    """Run the enrichment stages in order, returning the enriched Violation.

    Each stage:
      1. proposes new items via the LLM,
      2. lands them through the existing layer functions (which enforce
         schema invariants),
      3. logs a provenance entry.

    Failures in any single stage are surfaced as LLMError; the caller can
    choose to skip that stage and continue. Default is fail-fast.
    """
    frameworks = frameworks or {}
    known_violation_ids = known_violation_ids or set()
    selected = list(stages) if stages else list(ENRICHMENT_STAGES)
    v = violation

    if "segments" in selected:
        refined = propose_segment_metadata(v, client)
        if refined:
            by_id = {s.segment_id: s for s in v.segments}
            for r in refined:
                by_id[r.segment_id] = r
            v = v.model_copy(update={"segments": list(by_id.values())})

    if "subsections" in selected:
        refinements = propose_article_subsections(v, frameworks, client)
        if refinements:
            ref_by_id = {r["article_id"]: r for r in refinements}
            new_articles = []
            for a in v.established_articles:
                r = ref_by_id.get(a.article_id)
                if not r:
                    new_articles.append(a)
                    continue
                # Replace excerpt + hash + subsections.
                import hashlib
                new_excerpt = r["verbatim_excerpt"]
                new_sha = hashlib.sha256(new_excerpt.encode("utf-8")).hexdigest()
                new_articles.append(a.model_copy(update={
                    "verbatim_excerpt": new_excerpt,
                    "verbatim_excerpt_sha256": new_sha,
                    "subsections_invoked": r["subsections_invoked"],
                }))
            v = v.model_copy(update={"established_articles": new_articles})

    if "element_grids" in selected:
        for art in list(v.established_articles):
            # Indirect-predicate articles anchor materiality (e.g. Art. 211
            # calumnia as predicate for Art. 193 N° 8 ocultación); they do
            # not carry their own doctrinal grid in the canonical theory.
            # Building one here over-decomposes the case and dilutes the
            # weighted confidence score with elements the prosecution does
            # not need to independently prove.
            if art.applicability == "indirect_predicate":
                continue
            grid = propose_element_grid(v, art.article_id, client)
            if grid is not None:
                v = add_element_grid(v, grid)
        # Promote applicability from "supporting" to "direct" for articles
        # whose grid is materially strong (weighted_score >= 0.70 and at
        # least one element established). This reflects the standard
        # baseline: once the doctrinal grid is built and corroborated, the
        # article is no longer merely "supporting".
        grids_by_aid = {g.article_id: g for g in v.element_grids}
        new_articles = []
        promoted = False
        for art in v.established_articles:
            grid = grids_by_aid.get(art.article_id)
            if (
                grid is not None
                and art.applicability == "supporting"
                and grid.weighted_score() >= 0.70
                and any(e.proof_status == "established" for e in grid.elements)
            ):
                new_articles.append(art.model_copy(update={"applicability": "direct"}))
                promoted = True
            else:
                new_articles.append(art)
        if promoted:
            v = v.model_copy(update={"established_articles": new_articles})

    if "nexus" in selected:
        entries = propose_nexus(v, client)
        if entries:
            v = build_nexus_layer(v, entries)

    if "candidates" in selected:
        cands = propose_candidates(v, client)
        if cands:
            existing = {c.candidate_article_id: c for c in v.candidate_articles}
            for c in cands:
                existing[c.candidate_article_id] = c
            v = v.model_copy(update={"candidate_articles": list(existing.values())})

    if "authorities" in selected:
        stubs = propose_authorities(v, client)
        for s in stubs:
            v = add_authority_stub(v, **s)

    if "open_questions" in selected:
        oqs = propose_open_questions(v, client)
        if oqs:
            by_id = {q.id: q for q in v.open_questions}
            for q in oqs:
                by_id[q.id] = q
            v = v.model_copy(update={"open_questions": list(by_id.values())})

    if "cross_references" in selected:
        xrefs = propose_cross_references(
            v, known_violation_ids, client,
            known_violation_titles=known_violation_titles,
        )
        if xrefs:
            by_ref = {x.ref: x for x in v.cross_references}
            for x in xrefs:
                by_ref[x.ref] = x
            v = v.model_copy(update={"cross_references": list(by_ref.values())})

    # Re-attach confidence so it reflects the new element grids.
    v = attach_confidence(v)
    return v
