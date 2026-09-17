#!/usr/bin/env python3
"""Convert LA8159 violation JSON (schema 4.0) into final bundles.

The vault no longer holds Markdown. Violations are structured JSON:

    <vault>/01-violations/_json/EN/<VID>.json

so this module reads them directly (the former YAML-frontmatter parser is
gone) and writes the **final** bundle — the layout ``refine_batch`` consumes,
with no staging step in between:

    <output>/<VID>/contract.json            identity + confidence summary
    <output>/<VID>/segments_manifest.json   per-segment anchor provenance
    <output>/<VID>/<VID>.json               the Violation document itself
    <output>/<VID>/Transcripts/             symlinks into data/transcripts/json
    <output>/<VID>/Legal framework/         symlinks into data/law, named <code>.md
    <output>/<VID>/conversion_warnings.json every warning, in full
    <output>/<VID>/speaker_index.json       symlink, when present

The emitted ``<VID>.json`` is translated into the *final* shape, not an
intermediate one: ``refine_batch_core._load_violation`` returns it verbatim as
soon as it validates, so anything this module drops (element grids, nexus
rows, authorities) is dropped for the refiner too. ``conversion_warnings.json``
is the audit trail for exactly that.

Segment re-anchoring
--------------------
``full_segments[].segment_id`` uses the *legacy render* numbering, which is
stale: ``transcription`` re-rendered every transcript (header repair + speaker
consolidation), so the indices moved and the old ids now point at the wrong
utterance. Every segment is re-anchored against the canonical transcript in
``data/transcripts/json/`` using two independent signals (normalized text
similarity and audio offset), and the *current* index is emitted as
``<transcript_id>.seg-<index>`` — the shape ``JsonTranscriptSource`` composes.

Element-id canonicalization
---------------------------
The vault's ``element_grids`` use the article's full prefix — e.g.
``CL.CHIPENCOD.T4.C3.Art.193.8.elem.modalidad_ocultacion`` — while the
established article it belongs to may be spelled ``CL.CHIPENCOD.Art.193``.
Both spellings are semantically identical and the template registry accepts
either, but a bundle that mixes them forces V21 to tolerate drift it should
not have to. :func:`build_violation_document` rewrites element-id prefixes at
write-time so the shipped bundle carries one spelling and one only. The
rewrite applies to ``element_grids[]`` and to the ``element_id``/``norm_id``
fields of ``nexus_matrix[]``, because a nexus row that pointed at the old
prefix would otherwise dangle after the grid was rewritten.

Usage:
    python3 examples/vault_to_bundle.py CL-009
    python3 examples/vault_to_bundle.py --all
    python3 examples/vault_to_bundle.py --all --output build
    python3 examples/vault_to_bundle.py CL-009 --inputs-only

Run it with the project virtualenv (``.venv/bin/python``); the system
``python3`` does not carry the project's dependencies.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import statistics
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

# Runnable as ``python examples/vault_to_bundle.py`` from the repo root without
# needing PYTHONPATH set by hand.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from violation_pack._utils import sha256_text  # noqa: E402
from violation_pack.confidence import derive_confidence  # noqa: E402
from violation_pack.element_templates import (  # noqa: E402
    split_article_id,
)
from violation_pack.models import Violation  # noqa: E402
from violation_pack.sources import MarkdownFrameworkSource  # noqa: E402
from violation_pack.sources_json import JsonTranscriptSchemaError, JsonTranscriptSource  # noqa: E402

#: Vault root (Olivia case share). ``_json/EN`` holds the authoritative set;
#: ``_json/{BR,ES,IT}`` only carry a handful of translations.
DEFAULT_SOURCE = Path(
    "/Users/leandrodisconzi/repos/olivia/_shared/cases/la8159/01-violations/_json/EN"
)
#: Read-only consumers of ``transcription``-owned data; both are symlinks into
#: ``../transcription`` (see docs/data_source_of_truth.md).
DEFAULT_TRANSCRIPT_DIR = Path("data/transcripts/json")
DEFAULT_LAW_ROOT = Path("data/law")
#: Final bundles, one directory per violation — the layout ``refine_batch`` and
#: ``ui_server`` discover (``build/<VID>/``).
DEFAULT_OUTPUT = Path("build")
#: ``speaker_index.json`` travels beside the transcripts so the bundle is
#: self-describing (``refine_batch_core._speaker_index_path``).
DEFAULT_SPEAKER_INDEX = Path("data/speaker_index.json")

#: ``audio_id`` -> bundle source token. Anchored, never a substring search: an
#: unanchored ``STG_2`` match also hits ``latam_STG_2`` and silently returns the
#: wrong transcript.
_AUDIO_ID_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^aeropuerto_STG_(\d+)$"), "STG-{0}"),
    (re.compile(r"^latam_STG_(\d+)$"), "LATAM-{0}"),
    (re.compile(r"^carabineros_ppdartnel_(\d+)$"), "CARABINEROS-{0}"),
    # Guarulhos (BR) incident audio; 1105 vault segments cite ``BDM.seg-N``.
    (re.compile(r"^(GRU_Airport_Full)$"), "BDM"),
)

#: Enum domains enforced by ``violation_pack.refine_batch_core._normalize``.
_VALID_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
_VALID_APPLICABILITY = {"direct", "indirect_predicate", "supporting"}
_VALID_NORM_TYPES = {
    "prohibition",
    "penalty",
    "right",
    "liability",
    "definition",
    "exemption",
}
_VALID_PRIORITY = {"low", "medium", "high", "critical"}
#: ``Violation.pack.models.ProofStatus`` — a vault status outside this set would
#: make the whole document fail validation and silently fall back to the lossy
#: legacy normalizer.
_VALID_PROOF_STATUS = {
    "established",
    "strong",
    "contested",
    "weak",
    "missing",
    "not_applicable",
    "not_developed",
}
_VALID_AUTHORITY_TYPES = {"jurisprudence", "doctrine", "comparative", "statute"}
_VALID_CANDIDATE_CACHE_STATUS = {"not_in_bundle", "pending_fetch"}
_VALID_CLOCK_CONFIDENCE = {"verified", "estimated_from_audio_offset", "unknown"}

#: ``applicability`` values the vault emits that the contract does not define.
_APPLICABILITY_ALIASES = {
    "primary": "direct",
    "primary_criminal": "supporting",
    "primary_civil": "supporting",
    "criminal_reporting": "supporting",
    "supporting_analogical": "supporting",
    "analogical": "supporting",
}


def _norm_text(value: str | None) -> str:
    """Fold text to comparison form: no accents, no punctuation, 1-space gaps."""
    folded = (
        unicodedata.normalize("NFKD", value or "")
        .encode("ascii", "ignore")
        .decode()
    )
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", folded.lower())).strip()


# ── CLI ─────────────────────────────────────────────────────────────────────

def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Convert LA8159 violation JSON (schema 4.0) to bundle inputs"
    )
    p.add_argument(
        "violation",
        nargs="*",
        help="Violation IDs (e.g. CL-009) or paths to <VID>.json files.",
    )
    p.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"Vault directory holding <VID>.json (default: {DEFAULT_SOURCE}).",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Convert every violation matching --jurisdiction in --source.",
    )
    p.add_argument(
        "--jurisdiction",
        default="CL",
        help="Prefix filter for IDs / batch mode (default: CL). Use '' for all.",
    )
    p.add_argument(
        "--transcript-dir",
        type=Path,
        default=DEFAULT_TRANSCRIPT_DIR,
        help=f"Canonical transcript JSON dir (default: {DEFAULT_TRANSCRIPT_DIR}).",
    )
    p.add_argument(
        "--law-root",
        type=Path,
        default=DEFAULT_LAW_ROOT,
        help=f"Law corpus root holding _mapping/law_registry.json (default: {DEFAULT_LAW_ROOT}).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output root directory (default: {DEFAULT_OUTPUT}).",
    )
    p.add_argument(
        "--allow-weak-anchors",
        action="store_true",
        help="Emit segments whose anchor rests on the audio offset alone "
             "(low confidence) instead of failing the run.",
    )
    p.add_argument(
        "--speaker-index",
        type=Path,
        default=DEFAULT_SPEAKER_INDEX,
        help=f"speaker_index.json linked into each bundle (default: {DEFAULT_SPEAKER_INDEX}).",
    )
    p.add_argument(
        "--inputs-only",
        action="store_true",
        help="Write only contract.json + segments_manifest.json; skip assembling "
             "the final bundle (Transcripts/, Legal framework/, <VID>.json).",
    )
    return p.parse_args(argv)


# ── Framework code resolution (derived from the registry, never mirrored) ───

#: Legacy codes that appear in vault ``article_id``s but are not an ELI code in
#: ``data/law/_mapping/law_registry.json``. Each alias is pinned to the evidence
#: that justifies it; ``None`` means the corpus has no file at all.
_LEGACY_CODE_ALIASES: dict[tuple[str, str], str | None] = {
    # CL.CP.Art.412 / Art.211 -> Código Penal (registry code ``CPCL``).
    ("CL", "CP"): "CPCL",
    # BR.CP.Art.140 / Art.147 -> DL 2848 (registry code ``CPB``).
    ("BR", "CP"): "CPB",
    # CL.CPR.Art.19 -> "Constitucion Politica de la Republica".
    ("CL", "CPR"): "CONST",
    # BR.ABEAR.CODECONDUCT.S1 -> Código de Conduta ABEAR, §1.
    ("BR", "ABEAR"): "ABEAR_COC",
    # ``LEY<n>`` spellings of codes the registry knows as ``L<n>``.
    ("CL", "LEY16752"): "L16752",
    ("CL", "LEY20285"): "L20285",
    # Ley 19.880 is NOT in the corpus.
    ("CL", "LEY19880"): None,
    # BR.CF.Art.N -> Constituição Federal de 1988 (registry ``CONST``).
    ("BR", "CF"): "CONST",
    # BR.LEI9784.Art.N -> Lei 9.784 (registry ``L9784``).
    ("BR", "LEI9784"): "L9784",
    # INT.BR-CL.Art.N -> Brazil-Chile Joint Declaration 2024 (registry ``BRCL``).
    ("INT", "BR-CL"): "BRCL",
}


class FrameworkResolver:
    """Maps an ``article_id`` code to a law markdown file in the corpus."""

    def __init__(self, law_root: Path, preferred_language: str = "EN") -> None:
        self._law_root = law_root
        self._preferred = preferred_language.upper()
        self._by_code: dict[str, list[str]] = {}
        self._load()

    def _load(self) -> None:
        registry = self._law_root / "_mapping" / "law_registry.json"
        if not registry.is_file():
            return
        doc = json.loads(registry.read_text(encoding="utf-8"))
        for entry in doc.get("files") or []:
            rel = entry.get("file")
            if not rel:
                continue
            elis = list(entry.get("in_qdrant_eli") or []) + list(entry.get("alias_eli") or [])
            for eli in elis:
                parts = str(eli).split(".")
                if len(parts) < 2:
                    continue
                code = parts[1]
                files = self._by_code.setdefault(code, [])
                if rel not in files:
                    files.append(rel)

    @property
    def codes(self) -> set[str]:
        return set(self._by_code)

    def resolve(self, code: str, jurisdiction: str) -> tuple[str | None, str | None]:
        if not code:
            return None, None
        if code not in self._by_code:
            alias = _LEGACY_CODE_ALIASES.get((jurisdiction, code))
            if alias is None and (jurisdiction, code) not in _LEGACY_CODE_ALIASES:
                return None, None
            code = alias  # type: ignore[assignment]
            if code is None:
                return None, None
        files = self._by_code.get(code) or []
        if not files:
            return code, None
        return code, self._pick(files, jurisdiction)

    def _pick(self, files: list[str], jurisdiction: str) -> str:
        if len(files) == 1:
            return files[0]

        def rank(rel: str) -> tuple[int, int, str]:
            parts = rel.split("/")
            jur_hit = 0 if parts[0] == jurisdiction else 1
            lang_hit = 0 if self._preferred in parts[1:-1] else 1
            return (jur_hit, lang_hit, rel)

        return sorted(files, key=rank)[0]


# ── Transcript index ────────────────────────────────────────────────────────

def build_transcript_index(transcript_dir: Path) -> dict[str, dict]:
    """Map a bundle source token (``STG-7``) to its canonical transcript."""
    index: dict[str, dict] = {}
    for path in sorted(transcript_dir.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("segments"), list):
            continue
        audio_id = str(doc.get("audio_id") or "")
        for pattern, template in _AUDIO_ID_RULES:
            m = pattern.match(audio_id)
            if m:
                index[template.format(m.group(1))] = {"doc": doc, "path": path}
                break
    return index


# ── Segment re-anchoring ────────────────────────────────────────────────────

def _nearest_by_offset(segments: list[dict], offset: float | None) -> int | None:
    if offset is None or not segments:
        return None
    return min(
        range(len(segments)),
        key=lambda i: abs(float(segments[i].get("start") or 0.0) - offset),
    )


#: Shortest normalised quote worth scoring. Below this, similarity is dominated
#: by filler ("ah!", "como?") and the ratio says nothing about which segment is
#: meant, so such a needle is never allowed to *choose* an anchor.
_MIN_TEXT_MATCH_LEN = 12


def _best_by_text(segments: list[dict], needle: str) -> tuple[int | None, float, float]:
    """Return ``(index, best_ratio, runner_up_ratio)`` for the closest segment.

    Scoring every candidate matters: a naive ``needle in text or text in needle``
    scan matches the first short interjection that happens to be a substring of
    a long quote, which silently anchors a 3-minute utterance to a one-word
    segment.

    Ties resolve to the **earlier** index. The previous form
    (``scored.sort(reverse=True)``) broke equal-ratio ties on ``i`` descending,
    so a phrase the passenger repeated twice would anchor to the later
    utterance — the one the vault author heard second and, when the offsets are
    close, is not the one they meant.
    """
    if not needle or len(needle) < _MIN_TEXT_MATCH_LEN:
        return None, 0.0, 0.0
    scored = [
        (difflib.SequenceMatcher(None, needle, _norm_text(seg.get("text"))).ratio(), i)
        for i, seg in enumerate(segments)
    ]
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    if not scored:
        return None, 0.0, 0.0
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    return scored[0][1], scored[0][0], runner_up


def _best_in_window(
    segments: list[dict], needle: str, center: int, window: int = 2
) -> tuple[int, float]:
    """Return ``(index, ratio)`` for the best match within ``window`` of ``center``."""
    low = max(0, center - window)
    high = min(len(segments), center + window + 1)
    best_index, best_ratio = center, -1.0
    for i in range(low, high):
        ratio = difflib.SequenceMatcher(
            None, needle, _norm_text(segments[i].get("text"))
        ).ratio()
        if ratio > best_ratio or (
            abs(ratio - best_ratio) <= 0.05
            and abs(i - center) < abs(best_index - center)
        ):
            best_index, best_ratio = i, ratio
    return best_index, best_ratio


#: Text similarity at or above which a match is treated as decisive evidence.
_TEXT_DECISIVE = 0.90

#: Clip-offset calibration bounds.
_DELTA_MIN_SAMPLES = 3
_DELTA_MIN_MAGNITUDE = 30.0
_DELTA_TOLERANCE = 3.0
_DELTA_MIN_AGREEMENT = 0.6


def estimate_clip_offset_delta(
    violation: dict, transcripts: dict[str, dict]
) -> dict[str, float]:
    """Infer a per-source constant offset between a vault clip and its audio."""
    samples: dict[str, list[float]] = {}
    for seg in violation.get("full_segments") or []:
        if not isinstance(seg, dict):
            continue
        raw = str(seg.get("segment_id") or "")
        if "." not in raw:
            continue
        entry = transcripts.get(raw.split(".", 1)[0])
        offset = seg.get("audio_offset_start")
        if entry is None or not isinstance(offset, (int, float)):
            continue
        needle = _norm_text(seg.get("verbatim_es") or seg.get("translation_en"))
        index, ratio, _ = _best_by_text(entry["doc"]["segments"], needle)
        if index is None or ratio < _TEXT_DECISIVE:
            continue
        start = entry["doc"]["segments"][index].get("start")
        if isinstance(start, (int, float)):
            samples.setdefault(raw.split(".", 1)[0], []).append(float(start) - float(offset))

    deltas: dict[str, float] = {}
    for token, observed in samples.items():
        if len(observed) < _DELTA_MIN_SAMPLES:
            continue
        median = statistics.median(observed)
        if abs(median) < _DELTA_MIN_MAGNITUDE:
            continue
        agreeing = sum(1 for d in observed if abs(d - median) <= _DELTA_TOLERANCE)
        if agreeing / len(observed) < _DELTA_MIN_AGREEMENT:
            continue
        deltas[token] = median
    return deltas


def reanchor_segment(
    seg: dict,
    transcripts: dict[str, dict],
    deltas: dict[str, float] | None = None,
) -> dict | None:
    """Resolve a vault segment to the current canonical transcript index."""
    raw = str(seg.get("segment_id") or "")
    if "." not in raw:
        return None
    source_token = raw.split(".", 1)[0]
    entry = transcripts.get(source_token)
    if entry is None:
        return None

    segments = entry["doc"]["segments"]
    transcript_id = str(entry["doc"].get("transcript_id") or entry["path"].stem)
    offset = seg.get("audio_offset_start")
    offset = float(offset) if isinstance(offset, (int, float)) else None
    by_time = _nearest_by_offset(segments, offset)
    delta = (deltas or {}).get(source_token)
    by_delta = (
        _nearest_by_offset(segments, offset + delta)
        if delta is not None and offset is not None
        else None
    )

    needle = _norm_text(seg.get("verbatim_es") or seg.get("translation_en"))
    by_text, ratio, runner_up = _best_by_text(segments, needle)

    if by_text is not None and ratio >= _TEXT_DECISIVE:
        index, method, confidence = by_text, "text", "high"
    elif by_text is not None and ratio >= 0.65 and (ratio - runner_up) >= 0.10:
        index, method, confidence = by_text, "text-weak", "medium"
    elif by_delta is not None:
        index, method, confidence = by_delta, f"clip-delta{delta:+.1f}s", "medium"
        if len(needle) >= _MIN_TEXT_MATCH_LEN:
            snapped, snapped_ratio = _best_in_window(segments, needle, by_delta)
            if snapped != by_delta and snapped_ratio >= 0.40:
                index = snapped
                method = f"clip-delta{delta:+.1f}s+text"
    elif by_time is not None:
        index, method, confidence = by_time, "offset", "low"
    elif by_text is not None:
        index, method, confidence = by_text, "text-only", "low"
    else:
        return None

    notes: list[str] = []
    if by_delta is not None:
        notes.append(f"vault offset read as clip-relative ({delta:+.1f}s)")
        if index == by_delta and method.startswith("text"):
            confidence = "high"
    elif by_time is not None:
        if index == by_time:
            method = f"{method}+offset"
            if method.startswith("text"):
                confidence = "high"
        elif offset is not None:
            drift = abs(float(segments[index].get("start") or 0.0) - offset)
            notes.append(f"offset would pick seg-{by_time} (drift {drift:.2f}s)")
    if confidence == "low" and needle:
        notes.append("no decisive text match")

    return {
        "transcript_id": transcript_id,
        "index": index,
        "offset_start": segments[index].get("start"),
        "offset_end": segments[index].get("end"),
        "method": method,
        "confidence": confidence,
        "ratio": round(ratio, 3),
        "note": "; ".join(notes),
    }


# ── Wikilink / shape normalisation ──────────────────────────────────────────

def flatten_wikilinks(value: Any) -> list[str]:
    """Recursively flatten wikilink references into plain strings."""
    if value is None:
        return []
    if isinstance(value, dict):
        for key in ("name", "ref", "id", "source", "value"):
            if key in value:
                return flatten_wikilinks(value[key])
        return []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(flatten_wikilinks(item))
        return out
    text = str(value).strip()
    if text.startswith("[[") and text.endswith("]]"):
        text = text[2:-2].strip()
    return [text] if text else []


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _coerce_enum(value: Any, allowed: set[str], fallback: str, aliases: dict | None = None) -> str:
    text = str(value or "").strip()
    if aliases:
        text = aliases.get(text.lower(), text)
    canonical = {a.lower(): a for a in allowed}
    return canonical.get(text.lower(), fallback)


# ── Build contract.json ─────────────────────────────────────────────────────

def build_contract(violation: dict, resolver: FrameworkResolver) -> tuple[dict, list[str]]:
    """Build contract.json from a schema-4.0 violation document."""
    warnings: list[str] = []
    vid = str(violation.get("violation_id") or "UNKNOWN")
    title = str(violation.get("title") or vid).strip()

    severity = _coerce_enum(violation.get("severity"), _VALID_SEVERITIES, "MEDIUM")
    if str(violation.get("severity") or "").strip().upper() != severity:
        warnings.append(f"severity {violation.get('severity')!r} normalised to {severity}")

    incident_name = " ".join(flatten_wikilinks(violation.get("incident"))) or str(
        violation.get("incident_id") or ""
    )
    case = {"id": violation.get("incident_id") or "", "name": incident_name}

    meta = violation.get("incident_meta") if isinstance(violation.get("incident_meta"), dict) else {}
    display = str(violation.get("incident_timestamp_display") or "")
    date = meta.get("date") or (display.split("—")[0].strip() if "—" in display else display)
    if not str(date or "").strip():
        date = "unknown"
        warnings.append(f"{violation.get('violation_id')}: incident has no date; recorded as 'unknown'")
    location = meta.get("location")
    if not str(location or "").strip():
        location = "unknown"
        warnings.append(
            f"{violation.get('violation_id')}: incident has no location; recorded as 'unknown'"
        )
    incident = {
        "date": str(date),
        "location": str(location),
        "flight": meta.get("flight"),
        "operator": meta.get("operator"),
        "clock_time_estimate": meta.get("clock_time_estimate")
        or violation.get("incident_timestamp"),
    }
    clock_confidence = meta.get("clock_time_confidence")
    if clock_confidence:
        clock_confidence = str(clock_confidence).strip()
        if clock_confidence not in _VALID_CLOCK_CONFIDENCE:
            warnings.append(
                f"{violation.get('violation_id')}: clock_time_confidence "
                f"{clock_confidence!r} is not a model value; recorded as 'unknown'"
            )
            clock_confidence = "unknown"
        incident["clock_time_confidence"] = clock_confidence

    frameworks: dict[str, dict] = {}
    candidates: list[dict] = []
    for raw_article in violation.get("legal_basis") or []:
        if not isinstance(raw_article, dict):
            continue
        article_id = str(raw_article.get("article_id") or "").strip()
        if not article_id:
            continue
        status = str(raw_article.get("status") or "established").strip().lower()
        if status == "candidate":
            candidates.append(
                {
                    "candidate_article_id": article_id,
                    "candidate_name": str(raw_article.get("article_name") or article_id),
                    "framework_cache_status": str(
                        raw_article.get("framework_cache_status") or "not_in_bundle"
                    ),
                    "verification_required": list(
                        raw_article.get("verification_required") or []
                    ),
                    "preliminary_view": str(
                        raw_article.get("preliminary_view") or raw_article.get("nexus") or ""
                    ),
                    "history_note": str(raw_article.get("history_note") or ""),
                }
            )

        parts = article_id.split(".")
        article_jurisdiction = parts[0] if parts else ""
        raw_code = str(raw_article.get("framework_code") or "").strip()
        if not raw_code and len(parts) > 2:
            raw_code = parts[1]
        code, rel_file = resolver.resolve(raw_code, article_jurisdiction)
        if code is None:
            warnings.append(
                f"{article_id}: framework code {raw_code!r} has no file in the law corpus"
            )
            code = raw_code
        elif rel_file is None:
            warnings.append(f"{article_id}: {code} resolved but no corpus file matched")

        applicability = _coerce_enum(
            raw_article.get("applicability"),
            _VALID_APPLICABILITY,
            "supporting",
            aliases=_APPLICABILITY_ALIASES,
        )
        subsections = raw_article.get("subsections")
        if isinstance(subsections, (list, tuple)):
            subsections_invoked = [str(s).strip() for s in subsections if str(s).strip()]
        elif subsections is None:
            subsections_invoked = []
        else:
            subsections_invoked = [str(subsections).strip()]

        article = {
            "article_id": article_id,
            "article_name": str(raw_article.get("article_name") or article_id),
            "article_text": str(raw_article.get("verbatim_text") or "").strip(),
            "applicability_rationale": str(
                raw_article.get("applicability_rationale") or raw_article.get("nexus") or ""
            ).strip(),
            "duty_bearer": str(raw_article.get("duty_bearer") or "state"),
            "norm_type": _coerce_enum(
                raw_article.get("norm_type"), _VALID_NORM_TYPES, "definition"
            ),
            "applicability": applicability,
            "subsections_invoked": subsections_invoked,
            "status": status or "established",
        }

        fw = frameworks.setdefault(
            code,
            {
                "framework_code": code,
                "framework_name": code,
                "framework_file": rel_file,
                "articles": [],
            },
        )
        if rel_file and not fw.get("framework_file"):
            fw["framework_file"] = rel_file
        fw["articles"].append(article)

    cross_refs: list[dict] = []
    for ref in violation.get("cross_references") or []:
        if isinstance(ref, dict):
            cross_refs.append(
                {"ref": str(ref.get("ref") or ""), "relation": str(ref.get("relation") or "")}
            )
        else:
            text = " ".join(flatten_wikilinks(ref))
            if text:
                cross_refs.append({"ref": text, "relation": ""})

    open_questions: list[dict] = []
    for oq in violation.get("open_questions") or []:
        if not isinstance(oq, dict):
            continue
        priority = _coerce_enum(oq.get("priority"), _VALID_PRIORITY, "medium")
        open_questions.append(
            {
                "id": str(oq.get("id") or "").strip().strip("`"),
                "question": str(oq.get("question") or ""),
                "blocks_element": str(oq.get("blocks_element") or ""),
                "priority": priority,
            }
        )

    provenance = violation.get("provenance") or []
    contract = {
        "schema_version": str(violation.get("schema_version") or "4.0"),
        "violation_id": vid,
        "violation_number": vid,
        "title": title,
        "case": case,
        "jurisdiction": violation.get("jurisdiction") or "",
        "framework": {
            "codes": sorted(frameworks),
            "files": {c: f.get("framework_file") for c, f in sorted(frameworks.items())},
        },
        "category": violation.get("category") or "",
        "severity": severity,
        "confidence": violation.get("confidence"),
        "incident": incident,
        "incident_timestamp": violation.get("incident_timestamp") or "",
        "incident_timestamp_display": display,
        "allegation_summary": violation.get("allegation_summary") or "",
        "legal_basis": {"frameworks": list(frameworks.values())},
        "candidate_articles": candidates or (violation.get("candidate_articles") or []),
        "cross_references": cross_refs,
        "open_questions": open_questions,
        "related_violations": flatten_wikilinks(violation.get("related_violations")),
        "tags": list(violation.get("tags") or []),
        "_provenance": {
            "source": str(violation.get("__source_path__") or ""),
            "vault_operations": len(provenance) if isinstance(provenance, list) else 0,
            "converted_by": "examples/vault_to_bundle.py",
        },
    }
    return contract, warnings


# ── Build segments_manifest.json ────────────────────────────────────────────

def build_segments_manifest(
    violation: dict,
    transcripts: dict[str, dict],
    allow_weak: bool = False,
    deltas: dict[str, float] | None = None,
) -> tuple[dict, list[str]]:
    """Build segments_manifest.json, re-anchoring every segment id."""
    if deltas is None:
        deltas = estimate_clip_offset_delta(violation, transcripts)
    warnings: list[str] = []
    segments: list[dict] = []
    seen: set[str] = set()
    transcript_files: dict[str, str] = {}
    placeholders = 0
    available_files = {
        str(entry["doc"].get("transcript_id") or entry["path"].stem): entry["path"].name
        for entry in transcripts.values()
    }

    for raw_segment in violation.get("full_segments") or []:
        if not isinstance(raw_segment, dict):
            continue
        raw_id = str(raw_segment.get("segment_id") or "").strip()
        if not str(raw_segment.get("verbatim_es") or "").strip() and not str(
            raw_segment.get("translation_en") or ""
        ).strip():
            placeholders += 1
            continue
        anchor = reanchor_segment(raw_segment, transcripts, deltas)
        if anchor is None:
            warnings.append(f"{raw_id or '<no segment_id>'}: no canonical transcript matched")
            continue

        transcript_id = anchor["transcript_id"]
        if transcript_id in available_files:
            transcript_files[transcript_id] = available_files[transcript_id]
        else:
            warnings.append(f"{transcript_id}: no canonical transcript file on disk")
        seg_id = f"{transcript_id}.seg-{anchor['index']}"
        if seg_id in seen:
            continue
        seen.add(seg_id)

        if anchor["confidence"] == "low" and not allow_weak:
            warnings.append(
                f"{raw_id} -> {seg_id}: low-confidence anchor ({anchor['method']}); "
                "rerun with --allow-weak-anchors to accept"
            )
            continue

        provenance = f"reanchored from {raw_id} (method={anchor['method']}"
        provenance += f", confidence={anchor['confidence']}"
        if anchor.get("ratio"):
            provenance += f", text_ratio={anchor['ratio']}"
        provenance += ")"
        if anchor.get("note"):
            provenance += f"; {anchor['note']}"
        existing_notes = str(raw_segment.get("transcription_notes") or "").strip()

        segments.append(
            {
                "segment_id": seg_id,
                "legacy_segment_id": raw_id,
                "role_in_argument": str(raw_segment.get("role_in_argument") or "fact"),
                "audio_offset_start": anchor["offset_start"],
                "audio_offset_end": anchor["offset_end"],
                "verbatim_es": str(raw_segment.get("verbatim_es") or ""),
                "translation_en": str(raw_segment.get("translation_en") or ""),
                "transcription_notes": "; ".join(filter(None, [existing_notes, provenance])),
            }
        )

    manifest = {
        "schema_version": str(violation.get("schema_version") or "4.0"),
        "violation_id": str(violation.get("violation_id") or ""),
        "matched_audio_sources": sorted({s["segment_id"].split(".", 1)[0] for s in segments}),
        "total_segments_matched": len(segments),
        "segments": segments,
        "clip_offset_deltas": deltas or {},
        "transcript_files": transcript_files,
    }
    if placeholders:
        warnings.append(
            f"{placeholders} empty placeholder segment(s) in full_segments skipped"
        )
    return manifest, warnings


def _summarise_warnings(warnings: list[str], vid: str) -> list[str]:
    """Collapse repetitive per-reference warnings into counted summary lines."""
    counts: dict[str, int] = {}
    keep: list[str] = []
    for warning in warnings:
        if any(marker in warning for marker in _INFORMATIONAL_MARKERS):
            continue
        for marker, label in _REPEATED_WARNING_MARKERS:
            if marker in warning:
                counts[label] = counts.get(label, 0) + 1
                break
        else:
            keep.append(warning)
    if counts:
        detail = ", ".join(f"{label}: {count}" for label, count in sorted(counts.items()))
        keep.append(f"{vid}: {sum(counts.values())} dangling reference(s) dropped ({detail})")
    return keep


_INFORMATIONAL_MARKERS: tuple[str, ...] = (
    "empty placeholder segment(s) in full_segments skipped",
)

_REPEATED_WARNING_MARKERS: tuple[tuple[str, str], ...] = (
    ("has no re-anchored equivalent", "segment refs to unanchored vault segments"),
    ("link dropped", "nexus rows to unanchored vault segments"),
    ("rerun with --allow-weak-anchors", "segments rejected as low-confidence"),
    ("no canonical transcript matched", "segments with no matching transcript"),
)


# ── Translate the vault's layer objects into the model shapes ───────────────

def _candidate_record(raw: dict) -> dict | None:
    """Normalise a vault candidate article into ``models.CandidateArticle``."""
    candidate_id = str(raw.get("candidate_article_id") or raw.get("article_id") or "").strip()
    if not candidate_id:
        return None
    status = str(raw.get("framework_cache_status") or "").strip()
    if status not in _VALID_CANDIDATE_CACHE_STATUS:
        status = "not_in_bundle"
    verification = [str(v) for v in (raw.get("verification_required") or [])]
    return {
        "candidate_article_id": candidate_id,
        "candidate_name": str(raw.get("candidate_name") or raw.get("article_name") or candidate_id),
        "framework_cache_status": status,
        "verification_required": verification or ["Confirm this article exists and applies."],
        "preliminary_view": raw.get("preliminary_view") or None,
        "history_note": raw.get("history_note") or None,
    }


def _rewrite_prefix(value: str, old_prefix: str, new_prefix: str) -> str:
    """Replace ``old_prefix`` at the head of ``value`` with ``new_prefix``.

    Only fires when ``old_prefix`` is followed by a ``.``, so ``Art.193`` does
    not rewrite the head of an unrelated ``Art.1930`` id. Returns ``value``
    unchanged otherwise — the caller is rewriting an element-id *prefix*, not
    performing a substring replacement.
    """
    if value.startswith(old_prefix + "."):
        return new_prefix + value[len(old_prefix):]
    return value


def build_violation_document(
    violation: dict,
    contract: dict,
    manifest: dict,
    law_root: Path,
    transcript_dir: Path,
    bundle_dir: Path,
) -> tuple[dict, list[str]]:
    """Translate a vault violation into a complete ``models.Violation`` document.

    Writing the *final* shape rather than an intermediate is what keeps the
    vault's layer 3-5 data alive: ``refine_batch_core._normalize`` only reads
    ``segments`` and ``legal_basis`` and silently drops ``element_grids``,
    ``nexus_matrix``, ``authorities`` and ``confidence``. Because the document
    validates as a ``Violation``, the refiner loads it verbatim instead of
    falling back to that lossy path.
    """
    warnings: list[str] = []
    vid = str(contract.get("violation_id") or violation.get("violation_id") or "UNKNOWN")

    legacy_to_canonical = {
        str(seg.get("legacy_segment_id") or ""): str(seg.get("segment_id") or "")
        for seg in manifest.get("segments") or []
    }

    # ── Layer 1: evidence ───────────────────────────────────────────────────
    bundle_speaker_index = bundle_dir / "speaker_index.json"
    readers: dict[str, JsonTranscriptSource] = {}
    for transcript_id, filename in (manifest.get("transcript_files") or {}).items():
        path = transcript_dir / filename
        if not path.exists():
            warnings.append(f"{transcript_id}: transcript file missing ({path})")
            continue
        try:
            readers[transcript_id] = JsonTranscriptSource(
                path=path,
                bundle_uri=f"Transcripts/{filename}",
                speaker_index_path=bundle_speaker_index if bundle_speaker_index.exists() else None,
            )
        except JsonTranscriptSchemaError as exc:
            warnings.append(f"{transcript_id}: {exc}")

    segments: list[dict] = []
    for seg in manifest.get("segments") or []:
        seg_id = str(seg.get("segment_id") or "")
        # Split at the *last* dot: the local id is always ``seg-<index>`` and
        # the transcript id may in principle contain a dot. ``partition``
        # would split at the first, which silently mis-resolves any future
        # transcript whose id is dotted.
        transcript_id, _, local_id = seg_id.rpartition(".")
        reader = readers.get(transcript_id)
        parsed = reader.get_segment(local_id) if reader else None
        if reader is None or parsed is None:
            warnings.append(f"{seg_id}: cannot hydrate verbatim text from the transcript")
            continue
        verbatim = parsed["verbatim"] or str(seg.get("verbatim_es") or "")
        legacy_text = str(seg.get("verbatim_es") or "")
        source_filename = reader.source_uri().split("/")[-1]
        segments.append(
            {
                "segment_id": seg_id,
                "role_in_argument": str(seg.get("role_in_argument") or "fact"),
                "audio_offset_start": parsed["audio_offset_start"],
                "audio_offset_end": parsed["audio_offset_end"],
                "speaker": parsed["speaker"],
                "verbatim_es": verbatim,
                "verbatim_sha256": sha256_text(verbatim),
                "translation_en": str(seg.get("translation_en") or "") or legacy_text or verbatim,
                "transcription_notes": seg.get("transcription_notes"),
                "source_uri": f"Transcripts/{source_filename}#{local_id}",
                "source_sha256": reader.source_sha256(),
                "audio_uri": None,
            }
        )

    # ── Layers 2-5 ──────────────────────────────────────────────────────────
    framework_caches: list[dict] = []
    established_articles: list[dict] = []
    candidates: list[dict] = []
    seen_candidates: set[str] = set()
    for raw in contract.get("candidate_articles") or []:
        record = _candidate_record(raw) if isinstance(raw, dict) else None
        if record and record["candidate_article_id"] not in seen_candidates:
            seen_candidates.add(record["candidate_article_id"])
            candidates.append(record)
    for raw in violation.get("candidate_articles") or []:
        record = _candidate_record(raw) if isinstance(raw, dict) else None
        if record and record["candidate_article_id"] not in seen_candidates:
            seen_candidates.add(record["candidate_article_id"])
            candidates.append(record)

    for fw in (contract.get("legal_basis") or {}).get("frameworks") or []:
        code = str(fw.get("framework_code") or "LEGACY")
        rel_file = fw.get("framework_file")
        target = (law_root / str(rel_file)) if rel_file else None
        source: MarkdownFrameworkSource | None = None
        if target is not None and target.exists():
            source = MarkdownFrameworkSource(
                path=target,
                framework_code=code,
                bundle_uri=f"Legal framework/{_framework_bundle_name(code)}",
            )
            framework_caches.append(
                {
                    "framework_code": code,
                    "framework_name": str(fw.get("framework_name") or code),
                    "cache_file": source.cache_uri(),
                    "cache_file_sha256": source.cache_sha256(),
                    "cache_self_reported_sha256": source.declared_sha256(),
                    "articles_cached": source.articles_cached(),
                }
            )
        else:
            warnings.append(f"{code}: no law file in the corpus; its articles stay candidates")

        for article in fw.get("articles") or []:
            article_id = str(article.get("article_id") or "").strip()
            if not article_id:
                continue
            excerpt = str(article.get("article_text") or "").strip()
            article_number = article_id.rsplit(".Art.", 1)[-1].split(".")[0]
            body = source.get_article_body(article_number) if source else None

            if body and excerpt and excerpt in body:
                established_articles.append(
                    {
                        "article_id": article_id,
                        "article_name": str(article.get("article_name") or article_id),
                        "subsections_invoked": list(article.get("subsections_invoked") or []),
                        "verbatim_excerpt": excerpt,
                        "verbatim_excerpt_sha256": sha256_text(excerpt),
                        "framework_code": code,
                        "framework_cache_status": "verified_in_bundle",
                        "duty_bearer": str(article.get("duty_bearer") or "state"),
                        "norm_type": str(article.get("norm_type") or "definition"),
                        "applicability": str(article.get("applicability") or "supporting"),
                        "applicability_rationale": str(
                            article.get("applicability_rationale") or "legacy import"
                        ),
                    }
                )
                continue

            if body is None:
                reason = "article body not in the framework cache"
            elif not excerpt:
                reason = "no excerpt supplied"
            else:
                reason = "excerpt is not a substring of the cached body"
            warnings.append(f"{article_id}: candidate ({reason})")
            if article_id not in seen_candidates:
                seen_candidates.add(article_id)
                candidates.append(
                    {
                        "candidate_article_id": article_id,
                        "candidate_name": str(article.get("article_name") or article_id),
                        "framework_cache_status": "not_in_bundle",
                        "verification_required": [
                            f"Fetch verbatim text for {article_id} and confirm the excerpt: {reason}",
                        ],
                        "preliminary_view": excerpt[:240] or None,
                        "history_note": str(article.get("applicability_rationale") or "")[:512] or None,
                    }
                )

    # ── Layer 3: element grids ──────────────────────────────────────────────
    # ``verifier.E_GRID_UNKNOWN_ARTICLE`` makes a grid on an article that is
    # not in ``established_articles`` an error, and ``confidence
    # .derive_confidence`` weights grids through the article's
    # ``applicability`` — so a grid for a demoted article is both a hard
    # failure and an unweighted input. Drop it, with a warning that names the
    # article, so the loss is visible.
    established_article_ids = {a["article_id"] for a in established_articles}

    # Canonical prefix map: the article_id spelling the established articles
    # carry, keyed by the hierarchy-insensitive ``(framework, number)`` pair.
    # Populated *before* grids are processed so the rewrite happens as each
    # grid is translated.
    canonical_prefix: dict[tuple[str, str], str] = {}
    for a in established_articles:
        split = split_article_id(a["article_id"])
        if split is not None:
            canonical_prefix.setdefault(split, a["article_id"])

    raw_grids = violation.get("element_grids")

    # Dispatch on the vault's element_grids shape. Schema 4.0 emits a dict
    # keyed by article_id; schema 3.0 emits a list of {article_id, elements}.
    # The previous single-shape handling silently dropped the list form.
    grids_iter: list[tuple[str, list, str]] = []
    if isinstance(raw_grids, dict):
        for aid, elements in raw_grids.items():
            if isinstance(elements, list):
                grids_iter.append((str(aid), elements, ""))
    elif isinstance(raw_grids, list):
        for g in raw_grids:
            if not isinstance(g, dict):
                continue
            aid = str(g.get("article_id") or "")
            elems = g.get("elements")
            short = str(g.get("article_short") or "")
            if aid and isinstance(elems, list):
                grids_iter.append((aid, elems, short))
        if raw_grids:
            warnings.append(
                f"element_grids is a list ({len(raw_grids)} item(s), schema 3.0 "
                "shape); translated per-item"
            )
    elif raw_grids is None:
        grids_iter = []
    else:
        warnings.append(
            f"element_grids has unrecognised type {type(raw_grids).__name__}; dropped"
        )

    element_grids: list[dict] = []
    prefix_rewrites: dict[str, str] = {}  # old article_id -> new article_id

    for article_id_in, elements, grid_short in grids_iter:
        # Canonicalize the grid's article_id to match the established article
        # it belongs to, and remember the mapping so the nexus pass can apply
        # the same rewrite to norm_id / element_id.
        article_id = article_id_in
        split = split_article_id(article_id_in)
        if split is not None:
            canonical = canonical_prefix.get(split)
            if canonical and canonical != article_id_in:
                prefix_rewrites[article_id_in] = canonical
                article_id = canonical
                warnings.append(
                    f"element grid {article_id_in}: article prefix canonicalized "
                    f"to {canonical} (matches the established article)"
                )

        translated: list[dict] = []
        article_short = grid_short
        for element in elements:
            if not isinstance(element, dict):
                continue
            # The vault puts ``article_short`` on the grid in schema 3.0 and
            # on each element in schema 4.0; both spellings are accepted.
            article_short = article_short or str(element.get("article_short") or "")

            evidence = []
            for raw_fact in element.get("evidence") or []:
                mapped = legacy_to_canonical.get(str(raw_fact).strip())
                if mapped:
                    evidence.append(mapped)
                else:
                    warnings.append(
                        f"element {element.get('element_id')}: evidence {raw_fact!r} "
                        "has no re-anchored equivalent"
                    )

            status = str(element.get("status") or "").strip()
            if not status:
                status = "not_developed"
            elif status not in _VALID_PROOF_STATUS:
                warnings.append(
                    f"element {element.get('element_id')}: proof_status {status!r} "
                    "is not a model value; recorded as not_developed"
                )
                status = "not_developed"

            # Rewrite the element_id prefix if the grid's article_id changed.
            raw_element_id = str(element.get("element_id") or "")
            if article_id_in != article_id:
                raw_element_id = _rewrite_prefix(raw_element_id, article_id_in, article_id)

            translated.append(
                {
                    "element_id": raw_element_id,
                    "label": str(element.get("element_name") or element.get("label") or ""),
                    "doctrinal_basis": element.get("doctrinal_basis") or None,
                    "proof_status": status,
                    "proof_evidence_segments": evidence,
                    "argument_es": str(
                        element.get("argument") or element.get("argument_es") or ""
                    ),
                    "weaknesses": [str(w) for w in (element.get("weaknesses") or [])],
                    "open_questions": [
                        str(o).strip("`") for o in (element.get("open_questions") or [])
                    ],
                }
            )
        if not translated:
            continue
        if article_id not in established_article_ids:
            warnings.append(
                f"element grid for {article_id} ({len(translated)} element(s)) "
                "dropped: the article is not in established_articles, so the "
                "grid would be an orphan (V11 E_GRID_UNKNOWN_ARTICLE) and "
                "would carry no confidence weight"
            )
            continue
        element_grids.append(
            {
                "article_id": article_id,
                "article_short": article_short or article_id,
                "elements": translated,
            }
        )

    # ── Layer 4: nexus matrix ───────────────────────────────────────────────
    grid_article_ids = {g["article_id"] for g in element_grids}
    nexus_matrix: list[dict] = []
    orphaned_norm_rows: dict[str, int] = {}
    for entry in violation.get("nexus_matrix") or []:
        if not isinstance(entry, dict):
            continue
        raw_fact = str(entry.get("fact_id") or "").strip()
        fact_id = legacy_to_canonical.get(raw_fact)
        if not fact_id:
            warnings.append(
                f"nexus {entry.get('element_id')}: fact {raw_fact!r} has no "
                "re-anchored equivalent; link dropped"
            )
            continue

        norm_id = str(entry.get("norm_id") or "")
        # Apply the prefix rewrite the grid pass recorded. A nexus row whose
        # norm_id pointed at the pre-canonicalization article_id would
        # otherwise be reported as an orphan even though its grid now exists.
        if norm_id in prefix_rewrites:
            norm_id = prefix_rewrites[norm_id]
        if norm_id not in grid_article_ids:
            orphaned_norm_rows[norm_id] = orphaned_norm_rows.get(norm_id, 0) + 1
            continue

        strength = str(entry.get("strength") or "").strip().lower()
        if strength not in {"high", "medium", "low"}:
            warnings.append(f"nexus {fact_id}: strength {strength!r} is not a model value")
            strength = "low"

        element_id = str(entry.get("element_id") or "")
        for old, new in prefix_rewrites.items():
            if element_id.startswith(old + "."):
                element_id = new + element_id[len(old):]
                break

        nexus_matrix.append(
            {
                "fact_id": fact_id,
                "norm_id": norm_id,
                "element_id": element_id,
                "nexus_type": str(entry.get("nexus_type") or ""),
                "strength": strength,
                "rationale_oneline": str(entry.get("rationale_oneline") or ""),
            }
        )
    for norm_id, count in sorted(orphaned_norm_rows.items()):
        warnings.append(
            f"nexus: {count} row(s) for {norm_id or '<empty norm_id>'} dropped: the "
            "article has no element grid, so the link would be an orphan "
            "(V11 E_NEXUS_UNKNOWN_NORM)"
        )

    # ── Layer 5: authorities ────────────────────────────────────────────────
    authorities: list[dict] = []
    for entry in violation.get("authorities") or []:
        if not isinstance(entry, dict):
            continue
        authority_id = str(entry.get("authority_id") or entry.get("id") or "").strip()
        if not authority_id:
            continue
        authority_type = str(entry.get("type") or "").strip()
        if authority_type not in _VALID_AUTHORITY_TYPES:
            warnings.append(
                f"authority {authority_id}: type {authority_type!r} is not a model value"
            )
            authority_type = "doctrine"
        query = str(entry.get("research_query") or "").strip()
        authorities.append(
            {
                "authority_id": authority_id,
                "type": authority_type,
                "supports": [
                    str(s)
                    for s in (entry.get("supports") or entry.get("supports_elements") or [])
                ],
                "research_query": query,
                "proposition_to_verify": str(entry.get("proposition_to_verify") or query),
                "verified": False,
            }
        )

    # ── Auxiliary ───────────────────────────────────────────────────────────
    open_questions = [
        {
            "id": str(oq.get("id") or ""),
            "question": str(oq.get("question") or ""),
            "blocks_element": str(oq.get("blocks_element") or "") or None,
            "priority": str(oq.get("priority") or "medium"),
            "obtaining_method": oq.get("obtaining_method") or None,
        }
        for oq in contract.get("open_questions") or []
        if isinstance(oq, dict)
    ]
    cross_references = [
        {"ref": str(ref.get("ref") or ""), "relation": str(ref.get("relation") or "legacy_reference")}
        for ref in contract.get("cross_references") or []
        if isinstance(ref, dict) and ref.get("ref")
    ]

    document: dict[str, Any] = {
        "violation_id": vid,
        "title": str(contract.get("title") or vid),
        "severity": str(contract.get("severity") or "MEDIUM"),
        "schema_version": "3.0",
        "incident": contract.get("incident") or {"date": "unknown", "location": "unknown"},
        "segments": segments,
        "framework_caches": framework_caches,
        "established_articles": established_articles,
        "candidate_articles": candidates,
        "element_grids": element_grids,
        "nexus_matrix": nexus_matrix,
        "authorities": authorities,
        # Left null on purpose: ``refine_batch_core`` derives it from the element
        # grids it can now see, and V08 compares that derivation to the contract.
        "confidence": None,
        "open_questions": open_questions,
        "cross_references": cross_references,
        "provenance": _provenance_entries(violation.get("provenance"), vid, warnings),
    }
    return document, warnings


def _provenance_entries(raw: Any, vid: str, warnings: list[str]) -> list[dict]:
    """Normalise the vault audit trail into ``models.ProvenanceEntry`` records.

    ``ProvenanceEntry.layer`` is bounded 1-5 (or null), but 51 vault entries
    corpus-wide use ``layer: 0`` to mean "whole-document rebuild, not tied to a
    layer". Those become ``layer=None`` with the original value kept in the note
    so the audit trail stays legible.

    The timestamp is *validated* here but stored as the original string.
    ``ProvenanceEntry.timestamp`` is a ``datetime`` and Pydantic parses an
    ISO-8601 string into one at ``model_validate`` time, so the string form
    round-trips. What this function needs to prevent is different: a
    non-ISO timestamp would make ``Violation.model_validate`` fail, which
    causes ``refine_batch_core._load_violation`` to silently fall back to the
    legacy normalizer and drop every layer 3-5 record — the failure mode this
    module exists to prevent. Parsing here, but keeping the string, means a
    single bad entry is skipped with a warning instead of poisoning the whole
    document.
    """
    entries: list[dict] = []
    for index, item in enumerate(raw or []):
        if not isinstance(item, dict):
            warnings.append(f"{vid}: provenance[{index}] is not an object; skipped")
            continue
        note = str(item.get("note") or "")
        layer = item.get("layer")
        if isinstance(layer, bool) or not isinstance(layer, int) or not 1 <= layer <= 5:
            if layer is not None:
                note = f"[vault layer={layer}] {note}".strip()
            layer = None
        timestamp = item.get("timestamp")
        if not timestamp:
            warnings.append(f"{vid}: provenance[{index}] has no timestamp; skipped")
            continue
        # Validate that Pydantic will be able to parse it, but keep the string.
        try:
            datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            warnings.append(
                f"{vid}: provenance[{index}] timestamp {timestamp!r} is not "
                "ISO-8601; skipped"
            )
            continue
        entries.append(
            {
                "timestamp": str(timestamp),
                "actor": str(item.get("actor") or "vault_import"),
                "operation": str(item.get("operation") or "vault_import"),
                "layer": layer,
                "note": note,
            }
        )
    return entries


def _validate_document(document: dict, vid: str) -> list[str]:
    """Fail loudly in the converter if the document would not load verbatim.

    ``refine_batch_core._load_violation`` swallows a model error and silently
    re-normalises through the lossy legacy path, so drift here would otherwise
    go unnoticed until the layer 3-5 data disappeared downstream.
    """
    try:
        Violation.model_validate(document)
    except Exception as exc:  # noqa: BLE001 - surfaced, never hidden
        return [f"{vid}: staged document does not validate as Violation: {exc}"]
    return []


# ── Stage the final bundle ──────────────────────────────────────────────────

def _framework_bundle_name(code: str) -> str:
    """Filename to use for a framework inside ``Legal framework/``.

    ``refine_batch_core._discover_frameworks`` keys readers by
    ``md.stem.split("_")[0].upper()``, and ``validation.v03``/``v04`` look the
    reader up by the article's ``framework_code``. Preserving the corpus
    filename (``CodigoPenal.md`` → ``CODIGOPENAL``, ``L19496_LPDC.md`` →
    ``L19496``) makes both miss the reader and report the law as unregistered
    even though the file is present and correct. Naming the symlink after the
    code makes the derived key equal the key that is looked up.

    Codes containing ``_`` cannot round-trip through that rule at all (the
    first token wins), which ``stage_bundle`` warns about.
    """
    return f"{code}.md"


def _ensure_symlink(link: Path, target: Path) -> None:
    """Point ``link`` at ``target`` (relative), replacing a stale link."""
    if not target.exists():
        raise FileNotFoundError(str(target))
    if link.is_symlink():
        if link.resolve() == target.resolve():
            return
        link.unlink()
    elif link.exists():
        raise IsADirectoryError(f"{link} exists and is not a symlink")
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(os.path.relpath(target, link.parent))


def stage_bundle(
    bundle_dir: Path,
    violation: dict,
    contract: dict,
    manifest: dict,
    law_root: Path,
    transcript_dir: Path,
    speaker_index: Path | None = None,
) -> list[str]:
    """Assemble the final ``build/<VID>/`` layout that ``refine_batch`` reads.

    Returns non-fatal warnings. A document that would fail
    ``Violation.model_validate`` is a **fatal** error: writing it to disk
    would let the refiner silently fall back to the lossy legacy normalizer
    and drop every layer 3-5 record. In that case the invalid document is
    saved as ``<VID>.json.invalid`` for inspection and any stale
    ``<VID>.json`` from a previous successful run is removed before the
    exception propagates.
    """
    warnings: list[str] = []
    vid = bundle_dir.name

    for transcript_id, filename in (manifest.get("transcript_files") or {}).items():
        target = transcript_dir / filename
        if not target.exists():
            warnings.append(f"{transcript_id}: transcript file missing ({target})")
            continue
        _ensure_symlink(bundle_dir / "Transcripts" / filename, target)

    if speaker_index is not None:
        if speaker_index.exists():
            _ensure_symlink(bundle_dir / "speaker_index.json", speaker_index)
        else:
            warnings.append(f"speaker_index.json missing ({speaker_index})")

    for fw in (contract.get("legal_basis") or {}).get("frameworks") or []:
        code = str(fw.get("framework_code") or "")
        rel_file = fw.get("framework_file")
        if not rel_file:
            warnings.append(f"{code or '<unknown>'}: no law file resolved; articles stay candidates")
            continue
        target = law_root / str(rel_file)
        if not target.exists():
            warnings.append(f"{code}: law file not found ({target})")
            continue
        if "_" in code:
            warnings.append(
                f"{code}: framework code contains '_', which "
                "refine_batch_core._discover_frameworks truncated to "
                f"{code.split('_')[0].upper()}; V03/V04 will report this law as unregistered"
            )
        _ensure_symlink(bundle_dir / "Legal framework" / _framework_bundle_name(code), target)

    document, doc_warnings = build_violation_document(
        violation, contract, manifest, law_root, transcript_dir, bundle_dir
    )
    warnings += doc_warnings

    validation_errors = _validate_document(document, vid)
    if validation_errors:
        # Refuse to write an invalid document. Downstream, ``_load_violation``
        # would swallow the model error and re-normalize through the lossy
        # legacy path, so a written-and-invalid file is worse than no file:
        # it looks final and behaves like a staging artifact.
        invalid_path = bundle_dir / f"{vid}.json.invalid"
        invalid_path.write_text(
            json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        stale = bundle_dir / f"{vid}.json"
        if stale.exists():
            stale.unlink()
        raise ValueError(
            "; ".join(validation_errors)
            + f" — invalid document saved as {invalid_path.name}"
        )

    (bundle_dir / f"{vid}.json").write_text(
        json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if _reconcile_contract_confidence(contract, document, vid, warnings):
        (bundle_dir / "contract.json").write_text(
            json.dumps(contract, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    return warnings


def _reconcile_contract_confidence(
    contract: dict, document: dict, vid: str, warnings: list[str]
) -> bool:
    """Stop ``contract.json`` from asserting a confidence the bundle contradicts.

    The vault keeps a confidence *snapshot* that ``refine_batch_core
    .attach_confidence`` unconditionally recomputes from ``element_grids``,
    and ``validation.v08_contract_consistency`` treats a dict-shaped
    confidence as a *live* assertion (only a bare scalar is downgraded to
    "legacy snapshot" and merely warned about) — so a snapshot the bundle's
    own data does not reproduce becomes a V08 FAIL that no amount of faithful
    translation can clear. The snapshot is preserved as
    ``contract["_vault_confidence"]`` and the divergence is reported with both
    numbers. Returns True when ``contract`` was modified.
    """
    snapshot = contract.get("confidence")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("value"), (int, float)):
        return False
    try:
        violation = Violation.model_validate(document)
    except Exception:  # pylint: disable=broad-except
        return False
    derived = derive_confidence(violation)
    if abs(float(snapshot["value"]) - derived.value) < 1e-9:
        return False
    contract["_vault_confidence"] = snapshot
    contract.pop("confidence", None)
    warnings.append(
        f"{vid}: vault confidence snapshot {snapshot['value']} is not reproduced by the "
        f"bundle data (derived {derived.value}, components {derived.components}); moved to "
        "contract._vault_confidence and dropped from the contract so V08 does not assert "
        "a value the bundle contradicts"
    )
    return True


def load_violation(path: Path) -> dict:
    """Read a schema-4.0 violation document and tag it with its source path."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: expected a JSON object")
    if "segments" in doc and "full_segments" not in doc:
        raise ValueError(f"{path}: looks like a transcript, not a violation")
    doc["__source_path__"] = str(path)
    return doc


def convert_one(
    json_path: Path,
    output_root: Path,
    transcripts: dict[str, dict],
    resolver: FrameworkResolver,
    allow_weak: bool = False,
    stage: bool = True,
    law_root: Path | None = None,
    transcript_dir: Path | None = None,
    speaker_index: Path | None = None,
) -> tuple[Path, list[str]]:
    """Convert one vault JSON document into a bundle directory."""
    violation = load_violation(json_path)
    vid = str(violation.get("violation_id") or json_path.stem)
    bundle_dir = output_root / vid
    bundle_dir.mkdir(parents=True, exist_ok=True)

    contract, contract_warnings = build_contract(violation, resolver)
    (bundle_dir / "contract.json").write_text(
        json.dumps(contract, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    manifest, manifest_warnings = build_segments_manifest(
        violation, transcripts, allow_weak
    )
    (bundle_dir / "segments_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    warnings = contract_warnings + manifest_warnings
    if stage:
        warnings += stage_bundle(
            bundle_dir,
            violation,
            contract,
            manifest,
            law_root if law_root is not None else DEFAULT_LAW_ROOT,
            transcript_dir if transcript_dir is not None else DEFAULT_TRANSCRIPT_DIR,
            speaker_index if speaker_index is not None else DEFAULT_SPEAKER_INDEX,
        )
        (bundle_dir / "conversion_warnings.json").write_text(
            json.dumps(warnings, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return bundle_dir, _summarise_warnings(warnings, vid)


def find_violation_path(violation_id: str, source_root: Path) -> Path | None:
    """Locate ``<violation_id>.json`` directly under ``source_root``."""
    path = source_root / f"{violation_id}.json"
    return path if path.is_file() else None


def _vault_confidence_value(path: Path) -> float:
    """Declared vault confidence, or ``-1.0`` when absent/unreadable."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # pylint: disable=broad-except
        return -1.0
    snapshot = raw.get("confidence")
    if isinstance(snapshot, dict) and isinstance(snapshot.get("value"), (int, float)):
        return float(snapshot["value"])
    return -1.0


def _revision_sort_key(path: Path) -> tuple[float, int, str]:
    """Rank competing revisions of one violation."""
    return (-_vault_confidence_value(path), len(path.name), path.name)


def _prefer_authoritative_revisions(paths: list[Path]) -> list[Path]:
    """Reduce vault files to one authoritative revision per ``violation_id``.

    ``convert_one`` keys the bundle directory off the *declared* violation id,
    so two files declaring the same id write the same ``build/<VID>`` and the
    survivor depends on glob order. The LA8159 vault really does this: ``BR-001``
    is declared by three files. Byte-identical copies are dropped by content
    hash, then the highest vault confidence wins, and every discarded file is
    named so the choice is auditable.
    """
    groups: dict[str, list[Path]] = {}
    order: list[str] = []
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            vid = str(raw.get("violation_id") or path.stem)
        except Exception:  # pylint: disable=broad-except
            vid = path.stem
        if vid not in groups:
            groups[vid] = []
            order.append(vid)
        groups[vid].append(path)

    kept: list[Path] = []
    for vid in order:
        candidates = groups[vid]
        by_hash: dict[str, list[Path]] = {}
        hash_order: list[str] = []
        for path in candidates:
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                digest = f"unreadable:{path}"
            if digest not in by_hash:
                by_hash[digest] = []
                hash_order.append(digest)
            by_hash[digest].append(path)

        unique: list[Path] = []
        for digest in hash_order:
            siblings = by_hash[digest]
            best = min(siblings, key=_revision_sort_key)
            unique.append(best)
            if len(siblings) > 1:
                others = ", ".join(p.name for p in siblings if p is not best)
                print(
                    f"{others} is byte-identical to {best.name}; skipping",
                    file=sys.stderr,
                )

        winner = min(unique, key=_revision_sort_key)
        kept.append(winner)
        if len(candidates) > 1:
            discarded = ", ".join(
                f"{p.name} (vault confidence {_vault_confidence_value(p)})"
                for p in candidates
                if p is not winner
            )
            print(
                f"Duplicate violation_id {vid!r}: keeping {winner.name} "
                f"(vault confidence {_vault_confidence_value(winner)}); discarded {discarded}",
                file=sys.stderr,
            )
    return kept


def _resolve_inputs(args: argparse.Namespace) -> list[Path]:
    """Turn CLI arguments into an explicit list of violation JSON paths."""
    paths: list[Path] = []
    for spec in args.violation:
        candidate = Path(spec)
        if candidate.suffix == ".json":
            if not candidate.is_file():
                print(f"File not found: {candidate}", file=sys.stderr)
            else:
                paths.append(candidate)
            continue
        found = find_violation_path(spec, args.source)
        if found is None:
            print(f"Violation {spec} not found in {args.source}", file=sys.stderr)
        else:
            paths.append(found)

    if args.all:
        pattern = f"{args.jurisdiction}-*.json" if args.jurisdiction else "*.json"
        paths.extend(sorted(p for p in args.source.glob(pattern) if p.is_file()))

    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return _prefer_authoritative_revisions(unique)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.violation and not args.all:
        print("Specify one or more violation IDs, or --all.", file=sys.stderr)
        return 1
    if not args.source.is_dir():
        print(f"Vault source not found: {args.source}", file=sys.stderr)
        return 1

    inputs = _resolve_inputs(args)
    if not inputs:
        print("No violations matched.", file=sys.stderr)
        return 1

    transcripts = build_transcript_index(args.transcript_dir)
    if not transcripts:
        print(
            f"No canonical transcripts found in {args.transcript_dir}; segment ids "
            "cannot be re-anchored.",
            file=sys.stderr,
        )
        return 1
    resolver = FrameworkResolver(args.law_root)
    if not resolver.codes:
        print(
            f"No law registry at {args.law_root}/_mapping/law_registry.json; framework "
            "symlinks will be unresolved.",
            file=sys.stderr,
        )

    results: list[dict] = []
    warning_count = 0
    for json_path in inputs:
        try:
            bundle_dir, warnings = convert_one(
                json_path,
                args.output,
                transcripts,
                resolver,
                args.allow_weak_anchors,
                stage=not args.inputs_only,
                law_root=args.law_root,
                transcript_dir=args.transcript_dir,
                speaker_index=args.speaker_index,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            results.append({"violation_id": json_path.stem, "ok": False, "error": str(exc)})
            warning_count += 1
            continue

        manifest = json.loads(
            (bundle_dir / "segments_manifest.json").read_text(encoding="utf-8")
        )
        warning_count += len(warnings)
        results.append(
            {
                "violation_id": bundle_dir.name,
                "ok": True,
                "bundle": str(bundle_dir),
                "segments": manifest.get("total_segments_matched", 0),
                "sources": manifest.get("matched_audio_sources", []),
                "warnings": warnings,
            }
        )

    ok = sum(1 for r in results if r.get("ok"))
    print(json.dumps({"converted": ok, "warnings": warning_count, "results": results}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())