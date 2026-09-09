# Golden Case — Contract & Specification Guide
**Ontology:** Legal Intelligence Ontology v2.4  
**Pipeline:** awareness-pipeline-v2.4  
**Status:** AUTHORITATIVE — this case is the reference implementation for every pipeline output  
**Last Updated:** 2026-03-03  

---

## Purpose

This case is the **canonical contract** for any case that enters the pipeline. It defines:

1. **What nodes are required** and what properties each must carry  
2. **What relationships are mandatory** vs optional  
3. **Which invariants must pass** before a case output is valid  
4. **Naming rules** that must be followed exactly  

Any pipeline output that deviates from this contract is **non-compliant** with Ontology v2.4.

---

## Directory Structure

```
template_golden_case/
├── GOLDEN_CASE_SPEC.md                        ← this document (the contract)
├── chain_analysis.json                        ← which frameworks to run and in what order/mode
├── 00_metadata/
│   ├── mc99_framework.json                    ← framework config with CORRECT ELI IDs for MC99
│   └── cba_framework.json                     ← framework config with CORRECT ELI IDs for CBA
├── 01_input_sources/
│   └── transcripts/
│       └── aeropuerto_template.json           ← input transcript with node_ids, timestamps, role-based speakers
├── 02_framework_analyses/
│   └── by_jurisdiction/
│       └── international/
│           └── aeropuerto_template_mc99_analysis.json  ← raw LLM analysis output
├── 03_violations_database/
│   └── evidence_library/                      ← evidence artefacts
├── 04_synthesized_outputs/
│   └── golden_case_canonical_output.json      ← THE COMPLETE v2.3 COMPLIANT OUTPUT (primary artefact)
├── 05_visualizations/
├── 06_processing_logs/
│   ├── ai_prompts_used/
│   └── chaining_decisions/
└── 07_context/
```

---

## The 14 Node Types — Quick Reference

| Node Type          | node_id Pattern        | Mandatory Properties                                           | Key Rules |
|--------------------|------------------------|----------------------------------------------------------------|-----------|
| `Case`             | `CASE_[a-z0-9]{8}`    | node_id, title, created_date, jurisdiction                     | Prohibited: direct links to Action, Evidence, LegalArticle |
| `Violation`        | `VIOL_[a-z0-9]{8}`    | node_id, category, description, timestamp                      | Is an **allegation**, not a conclusion. Must have ≥1 Action and ≥1 Article |
| `Action`           | `ACTN_[a-z0-9]{8}`    | node_id, action_type, description, timestamp                   | **Invariant IX-1**: must have ≥1 incoming SUPPORTS_ACTION from Evidence |
| `ActorRole`        | `ROLE_[a-z0-9]{8}`    | node_id, function                                              | **ZERO personal identity**. function from controlled vocabulary only |
| `Evidence`         | `EVID_[a-z0-9]{8}`    | node_id, evidence_type, source, timestamp                      | Must NOT have outgoing link to Violation |
| `Segment`          | `SEG_[a-z0-9]{8}`     | node_id, text, position, evidence_node_id                      | text = VERBATIM. speaker = functional role. Terminal node (no outgoing links). `evidence_node_id` renamed from `source_reference` in v2.4 |
| `LegalFramework`   | `{jurisdiction}.{code}` | node_id, name, jurisdiction                                  | Only node type with non-8id format |
| `LegalArticle`     | Full ELI ID            | node_id, article_number, article_reference, article_text, framework_code, jurisdiction | article_text VERBATIM. ELI must match law JSON. `framework_code` renamed from `framework` in v2.4 |
| `SourcePack`       | `PACK_[a-z0-9]{8}`    | node_id, created_at, integrity_hash                            | integrity_hash = SHA-256 of full pack. Renamed from `hash` in v2.4 |
| `SourceFile`       | `FILE_[a-z0-9]{8}`    | node_id, path, sha256, file_type                               | path = relative within pack |
| `MediaAsset`       | `MEDIA_[a-z0-9]{8}`   | node_id, created_at, media_type                                | created_at = original recording timestamp |
| `Transcript`       | `TRNS_[a-z0-9]{8}`    | node_id, created_at, language                                  | **v2.4 breaking change**: `created_at` and `language` are now mandatory |
| `ApplicabilityBasis` | `APPL_[a-z0-9]{8}`  | node_id, basis_type                                            | Required whenever Case.jurisdiction ≠ any cited LegalFramework.jurisdiction |
| `LLMRun`           | `RUN_[a-z0-9]{8}`     | node_id, framework, timestamp, model, prompt_version           | Exactly ONE per Case. **v2.4 breaking change**: `prompt_version` is now mandatory (Invariant IX-3) |

---

## ELI ID Formats

The ELI ID is the `node_id` of every `LegalArticle`. It must exactly match the law JSON source.

```
{JURISDICTION}.{FRAMEWORK}.{TITLE?}.{CHAPTER?}.Art.{NUMBER}

MC99 (no Titles):    INT.MC99.C{n}.Art.{number}
CBA  (Title+Chapter): BR.CBA.T{n}.C{n}.Art.{number}
```

| Framework | Article | Correct ELI                  | Wrong ELI (do not use)         |
|-----------|---------|------------------------------|--------------------------------|
| MC99      | 17      | `INT.MC99.C3.Art.17`         | `INT.MC99.T1.C1.Art.17` ✗      |
| MC99      | 19      | `INT.MC99.C3.Art.19`         | `INT.MC99.T1.C1.Art.19` ✗      |
| MC99      | 21      | `INT.MC99.C3.Art.21`         | `INT.MC99.T1.C1.Art.21` ✗      |
| CBA       | 175     | `BR.CBA.T6.C1.Art.175`       | `BR.CBA.T3.C2.Art.175` ✗       |
| CBA       | 260     | `BR.CBA.T8.C3.Art.260`       | `BR.CBA.T3.C2.Art.260` ✗       |

---

## Mandatory Relationships (All Cases)

```
LLMRun     ──[GENERATED_CASE]──►   Case
Case       ──[HAS_PROVENANCE]──►   SourcePack
Case       ──[SCOPES_VIOLATION]──► Violation (1 or more)             ← renamed from CONTAINS_VIOLATION in v2.4
Violation  ──[GROUNDED_IN_ACTION]──► Action  (1 or more, Invariant II-2)  ← renamed from BASED_ON_ACTION in v2.4
Violation  ──[INVOLVES_ACTOR]──►   ActorRole  (0 or more)            ← new in v2.4
Violation  ──[VIOLATES_ARTICLE]──► LegalArticle  (1 or more, Invariant II-2)
Evidence   ──[SUPPORTS_ACTION]──►  Action  (1 or more per Action, Invariant IX-1)
Evidence   ──[CONTAINS_SEGMENT]──► Segment  (1 or more)
Evidence   ──[GENERATED_FROM]──►   Transcript  ──[TRANSCRIBES]──►  MediaAsset
LegalFramework  ──[CONTAINS_ARTICLE]──►  LegalArticle
SourcePack ──[CONTAINS_FILE]──►    SourceFile
SourceFile ──[REPRESENTS_MEDIA]──► MediaAsset
```

**Cross-jurisdictional only:**
```
Case  ──[HAS_APPLICABILITY_BASIS]──►  ApplicabilityBasis
  (required when Case.jurisdiction ≠ any referenced LegalFramework.jurisdiction)
```

---

## Prohibited Relationships (Schema Corruption)

| Prohibited                          | Reason |
|-------------------------------------|--------|
| `Evidence → Violation`              | Evidence grounds; never concludes (Invariant I-3) |
| `Segment → Violation`               | Segments are purely factual |
| `Segment → LegalArticle`            | Same |
| `Action → LegalArticle`             | Facts cannot directly invoke law |
| `ActorRole → ActorRole`             | No role-to-role links |
| `Case → Evidence`                   | Case scopes only via Violations |
| `Case → Action`                     | Same |

---

## ActorRole Controlled Vocabulary

Allowed values for `ActorRole.function`:

```
service_provider | regulator | operator | crew | controller 
passenger | witness | police_officer | airline_staff 
security_personnel | ground_handler
```

**Hard rules:**
- NEVER put a person's name in any property of any node
- `context` field may describe the role in general terms but must contain zero personal identifiers
- Any string that could identify a natural person is a violation of Invariant III-2

---

## Precision Rule for VIOLATES_ARTICLE

> Only cite articles that have a **direct, specific factual nexus** to an observed Action.

| Do this ✓                                              | Avoid this ✗                                              |
|--------------------------------------------------------|-----------------------------------------------------------|
| 1 Violation → 1–3 highly relevant articles             | 1 Violation → 9 articles from a bulk scan                 |
| Article cited because a specific segment grounds it    | Article cited because it's "generally relevant"           |
| article_text confirms the specific obligation breached | Article loaded but no factual path from the transcript    |

See §12.5 Data Quality Issue #2 in the ontology spec.

---

## Cross-Jurisdictional Cases

When `Case.jurisdiction` (e.g. `BR`) differs from any `LegalFramework.jurisdiction` (e.g. `INT` for MC99):

1. Create an `ApplicabilityBasis` node with an appropriate `basis_type`
2. Link: `Case ──[HAS_APPLICABILITY_BASIS]──► ApplicabilityBasis`

Common `basis_type` values:
- `international_air_carriage` — passenger holds an international ticket
- `brazilian_operator` — carrier is incorporated or operating under Brazilian law
- `passenger_nationality` — passenger's nationality triggers treaty application
- `territorial_operation` — incident occurred in a specific territory

---

## Severity and Confidence Values

| Field      | Type  | Allowed Values              | Constraint |
|------------|-------|-----------------------------|------------|
| severity   | string | `low`, `medium`, `high`    | **Lowercase only** — `HIGH` or `High` are invalid |
| confidence | float | `0.0` – `1.0`              | IEEE 754 double precision |

---

## Timestamps

All timestamps: **ISO 8601 UTC with milliseconds**: `YYYY-MM-DDThh:mm:ss.sssZ`

| Field                | What it represents |
|----------------------|--------------------|
| `LLMRun.timestamp`   | When the pipeline ran |
| `Case.created_date`  | When the analysis was created |
| `MediaAsset.created_at` | Original recording creation time (from file metadata, not analysis date) |
| `Evidence.timestamp` | When the evidence was recorded/captured |
| `Violation.timestamp` | When the violation was recorded by the system |
| `Action.timestamp`   | When the observable action occurred in reality |

---

## Invariant Summary — All Must Pass

| ID     | Name                        | Check |
|--------|-----------------------------|-------|
| I-1    | No Conclusions              | No guilt, liability, judgment in any property |
| I-2    | No Interpretive Collapse    | No prohibited relationships (§4.2) |
| I-3    | Evidence Never Decides      | Evidence has zero outgoing links to Violation |
| II-1   | Violation Traceability      | Full path: Violation→Action→Evidence→…→SourcePack |
| II-2   | No Orphan Violations        | Every Violation has ≥1 Action and ≥1 Article |
| II-3   | Evidence Must Have Content  | ≥1 Segment OR derived from MediaAsset OR generated from Transcript |
| II-4   | No Orphan Articles          | Every Article linked to exactly one LegalFramework |
| II-5   | Case Provenance Path        | Case → HAS_PROVENANCE → SourcePack |
| III-1  | Role Purity                 | No personal identity in ActorRole |
| III-2  | Identity Exclusion          | No personal data anywhere |
| IV-1   | Law Not Flow Downward       | No LegalArticle → Action |
| IV-2   | Facts Not Flow Upward       | No Segment/Action → LegalArticle |
| V-1    | No Cyclic Legal Reasoning   | VIOLATES_ARTICLE graph is acyclic |
| V-2    | Controlled Action Recursion | No GROUNDED_IN_ACTION self-loops; depth ≤5 |
| V-3    | No Leakage Between Cases    | Core nodes (Violation/Action/Evidence/Segment/ActorRole) belong to exactly one Case |
| VI-1   | Semantic Minimalism         | Only defined node types; no ad hoc fields beyond `_spec` annotations |
| VII-1  | Framework Consistency       | LegalArticle.framework = suffix of containing LegalFramework.node_id |
| VII-2  | Jurisdiction Consistency    | LegalArticle.jurisdiction = LegalFramework.jurisdiction |
| VIII-1 | Provenance Integrity        | Case → HAS_PROVENANCE → SourcePack (exactly one) |
| VIII-2 | Evidence Forensics          | Evidence → Transcript → MediaAsset path exists for type='transcript' |
| VIII-3 | Applicability Requirement   | Cross-jurisdiction always has ApplicabilityBasis |
| VIII-4 | Agent Traceability          | LLMRun → GENERATED_CASE → Case (exactly one) |
| IX-1   | Evidence-Backed Actions     | Every Action has ≥1 incoming SUPPORTS_ACTION from Evidence |
| IX-2   | Confidence Bounds           | Every Violation.confidence is in range [0.0, 1.0] |
| IX-3   | Prompt Auditability         | Every LLMRun has a non-empty `prompt_version` string |

---

## Primary Artefact

```
04_synthesized_outputs/golden_case_canonical_output.json
```

This file contains a fully populated example of every node type, every mandatory relationship, and every invariant satisfied — with `_spec` annotations on each node and relationship explaining exactly which rule it demonstrates.

**To use as a template for a new case:**
1. Replace all `node_id` values with new UUIDs following the `[a-z0-9]{8}` patterns
2. Replace `article_text` with verbatim text from the relevant law JSON in `data/law/`
3. Replace transcript `text` values with verbatim excerpts from the source recording
4. Adjust `Case.jurisdiction` and add `ApplicabilityBasis` as needed for cross-jurisdiction cases
5. Run the pipeline validation (§10.3 of ontology spec) before marking the case as complete
