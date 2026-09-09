# -*- coding: utf-8 -*-
"""
infrastructure/parsers/integrated_parser_adapter.py

Adapts IntegratedLegalFrameworkParser (v3) to the IFrameworkParser contract
defined in domain/interfaces. This is the only place that imports the concrete
parser implementation.
"""
from typing import Any, Dict, List

from domain.interfaces.i_framework_parser import IFrameworkParser
from ingestors.integrated_legal_framework_parser_v3 import IntegratedLegalFrameworkParser


class IntegratedParserAdapter(IFrameworkParser):
    """
    Thin adapter that delegates every IFrameworkParser call to the
    concrete v3 parser, keeping domain code free of implementation details.
    """

    def __init__(self) -> None:
        self._parser = IntegratedLegalFrameworkParser()

    def detect_framework_characteristics(self, text: str) -> Dict[str, Any]:
        return self._parser.detect_framework_characteristics(text)

    def extract_legal_articles_with_context(self, text: str) -> Dict[str, List[Dict]]:
        return self._parser.extract_legal_articles_with_context(text)

    def build_enhanced_legal_prompt(
        self,
        config: Dict[str, Any],
        extracted_sections: Dict[str, List[Dict]],
        framework_text: str,
    ) -> str:
        return self._parser.build_enhanced_legal_prompt(config, extracted_sections, framework_text)

    def generate_integrated_js_analyzer(
        self,
        config: Dict[str, Any],
        prompt: str,
        output_path: str,
    ) -> str:
        return self._parser.generate_integrated_js_analyzer(config, prompt, output_path)

    def convert_user_articles(self, articles: List[Dict[str, Any]]) -> Dict[str, List[Dict]]:
        """
        Convert a user-supplied article list (CBA.json / MC99.json format) into the
        extracted_sections dict expected by build_enhanced_legal_prompt.
        Implemented here to avoid depending on a method that the v3 parser may not have.
        """
        converted = []
        for art in articles:
            article_number = str(art.get("article_number") or art.get("number") or "?")
            text = art.get("text") or art.get("content") or ""
            text_lower = text.lower()

            if any(k in text_lower for k in ["shall not", "proibido", "prohibido", "não deve", "no deberá"]):
                article_type = "prohibition"
            elif any(k in text_lower for k in ["shall", "must", "deve", "deberá", "obriga"]):
                article_type = "obligation"
            elif any(k in text_lower for k in ["right to", "entitled", "freedom", "direito", "derecho"]):
                article_type = "rights_provision"
            elif any(k in text_lower for k in ["penalty", "fine", "multa", "sanction", "indeniz"]):
                article_type = "remedy_penalty"
            elif any(k in text_lower for k in ["means", "entende-se", "se entiende", "defined as"]):
                article_type = "definition"
            else:
                article_type = "general_provision"

            converted.append({
                "number": article_number,
                "type": article_type,
                "content": text[:300],
                "full_content": text,
                "context": art.get("reference", ""),
                "juridical_value": {
                    "hierarchy": "mandatory",
                    "enforceability": "direct",
                    "interpretation_weight": "high",
                },
                "eli_id": art.get("eli_id", ""),
                "theme": art.get("theme", ""),
                "reference": art.get("reference", ""),
                "_user_defined": True,
            })

        return {
            "numbered_articles": converted,
            "definitions": [],
            "obligations": [],
            "prohibitions": [],
        }
