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

Both data trees are the repo's own, so a run needs no server paths:
``data/transcripts/json`` for re-anchoring and ``data/law`` (plus its
``_mapping/law_registry.json``) for framework resolution. Framework codes come
from that registry and are never mirrored here.

Segment re-anchoring
--------------------
``full_segments[].segment_id`` uses the *legacy render* numbering, which is
stale: ``transcription`` re-rendered every transcript (header repair + speaker
consolidation), so the indices moved and the old ids now point at the wrong
utterance. Verified example — vault ``STG-7.seg-44`` (403.07-406.41 s,
"quando tu le diga que no hay ninguna agression…") is ``seg-40`` in the
current render, with byte-identical text *and* offsets.

Every segment is therefore re-anchored against the canonical transcript in
``data/transcripts/json/`` using two independent signals (normalized text
similarity and audio offset), and the *current* index is emitted as
``<transcript_id>.seg-<index>`` — the shape ``JsonTranscriptSource`` composes,
which also joins to the ``reviewed_transcripts`` collection. The original vault
id and the anchor method are preserved in ``transcription_notes`` rather than
discarded, and every weak anchor is reported.

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
from pathlib import Path
from typing import Any, Iterable

# Runnable as ``python examples/vault_to_bundle.py`` from the repo root without
# needing PYTHONPATH set by hand.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from violation_pack._utils import sha256_text  # noqa: E402
from violation_pack.confidence import derive_confidence  # noqa: E402
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
    # Pinned by evidence, not by name: 19 of the 44 BDM verbatims longer than 12
    # chars appear verbatim in this document and none appear in
    # ``Terminal_2_full`` (the lost-phone report, a different recording). Note
    # the vault's declared offsets (0.37-193.25 s) are relative to the original
    # clip, not to this "Full Consolidated" recording where the same speech sits
    # at 878-1071 s, so the offset fallback cannot anchor these segments and
    # they are recovered by text alone.
    (re.compile(r"^(GRU_Airport_Full)$"), "BDM"),
)

#: Enum domains enforced by ``violation_pack.refine_batch_core._normalize``.
#: Values outside these sets are downgraded there anyway; normalising up-front
#: makes the staged contract self-consistent and the downgrade visible.
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
#: Mapped to the contract's own fallback (``supporting``) so the downgrade is
#: explicit and reportable instead of incidental.
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
             "the final bundle (Transcripts/, Legal framework/, <VID>.json). Note "
             "that confidence reconciliation needs the staged document, so an "
             "inputs-only contract keeps the raw vault snapshot and may still "
             "trip V08 when fed straight to refine_batch.",
    )
    return p.parse_args(argv)


# ── Framework code resolution (derived from the registry, never mirrored) ───

#: Legacy codes that appear in vault ``article_id``s but are not an ELI code in
#: ``data/law/_mapping/law_registry.json``. Each alias is pinned to the evidence
#: that justifies it; ``None`` means the corpus has no file at all.
_LEGACY_CODE_ALIASES: dict[tuple[str, str], str | None] = {
    # CL.CP.Art.412 ("Es calumnia la imputacion…") / Art.211 -> Código Penal.
    ("CL", "CP"): "CPCL",
    # BR.CP.Art.140 ("Injuriar alguém") / Art.147 ("Ameaçar alguém") -> DL 2848.
    ("BR", "CP"): "CPB",
    # CL.CPR.Art.19 -> "Constitucion Politica de la Republica".
    ("CL", "CPR"): "CONST",
    # BR.ABEAR.CODECONDUCT.S1 -> Código de Conduta ABEAR, §1.
    ("BR", "ABEAR"): "ABEAR_COC",
    # ``LEY<n>`` spellings of codes the registry knows as ``L<n>``.
    ("CL", "LEY16752"): "L16752",
    ("CL", "LEY20285"): "L20285",
    # Ley 19.880 (bases del procedimiento administrativo) is NOT in the corpus.
    ("CL", "LEY19880"): None,
    # BR.CF.Art.N -> Constituição Federal de 1988 (registry ``CONST`` -> BR/CF88.md).
    # Pinned by evidence, not name similarity: BR-014's own contract resolves
    # ``CONST`` while its ``CF`` entry fails, i.e. the vault spells one document
    # two ways.
    ("BR", "CF"): "CONST",
    # BR.LEI9784.Art.N -> Lei 9.784 (administrative procedure), registry ``L9784``
    # -> BR/L9784.md. Same ``LEI<n>`` vs ``L<n>`` spelling gap as the CL entries
    # above; BR-014 again carries both spellings at once.
    ("BR", "LEI9784"): "L9784",
    # INT.BR-CL.Art.N -> the Brazil-Chile Joint Declaration 2024, whose registry
    # code is ``BRCL`` (the dash is dropped in the ELI). INT-018 is the only citer.
    ("INT", "BR-CL"): "BRCL",
}


class FrameworkResolver:
    """Maps an ``article_id`` code to a law markdown file in the corpus.

    The allow-list is *derived* from the registry's ELIs rather than mirrored in
    a hand-maintained table: hardcoded copies drift silently and drop newly
    bundled frameworks (the legacy ``FRAMEWORK_MD_MAP`` mapped ``CL.CP`` to the
    Penal Code's *chip-encoding* section, which is a different law).
    """

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
        """Every framework code the registry knows about."""
        return set(self._by_code)

    def resolve(self, code: str, jurisdiction: str) -> tuple[str | None, str | None]:
        """Return ``(registry_code, relative_path)`` for an article code.

        ``(None, None)`` means the code has no file in the corpus, which is a
        reportable gap rather than something to paper over.
        """
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
        """Disambiguate codes that exist in several jurisdictions/languages.

        ``CC`` is both the Brazilian Civil Code and the Chilean one; ``CONST``
        is both CF/88 and the Chilean Constitution. Prefer the file whose
        leading path segment matches the article's jurisdiction, then the
        vault's language.
        """
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
    """Map a bundle source token (``STG-7``) to its canonical transcript.

    ``full_segments[]`` references sources by token, but the transcript files
    are named by ``transcript_id``. ``audio_id`` is the only reliable bridge,
    so index every canonical document by it — including the ones a violation
    never lists in ``transcripts[]`` (33 violations reference ``STG-29`` with an
    empty list).
    """
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
    """
    if not needle or len(needle) < _MIN_TEXT_MATCH_LEN:
        return None, 0.0, 0.0
    scored = [
        (difflib.SequenceMatcher(None, needle, _norm_text(seg.get("text"))).ratio(), i)
        for i, seg in enumerate(segments)
    ]
    scored.sort(reverse=True)
    if not scored:
        return None, 0.0, 0.0
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    return scored[0][1], scored[0][0], runner_up


def _best_in_window(
    segments: list[dict], needle: str, center: int, window: int = 2
) -> tuple[int, float]:
    """Return ``(index, ratio)`` for the best match within ``window`` of ``center``.

    Used to correct a calibrated clip offset, which is only good to about a
    second and so can swap neighbouring segments. Ties resolve toward
    ``center``: when the transcript repeats a phrase, proximity to the timing
    prediction keeps the two occurrences apart instead of collapsing both onto
    whichever copy scores a hair higher.
    """
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


#: Text similarity at or above which a match is treated as decisive evidence
#: rather than a hint. Duplicated from the branch below so the calibration pass
#: and the anchoring pass agree on what counts as proof.
_TEXT_DECISIVE = 0.90

#: Clip-offset calibration bounds. A clip cut from a longer recording produces a
#: constant offset between its own timings and the consolidated transcript, and
#: these keep the inference from engaging on noise: enough samples to be robust,
#: a magnitude that is unmistakably not "already aligned", and a cluster tight
#: enough that a bimodal spread (the signature of a wrong transcript) fails.
_DELTA_MIN_SAMPLES = 3
_DELTA_MIN_MAGNITUDE = 30.0
_DELTA_TOLERANCE = 3.0
_DELTA_MIN_AGREEMENT = 0.6


def estimate_clip_offset_delta(
    violation: dict, transcripts: dict[str, dict]
) -> dict[str, float]:
    """Infer a per-source constant offset between a vault clip and its audio.

    Some vault clips are excerpts of a longer session, so ``audio_offset_start``
    is relative to the clip while the canonical transcript runs over the whole
    recording. ``BDM`` is the worked example: its 65 segments declare 0.37-193
    s, but the speech they quote sits 878 s into ``GRU_Airport_Full``. Raw
    offset lookup therefore resolves to unrelated audio, and every segment too
    short to clear the text gate gets dropped.

    Decisive text matches recover the delta without needing the offset at all,
    because ``transcript_start - vault_offset`` is constant across the clip.
    Returns ``{source_token: delta}`` for tokens that calibrate cleanly, so
    :func:`reanchor_segment` can shift the offset instead of trusting it.
    """
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
        # Median, not mean: a handful of matches land on a neighbouring segment
        # and inflate the mean by seconds.
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
    """Resolve a vault segment to the current canonical transcript index.

    Neither signal is sufficient alone: the vault index is stale, the timings
    shifted between renders, and ``verbatim_es`` is missing on ~19% of segments.
    Text identity wins when it is decisive; otherwise the audio offset decides,
    and the confidence is reported so a weak anchor is reviewable instead of
    being indistinguishable from a byte-exact one.

    ``deltas`` (see :func:`estimate_clip_offset_delta`) rescues clips whose
    offsets are relative to the original recording: for those, the raw offset
    cannot be trusted at all, so the calibrated one replaces it rather than
    merely corroborating it.
    """
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
        # A calibrated offset lands within a second or so, which is enough to
        # pick the wrong neighbour; where the quote is long enough to be
        # informative, let it pick among the nearby candidates.
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

    # Two independent signals agreeing is the strongest evidence available.
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
    """Recursively flatten wikilink references into plain strings.

    ``transcripts[]`` is not uniform across the vault: it appears as flat
    strings (``"[[I-002_05_…]]"``), as nested lists-of-lists
    (``[[["I-002_17_…"]]]``) and occasionally as dicts. A single recursive pass
    handles every observed shape without special-casing a violation.
    """
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
    """Match ``value`` against ``allowed`` case-insensitively, returning the
    canonical spelling from ``allowed`` (the sets differ in case: severities are
    upper-case, everything else lower-case)."""
    text = str(value or "").strip()
    if aliases:
        text = aliases.get(text.lower(), text)
    canonical = {a.lower(): a for a in allowed}
    return canonical.get(text.lower(), fallback)


# ── Build contract.json ─────────────────────────────────────────────────────

def build_contract(violation: dict, resolver: FrameworkResolver) -> tuple[dict, list[str]]:
    """Build contract.json from a schema-4.0 violation document.

    Returns ``(contract, warnings)``. Warnings are surfaced (never swallowed)
    because the vault carries real gaps — most notably ``CL.LEY19880.Art.4``,
    which has no counterpart file anywhere in the law corpus.
    """
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

    # ── Incident ────────────────────────────────────────────────────────────
    # ``incident_meta`` already carries the structured record; the display
    # string is only a fallback so nothing is hardcoded here.
    meta = violation.get("incident_meta") if isinstance(violation.get("incident_meta"), dict) else {}
    display = str(violation.get("incident_timestamp_display") or "")
    date = meta.get("date") or (display.split("—")[0].strip() if "—" in display else display)
    # ``Incident.date``/``location`` are non-nullable strings, but a handful of
    # vault records leave them out (CL-f7dd941e has ``location: null``). Writing
    # the null through would make the whole document fail validation and drop
    # every layer on the legacy fallback, so substitute and say so.
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

    # ── Legal basis ─────────────────────────────────────────────────────────
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
            # Candidates still belong in ``legal_basis`` so the refiner can see
            # them (``_normalize`` demotes any article whose excerpt is not in
            # the cache, and it drops top-level ``candidate_articles`` entirely),
            # but they carry no verified body. Keep the vault's full record in
            # the mirror below instead of collapsing it to a bare id.
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
            # The vault's verbatim_text is the authoritative body; the local
            # markdown copy is only consulted when the vault supplies none.
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

    # ── Cross references / open questions ───────────────────────────────────
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
    """Build segments_manifest.json, re-anchoring every segment id.

    Returns ``(manifest, warnings)``. A low-confidence anchor (one resting on
    the audio offset alone) is a warning, not a silent success: the old ids are
    known to be wrong, so an unverifiable anchor can point at the wrong
    utterance and nothing downstream would notice.

    ``deltas`` are the calibrated clip offsets for this violation; pass ``None``
    (the default) to calibrate them here, or ``{}`` to switch the correction
    off. Calibrating by default keeps the fix from depending on every caller
    remembering to ask for it.
    """
    if deltas is None:
        deltas = estimate_clip_offset_delta(violation, transcripts)
    warnings: list[str] = []
    segments: list[dict] = []
    seen: set[str] = set()
    transcript_files: dict[str, str] = {}
    placeholders = 0
    # canonical transcript id -> file name, so staging never re-derives it.
    available_files = {
        str(entry["doc"].get("transcript_id") or entry["path"].stem): entry["path"].name
        for entry in transcripts.values()
    }

    for raw_segment in violation.get("full_segments") or []:
        if not isinstance(raw_segment, dict):
            continue
        raw_id = str(raw_segment.get("segment_id") or "").strip()
        # 65 vault segments corpus-wide are empty placeholders (``seg-40`` with
        # offsets 0-0). They carry no evidence, so anchoring them would only
        # produce a rejected offset guess and bury the real warnings.
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
                # Kept so the anchor itself is reviewable: a re-anchored id is
                # only trustworthy if the text it matched is the text the vault
                # meant.
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
        # Non-empty only for clips whose vault timings are relative to a
        # different cut of the audio. Recorded so a reviewer can see that an
        # anchor was shifted rather than taken at face value.
        "clip_offset_deltas": deltas or {},
        # Recorded so a consumer can symlink the right transcript files (and
        # cross-check them) instead of re-deriving the audio_id -> transcript_id
        # bridge that ``build_segments_manifest`` resolves above.
        "transcript_files": transcript_files,
    }
    if placeholders:
        warnings.append(
            f"{placeholders} empty placeholder segment(s) in full_segments skipped"
        )
    return manifest, warnings


def _summarise_warnings(warnings: list[str], vid: str) -> list[str]:
    """Collapse repetitive per-reference warnings into counted summary lines.

    Re-anchoring one violation can produce hundreds of "no re-anchored
    equivalent" lines (one per element evidence link and nexus row that pointed
    at a rejected segment), which drowns out the warnings that need action. The
    counts carry the same information in a readable form. Lines matching
    ``_INFORMATIONAL_MARKERS`` are dropped from the summary entirely — they are
    kept in the bundle's ``conversion_warnings.json``.
    """
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


#: Expected, self-explanatory outcomes — kept in ``conversion_warnings.json``
#: but excluded from the console summary.
_INFORMATIONAL_MARKERS: tuple[str, ...] = (
    "empty placeholder segment(s) in full_segments skipped",
)

#: Per-reference warnings that repeat once per element evidence link, per nexus
#: row and per rejected segment. Collapsed to counts so the actionable warnings
#: stay visible.
_REPEATED_WARNING_MARKERS: tuple[tuple[str, str], ...] = (
    ("has no re-anchored equivalent", "segment refs to unanchored vault segments"),
    ("link dropped", "nexus rows to unanchored vault segments"),
    ("rerun with --allow-weak-anchors", "segments rejected as low-confidence"),
    ("no canonical transcript matched", "segments with no matching transcript"),
)


# ── Conversion ──────────────────────────────────────────────────────────────

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

    Evidence segment ids inside ``element_grids``/``nexus_matrix`` are re-mapped
    from the stale vault numbering to the re-anchored ids, otherwise every
    element would point at an utterance that no longer exists.
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
        transcript_id, _, local_id = seg_id.partition(".")
        reader = readers.get(transcript_id)
        parsed = reader.get_segment(local_id) if reader else None
        if reader is None or parsed is None:
            warnings.append(f"{seg_id}: cannot hydrate verbatim text from the transcript")
            continue
        verbatim = parsed["verbatim"] or str(seg.get("verbatim_es") or "")
        legacy_text = str(seg.get("verbatim_es") or "")
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
                "source_uri": f"Transcripts/{readers[transcript_id].source_uri().split('/')[-1]}#{local_id}",
                "source_sha256": reader.source_sha256(),
                "audio_uri": None,
            }
        )

    # ── Layers 2-5 ----------------------------------------------------------
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

    # Layer 3 — element grids (shape changes: name/status/evidence/argument).
    # ``verifier.E_GRID_UNKNOWN_ARTICLE`` makes a grid on an article that is not
    # in ``established_articles`` an error, and ``confidence.derive_confidence``
    # weights grids through ``established_articles[].applicability`` — so a grid
    # for a demoted article is both a hard failure and an unweighted input. The
    # element analysis is not lost: the article is already carried as a
    # candidate (with the reason it was demoted), and the grid's size is
    # reported so the omission is visible.
    established_article_ids = {a["article_id"] for a in established_articles}
    element_grids: list[dict] = []
    raw_grids = violation.get("element_grids")
    if isinstance(raw_grids, dict):
        for article_id, elements in raw_grids.items():
            if not isinstance(elements, list):
                continue
            translated: list[dict] = []
            article_short = ""
            for element in elements:
                if not isinstance(element, dict):
                    continue
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
                translated.append(
                    {
                        "element_id": str(element.get("element_id") or ""),
                        "label": str(element.get("element_name") or element.get("label") or ""),
                        "doctrinal_basis": element.get("doctrinal_basis") or None,
                        "proof_status": status,
                        "proof_evidence_segments": evidence,
                        "argument_es": str(element.get("argument") or element.get("argument_es") or ""),
                        "weaknesses": [str(w) for w in (element.get("weaknesses") or [])],
                        "open_questions": [
                            str(o).strip("`") for o in (element.get("open_questions") or [])
                        ],
                    }
                )
            if not translated:
                continue
            if str(article_id) not in established_article_ids:
                warnings.append(
                    f"element grid for {article_id} ({len(translated)} element(s)) "
                    "dropped: the article is not in established_articles, so the "
                    "grid would be an orphan (V11 E_GRID_UNKNOWN_ARTICLE) and "
                    "would carry no confidence weight"
                )
                continue
            element_grids.append(
                {
                    "article_id": str(article_id),
                    "article_short": article_short or str(article_id),
                    "elements": translated,
                }
            )

    # Layer 4 — nexus matrix (``fact_id`` carries stale segment ids).
    # A nexus row is only meaningful against an emitted grid:
    # ``verifier`` resolves ``norm_id`` through ``element_ids_by_article``, so a
    # row for a dropped grid is ``E_NEXUS_UNKNOWN_NORM``.
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
                f"nexus {entry.get('element_id')}: fact {raw_fact!r} has no re-anchored "
                "equivalent; link dropped"
            )
            continue
        norm_id = str(entry.get("norm_id") or "")
        if norm_id not in grid_article_ids:
            orphaned_norm_rows[norm_id] = orphaned_norm_rows.get(norm_id, 0) + 1
            continue
        strength = str(entry.get("strength") or "").strip().lower()
        if strength not in {"high", "medium", "low"}:
            warnings.append(f"nexus {fact_id}: strength {strength!r} is not a model value")
            strength = "low"
        nexus_matrix.append(
            {
                "fact_id": fact_id,
                "norm_id": norm_id,
                "element_id": str(entry.get("element_id") or ""),
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

    # Layer 5 — authorities. Vault records carry no proposition to verify, so
    # the research query doubles as one (authorities stay unverified).
    authorities: list[dict] = []
    for entry in violation.get("authorities") or []:
        if not isinstance(entry, dict):
            continue
        authority_id = str(entry.get("authority_id") or entry.get("id") or "").strip()
        if not authority_id:
            continue
        authority_type = str(entry.get("type") or "").strip()
        if authority_type not in _VALID_AUTHORITY_TYPES:
            warnings.append(f"authority {authority_id}: type {authority_type!r} is not a model value")
            authority_type = "doctrine"
        query = str(entry.get("research_query") or "").strip()
        authorities.append(
            {
                "authority_id": authority_id,
                "type": authority_type,
                "supports": [
                    str(s) for s in (entry.get("supports") or entry.get("supports_elements") or [])
                ],
                "research_query": query,
                "proposition_to_verify": str(entry.get("proposition_to_verify") or query),
                "verified": False,
            }
        )

    # ── Auxiliary (already normalised by build_contract) ────────────────────
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
        from violation_pack.models import Violation

        Violation.model_validate(document)
    except Exception as exc:  # noqa: BLE001 - surfaced, never hidden
        return [f"{vid}: staged document does not validate as Violation: {exc}"]
    return []


# ── Stage the final bundle ──────────────────────────────────────────────────

def _framework_bundle_name(code: str) -> str:
    """Filename to use for a framework inside ``Legal framework/``.

    ``refine_batch_core._discover_frameworks`` keys readers by
    ``md.stem.split("_")[0].upper()``, and ``validation.v03``/``v04`` look the
    reader up by the article's ``framework_code``. Preserving the corpus filename
    (``CodigoPenal.md`` → ``CODIGOPENAL``, ``L19496_LPDC.md`` → ``L19496``) makes
    both miss the reader and report the law as unregistered even though the file
    is present and correct. Naming the symlink after the code makes the derived
    key equal the key that is looked up.

    Codes containing ``_`` cannot round-trip through that rule at all (the first
    token wins), which ``stage_bundle`` warns about.
    """
    return f"{code}.md"


def _ensure_symlink(link: Path, target: Path) -> None:
    """Point ``link`` at ``target`` (relative), replacing a stale link.

    Symlinks rather than copies so a bundle can never diverge from the single
    source of truth, and relative so ``build/`` stays movable.
    """
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

    Returns non-fatal warnings (a framework with no corpus file, an unresolved
    transcript, a document that would fall back to the legacy normalizer, ...).
    """
    warnings: list[str] = []
    vid = bundle_dir.name

    # Symlinks first: the document's framework caches and ``source_uri`` fields
    # reference the bundle-relative paths, so the target must exist before the
    # framework markdown is hashed.
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
        # ``_discover_frameworks`` derives the code from the filename; a code
        # containing "_" cannot survive a rule that only reads the first token,
        # and V03/V04 would then call the law unregistered.
        if "_" in code:
            warnings.append(
                f"{code}: framework code contains '_', which "
                "refine_batch_core._discover_frameworks truncated to "
                f"{code.split('_')[0].upper()}; V03/V04 will report this law as unregistered"
            )
        _ensure_symlink(bundle_dir / "Legal framework" / _framework_bundle_name(code), target)

    # Canonical violation document.
    document, doc_warnings = build_violation_document(
        violation, contract, manifest, law_root, transcript_dir, bundle_dir
    )
    warnings += doc_warnings
    warnings += _validate_document(document, vid)
    (bundle_dir / f"{vid}.json").write_text(
        json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # The contract can only be reconciled once the document it describes
    # exists, so rewrite it after staging.
    if _reconcile_contract_confidence(contract, document, vid, warnings):
        (bundle_dir / "contract.json").write_text(
            json.dumps(contract, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    return warnings


def _reconcile_contract_confidence(
    contract: dict, document: dict, vid: str, warnings: list[str]
) -> bool:
    """Stop ``contract.json`` from asserting a confidence the bundle contradicts.

    The vault keeps a confidence *snapshot* (``value``/``components``/
    ``derived_at``/``history``/``validated``). ``refine_batch_core
    .attach_confidence`` unconditionally recomputes from ``element_grids``, and
    ``validation.v08_contract_consistency`` treats a dict-shaped confidence as a
    *live* assertion (only a bare scalar is downgraded to "legacy snapshot" and
    merely warned about) — so a snapshot the bundle's own data does not
    reproduce becomes a V08 FAIL that no amount of faithful translation can
    clear. Observed causes in the LA8159 corpus: the snapshot was never derived
    (``value: 0``, empty ``components``), its components were rounded before the
    value was computed, or the weights implied by ``value`` are not the weights
    its ``applicability`` fields declare.

    The snapshot is preserved as ``contract["_vault_confidence"]`` and the
    divergence is reported with both numbers, so the check is skipped rather
    than silently satisfied. Returns True when ``contract`` was modified.
    """
    snapshot = contract.get("confidence")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("value"), (int, float)):
        return False
    try:
        violation = Violation.model_validate(document)
    except Exception:  # pylint: disable=broad-except
        return False  # _validate_document already reported this
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
    """Convert one vault JSON document into a bundle directory.

    Writes ``contract.json`` + ``segments_manifest.json``, then (unless
    ``stage`` is false) assembles the final bundle layout around them.

    Returns ``(bundle_dir, warnings)``.
    """
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
        # Keep the full list on disk so summarising the console output never
        # destroys the per-reference detail a reviewer may need.
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
    """Rank competing revisions of one violation.

    Highest declared vault confidence first, then the plainest filename (so
    ``BR-030.json`` beats a decorated ``BR-030-updated.json``), then alphabetical
    so the result never depends on glob order. Equal confidence is the normal
    case for the byte-identical copies in this vault.
    """
    return (-_vault_confidence_value(path), len(path.name), path.name)


def _prefer_authoritative_revisions(paths: list[Path]) -> list[Path]:
    """Reduce vault files to one authoritative revision per ``violation_id``.

    ``convert_one`` keys the bundle directory off the *declared* violation id,
    so two files declaring the same id write the same ``build/<VID>`` and the
    survivor depends on glob order. The LA8159 vault really does this: ``BR-001``
    is declared by ``BR-001.json`` (confidence 0.68), ``BR-030.json`` (0.98) and
    a byte-identical ``BR-030-updated.json``. Byte-identical copies are dropped
    by content hash (pure redundancy), then the highest confidence wins, and
    every discarded file is named so the choice is auditable rather than
    incidental.
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
        # Byte-identical copies are pure redundancy; collapse them by content,
        # keeping the representative the ranking rule would have picked anyway.
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

    # De-duplicate while preserving order.
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

        manifest = json.loads((bundle_dir / "segments_manifest.json").read_text(encoding="utf-8"))
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
