## Golden Analyzer Pack – Generation Instructions

This document provides **detailed specifications and guidelines** for generating a **golden analyzer pack** – the canonical output of the Argus framework generator. A golden analyzer pack is a self‑contained set of files that enables an AI agent (in the Pinocchio‑multi ecosystem) to perform legal analysis under a specific legal framework (e.g., Montreal Convention 1999, Código Brasileiro de Aeronáutica) and produce outputs that fully comply with the **Legal Intelligence Ontology v2.4**.

All generated analyzer packs **must** be consistent across frameworks, produce the same structured output, and be free of the technical debt identified in the current codebase (e.g., version fragmentation, missing canonical JSON, hardcoded prompts). The following instructions are intended for the developer refining the Argus generator.

---

## 1. What is a Golden Analyzer Pack?

A golden analyzer pack consists of:

- **`{Framework}Analyzer.js`** – The core JavaScript analyzer module. It defines the framework’s legal configuration (`LEGAL_CONFIG`), the analysis prompt (`ANALYSIS_TEMPLATE`), and the system prompt (`SYSTEM_PROMPT`). It injects a UI panel and provides the function that sends the analysis request to the LLM.
- **`config.json`** – The framework’s metadata and article list in a structured JSON format (used to build `LEGAL_CONFIG`).
- **`generated_prompt.txt`** – The complete user prompt that was sent to the LLM during analyzer generation (for traceability).
- **Original legal document** (`.txt` or `.pdf`) – The source material from which the framework was derived.

The pack must be **self‑consistent** and **idempotent**: when loaded into the Pinocchio‑multi frontend, it must produce analysis outputs that adhere strictly to the v2.4 ontology and can be parsed into the graph database without additional post‑processing.

---

## 2. Mandatory Consistency Across Frameworks

Every generated analyzer **must**:

1. **Produce the same structured output** – after the human‑readable analysis, a **v2.4‑compliant JSON block** must be included (the “canonical bundle”). This block contains the violations, actions, actor roles, evidence, and segments in a machine‑readable format.
2. **Use the same severity mapping** – internal severity values (`CRITICAL`, `HIGH`, `MODERATE`, `LOW`) must be mapped to the ontology’s lowercase values (`critical`, `high`, `medium`, `low`) in the JSON.
3. **Generate deterministic IDs** – all node IDs (`VIOL_`, `EVID_`, `ACTN_`, `ROLE_`, `SEGM_`) must be generated using SHA‑256 hashes of their deterministic fields, as defined in the ontology §6.1.
4. **Include the same article reference format** – articles must be referenced by their **full ELI ID** (e.g., `INT.MC99.C3.Art.17`) in the JSON. The `LegalArticle` nodes in the graph will later be created from these IDs.
5. **Forbid any PII or personal identifiers** – actor roles must be **functional roles** only (e.g., `service_provider`, `police_officer`), never personal names.
6. **Include the same required sections** – the analysis must contain **Section 1 (Violations)**, **Section 2 (Overall Assessment)**, and **Section 3 (Canonical JSON)**. The JSON must be placed inside a code block marked ````json```` after Section 2.

---

## 3. File Specifications

### 3.1 `{Framework}Analyzer.js`

This file is the output of Argus’s `generate_integrated_js_analyzer` method. It must contain:

- A **header comment** with the framework name, jurisdiction, legal style, generation timestamp, and version (e.g., `Version: Integrated 3.0`).
- A **function** (e.g., `inject<Framework>Analyzer`) that takes an `options` object (`targetContainerId`, `getTranscriptText`, `onAnalyze`, `analysisMode`, `language`). This function:
  - Creates a UI panel with the framework’s configuration and the analysis template.
  - On button click, constructs a `legalAnalysisPackage` containing `system_prompt`, `user_prompt`, `transcript`, `framework_metadata`, etc., and calls `onAnalyze`.
- A **`LEGAL_CONFIG`** object – exactly the content of `config.json` (see below). It must be embedded as a JavaScript object.
- An **`ANALYSIS_TEMPLATE`** – a string containing the full user prompt. **This template must enforce the canonical JSON requirement.** Use the **MC99 analyzer as the reference** – it already includes the golden example and the required JSON block. Copy that structure for all frameworks.
- A **`SYSTEM_PROMPT`** – the system instruction for the LLM. It must **forbid** metadata headers, standalone severity lines, introduction preambles, and any other forbidden patterns (as already done in the MC99 analyzer). It must also explicitly require the canonical JSON output and describe the ID generation rules.
- At the end of the file, a **module export** (`if (typeof module !== 'undefined' && module.exports) { module.exports = ... }`).

**Important:** The `ANALYSIS_TEMPLATE` and `SYSTEM_PROMPT` **must be identical in structure for every framework**, only the framework‑specific details (name, jurisdiction, articles) should vary. Do **not** omit the canonical JSON requirement for any framework (as happened with CBA).

### 3.2 `config.json`

The configuration file must contain a JSON object with the following top‑level keys:

- `framework_name` (string) – full official name.
- `jurisdiction` (string) – e.g., `"BR"`, `"INT"`.
- `framework_code` (string) – short code, e.g., `"CBA"`, `"MC99"`.
- `framework_type` (string) – e.g., `"national_law"`, `"international_treaty"`.
- `legal_style` (string) – `"civil_law"`, `"common_law"`, or `"mixed"`.
- `articles` (array of objects) – each object **must** contain at least:
  - `jurisdiction` (string)
  - `framework_code` (string)
  - `framework_name` (string)
  - `article_number` (string)
  - `hierarchy` (object with `title`, `chapter`, `section`, `paragraph` – may be null)
  - `reference` (string) – human‑readable reference
  - `text` (string) – full article text
  - `theme` (string) – e.g., `"Liability of the Carrier"`
  - `eli_id` (string) – the full ELI‑style identifier, e.g., `"BR.CBA.T5.C1.Art.171"`

The `articles` array is the source for building the “SPECIFIC LEGAL PROVISIONS FOR REFERENCE” section in the prompt. The generator should include **all articles**, but may truncate long texts for brevity (with a note). The `eli_id` will be used directly in the canonical JSON.

### 3.3 `generated_prompt.txt`

This is a plain text file containing the **exact user prompt** that was sent to the AI when generating the analyzer. It should be identical to the `ANALYSIS_TEMPLATE` string in the JS file. It is included for auditability.

### 3.4 Original Legal Document

The source document (`.txt` or `.pdf`) used to generate the configuration. This allows later verification of the extracted articles. The generator should preserve the original filename.

---

## 4. Generator‑Level Improvements (Argus Refinements)

Based on the audit, the following changes must be made to the Argus generator (`app.py` and the parser classes) to ensure all produced analyzers meet the golden standard:

1. **Unify Prompt Templates**  
   - Move the `ANALYSIS_TEMPLATE` and `SYSTEM_PROMPT` into **shared template files** or functions. The MC99 analyzer already contains the correct structure; use it as the reference.
   - For every framework, inject the canonical JSON requirement **exactly as in MC99**. The CBA analyzer must be updated to include the JSON block.

2. **Enforce Severity Mapping**  
   - The prompt must instruct the LLM to map `CRITICAL` → `critical`, `HIGH` → `high`, `MODERATE` → `medium`, `LOW` → `low` in the JSON.
   - The generator should also add a note that severity in the JSON must be **lowercase**.

3. **Standardize ID Generation Rules**  
   - The prompt must explain the deterministic ID generation rules (SHA‑256, truncation). The rules are already well documented in the MC99 prompt – propagate them to all prompts.

4. **Include Golden Examples**  
   - The MC99 prompt includes a golden example (the `aeropuerto_STG_7_segment_8_v24` case). Every framework should have such an example. The generator should either:
     - Include a generic example that demonstrates the structure, or
     - Allow the user to provide a custom example during configuration.

5. **Validate Article `eli_id`**  
   - The `config.json` articles must contain a valid `eli_id`. The generator should validate that the ID follows the pattern `{jurisdiction}.{framework_code}.T{title}.C{chapter}.Art.{number}` (with optional parts) and issue a warning if not.

6. **Remove Dead Code and Dependencies**  
   - The parser classes (`integrated_legal_framework_parser_v*.py`) must be consolidated into a single canonical version (v3 or v4) with all infrastructure concerns (PyPDF2, requests) moved to an infrastructure module. The domain logic must be pure.
   - Remove unused imports (`typer`, `spacy` if not used, `attrs`) and fix the `tempfile.mktemp()` vulnerability.

7. **Add Tests**  
   - The generator should include a test suite that verifies the output of a generated analyzer against a known transcript. This ensures the canonical JSON is produced correctly.

8. **Document the Generation Process**  
   - Update `README.md` and add an `ARCHITECTURE.md` describing the layered architecture and the expected output of analyzers.

---

## 5. Validation Checklist for a Generated Pack

Before releasing a golden analyzer pack, verify:

- [ ] **`config.json`** – contains all mandatory fields; articles have `eli_id`; no personal data.
- [ ] **`{Framework}Analyzer.js`** – `ANALYSIS_TEMPLATE` includes Section 3 (canonical JSON) with a placeholder example.
- [ ] **`{Framework}Analyzer.js`** – `SYSTEM_PROMPT` explicitly forbids metadata and standalone severity, and requires lowercase severity in JSON.
- [ ] **`{Framework}Analyzer.js`** – The function `inject...` correctly passes all options to the analysis package.
- [ ] **`generated_prompt.txt`** – matches the `ANALYSIS_TEMPLATE`.
- [ ] **Original document** – present (optional but recommended).

**Runtime verification** (using Pinocchio‑multi or a test harness):
- [ ] When the analyzer is invoked with a transcript, it produces a textual analysis followed by a valid JSON block.
- [ ] The JSON block contains at least one violation with all required fields (`violation_id`, `type`, `category`, `description`, `timestamp`, `severity`, `confidence`, `framework`, `articles_violated`, `evidence_node_ids`, etc.).
- [ ] Severity values are lowercase (`critical`, `high`, `medium`, `low`).
- [ ] All IDs follow the prescribed format (e.g., `VIOL_` with 8 hex chars).
- [ ] No personal names appear in `actor_role` contexts.

---

## 6. Conclusion

By adhering to these specifications, the Argus generator will produce analyzer packs that are **consistent, audit‑ready, and fully compatible with the v2.4 graph‑based knowledge architecture**. This resolves the current inconsistency between the MC99 and CBA analyzers and ensures that downstream pipelines (like Pinocchio‑multi’s graph builder) receive well‑structured data.

The next step for the developer is to:

1. Consolidate the parser versions into one canonical implementation.
2. Refactor the prompt generation to use a unified template with mandatory JSON output.
3. Update the generation endpoint (`/api/build_framework`) to embed the canonical example.
4. Test the generated analyzers with a real case to confirm correct output.

If any part of these instructions is unclear, refer to the **MC99 analyzer file** as the living golden reference. All new analyzers must mirror its structure exactly.