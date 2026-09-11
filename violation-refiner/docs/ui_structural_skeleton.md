# ViolationRefiner — UI Structural Skeleton

**Status:** specification (ground truth verified against source, 2026-09-11)
**Audience:** engineers/agents building the ViolationRefiner UI
**Scope:** the complete structural skeleton — every step, every input, every field, every file the user must define, drop in, or point at.

This document is derived **from the code**, not from intent. Every parameter name, type, enum value, default, and file path below was read out of the package. Where a UI control is proposed, it is marked as *proposed*.

---

## 0. How to read this document

| Section | What it gives you |
| --- | --- |
| §1 | What the UI actually wraps (the four runtime surfaces + canonical pipeline order) |
| §2 | The global shell: persistent chrome, path settings, environment settings |
| §3 | Screen map / navigation model |
| §4 | **Step-by-step specification S0–S11** — the core of this document |
| §5 | Field-level form schemas for every Pydantic model (exact enums + constraints) |
| §6 | Cross-cutting UI requirements (pickers, drop zones, guards, feedback) |
| §7 | State, persistence, concurrency |
| §8 | Phasing / non-goals |

Two conventions used throughout:

- **`F-…`** = a *field* the user must supply or pick.
- **`→`** = the backing implementation (library function, then MCP tool).

---

## 1. Ground truth: what the UI wraps

### 1.1 Runtime surfaces

| Surface | Entry point | Used by the UI as |
| --- | --- | --- |
| Python library | `violation_pack/__init__.py` (20+ exported symbols) | Direct in-process calls (fastest, richest errors) |
| MCP server | `violation-pack-mcp` → `violation_pack.mcp_server:main` (39 tools) | Tool-call backend when the UI is a client (stdio / sse / streamable-http) |
| Catalog CLI | `violation-pack-catalog --format catalog\|vscode\|claude` | Client-config generator ("add this to another project") |
| Batch CLI | `python3 examples/refine_batch.py` | Batch screen S11 (thin wrapper over `refine_batch_core.run`) |

> The UI should treat the MCP tool surface as the **contract boundary**. Both the library and the MCP server expose the same operations; a UI built on MCP tools can later swap to in-process calls without a redesign.

### 1.2 Canonical pipeline order

This is the exact order used by the reference end-to-end script (`examples/refine_cl005.py`). The UI wizard MUST follow it, because later layers read what earlier layers wrote.

```
S0  Stage source artifacts in the bundle        copy_source_into_bundle
S1  Initialise the Violation (identity+incident) init_violation
S2  Layer 1 — Evidence (segments)               build_evidence_layer
S3  Layer 2 — Norms (articles)                  build_norms_layer
S4  Layer 3 — Element grids                     add_element_grid
S5  Layer 4 — Nexus matrix                      build_nexus_layer
S6  Layer 5 — Authority stubs                   add_authority_stub
S7  Authority verification (3 protocols)        verify_statute_* / verify_human_attested
S8  Confidence derivation + attach              derive_confidence / attach_confidence
S9  LLM enrichment (optional, 8 stages)         enrich_violation
S10 Validation V01–V11                          run_pipeline
S11 Packaging (json → manifest → zip)           write_violation_json → build_manifest → zip_bundle
```

Two additional, orthogonal surfaces:

- **S12 Extensions** — Qdrant / Neo4j / jurisprudence. Run *after* S11 normally, but can be exercised any time a `Violation` exists.
- **S13 Ingesters** — jurisprudence index, transcript bundles, framework markdown → Qdrant. Run *before* extension search, independent of any single violation.
- **S14 Introspection** — `embedder_info_tool`, `llm_provider_info_tool`, catalog.

### 1.3 The state spine

The UI holds exactly one piece of authoritative state: a serialized `Violation`. Every step is a pure function `Violation → Violation`. Consequences for the UI:

- The wizard is **resumable and re-runnable**: a step can be replayed against the current `Violation` without redoing prior steps.
- The `Violation` is the only thing worth persisting; step forms are derived views.
- Steps must be **idempotent by ID**: `segment_id`, `article_id`, `element_id`, `authority_id` are keys. Re-running a step with the same IDs replaces, it does not duplicate.

---

## 2. Global shell (persistent chrome)

Everything in §2 is visible from every step. It is the answer to "set paths / choose files".

### 2.1 Project & paths panel

Repeatedly needed paths. Proposed: a single collapsible **Settings drawer** with a folder-picker per row, remembered per project.

| ID | Label | Type | Default | Notes |
| --- | --- | --- | --- | --- |
| `F-project-root` | Project root | directory picker | repo root (dir containing `pyproject.toml`) | Used to resolve all relative paths; validates `violation_pack/` exists |
| `F-bundles-root` | Bundles root | directory picker | `examples/` in this repo, user's `CL/` in production | Parent of `CL-*` folders; S11 operates here |
| `F-bundle-dir` | Active bundle | directory picker / list | `<bundles-root>/CL-005` | The bundle the wizard is editing; all bundle-relative paths derive from here |
| `F-build-root` | Output / build root | directory picker | `build/` | Where `.zip` and side artifacts land |
| `F-transcripts-dir` | Transcripts source dir | directory picker | `<bundle-dir>/Transcripts` | Drop zone for `timeline_*.html` (S0, S2) |
| `F-frameworks-dir` | Legal framework source dir | directory picker | `<bundle-dir>/Legal framework` | Drop zone for `*_*.md` (S0, S3) |
| `F-env-file` | `.env` file | file picker | `<project-root>/.env` | Loaded by `Settings.from_env()`; created from `.env.example` |
| `F-venv-python` | Python interpreter | file picker | `<project-root>/.venv/bin/python` | Used to spawn the MCP server / CLI |
| `F-log-dir` | Log directory | directory picker | `.dev-logs/violation-refiner/` | Where `start.sh` writes server logs |

**Validation rules**

- `F-project-root` must contain `pyproject.toml` **and** `violation_pack/`; otherwise show *"Not a violation-pack project root"*.
- `F-bundles-root` must exist and be a directory; warn if it contains zero `CL-*` children.
- `F-bundle-dir` must be a directory whose name starts with `CL-`. S11 additionally filters to `CL-<digits>` unless `F-include-extra` is set.
- `F-env-file` may be absent (all settings have defaults) — do not hard-fail.

### 2.2 Environment & config panel

`Settings.from_env()` reads **31 variable names**. The UI should render them grouped, with the *effective* value shown after resolution, and mark each as *set / defaulted*.

| Group | Variable | Default (from `Settings`) | UI control |
| --- | --- | --- | --- |
| Qdrant | `QDRANT_URL` | *(empty)* | text |
| | `QDRANT_API_KEY` | *(empty)* | password (masked) |
| | `QDRANT_COLLECTION_PREFIX` | `violationrefiner_v1` | text |
| Neo4j | `NEO4J_URI` | *(empty)* | text |
| | `NEO4J_USER` | *(empty)* | text |
| | `NEO4J_PASSWORD` | *(empty)* | password |
| | `NEO4J_DATABASE` | `agent.violation.refiner` | text |
| | `NEO4J_LOCAL_URI` | *(empty)* | text (advanced) |
| | `NEO4J_LOCAL_USER` | *(empty)* | text (advanced) |
| | `NEO4J_LOCAL_PASS` | *(empty)* | password (advanced) |
| Ollama | `OLLAMA_HOST` | *(empty → `http://localhost:11434`)* | text |
| | `OLLAMA_EMBED_MODEL` | `bge-m3` | text |
| | `OLLAMA_MODEL` | *(empty)* | text |
| | `OLLAMA_API_KEY` | *(empty)* | password |
| LLM (generic) | `LLM_PROVIDER` | inferred from base URL / keys | select: `openrouter` \| `anthropic` \| `deepseek` \| `openai` \| `ollama` |
| | `LLM_MODEL` | *(empty)* | text |
| | `LLM_API_KEY` | *(empty)* | password |
| | `LLM_BASE_URL` | *(empty)* | text |
| | `LLM_TEMPERATURE` | `0.1` | number (slider 0–2) |
| | `LLM_MAX_TOKENS` | `8000` | number |
| | `LLM_TOKEN_BUDGET` | `250000` | number |
| | `LLM_TIMEOUT_SECONDS` | `90.0` | number |
| Provider keys | `OPENROUTER_API_KEY` | *(empty)* | password |
| | `OPENROUTER_MODEL` | *(empty)* | text |
| | `ANTHROPIC_API_KEY` | *(empty)* | password |
| | `ANTHROPIC_MODEL` | *(empty)* | text |
| | `DEEPSEEK_API_KEY` | *(empty)* | password |
| | `DEEPSEEK_MODEL` | *(empty)* | text |
| | `OPENAI_API_KEY` | *(empty)* | password |
| | `OPENAI_MODEL` | *(empty)* | text |
| Governance | `AUTHORITY_VERIFICATION_FLOOR` | `0.85` | number 0–1 (affects S8) |

Also surface, outside `Settings`:

| Variable | Default | Effect |
| --- | --- | --- |
| `MCP_TRANSPORT` | `stdio` (env), `streamable-http` via `start.sh` | `stdio` \| `sse` \| `streamable-http` |
| `MCP_HOST` | `127.0.0.1` (code), `0.0.0.0` via `start.sh` | bind host |
| `MCP_PORT` | `8124` | bind port |

**Validation rules**

- `AUTHORITY_VERIFICATION_FLOOR` must be `0 ≤ x ≤ 1`; the value is clamped in code, but surface a warning if outside.
- Secret fields must never be echoed back into the DOM in plaintext after save; show `••••` + a "replace" affordance.
- A **Test connections** button should call `embedder_info_tool` and `llm_provider_info_tool` and show resolved provider/model, mirroring `--catalog`/`--format catalog` introspection.

### 2.3 Runtime & dependency health strip

Proposed always-visible status strip. Each item has a green/amber/red state and a fix-it link.

| Check | How | Failure text |
| --- | --- | --- |
| Python version | `sys.version_info >= (3, 10)` | "requires-python >=3.10" |
| `pydantic >= 2.5` | import check | "core dependency missing" |
| `mcp` extra | `importlib.metadata.version("mcp")` major == 1 | "MCP client/server unavailable — `pip install -e '.[mcp]'`" |
| `qdrant-client` extra | import check | "Qdrant tools disabled" |
| `neo4j` extra | import check | "Neo4j tools disabled" |
| `httpx` extra | import check | "LLM enrichment disabled" |
| `pytest` (dev) | import check | "test suite cannot run" |
| MCP server reachable | `GET http://{host}:{port}/health` | "server not listening on 8124" |

### 2.4 Global activity log

A single append-only pane fed by: step results, the MCP server stdout/stderr, and the batch summary. Should be filterable by step and severity, and exportable. Long-running operations (S9 enrichment, S11 batch, S13 ingest) stream here with per-stage progress.

---

## 3. Screen map

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  ViolationRefiner            [project ▾]  [bundle ▾]   ● health   ⚙ settings │
├───────────────┬──────────────────────────────────────────────────────────────┤
│  WIZARD       │                                                              │
│               │                                                              │
│  S0 Stage     │                     STEP CANVAS                              │
│  S1 Init      │  (form for the selected step; see §4)                        │
│  S2 Evidence  │                                                              │
│  S3 Norms     │                                                              │
│  S4 Elements  │                                                              │
│  S5 Nexus     │                                                              │
│  S6 Auth stubs│                                                              │
│  S7 Verify    │                                                              │
│  S8 Confidence│                                                              │
│  S9 Enrich    │                                                              │
│  S10 Validate │                                                              │
│  S11 Package  │                                                              │
│  ─────────────│                                                              │
│  S12 Stores   │                                                              │
│  S13 Ingest   │                                                              │
│  S14 Inspect  │                                                              │
│               │                                                              │
├───────────────┴──────────────────────────────────────────────────────────────┤
│  ACTIVITY LOG                                                  [filter ▾]     │
└──────────────────────────────────────────────────────────────────────────────┘
```

Side panels available from any step (proposed tabs on the right or as drawers):

1. **Violation JSON** — read-only, live, collapsible tree of the current `Violation`.
2. **Validation** — latest `ValidationReport` (11 checks, pass/warn/fail).
3. **Provenance** — the `provenance` array as a reverse-chronological timeline.
4. **Confidence** — value + formula + component breakdown.
5. **Files** — the on-disk bundle tree with sizes/hashes (mirrors `MANIFEST.txt`).

---

## 4. Step specification

Each step below gives: **purpose**, **user inputs**, **backing call**, **outputs**, **UI controls**, **failure modes**, **gate**.

---

### S0 — Stage source artifacts

**Purpose.** Put the source-of-truth files inside the bundle so later steps can hash and anchor against them. This is the "drop in" step.

**→** `copy_source_into_bundle(source_path: Path, root: Path, kind: str) -> Path`
**→** MCP: `copy_source_into_bundle_tool(source_path, bundle_root, kind)`

`kind` MUST be one of the `BUNDLE_LAYOUT` keys — this is a closed enum, and the UI should render it as a dropdown, not free text:

| `kind` value | Destination inside the bundle |
| --- | --- |
| `violation_main` | `{violation_id}.json` |
| `contract` | `contract.json` |
| `manifest` | `MANIFEST.txt` |
| `readme` | `Violation bundle/README.md` |
| `validation_report` | `Validation/validation_report.md` |
| `validation_checks` | `Validation/checks.json` |
| `element_grid` | `Schema/element_grid_{violation_id}.json` |
| `transcripts_dir` | `Transcripts/` |
| `framework_dir` | `Legal framework/` |

**User inputs**

| ID | Label | Type | Required | Notes |
| --- | --- | --- | --- | --- |
| `F-s0-source` | Source file | **file drop zone + picker** | yes | Any file; name is preserved |
| `F-s0-kind` | Destination | select (9 values above) | yes | Filters to sensible defaults from file type |
| `F-s0-bundle-root` | Bundle root | directory (from §2.1) | yes | Created if absent |

**Behaviours**

- Drag-and-drop multiple files at once; queue them as a list of `(source, kind)` rows.
- Auto-suggest `kind` from the file: `*.html` containing `transcript-segment` → `transcripts_dir`; `*.md` with `### Art.` headers → `framework_dir`; `*.json` → `contract` or `violation_main`.
- Show the computed destination path **before** copying, and warn if it would overwrite.
- After copy, show the file's `sha256` — this is the hash later steps (S2/S3, V02/V03) compare against.

**Failure modes.** Source missing/unreadable; `kind` not in `BUNDLE_LAYOUT` (raise before copying); destination exists (confirm overwrite).

**Gate.** At least one transcript and one framework staged, or an explicit "continue without" acknowledgement.

---

### S1 — Initialise the violation

**Purpose.** Create the identity + incʹident block that every downstream layer hangs off.

**→** `init_violation` / MCP `init_violation`
**Signature:** `init_violation(violation_id, title, severity, incident, cross_references=None, open_questions=None)`

**User inputs**

| ID | Field | Type | Required | Default | Validation |
| --- | --- | --- | --- | --- | --- |
| `F-vid` | `violation_id` | text | yes | derived from bundle dir name (`CL-005`) | non-empty; unique across siblings recommended |
| `F-title` | `title` | text | yes | — | non-empty (falls back to `violation_id` in code, but UI should require) |
| `F-severity` | `severity` | **select** | yes | `MEDIUM` | `LOW` \| `MEDIUM` \| `HIGH` \| `CRITICAL` (uppercased; invalid → `MEDIUM`) |
| `F-inc-date` | `incident.date` | date | yes | `unknown` | ISO-8601 or the literal `unknown` |
| `F-inc-location` | `incident.location` | text | yes | `unknown` | — |
| `F-inc-flight` | `incident.flight` | text | no | — | e.g. `LA-1234` |
| `F-inc-operator` | `incident.operator` | text | no | — | — |
| `F-inc-clock` | `incident.clock_time_estimate` | text | no | — | free text, e.g. `15:16` |
| `F-inc-clockconf` | `incident.clock_time_confidence` | **select** | no | `unknown` | `verified` \| `estimated_from_audio_offset` \| `unknown` |
| `F-xrefs` | `cross_references` | repeatable row | no | `[]` | each row: `ref` (text) + `relation` (text) |
| `F-oqs` | `open_questions` | repeatable row | no | `[]` | each row: `id`, `question`, `blocks_element`, `priority`, `obtaining_method` |

**Open-question sub-form**

| Field | Type | Allowed values |
| --- | --- | --- |
| `id` | text | e.g. `OQ-CL005-PDI-PARTE` |
| `question` | textarea | — |
| `blocks_element` | text | element ID, optional |
| `priority` | select | `low` \| `medium` \| `high` \| `critical` (invalid → `medium`) |
| `obtaining_method` | textarea | e.g. "request PDI parte policial via Ley 20.285" |

**Outputs.** A `Violation` with `schema_version="3.0"` and everything else empty.

**Gate.** `violation_id`, `title`, `severity`, `incident.date`, `incident.location` present.

---

### S2 — Layer 1: Evidence segments

**Purpose.** Anchor verbatim transcript quotes to real HTML artifacts, producing segments with hashes and audio offsets. This is what makes V01/V02 meaningful.

**→** `build_evidence_layer` / MCP `build_evidence_layer_tool`
**Signature:** `build_evidence_layer_tool(violation, transcript_path, transcript_source_id, transcript_bundle_uri, segment_specs)`

**User inputs**

| ID | Field | Type | Required | Notes |
| --- | --- | --- | --- | --- |
| `F-s2-transcript` | `transcript_path` | **file picker** (`.html`) | yes | Pre-filled from staged `Transcripts/*.html` |
| `F-s2-source-id` | `transcript_source_id` | text | yes | e.g. `STG-7`. Auto-suggested from filename (see below) |
| `F-s2-uri` | `transcript_bundle_uri` | text | no | e.g. `Transcripts/timeline_aeropuerto_STG_7.html` |
| `F-s2-specs` | `segment_specs` | repeatable table | yes | see below |

**Filename → `source_id` inference** (mirror this in the UI so the field auto-fills):

| Filename pattern | Inferred `source_id` |
| --- | --- |
| `timeline_aeropuerto_(STG_\d+)\.html` | `STG-N` |
| `timeline_aeropuerto_arturo_merino_benitez_(\d+)\.html` | `STG-N` |
| `timeline_latam_STG_(\d+)\.html` | `LATAM-N` |
| anything else | file stem |

**Segment spec table** — each row is one segment the user wants to pull in:

| Column | Type | Required | Notes |
| --- | --- | --- | --- |
| `segment_id` | text | yes | **scoped form `SRC.local`, e.g. `STG-7.seg-55`**. Unscoped IDs are skipped with a note |
| `role_in_argument` | text | no | e.g. `fact`, `admission`, `contradiction` (defaults to `legacy_fact` in the normalizer) |
| `translation_en` | textarea | no | English rendering; falls back to verbatim |
| `transcription_notes` | textarea | no | — |

**Read-only, derived, and shown live after the call** (this is the key feedback loop):

| Derived | Source |
| --- | --- |
| `audio_offset_start` / `audio_offset_end` | parsed from the HTML `<div class="seg-time">12.80s → 15.16s</div>` |
| `speaker` | parsed from `<div class="seg-speaker">` |
| `verbatim_es` | parsed from `<p class="seg-text">"…"</p>` — **never hand-typed** |
| `verbatim_sha256` | `sha256(verbatim_es)` |
| `source_uri` | `<bundle_uri>#<local_id>` |
| `source_sha256` | `sha256` of the HTML artifact bytes |

**Behaviours**

- **Segment browser.** Before adding, let the user browse the parsed transcript (all segments with timecode, speaker, text) and tick rows to build `segment_specs`. This removes the main source of error (`segment_id` typos).
- If a segment ID is not found, the record is still kept but rewritten as an **unanchored legacy record**: `source_uri = legacy://{violation_id}/{segment_id}`, `transcription_notes += " | legacy-unanchored"`, and audio offsets attempted via `_parse_time_seconds` (`"12.80s"`, `"15:16"`, floats all supported). The UI must flag these rows red — they will fail V01.
- Empty `verbatim_es` on a resolved segment is back-filled from the supplied legacy text (a real behaviour of the normalizer) — surface this as an info note, not an error.

**Failure modes.** Transcript file missing/unreadable; HTML does not match the expected `transcript-segment` template → zero segments parsed; handle with "template not recognised" guidance rather than a stack trace.

**Gate.** ≥1 anchored segment (a segment whose `source_uri` is not `legacy://…`).

---

### S3 — Layer 2: Norms (cached articles)

**Purpose.** Attach the legal articles that the violation invokes, with verbatim excerpts verified against the framework Markdown, plus candidate (unverified) articles.

**→** `build_norms_layer` / MCP `build_norms_layer_tool`
**Signature:** `build_norms_layer_tool(violation, framework_path, framework_code, framework_bundle_uri, article_specs, candidate_specs=None)`

**User inputs**

| ID | Field | Type | Required | Notes |
| --- | --- | --- | --- | --- |
| `F-s3-framework` | `framework_path` | **file picker** (`.md`) | yes | Pre-filled from staged `Legal framework/*.md` |
| `F-s3-code` | `framework_code` | text | yes | e.g. `CHIPENCOD`, `CPCL`, `CP`. Auto-suggested: `md.stem.split("_")[0].upper()` |
| `F-s3-uri` | `framework_bundle_uri` | text | no | e.g. `Legal framework/CHIPENCOD_CP.md` |
| `F-s3-articles` | `article_specs` | repeatable table | yes | established articles |
| `F-s3-candidates` | `candidate_specs` | repeatable table | no | preliminary/uncertain articles |

**Established-article row**

| Column | Type | Required | Allowed values / default |
| --- | --- | --- | --- |
| `article_id` | text | yes | e.g. `CHIPENCOD.Art.193` |
| `article_name` | text | no | defaults to `article_id` |
| `subsections_invoked` | list | no | e.g. `["193.1","193.2"]` |
| `verbatim_excerpt` | textarea | yes | **must be a byte-exact substring of the article body in the cache** |
| `duty_bearer` | text | no | default `state` |
| `norm_type` | select | no | `prohibition` \| `penalty` \| `right` \| `liability` \| `definition` \| `exemption` (default `definition`) |
| `applicability` | select | no | `direct` \| `indirect_predicate` \| `supporting` (default `supporting`) |
| `applicability_rationale` | textarea | no | default `legacy import` |

**Candidate-article row**

| Column | Type | Required |
| --- | --- | --- |
| `candidate_article_id` | text | yes |
| `candidate_name` | text | no |
| `framework_cache_status` | select | `verified_in_bundle` \| `not_in_bundle` \| `pending_fetch` |
| `verification_required` | string list | no |
| `preliminary_view` | textarea | no |
| `history_note` | textarea | no |

**Behaviours — the arithmetic must be explained in the UI**

- **Article picker.** Parse the framework `.md` and list every `### Art. N — Name` header (the reader indexes identifiers such as `1`, `19.1`, `133 A`, `3 letra b)`). Let the user pick an article and *select text* from its body to fill `verbatim_excerpt`, guaranteeing the substring condition.
- **Lookup semantics to mirror:** exact identifier match first, then a prefix match on `N ` or `N.` (so `133` matches `133 A` only if `133` itself is not cached). The UI's search box should implement the same fallback.
- **Live excerpt verification.** Show, per row: ✅ *excerpt found in cache body* / ❌ *not a substring* / ⚠️ *article body not in any cache*. This is exactly the demotion logic in the normalizer.
- **Demotion rule.** If an article cannot be verified, the library **demotes it to a candidate** with `framework_cache_status="not_in_bundle"` and a `verification_required` hint. The UI should offer a one-click "demote to candidate" action for rows it already knows will fail, rather than letting the round-trip surprise the user.
- **Framework cache provenance** is computed, not entered: `cache_file`, `cache_file_sha256`, `cache_self_reported_sha256` (from a `**Sha256:**` header if present), `cache_fetched_at`, `articles_cached`. Display these read-only; V03 compares the self-reported hash to the real one.

**Failure modes.** `framework_path` unreadable; no `### Art.` headers found → "cache format not recognised"; excerpt present but article body missing.

**Gate.** ≥1 established article verified in-bundle.

---

### S4 — Layer 3: Element grids

**Purpose.** For each established article, define the doctrinal elements that must be proven, and mark which segments prove them. This is the analytical heart of the bundle and the input to V06.

**→** `add_element_grid` / MCP `add_element_grid_tool`
**Signature:** `add_element_grid_tool(violation, grid)`

**User inputs**

| ID | Field | Type | Required | Notes |
| --- | --- | --- | --- | --- |
| `F-s4-article` | `grid.article_id` | select (from S3) | yes | — |
| `F-s4-short` | `grid.article_short` | text | no | e.g. `Art. 193` |
| `F-s4-elements` | `grid.elements` | repeatable table | yes | see below |

**Element row**

| Column | Type | Required | Allowed values / default |
| --- | --- | --- | --- |
| `element_id` | text | yes | e.g. `art193.documento_oficial` (used as a graph node + cross-ref key) |
| `label` | text | yes | human label |
| `doctrinal_basis` | textarea | no | why this element exists |
| `proof_status` | **select** | yes | `established` \| `strong` \| `contested` \| `weak` \| `missing` \| `not_applicable` \| `not_developed` |
| `proof_evidence_segments` | multi-select | no | pick from S2 segment IDs |
| `argument_es` | textarea | no | the Spanish argument linking evidence → element |
| `weaknesses` | textarea | no | — |
| `open_questions` | list | no | link to `OpenQuestion.id` from S1 |

**Weights — display these next to the dropdown so the score is never a mystery** (`PROOF_WEIGHTS`):

| `proof_status` | weight |
| --- | --- |
| `established` | 1.0 |
| `strong` | 0.8 |
| `contested` | 0.5 |
| `weak` | 0.2 |
| `missing` | 0.0 |
| `not_applicable` | 1.0 |
| `not_developed` | 0.0 |

**Derived, read-only:** `ArticleElementGrid.weighted_score()` — mean of the element weights. Show it as a live ring/bar per grid and an overall score.

**Behaviours.** Matrix-style editor is strongly preferred: elements as rows, segments as columns, and a cell to attach a segment with a linkage note. Flag every non-`established` element, and cross-link to the shared `open_questions` list.

**Gate.** Every established article has a grid with ≥1 element.

---

### S5 — Layer 4: Nexus matrix

**Purpose.** Record the fact ↔ norm ↔ element links that make the argument explicit, with a strength rating.

**→** `build_nexus_layer` / MCP `build_nexus_layer_tool`
**Signature:** `build_nexus_layer_tool(violation, entries)`

**User inputs**

| ID | Field | Type | Required | Allowed values |
| --- | --- | --- | --- | --- |
| `F-s5-fact` | `fact_id` | select (S2 segments) | yes | — |
| `F-s5-norm` | `norm_id` | select (S3 articles) | yes | — |
| `F-s5-element` | `element_id` | select (S4 elements) | yes | — |
| `F-s5-type` | `nexus_type` | text/select | yes | e.g. `proves`, `supports`, `contradicts` |
| `F-s5-strength` | `strength` | **select** | yes | `high` \| `medium` \| `low` |
| `F-s5-rationale` | `rationale_oneline` | text | yes | one line |

**Behaviours.** The three selects must be populated from state, never typed. Show a coverage matrix: any segment not cited by a nexus row, any element with no incoming nexus, any article with no nexus — these are the gaps the reviewer wants to find. V06/V07 consume this.

**Gate.** ≥1 nexus entry per established article.

---

### S6 — Layer 5: Authority stubs

**Purpose.** Register the authorities (case law, doctrine, comparative, statute) that will support the argument — deliberately *unverified* at this stage.

**→** `add_authority_stub` / MCP `add_authority_stub_tool`
**Signature:** `add_authority_stub_tool(violation, authority_id, type, supports, research_query, proposition_to_verify, verification_protocol=None, fabrication_risk_note=None)`

**User inputs**

| ID | Field | Type | Required | Allowed values / notes |
| --- | --- | --- | --- | --- |
| `F-s6-id` | `authority_id` | text | yes | unique key |
| `F-s6-type` | `type` | **select** | yes | `jurisprudence` \| `doctrine` \| `comparative` \| `statute` |
| `F-s6-supports` | `supports` | multi-select | yes | element IDs from S4 |
| `F-s6-query` | `research_query` | textarea | yes | how to find it |
| `F-s6-prop` | `proposition_to_verify` | textarea | yes | the exact legal proposition |
| `F-s6-protocol` | `verification_protocol` | **select** | no | `statute_in_bundle_v1` \| `statute_external_fetch_v1` \| `human_attested_v1` |
| `F-s6-risk` | `fabrication_risk_note` | textarea | no | known fabrication risk |

Optional bibliographic fields (all text, all optional): `court`, `rol`, `decision_date`, `author`, `work`, `pages`, `instrument`, `holding_summary`.

**Behaviours**

- The `verification_protocol` select should *drive the S7 form*: choosing `statute_in_bundle_v1` pre-selects the S7 tab and shows the fields that protocol needs.
- Show `verified: false` prominently on every stub. Nothing in the UI should imply a stub is evidence.
- `fabrication_risk_note` is a first-class field — render it as a warning-styled textarea, because it is the guard against LLM-fabricated citations.

**Gate.** Every element with `proof_status` in {`established`, `strong`, `contested`} should be referenced by ≥1 authority `supports` (advisory, not blocking).

---

### S7 — Authority verification (three protocols)

**Purpose.** Convert an unverified stub into a verified authority with a `VerificationProvenance` record. There are exactly three protocols; the UI must implement all three as separate sub-forms.

All three raise on failure with the prefix `verification_failed:` — parse that and show the reason.

#### S7a — `statute_in_bundle_v1`

**→** `verify_statute_in_bundle` / MCP `verify_statute_in_bundle_tool`
**Signature:** `verify_statute_in_bundle_tool(violation, authority_id, framework_md_path, framework_code, article_number, target_quote, instrument=None, pages=None)`

| ID | Field | Type | Source |
| --- | --- | --- | --- |
| `F-s7a-authority` | `authority_id` | select (unverified stubs) | S6 |
| `F-s7a-md` | `framework_md_path` | **file picker** | pre-filled from bundle framework |
| `F-s7a-code` | `framework_code` | text | from S3 |
| `F-s7a-article` | `article_number` | text | from S3 article list |
| `F-s7a-quote` | `target_quote` | textarea | the quote to match **in the bundle** |
| `F-s7a-instrument` | `instrument` | text | optional |
| `F-s7a-pages` | `pages` | text | optional |

#### S7b — `statute_external_fetch_v1`

**→** `verify_statute_external_fetch` / MCP `verify_statute_external_fetch_tool`
**Signature:** `verify_statute_external_fetch_tool(violation, authority_id, source_uri, source_content, target_quote, instrument, pages=None)`

| ID | Field | Type | Notes |
| --- | --- | --- | --- |
| `F-s7b-authority` | `authority_id` | select | — |
| `F-s7b-uri` | `source_uri` | text | **required**, e.g. `https://www.bcn.cl/leychile/...` |
| `F-s7b-content` | `source_content` | **file drop zone + textarea** | **required** — paste, or drop the fetched `.html`/`.txt`/`.json` |
| `F-s7b-quote` | `target_quote` | textarea | required |
| `F-s7b-instrument` | `instrument` | text | required |
| `F-s7b-pages` | `pages` | text | optional |

#### S7c — `human_attested_v1`

**→** `verify_human_attested` / MCP `verify_human_attested_tool`
**Signature:** `verify_human_attested_tool(violation, authority_id, source_uri, source_content, target_quote, attestor, court=None, rol=None, decision_date=None, author=None, work=None, pages=None, instrument=None, holding_summary=None)`

| ID | Field | Type | Required |
| --- | --- | --- | --- |
| `F-s7c-authority` | `authority_id` | select | yes |
| `F-s7c-uri` | `source_uri` | text | yes |
| `F-s7c-content` | `source_content` | textarea / drop zone | yes |
| `F-s7c-quote` | `target_quote` | textarea | yes |
| `F-s7c-attestor` | `attestor` | text | **yes** — the human who attests |
| `F-s7c-court` / `rol` / `decision_date` / `author` / `work` / `pages` / `instrument` | text | no |
| `F-s7c-holding` | `holding_summary` | textarea | no |

**Outputs for all three.** An updated `Authority` with `verified=true`, plus `VerificationProvenance`:

| Field | Description |
| --- | --- |
| `protocol` | one of the three literals |
| `source_uri` | as supplied |
| `source_sha256` | computed from bytes |
| `verified_at` | timestamp |
| `matched_quote` | the quote that matched |
| `matched_offset` | character offset of the match |
| `notes` | free text |

**Behaviours.**

- Show the matched offset as a **highlighted span** in the source content viewer. This is the single most valuable UI affordance in the whole app — it lets a human see the quote is real in one glance.
- Verify-all button: run all unverified stubs against the chosen protocol, then show a table of verified / failed / skipped.
- Failure presentation: `verification_failed: …` → red inline error with the failing `authority_id` and the specific mismatch (quote not found vs. article not found).

**Gate.** None (advisory). But the health of this step feeds V07 and the confidence factor in S8.

---

### S8 — Confidence derivation

**Purpose.** Compute and attach the confidence value with a human-readable formula.

**→** `derive_confidence(violation, article_weights=None, authority_verification_floor=0.85)` / MCP `derive_confidence_tool`
**→** `attach_confidence(violation)` / MCP `attach_confidence_tool`

**User inputs**

| ID | Field | Type | Default | Notes |
| --- | --- | --- | --- | --- |
| `F-s8-weights` | `article_weights` | editable table | derived | per-`article_id` weight; defaults come from `DEFAULT_APPLICABILITY_WEIGHTS` and element scores, then `1.0` for any article not in the applicability map |
| `F-s8-floor` | `authority_verification_floor` | number 0–1 | `0.85` (from `AUTHORITY_VERIFICATION_FLOOR`) | minimum verification multiplier |

**Derived outputs to display (never editable)**

| Field | Description |
| --- | --- |
| `confidence.value` | final score |
| `confidence.components` | per-component breakdown |
| `confidence.authorities_verification_factor` | `floor + (1 − floor) × verified_ratio` when authorities exist; the code's formula string is `"authorities_verification_factor = {floor} + {1-floor} × verified_ratio = {factor}"`, and exactly `floor` when no authorities are declared |
| `confidence.derivation_formula` | the formula text |
| `confidence.derived_at` | timestamp |
| `confidence.history` | prior derivations, appended |

**Behaviours.** Render a **"why" panel**: value, each component with its weight, and the verification factor with `verified_ratio` spelled out (e.g. "3 of 5 authorities verified → 0.85 + 0.15 × 0.6 = 0.94"). Provide a *Recompute* button that is purely idempotent.

---

### S9 — LLM enrichment (optional)

**Purpose.** Let an LLM propose refinements across eight stages. Each stage proposes, the layer functions validate, and a provenance entry is logged.

**→** `enrich_violation_tool(violation, framework_specs=None, known_violation_ids=None, stages=None, llm_override=None)`
**→** `enrich_stage_tool(stage, violation, framework_specs=None, known_violation_ids=None, llm_override=None)`
**→** `verify_enrichment_tool(violation, framework_specs=None, known_violation_ids=None)`

**Stage picker — a checklist of exactly these eight, in this order** (`ENRICHMENT_STAGES`):

| # | Stage | What it proposes |
| --- | --- | --- |
| 1 | `segments` | segment metadata (role, translation, notes) |
| 2 | `subsections` | article subsection invocations |
| 3 | `element_grids` | element rows / proof status |
| 4 | `nexus` | fact↔norm↔element links |
| 5 | `candidates` | candidate articles |
| 6 | `authorities` | authority stubs (unverified!) |
| 7 | `open_questions` | open questions |
| 8 | `cross_references` | cross-references to sibling violations |

**User inputs**

| ID | Field | Type | Default | Notes |
| --- | --- | --- | --- | --- |
| `F-s9-stages` | `stages` | multi-checkbox | all 8 | Partial runs are supported; order is always canonical |
| `F-s9-frameworks` | `framework_specs` | repeatable row | from bundle | each row `{path, framework_code, bundle_uri}` |
| `F-s9-known` | `known_violation_ids` | tag input | auto | `refine_batch_core` derives this from sibling bundles automatically |
| `F-s9-provider` | `llm_override.provider` | select | from `Settings` | `openrouter` \| `anthropic` \| `deepseek` \| `openai` \| `ollama` |
| `F-s9-model` | `llm_override.model` | text | from `Settings` | — |
| `F-s9-key` | `llm_override.api_key` | password | from `Settings` | masked |
| `F-s9-baseurl` | `llm_override.base_url` | text | from `Settings` | — |

**Behaviours**

- Before running, show resolved provider + model + temperature + token budget, taken from `llm_provider_info_tool`. Do not let the user start a run that will obviously fail on a missing key.
- **Per-stage progress** with a streamed log — the batch runner prints `enrich [3/8]: element_grids ...` / `... done`, so mirror that format.
- Fail-fast is the library default: if a stage raises `LLMError`, show the failing stage and offer *skip this stage and continue*, which is exactly what `enrich_stages` supports.
- **Post-run diff.** Show added/modified items per stage against the pre-run snapshot, since enrichment mutates the `Violation` in place.
- **Verifier.** A separate button runs `verify_enrichment_tool` and shows unsupported claims. Make it visually distinct from enrichment so enrichment is never mistaken for verification.

**Gate.** None. Enrichment is a convenience layer, and the UI must say so: authority stubs created here are **unverified** and must go through S7.

---

### S10 — Validation V01–V11

**Purpose.** Run the integrity pipeline and present the result. This is the reviewer's decision surface.

**→** `run_pipeline(violation, transcripts=None, frameworks=None, contract=None, known_violation_ids=None, extra_checks=None)` / MCP `run_pipeline_tool`
**`PIPELINE_VERSION` = `"1.0"`**

**User inputs**

| ID | Field | Type | Default | Notes |
| --- | --- | --- | --- | --- |
| `F-s10-transcripts` | `transcripts` | registry | auto-discovered | The normalizer auto-discovers `Transcripts/*.html` and `Legal framework/*.md`; expose as a read-only "registered sources" list |
| `F-s10-frameworks` | `frameworks` | registry | auto-discovered | as above |
| `F-s10-contract` | `contract` | **file picker** (`contract.json`) | `<bundle>/contract.json` | optional; used by V08 |
| `F-s10-known` | `known_violation_ids` | tag input | siblings | used by V05 |
| `F-s10-extra` | `extra_checks` | advanced | `[]` | plug-in checks |

**The eleven checks — render each with its semantics so pass/warn/fail is interpretable:**

| ID | Name | Pass / Warn / Fail semantics |
| --- | --- | --- |
| V01 | `segment_resolution` | fail when a segment does not resolve against its transcript |
| V02 | `verbatim_quote_match` | fail when a verbatim quote is not byte-for-byte in the transcript HTML |
| V03 | `article_text_hash` | **warn** when the cache's self-reported SHA mismatches the real one; **fail** when an excerpt is not a substring of the cache body |
| V04 | `article_exists_in_framework_cache` | fail when a cited article is absent from every cache |
| V05 | `cross_references_resolve` | **warn** when there is no bundle-level index to resolve against |
| V06 | `element_coverage` | fail when an established article has no element grid / no coverage |
| V07 | `authorities_verification` | warn/fail on unverified or unbacked authorities |
| V08 | `contract_consistency` | accepts the legacy `violation_number` alias; a purely numeric contract confidence is treated as a **legacy warning**, not a failure |
| V09 | `language_consistency` | fail on inconsistent language fields |
| V10 | `confidence_derivation` | fail when confidence is missing / not derivable |
| V11 | `enrichment_integrity` | includes the known warning `W_AUTH_DANGLING_SUPPORT` |

**Outputs.** `ValidationReport(pipeline_version, ran_at, violation_id, checks)` plus `report.summary` = `{total, pass, warn, fail}`.

**Known-good reference result** (from the demo bundle — use this as a smoke test for the UI):

```
Confidence: 0.74
{'total': 11, 'pass': 7, 'warn': 4, 'fail': 0}
warnings: V03, V05, V07, V11 (W_AUTH_DANGLING_SUPPORT)
```

**Files written by the batch path** (S11): `Validation/checks.json` (full report) and `Validation/validation_report.md` (markdown with `Total/Pass/Warn/Fail` and a bullet list per check).

**Behaviours.** Check rows expand to `details`; failing rows deep-link to the offending step (a V02 failure jumps to S2 with that segment selected). Provide a *fail-only* filter and a copy-as-markdown action.

---

### S11 — Packaging and batch

**Purpose.** Persist the canonical JSON, build the manifest, optionally zip and copy sources.

**Single bundle →** `write_violation_json` → `build_manifest` → `zip_bundle`

| ID | Field | Type | Default | Notes |
| --- | --- | --- | --- | --- |
| `F-s11-bundle` | `bundle_root` | directory | active bundle | output location |
| `F-s11-schema` | `schema_version` | text | `3.0` | passed to `build_manifest` |
| `F-s11-zip` | `out_zip` | file path | `<bundle>/../<id>_refined_pack.zip` | `zip_bundle` deletes an existing file before writing |

`build_manifest` output format (three lines per file): `relative_path`, `bytes`, `sha256`, with header lines `Violation pack`, `Generated`, `Schema version`, `Files included`.

**Batch →** `refine_batch_tool(input_root, only=None, include_extra=False, limit=None, write_backup=True, zip_output=False)`
**→** `violation_pack.refine_batch_core.run(root, include_extra, only, limit, write_backup, zip_output, enrich=False, enrich_stages=None, llm_override=None) -> int` (0 = all ok, 1 = ≥1 failure)

| ID | Field | Type | Default | Semantics |
| --- | --- | --- | --- | --- |
| `F-s11-root` | `input_root` | directory picker | `F-bundles-root` | container of `CL-*` folders |
| `F-s11-only` | `only` | multi-select of discovered folders | none | e.g. `CL-005 CL-007` |
| `F-s11-extra` | `include_extra` | toggle | **off** | off ⇒ keep only `CL-<digits>`; on ⇒ also `CL-F7DD941E`-style names |
| `F-s11-limit` | `limit` | number | none | process first N after filtering |
| `F-s11-backup` | `write_backup` | toggle | **on** | writes `<id>.json.bak` **only if absent**; re-runs read the `.bak` as the source so re-anchoring is repeatable |
| `F-s11-zip` | `zip_output` | toggle | off | writes `<folder>_refined_pack.zip` next to each bundle |
| `F-s11-enrich` | `enrich` | toggle | auto | CLI resolves: `--no-enrich` wins; else `--enrich`; else auto-on when a key exists or provider is `ollama` |
| `F-s11-stages` | `enrich_stages` | multi-checkbox | all | comma-separated in CLI; list here |
| `F-s11-llm-*` | `llm_override` | provider/model/base_url | none | `{provider, model, api_key, base_url}` |

**Discovery rules the UI must reproduce** (so the folder picker shows what the runner will actually see):

- Candidate folders = direct children of `input_root` whose name starts with `CL-`, sorted by name.
- Violation JSON lookup: `<dir>/<dir-name>.json` first; else the single `*.json` that is not `contract.json` and not `*.bak`; else *not found* (that folder fails with `violation JSON not found`).
- Transcripts discovered as `Transcripts/*.html`; frameworks as `Legal framework/*.md`.
- `known_violation_ids` is collected from **all** discovered bundles **before** the `only` filter is applied — so a single-bundle run still sees its siblings.

**Outputs.** Per folder: rewritten `<id>.json`, `Validation/checks.json`, `Validation/validation_report.md`, `MANIFEST.txt`, optional zip. At the root: `refine_batch_summary.json` = `{root, total, succeeded, failed, results[]}` where each result is `{violation_id, summary, confidence, notes}` or `{violation_id, error}`.

**Behaviours.** Multi-select folder list with per-row status; streaming log with the runner's exact format (`- CL-005: pass=7 warn=4 fail=0 confidence=0.74`); final summary table with pass/warn/fail and confidence per bundle; autosave the summary JSON and offer to download. Warn loudly when `write_backup` is off.

---

### S12 — Extensions: Qdrant, Neo4j, jurisprudence

**Purpose.** Project the bundle into the vector index and the graph, and query across the corpus. All are optional and all reads must degrade gracefully when the extra is missing.

#### S12.1 Qdrant

| Action | MCP tool | Inputs |
| --- | --- | --- |
| Index a violation | `qdrant_index_violation_tool` | `violation` |
| Search segments | `qdrant_search_segments_tool` | `query` (text), `top_k` (default 5) |
| Search articles | `qdrant_search_articles_tool` | `query`, `top_k=5` |
| Search authorities | `qdrant_search_authorities_tool` | `query`, `top_k=5` |
| Search jurisprudence | `qdrant_search_jurisprudence_tool` | `query`, `top_k=5` |
| Upsert jurisprudence | `qdrant_upsert_jurisprudence_tool` | `record_id`, `text`, `payload` (JSON) |
| **Reset collections** | `qdrant_reset_collections_tool` | **none — DESTRUCTIVE** |

UI: search box + top-k + result cards with score, payload, and a jump-to-source link. Connection target from `QDRANT_URL` / `QDRANT_COLLECTION_PREFIX`.

#### S12.2 Neo4j

| Action | MCP tool | Inputs |
| --- | --- | --- |
| Upsert violation | `neo4j_upsert_violation_tool` | `violation` |
| Violations citing an article | `neo4j_find_violations_citing_tool` | `article_id` |
| Violations with contested element | `neo4j_find_violations_with_contested_element_tool` | `element_id_glob` (glob!) |
| Walk implications | `neo4j_walk_implications_tool` | `open_question_id` |
| **Reset database** | `neo4j_reset_database_tool` | **none — DESTRUCTIVE** |

UI: three preset query panels matching the three read queries, plus a results table that links back to the owning bundle. Connection target from `NEO4J_URI` / `NEO4J_USER` / `NEO4J_DATABASE`.

#### S12.3 Jurisprudence

| Action | MCP tool | Inputs |
| --- | --- | --- |
| Search | `jurisprudence_search_tool` | `query` (text), `supports` (list of element IDs), `max_results` (default 5) |
| Verify | `jurisprudence_verify_tool` | `authority` (an `Authority`) |

UI: search box pre-populated with element IDs from S4; results show the full provenance and a **verified** badge that is only ever set when the provider has a primary source.

#### S12.4 Destructive-action guard (mandatory)

For `qdrant_reset_collections_tool` and `neo4j_reset_database_tool` the UI must:

1. Render the action in a danger style, never adjacent to routine controls.
2. Show the **resolved target** (URL / database name) in the confirmation.
3. Require a typed confirmation matching the target name, not a bare "OK".
4. Never expose a bulk "reset everything" shortcut.

---

### S13 — Ingesters

**→** `jurisprudence_ingest_tool(index_path, limit=None, skip=0, batch_size=64, sleep_between_batches=0.0, max_chunks_per_ruling=8)`
**→** `transcript_ingest_tool(bundle_root, bundle_id=None, limit_segments=None, batch_size=64, sleep_between_batches=0.0)`
**→** `framework_ingest_tool(markdown_path, framework_code, framework_name=None, batch_size=64)`

| Screen | File input | Fields |
| --- | --- | --- |
| Ingest rulings | `index_path` — **file picker (JSON)** | `limit`, `skip`, `batch_size` (64), `sleep_between_batches` (0.0), `max_chunks_per_ruling` (8) |
| Ingest transcript bundle | `bundle_root` — **directory picker** | `bundle_id` (defaults to dir name), `limit_segments`, `batch_size` (64), `sleep_between_batches` (0.0) |
| Ingest framework | `markdown_path` — **file picker (.md)** | `framework_code` (required), `framework_name` (defaults to code), `batch_size` (64) |

**Behaviours.** Show a progress bar from the batch counters; `sleep_between_batches` is a rate-limit knob and should have a tooltip saying so. `framework_code` should auto-suggest using the same rule as S3 (`stem.split("_")[0].upper()`).

---

### S14 — Introspection & catalog

| Action | MCP tool / CLI | Output to render |
| --- | --- | --- |
| Embedder info | `embedder_info_tool` | active embedder name (e.g. `hash-384`, `ollama-bge-m3`) + dimension |
| LLM provider info | `llm_provider_info_tool` | resolved provider + model |
| MCP catalog | `violation-pack-catalog --format catalog` | server entry: name, transport, command, env, optional env, 39 tools with tags |
| VS Code snippet | `--format vscode` | JSON under `mcp.servers` with `type`/`command`/`args`/`env` |
| Claude Desktop snippet | `--format claude` | JSON under `mcpServers` |

UI: an "Integrate" panel with copy buttons for both snippets, plus a tool inventory table. Embedder names available in this package: `hash-384`, `ollama-<model>`, `voyage-<model>`, `openai-<model>`, `cohere-<model>`.

---

## 5. Field-level form schemas

The canonical models. **All models are `extra="forbid"`** — the UI must never post an unknown key; doing so raises a validation error. Types are JS-friendly, with the Pydantic constraint in parentheses.

### 5.1 `Violation` (root state)

| Field | Type | Constraint |
| --- | --- | --- |
| `violation_id` | string | required |
| `title` | string | required |
| `severity` | string | `LOW\|MEDIUM\|HIGH\|CRITICAL` |
| `schema_version` | string | default `3.0` |
| `incident` | `Incident` | required |
| `segments` | `EvidenceSegment[]` | `[]` |
| `framework_caches` | `FrameworkCache[]` | `[]` |
| `established_articles` | `CachedArticle[]` | `[]` |
| `candidate_articles` | `CandidateArticle[]` | `[]` |
| `element_grids` | `ArticleElementGrid[]` | `[]` |
| `nexus_matrix` | `NexusEntry[]` | `[]` |
| `authorities` | `Authority[]` | `[]` |
| `confidence` | `ConfidenceDerivation?` | `null` until S8 |
| `open_questions` | `OpenQuestion[]` | `[]` |
| `cross_references` | `CrossReference[]` | `[]` |
| `provenance` | `ProvenanceEntry[]` | `[]` |

### 5.2 `Incident`

`date` (string) · `location` (string) · `flight` (string?) · `operator` (string?) · `clock_time_estimate` (string?) · `clock_time_confidence` ∈ `verified|estimated_from_audio_offset|unknown`

### 5.3 `EvidenceSegment`

| Field | Type | Notes |
| --- | --- | --- |
| `segment_id` | string | scoped `SRC.local` |
| `role_in_argument` | string | — |
| `audio_offset_start` / `audio_offset_end` | float | seconds |
| `speaker` | string | — |
| `verbatim_es` | string | — |
| `verbatim_sha256` | string | **exactly 64 hex chars** |
| `translation_en` | string? | — |
| `transcription_notes` | string? | — |
| `source_uri` | string | `legacy://…` marks unanchored |
| `source_sha256` | string | **exactly 64 hex chars** |
| `audio_uri` | string? | — |

### 5.4 `FrameworkCache`

`framework_code` · `framework_name` · `cache_file` · `cache_file_sha256` (64 hex) · `cache_self_reported_sha256` (64 hex, nullable) · `cache_source_url` · `cache_fetched_at` · `articles_cached` (string[])

### 5.5 `CachedArticle`

`article_id` · `article_name` · `subsections_invoked` (string[]) · `verbatim_excerpt` · `verbatim_excerpt_sha256` · `framework_code` · `framework_cache_status` ∈ `verified_in_bundle|not_in_bundle|pending_fetch` · `duty_bearer` · `norm_type` ∈ `prohibition|penalty|right|liability|definition|exemption` · `applicability` ∈ `direct|indirect_predicate|supporting` · `applicability_rationale`

### 5.6 `CandidateArticle`

`candidate_article_id` · `candidate_name` · `framework_cache_status` (same enum) · `verification_required` (string[]) · `preliminary_view?` · `history_note?`

### 5.7 `Element` / `ArticleElementGrid`

`Element`: `element_id` · `label` · `doctrinal_basis` · `proof_status` ∈ `established|strong|contested|weak|missing|not_applicable|not_developed` · `proof_evidence_segments` (string[]) · `argument_es` · `weaknesses` · `open_questions` (string[])
`ArticleElementGrid`: `article_id` · `article_short` · `elements[]` · derived `weighted_score()` using `PROOF_WEIGHTS` (§4 S4)

### 5.8 `NexusEntry`

`fact_id` · `norm_id` · `element_id` · `nexus_type` · `strength` ∈ `high|medium|low` · `rationale_oneline`

### 5.9 `Authority`

`authority_id` · `type` ∈ `jurisprudence|doctrine|comparative|statute` · `supports` (string[]) · `research_query` · `proposition_to_verify` · `court?` · `rol?` · `decision_date?` · `author?` · `work?` · `pages?` · `instrument?` · `holding_summary?` · `verified` (bool, default **false**) · `verification_protocol?` ∈ the three protocol literals · `verification_provenance?` · `fabrication_risk_note?`

### 5.10 `VerificationProvenance`

`protocol` ∈ `statute_in_bundle_v1|statute_external_fetch_v1|human_attested_v1` · `source_uri` · `source_sha256` · `verified_at` · `matched_quote` · `matched_offset` · `notes?`

### 5.11 `ConfidenceDerivation`

`value` · `components` · `authorities_verification_factor` · `derivation_formula` · `derived_at` · `history`

### 5.12 `CheckResult` / `ValidationReport`

`CheckResult`: `check_id` · `name` · `status` ∈ `pass|warn|fail` · `details`
`ValidationReport`: `pipeline_version` · `ran_at` · `violation_id` · `checks[]` · derived `summary` = `{total, pass, warn, fail}`

### 5.13 `OpenQuestion` / `CrossReference` / `ProvenanceEntry`

`OpenQuestion`: `id` · `question` · `blocks_element?` · `priority` ∈ `low|medium|high|critical` · `obtaining_method?`
`CrossReference`: `ref` · `relation`
`ProvenanceEntry`: `timestamp` · `actor` · `operation` · `layer?` · `note?`

---

## 6. Cross-cutting UI requirements

1. **Path discipline.** Every path is either an absolute path from a picker or a bundle-relative URI. Show both (`…/CL-005/Transcripts/x.html` and `Transcripts/x.html`), because downstream records store the relative form while tools need the absolute one.
2. **Drop zones are first-class.** S0, S7b, S7c, S13 all accept dropped files. Dropping must never silently succeed on a wrong `kind`.
3. **Never hand-type what can be picked.** `segment_id`, `article_id`, `element_id`, `authority_id` are all selects/multi-selects fed from state.
4. **Hashes are always computed.** `verbatim_sha256`, `source_sha256`, `cache_file_sha256`, `verbatim_excerpt_sha256` are read-only displays, never inputs.
5. **`extra="forbid"` handling.** If a form ever posts an unknown key, surface the raw Pydantic error mapped to the offending form row; do not swallow it.
6. **Show `verified` truthfully.** `Authority.verified` defaults to `false` and only S7 flips it. No other UI path may set it.
7. **Destructive actions** require typed confirmation and display the resolved target (§S12.4).
8. **Idempotent replay.** Every step shows "re-run against current state" and a diff preview before applying.
9. **Backups.** When a step rewrites `<id>.json`, honour the `write_backup` semantics: write `.bak` only if absent, and read from `.bak` when present.
10. **Progress and cancellation.** S9/S11/S13 are long-running; they must stream progress and support cancellation without leaving a half-written JSON (write to temp, then move).
11. **Graceful degradation.** Missing optional extras disable their panels with an install hint rather than throwing.

---

## 7. State, persistence, concurrency

- **Single source of truth:** the `Violation` JSON. Persist it after every step (`write_violation_json`).
- **Form state** is derived from the `Violation`; treat forms as projections so a reload never loses work.
- **Undo:** keep the previous `Violation` snapshot per step (cheap — it is one JSON file) and expose "revert this step".
- **Concurrency:** the batch runner is the only writer that touches many bundles; block other steps while S11 runs, and never run two batches over the same root concurrently.
- **Offline:** everything except S9/S12/S13 works fully offline against local files.

---

## 8. Phasing

| Phase | Deliverable | Steps |
| --- | --- | --- |
| **P1 — Local single bundle** | Wizard + JSON side panel + validation panel. No external stores. | S0–S8, S10, S11 (single bundle) |
| **P2 — Batch** | Folder discovery, multi-select, streaming summary. | S11 (batch) |
| **P3 — LLM** | Provider config, stage picker, diff + verifier. | S9 |
| **P4 — Stores** | Qdrant + Neo4j panels, destructive guards. | S12 |
| **P5 — Bulk ingest & integrate** | Ingesters, catalog snippets. | S13, S14 |

**Non-goals.** Authoring legal text; replacing the validator; editing source digests; any UI-set `verified` flag; a free-form Cypher/SQL console.

---

## Appendix A — Tool → step index (all 39)

| # | MCP tool | Step | Read/write | Destructive |
| --- | --- | --- | --- | --- |
| 1 | `init_violation` | S1 | write | no |
| 2 | `build_evidence_layer_tool` | S2 | write | no |
| 3 | `build_norms_layer_tool` | S3 | write | no |
| 4 | `add_element_grid_tool` | S4 | write | no |
| 5 | `build_nexus_layer_tool` | S5 | write | no |
| 6 | `add_authority_stub_tool` | S6 | write | no |
| 7 | `verify_statute_in_bundle_tool` | S7a | write | no |
| 8 | `verify_statute_external_fetch_tool` | S7b | write | no |
| 9 | `verify_human_attested_tool` | S7c | write | no |
| 10 | `derive_confidence_tool` | S8 | write | no |
| 11 | `attach_confidence_tool` | S8 | write | no |
| 12 | `enrich_violation_tool` | S9 | write | no |
| 13 | `enrich_stage_tool` | S9 | write | no |
| 14 | `verify_enrichment_tool` | S9 | read | no |
| 15 | `run_pipeline_tool` | S10 | read | no |
| 16 | `write_violation_json_tool` | S11 | write | no |
| 17 | `build_manifest_tool` | S11 | write | no |
| 18 | `zip_bundle_tool` | S11 | write | no |
| 19 | `copy_source_into_bundle_tool` | S0 | write | no |
| 20 | `refine_batch_tool` | S11 | write (bulk) | no |
| 21 | `qdrant_index_violation_tool` | S12.1 | write | no |
| 22 | `qdrant_search_segments_tool` | S12.1 | read | no |
| 23 | `qdrant_search_articles_tool` | S12.1 | read | no |
| 24 | `qdrant_search_authorities_tool` | S12.1 | read | no |
| 25 | `qdrant_search_jurisprudence_tool` | S12.1 | read | no |
| 26 | `qdrant_upsert_jurisprudence_tool` | S12.1 | write | no |
| 27 | `qdrant_reset_collections_tool` | S12.1 | write | **YES** |
| 28 | `neo4j_upsert_violation_tool` | S12.2 | write | no |
| 29 | `neo4j_find_violations_citing_tool` | S12.2 | read | no |
| 30 | `neo4j_find_violations_with_contested_element_tool` | S12.2 | read | no |
| 31 | `neo4j_walk_implications_tool` | S12.2 | read | no |
| 32 | `neo4j_reset_database_tool` | S12.2 | write | **YES** |
| 33 | `jurisprudence_search_tool` | S12.3 | read | no |
| 34 | `jurisprudence_verify_tool` | S12.3 | write | no |
| 35 | `jurisprudence_ingest_tool` | S13 | write | no |
| 36 | `transcript_ingest_tool` | S13 | write | no |
| 37 | `framework_ingest_tool` | S13 | write | no |
| 38 | `embedder_info_tool` | S14 | read | no |
| 39 | `llm_provider_info_tool` | S14 | read | no |

## Appendix B — Bundle layout on disk

```
<bundles-root>/
└── CL-005/
    ├── CL-005.json                    violation_main  (canonical state)
    ├── CL-005.json.bak                backup (written once, read as source on re-run)
    ├── contract.json                  contract
    ├── MANIFEST.txt                   manifest
    ├── Violation bundle/README.md     readme
    ├── Validation/
    │   ├── validation_report.md       validation_report
    │   └── checks.json                validation_checks
    ├── Schema/
    │   └── element_grid_CL-005.json   element_grid
    ├── Transcripts/                   transcripts_dir
    │   └── timeline_aeropuerto_STG_7.html
    └── Legal framework/               framework_dir
        └── CHIPENCOD_CP.md
```

Plus, at the bundles root after a batch run: `refine_batch_summary.json` and, when zipping, `CL-005_refined_pack.zip`.
