# -*- coding: utf-8 -*-
"""
domain/interfaces/i_framework_parser.py

Abstract interface for legal framework parsers.
Infrastructure implementations must satisfy this contract.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List


class IFrameworkParser(ABC):
    """
    Contract every framework parser implementation must satisfy.
    Domain layer only depends on this interface — never on a concrete parser.
    """

    @abstractmethod
    def detect_framework_characteristics(self, text: str) -> Dict[str, Any]:
        """Detect jurisdiction, framework type, legal style, and other metadata."""
        ...

    @abstractmethod
    def extract_legal_articles_with_context(self, text: str) -> Dict[str, List[Dict]]:
        """
        Extract numbered articles, definitions, obligations, prohibitions,
        and remedies from raw legal text. Returns a structured dict of lists.
        """
        ...

    @abstractmethod
    def build_enhanced_legal_prompt(
        self,
        config: Dict[str, Any],
        extracted_sections: Dict[str, List[Dict]],
        framework_text: str,
    ) -> str:
        """Build the full analysis prompt to send to the AI model."""
        ...

    @abstractmethod
    def generate_integrated_js_analyzer(
        self,
        config: Dict[str, Any],
        prompt: str,
        output_path: str,
    ) -> str:
        """Generate a self-contained JavaScript analyzer file and return its content."""
        ...

    @abstractmethod
    def convert_user_articles(self, articles: List[Dict[str, Any]]) -> Dict[str, List[Dict]]:
        """Convert user-supplied pre-parsed articles into the extracted_sections format."""
        ...
