# COMPREHENSIVE ANALYSIS PROMPT: Argus

## PROJECT OVERVIEW
**Path**: `/Users/leandrodisconzi/Documents/sa_server/Argus`
**Purpose**: Legal framework analyzer generator - creates AI-powered framework analysis tools from legal documents

---

## ANALYSIS OBJECTIVES

### 1. ARCHITECTURAL MAPPING

#### Core Application
**app-framework-builder.py**
```
CRITICAL ANALYSIS:
- Flask application structure (5 routes only after cleanup)
- Route inventory:
  1. / → dashboard.html rendering
  2. /view → frameworks.html template viewer
  3. /api/extract_pdf_text → PDF text extraction
  4. /api/generate_config_from_text → AI config generation
  5. /api/build_framework → JS analyzer generation
  
- Request/response formats for each endpoint
- Error handling patterns
- File upload handling (32 MB limit)
- Temporary file management
- CORS configuration

DEEP DIVE INTO /api/build_framework:
- Input validation (framework_text, config_json, output_filename)
- IntegratedLegalFrameworkParser initialization
- Workflow steps:
  1. Parse config JSON
  2. Add output_language to config
  3. Detect framework characteristics
  4. Extract legal articles with context
  5. Build enhanced prompt
  6. Generate integrated JS analyzer
  7. Return: generated_js, generated_prompt, filename
```

#### Framework Generator Engine
**ingestors/integrated_legal_framework_parser.py**
```
CRITICAL ANALYSIS (981 lines):

CLASS: IntegratedLegalFrameworkParser

METHODS TO ANALYZE IN DETAIL:

1. detect_framework_characteristics(framework_text)
   - What patterns does it detect?
   - How are jurisdiction, type, entity inferred?
   - Regex patterns for Brazilian resolutions
   - Country detection logic

2. extract_legal_articles_with_context(framework_text)
   - Article numbering patterns (Article 1, Art. 1, Artigo 1º)
   - Section/chapter detection
   - Context window size around each article
   - How malformed documents are handled
   - Return structure: {article_id: {content, metadata}}

3. build_enhanced_legal_prompt(config, extracted_sections, framework_text)
   - LINES 450-513: Violation template construction
   - LINES 579-592: Brazilian Portuguese enhancements
   - How ANALYSIS_TEMPLATE is assembled
   - Forbidden patterns list (lines 450-459)
   - Severity integration instructions
   - Evidence citation requirements
   - Output format specifications

4. generate_integrated_js_analyzer(config, full_prompt, output_path)
   - LINES 765-805: SYSTEM_PROMPT generation (CRITICAL!)
   - How LEGAL_CONFIG object is constructed
   - Template variable substitution
   - UI strings for different languages (en, es, pt, it, hi)
   - createLegalPanel() function generation
   - File writing and validation

CRITICAL SECTIONS:

Lines 450-459: Forbidden Patterns
```python
FORBIDDEN_PATTERNS = [
    "**STANDALONE SEVERITY LINES:** 'Severity: HIGH -', 'Severity: CRITICAL -'",
    "Introduction preambles: 'Based on the analysis of the provided transcript...'",
    "Metadata headers: 'Framework:', 'Jurisdiction:', 'Analysis Date:'",
    "Section headers: 'LEGAL COMPLIANCE ANALYSIS', 'VIOLATIONS'",
    # ... analyze complete list
]
```

Lines 488-513: Violation Template Structure
```python
VIOLATION_TEMPLATE = """
a) {Violation Title}

Transcript Evidence: "{exact quote}" [timestamp]

Legal Reference: {Article number and exact text}

Analysis: [...SEVERITY MUST BE INTEGRATED HERE: "This constitutes a {HIGH} severity violation because..."]
"""
# Analyze how this template prevents metadata pollution
```

Lines 765-805: SYSTEM_PROMPT Generation (THE FIX!)
```python
SYSTEM_PROMPT = f'''You are a specialized legal analyst...

CRITICAL FORMATTING RULES - VIOLATIONS SECTION:

2. **STRICTLY FORBIDDEN - DO NOT GENERATE**:
   ❌ Metadata headers: "Framework:", "Jurisdiction:", "Analysis Date:", "Applicable Incident:"
   ❌ Section headers: "LEGAL COMPLIANCE ANALYSIS", "VIOLATIONS", "LEGAL CONTEXT"
   ❌ Standalone severity lines: "Severity: HIGH -", "Severity: CRITICAL -"
   ❌ Introduction preambles: "Based on the analysis...", "The following violations..."
   ❌ Negative findings as violations: "No Violation -", "Not applicable"
   ❌ Applicability assessments: "Applicability (Article 1):", "Jurisdiction (Article 3):"

3. **REQUIRED STRUCTURE** - Each violation MUST be:
   [Letter label: a), b), c)] [Descriptive Title]
   
   Transcript Evidence: "[exact quote]" [timestamp]
   
   Legal Reference: [Article X: "exact article text"]
   
   Analysis: [Explain how evidence violates the article. Include: "This constitutes a [SEVERITY] severity violation because..." WITHIN this paragraph. NO separate Severity: line]
'''
# Analyze how this fixes the two-prompt conflict
```

QUESTIONS TO ANSWER:
1. Why does SYSTEM_PROMPT override ANALYSIS_TEMPLATE?
2. How does the NEW SYSTEM_PROMPT (40 lines) differ from OLD (25 lines)?
3. What was the root cause of metadata pollution?
4. How do forbidden patterns enforce clean output?
5. How is severity integration enforced?
```

---

### 2. TEMPLATE & UI SYSTEM

#### Framework Builder UI
**templates/frameworks/frameworks.html**
```
ANALYZE (1026 lines):

STRUCTURE:
- HTML layout and CSS styling
- JavaScript module structure
- Event handlers for file upload, config generation, analyzer generation
- Real-time reasoning display during AI config generation
- Code syntax highlighting (Prism.js)
- Package download (JSZip, FileSaver.js)

KEY FUNCTIONS:

1. uploadFrameworkFile(file)
   - File validation (.txt, .pdf)
   - PDF text extraction via /api/extract_pdf_text
   - Display extracted text in textarea

2. generateConfig()
   - Reads framework text
   - Calls /api/generate_config_from_text (streaming SSE)
   - Parses deepseek-reasoner response
   - Extracts JSON config from AI output
   - Displays in config textarea

3. generateJSAnalyzer()
   - Validates inputs: framework text, config JSON, output filename
   - Selects output language (4. Output Language dropdown)
   - NO parser version selection (removed)
   - Calls /api/build_framework
   - Receives: generated_js, generated_prompt
   - Displays generated code
   - Enables download buttons

4. downloadPackage()
   - Creates ZIP with:
     * {Framework}Analyzer.js
     * config.json
     * generated_prompt.txt
     * original framework document
   - Naming: {FrameworkName}Analyzer_package.zip

REMOVED FEATURES (after cleanup):
- Parser version selector (always uses integrated parser)
- api-logger.js (static file removed)
- session_recorder.js (static file removed)

UI STATES:
1. Initial: Upload prompt
2. Framework loaded: Generate config enabled
3. Config generated: Generate analyzer enabled
4. Analyzer generated: Download enabled
```

#### Dashboard
**templates/dashboard.html**
```
ANALYZE:
- Minimal landing page (60 lines)
- Single button: "Launch Framework Builder" → /view?path=frameworks/frameworks.html
- Feature list display
- Gradient styling
```

---

### 3. FRAMEWORK GENERATION WORKFLOW

#### Complete Generation Pipeline
```
TRACE END-TO-END:

STEP 1: Document Upload
User uploads: Tokyo_Convention_1963.pdf or .txt
↓
app-framework-builder.py: /api/extract_pdf_text
↓
pdfminer.six or PyPDF2 extracts text
↓
Returns: {text: "...", filename: "Tokyo_Convention_1963.pdf"}
↓
frameworks.html displays text in textarea

STEP 2: AI Config Generation
User clicks "Generate Config with AI"
↓
frameworks.html: generateConfig()
↓
POST /api/generate_config_from_text
{framework_text: "...", model: "deepseek-reasoner", stream: true}
↓
app-framework-builder.py streams to deepseek-stream-proxy (pinocchio-multi:8019)
↓
SSE stream returns reasoning + JSON config
↓
frameworks.html parses and displays config:
{
  "framework_name": "Convention on Offences and Certain Other Acts...",
  "framework_type": "International Treaty",
  "responsible_entity": "International Civil Aviation Organization (ICAO)",
  "analysis_focus": {
    "Aircraft Commander Authority": "Article 6.*commander.*reasonable grounds",
    "Unlawful Acts": "Article 1.*offence.*penal law",
    ...
  },
  "js_function_name": "injectTokyoConventionPanel"
}

STEP 3: JS Analyzer Generation
User clicks "Generate JS Analyzer"
↓
frameworks.html: generateJSAnalyzer()
↓
POST /api/build_framework
{
  framework_text: "...",
  config_json: "{...}",
  output_filename: "TokyoConventionAnalyzer.js",
  output_language: "en"
}
↓
app-framework-builder.py: build_framework_analyzer()
↓
IntegratedLegalFrameworkParser:
  1. detect_framework_characteristics() → jurisdiction, type
  2. extract_legal_articles_with_context() → article sections
  3. build_enhanced_legal_prompt() → ANALYSIS_TEMPLATE (200+ lines)
  4. generate_integrated_js_analyzer() → SYSTEM_PROMPT (40 lines) + JS code
↓
Returns:
{
  generated_js: "const LEGAL_CONFIG = {...}; const ANALYSIS_TEMPLATE = `...`; const SYSTEM_PROMPT = `...`; function createLegalPanel() {...}",
  generated_prompt: "Full 200+ line prompt",
  filename: "TokyoConventionAnalyzer.js"
}
↓
frameworks.html displays generated code with syntax highlighting

STEP 4: Package Download
User clicks "Download Complete Package"
↓
frameworks.html: downloadPackage()
↓
Creates ZIP:
  TokyoConventionAnalyzer_package/
    TokyoConventionAnalyzer.js
    config.json
    generated_prompt.txt
    Tokyo_Convention_1963.txt
↓
FileSaver.js triggers download
```

---

### 4. DEPLOYMENT INTEGRATION

#### How Generated Frameworks Reach pinocchio-multi
```
ANALYZE THE DEPLOYMENT WORKFLOW:

1. MANUAL DEPLOYMENT (current):
   - User downloads {Framework}Analyzer_package.zip from Argus
   - User extracts package
   - User copies {Framework}Analyzer/ folder to:
     pinocchio-multi/static/js/legal_frameworks/{Framework}Analyzer/
   - User runs watch_frameworks.py to update framework_list.json
   
2. FILES DEPLOYED:
   {Framework}Analyzer/
     {Framework}Analyzer.js ← Core analyzer with SYSTEM_PROMPT fix
     config.json ← Framework metadata
     generated_prompt.txt ← Full AI prompt for reference
     {Framework_Document}.txt/md ← Original legal document

3. FRAMEWORK ACTIVATION:
   pinocchio-multi/scripts/watch_frameworks.py detects new folder
   ↓
   Reads config.json
   ↓
   Enriches with jurisdiction/flag using JurisdictionEnricher
   ↓
   Updates framework_list.json:
   {
     "tokyoconvention": {
       "name": "Convention on Offences...",
       "path": "/static/js/legal_frameworks/TokyoConventionAnalyzer",
       "config": {...},
       "primary_jurisdiction": "International",
       "flag": "🇺🇳"
     }
   }
   ↓
   pinocchio-multi UI shows new framework in checkbox list

4. QUESTIONS:
   - Is there automated deployment? (CI/CD, GitHub Actions)
   - How are framework updates managed?
   - Is versioning tracked?
   - What if deployment fails mid-copy?
```

---

### 5. LANGUAGE & LOCALIZATION

#### Multi-Language Support
```
ANALYZE:

SUPPORTED LANGUAGES:
- English (en)
- Spanish (es)
- Portuguese (pt)
- Italian (it)
- Hindi (hi)

UI STRINGS in app-framework-builder.py (lines 869-924):
{
  'en': {
    'analyze_button': 'Analyze',
    'reset_button': 'Reset',
    'placeholder': 'Paste your text here...',
    'results_heading': 'Analysis Results',
    'copy_button': 'Copy Results',
    'no_violations': 'No issues found.',
    'violations_found': 'Potential issues found:',
    'see_details': 'See details',
    'violation_text': 'The text may violate',
    'references': 'References',
    'download_report': 'Download Report'
  },
  'pt': {...},
  'es': {...},
  'it': {...},
  'hi': {...}
}

HOW LANGUAGE IS APPLIED:
1. User selects language in frameworks.html: "4. Output Language" dropdown
2. Sent to /api/build_framework as output_language: "pt"
3. config['output_language'] = "pt"
4. config['ui_strings'] = ui_strings['pt']
5. generate_integrated_js_analyzer() embeds Portuguese UI strings in JS
6. Generated analyzer displays Portuguese labels

QUESTIONS:
- Are ANALYSIS_TEMPLATE and SYSTEM_PROMPT also localized?
- Or only UI strings?
- How are Brazilian vs European Portuguese handled?
- Can users add new languages?
```

---

### 6. QUALITY ASSURANCE

#### The SYSTEM_PROMPT Fix
```
CRITICAL ANALYSIS OF THE FIX:

PROBLEM (Old System):
- ANALYSIS_TEMPLATE said: "DO NOT create separate Severity: line"
- SYSTEM_PROMPT said: "Assign severity: CRITICAL/HIGH/MODERATE/LOW"
- AI followed SYSTEM_PROMPT's simpler instruction → metadata pollution

ROOT CAUSE:
Two-prompt conflict where SYSTEM_PROMPT overrides ANALYSIS_TEMPLATE

SOLUTION (lines 765-805):
NEW SYSTEM_PROMPT explicitly forbids all bad patterns:
```python
STRICTLY FORBIDDEN - DO NOT GENERATE:
❌ Metadata headers: "Framework:", "Jurisdiction:", "Analysis Date:", "Applicable Incident:"
❌ Section headers: "LEGAL COMPLIANCE ANALYSIS", "VIOLATIONS", "LEGAL CONTEXT"
❌ Standalone severity lines: "Severity: HIGH -", "Severity: CRITICAL -"
❌ Introduction preambles: "Based on the analysis...", "The following violations..."
❌ Negative findings as violations: "No Violation -", "Not applicable"
❌ Applicability assessments: "Applicability (Article 1):", "Jurisdiction (Article 3):"

REQUIRED STRUCTURE - Each violation MUST be:
Analysis: [...Include: "This constitutes a [SEVERITY] severity violation because..." WITHIN paragraph. NO separate Severity: line]
```

RESULTS:
- Violations dropped from 15 → 12 → 10 → 4
- Metadata pollution eliminated (100% quality)
- All 4 remaining violations are actual legal violations
- Clean format with integrated severity

VALIDATION:
Package: case_aeropuerto_STG_5_analysis_package_1767309028770
- NO "Framework:" headers ✅
- NO "Severity: HIGH -" standalone lines ✅
- NO "LEGAL COMPLIANCE ANALYSIS" sections ✅
- NO "Applicability (Article 1):" entries ✅
- Severity integrated in analysis text ✅
```

---

### 7. CRITICAL QUESTIONS TO ANSWER

1. **Parser Evolution**
   - What was "Standard Parser" before it was removed?
   - Why keep only "Integrated Parser"?
   - What makes integrated parser "enhanced"?

2. **Config AI Generation**
   - How reliable is deepseek-reasoner for config extraction?
   - What if it returns malformed JSON?
   - Can users manually edit config after generation?

3. **Framework Validation**
   - Are generated analyzers tested before deployment?
   - What if regex patterns in analysis_focus fail to match?
   - How are errors caught in production?

4. **Scalability**
   - Can Argus generate frameworks in batch?
   - How long does generation take for large documents (1000+ pages)?
   - Memory constraints for PDF extraction?

5. **Maintenance**
   - How are existing frameworks updated?
   - What if legal document changes (new articles added)?
   - Versioning strategy for framework updates?

---

## OUTPUT REQUIREMENTS

Provide a comprehensive document covering:

1. **Code Architecture**: Class diagram of IntegratedLegalFrameworkParser
2. **Generation Workflow**: Step-by-step with code snippets
3. **Prompt Engineering**: ANALYSIS_TEMPLATE vs SYSTEM_PROMPT comparison
4. **Template System**: Violation template anatomy
5. **Language Support**: Complete UI strings for all languages
6. **Deployment Process**: Manual + proposed automated workflow
7. **Quality Metrics**: Before/after fix comparison
8. **Integration Points**: How Argus connects to pinocchio-multi
9. **File Inventory**: Every file explained with purpose
10. **Future Enhancements**: Gaps and improvement opportunities

---

## ANALYSIS DEPTH

- Read EVERY line of integrated_legal_framework_parser.py
- Understand EVERY prompt engineering decision
- Map EVERY data flow from upload to download
- Document EVERY API endpoint contract
- Test EVERY generation step with sample data
- Validate EVERY quality improvement claim

This analysis will reveal the complete framework generation system and quality control mechanisms.
