#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ENHANCED LEGAL FRAMEWORK PARSER - INTEGRATED VERSION
Combines best elements from all parsers with enhanced legal precision
"""

import json
import argparse
import re
import os
import PyPDF2
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
import hashlib

class IntegratedLegalFrameworkParser:
    """
    Integrated parser combining:
    1. Version 1's balanced analysis structure
    2. Enhanced legal article extraction
    3. Standardized reporting
    4. Severity scaling with legal justification
    """
    
    def __init__(self):
        # Standard structure from Version 1
        self.analysis_structure = {
            "violations_section": {
                "format": "lettered_categories",
                "required": ["transcript_excerpt", "legal_reference", "analysis", "severity"],
                "severity_scale": {
                    "CRITICAL": "Fundamental rights violation with material impact",
                    "HIGH": "Substantial breach of core obligations", 
                    "MODERATE": "Procedural violation affecting rights",
                    "LOW": "Minor compliance issue"
                }
            },
            "summary_section": {
                "systemic_assessment": True,
                "recommendations": True,
                "legal_consequences": True
            }
        }
        
        # Enhanced legal extraction patterns
        self.legal_patterns = {
            "articles": [
                r'(?:Article|Art\.?|Artigo|Artículo|§|Seção|Sección|Section)\s*(\d+[a-z]?[\.\d]*)[:\-\s]+(.+?)(?=(?:Article|Art\.?|Artigo|Artículo|§|Seção|Sección|Section)\s*\d+|$)',
                r'Art\.\s*(\d+[º°]?)\s*[-–]\s*(.+)',
                r'(\d+[a-z]?)\s*\.\s*(.+)'
            ],
            "definitions": [
                r'("[^"]+"\s+(?:means|shall mean|entende-se por|se entiende por)\s+[^\.]+\.)',
                r'(?:Para os fins deste|For the purposes of|A los efectos de)[^\.]+\.[^\.]+\.'
            ],
            "obligations": [
                r'(shall|must|deve|deberá)\s+(?:provide|ensure|inform|notify|proteger)',
                r'(is required to|é obrigatório|es obligatorio)',
                r'(the .+ shall|o .+ deve|el .+ deberá)'
            ],
            "prohibitions": [
                r'shall not|must not|não deve|no deberá',
                r'prohibited|proibido|prohibido',
                r'may not|cannot|não pode|no puede'
            ]
        }
    
    def load_and_enhance_config(self, config_or_path: Any, framework_text: str) -> Dict[str, Any]:
        """
        Enhanced config loading with automatic legal framework detection
        """
        if isinstance(config_or_path, (str, Path)):
            with open(config_or_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        else:
            config = config_or_path
        
        # Auto-detect framework characteristics
        detected_info = self.detect_framework_characteristics(framework_text)
        
        # Only update if missing or unknown in original config
        for key, value in detected_info.items():
            if key not in config or not config[key] or config[key] == 'Unknown':
                config[key] = value
        
        # Ensure required analysis structure
        if 'analysis_structure' not in config:
            config['analysis_structure'] = self.analysis_structure
        
        # Standardize framework name
        config['framework_name'] = self.standardize_legal_name(
            config.get('framework_name', detected_info.get('detected_name', 'Legal Framework'))
        )
        
        return config
    
    def detect_framework_characteristics(self, text: str) -> Dict[str, Any]:
        """
        Enhanced framework detection with legal specificity
        """
        text_lower = text.lower()
        
        characteristics = {
            "detected_name": self.extract_framework_name(text),
            "jurisdiction": self.detect_jurisdiction(text_lower),
            "framework_type": self.detect_framework_type(text_lower),
            "legal_style": self.detect_legal_style(text),
            "has_severity_provisions": bool(re.search(r'severity|gravity|gravidade|gravedad', text_lower)),
            "has_penalty_provisions": bool(re.search(r'penalty|fine|sanction|multa|sanção|penalidad', text_lower)),
            "has_due_process": bool(re.search(r'due process|procedural fairness|contraditório|debido proceso', text_lower))
        }
        
        return characteristics
    
    def extract_framework_name(self, text: str) -> str:
        """
        Intelligent framework name extraction
        """
        patterns = [
            r'(?:LEI|Law|Act)\s+N[º°]?\s*([\d\.\/\-]+(?:\s+DE\s+\d{1,2}\s+DE\s+[A-Za-zç]+\s+DE\s+\d{4})?)',
            r'(?:LEI|law|act)\s+n[º°]?\s*\.?\s*(\d+[,.\d\/\-]*)',
            r'(?:CONVENTION|CONVENÇÃO|CONVENCIÓN)\s+(?:ON|DO|DE)?\s+([A-Z][A-Za-z\s]+(?:OF|ON|DE|DO)?)',
            r'(?:RESOLUÇÃO|RESOLUTION|RESOLUCIÓN)\s+(?:N[º°]?\s*)?(\d+[\/\-]?\d*)',
            r'(?:CÓDIGO|CODE|CÓDIGO)\s+DE\s+([A-Z][A-Za-z\s]+)',
            r'(?:ANEXO|ANNEX|ANEXO)\s+(\d+[A-Z]?)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        # Fallback: Extract from first meaningful line
        lines = text.split('\n')
        for line in lines:
            line_stripped = line.strip()
            # Look for lines that look like titles (capitals, decent length)
            if len(line_stripped) > 15 and len(line_stripped) < 200 and not line_stripped.isdigit():
                # Prefer lines that have legal keywords
                if any(keyword in line_stripped.lower() for keyword in ['lei', 'law', 'decreto', 'code', 'convention', 'resolução']):
                    return line_stripped
        
        # Last resort: just return a reasonable length line
        for line in lines:
            if len(line.strip()) > 20 and len(line.strip()) < 200 and not line.strip().isdigit():
                return line.strip()[:100]
        
        return "Legal Framework"
    
    def standardize_legal_name(self, name: str) -> str:
        """
        Standardize legal framework names while preserving legal precision
        """
        name_mapping = {
            "Lei 8.078/90": "Código de Defesa do Consumidor do Brasil (Lei 8.078/1990)",
            "Convenção de Montreal 1999": "Convenção para a Unificação de Certas Regras Relativas ao Transporte Aéreo Internacional (Montreal, 1999)",
            "CDC": "Código de Defesa do Consumidor do Brasil",
            "Montreal Convention": "Convention for the Unification of Certain Rules for International Carriage by Air (Montreal, 1999)"
        }
        
        return name_mapping.get(name, name)
    
    def detect_jurisdiction(self, text_lower: str) -> str:
        """
        Precise jurisdiction detection
        """
        jurisdiction_patterns = {
            "Brazil": [
                r'república federativa do brasil',
                r'presidência da república',
                r'lei brasileira',
                r'defesa do consumidor',  # More flexible pattern
                r'anac',
                r'código de defesa',
                r'brasil',
                r'brasileiro'
            ],
            "Chile": [
                r'república de chile',
                r'gobierno de chile',
                r'dgac',
                r'ley aeronáutica',
                r'ministerio de justicia',
                r'congreso nacional de chile',
                r'biblioteca del congreso',
                r'código penal',
                r'diario oficial de la república de chile'
            ],
            "International": [
                r'international civil aviation organization',
                r'icao',
                r'montreal convention',
                r'warsaw convention',
                r'tokyo convention',
                r'annex \d+',
                r'united nations'
            ],
            "European Union": [
                r'european union',
                r'eu regulation',
                r'ec no',
                r'european commission'
            ]
        }
        
        for jurisdiction, patterns in jurisdiction_patterns.items():
            if any(re.search(pattern, text_lower) for pattern in patterns):
                return jurisdiction
        
        return "Unknown"
    
    def detect_framework_type(self, text_lower: str) -> str:
        """
        Detect framework type with legal precision
        """
        if re.search(r'international convention|convenção internacional', text_lower):
            return "international_convention"
        elif re.search(r'law|lei|acto legislativo', text_lower):
            return "national_law"
        elif re.search(r'regulation|regulamento|reglamento', text_lower):
            return "regulation"
        elif re.search(r'code|código|codex', text_lower):
            return "code"
        elif re.search(r'resolution|resolução|resolución', text_lower):
            return "administrative_resolution"
        elif re.search(r'policy|política|corporate', text_lower):
            return "corporate_policy"
        
        return "legal_framework"
    
    def detect_legal_style(self, text: str) -> str:
        """
        Detect legal drafting style (civil law vs common law)
        """
        text_lower = text.lower()
        
        # Civil law indicators (Brazil, Chile, EU)
        civil_law_indicators = [
            r'art\.\s*\d+',
            r'parágrafo único',
            r'inciso [IVXLCDM]+',
            r'caput',
            r'seção [IVXLCDM]+'
        ]
        
        # Common law indicators
        common_law_indicators = [
            r'section \d+',
            r'subsection \([a-z]\)',
            r'schedule \d+',
            r'hereinafter referred to as',
            r'in accordance with'
        ]
        
        civil_count = sum(1 for pattern in civil_law_indicators if re.search(pattern, text_lower))
        common_count = sum(1 for pattern in common_law_indicators if re.search(pattern, text_lower))
        
        if civil_count > common_count:
            return "civil_law"
        elif common_count > civil_count:
            return "common_law"
        else:
            return "mixed"
    
    def extract_legal_articles_with_context(self, text: str) -> Dict[str, List[Dict]]:
        """
        Enhanced article extraction with legal context preservation
        """
        articles = {
            "numbered_articles": [],
            "definitions": [],
            "rights_provisions": [],
            "obligations": [],
            "prohibitions": [],
            "remedies_penalties": []
        }
        
        # Extract numbered articles with context
        for pattern in self.legal_patterns["articles"]:
            matches = re.finditer(pattern, text, re.IGNORECASE | re.DOTALL | re.MULTILINE)
            for match in matches:
                article_num = match.group(1).strip()
                article_content = match.group(2).strip()
                
                # Get context (previous and next 2 lines)
                lines = text.split('\n')
                match_start = text[:match.start()].count('\n')
                context_start = max(0, match_start - 2)
                context_end = min(len(lines), match_start + 5)
                context = '\n'.join(lines[context_start:context_end])
                
                # Classify article
                article_type = self.classify_article_with_legal_precision(article_content)
                
                articles["numbered_articles"].append({
                    "number": article_num,
                    "type": article_type,
                    "content": article_content[:300],  # Truncated for prompt
                    "full_content": article_content,
                    "context": context,
                    "juridical_value": self.assess_juridical_value(article_content, article_type)
                })
        
        # Extract definitions
        for pattern in self.legal_patterns["definitions"]:
            matches = re.finditer(pattern, text, re.IGNORECASE | re.DOTALL)
            for match in matches:
                articles["definitions"].append(match.group(0))
        
        # Extract obligations
        for pattern in self.legal_patterns["obligations"]:
            matches = re.finditer(pattern, text, re.IGNORECASE | re.DOTALL)
            for match in matches:
                # Get full sentence
                sentence_start = max(0, match.start() - 50)
                sentence_end = min(len(text), match.end() + 100)
                obligation_text = text[sentence_start:sentence_end].strip()
                articles["obligations"].append(obligation_text)
        
        # Extract prohibitions
        for pattern in self.legal_patterns["prohibitions"]:
            matches = re.finditer(pattern, text, re.IGNORECASE | re.DOTALL)
            for match in matches:
                # Get full sentence
                sentence_start = max(0, match.start() - 50)
                sentence_end = min(len(text), match.end() + 100)
                prohibition_text = text[sentence_start:sentence_end].strip()
                articles["prohibitions"].append(prohibition_text)
        
        return articles
    
    def classify_article_with_legal_precision(self, content: str) -> str:
        """
        Legal-precise article classification
        """
        content_lower = content.lower()
        
        # Rights-focused articles
        rights_keywords = ['right to', 'entitled to', 'shall have', 'may', 'freedom of', 'liberdade de']
        if any(keyword in content_lower for keyword in rights_keywords):
            return "rights_provision"
        
        # Obligation-focused articles
        obligation_keywords = ['shall', 'must', 'is required to', 'deve', 'deberá', 'obrigação']
        if any(keyword in content_lower for keyword in obligation_keywords):
            return "obligation"
        
        # Prohibition-focused articles
        prohibition_keywords = ['shall not', 'must not', 'prohibited', 'forbidden', 'proibido', 'prohibido']
        if any(keyword in content_lower for keyword in prohibition_keywords):
            return "prohibition"
        
        # Remedy/penalty articles
        remedy_keywords = ['compensation', 'damages', 'indemnity', 'penalty', 'fine', 'sanction', 'multa']
        if any(keyword in content_lower for keyword in remedy_keywords):
            return "remedy_penalty"
        
        # Procedural articles
        procedural_keywords = ['procedure', 'process', 'appeal', 'complaint', 'recurso', 'procedimento']
        if any(keyword in content_lower for keyword in procedural_keywords):
            return "procedural"
        
        # Definition articles
        definition_keywords = ['means', 'refers to', 'defined as', 'entende-se por', 'se entiende por']
        if any(keyword in content_lower for keyword in definition_keywords):
            return "definition"
        
        return "general_provision"
    
    def assess_juridical_value(self, content: str, article_type: str) -> Dict[str, str]:
        """
        Assess juridical value of article (hierarchy, enforceability)
        """
        content_lower = content.lower()
        
        value_assessment = {
            "hierarchy": "ordinary",
            "enforceability": "direct",
            "interpretation_weight": "medium"
        }
        
        # Hierarchy assessment
        if any(term in content_lower for term in ['fundamental right', 'human right', 'direito fundamental']):
            value_assessment["hierarchy"] = "constitutional"
        elif any(term in content_lower for term in ['principle', 'princípio', 'principio']):
            value_assessment["hierarchy"] = "principled"
        elif any(term in content_lower for term in ['shall', 'must', 'obligatory']):
            value_assessment["hierarchy"] = "mandatory"
        elif any(term in content_lower for term in ['may', 'optional', 'discretionary']):
            value_assessment["hierarchy"] = "discretionary"
        
        # Enforceability assessment
        if article_type == "rights_provision":
            value_assessment["enforceability"] = "direct_enforceable"
        elif article_type == "obligation":
            value_assessment["enforceability"] = "enforceable"
        elif article_type == "prohibition":
            value_assessment["enforceability"] = "strict_enforceable"
        elif article_type == "definition":
            value_assessment["enforceability"] = "interpretive"
        
        # Interpretation weight
        if value_assessment["hierarchy"] == "constitutional":
            value_assessment["interpretation_weight"] = "highest"
        elif value_assessment["hierarchy"] == "principled":
            value_assessment["interpretation_weight"] = "high"
        elif article_type in ["rights_provision", "obligation"]:
            value_assessment["interpretation_weight"] = "high"
        else:
            value_assessment["interpretation_weight"] = "medium"
        
        return value_assessment

    # ─────────────────────────────────────────────────────────────────────────
    # Actor / framework-code helpers  (ported from v4.py)
    # ─────────────────────────────────────────────────────────────────────────

    def normalize_actor_name(self, name: str, actor_type: str = "individual") -> str:
        """Normalize an actor name for deterministic ID generation."""
        if not name:
            return "UNKNOWN"
        if actor_type == "organization":
            if "latam" in name.lower():
                return "LATAM_AIRLINES"
            # Generic org
            n = re.sub(r'[áàãâä]', 'a', name, flags=re.I)
            n = re.sub(r'[éèêë]', 'e', n, flags=re.I)
            n = re.sub(r'[íìîï]', 'i', n, flags=re.I)
            n = re.sub(r'[óòôõö]', 'o', n, flags=re.I)
            n = re.sub(r'[úùûü]', 'u', n, flags=re.I)
            n = re.sub(r'[ç]', 'c', n, flags=re.I)
            return re.sub(r'[^A-Z0-9_]', '', n.upper())
        # Individual
        name_lower = name.lower()
        if "leandro" in name_lower or "disconzi" in name_lower:
            return "LEANDRO_DISCONZI"
        if "marinho" in name_lower or "andr" in name_lower:
            return "LEANDRO_DISCONZI"  # alias for the case passenger
        n = re.sub(r'[^A-Z0-9_]', '', name.upper())
        return n or "UNKNOWN"

    def _get_framework_code(self, framework_name: str) -> str:
        """Return a canonical short code for a framework name."""
        _map = {
            "Código de Defesa do Consumidor": "CDC",
            "Código Brasileiro de Aeronáutica": "CBA",
            "RESOLUÇÃO Nº 400": "R400", "Resolução ANAC 400": "R400", "Resolução 400": "R400",
            "Resolução ANAC nº 400": "R400",
            "Código Penal Brasileiro": "CPB",
            "Decreto nº 11.129": "D11129",
            "Constitución Política de Chile": "CONST",
            "Código Penal de la República de Chile": "CPCL",
            "Montreal Convention": "MC99", "Convención de Montreal": "MC99",
            "Convention for the Unification": "MC99",
            "American Convention on Human Rights": "ACHR",
            "Annex 9": "AN9", "Annex 13": "AN13", "Annex 17": "AN17",
            "IATA General Conditions": "IATA_GC",
        }
        # Check explicit mapping first
        for key, code in _map.items():
            if key in framework_name:
                return code
        # Fall back to config value if already set
        # (caller should pass config.get('framework_code') before calling this)
        # Generic: first letters of first 3 capitalised words
        clean = re.sub(r'[^a-zA-Z0-9 ]', '', framework_name)
        parts = [w for w in clean.split() if w]
        if parts:
            return ''.join(w[0].upper() for w in parts[:4])
        return "FWK"

    def build_enhanced_legal_prompt(self, config: Dict, articles: Dict, framework_text: str, skip_brazilian: bool = False) -> str:
        """
        Build enhanced prompt with legal precision and structured analysis.
        Includes canonical JSON output block (ported from v4.py) so downstream
        pipeline stages can always find a machine-readable violations bundle.
        """
        framework_name = config['framework_name']
        jurisdiction = config.get('jurisdiction', 'Unknown')
        framework_type = config.get('framework_type', 'legal_framework')
        # Resolve canonical framework code (prefer explicit config value)
        framework_code = config.get('framework_code') or self._get_framework_code(framework_name)

        # Actor context – read from config when available, fallback to case defaults
        airline_name   = config.get('airline_name',   'LATAM Airlines')
        passenger_name = config.get('passenger_name', 'Passenger')
        norm_airline   = self.normalize_actor_name(airline_name,   'organization')
        norm_passenger = self.normalize_actor_name(passenger_name, 'individual')

        prompt = f"""LEGAL COMPLIANCE ANALYSIS REQUEST

FRAMEWORK: {framework_name}
JURISDICTION: {jurisdiction.upper()}
FRAMEWORK TYPE: {framework_type.replace('_', ' ').title()}
LEGAL STYLE: {config.get('legal_style', 'Unknown').upper()}
FRAMEWORK CODE: {framework_code}

## CRITICAL OUTPUT FORMATTING RULES

⚠️ **VIOLATIONS SECTION - STRICT REQUIREMENTS:**

1. **ONLY include actual violations** - Do NOT include:
   - Metadata headers (Framework:, Jurisdiction:, Analysis Date:, etc.)
   - Negative findings ("NO VIOLATIONS IDENTIFIED", "Not applicable")
   - Recommendations for other frameworks to apply
   - General legal context or background information
   - Transcript evidence descriptions that are not violations
   - Severity assessments as standalone entries
   - Article explanations or definitions

2. **Each violation MUST start with a clear label:**
   - ✅ GOOD: "a) Violation of Right to Information"
   - ✅ GOOD: "VIOLATION CATEGORY A: Improper Denial of Service"
   - ✅ GOOD: "b) Breach of Due Process Requirements"
   - ❌ BAD: "The crew's repeated demands..." (narrative)
   - ❌ BAD: "Primary Rationale:" (metadata)
   - ❌ BAD: "Legal Context:" (background)
   - ❌ BAD: "This represents a failure..." (assessment)

3. **Structure for EACH violation:**
   ```
   a) [VIOLATION NAME - Action-oriented, specific]
   
   Transcript Evidence: "[exact quote]" [timestamp]
   
   Legal Reference: Article X: "[exact article text]"
   
   Analysis: [How the provision was violated, why it matters. SEVERITY MUST BE INTEGRATED HERE, e.g., "This constitutes a HIGH severity violation because..." DO NOT create separate "Severity:" line]
   ```

4. **CANONICAL OUTPUT REQUIRED** – After Section 2, output a JSON code block with this exact structure:
   ```json
   {{
     "schema_version": "2.0",
     "entities": {{
       "violations": [
         {{
           "violation_id": "VIOL_<12-char-sha256>",
           "case_id": "CASE_<timestamp>",
           "jurisdiction": "{jurisdiction.upper()[:10]}",
           "framework_code": "{framework_code}",
           "category": "<violation_category>",
           "violation_type": "<specific_violation_name>",
           "severity": "CRITICAL|HIGH|MEDIUM|LOW",
           "confidence": 0.85,
           "status": "OPEN",
           "actor_ids": ["ACT_{norm_airline}", "ACT_{norm_passenger}"],
           "action_ids": ["ACTN_<hash>"],
           "legal_article_ids": ["{framework_code}_ART<number>"],
           "evidence_ids": ["EVID_<hash>"]
         }}
       ],
       "evidences": [
         {{
           "evidence_id": "EVID_<hash>",
           "case_id": "CASE_<timestamp>",
           "type": "transcript",
           "source": "transcript_audio",
           "excerpt": "<exact_quote>",
           "start_time": "<hh:mm:ss>",
           "end_time": "<hh:mm:ss>"
         }}
       ],
       "actors": [
         {{
           "actor_id": "ACT_{norm_airline}",
           "name": "{airline_name}",
           "actor_type": "organization",
           "role": "operating_carrier"
         }},
         {{
           "actor_id": "ACT_{norm_passenger}",
           "name": "{passenger_name}",
           "actor_type": "individual",
           "role": "ticketed_passenger"
         }}
       ],
       "articles": [
         {{
           "article_id": "{framework_code}_ART<number>",
           "framework_code": "{framework_code}",
           "article_code": "<article_number>",
           "jurisdiction": "{jurisdiction.upper()[:10]}",
           "reference": "<full_reference_string>"
         }}
       ],
       "actions": [
         {{
           "action_id": "ACTN_<hash>",
           "description": "<observable_action>",
           "sequence_index": 1,
           "actor_id": "ACT_{norm_airline}"
         }}
       ]
     }}
   }}
   ```
   **ID rules:** `VIOL_` = SHA256(case_id|framework_code|article_ids|violation_type)[:12]; `EVID_` = SHA256(case_id|source|start|end|excerpt)[:8]; `ACTN_` = SHA256(violation_id|description)[:8].  
   **Severity MUST be one of:** `CRITICAL`, `HIGH`, `MEDIUM`, `LOW` (map `MODERATE`→`MEDIUM`).  
   If no violations exist, output the block with an empty `violations` array.

5. **Forbidden patterns - DO NOT generate:**
   - Lines starting with: "Analyst:", "Framework:", "Note:", "Important:", "Context:", "Rationale:"
   - **STANDALONE SEVERITY LINES:** "Severity: HIGH -", "Severity: CRITICAL -", "Severity: MODERATE -", "Severity: LOW -"
   - Quoted article definitions: "Article 26 (general_provision):" followed by explanatory text
   - Recommendations: "The Montreal Convention should be applied...", "Use ICAO Annex 9 instead..."
   - Timestamp evidence as violations: [2.87-3.52] transcript excerpts
   - Negative statements: "Does not constitute...", "Not applicable...", "Framework does not apply..."
   - Introduction preambles: "Based on the analysis of the provided transcript, the following violations..."

### A. VIOLATION IDENTIFICATION GUIDELINES

**What constitutes a violation:**
- A specific action that breaches a specific legal provision
- Must have: (1) Observable conduct (2) Violated article (3) Legal harm

**What is NOT a violation:**
- Framework applicability assessments
- Recommendations to use different frameworks
- Legal background or context
- Article definitions or explanations
- Procedural notes or jurisdictional clarifications

### B. SPECIFIC LEGAL PROVISIONS FOR REFERENCE:

{self._format_articles_for_prompt(articles)}

### C. JURISDICTIONAL CONSIDERATIONS:
- Apply {jurisdiction} legal interpretation principles
- Consider hierarchy of norms in {jurisdiction}
- Account for {config.get('legal_style', 'mixed')} legal drafting style

### D. REQUIRED ANALYSIS STRUCTURE:

#### **SECTION 1: VIOLATIONS IDENTIFIED** (If any)

**a) [Violation Name - e.g., Improper Denial of Carriage Without Justification]**

Transcript Evidence: "[Exact quote showing the violating behavior]" [timestamp]

Legal Reference: Article X: "[Exact article text that was violated]"

Analysis: [Explain HOW this specific conduct violates this specific provision. Reference the juridical value and legal intent of the provision. INCLUDE SEVERITY ASSESSMENT HERE - integrate "This constitutes a [CRITICAL/HIGH/MEDIUM/LOW] severity violation because [brief justification based on impact and legal hierarchy]" within this analysis paragraph, NOT as a separate line.]

---

**b) [Second Violation Name]**

Transcript Evidence: "[Exact quote]" [timestamp]

Legal Reference: Article Y: "[Exact article text]"

Analysis: [Explain violation with severity integrated: "This represents a [CRITICAL/HIGH/MEDIUM/LOW] violation as [justification]..." DO NOT create separate "Severity:" lines.]

---

[Continue for each discrete violation - aim for 3-8 violations maximum, only when genuinely applicable]

⚠️ **CRITICAL**: Do NOT create standalone lines starting with "Severity:" - integrate severity assessment WITHIN the Analysis paragraph.

#### **SECTION 2: OVERALL ASSESSMENT** (Separate from violations)

**Systemic Patterns:**
[Analysis of whether violations indicate systematic compliance failure vs. isolated incidents]

**Legal Consequences:**
[Potential remedies, penalties, or legal actions available under this framework]

**Recommendations:**
[Specific corrective actions - these go here, NOT in the violations section]

#### **SECTION 3: CANONICAL BUNDLE** (machine-readable – required)

Output the JSON block exactly as specified in Rule 4 above.
Start with: ```json  — end with: ```  — no prose around it.

### E. LEGAL PRECISION REQUIREMENTS:
- Always quote EXACT article text, not just article numbers
- Consider the hierarchy of legal norms
- Reference specific legal principles (good faith, proportionality, due process)
- Distinguish between procedural and substantive violations
- Consider cumulative impact of multiple violations

### F. QUALITY CONTROL CHECKLIST

Before finalizing your analysis, verify:
- [ ] Every violation has a clear category label (a, b, c...)
- [ ] No metadata headers in violations section
- [ ] No "NO VIOLATIONS" entries as violation items
- [ ] No article explanations masquerading as violations
- [ ] No framework recommendations in violations section
- [ ] Each violation is a discrete, actionable breach
- [ ] Severity uses CRITICAL/HIGH/MEDIUM/LOW only (MODERATE → MEDIUM)
- [ ] Canonical JSON block is present after Section 2 (empty array if no violations)
- [ ] All severity values in the JSON block use CRITICAL/HIGH/MEDIUM/LOW

## FINAL OUTPUT MUST:
1. Be in Portuguese for Brazilian frameworks, English for international
2. Use precise legal terminology appropriate to jurisdiction
3. Clearly separate violations from commentary/recommendations
4. Only include actual violations - if none exist, state clearly in Section 2
5. Reference specific remedies available under the framework
6. End with the canonical JSON block (Rule 4 schema) — always required
"""

        # If this framework is Brazilian and we haven't already added Brazilian sections, add them now
        if not skip_brazilian and config.get('jurisdiction', '').lower() in ('brazil', 'brasil'):
            try:
                return self.build_optimal_brazilian_prompt(config, articles, framework_text)
            except Exception:
                # Fall back to the generic prompt on error
                return prompt

        return prompt

    def build_optimal_brazilian_prompt(self, config: Dict, articles: Dict, framework_text: str) -> str:
        """
        Build an optimized Portuguese prompt tailored for Brazilian legal practice (CDC).
        Adds strict Brazilian citation format, prescriptive recommendation structure, and severity rules.
        UPDATED: Enhanced with strict formatting to prevent metadata pollution
        """
        # Use skip_brazilian=True to avoid infinite recursion
        base_prompt = self.build_enhanced_legal_prompt(config, articles, framework_text, skip_brazilian=True)

        brazilian_sections = """

### F. FORMATAÇÃO DE CITAÇÕES LEGAIS BRASILEIRAS:
- **Leis**: use formato completo, ex: "Lei nº 8.078/1990" (não "Lei 8.078/90").
- **Artigos**: usar: "Art. 6º, III, do CDC" (não "Artigo 6, item 3").
- **Resoluções**: mencionar com número e ano, ex: "Resolução ANAC nº 400/2016".
- **Jurisprudência**: citar súmulas por número, ex: "Súmula 297 do STJ".

### G. REGRAS CRÍTICAS PARA ANÁLISE BRASILEIRA:

⚠️ **PROIBIDO na seção de violações:**
- NÃO incluir: "Sobre a aplicabilidade", "Experiência do passageiro", "Documentação imediata"
- NÃO incluir: "Auditar", "Assegurar que", "Investigar", "Treinamento" (são recomendações, não violações)
- NÃO incluir: "Declaração Final de Conformidade" ou conclusões gerais
- NÃO incluir: citações diretas do transcript sem análise legal
- NÃO incluir: avaliações de gravidade como violações separadas ("ALTA. A conduta da tripulação...")
- **NÃO criar linhas separadas começando com "Severidade:" ou "Gravidade:" - integrar na análise**
- NÃO incluir: "Based on the analysis...", "The following violations...", "Identified violations:" (preâmbulos)

✅ **OBRIGATÓRIO para cada violação:**
- Começar com: "a) Violação de [direito específico]" ou "CATEGORIA A: [nome da violação]"
- Citar artigo CDC completo: "Art. 6º, III, da Lei nº 8.078/1990"
- Explicar COMO a conduta viola o artigo (não apenas descrever a conduta)
- **Integrar gravidade NA ANÁLISE:** "Esta conduta representa violação de ALTA gravidade pois..."
- NÃO criar linha separada "Gravidade: ALTA - [explicação]"

### H. ESTRUTURA DE RECOMENDAÇÕES PRÁTICAS (SEÇÃO SEPARADA):
Para cada violação de gravidade **CRÍTICA** ou **ALTA**, incluir NA SEÇÃO DE RECOMENDAÇÕES:

1) Via Administrativa
   - Órgão competente (ex: PROCON, ANAC)
   - Prazo sugerido (ex: 90 dias, ou prazo específico regulatório)
   - Documentos necessários (lista objetiva)
   - Resultado esperado (multa, reembolso, aplicação de medida)

2) Via Judicial
   - Ação cabível (ex: Ação de Indenização por Danos Materiais e Morais)
   - Prazo prescricional aplicável (ex: 3 anos — Art. 27 do CDC)
   - Foro/Competência (ex: Juizado Especial Cível)
   - Remédio processual sugerido (ex: tutela antecipada para reembolso)

3) Recomendações para a Empresa
   - Medida corretiva imediata
   - Checklist documental
   - Modelo de notificação extrajudicial

### I. TABELA DE JUSTIFICAÇÃO DE GRAVIDADE (EXEMPLO):
| Violação | Gravidade | Justificativa | Consequência Potencial |
|----------|-----------|---------------|------------------------|
| a) Direito à Informação | ALTA | Falta de informação clara (Art. 6º, III) | Indenização e obrigação de informação |
| b) Direito à Segurança | CRÍTICA | Ato que coloca consumidor em risco (Art. 6º, I) | Indenização e multas administrativas |

### J. CONTROLE DE QUALIDADE ESPECÍFICO BRASIL:

Antes de finalizar, verificar:
- [ ] Violações usam nomenclatura CDC correta (Art. X, inciso Y)
- [ ] Nenhuma recomendação está listada como violação
- [ ] Gravidade reflete hierarquia do CDC (direitos básicos = prioridade)
- [ ] Cada violação tem remédio específico mencionado na seção de recomendações
- [ ] Nenhum "Sobre...", "Auditar...", "Assegurar..." na seção de violações
- [ ] Conclusões e resumos estão na Seção 2, não misturadas com violações
- [ ] Bloco JSON canônico (Seção 3 / Regra 4) presente após a Seção 2 (array vazio se sem violações)
- [ ] Valores de severidade no JSON: CRITICAL/HIGH/MEDIUM/LOW apenas (MODERADA → MEDIUM)

"""

        final = base_prompt + brazilian_sections
        return final

    def avaliar_gravidade_detalhada(self, artigo_violado: str, impacto: str) -> Dict[str, Any]:
        """
        Brazilian-specific severity assessment returning criteria, consequences, recommendation and prazo.
        """
        matriz_gravidade = {
            "CRÍTICA": {
                "criterio": "Violação de direito fundamental com dano material ou risco à integridade",
                "consequencia": "Responsabilidade objetiva + danos morais + sanção administrativa",
                "recomendacao": "Ação judicial imediata com pedido de tutela antecipada",
                "prazo": "Urgente (30 dias para medida cautelar)"
            },
            "ALTA": {
                "criterio": "Descumprimento substantivo de obrigações essenciais",
                "consequencia": "Indenização + revisão contratual + sanção administrativa",
                "recomendacao": "Notificação extrajudicial seguida de reclamação no PROCON",
                "prazo": "90 dias para solução amigável"
            },
            "MODERADA": {
                "criterio": "Falha procedimental que afeta direitos, sem dano material imediato",
                "consequencia": "Correção administrativa + possível indenização",
                "recomendacao": "Correção contratual e compensação ao consumidor",
                "prazo": "60-90 dias"
            },
            "BAIXA": {
                "criterio": "Não conformidade menor, principalmente formal",
                "consequencia": "Advertência e medidas corretivas internas",
                "recomendacao": "Ajuste de processo interno e treinamento",
                "prazo": "30-60 dias"
            }
        }

        # Heuristic: choose severity based on keywords in artigo_violado and impacto
        content = (artigo_violado or "") + " " + (impacto or "")
        content_lower = content.lower()
        if any(k in content_lower for k in ["perigo", "risco", "segurança", "ameaç"]):
            return matriz_gravidade["CRÍTICA"]
        if any(k in content_lower for k in ["grave", "substancial", "indeniz"]):
            return matriz_gravidade["ALTA"]
        if any(k in content_lower for k in ["procediment", "formal", "incompleto"]):
            return matriz_gravidade["MODERADA"]
        return matriz_gravidade["BAIXA"]
    
    def convert_user_articles(self, user_articles: List[Dict]) -> Dict:
        """
        Convert a user-supplied article list (the CBA.json / MC99.json format produced by the
        law-DB pipeline) into the internal ``extracted_sections`` dict expected by
        ``build_enhanced_legal_prompt`` / ``_format_articles_for_prompt``.

        Accepted input fields per article object:
            article_number  (str)   – e.g. "142"
            text            (str)   – raw article text
            reference       (str)   – e.g. "CBA Title III, Ch. II, Art. 142 – …"
            eli_id          (str)   – e.g. "BR.CBA.T3.C2.Art.142"
            theme           (str)   – e.g. "Aviation Safety"
            framework_code  (str)
            framework_name  (str)
            jurisdiction    (str)
        """
        converted = []
        for art in user_articles:
            article_number = str(art.get("article_number") or art.get("number") or "?")
            text = art.get("text") or art.get("content") or ""

            # Derive type from text keywords
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
                    "interpretation_weight": "high"
                },
                # Preserve user-supplied metadata for richer formatting
                "eli_id": art.get("eli_id", ""),
                "theme": art.get("theme", ""),
                "reference": art.get("reference", ""),
                "_user_defined": True          # sentinel: show regardless of hierarchy
            })

        return {
            "numbered_articles": converted,
            "definitions": [],
            "obligations": [],
            "prohibitions": []
        }

    def _format_articles_for_prompt(self, articles: Dict) -> str:
        """
        Format extracted articles for the prompt with legal significance.
        Handles both the internal extraction format AND the user-supplied CBA/MC99 JSON format.
        """
        formatted = []

        for article in articles.get("numbered_articles", []):
            # ── resolve field names (internal vs user-supplied) ──────────────────
            num         = article.get("number") or article.get("article_number", "?")
            content     = (article.get("content") or article.get("text") or "").strip()
            article_type = article.get("type", "general_provision")
            jv          = article.get("juridical_value") or {}
            hierarchy   = jv.get("hierarchy", "mandatory")
            interp_w    = jv.get("interpretation_weight", "high")
            user_defined = article.get("_user_defined", False)

            # For auto-extracted articles only keep high-value ones to limit prompt size.
            # User-defined articles are always included in full.
            if not user_defined and hierarchy not in ("constitutional", "principled", "mandatory"):
                continue

            # Build a rich header line
            reference = article.get("reference", "")
            eli_id    = article.get("eli_id", "")
            theme     = article.get("theme", "")

            if reference:
                header = f"**{reference}**"
            elif eli_id:
                header = f"**Article {num}** [{eli_id}]"
            else:
                header = f"**Article {num}**"

            detail_parts = [article_type]
            if theme:
                detail_parts.append(theme)
            detail_parts.append(hierarchy.upper())
            header += f" ({' | '.join(detail_parts)}):"

            formatted.append(header)
            formatted.append(f"  \"{content}\"")
            formatted.append(f"  [Interpretation weight: {interp_w.upper()}]")
            formatted.append("")

        # Add key definitions
        if articles.get("definitions"):
            formatted.append("### KEY DEFINITIONS:")
            for i, definition in enumerate(articles["definitions"][:3]):
                formatted.append(f"{i+1}. {definition}")
            formatted.append("")

        # Add core obligations
        if articles.get("obligations"):
            formatted.append("### CORE OBLIGATIONS:")
            for i, obligation in enumerate(articles["obligations"][:3]):
                formatted.append(f"{i+1}. {obligation[:150]}...")
            formatted.append("")

        # Add key prohibitions
        if articles.get("prohibitions"):
            formatted.append("### KEY PROHIBITIONS:")
            for i, prohibition in enumerate(articles["prohibitions"][:3]):
                formatted.append(f"{i+1}. {prohibition[:150]}...")
            formatted.append("")

        return '\n'.join(formatted)
    
    def _escape_template_string(self, text: str) -> str:
        """
        Safely escape text for use in JavaScript template literals (backtick strings).
        """
        # First escape backslashes
        text = text.replace('\\', '\\\\')
        # Then escape backticks
        text = text.replace('`', '\\`')
        # Handle ${...} syntax which has special meaning in template literals
        text = text.replace('${', '\\${')
        return text

    def generate_integrated_js_analyzer(self, config: Dict, prompt: str, output_path: Optional[str] = None) -> str:
        """
        Generate JS analyzer with integrated capabilities.
        Writes to `output_path` if provided and RETURNS the JS content as a string.
        """
        framework_name = config.get('framework_name', 'Legal Framework')
        # Create a clean CamelCase function name
        clean_name = re.sub(r'[^a-zA-Z0-9\s]', '', framework_name)
        camel_case_name = ''.join(word.capitalize() for word in clean_name.split())
        js_function_name = config.get('js_function_name', f"inject{camel_case_name}Analyzer")
        js_function_name = re.sub(r'[^a-zA-Z0-9_]', '', js_function_name)
        if not js_function_name[0].isalpha():
            js_function_name = 'inject' + js_function_name

        # Safely escape the prompt for use in template literal
        escaped_prompt = self._escape_template_string(prompt)

        js_template = f"""/**
 * INTEGRATED LEGAL FRAMEWORK ANALYZER
 * Framework: {framework_name}
 * Jurisdiction: {config.get('jurisdiction', 'Unknown')}
 * Legal Style: {config.get('legal_style', 'Unknown')}
 * Generated: {datetime.now().isoformat()}
 * Version: Integrated 2.0
 */

function {js_function_name}(options) {{
    const {{ 
        targetContainerId, 
        getTranscriptText, 
        onAnalyze,
        analysisMode = 'standard',
        language = 'auto'
    }} = options;

    const LEGAL_CONFIG = {json.dumps(config, ensure_ascii=False, indent=2)};

    const ANALYSIS_TEMPLATE = `{escaped_prompt}`;

    const SYSTEM_PROMPT = `You are a specialized legal analyst for {framework_name}. 

CRITICAL FORMATTING RULES - VIOLATIONS SECTION:

1. **WHAT TO INCLUDE**: Only actual, discrete violations with:
   - Clear violation label: a), b), c) OR "VIOLATION CATEGORY A:"
   - Transcript evidence with timestamps
   - Exact article reference and quote
   - Analysis explaining HOW the provision was violated
   - Severity INTEGRATED within analysis paragraph

2. **STRICTLY FORBIDDEN - DO NOT GENERATE**:
   ❌ Metadata headers: "Framework:", "Jurisdiction:", "Analysis Date:", "Applicable Incident:"
   ❌ Section headers: "LEGAL COMPLIANCE ANALYSIS", "VIOLATIONS", "LEGAL CONTEXT", "NEGATIVE FINDINGS"
   ❌ Standalone severity lines: "Severity: HIGH -", "Severity: CRITICAL -"
   ❌ Introduction preambles: "Based on the analysis...", "The following violations..."
   ❌ Negative findings as violations: "No Violation -", "Not applicable", "Lack of Evidence"
   ❌ Applicability assessments as violations: "Applicability (Article 1):", "Jurisdiction (Article 3):"
   ❌ Article explanations: "Article X defines...", "The Convention applies to..."
   ❌ Recommendations as violations: "Should apply Montreal Convention instead..."

3. **REQUIRED STRUCTURE** - Each violation MUST be:
   a) [Violation Name]
   
   Transcript Evidence: "[exact quote]" [timestamp]
   
   Legal Reference: Article X: "[exact article text]"
   
   Analysis: [Explain violation. Include: "This constitutes a [SEVERITY] violation because..." WITHIN this paragraph. NO separate Severity: line]

4. **LEGAL PRECISION**:
   - Quote EXACT article text, not just numbers
   - Apply {config.get('jurisdiction', 'appropriate')} legal interpretation principles
   - Distinguish procedural vs substantive violations
   - Consider hierarchy of legal norms

5. **OUTPUT**: 
   - Language: ${{language === 'auto' ? 'Portuguese for Brazilian frameworks, English otherwise' : language}}
   - Only list ACTUAL violations (target: 3-8 maximum)
   - If NO violations exist, state clearly in conclusion, do NOT create violation entries`;

    // Create integrated analysis panel
    const createLegalPanel = () => {{
        const panel = document.createElement('div');
        panel.className = 'integrated-legal-panel';
        panel.innerHTML = `
            <div class="panel-header legal-header">
                <h3><span class="legal-icon">⚖️</span> {framework_name} Analysis</h3>
                <div class="legal-metadata">
                    <span class="badge jurisdiction">{config.get('jurisdiction', 'Unknown')}</span>
                    <span class="badge type">{config.get('framework_type', 'legal').replace('_', ' ')}</span>
                    <span class="badge style">{config.get('legal_style', 'Unknown')}</span>
                </div>
            </div>
            <div class="panel-body">
                <div class="legal-config-section">
                    <h4>Legal Framework Configuration</h4>
                    <pre class="legal-config">${{JSON.stringify(LEGAL_CONFIG, null, 2)}}</pre>
                </div>
                <div class="analysis-instructions">
                    <h4>Legal Analysis Template</h4>
                    <textarea class="legal-prompt" rows="15">${{ANALYSIS_TEMPLATE}}</textarea>
                </div>
                <div class="analysis-controls">
                    <div class="control-group">
                        <label>Analysis Mode:</label>
                        <select class="mode-select">
                            <option value="standard">Standard Legal Analysis</option>
                            <option value="detailed">Detailed with Jurisprudence</option>
                            <option value="remedial">Focus on Remedies</option>
                        </select>
                    </div>
                    <div class="control-group">
                        <label>Output Language:</label>
                        <select class="language-select">
                            <option value="auto">Auto (Framework-based)</option>
                            <option value="pt">Português</option>
                            <option value="en">English</option>
                            <option value="es">Español</option>
                        </select>
                    </div>
                    <button class="execute-legal-analysis">
                        <span class="icon">⚖️</span> Execute Legal Analysis
                    </button>
                </div>
            </div>
        `;

        // Enhanced event handling
        panel.querySelector('.execute-legal-analysis').addEventListener('click', () => {{
            const userPrompt = panel.querySelector('.legal-prompt').value;
            const analysisMode = panel.querySelector('.mode-select').value;
            const outputLanguage = panel.querySelector('.language-select').value;
            const transcriptText = getTranscriptText();

            const legalAnalysisPackage = {{
                system_prompt: SYSTEM_PROMPT,
                user_prompt: userPrompt,
                transcript: transcriptText,
                framework: '{framework_name}',
                framework_metadata: LEGAL_CONFIG,
                analysis_mode: analysisMode,
                output_language: outputLanguage,
                legal_parameters: {{
                    jurisdiction: '{config.get('jurisdiction', 'Unknown')}',
                    framework_type: '{config.get('framework_type', 'legal')}',
                    legal_style: '{config.get('legal_style', 'Unknown')}',
                    requires_exact_citations: true,
                    requires_severity_assessment: true,
                    requires_systemic_assessment: true
                }},
                timestamp: new Date().toISOString(),
                version: 'integrated_2.0'
            }};

            if (typeof onAnalyze === 'function') {{
                onAnalyze(legalAnalysisPackage);
            }}
        }});

        return panel;
    }};

    // Injection logic
    const container = document.getElementById(targetContainerId);
    if (!container) {{
        console.error(`[Integrated Legal Analyzer] Container #${{targetContainerId}} not found`);
        return;
    }}

    const panel = createLegalPanel();
    container.appendChild(panel);
    
    console.log(`[Integrated Legal] {framework_name} analyzer injected successfully`);
    console.log(`  Jurisdiction: {config.get('jurisdiction', 'Unknown')}`);
    console.log(`  Legal Style: {config.get('legal_style', 'Unknown')}`);
    console.log(`  Framework Type: {config.get('framework_type', 'legal')}`);
}}

// Module export
if (typeof module !== 'undefined' && module.exports) {{
    module.exports = {js_function_name};
}}
"""

        # Write to file if requested
        if output_path:
            try:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(js_template)
                print(f"Successfully generated integrated JS file: {output_path}")
            except Exception as e:
                raise

        return js_template

def main():
    """
    Main function for the integrated parser
    """
    parser = argparse.ArgumentParser(description='Integrated Legal Framework Parser')
    parser.add_argument('--input', '-i', required=True, help='Input framework document (PDF or text)')
    parser.add_argument('--config', '-c', required=True, help='JSON configuration file')
    parser.add_argument('--output', '-o', help='Output JS file path')
    parser.add_argument('--validate', '-v', action='store_true', help='Validate extracted legal content')
    
    args = parser.parse_args()
    
    # Initialize integrated parser
    legal_parser = IntegratedLegalFrameworkParser()
    
    # Read input document
    print(f"📚 Reading framework document: {args.input}")
    if args.input.lower().endswith('.pdf'):
        with open(args.input, 'rb') as f:
            pdf_reader = PyPDF2.PdfReader(f)
            framework_text = ""
            for i, page in enumerate(pdf_reader.pages):
                page_text = page.extract_text()
                if page_text:
                    framework_text += page_text + "\n"
                print(f"  Processed page {i+1}")
    else:
        with open(args.input, 'r', encoding='utf-8') as f:
            framework_text = f.read()
    
    print(f"✓ Document loaded: {len(framework_text)} characters")
    
    # Load and enhance configuration
    print(f"⚙️ Loading and enhancing configuration: {args.config}")
    config = legal_parser.load_and_enhance_config(args.config, framework_text)
    
    print(f"✓ Framework identified: {config['framework_name']}")
    print(f"✓ Jurisdiction: {config.get('jurisdiction', 'Unknown')}")
    print(f"✓ Legal Style: {config.get('legal_style', 'Unknown')}")
    
    # Extract legal articles with enhanced precision
    print("📖 Extracting legal articles with enhanced precision...")
    articles = legal_parser.extract_legal_articles_with_context(framework_text)
    
    print(f"✓ Extracted: {len(articles.get('numbered_articles', []))} articles")
    print(f"✓ Found: {len(articles.get('definitions', []))} definitions")
    print(f"✓ Identified: {len(articles.get('obligations', []))} obligations")
    print(f"✓ Identified: {len(articles.get('prohibitions', []))} prohibitions")
    
    # Build enhanced legal prompt
    print("🔨 Building enhanced legal analysis prompt...")
    prompt = legal_parser.build_enhanced_legal_prompt(config, articles, framework_text)
    
    # Generate JS analyzer
    output_path = args.output or f"./integrated_{config['framework_name'].replace(' ', '_')}_analyzer.js"
    print(f"💾 Generating integrated JS analyzer: {output_path}")
    
    js_content = legal_parser.generate_integrated_js_analyzer(config, prompt, output_path)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(js_content)
    
    print("✅ INTEGRATED LEGAL PARSER COMPLETE")
    print(f"   Output: {output_path}")
    print(f"   Framework: {config['framework_name']}")
    print(f"   Prompt Length: {len(prompt)} characters")
    print(f"   JS Analyzer: {len(js_content)} characters")
    
    if args.validate:
        print("\n🔍 VALIDATION SUMMARY:")
        high_value_articles = [a for a in articles.get('numbered_articles', []) 
                              if a['juridical_value']['hierarchy'] in ['constitutional', 'principled']]
        print(f"   High-value articles: {len(high_value_articles)}")
        print(f"   Directly enforceable provisions: {len([a for a in articles.get('numbered_articles', []) 
                                                         if a['juridical_value']['enforceability'] == 'direct_enforceable'])}")
        print(f"   Rights provisions: {len([a for a in articles.get('numbered_articles', []) 
                                           if a['type'] == 'rights_provision'])}")

if __name__ == '__main__':
    main()