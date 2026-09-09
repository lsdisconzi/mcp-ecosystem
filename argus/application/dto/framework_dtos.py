# -*- coding: utf-8 -*-
"""
application/dto/framework_dtos.py

Data Transfer Objects for the framework build pipeline.
These are the typed contracts between the HTTP layer and the application service.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class FrameworkConfigDto:
    """Validated, typed representation of the user-supplied framework config."""
    framework_name: str
    framework_type: str = "legal_framework"
    responsible_entity: str = ""
    jurisdiction: str = "Unknown"
    legal_style: str = "mixed"
    js_function_name: str = ""
    output_language: str = "en"
    analysis_focus: Dict[str, str] = field(default_factory=dict)
    articles: List[Dict[str, Any]] = field(default_factory=list)
    # Populated downstream
    ui_strings: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FrameworkConfigDto":
        return cls(
            framework_name=data["framework_name"],
            framework_type=data.get("framework_type", "legal_framework"),
            responsible_entity=data.get("responsible_entity", ""),
            jurisdiction=data.get("jurisdiction", "Unknown"),
            legal_style=data.get("legal_style", "mixed"),
            js_function_name=data.get("js_function_name", ""),
            output_language=data.get("output_language", "en"),
            analysis_focus=data.get("analysis_focus", {}),
            articles=data.get("articles", []),
            ui_strings=data.get("ui_strings", {}),
        )


@dataclass
class BuildRequestDto:
    """Everything the HTTP POST /api/build_framework sends to the service."""
    framework_text: str
    config_json_text: str
    output_filename: str = "generatedAnalyzer.js"
    output_language: str = "en"


@dataclass
class BuildResultDto:
    """Everything the service returns to the HTTP layer."""
    success: bool
    generated_prompt: str = ""
    generated_js: str = ""
    filename: str = ""
    parser_used: str = "integrated"
    language_used: str = "en"
    error: Optional[str] = None
