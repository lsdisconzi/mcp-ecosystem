# -*- coding: utf-8 -*-
"""
domain/services/article_classifier.py

Pure domain service: classifies legal articles by type and assesses
their juridical value. Zero infrastructure imports.
"""
import re
from typing import Dict


class ArticleClassifier:
    """
    Classifies individual legal articles and assesses their juridical value.
    All logic is pure Python — no I/O, no external libs.
    """

    # ── Article type classification ─────────────────────────────────────────

    _RIGHTS_KEYWORDS = ("right to", "entitled to", "shall have", "may", "freedom of", "liberdade de")
    _OBLIGATION_KEYWORDS = ("shall", "must", "is required to", "deve", "deberá", "obrigação")
    _PROHIBITION_KEYWORDS = ("shall not", "must not", "prohibited", "forbidden", "proibido", "prohibido")
    _REMEDY_KEYWORDS = ("compensation", "damages", "indemnity", "penalty", "fine", "sanction", "multa")
    _PROCEDURAL_KEYWORDS = ("procedure", "process", "appeal", "complaint", "recurso", "procedimento")
    _DEFINITION_KEYWORDS = ("means", "refers to", "defined as", "entende-se por", "se entiende por")

    def classify(self, content: str) -> str:
        lower = content.lower()
        if any(k in lower for k in self._PROHIBITION_KEYWORDS):
            return "prohibition"
        if any(k in lower for k in self._OBLIGATION_KEYWORDS):
            return "obligation"
        if any(k in lower for k in self._RIGHTS_KEYWORDS):
            return "rights_provision"
        if any(k in lower for k in self._REMEDY_KEYWORDS):
            return "remedy_penalty"
        if any(k in lower for k in self._PROCEDURAL_KEYWORDS):
            return "procedural"
        if any(k in lower for k in self._DEFINITION_KEYWORDS):
            return "definition"
        return "general_provision"

    # ── Juridical value assessment ───────────────────────────────────────────

    def assess_juridical_value(self, content: str, article_type: str) -> Dict[str, str]:
        lower = content.lower()
        hierarchy = "ordinary"
        if any(t in lower for t in ("fundamental right", "human right", "direito fundamental")):
            hierarchy = "constitutional"
        elif any(t in lower for t in ("principle", "princípio", "principio")):
            hierarchy = "principled"
        elif any(t in lower for t in ("shall", "must", "obligatory")):
            hierarchy = "mandatory"
        elif any(t in lower for t in ("may", "optional", "discretionary")):
            hierarchy = "discretionary"

        enforceability_map = {
            "rights_provision": "direct_enforceable",
            "obligation": "enforceable",
            "prohibition": "strict_enforceable",
            "definition": "interpretive",
        }
        enforceability = enforceability_map.get(article_type, "direct")

        if hierarchy == "constitutional":
            weight = "highest"
        elif hierarchy == "principled" or article_type in ("rights_provision", "obligation"):
            weight = "high"
        else:
            weight = "medium"

        return {
            "hierarchy": hierarchy,
            "enforceability": enforceability,
            "interpretation_weight": weight,
        }
