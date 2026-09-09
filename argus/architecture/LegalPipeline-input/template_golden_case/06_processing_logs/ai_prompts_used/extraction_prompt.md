# Legal Extraction Prompts — Golden Case Reference

**Pipeline Stage:** Stage 2 (LLM Framework Analysis)
**Prompt Version:** `legal-extraction-v2.4`
**Referenced in:** LLMRun node `RUN_llmr0001` in all per-framework outputs

---

## Overview

This file documents the actual prompt templates used during the AI extraction stage for the golden case. There are two templates:

1. **Base Extraction Prompt** — used when `chaining_mode = "none"` (MC99 in this case)
2. **Chaining Extraction Prompt** — used when `chaining_mode = "all"` or `"prior"` (CBA in this case)

The ONTOLOGY DEFINITIONS section is the critical v2.4 update — it was changed in `ai_enrichment_stage.py` line 868 to use v2.4 relationship names.

---

## Template 1: Base Extraction Prompt (MC99 — chaining_mode=none)

```
SYSTEM: You are a legal AI system specialized in aviation law. You extract structured ontology nodes from transcripts. Respond only with valid JSON matching the schema below.

VERSION: legal-extraction-v2.4

---

ONTOLOGY DEFINITIONS (v2.4):

Node types:
- Violation: A legal violation identified in the transcript. Required fields: node_id, node_type="Violation", violation_type, severity, confidence, evidence_node_id, framework_code.
- Action: A concrete action taken by a party that grounds a legal violation. Required fields: node_id, node_type="Action", action_type, actor_role_id, segment_id.
- ActorRole: A party that performs or is affected by an action. Required fields: node_id, node_type="ActorRole", role_type.
- Segment: A specific portion of the transcript. Required fields: node_id, node_type="Segment", content, speaker_role.

Relationships:
- SCOPES_VIOLATION(Violation → LegalArticle): The article that scopes/defines the violation.
  ⚠️ v2.4 CHANGE: was CONTAINS_VIOLATION in v2.3. Now SCOPES_VIOLATION.
- GROUNDED_IN_ACTION(Violation → Action): The action that constitutes the violation.
  ⚠️ v2.4 CHANGE: was BASED_ON_ACTION in v2.3. Now GROUNDED_IN_ACTION.
- INVOLVES_ACTOR(Violation → ActorRole): The actor whose conduct is at issue.
- DERIVED_FROM(Action → Segment): The transcript segment from which the action was extracted.

Mandatory node fields:
- All nodes MUST include: node_id (8-char alphanumeric), node_type, integrity_hash
- Violations MUST include: evidence_node_id (replaces v2.3 source_reference)
- Transcripts MUST include: created_at, language

---

FRAMEWORK: {framework_code}
JURISDICTION: {framework_jurisdiction}
ARTICLES TO ANALYZE: {articles_list}

---

TRANSCRIPT:
```json
{transcript_json}
```

---

TASK: Analyze the transcript under the {framework_code} legal framework. For each legal violation found:

1. Create a Violation node. Set severity based on passenger impact. Set confidence as a float 0.0–1.0.
2. Create one or more Action nodes that constitute the violation. Each Action must be grounded in a specific transcript segment (DERIVED_FROM).
3. Identify the governing legal article (from ARTICLES TO ANALYZE) via SCOPES_VIOLATION.
4. Link the violation to the action via GROUNDED_IN_ACTION.

If an article from ARTICLES TO ANALYZE is loaded but does NOT apply, include it in your output with a note explaining why it was excluded. This is required for transparency (precision rule §12.5).

Respond with a JSON object containing "nodes" and "relationships" arrays.
```

---

## Template 2: Chaining Extraction Prompt (CBA — chaining_mode=all)

```
SYSTEM: You are a legal AI system specialized in aviation law. You extract structured ontology nodes from transcripts. You are running in CHAINING MODE — prior framework analysis results are provided below. Respond only with valid JSON matching the schema below.

VERSION: legal-extraction-v2.4

---

ONTOLOGY DEFINITIONS (v2.4):
[same definitions as Template 1 above — omitted for brevity]

---

FRAMEWORK: {framework_code}
JURISDICTION: {framework_jurisdiction}
ARTICLES TO ANALYZE: {articles_list}

---

PRIOR ANALYSIS CONTEXT (chaining_mode=all):

The following violations and actions were already identified by prior frameworks:
```json
{
  "violations_from_prior": [
    {
      "node_id": "VIOL_mc99v001",
      "framework": "MC99",
      "violation_type": "refusal_to_reroute",
      "action_node_id": "ACTN_deny0001",
      "article": "INT.MC99.C3.Art.19"
    }
  ],
  "actions_from_prior": [
    {
      "node_id": "ACTN_deny0001",
      "action_type": "refusal_to_reroute",
      "segment_id": "SEG_seg00002"
    }
  ]
}
```

⚠️ IMPORTANT: Do NOT re-create nodes that already exist in the prior context. You may reference them using their existing node_id. Focus on identifying ADDITIONAL violations or actions not yet captured.

---

TRANSCRIPT:
```json
{transcript_json}
```

---

TASK: Analyze the transcript under the {framework_code} legal framework WITH AWARENESS of the prior framework analysis above.

1. Identify violations specific to {framework_code} that are NOT already captured.
2. Identify actions that constitute NEW violations (not ACTN_deny0001).
3. If a prior action also constitutes a violation under {framework_code}, you may reference it by node_id rather than re-extracting.
4. Apply the same precision rule — document articles that were loaded but not cited.

Respond with a JSON object containing "nodes" and "relationships" arrays. Reference shared nodes by ID rather than duplicating them.
```

---

## Notes for Pipeline Agents

- The `{articles_list}` is populated from the framework config's `key_articles` field (see `00_metadata/<framework>_framework.json`)
- The `{transcript_json}` is the full transcript from `01_input_sources/transcripts/`
- For `chaining_mode="all"`, ALL prior violations and actions are injected into the prompt context
- For `chaining_mode="prior"`, only the immediately preceding framework's output is injected
- For `chaining_mode="none"`, no prior context is injected (Template 1 above)
- The `integrity_hash` on each node is computed as SHA-256 of `{node_id}:{node_type}:{primary_content_field}` and stored as `integrity_hash` (v2.4 — was `hash` in v2.3)
- The `prompt_version` field on every LLMRun node MUST match this document's version string: `"legal-extraction-v2.4"`
