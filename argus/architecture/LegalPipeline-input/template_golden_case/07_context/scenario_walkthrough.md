# Golden Case — Scenario Walkthrough

**Document purpose:** Plain-language walkthrough of the golden case scenario. Maps every real-world event to its corresponding ontology node, explains why two legal frameworks apply, and describes what the pipeline does at each stage. This document is the "explain it like I'm an agent" guide for anyone producing cases for the LegalPipeline.

---

## The Scenario

On a regular weekday, a passenger is at **Guarulhos International Airport (GRU), São Paulo, Brazil**. Their connecting flight has been delayed — the airline is responsible.

Three things happen in sequence:

### Event 1 — Passenger Complains
The passenger approaches an airline agent at the gate counter and says:
> *"My flight is over two hours late. I need to be rerouted or given assistance."*

This event is captured in **Segment `SEG_seg00001`** (speaker_role: `passenger`).

No legal violation has occurred yet — this is the triggering complaint, not the violation itself.

### Event 2 — Airline Staff Refuses Rerouting
The airline employee responds:
> *"We don't have available seats on other flights. You'll have to wait."*

This event is captured in **Segment `SEG_seg00002`** (speaker_role: `airline_staff`).

This is the legally critical moment. The employee's refusal to reroute or offer alternatives when alternatives exist constitutes:
- **Action `ACTN_deny0001`** — `refusal_to_reroute`
- **Violation `VIOL_mc99v001`** under Montreal Convention Art.19 (carrier's liability for delay)

### Event 3 — No Assistance Offered
The airline agent does not offer meals, accommodation, or any form of care. Instead they say:
> *"You should contact our customer service line."*

This event is captured in **Segment `SEG_seg00003`** (speaker_role: `airline_staff`).

This constitutes a second, distinct legally wrongful act:
- **Action `ACTN_noasst01`** — `failure_to_provide_assistance`
- **Violation `VIOL_cbav0001`** under Brazilian Aviation Code Art.175 §2 (service obligation during delay)

---

## The Evidence

The entire exchange was recorded (with consent). The recording is stored as:

| Node | Type | Description |
|------|------|-------------|
| `MEDIA_aud00001` | MediaAsset | Original audio file, `audio/mp4`, GPS-tagged at GRU Airport |
| `TRNS_trs00001` | Transcript | Portuguese-language transcript of the recording |
| `EVID_trscr001` | Evidence | Formal evidence node that wraps the transcript for pipeline use |

The forensic chain is: `MEDIA_aud00001` → `TRNS_trs00001` → `EVID_trscr001`. Both violations are substantiated by `EVID_trscr001`, which means the same transcript grounds both the MC99 and CBA findings.

---

## Why Two Legal Frameworks Apply

This is a question many agents ask. The answer has three parts:

### 1. The Journey Is International
The passenger's itinerary involves an international leg. Because the flight involves "international carriage" as defined in the **Montreal Convention 1999 (MC99)**, that treaty applies regardless of where the incident occurs. The incident occurs at a Brazilian airport, but the *journey* is international.

This is formalized by the **`APPL_intc0001`** node (`ApplicabilityBasis`, `basis_type: international_air_carriage`). This node is *required* whenever an international treaty is applied to a case with `jurisdiction ≠ INT`. Without it, Invariant VIII-3 fails.

### 2. Brazilian Law Also Applies Independently
Brazil's **Código Brasileiro de Aeronáutica (CBA)** governs airline operations in Brazil. Its obligations regarding passenger care during delays (Art.175) exist independently of the Montreal Convention. A carrier operating in Brazil must comply with BOTH.

This is why you see two `LegalFramework` nodes (`INT.MC99` and `BR.CBA`) and two sets of violations.

### 3. The Two Violations Are Different Facts
Even though both violations arise from the same incident, they are grounded in *different actions*:
- MC99 violation ← `ACTN_deny0001` (the refusal to reroute) ← `SEG_seg00002`
- CBA violation ← `ACTN_noasst01` (the failure to provide assistance) ← `SEG_seg00003`

The actions are conceptually and factually distinct. The pipeline (and any agent producing cases) must not conflate them into a single action node.

---

## How the Pipeline Processes This Case

### Stage 1 — Input Ingestion
The pipeline ingests:
1. `MEDIA_aud00001` → registered in `SourcePack`
2. Transcript extracted, registered as `TRNS_trs00001`
3. Evidence node `EVID_trscr001` created to wrap the transcript
4. Three segments (`SEG_seg00001`, `SEG_seg00002`, `SEG_seg00003`) identified

### Stage 2 — Framework Analysis (LLM Extraction)

The `chain_analysis.json` defines execution order:

**Step A: MC99 analysis (`chaining_mode = "none"`):**
An LLM receives the transcript + MC99 framework config. No prior context (mode=none means independent). The LLM identifies:
- `VIOL_mc99v001` via `ACTN_deny0001` via `SEG_seg00002`
- `INT.MC99.C3.Art.19` as the governing article
- `INT.MC99.C3.Art.21` is loaded but excluded (no personal injury — precision rule applies)
- Output logged to `02_framework_analyses/by_jurisdiction/international/`

**Step B: CBA analysis (`chaining_mode = "all"`):**
An LLM receives the transcript + CBA framework config + ALL MC99 results as context. The chaining context prevents the LLM from re-discovering the rerouting refusal. Instead it finds:
- `VIOL_cbav0001` via `ACTN_noasst01` via `SEG_seg00003`
- `BR.CBA.T6.C1.Art.175` as the governing article
- `BR.CBA.T8.C3.Art.260` is loaded but excluded (no baggage issue — precision rule applies)
- Output logged to `02_framework_analyses/by_jurisdiction/brazil/`

### Stage 3 — Ontology Build
The raw LLM outputs are structured into full ontology files:
- `04_synthesized_outputs/MC99/03_ontology_v2.4.json`
- `04_synthesized_outputs/CBA/03_ontology_v2.4.json`

Each file contains the complete set of nodes and relationships for that framework, plus shared infrastructure nodes (SourcePack, Evidence, etc.).

### Stage 4 — Enrichment
Enriched ontology files are produced:
- `04_synthesized_outputs/MC99/04_enriched_ontology_v2.4.json`
- `04_synthesized_outputs/CBA/04_enriched_ontology_v2.4.json`

Enrichment adds `_enrichment` annotations — additional metadata like GPS coordinates, formal article text, description sanitization notes.

### Stage 5 — Synthesis
Everything is merged into the canonical output:
- `04_synthesized_outputs/golden_case_canonical_output.json`

This is the **single source of truth** for the case. It contains every node from both frameworks (deduplicated), all relationships, plus the `invariant_checklist` validating structural completeness.

---

## Invariant Checklist Explained

The canonical output includes an `invariant_checklist`. Here is what each invariant means for this case:

| Invariant | What it checks | This case |
|-----------|---------------|-----------|
| I-1 | Every Violation has an `evidence_node_id` | EVID_trscr001 on both violations ✅ |
| I-2 | Evidence `integrity_hash` is present | SHA-256 hash on EVID_trscr001 ✅ |
| I-3 | Every node has `integrity_hash` | All 14+ nodes carry this field ✅ |
| II-1 | `SCOPES_VIOLATION` relationship exists | VIOL_mc99v001 → ART19, VIOL_cbav0001 → ART175 ✅ |
| II-2 | `GROUNDED_IN_ACTION` relationship exists | Both violations linked to actions ✅ |
| II-3 | Action grounded in a Segment | Both actions have DERIVED_FROM ✅ |
| III-1 | Transcript has `created_at` and `language` | TRNS_trs00001 has both ✅ |
| IV-1 | LLMRun has `prompt_version` | RUN_llmr0001 carries "legal-extraction-v2.4" ✅ |
| V-1 | Confidence is float 0.0–1.0 | 0.91 and 0.88 ✅ |
| V-2 | Confidence bounds documented | _spec notes explain calibration ✅ |
| VI-1 | Cross-framework violations share Evidence node | Both violations → EVID_trscr001 ✅ |
| VII-1 | Precision rule: non-cited articles documented | ART21 and ART260 both have `_reason_not_cited` ✅ |
| VIII-3 | ApplicabilityBasis for cross-jurisdiction | APPL_intc0001 bridges BR case → INT law ✅ |
| IX-1 | SourcePack references all source files | PACK_src00001 → SRCF_aud00001 + SRCF_trs00001 ✅ |
| IX-2 | Confidence bounds present on all violations | Both violations carry confidence float ✅ |
| IX-3 | LLMRun prompt_version auditable | "legal-extraction-v2.4" resolvable to extraction_prompt.md ✅ |

---

## Key Node Reference Card

| Node ID | Type | Plain Description |
|---------|------|-------------------|
| `CASE_gc2026a1` | Case | The incident case |
| `VIOL_mc99v001` | Violation | MC99 violation — refused rerouting |
| `VIOL_cbav0001` | Violation | CBA violation — no assistance |
| `ACTN_deny0001` | Action | The act of refusing rerouting |
| `ACTN_noasst01` | Action | The act of failing to provide assistance |
| `ROLE_carr0001` | ActorRole | The airline employee at the gate |
| `ROLE_pass0001` | ActorRole | The affected passenger |
| `EVID_trscr001` | Evidence | The transcript as legal evidence |
| `SEG_seg00001` | Segment | Passenger complaint utterance |
| `SEG_seg00002` | Segment | Carrier denial utterance |
| `SEG_seg00003` | Segment | No-assistance / redirect utterance |
| `PACK_src00001` | SourcePack | Collection of all source files |
| `MEDIA_aud00001` | MediaAsset | Original audio recording |
| `TRNS_trs00001` | Transcript | Portuguese transcript |
| `APPL_intc0001` | ApplicabilityBasis | Why MC99 applies to a BR case |
| `RUN_llmr0001` | LLMRun | The LLM run that produced extractions |
| `INT.MC99` | LegalFramework | Montreal Convention 1999 |
| `BR.CBA` | LegalFramework | Código Brasileiro de Aeronáutica |
| `INT.MC99.C3.Art.19` | LegalArticle | Carrier delay liability (violated) |
| `INT.MC99.C3.Art.21` | LegalArticle | Death/injury — loaded, not cited |
| `BR.CBA.T6.C1.Art.175` | LegalArticle | Service obligation (violated) |
| `BR.CBA.T8.C3.Art.260` | LegalArticle | Baggage limits — loaded, not cited |

---

## What an Agent Must Produce to Match This Case

When producing a new case following this golden case template, the agent must:

1. **Identify the transcript segments** that constitute violations — one per action node
2. **Create distinct Action nodes** for each wrongful act (do not merge different acts)
3. **Create distinct Violation nodes** per framework — even if they share the same transcript
4. **Apply the precision rule** — document every article that was loaded but NOT cited
5. **Create an `ApplicabilityBasis` node** if any framework jurisdiction ≠ case jurisdiction
6. **Set `evidence_node_id`** on every Violation (v2.4 requirement — replaces `source_reference`)
7. **Set `created_at` and `language`** on every Transcript node (v2.4 requirement)
8. **Set `prompt_version`** on every LLMRun node (v2.4 requirement)
9. **Use v2.4 relationship names**: `SCOPES_VIOLATION`, `GROUNDED_IN_ACTION`, `INVOLVES_ACTOR`
10. **Include `integrity_hash`** on every node
11. **Verify all invariants** (I-1 through IX-3) before declaring the case complete

---

*This document is part of the `template_golden_case` reference package. For the full machine-readable specification, see `GOLDEN_CASE_SPEC.md` and `04_synthesized_outputs/golden_case_canonical_output.json`.*
