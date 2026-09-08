# Next Ingestion Set — Review & Pipeline Update Strategy

**Set:** `discovery/_files_which_will_be_used_in_pipeline/`
**Date of review:** 2026-09-08
**Predecessor:** `documents_scanned/sessions/f889c1cd-3efb-4f2f-b39a-1a5d708f041d/PIPELINE_REVIEW_I-002.md` (root-cause findings & P0/P1/P2 proposal)
**Classification of contents:** Attorney Work Product — Privileged and Confidential

---

## 1. Purpose

This corpus is the **next input batch for the full pipeline**. It is materially more complex than the I-002 session already reviewed: it adds a **second case** (I-001 / Brazil-Guarulhos), a **new data class** (a curated per-code `violations/` legal dossier library for both cases), and it **re-presents the I-002 transcripts**. This document reviews the set against the baseline defined in the I-002 review and proposes the update strategy the pipeline needs before (and while) ingesting it.

---

## 1b. Decisions (confirmed 2026-09-08)

| # | Question | Decision | Consequence for the strategy |
|---|---|---|---|
| 1 | Intent of `violations/` | **Both** — reference to ground resolution **and** expected outputs to validate against | Dossiers are indexed as the law registry (S4) **and** used as ground truth in the evaluation harness (S5) |
| 2 | Canonical id for I-001 | `C-2026-07-13-001` is **not** canonical — **`I-001` (folder) wins** | Ingest maps/overrides any `case_id` → `I-001`; folder identity is authoritative |
| 3 | 42 confidence==0 dossiers | **Excluded** from "established" legal basis | Only confidence>0 (Tier A, 32 dossiers) can anchor *established* citations; the rest are candidate/unverified only |
| 4 | I-001 transcripts (0% reviewed) | **Both** — consume now at reviewed-weighted confidence **and** flag for refinement | Ingest immediately with a "raw ASR, needs review" flag; do not block on refinement |
| 5 | `IN` vs `INT` | **Yes** — normalize `IN` → `INT` | Normalize jurisdiction labels at ingest; filename prefix is treated as authoritative where they disagree |
| 6 | Duplicated I-002 copy + `.bak` | **No dedupe needed** — I-002 copy is 100% identical, provided only for context | Do not treat as new data; still exclude `.bak` from groups/stats/comprehension |

---

## 2. Inventory of the set

| Area | Contents | Count | Role in the pipeline |
|---|---|---|---|
| `transcripts/I-002/` | The 27 I-002 stage narratives already reviewed (+ 1 `.bak`) | 27 (+1) | Case evidence (SCL, Chile, 2024-07-05/06) |
| `transcripts/I-001/` | 2 new consolidated GRU narratives (lost-phone report + passenger dispute / LATAM counter) | 2 | **New case** — earlier in time (GRU, Brazil, 2024-04-04), same passenger & airline |
| `violations/` | Per-code legal dossiers `BR-*` (21 files), `CL-*` (42), `INT-*` (19) | 82 | **Legal reference / law-registry layer** (schema v4.0) |

### 2a. `transcripts/I-001` readiness (new case)

| File | case_id field | recording_dt | lang | segs | reviewed | VC | FC | KEF |
|---|---|---|---|---|---|---|---|---|
| `I-001_0_..._Lost_Phone_Report.json` | `C-2026-07-13-001` | 2024-04-04T23:00 | pt | 214 | **0%** | 0 | 3 | 9 |
| `I-001_01_..._Ofensive_Agressive_Behaviour.json` | `C-2026-07-13-001` | **2026-07-12T23:00** | pt | 155 | **0%** | 0 | 4 | 6 |

Notes:
- Folder name is `I-001`, but the `case_id` field is `C-2026-07-13-001`; narrative ids are `NAR-GRU-01/02`. **Inconsistent case identity.**
- Segment text is **unreviewed ASR** (`reviewed: false` everywhere, `[Silence/Artifact]` segments) → lower curation than I-002.
- Mixed timestamp semantics: real incident is 2024-04-04 (per BR dossiers, ~02:05 BRT); one file also carries a **2026-07-12 processing-looking datetime**.
- `violations_cited` is empty in both; but the BR dossiers (BR-001 "Staff Misconduct — LATAM employee at GRU", etc.) reference this case, so codes live only in the dossier layer.

### 2b. I-002 transcripts

Same 27 files analyzed in the prior review (dates 2024-07-05/06, `case_id: I-002`, mostly `es`, ~92–100% reviewed, 10 files already cite codes in `violations_cited`, e.g. 17 in the jetbridge standoff). A handful are tiny fragments (3–25 segs) with no clusters/findings. Includes the `.bak`.

### 2c. `violations/` dossier library (82 files)

Schema v4.0 dossier per code. Each contains: `violation_id`, `title`, `incident`/`incident_id`, `jurisdiction`, `category`, `severity`, `confidence{value,components}`, `allegation_summary`, `evidentiary_strength`, `legal_theory`, `required_elements_status`, **`legal_basis[]` (article_id + article_name + status + applicability + verbatim_text)**, `candidate_articles[]`, `element_grids{}` (keyed by full article ids like `BR.CDC.T4.C2.Art.14`, `BR.R400.C2.S2.Art.22`, `CL.CACH.Art.133`, `CL.L16752.T1.Art.1`), `authorities`, `transcripts`, `evidence_links`, `event_ids`, `related_violations`, `validation_pack`, `framework_cache(s)`, `classification`.

Mapping observed:
- **CL-* → I-002** (CACH, L16752, DGAC, CPCL theories), **BR-* → I-001** (CDC, CF88, ANAC Res. 400 theories), **INT-* → I-002** (ICAO Annex 9, Chicago Convention).
- 70 dossiers → I-002, 9 → I-001, **2 span both** (`I-002|I-001`), 1 uses an inline incident object (GRU-GYN secondary incident).

**Trust tiers (quantified):**

| Tier | Definition | BR | CL | INT | Total |
|---|---|---|---|---|---|
| **A** | confidence>0 + verbatim `legal_basis` + clean | 4 | **28** | 0 | 32 |
| **B** | verbatim basis but confidence==0 | 10 | 1 | 13 | 24 |
| **C** | seed/placeholder or bare | 7 | 13 | 6 | 26 |

- **42 of 82 dossiers have `confidence.value == 0`** (BR 17, INT 19, CL 6) — i.e., more than half are unverified by the confidence model.
- 7 are explicit "Created from seed (Lote F)" placeholders; 4 have `has_broken_refs`; 19 lack any verbatim `legal_basis` entry.
- **Naming inconsistency:** 18 files have filename prefix (BR/CL/INT) that does not match the `jurisdiction` field (e.g., INT files labeled `IN`); `BR-021…029` are absent (jumps to `BR-030`).

---

## 3. Key observations

1. **This is no longer a single-case, single-jurisdiction corpus.** It contains two cases (GRU/BR + SCL/CL) plus an international-law layer (INT). The current pipeline model is single-case: one `case` node, one `jurisdiction`, one `case_state` phase, one timeline (`case_graph.json`/`case_state.json`/`events.json`). Feeding both cases into one run will silently mix BR and CL chronologies and phase logic.
2. **The `violations/` dossiers are legal conclusions, not evidence.** They are the kind of artifact the pipeline is supposed to *produce*, and they are keyed by exactly the codes the transcripts cite (`CL-008`, `CL-014`, …). Ingesting them as ordinary documents would (a) trigger the same L1 raw-JSON / LLM-empty / generic-fallback failure documented in the I-002 review, and (b) create circularity (using conclusions as source evidence).
3. **They also constitute the missing law-registry substrate.** The dossier `legal_basis[].verbatim_text` + `element_grids` + `candidate_articles` is precisely what L6 law resolution and the (currently offline) KB need — a local, per-jurisdiction article cache (BR.CDC / BR.R400 / CL.CACH / CL.L16752 / ICAO Annex 9…).
4. **Cases are linked.** I-001 (GRU 2024-04-04) is the earlier São Paulo episode that I-002 narratives reference as "prior LATAM experience". Two dossiers already declare `I-002|I-001`. A per-case-only strategy would lose the cross-case retaliation/pattern narrative.
5. **Uneven ground truth quality.** Only 32/82 dossiers are Tier A; INT is entirely unverified; BR mostly lacks confidence. The dossier library can anchor an evaluation harness, but only with explicit trust tiers.

---

## 4. Risks if ingested naively (with the current pipeline)

| # | Risk | Consequence |
|---|---|---|
| R1 | All three sub-folders fed through the same extract-and-find pipeline | Dossiers shredded by the L1 `.json` raw-text bug; 82 more generic filler "violations"; conclusions treated as evidence (circularity) |
| R2 | Two cases in one run | Mixed BR/CL chronologies; wrong single jurisdiction; broken per-case `case_state` phase |
| R3 | Case identity inconsistency (`I-001` vs `C-2026-07-13-001`) | Dedup/grouping treats them as different; cross-case links lost |
| R4 | Unreviewed ASR in I-001 + tiny fragments | Noise treated as evidence; recognition artifacts pulled into findings |
| R5 | Timestamp semantics mixed (2024-04-04 vs 2026-07-12/13; processing vs recording) | Wrong timeline/events (repeats the run-date bug from the I-002 run) |
| R6 | Dossier trust ignored (conf 0 / seed / broken refs / IN-vs-INT) | "Verified" citations asserted from unverified dossiers |
| R7 | `.bak` + duplicate I-002 copy re-ingested | Inflated counts; `.bak` pollutes content groups/comprehension |

---

## 5. Proposed update strategy

### S1 — Ingestion routing by data class (do this first)
Sniff content type at ingest and route into three lanes:
1. **Evidence lane:** `transcripts/*/*.json` → structured decode → L2–L7 (extraction, graph, narrative, timeline).
2. **Law-registry lane:** `violations/*.json` → indexed into the **law registry / article cache** (never into extraction). Each dossier becomes a registry entry keyed by `(jurisdiction, violation_id/code)` with `legal_basis`, `element_grids`, `candidate_articles`, trust tier.
3. **Excluded lane:** `.bak`, temp, and any file failing schema validation.

This one change prevents both the circularity and the "82 fake violations" failure.

### S2 — Multi-case model
- Partition by resolved case id. Build a **canonical case map** where the **folder identity is authoritative**: `I-001 ↔ GRU` (override the non-canonical `C-2026-07-13-001` field) and `I-002 ↔ SCL`. Any `case_id` field inconsistent with the folder is normalized to the folder id during ingest.
- Produce **per-case** artifacts (`case_graph`, `case_state`, `events`, `timeline`, `narrative`) **and** a cross-case **matter layer**: one passenger, one airline, chronological spine GRU-2024-04-04 → SCL-2024-07-05/06, and a flag where I-002 references I-001.
- `case_state` phases must be evaluated **per case**, not globally.

### S3 — Structured decode + P0 fixes (from the I-002 review) — prerequisites
The four P0/P1 items are still the gating fixes:
- L1 decode of narrative JSONs → clean readable text (`segments[].text` + speaker, `title`, cluster summaries, key findings). This is what makes both I-001 and I-002 actually processable.
- Honest fallback (never persist heuristic filler as "violations"; surface `degraded`).
- Empty-output guards (narrative static fallback, LLM retry, JSON-truncation repair for comprehension).
- Metadata-driven timestamps (`recording_datetime`) and jurisdiction — **now mandatory**, because both BR and CL are present and text heuristics already misfired (BR-for-Chile) in the I-002 run.

### S4 — Use the dossier library as the law registry (no external KB required)
- Build a local registry index: `code → dossier` (e.g., `CL-008`, `CL-014`, `INT-001`…), each with jurisdiction, severity, confidence, and article cache.
- Populate the article cache from `legal_basis[]`: `article_id` (e.g. `CL.CACH.Art.133`) → `article_name`, `verbatim_text`, `status`, `applicability`; enrich from `element_grids` and `candidate_articles` (marking the latter `needs_verbatim` where text is missing).
- L6 resolution then becomes a **local lookup** for every `violations_cited` code in a transcript (10 I-002 files already cite codes) — fixing the "37/38 unresolved, regex-only" failure without Qdrant/Neo4j.
- **Store trust tier per entry** (A/B/C + confidence.components). Per confirmed decision, **only confidence>0 entries are eligible for "established" citations** (Tier A — 32 dossiers today). Tier B/C and any confidence==0 dossier are surfaced strictly as *candidate/unverified* and are never asserted as established legal basis.
- Confidence components (e.g. `CL.CACH.Art.133`, `BR.CDC.T1.Art.1`) become the per-article verification weights used downstream.

### S5 — Dual role: registry enrichment **and** evaluation harness (decision #1 = both)
Because the dossiers are both the grounding reference **and** the expected outputs, the scoring pass is mandatory (not optional). Now that the pipeline can (a) decode transcripts and (b) index dossiers:
- For each transcript-derived violation/finding, map to a dossier by code/case and measure **precision / recall / element coverage** (how many `required_elements_status` / `element_grids` elements are supported by extracted segments).
- **Where the pipeline disagrees with or misses a dossier, treat it as a defect to fix, not noise** — the dossiers encode the ground truth for both case I-001 and case I-002.
- This directly guards against the previous failure mode (27 identical filler violations) — anything not matching a real dossier or grounded segment is flagged.
- Report confidence agreement (extraction confidence vs. dossier `confidence.value`) and per-code match rate.

### S6 — Data-quality gates
- Exclude `.bak` from groups/stats/comprehension (the duplicated I-002 copy needs **no dedupe** — decision #6: it is 100% identical, provided for context only, and is simply not re-counted as new data).
- **Review gate:** weight segments by `reviewed`. **I-001 is consumed now** at reviewed-weighted confidence and **flagged "raw ASR, needs review"** for refinement in parallel (decision #4 = both) — do not block ingestion on refinement.
- **Timestamp discipline:** use `recording_datetime` for evidence/event dating; maintain `processing` vs `recording`; flag the I-001 2026-07-12 anomaly for manual reconciliation.
- **Language from case metadata:** BR → `pt`, CL → `es`, not text-guess on raw JSON.
- **Jurisdiction normalization:** normalize `IN` → `INT` (decision #5) and treat filename prefix (BR/CL/INT) as authoritative where it disagrees with the `jurisdiction` field.
- **Dossier hygiene:** drop/normalize seed placeholders; validate the 4 `has_broken_refs`; confidence==0 dossiers are candidate-only (decision #3) — never "established".

### S7 — Trust & UI surfacing
- Show per-artifact status (ready / degraded / unverified / failed) — never present filler or Tier-C citations under a "Violations" heading.
- Verification (L8) becomes meaningful: verify extracted findings **against the dossier article cache**, and emit an explicit "not verified / KB offline" report when the cache is unavailable.

### S8 — Rollout order
1. S1 routing + S3 L1 decode (unblocks everything).
2. S4 registry index + S2 case-id map (makes the set coherent).
3. S6 quality gates + S7 surfacing.
4. S5 evaluation harness (measure before/after on I-002 transcripts, where the prior run produced pure filler).
5. Re-run on the full set; report against the checklist in §6.

---

## 6. Expected-good baseline for THIS ingestion (definition of done)

When the full set has been ingested correctly, the pipeline should produce, **per case**:
- a non-empty, evidence-grounded `narrative.md` dated 2024-04-04 (I-001/GRU) and 2024-07-05/06 (I-002/SCL) — never processing timestamps;
- distinct, quoted findings that **match real dossiers** (CL-*/BR-*/INT-* codes) with **article-level legal basis** and trust tier — never per-file generic duplicates;
- correct jurisdictions (BR / CL / INT) and languages (pt / es);
- a timeline + event graph whose causal edges follow `prior_stage/next_stage` and the cross-case GRU→SCL spine;
- a **cross-case matter view** linking I-001 → I-002;
- explicit degraded/unverified flags wherever a dossier is Tier B/C or a transcript is unreviewed ASR;
- no `.bak`, no seed placeholders, no IN-vs-INT ambiguity counted as evidence.

---

## 7. Decisions status

All six open questions were **confirmed on 2026-09-08** — see **§1b (Decisions)** at the top of this document. The strategy in §5 is now final and implementable as specified, with the confirmed consequences already applied to S2, S4, S5, and S6.

---

*End of ingestion review & update strategy (final). Ontology v2.4 · Awareness-AI.*
