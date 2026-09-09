# -*- coding: utf-8 -*-
"""
application/services/analyzer_pack_builder.py

AnalyzerPackBuilder — generates a golden analyzer pack (v2.4) from a law
corpus entry.  Output conforms exactly to the specification in
architecture/pinocchio-input/golden_analyzer.md and mirrors the structure
of the MC99 golden reference in architecture/pinocchio-input/MC99Analyzer/.

Pack contents:
  {Code}Analyzer.js    — self-contained JavaScript analyzer module
  config.json          — framework metadata + full articles array
  generated_prompt.txt — plain-text copy of ANALYSIS_TEMPLATE (for audit)
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from domain.services.article_classifier import ArticleClassifier
from infrastructure.law.law_registry import LawRegistry

# ---------------------------------------------------------------------------
# Helpers to produce JavaScript-safe escaped backtick fragments.
# Inside a JS template literal (backtick string) backticks must be escaped
# as \`.  When we write that to a file from Python we need: \`  (backslash
# followed by a backtick).  In Python source, the backslash must itself be
# escaped: "\\`".
# ---------------------------------------------------------------------------
_BT3 = "\\`\\`\\`"        # → \`\`\`  (JS: opening/closing code fence)
_BT3J = "\\`\\`\\`json"   # → \`\`\`json
_BT1 = "\\`"              # → \`      (single inline backtick)

# Language defaults per jurisdiction
_LANG_MAP = {"BR": "Portuguese", "CL": "Español (Spanish)", "INT": "English"}

# Jurisdictional interpretation notes
_JURIS_NOTES = {
    "BR": (
        "- Apply Brazilian civil law principles (LINDB, constitutional supremacy)\n"
        "- Consider hierarchical norm structure: Constitution > Federal Law > Regulation\n"
        "- Interpret mandatory obligations strictly; rights provisions broadly\n"
        "- Account for CIVIL_LAW drafting style"
    ),
    "CL": (
        "- Apply Chilean civil law principles\n"
        "- Consider constitutional hierarchy: Constitution > Organic Laws > Ordinary Laws\n"
        "- Apply DGAC/ANAC regulatory authority where aviation-specific\n"
        "- Account for CIVIL_LAW drafting style"
    ),
    "INT": (
        "- Apply international law interpretation principles\n"
        "  (Vienna Convention on the Law of Treaties, Art. 31-33)\n"
        "- Consider hierarchy of norms: treaty > domestic implementing law\n"
        "- Distinguish binding standards from recommendations\n"
        "- Account for MIXED legal drafting style"
    ),
}
_DEFAULT_JURIS_NOTE = (
    "- Apply applicable domestic law principles\n"
    "- Consider hierarchy of norms in the relevant jurisdiction\n"
    "- Account for applicable legal drafting style"
)

# Framework type display mapping
_TYPE_DISPLAY = {
    "national_law": "national law",
    "national_regulation": "national regulation",
    "international_treaty": "international treaty",
    "international_standard": "international standard",
    "industry_standard": "industry standard",
    "constitution": "constitution",
}


# ---------------------------------------------------------------------------
# Result DTO
# ---------------------------------------------------------------------------

@dataclass
class AnalyzerPackResult:
    success: bool
    framework_code: str = ""
    js_filename: str = ""
    js_content: str = ""
    config: dict = None      # the config dict (not serialised)
    config_json: str = ""    # JSON string
    generated_prompt: str = ""
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class AnalyzerPackBuilder:
    """
    Builds a golden v2.4 analyzer pack from a law corpus entry.

    Usage::

        from infrastructure.law.law_registry import LawRegistry
        registry = LawRegistry()
        builder = AnalyzerPackBuilder(registry)
        result = builder.build("CBA")
        open("CBAAnalyzer.js", "w").write(result.js_content)
    """

    def __init__(self, law_registry: LawRegistry) -> None:
        self._registry = law_registry
        self._classifier = ArticleClassifier()

    # ── Public entry-point ────────────────────────────────────────────────

    def build(self, framework_code: str) -> AnalyzerPackResult:
        meta = self._registry.get_framework_meta(framework_code)
        if meta is None:
            return AnalyzerPackResult(
                success=False,
                framework_code=framework_code,
                error=f"Framework '{framework_code}' not found in law registry.",
            )

        articles = self._registry.articles_for_framework(framework_code)
        if not articles:
            return AnalyzerPackResult(
                success=False,
                framework_code=framework_code,
                error=f"No articles found for framework '{framework_code}'.",
            )

        config = self._build_config(meta, articles)
        analysis_template = self._build_analysis_template(meta, articles)
        system_prompt = self._build_system_prompt(meta, articles)
        js_content = self._assemble_js(meta, config, analysis_template, system_prompt)
        config_json = json.dumps(config, ensure_ascii=False, indent=2)
        code = meta["framework_code"]
        js_filename = code + "Analyzer.js"

        return AnalyzerPackResult(
            success=True,
            framework_code=code,
            js_filename=js_filename,
            js_content=js_content,
            config=config,
            config_json=config_json,
            generated_prompt=analysis_template,
        )

    # ── Config builder ────────────────────────────────────────────────────

    def _build_config(self, meta: dict, articles: list) -> dict:
        return {
            "framework_name": meta["framework_name"],
            "jurisdiction": meta["jurisdiction"],
            "framework_code": meta["framework_code"],
            "framework_type": meta.get("framework_type", "national_law"),
            "legal_style": meta.get("legal_style", "CIVIL_LAW").lower().replace("_", "_"),
            "articles": articles,
            "output_language": "en",
            "ui_strings": {
                "analyze_button": "Analyze",
                "reset_button": "Reset",
                "placeholder": "Paste your text here...",
                "results_heading": "Analysis Results",
                "copy_button": "Copy Results",
                "no_violations": "No issues found.",
                "violations_found": "Potential issues found:",
                "see_details": "See details",
                "violation_text": "The text may violate",
                "references": "References",
                "download_report": "Download Report",
            },
        }

    # ── ANALYSIS_TEMPLATE builder ─────────────────────────────────────────

    def _build_analysis_template(self, meta: dict, articles: list) -> str:
        name = meta["framework_name"]
        jur = meta["jurisdiction"]
        code = meta["framework_code"]
        ftype = meta.get("framework_type", "national_law").replace("_", " ").title()
        style = meta.get("legal_style", "CIVIL_LAW").upper()
        eli_prefix = meta.get("eli_prefix", jur + "." + code)

        # Pick a representative article for the golden example in the template
        example_art = self._pick_example_article(articles)
        example_eli = example_art.get("eli_id", eli_prefix + ".Art.1") if example_art else eli_prefix + ".Art.1"
        lang_instruction = _LANG_MAP.get(jur, "English")
        juris_notes = _JURIS_NOTES.get(jur, _DEFAULT_JURIS_NOTE)
        articles_ref = self._build_articles_reference(articles)
        eli_checklist_note = eli_prefix + ".C<chapter>.Art.<number>"

        parts = [
            "LEGAL COMPLIANCE ANALYSIS REQUEST\n",
            "\n",
            "FRAMEWORK: " + name + "\n",
            "JURISDICTION: " + jur + "\n",
            "FRAMEWORK TYPE: " + ftype + "\n",
            "LEGAL STYLE: " + style + "\n",
            "FRAMEWORK CODE: " + code + "\n",
            "\n",
            "## CRITICAL OUTPUT FORMATTING RULES\n",
            "\n",
            "⚠️ **VIOLATIONS SECTION - STRICT REQUIREMENTS:**\n",
            "\n",
            "1. **ONLY include actual violations** - Do NOT include:\n",
            "   - Metadata headers (Framework:, Jurisdiction:, Analysis Date:, etc.)\n",
            '   - Negative findings ("NO VIOLATIONS IDENTIFIED", "Not applicable")\n',
            "   - Recommendations for other frameworks to apply\n",
            "   - General legal context or background information\n",
            "   - Transcript evidence descriptions that are not violations\n",
            "   - Severity assessments as standalone entries\n",
            "   - Article explanations or definitions\n",
            "\n",
            "2. **Each violation MUST start with a clear label:**\n",
            '   - ✅ GOOD: "a) Violation of Right to Information"\n',
            '   - ✅ GOOD: "VIOLATION CATEGORY A: Improper Denial of Service"\n',
            '   - ✅ GOOD: "b) Breach of Due Process Requirements"\n',
            '   - ❌ BAD: "The crew\'s repeated demands..." (narrative)\n',
            '   - ❌ BAD: "Primary Rationale:" (metadata)\n',
            '   - ❌ BAD: "Legal Context:" (background)\n',
            '   - ❌ BAD: "This represents a failure..." (assessment)\n',
            "\n",
            "3. **Structure for EACH violation:**\n",
            "   " + _BT3 + "\n",
            "   a) [VIOLATION NAME - Action-oriented, specific]\n",
            "   \n",
            '   Transcript Evidence: "[exact quote]" [timestamp]\n',
            "   \n",
            '   Legal Reference: Article X: "[exact article text]"\n',
            "   \n",
            '   Analysis: [How the provision was violated, why it matters. SEVERITY MUST BE INTEGRATED HERE, e.g., "This constitutes a HIGH severity violation because..." DO NOT create separate "Severity:" line]\n',
            "   " + _BT3 + "\n",
            "\n",
            "4. **CANONICAL OUTPUT REQUIRED (v2.4)** – After Section 2, output a JSON code block with this exact v2.4 ontology structure:\n",
            "   " + _BT3J + "\n",
            "   {\n",
            '     "ontology_version": "2.4",\n',
            '     "framework": "' + eli_prefix + '",\n',
            '     "violations": [\n',
            "       {\n",
            '         "node_id": "VIOL_<8-char-sha256>",\n',
            '         "type": "Violation",\n',
            '         "category": "<snake_case_category>",\n',
            '         "description": "<specific description of the breach, citing article and conduct>",\n',
            '         "timestamp": "<ISO8601_timestamp_of_incident>",\n',
            '         "severity": "critical|high|medium|low",\n',
            '         "confidence": 0.80,\n',
            '         "framework": "' + eli_prefix + '",\n',
            '         "articles_violated": ["' + example_eli + '"],\n',
            '         "evidence_node_ids": ["EVID_<hash>"],\n',
            '         "supporting_segments": ["SEGM_<hash>"],\n',
            '         "applicability_basis": "APPL_<hash>"\n',
            "       }\n",
            "     ],\n",
            '     "actions": [\n',
            "       {\n",
            '         "node_id": "ACTN_<hash>",\n',
            '         "type": "Action",\n',
            '         "action_type": "<snake_case_action_type>",\n',
            '         "description": "<observable conduct description>",\n',
            '         "sequence_index": 1,\n',
            '         "timestamp": "<ISO8601>",\n',
            '         "actor_role": "ROLE_<hash>"\n',
            "       }\n",
            "     ],\n",
            '     "actor_roles": [\n',
            "       {\n",
            '         "node_id": "ROLE_<hash>",\n',
            '         "type": "ActorRole",\n',
            '         "function": "airline_staff|police_officer|regulator_agent|unknown_role",\n',
            '         "context": "<functional role description — NO personal names or identifiers>"\n',
            "       }\n",
            "     ],\n",
            '     "evidences": [\n',
            "       {\n",
            '         "node_id": "EVID_<hash>",\n',
            '         "type": "Evidence",\n',
            '         "evidence_type": "transcript",\n',
            '         "source": "<transcript reference>",\n',
            '         "timestamp": "<ISO8601_start_time>",\n',
            '         "description": "<what the evidence shows>",\n',
            '         "confidence": 0.9,\n',
            '         "transcript_node_id": "TRNS_<hash>"\n',
            "       }\n",
            "     ]\n",
            "   }\n",
            "   " + _BT3 + "\n",
            "\n",
            "   **GOLDEN CASE EXAMPLE** (authoritative reference — generic_compliance_example_v24):\n",
            "   " + _BT3J + "\n",
            self._build_golden_example_json(meta, example_art),
            "   " + _BT3 + "\n",
            "\n",
            "   **Node ID rules:** " + _BT1 + "VIOL_" + _BT1 + " = SHA256(case_id|framework|articles_violated|category)[:8]; "
            + _BT1 + "EVID_" + _BT1 + " = SHA256(case_id|source|timestamp|description)[:8]; "
            + _BT1 + "ACTN_" + _BT1 + " = SHA256(violation_id|action_type)[:8]; "
            + _BT1 + "ROLE_" + _BT1 + " = SHA256(case_id|function)[:8].  \n",
            "   **Severity MUST be lowercase:** " + _BT1 + "critical" + _BT1 + ", " + _BT1 + "high" + _BT1
            + ", " + _BT1 + "medium" + _BT1 + ", " + _BT1 + "low" + _BT1
            + " (map " + _BT1 + "MODERATE" + _BT1 + "→" + _BT1 + "medium" + _BT1
            + ", " + _BT1 + "HIGH" + _BT1 + "→" + _BT1 + "high" + _BT1 + ", etc.).  \n",
            "   **Actor functions MUST be functional roles only** — never personal names or identifiers.  \n",
            "   **Article IDs MUST use full ELI format:** " + _BT1 + eli_checklist_note + _BT1 + "  \n",
            "   If no violations exist, output the block with an empty " + _BT1 + "violations" + _BT1 + " array.\n",
            "\n",
            "5. **Forbidden patterns - DO NOT generate:**\n",
            '   - Lines starting with: "Analyst:", "Framework:", "Note:", "Important:", "Context:", "Rationale:"\n',
            '   - **STANDALONE SEVERITY LINES:** "Severity: HIGH -", "Severity: CRITICAL -", "Severity: MODERATE -", "Severity: LOW -"\n',
            '   - Quoted article definitions: "Article 26 (general_provision):" followed by explanatory text\n',
            '   - Recommendations: "The ' + name + ' should be applied...", "Use other framework instead..."\n',
            "   - Timestamp evidence as violations: [2.87-3.52] transcript excerpts\n",
            '   - Negative statements: "Does not constitute...", "Not applicable...", "Framework does not apply..."\n',
            '   - Introduction preambles: "Based on the analysis of the provided transcript, the following violations..."\n',
            "\n",
            "### A. VIOLATION IDENTIFICATION GUIDELINES\n",
            "\n",
            "**What constitutes a violation:**\n",
            "- A specific action that breaches a specific legal provision\n",
            "- Must have: (1) Observable conduct (2) Violated article (3) Legal harm\n",
            "\n",
            "**What is NOT a violation:**\n",
            "- Framework applicability assessments\n",
            "- Recommendations to use different frameworks\n",
            "- Legal background or context\n",
            "- Article definitions or explanations\n",
            "- Procedural notes or jurisdictional clarifications\n",
            "\n",
            "### B. SPECIFIC LEGAL PROVISIONS FOR REFERENCE:\n",
            "\n",
            articles_ref,
            "\n",
            "### C. JURISDICTIONAL CONSIDERATIONS:\n",
            juris_notes + "\n",
            "\n",
            "### D. REQUIRED ANALYSIS STRUCTURE:\n",
            "\n",
            "#### **SECTION 1: VIOLATIONS IDENTIFIED** (If any)\n",
            "\n",
            "**a) [Violation Name - e.g., Failure to Comply with Statutory Obligation]**\n",
            "\n",
            "Transcript Evidence: \"[Exact quote showing the violating behavior]\" [timestamp]\n",
            "\n",
            "Legal Reference: Article X: \"[Exact article text that was violated]\"\n",
            "\n",
            "Analysis: [Explain HOW this specific conduct violates this specific provision. Reference the juridical value and legal intent of the provision. INCLUDE SEVERITY ASSESSMENT HERE — integrate \"This constitutes a [critical/high/medium/low] severity violation because [brief justification based on impact and legal hierarchy]\" within this analysis paragraph, NOT as a separate line.]\n",
            "\n",
            "---\n",
            "\n",
            "**b) [Second Violation Name]**\n",
            "\n",
            "Transcript Evidence: \"[Exact quote]\" [timestamp]\n",
            "\n",
            "Legal Reference: Article Y: \"[Exact article text]\"\n",
            "\n",
            "Analysis: [Explain violation with severity integrated: \"This represents a [critical/high/medium/low] violation as [justification]...\" DO NOT create separate \"Severity:\" lines.]\n",
            "\n",
            "---\n",
            "\n",
            "[Continue for each discrete violation - aim for 3-8 violations maximum, only when genuinely applicable]\n",
            "\n",
            "⚠️ **CRITICAL**: Do NOT create standalone lines starting with \"Severity:\" - integrate severity assessment WITHIN the Analysis paragraph. Severity values are LOWERCASE in the canonical output (e.g., \"medium\", \"high\").\n",
            "\n",
            "#### **SECTION 2: OVERALL ASSESSMENT** (Separate from violations)\n",
            "\n",
            "**Systemic Patterns:**\n",
            "[Analysis of whether violations indicate systematic compliance failure vs. isolated incidents]\n",
            "\n",
            "**Legal Consequences:**\n",
            "[Potential remedies, penalties, or legal actions available under this framework]\n",
            "\n",
            "**Recommendations:**\n",
            "[Specific corrective actions - these go here, NOT in the violations section]\n",
            "\n",
            "#### **SECTION 3: CANONICAL BUNDLE** (machine-readable – required)\n",
            "\n",
            "Output the JSON block exactly as specified in Rule 4 above.\n",
            "Start with: " + _BT3J + "  — end with: " + _BT3 + "  — no prose around it.\n",
            "\n",
            "### E. LEGAL PRECISION REQUIREMENTS:\n",
            "- Always quote EXACT article text, not just article numbers\n",
            "- Consider the hierarchy of legal norms\n",
            "- Reference specific legal principles (good faith, proportionality, due process)\n",
            "- Distinguish between procedural and substantive violations\n",
            "- Consider cumulative impact of multiple violations\n",
            "\n",
            "### F. QUALITY CONTROL CHECKLIST\n",
            "\n",
            "Before finalizing your analysis, verify:\n",
            "- [ ] Every violation has a clear category label (a, b, c...)\n",
            "- [ ] No metadata headers in violations section\n",
            "- [ ] No \"NO VIOLATIONS\" entries as violation items\n",
            "- [ ] No article explanations masquerading as violations\n",
            "- [ ] No framework recommendations in violations section\n",
            "- [ ] Each violation is a discrete, actionable breach\n",
            "- [ ] Severity uses critical/high/medium/low only (lowercase — map MODERATE→medium, HIGH→high, etc.)\n",
            "- [ ] Canonical JSON block is present after Section 2 (empty array if no violations)\n",
            "- [ ] All severity values in the JSON block are lowercase\n",
            "- [ ] actor_roles uses functional role names only (no personal names)\n",
            "- [ ] articles_violated uses full ELI IDs (" + eli_checklist_note + ")\n",
            "\n",
            "## FINAL OUTPUT MUST:\n",
            "1. Be in " + lang_instruction + " (aligned with " + jur + " jurisdiction)\n",
            "2. Use precise legal terminology appropriate to jurisdiction\n",
            "3. Clearly separate violations from commentary/recommendations\n",
            "4. Only include actual violations - if none exist, state clearly in Section 2\n",
            "5. Reference specific remedies available under the framework\n",
            "6. End with the canonical JSON block (Rule 4 schema) — always required\n",
        ]
        return "".join(parts)

    # ── SYSTEM_PROMPT builder ─────────────────────────────────────────────

    def _build_system_prompt(self, meta: dict, articles: list) -> str:
        name = meta["framework_name"]
        jur = meta["jurisdiction"]
        code = meta["framework_code"]
        eli_prefix = meta.get("eli_prefix", jur + "." + code)
        example_art = self._pick_example_article(articles)
        example_eli = example_art.get("eli_id", eli_prefix + ".Art.1") if example_art else eli_prefix + ".Art.1"
        example_text_excerpt = ""
        if example_art:
            t = example_art.get("text", "")
            example_text_excerpt = (t[:200] + "...") if len(t) > 200 else t

        # pick 2-3 key articles to highlight in legal precision notes
        key_arts = [a for a in articles if a.get("article_number") not in ("0", "58", "59")][:3]
        key_arts_note = "\n".join(
            "   - " + a.get("eli_id", "") + ": " + (a.get("text", "")[:100] + "...")
            for a in key_arts
        ) if key_arts else "   - See articles reference list above"

        parts = [
            "You are a specialized legal analyst for " + name + " (" + code + "), "
            "operating under the Awareness Legal Intelligence Ontology v2.4.\n",
            "\n",
            "## GOLDEN REFERENCE\n",
            "\n",
            "The following is the authoritative example structure. Use it as your exact structural and semantic guide:\n",
            "\n",
            "**Golden Case**: generic_compliance_example_v24  \n",
            "**Transcript excerpt**: \"[Party representative] denied the request citing [reason]\" [HH:MM:SS] — "
            "conduct constitutes failure to meet statutory obligation.  \n",
            "**Correct violation found**:\n",
            "- category: failure_to_comply_with_statutory_obligation  \n",
            "- article: " + example_eli + " — \"" + example_text_excerpt[:150] + "\"  \n",
            "- severity: high (lowercase)  \n",
            "- confidence: 0.80  \n",
            "- reasoning: The provision establishes a mandatory obligation. The conduct described constitutes "
            "a direct failure to comply. Institutional attribution must be explicit, not personal.  \n",
            "\n",
            "## CRITICAL FORMATTING RULES\n",
            "\n",
            "1. **WHAT TO INCLUDE**: Only actual, discrete violations with:\n",
            "   - Clear violation label: a), b), c) OR \"VIOLATION CATEGORY A:\"\n",
            "   - Transcript evidence with timestamps\n",
            "   - Exact article reference and quote\n",
            "   - Analysis explaining HOW the provision was violated\n",
            "   - Severity INTEGRATED within analysis paragraph (LOWERCASE: critical/high/medium/low)\n",
            "\n",
            "2. **STRICTLY FORBIDDEN - DO NOT GENERATE**:\n",
            '   ❌ Metadata headers: "Framework:", "Jurisdiction:", "Analysis Date:", "Applicable Incident:"\n',
            '   ❌ Section headers: "LEGAL COMPLIANCE ANALYSIS", "VIOLATIONS", "LEGAL CONTEXT", "NEGATIVE FINDINGS"\n',
            '   ❌ Standalone severity lines: "Severity: HIGH -", "Severity: CRITICAL -", "Severity: MEDIUM -"\n',
            '   ❌ Introduction preambles: "Based on the analysis...", "The following violations..."\n',
            '   ❌ Negative findings as violations: "No Violation -", "Not applicable", "Lack of Evidence"\n',
            '   ❌ Applicability assessments as violations: "Applicability (Article 1):", "Jurisdiction (Article 3):"\n',
            '   ❌ Article explanations: "Article X defines...", "The Convention applies to..."\n',
            '   ❌ Recommendations as violations: "Should apply ' + name + ' instead..."\n',
            "   ❌ Personal names or identifiers in actor_roles — use only functional roles\n",
            "   ❌ UPPERCASE severity in canonical JSON — always lowercase\n",
            "\n",
            "3. **REQUIRED STRUCTURE** - Each violation MUST be:\n",
            "   a) [Violation Name]\n",
            "   \n",
            '   Transcript Evidence: "[exact quote]" [timestamp]\n',
            "   \n",
            '   Legal Reference: Article X: "[exact article text]"\n',
            "   \n",
            '   Analysis: [Explain violation. Include: "This constitutes a [severity] violation because..." '
            "WITHIN this paragraph. NO separate Severity: line]\n",
            "\n",
            "4. **v2.4 CANONICAL OUTPUT REQUIRED** — The JSON block MUST use:\n",
            "   - " + _BT1 + "node_id" + _BT1 + " prefixes: VIOL_, EVID_, ACTN_, ROLE_, SEGM_\n",
            "   - " + _BT1 + "type" + _BT1 + " field on every node\n",
            "   - " + _BT1 + "articles_violated" + _BT1 + " as array of full ELI IDs (e.g., \""
            + example_eli + "\")\n",
            "   - " + _BT1 + "actor_roles" + _BT1 + " array with " + _BT1 + "function" + _BT1
            + " field (NOT " + _BT1 + "actors" + _BT1 + " with " + _BT1 + "actor_id" + _BT1 + ")\n",
            "   - severity in lowercase: critical / high / medium / low\n",
            "   - No personal names in any field\n",
            "\n",
            "5. **LEGAL PRECISION**:\n",
            "   - Quote EXACT article text, not just numbers\n",
            "   - Apply " + jur + " legal interpretation principles\n",
            "   - Distinguish procedural vs substantive violations\n",
            "   - Key articles for " + code + ":\n",
            key_arts_note + "\n",
            "\n",
            "6. **OUTPUT**: \n",
            "   - Language: ${language === 'auto' ? '"
            + _LANG_MAP.get(jur, "English") + " for " + jur + " frameworks, English otherwise' : language}\n",
            "   - Only list ACTUAL violations (target: 1-5 maximum for focused incidents)\n",
            "   - If NO violations exist, state clearly in Section 2, do NOT create violation entries\n",
            "   - Always end with the canonical v2.4 JSON block (Rule 4 schema)\n",
        ]
        return "".join(parts)

    # ── JS file assembler ─────────────────────────────────────────────────

    def _assemble_js(
        self,
        meta: dict,
        config: dict,
        analysis_template: str,
        system_prompt: str,
    ) -> str:
        name = meta["framework_name"]
        jur = meta["jurisdiction"]
        code = meta["framework_code"]
        ftype = meta.get("framework_type", "national_law")
        style = meta.get("legal_style", "CIVIL_LAW").lower()
        article_count = len(config.get("articles", []))
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", ".000000")
        fn_name = self._js_function_name(name)
        ftype_display = _TYPE_DISPLAY.get(ftype, ftype.replace("_", " "))
        config_json = json.dumps(config, ensure_ascii=False, indent=2)

        # The analysis template and system prompt are JS template literal values —
        # we need to escape any backtick that appears in them (other than the ones
        # we intentionally placed as \`\`\` fences).  Our pre-escaped _BT3 etc.
        # already contain the backslash, so they are safe.  We just need to make
        # sure that the raw Python text portions do not contain unescaped backticks.
        tmpl_escaped = _escape_js_template(analysis_template)
        sys_escaped = _escape_js_template(system_prompt)

        parts = [
            "/**\n",
            " * INTEGRATED LEGAL FRAMEWORK ANALYZER — GOLDEN REFERENCE\n",
            " * Framework: " + name + "\n",
            " * Jurisdiction: " + jur + "\n",
            " * Legal Style: " + style + "\n",
            " * Generated: " + ts + "\n",
            " * Version: Golden 2.4\n",
            " *\n",
            " * Articles loaded: " + str(article_count) + "\n",
            " *\n",
            " * Conforms to: architecture/pinocchio-input/golden_analyzer.md\n",
            " * Ontology: Awareness Legal Intelligence Ontology v2.4\n",
            " */\n",
            "\n",
            "function " + fn_name + "(options) {\n",
            "    const { \n",
            "        targetContainerId, \n",
            "        getTranscriptText, \n",
            "        onAnalyze,\n",
            "        analysisMode = 'standard',\n",
            "        language = 'auto'\n",
            "    } = options;\n",
            "\n",
            "    const LEGAL_CONFIG = ",
            config_json,
            ";\n",
            "\n",
            "    const ANALYSIS_TEMPLATE = `",
            tmpl_escaped,
            "`;\n",
            "\n",
            "    const SYSTEM_PROMPT = `",
            sys_escaped,
            "`;\n",
            "\n",
            "    // Create integrated analysis panel\n",
            "    const createLegalPanel = () => {\n",
            "        const panel = document.createElement('div');\n",
            "        panel.className = 'integrated-legal-panel';\n",
            "        panel.innerHTML = `\n",
            "            <div class=\"panel-header legal-header\">\n",
            "                <h3><span class=\"legal-icon\">⚖️</span> " + _js_html_escape(name) + " Analysis</h3>\n",
            "                <div class=\"legal-metadata\">\n",
            "                    <span class=\"badge jurisdiction\">" + jur + "</span>\n",
            "                    <span class=\"badge type\">" + ftype_display + "</span>\n",
            "                    <span class=\"badge style\">" + style + "</span>\n",
            "                </div>\n",
            "            </div>\n",
            "            <div class=\"panel-body\">\n",
            "                <div class=\"legal-config-section\">\n",
            "                    <h4>Legal Framework Configuration</h4>\n",
            "                    <pre class=\"legal-config\">${JSON.stringify(LEGAL_CONFIG, null, 2)}</pre>\n",
            "                </div>\n",
            "                <div class=\"analysis-instructions\">\n",
            "                    <h4>Legal Analysis Template</h4>\n",
            "                    <textarea class=\"legal-prompt\" rows=\"15\">${ANALYSIS_TEMPLATE}</textarea>\n",
            "                </div>\n",
            "                <div class=\"analysis-controls\">\n",
            "                    <div class=\"control-group\">\n",
            "                        <label>Analysis Mode:</label>\n",
            "                        <select class=\"mode-select\">\n",
            "                            <option value=\"standard\">Standard Legal Analysis</option>\n",
            "                            <option value=\"detailed\">Detailed with Jurisprudence</option>\n",
            "                            <option value=\"remedial\">Focus on Remedies</option>\n",
            "                        </select>\n",
            "                    </div>\n",
            "                    <div class=\"control-group\">\n",
            "                        <label>Output Language:</label>\n",
            "                        <select class=\"language-select\">\n",
            "                            <option value=\"auto\">Auto (Framework-based)</option>\n",
            "                            <option value=\"pt\">Português</option>\n",
            "                            <option value=\"en\">English</option>\n",
            "                            <option value=\"es\">Español</option>\n",
            "                        </select>\n",
            "                    </div>\n",
            "                    <button class=\"execute-legal-analysis\">\n",
            "                        <span class=\"icon\">⚖️</span> Execute Legal Analysis\n",
            "                    </button>\n",
            "                </div>\n",
            "            </div>\n",
            "        `;\n",
            "\n",
            "        panel.querySelector('.execute-legal-analysis').addEventListener('click', () => {\n",
            "            const userPrompt = panel.querySelector('.legal-prompt').value;\n",
            "            const analysisMode = panel.querySelector('.mode-select').value;\n",
            "            const outputLanguage = panel.querySelector('.language-select').value;\n",
            "            const transcriptText = getTranscriptText();\n",
            "\n",
            "            const legalAnalysisPackage = {\n",
            "                system_prompt: SYSTEM_PROMPT,\n",
            "                user_prompt: userPrompt,\n",
            "                transcript: transcriptText,\n",
            "                framework: '" + _js_str_escape(name) + "',\n",
            "                framework_metadata: LEGAL_CONFIG,\n",
            "                analysis_mode: analysisMode,\n",
            "                output_language: outputLanguage,\n",
            "                legal_parameters: {\n",
            "                    jurisdiction: '" + jur + "',\n",
            "                    framework_type: '" + ftype + "',\n",
            "                    legal_style: '" + style + "',\n",
            "                    requires_exact_citations: true,\n",
            "                    requires_severity_assessment: true,\n",
            "                    requires_systemic_assessment: true\n",
            "                },\n",
            "                timestamp: new Date().toISOString(),\n",
            "                version: 'integrated_2.0'\n",
            "            };\n",
            "\n",
            "            if (typeof onAnalyze === 'function') {\n",
            "                onAnalyze(legalAnalysisPackage);\n",
            "            }\n",
            "        });\n",
            "\n",
            "        return panel;\n",
            "    };\n",
            "\n",
            "    // Injection logic\n",
            "    const container = document.getElementById(targetContainerId);\n",
            "    if (!container) {\n",
            "        console.error(`[Integrated Legal Analyzer] Container #${targetContainerId} not found`);\n",
            "        return;\n",
            "    }\n",
            "\n",
            "    const panel = createLegalPanel();\n",
            "    container.appendChild(panel);\n",
            "\n",
            "    console.log(`[Integrated Legal] " + _js_str_escape(name) + " analyzer injected successfully`);\n",
            "    console.log(`  Jurisdiction: " + jur + "`);\n",
            "    console.log(`  Legal Style: " + style + "`);\n",
            "    console.log(`  Framework Type: " + ftype + "`);\n",
            "}\n",
            "\n",
            "// Module export\n",
            "if (typeof module !== 'undefined' && module.exports) {\n",
            "    module.exports = " + fn_name + ";\n",
            "}\n",
        ]
        return "".join(parts)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _build_articles_reference(self, articles: list) -> str:
        lines = []
        for art in articles:
            ref = art.get("reference", "")
            text = art.get("text", "")
            theme = art.get("theme", "")
            atype = self._classifier.classify(text)
            jval = self._classifier.assess_juridical_value(text, atype)
            weight = jval.get("interpretation_weight", "medium").upper()
            excerpt = (text[:200] + '"') if len(text) > 200 else (text + '"')
            lines.append(
                '**' + ref + '** (' + atype + ' | ' + theme + ' | MANDATORY):\n'
                '  "' + excerpt + '\n'
                '  [Interpretation weight: ' + weight + ']\n'
            )
        return "\n".join(lines) + "\n"

    def _build_golden_example_json(self, meta: dict, example_art: dict) -> str:
        jur = meta["jurisdiction"]
        code = meta["framework_code"]
        eli_prefix = meta.get("eli_prefix", jur + "." + code)
        eli = example_art.get("eli_id", eli_prefix + ".Art.1") if example_art else eli_prefix + ".Art.1"
        example_desc = (
            "Party (regulated_entity) failed to comply with the mandatory obligation established "
            "by " + eli + ". The party's conduct demonstrates a direct breach of the statutory "
            "requirement. The obligation is enforceable under " + eli_prefix + " framework provisions."
        )
        obj = {
            "ontology_version": "2.4",
            "framework": eli_prefix,
            "violations": [
                {
                    "node_id": "VIOL_ex000001",
                    "type": "Violation",
                    "category": "failure_to_comply_with_statutory_obligation",
                    "description": example_desc,
                    "timestamp": "2025-01-01T10:00:00Z",
                    "severity": "high",
                    "confidence": 0.80,
                    "framework": eli_prefix,
                    "articles_violated": [eli],
                    "evidence_node_ids": ["EVID_ex000001"],
                    "supporting_segments": ["SEGM_ex000001"],
                    "applicability_basis": "APPL_ex000001",
                }
            ],
            "actions": [
                {
                    "node_id": "ACTN_ex000001",
                    "type": "Action",
                    "action_type": "failure_to_comply_with_statutory_obligation",
                    "description": "Regulated entity failed to meet the applicable statutory requirement.",
                    "sequence_index": 1,
                    "timestamp": "2025-01-01T10:00:00Z",
                    "actor_role": "ROLE_ex000001",
                }
            ],
            "actor_roles": [
                {
                    "node_id": "ROLE_ex000001",
                    "type": "ActorRole",
                    "function": "regulated_entity",
                    "context": "Entity subject to " + eli_prefix + " obligations, party under review for compliance.",
                }
            ],
            "evidences": [
                {
                    "node_id": "EVID_ex000001",
                    "type": "Evidence",
                    "evidence_type": "transcript",
                    "source": "Audio/document recording, relevant segment",
                    "timestamp": "2025-01-01T10:00:00Z",
                    "description": "Exchange documenting the entity's failure to meet the statutory requirement.",
                    "confidence": 0.85,
                    "transcript_node_id": "TRNS_ex000001",
                }
            ],
        }
        # Indent each line 3 spaces (to align with surrounding template context)
        json_str = json.dumps(obj, ensure_ascii=False, indent=2)
        indented = "\n".join("   " + line for line in json_str.splitlines())
        return indented + "\n"

    def _pick_example_article(self, articles: list) -> dict | None:
        """Pick the first non-preamble, non-final-clause article."""
        skip_themes = {"Preamble", "Final Clauses", "Witness Clause", "Execution Clause"}
        for art in articles:
            num = str(art.get("article_number", ""))
            if num in ("0", "58", "59"):
                continue
            if art.get("theme", "") in skip_themes:
                continue
            return art
        return articles[0] if articles else None

    @staticmethod
    def _js_function_name(framework_name: str) -> str:
        """Derive a valid camelCase JS function name: inject<CamelCase>Analyzer."""
        # Strip accents
        nfkd = unicodedata.normalize("NFKD", framework_name)
        ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
        # Keep only alphanumeric and spaces
        clean = re.sub(r"[^a-zA-Z0-9 ]+", " ", ascii_name)
        # CamelCase
        camel = "".join(word.capitalize() for word in clean.split() if word)
        return "inject" + camel + "Analyzer"


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _escape_js_template(text: str) -> str:
    """
    Prepare text for embedding as the content of a JS template literal.

    The text already has intentional ``\\`\\`\\`` sequences (pre-escaped
    backtick fences) so we must NOT re-escape those backslashes.  We only
    need to escape raw backtick chars that appear in the Python source string
    and have not already been escaped.

    Strategy: replace any bare backtick (`` ` ``) that is NOT already
    preceded by a backslash with ``\\``+`` ` ``.
    """
    # Replace bare (unescaped) backtick with escaped backtick
    result = re.sub(r"(?<!\\)`", r"\\`", text)
    return result


def _js_str_escape(text: str) -> str:
    """Escape text for embedding inside JS single-quoted string."""
    return text.replace("\\", "\\\\").replace("'", "\\'")


def _js_html_escape(text: str) -> str:
    """Minimal HTML escaping for text placed in innerHTML."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
