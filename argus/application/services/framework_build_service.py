# -*- coding: utf-8 -*-
"""
application/services/framework_build_service.py

Orchestrates the full framework build pipeline:
  1. Parse and validate config
  2. Detect framework characteristics (if text mode)
  3. Extract legal articles
  4. Build the analysis prompt
  5. Generate the JS analyzer

This class depends only on domain interfaces — never on concrete infrastructure.
"""
import json
import os
import tempfile
from typing import Dict, Any

from domain.interfaces.i_framework_parser import IFrameworkParser
from application.dto.framework_dtos import BuildRequestDto, BuildResultDto, FrameworkConfigDto


# UI strings keyed by ISO language code
_UI_STRINGS: Dict[str, Dict[str, str]] = {
    "en": {
        "analyze_button": "Analyze", "reset_button": "Reset",
        "placeholder": "Paste your text here...", "results_heading": "Analysis Results",
        "copy_button": "Copy Results", "no_violations": "No issues found.",
        "violations_found": "Potential issues found:", "see_details": "See details",
        "violation_text": "The text may violate", "references": "References",
        "download_report": "Download Report",
    },
    "es": {
        "analyze_button": "Analizar", "reset_button": "Restablecer",
        "placeholder": "Pegue su texto aquí...", "results_heading": "Resultados del Análisis",
        "copy_button": "Copiar Resultados", "no_violations": "No se encontraron problemas.",
        "violations_found": "Posibles problemas encontrados:", "see_details": "Ver detalles",
        "violation_text": "El texto puede violar", "references": "Referencias",
        "download_report": "Descargar Informe",
    },
    "pt": {
        "analyze_button": "Analisar", "reset_button": "Redefinir",
        "placeholder": "Cole seu texto aqui...", "results_heading": "Resultados da Análise",
        "copy_button": "Copiar Resultados", "no_violations": "Nenhum problema encontrado.",
        "violations_found": "Possíveis problemas encontrados:", "see_details": "Ver detalhes",
        "violation_text": "O texto pode violar", "references": "Referências",
        "download_report": "Baixar Relatório",
    },
    "it": {
        "analyze_button": "Analizzare", "reset_button": "Ripristina",
        "placeholder": "Incolla il tuo testo qui...", "results_heading": "Risultati dell'Analisi",
        "copy_button": "Copia Risultati", "no_violations": "Nessun problema trovato.",
        "violations_found": "Potenziali problemi trovati:", "see_details": "Vedi dettagli",
        "violation_text": "Il testo potrebbe violare", "references": "Riferimenti",
        "download_report": "Scarica Rapporto",
    },
    "hi": {
        "analyze_button": "विश्लेषण करें", "reset_button": "रीसेट करें",
        "placeholder": "अपना टेक्स्ट यहां पेस्ट करें...", "results_heading": "विश्लेषण परिणाम",
        "copy_button": "परिणाम कॉपी करें", "no_violations": "कोई समस्या नहीं मिली।",
        "violations_found": "संभावित समस्याएँ मिलीं:", "see_details": "विवरण देखें",
        "violation_text": "टेक्स्ट उल्लंघन कर सकता है", "references": "संदर्भ",
        "download_report": "रिपोर्ट डाउनलोड करें",
    },
}


class FrameworkBuildService:
    """
    Application service for the framework build pipeline.
    Inject an IFrameworkParser implementation at construction time.
    """

    def __init__(self, parser: IFrameworkParser) -> None:
        self._parser = parser

    # ── Public entry point ───────────────────────────────────────────────────

    def build(self, request: BuildRequestDto) -> BuildResultDto:
        try:
            config = self._parse_and_validate_config(request)
            config, framework_text = self._resolve_mode(config, request)
            full_prompt = self._parser.build_enhanced_legal_prompt(
                config, config.pop("_extracted_sections"), framework_text
            )
            js_content = self._generate_js(config, full_prompt)
            return BuildResultDto(
                success=True,
                generated_prompt=full_prompt,
                generated_js=js_content,
                filename=request.output_filename,
                parser_used="integrated",
                language_used=request.output_language,
            )
        except (ValueError, KeyError) as exc:
            return BuildResultDto(success=False, error=str(exc))
        except Exception as exc:
            return BuildResultDto(success=False, error=f"An internal error occurred: {exc}")

    # ── Private helpers ──────────────────────────────────────────────────────

    def _parse_and_validate_config(self, request: BuildRequestDto) -> Dict[str, Any]:
        try:
            config: Dict[str, Any] = json.loads(request.config_json_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON configuration: {exc}") from exc

        if "framework_name" not in config:
            raise ValueError("Configuration missing required key: framework_name")

        lang = request.output_language if request.output_language in _UI_STRINGS else "en"
        config["output_language"] = lang
        config["ui_strings"] = _UI_STRINGS[lang]
        return config

    def _resolve_mode(self, config: Dict[str, Any], request: BuildRequestDto):
        """Determine articles-mode vs text-mode and extract sections accordingly."""
        articles_mode = isinstance(config.get("articles"), list) and len(config["articles"]) > 0

        if not articles_mode and not request.framework_text:
            raise ValueError(
                'framework_text is required when no "articles" array is provided in config_json.'
            )

        if articles_mode:
            extracted_sections = self._parser.convert_user_articles(config["articles"])
            framework_text = request.framework_text or "\n\n".join(
                a.get("text") or a.get("content") or "" for a in config["articles"]
            )
        else:
            framework_text = request.framework_text
            try:
                detected_info = self._parser.detect_framework_characteristics(framework_text)
                for key, value in detected_info.items():
                    if key not in config or not config[key] or config[key] == "Unknown":
                        config[key] = value
            except Exception:
                pass  # detection is best-effort
            try:
                extracted_sections = self._parser.extract_legal_articles_with_context(framework_text)
            except Exception:
                extracted_sections = {"Full Document": {"content": framework_text, "metadata": {}}}

        config["_extracted_sections"] = extracted_sections
        return config, framework_text

    def _generate_js(self, config: Dict[str, Any], prompt: str) -> str:
        fd, temp_path = tempfile.mkstemp(suffix=".js")
        try:
            os.close(fd)
            self._parser.generate_integrated_js_analyzer(config, prompt, temp_path)
            with open(temp_path, "r", encoding="utf-8") as f:
                return f.read()
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
