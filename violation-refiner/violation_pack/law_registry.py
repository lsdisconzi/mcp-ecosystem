"""Article extents derived from ``data/law/_mapping/law_registry.json``.

Used to catch *cross-code mis-attribution* in the candidates stage: a
proposal like ``CL.CPCL.C1.Art.2314`` names a valid framework prefix and a
valid-looking article number, but Art. 2314 of the Chilean Código Civil is
not an article of the Código Penal. The prefix test in
``enrich._has_known_framework`` cannot see that — it only looks at the
framework segment.

What the registry is, and is not
-------------------------------
It is an **ingestion coverage report**: it records which ``data/law/``
markdown files map to which ELI ids in the Qdrant collection. It is *not*
an authority on how far a code reaches.

That distinction decides the whole design. For a small, fully-ingested code
(``CL/CodigoPenal.md`` holds 7 articles; ``CL/CHIPENCOD_CP.md`` holds 12)
the per-framework maximum is a usable extent. For a large partial extract
(the USMCA ``BR.CBA`` sample, the Civil Codes, the ICAO annexes) it is only
a *lower bound* — a legitimate article that was simply never ingested sits
above it.

So this module must never ask "is the number above the maximum? then
reject": measured against the real registry that formulation rejects
``CL.CPCL.Art.100``, ``.300``, ``.391``, ``.436``, ``.470`` — all real
Código Penal articles (the code has ~500), merely absent from the extract.

The rule that survives measurement
----------------------------------
Reject ``<JUR>.<FW>...Art.<N>`` only when **all** of these hold:

1. the tail is a *plain integer* article (``\\\\.Art\\\\.(\\\\d+)$``). A compound
   tail such as ``INT.ACHR...Art.2.13.1`` or ``INT.ICAO...Art.2.1.1`` is a
   treaty's standard numbering, not a sequence position, so "in range" is
   not a meaningful question and the id is kept.
2. the registry has extent data for ``(JUR, FW)``. Unknown code ⇒ cannot
   judge ⇒ **keep**.
3. ``N`` is above ``FW``'s own observed extent (the number is outside the
   code we think it belongs to).
4. **exactly one** sibling framework ``S`` *in the same jurisdiction* both
   reaches ``N`` (``extent[S] >= N``) and actually *contains* ``N``
   (``N ∈ occupied[S]``) — a sole owner, so attribution is unambiguous.
5. ``N`` lies in ``S``'s *exclusive band*: it exceeds the extent of every
   other framework in the jurisdiction. This is what makes "only ``S`` can
   own this number" true rather than merely asserted.
6. ``S`` is an **extent outlier** in that jurisdiction:
   ``extent[S] >= 2.0 × max(extent[g] for g != S)``.

Conditions 3 and 4 are **subsumed** by 5 and 6, and are kept as the readable
statement of intent rather than because they decide anything:

* 5 implies 3. A rejection requires ``N > runner_up``, and ``runner_up`` is
  the largest extent other than ``S``'s, which is ``>= extent[own]`` whenever
  ``own`` is not ``S``. So ``N <= own_extent`` can never reach the return.
* 5 and 6 imply 4. Suppose two codes ``S1``, ``S2`` both hold ``N`` and reach
  it. If ``S1`` is the jurisdiction's largest, ``runner_up >= extent[S2] >=
  N``; if it is not, ``runner_up >= extent[S1] >= N``. Either way the band
  blocks, so a second owner cannot survive to make the attribution ambiguous.

Measured by differential search (120 random registries × 2,500 numbers × 3
codes = 900,000 candidate ids): deleting the sole-owner test, or deleting the
own-extent guard, changes **zero** verdicts; deleting the band changes 3,645.
So do not write a test that claims to isolate 3 or 4 — no fixture can, and
``tests/test_law_registry.py`` says so.

Conditions 5 and 6 are the two a prose-only reading of this rule tends to
drop, and each drop is measurable:

* Without **5**, membership in a *sparse* extract reads as ownership.
  ``BR.CC``'s sample holds 12 numbers, and ``BR.R400`` reaches 46 with all
  46 observed — so 53 is outside R400's territory, but it is not *uniquely*
  CC's either: Brazilian codes reach 302 (``CBA``). Dropping 5 turns the
  reject set from 126 into 277, adding ``BR.R400.Art.53`` and
  ``BR.L9784.Art.59`` (Lei 9.784/99 has 66 articles; the extract holds 2).
* Without **6**, a band exists in the international set too — ``MC99``
  reaches 59 against a 38 runner-up — and the rule rejects
  ``INT.CHICAGO.Art.50``, ``INT.UNCRC.Art.40``, ``INT.VCLT.Art.40``.

Condition 6 is derived from the registry rather than hardcoded as a
jurisdiction list. Measured live ratios: ``BR`` 927 vs 302 = 3.07 (outlier
present), ``CL`` 2329 vs 416 = 5.60 (present), ``INT`` 59 vs 38 = 1.55 (no
outlier). So the rule disables itself in the international set, where no
single code dominates and a "sole owner" argument has nothing to stand on.

Measured behaviour against the committed registry: **126** rejections, all
genuine (``BR`` 30 = every framework × ``Art.927``; ``CL`` 96 = 16
frameworks × the 6 Código Civil numbers ``{1437, 1546, 1698, 2314, 2328,
2329}``; ``INT`` 0), and 0 false positives across a 34-id probe of
legitimate in-range and not-yet-ingested articles.

The three earlier formulations and their measured reject sets, kept here so
nobody re-derives them: loose sibling rule 6,676; extent-tolerance-gated
sibling rule 4,141 (a multiple of an *extract* size is an arbitrary unit);
sole-owner rule without the exclusive band 277 (with false positives such as
``BR.R400.Art.53``).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

#: Override the registry location (mainly for tests).
REGISTRY_ENV_VAR = "VR_LAW_REGISTRY"

_REGISTRY_RELATIVE = ("data", "law", "_mapping", "law_registry.json")

#: A plain integer article tail. Anchored at ``$`` deliberately: an
#: unanchored ``re.search`` on ``INT.ACHR...Art.2.13.1`` captures the leading
#: ``2`` and makes a 30-article treaty look like a 2-article one.
_PLAIN_ARTICLE = re.compile(r"\.Art\.(\d+)$")

#: How far the largest code extent in a jurisdiction must exceed the next
#: largest before a sole-owner argument is considered sound.
_EXTENT_OUTLIER_RATIO = 2.0


def find_registry_path() -> Path | None:
    """Locate ``law_registry.json``, or ``None`` if it cannot be found.

    Honours ``$VR_LAW_REGISTRY`` first, then walks up from this file looking
    for ``data/law/_mapping/law_registry.json`` — the same walk-up shape as
    ``ui_server.find_data_root``, kept local so ``enrich`` does not have to
    import the UI server.
    """
    override = os.environ.get(REGISTRY_ENV_VAR)
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_file() else None

    for base in Path(__file__).resolve().parent.parents:
        candidate = base.joinpath(*_REGISTRY_RELATIVE)
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True)
class Misattribution:
    """A candidate id whose article number belongs to a sibling code."""

    article_id: str
    framework: str
    jurisdiction: str
    sibling_framework: str
    sibling_jurisdiction: str
    number: int
    sibling_extent: int
    band_floor: int

    def reason(self) -> str:
        """Human-readable reason, for provenance notes."""
        return (
            f"{self.article_id}: Art.{self.number} is "
            f"{self.sibling_jurisdiction}.{self.sibling_framework}-only "
            f"territory ({self.sibling_jurisdiction}.{self.sibling_framework} "
            f"reaches {self.sibling_extent}; every other "
            f"{self.jurisdiction} code stops at {self.band_floor}, "
            f"{self.jurisdiction}.{self.framework} included)"
        )


@dataclass(frozen=True)
class ArticleExtents:
    """Per-``(jurisdiction, framework)`` article numbers seen in the registry.

    ``occupied`` is keyed by ``(jurisdiction, framework)`` and never by
    framework alone: ``CC`` and ``CONST`` each appear in both ``BR`` and
    ``CL``, so a framework-only key silently mixes two different codes.
    """

    occupied: Mapping[tuple[str, str], frozenset[int]]
    extent: Mapping[tuple[str, str], int]
    outliers: frozenset[tuple[str, str]]
    #: Every framework segment the registry knows, across jurisdictions.
    framework_segments: frozenset[str]
    _by_jurisdiction: Mapping[str, tuple[tuple[str, str], ...]] = field(
        default_factory=dict, repr=False
    )
    #: Largest extent *other than* the jurisdiction's outlier, i.e. the floor
    #: of the outlier's exclusive band.
    _runner_up: Mapping[str, int] = field(default_factory=dict, repr=False)

    # -- construction ------------------------------------------------------

    @classmethod
    def from_registry(cls, data: Mapping[str, Any]) -> "ArticleExtents":
        """Build an index from parsed registry JSON."""
        occupied: dict[tuple[str, str], set[int]] = {}
        for entry in data.get("files") or []:
            if not isinstance(entry, Mapping):
                continue
            for eli in entry.get("in_qdrant_eli") or []:
                if not isinstance(eli, str):
                    continue
                parts = eli.split(".")
                if len(parts) < 3:
                    continue
                match = _PLAIN_ARTICLE.search(eli)
                if match is None:
                    # Compound-standard tails (ACHR Art.2.13.1, ICAO
                    # Art.2.1.1) carry no sequence position. Indexing their
                    # leading group would understate the code's extent and
                    # make the rule reject legitimate ids.
                    continue
                occupied.setdefault((parts[0], parts[1]), set()).add(
                    int(match.group(1))
                )

        frozen = {k: frozenset(v) for k, v in occupied.items()}
        extent = {k: max(v) for k, v in frozen.items()}

        by_jurisdiction: dict[str, list[tuple[str, str]]] = {}
        for key in frozen:
            by_jurisdiction.setdefault(key[0], []).append(key)
        grouped = {j: tuple(sorted(keys)) for j, keys in by_jurisdiction.items()}

        outliers: set[tuple[str, str]] = set()
        runner_up: dict[str, int] = {}
        for keys in grouped.values():
            largest = max(keys, key=lambda k: extent[k])
            others = [extent[k] for k in keys if k != largest]
            if not others:
                continue
            top_other = max(others)
            runner_up[largest[0]] = top_other
            if top_other > 0 and extent[largest] >= _EXTENT_OUTLIER_RATIO * top_other:
                outliers.add(largest)

        return cls(
            occupied=frozen,
            extent=extent,
            outliers=frozenset(outliers),
            framework_segments=frozenset(fw for (_jur, fw) in extent),
            _by_jurisdiction=grouped,
            _runner_up=runner_up,
        )

    @classmethod
    def load(cls, path: Path | None = None) -> "ArticleExtents | None":
        """Load from disk; ``None`` when the registry is absent or unreadable.

        Degrading to ``None`` is deliberate: a missing registry means the
        guardrail cannot judge anything, and "cannot judge" must mean "keep",
        never "reject". The candidates stage must not be able to fail a run
        because a coverage report was not on disk.
        """
        target = path or find_registry_path()
        if target is None:
            return None
        try:
            with open(target, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return None
        if not isinstance(data, Mapping):
            return None
        return cls.from_registry(data)

    # -- queries -----------------------------------------------------------

    def misattribution(self, article_id: str) -> Misattribution | None:
        """Return the mis-attribution this id commits, or ``None`` to keep it."""
        parts = article_id.split(".")
        if len(parts) < 3:
            return None
        jurisdiction, framework = parts[0], parts[1]
        key = (jurisdiction, framework)

        match = _PLAIN_ARTICLE.search(article_id)
        if match is None:
            return None
        number = int(match.group(1))

        own_extent = self.extent.get(key)
        if own_extent is None:
            return None
        # Subsumed by the band below (a rejection needs N > runner_up >=
        # own_extent); kept as the plain statement of the intent. See the
        # module docstring for the measurement.
        if number <= own_extent:
            return None

        reaching = [
            sibling
            for sibling in self._by_jurisdiction.get(jurisdiction, ())
            if sibling != key
            and self.extent[sibling] >= number
            and number in self.occupied[sibling]
        ]
        # Also subsumed: two owners cannot both clear the exclusive band.
        if len(reaching) != 1:
            return None

        sibling = reaching[0]
        if sibling not in self.outliers:
            return None
        # The sibling's exclusive band: the number must be above the reach of
        # every *other* code in this jurisdiction, so it can only be the
        # sibling's. Without this, membership in a sparse extract reads as
        # ownership — BR.CC's sample holds 12 numbers, so BR.R400.Art.53 would
        # be rejected although Brazilian codes reach 302.
        if number <= self._runner_up.get(jurisdiction, 0):
            return None

        return Misattribution(
            article_id=article_id,
            framework=framework,
            jurisdiction=jurisdiction,
            sibling_framework=sibling[1],
            sibling_jurisdiction=sibling[0],
            number=number,
            sibling_extent=self.extent[sibling],
            band_floor=self._runner_up.get(jurisdiction, 0),
        )


@lru_cache(maxsize=8)
def _load_cached(path: str) -> ArticleExtents | None:
    return ArticleExtents.load(Path(path))


def load_extents(path: Path | None = None) -> ArticleExtents | None:
    """Load (and cache) the extent index.

    Cached per resolved path, so a test that points ``$VR_LAW_REGISTRY`` at a
    fixture gets its own entry instead of the process-wide default.
    """
    target = path or find_registry_path()
    if target is None:
        return None
    return _load_cached(str(target))


def clear_cache() -> None:
    """Drop the cached index (tests that repoint the registry call this)."""
    _load_cached.cache_clear()
