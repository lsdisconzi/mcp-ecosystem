# -*- coding: utf-8 -*-
"""
infrastructure/law/law_registry.py

LawRegistry — loads and queries the canonical law corpus in data/law/.

Directory layout expected:
    data/law/
        index.json          # manifest of all frameworks
        BR/json/CBA.json    # array of articles for each framework
        CL/json/CACH.json
        INT/json/MC99.json
        ...

The index is loaded eagerly on first access; individual framework files are
loaded lazily on first query for that framework and cached in memory.
"""
from __future__ import annotations

import json
from functools import cached_property
from pathlib import Path
from typing import Dict, List, Optional

# Resolve corpus root relative to this file:
# infrastructure/law/law_registry.py → ../../data/law/
_CORPUS_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "law"


class LawRegistry:
    """Read-only access to the shared law corpus.

    All public methods return plain ``dict`` objects that directly mirror
    the JSON structure so callers can work without importing domain types.
    Use ``LawRegistry.article_to_canonical(raw)`` to convert to
    ``CanonicalArticle`` when needed.
    """

    def __init__(self, corpus_root: Path = _CORPUS_ROOT) -> None:
        self._root = corpus_root
        self._article_cache: Dict[str, List[dict]] = {}  # code → list of articles
        self._eli_cache: Dict[str, dict] = {}            # eli_id → article

    # ── Index ─────────────────────────────────────────────────────────────────

    @cached_property
    def index(self) -> List[dict]:
        """All framework manifest entries from ``index.json``."""
        index_path = self._root / "index.json"
        if not index_path.exists():
            raise FileNotFoundError(
                f"Law corpus index not found at {index_path}. "
                "Ensure data/law/index.json is present."
            )
        with index_path.open(encoding="utf-8") as fh:
            return json.load(fh)

    def list_frameworks(self) -> List[dict]:
        """Return all framework manifest entries (id, name, jurisdiction, etc.)."""
        return list(self.index)

    def get_framework_meta(self, code: str) -> Optional[dict]:
        """Return the index entry for ``code``, or ``None`` if not found."""
        code_upper = code.upper()
        for entry in self.index:
            if entry.get("framework_code", "").upper() == code_upper:
                return entry
        return None

    def frameworks_for_jurisdiction(self, jurisdiction: str) -> List[dict]:
        """Return all index entries for a given jurisdiction (BR, CL, INT, …)."""
        j = jurisdiction.upper()
        return [e for e in self.index if e.get("jurisdiction", "").upper() == j]

    # ── Article access ────────────────────────────────────────────────────────

    def articles_for_framework(self, code: str) -> List[dict]:
        """Return all articles for a framework, loading from disk on first call."""
        code_upper = code.upper()
        if code_upper in self._article_cache:
            return self._article_cache[code_upper]

        meta = self.get_framework_meta(code_upper)
        if meta is None:
            return []

        file_path = self._root / meta["file"]
        if not file_path.exists():
            return []

        with file_path.open(encoding="utf-8") as fh:
            articles = json.load(fh)

        self._article_cache[code_upper] = articles
        # index by eli_id for fast single-article lookup
        for art in articles:
            eli = art.get("eli_id")
            if eli:
                self._eli_cache[eli] = art

        return articles

    def get_article(self, eli_id: str) -> Optional[dict]:
        """Return a single article by its ELI id (e.g. ``BR.CBA.T3.C1.Art.74``).

        Triggers loading of the relevant framework file if not yet cached.
        """
        if eli_id in self._eli_cache:
            return self._eli_cache[eli_id]

        # Derive framework_code from the first two segments of the ELI id
        # e.g. "BR.CBA.T3.C1.Art.74" → code = "CBA"
        parts = eli_id.split(".")
        if len(parts) >= 2:
            self.articles_for_framework(parts[1])
            return self._eli_cache.get(eli_id)

        return None

    def themes_for_framework(self, code: str) -> List[str]:
        """Return the sorted list of unique themes present in a framework."""
        seen: set = set()
        for art in self.articles_for_framework(code):
            t = art.get("theme")
            if t:
                seen.add(t)
        return sorted(seen)

    def articles_by_theme(self, code: str, theme: str) -> List[dict]:
        """Return articles in ``code`` that match ``theme`` (case-insensitive)."""
        theme_lower = theme.lower()
        return [
            a for a in self.articles_for_framework(code)
            if (a.get("theme") or "").lower() == theme_lower
        ]

    # ── Conversion helper ─────────────────────────────────────────────────────

    @staticmethod
    def article_to_canonical(raw: dict):
        """Convert a raw article dict to a ``CanonicalArticle`` domain entity."""
        from domain.entities.canonical_entities import CanonicalArticle  # late import

        return CanonicalArticle(
            eli_id=raw.get("eli_id", ""),
            article_id=raw.get("eli_id", ""),
            framework_code=raw.get("framework_code", ""),
            framework_name=raw.get("framework_name", ""),
            article_number=str(raw.get("article_number", "")),
            jurisdiction=raw.get("jurisdiction", ""),
            reference=raw.get("reference", ""),
            text=raw.get("text", ""),
            full_text=raw.get("text"),
            theme=raw.get("theme", ""),
            hierarchy=raw.get("hierarchy") or {},
        )

    def preload_all(self) -> None:
        """Eagerly load every framework file — useful for startup health checks."""
        for entry in self.index:
            self.articles_for_framework(entry["framework_code"])
