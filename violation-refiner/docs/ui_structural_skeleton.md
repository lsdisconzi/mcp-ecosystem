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
| MCP server | `violation-pack-mcp` → `violation_pack.mcp_server:main` (41 tools) | Tool-call backend when the UI is a client (stdio / sse / streamable-http) |
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
S10 Validation V01–V17                          run_pipeline
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
| `F-bundles-root` | Bundles root | directory picker | `build/` in this repo, user's `CL/` in production | Parent of `CL-*` folders; S11 operates here |
| `F-bundle-dir` | Active bundle | directory picker / list | `<bundles-root>/CL-005` | The bundle the wizard is editing; all bundle-relative paths derive from here |
| `F-build-root` | Output / build root | directory picker | `build/` | Where `.zip` and side artifacts land |
| `F-transcripts-dir` | Transcripts source dir | directory picker | `data/transcripts/json/` in this repo | Canonical JSON sources for S0/S2; the rendered `data/transcripts/html/` copy is a display-only render |
| `F-frameworks-dir` | Legal framework source dir | directory picker | `data/law/` in this repo | Source Markdown caches; selected files are copied into `<bundle-dir>/Legal framework` |
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
| | `LLM_MAX_TOKENS` | `16000` | number |
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
**→** `write_source_into_bundle(root: Path, kind: str, source_name: str, data: bytes) -> Path`
**→** MCP: `copy_source_into_bundle_tool(source_path, bundle_root, kind)`
**→** Bridge: `POST /api/bundle-source` (what the page actually calls)

Both helpers funnel through **one** destination rule, `staged_source_path(root, kind, name)`, and the bridge calls it before the write as well as during it — so the path the page *shows* is computed from the same list the copy uses. Two rules is how a preview comes to disagree with the write it previews.

`kind` MUST be one of the `BUNDLE_LAYOUT` keys — a closed enum. The 10 values, and what each one means for a staged source:

| `kind` value | Destination inside the bundle | Shape |
| --- | --- | --- |
| `violation_main` | `{violation_id}.json` | file — the source replaces it |
| `contract` | `contract.json` | file |
| `manifest` | `MANIFEST.txt` | file |
| `readme` | `Violation bundle/README.md` | file |
| `validation_report` | `Validation/validation_report.md` | file |
| `validation_checks` | `Validation/checks.json` | file |
| `element_grid` | `Schema/element_grid_{violation_id}.json` | file |
| `transcripts_dir` | `Transcripts/<source name>` | folder |
| `framework_dir` | `Legal framework/<source name>` | folder |
| `authority_sources_dir` | `Authority sources/<source name>` | folder |

Which keys are folders is declared in `pack.SOURCE_DIRECTORY_KINDS` and published to the page as `schema.source_directory_kinds` (pinning test: `tests/test_pack_layout.py`). It is **not** inferred from "the template has no suffix": that would silently misplace a future folder named `Legal framework.v2`. A file key's destination ignores the name it was handed — `contract` has exactly one home.

**User inputs**

| ID | Label | Type | Required | Notes |
| --- | --- | --- | --- | --- |
| `F-s0-source` | Source file | **file drop zone + picker + upload** | yes | Any file; name is preserved for folder kinds |
| `F-s0-kind` | Destination | select (10 values above) | yes | Also moves where the picker opens |
| `F-s0-bundle-root` | Bundle root | read-only, derived | yes | `build/<violation_id>/` |

**Behaviours — shipped**

- **File picker (browse).** Opens at the root `GET /api/sources` reports for the chosen destination (`data/transcripts/html` for `transcripts_dir`, `data/law` for `framework_dir`), and never at the workspace root — that mismatch is what made a file picker impossible to open. Shortcut buttons switch destination *and* root together. The picker is **navigation + selection** only: choosing a file highlights it, `Stage this file` stages it.
- **Upload.** `content_base64` + `filename` in one JSON body (deliberately not multipart: this bridge has one body parser and one error shape). 16 MiB limit; base64 is decoded through `decode_base64_payload`, and the error is the client's (400), not a traceback.
- **Drag-and-drop.** One file at a time; dropping on `#s0DropZone` stages it, dropping anywhere else is refused with a log line rather than navigating the page away.
- **Destination is shown before the copy** — computed from `staged_source_path`, so it is the real path and not the request's claim.
- **Overwrite is reported, not silently performed.** The response carries `overwritten: true|false` and the page pushes a warning note. A staged source is proof; replacing one unnoticed is the edit a reviewer finds long after the quote it backed.
- **`sha256` of the staged bytes** is returned by the route and shown in the note, so S2/S3 and V02/V03 can compare against it (and against `MANIFEST.txt`) instead of trusting that a copy happened.
- **A refusal writes nothing.** Every 400/404 leaves the bundle byte-for-byte as it was (asserted as its own test, because "returned 400" and "wrote nothing" are different claims).
- Staging a file key does **not** leave a directory of that name behind. It used to: `copy_source_into_bundle` created a folder from the layout template for every key, so staging into `contract` produced a `contract/` directory beside the real `contract.json` — the same fact stored twice, which a manifest hash cannot see.
- **A staged write never travels through a symlink.** Both writers open the destination for writing, which resolves a link: with the real bundle convention (`build/CL-030/Legal framework/CPCL.md -> ../../../data/law/CL/CodigoPenal.md`, and `Transcripts/*.json` in the INT/BR bundles) staging a source whose basename collides rewrote the *corpus* file and then reported the bundle path with the corpus file's hash. `clear_linked_destination` unlinks a link at the destination first, so the bundle gets a real file and the file the link pointed at is untouched. A real file at the destination is still the ordinary replace case; a directory is left alone so the writer raises rather than discarding a tree.

**Behaviours — specified but NOT implemented** (kept here so the gap is visible, not so it reads as done)

- Multi-file drag-and-drop with a `(source, kind)` row per file. The page stages one file per request and renders the staged set as read-only rows.
- Auto-suggesting `kind` from file type (`*.html` + `transcript-segment` → `transcripts_dir`, `*.md` + `### Art.` → `framework_dir`, …). The reviewer picks the destination by hand.
- Pre-copy *confirmation* on overwrite. The page reports the replacement afterwards.

**Failure modes.** Source missing/unreadable; `source_path` outside the workspace or not a file (400 — containment is lexical, checked before resolution, so a repo-owned symlink like `data/law` stays reachable); `kind` not in `BUNDLE_LAYOUT` (400, and the response lists what it accepts); `violation_id` that is a path or a bundle absent from disk (400/404); upload over the limit or with no usable `filename` (400).

**Gate.** At least one transcript and one framework staged, or an explicit "continue without" acknowledgement. *Not yet enforced by the page* — the step is currently advisory.

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

**Purpose.** Anchor verbatim transcript quotes to real transcript artifacts, producing segments with hashes and audio offsets. This is what makes V01/V02 meaningful.

**→** `build_evidence_layer` / MCP `build_evidence_layer_tool`
**Signature:** `build_evidence_layer_tool(violation, transcript_path, transcript_source_id, transcript_bundle_uri, segment_specs)`

#### The two transcript corpora (read this before touching S2)

Both corpora ship the same 29 transcripts under the same filenames, but **they do
not share an id space**:

| Corpus | Reader | `source_id()` | Composed `segment_id` |
| --- | --- | --- | --- |
| `data/transcripts/json/*.json` | `JsonTranscriptSource` | the document's `transcript_id` | `I-002_01_NAR-01_STG_1_pre_boarding.seg-7` |
| `data/transcripts/html/*.html` | `HtmlTranscriptSource` | a display label parsed from the filename (`STG-1`) | `STG-1.seg-7` |

`layers.build_evidence_layer` composes `f"{source_id()}.{local_id}"`. Only the
JSON corpus yields ids byte-identical to `segments_manifest.json` and to the
violation JSON's `segments[].segment_id`; the HTML render's ids join nothing. So:

- the picker is fed from the **canonical JSON corpus** (via `/api/sources`'
  `transcripts_json`), not the render;
- `_transcript()` dispatches on the file's own suffix, and for a JSON transcript
  it **ignores** the caller's `transcript_source_id` — the canonical id comes
  from the document, so a typed label cannot shift the composed id;
- `segment_specs[].segment_id` is always the transcript-**local** form (`seg-12`),
  never the scoped one — `layers.py` composes the scope itself.

The render stays selectable for eyeballing a transcript, and the picker labels
it `render only` with a warning that marks off it will not join.

**User inputs**

| ID | Field | Type | Required | Notes |
| --- | --- | --- | --- | --- |
| `F-s2-transcript` | `transcript_path` | **file picker** (`.json`, `.html`) | yes | Discovered from `data/transcripts/{json,html}/` by the UI; the bridge accepts only discovered relative URIs |
| `F-s2-source-id` | `transcript_source_id` | text, **read-only** | yes | e.g. `I-002_01_NAR-01_STG_1_pre_boarding`. Derived, never typed: filled from the loaded transcript's `transcript_id` (canonical JSON) or filename label (HTML render). Still *sent* because the HTML reader needs it — the JSON reader ignores it and composes the prefix from the document. No code reads it back, so it is display only |
| `F-s2-uri` | `transcript_bundle_uri` | text | no | Bundle-relative, e.g. `Transcripts/I-002_01_NAR-01_STG_1_pre_boarding.json#seg-7` |
| `F-s2-specs` | `segment_specs` | repeatable table | yes | see below |

The browser calls `GET /api/source-transcript?uri=<data-relative-uri>` when
the selection changes. The returned parsed segments replace the segment list;
marking a row builds the corresponding `segment_specs` entry without asking the
user to retype offsets, speaker, or verbatim text. Rows that the pack already
cites are badged (`manifest` / `anchored` / `refined`) so the browser shows the
bundle's own evidence rather than an undifferentiated corpus dump.

Settings and S0 Browse controls use `GET /api/browse?path=<workspace-relative-path>&kind=directory|file`.
The server rejects absolute paths and traversal outside the repository root.
Containment is checked **lexically, before** the path is resolved, because
`data/law` and `data/transcripts/html` are repo-owned symlinks that leave the
workspace by design — resolving first made `data/law` unreachable. `kind` says
what the caller may **pick**, not what the path must already be: every picker
opens on a directory, so a directory is listed for either `kind`, and only a
resolved *selection* is checked against `kind`.

S0 stages a chosen or dropped file with `POST /api/bundle-source`, whose
`violation_id` + `kind` resolve the destination through `pack.staged_source_path`
(the same rule the copy uses). See §S0 for the request shapes and the refusals.

**Filename → `source_id` inference** (HTML render only — the JSON reader reads
`transcript_id` out of the document itself, which is the authoritative source):

| Filename pattern | Inferred `source_id` |
| --- | --- |
| `timeline_aeropuerto_(STG_\d+)\.html` | `STG-N` |
| `timeline_aeropuerto_arturo_merino_benitez_(\d+)\.html` | `STG-N` |
| `timeline_latam_STG_(\d+)\.html` | `LATAM-N` |
| anything else | file stem |

**Segment spec table** — each row is one segment the user wants to pull in:

| Column | Type | Required | Notes |
| --- | --- | --- | --- |
| `segment_id` | text | yes | **transcript-local form `seg-12`**. `layers.py` composes the scoped `<transcript_id>.seg-12` id itself |
| `role_in_argument` | text | no | e.g. `fact`, `admission`, `contradiction` (defaults to `legacy_fact` in the normalizer) |
| `translation_en` | textarea | no | English rendering; falls back to verbatim |
| `transcription_notes` | textarea | no | — |

Marking a row never invents these: if the bundle's manifest or violation JSON
already holds the segment, its own `role_in_argument` and `translation_en` are
reused. The old handler defaulted `translation_en` to the Spanish verbatim,
which wrote Spanish into an English field.

**Read-only, derived, and shown live after the call** (this is the key feedback loop):

| Derived | Source |
| --- | --- |
| `audio_offset_start` / `audio_offset_end` | parsed from the segment record's own offsets |
| `speaker` | parsed from the segment record |
| `verbatim_es` | parsed from the segment record — **never hand-typed** |
| `verbatim_sha256` | `sha256(verbatim_es)` |
| `source_uri` | `<bundle_uri>#<local_id>` |
| `source_sha256` | `sha256` of the transcript artifact bytes |

**The pack evidence manifest.** `segments_manifest.json` is the converter's own
record of every segment a built pack cites, and `/api/bundle` already serves it
(`artifacts_present.manifest`). S2 parses it into its own block, because it is
the only artifact that carries:

| Field | Why it matters |
| --- | --- |
| `segment_id` | the canonical join key against the violation JSON |
| `legacy_segment_id` | the vault id the segment was re-anchored from — recorded nowhere else |
| `refinement_added_segments` | ids with no vault ancestor, so they appear on no source segment |
| `role_in_argument`, `verbatim_es`, `translation_en` | the role and both texts, per segment |
| `transcription_notes` | the anchor's own note |
| `transcript_files` | `transcript_id → filename`, which is what makes a per-transcript seed possible |

Join on `segment_id` only. The manifest's `verbatim_es` drops accents the
violation JSON keeps (`avion` vs `avión`), so a text-equality join reports
mismatches for segments that are in fact the same one. Report drift both ways:
in the manifest but absent from the violation JSON, and vice versa.

Because `build_evidence_layer_tool` takes **one transcript per call**, the
manifest's 35 rows across 5 source files are really 5 calls. Each transcript's
rows get a seed control that writes that transcript's specs, and the args builder
sends only the specs belonging to the picked transcript — local ids carry no
scope, so sending another transcript's id composes an id that anchors nothing.

**Behaviours**

- **Segment browser.** Before adding, let the user browse the parsed transcript (all segments with timecode, speaker, text) and tick rows to build `segment_specs`. This removes the main source of error (`segment_id` typos). Marks are keyed by scoped id, so switching transcripts does not discard them — a manifest-seeded run spans several files at once.
- **Seed from the manifest.** Seeding is a copy out of the manifest, never a guess off a corpus file: the manifest already holds the role and the English rendering for every segment it declares, and the 30 `refinement_added_segments` exist in no transcript file at all.
- If a segment ID is not found, the record is still kept but rewritten as an **unanchored legacy record**: `source_uri = legacy://{violation_id}/{segment_id}`, `transcription_notes += " | legacy-unanchored"`, and audio offsets attempted via `_parse_time_seconds` (`"12.80s"`, `"15:16"`, floats all supported). The UI must flag these rows red — they will fail V01.
- Empty `verbatim_es` on a resolved segment is back-filled from the supplied legacy text (a real behaviour of the normalizer) — surface this as an info note, not an error.

**Failure modes.** Transcript file missing/unreadable; a JSON transcript that fails its schema (`JsonTranscriptSchemaError`) or an HTML render that does not match the expected `transcript-segment` template → zero segments parsed; handle with "template not recognised" guidance rather than a stack trace. A bundle with no `segments_manifest.json` is not an error — say so and fall back to the violation JSON's own segments.

**Gate.** ≥1 anchored segment (a segment whose `source_uri` is not `legacy://…`), reported alongside the manifest's declared count and any drift in either direction.

---

### S3 — Layer 2: Norms (cached articles)

**Purpose.** Attach the legal articles that the violation invokes, with verbatim excerpts verified against the framework Markdown, plus candidate (unverified) articles.

**→** `build_norms_layer` / MCP `build_norms_layer_tool`
**→** candidates: MCP `review_candidate_articles_tool`, then `apply_candidate_review_tool` (both read-only — the write is S11's `write_violation_json_tool`)
**Signature:** `build_norms_layer_tool(violation, framework_path, framework_code, framework_bundle_uri, article_specs, candidate_specs=None)`

**User inputs**

| ID | Field | Type | Required | Notes |
| --- | --- | --- | --- | --- |
| `F-s3-framework` | `framework_path` | **file picker** (`.md`) | yes | Pre-filled from staged `Legal framework/*.md` |
| `F-s3-code` | `framework_code` | text, **read-only** | yes | Derived, never typed: filled from the selected framework file (`c.framework_code`), e.g. `CHIPENCOD`, `CPCL`, `CP`. Backend default when suggested: `md.stem.split("_")[0].upper()`. Still *sent* — it is a real tool argument, just not hand-entered |
| `F-s3-article-id` | — (display only) | text, **read-only** | n/a | Mirrors the established article's `article_id` from the bundle, e.g. `CL.CPCL.C1.Art.255`. Not a top-level tool argument — established-article data travels inside `article_specs`, so nothing reads this back |
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

- **Article picker.** The chips come from the selected framework cache's own `articles_cached` list — the numbers the cache really holds, not a re-parse of the markdown. They are **buttons**: clicking one loads that article's cached body into `verbatim_excerpt` and its declared id into the read-only `article_id` field, over `GET /api/framework-article?uri=build/<violation_id>/Legal%20framework/<name>.md&article=255`. Nothing is typed, so the excerpt cannot fail the byte-exact substring check by a transcription slip. The id is taken from the cache's own `**ELI ID:**` declaration and is **never reconstructed** from the article number: the hierarchy segments (`C1`, `T2.P6`) are not derivable from `Art. 412`. If a cache declares no `**ELI ID:**` line the field stays empty rather than showing an invented id.
- **One article on screen at a time.** The chip highlight, the id and the excerpt are rendered from a single rule (`pickedArticleFor`): the picked article while it still belongs to the selected framework's cache, otherwise the bundle's established article. Re-hydrating the panel re-applies the pick instead of reverting it, and switching framework falls back to the established article rather than leaving a foreign excerpt under an empty chip row.
- **Lookup semantics to mirror:** exact identifier match first, then a spelling-insensitive match (`269 ter` ≡ `269_ter`), then a prefix match on `N ` or `N.` (so `133` matches `133 A` only if `133` itself is not cached). Every accessor resolves through this one rule, so a body, its declared ELI id and its title can never resolve to different articles.
- **Only the bundle's own cache is addressable.** `GET /api/framework-article` accepts exactly `build/<violation_id>/Legal framework/<name>.md` and refuses a discovered-but-uncached framework under `data/law/`: the bundle does not carry that file, so an excerpt read from it could never pass validation. Containment is checked on the raw path parts (never on a resolved path) because every `build/<id>/Legal framework/*.md` is itself a symlink.
- **Live excerpt verification.** Show, per row: ✅ *excerpt found in cache body* / ❌ *not a substring* / ⚠️ *article body not in any cache*. This is exactly the demotion logic in the normalizer.
- **Demotion rule.** If an article cannot be verified, the library **demotes it to a candidate** with `framework_cache_status="not_in_bundle"` and a `verification_required` hint. The UI should offer a one-click "demote to candidate" action for rows it already knows will fail, rather than letting the round-trip surprise the user.
- **Framework cache provenance** is computed, not entered: `cache_file`, `cache_file_sha256`, `cache_self_reported_sha256` (from a `**Sha256:**` header if present), `cache_fetched_at`, `articles_cached`. Display these read-only. Note that `cache_self_reported_sha256` is the hash of the **upstream document named by `cache_source_url`**, not of the cache file itself — a file cannot contain its own SHA-256, and no cache in this corpus satisfies the comparison. V03 therefore reports a mismatch as an INFO note and never warns on it; what V03 actually enforces is that `cache_file_sha256` (the real bytes) still matches the live file.

**Failure modes.** `framework_path` unreadable; no `### Art.` headers found → "cache format not recognised"; excerpt present but article body missing.

**Gate.** ≥1 established article verified in-bundle.

#### Candidate review (secondary, on the established block)

A candidate is a citation the bundle *invokes* but has not *established*: the
excerpt is missing, the text may not say what the model assumed, and nothing
verifies it. The **Review candidates** button sits in the `block-title-row` of the
**Established articles** block, which is where the candidate list is rendered, so
the two record sets are read together.

**Data source, decided before any model call.** `GET /api/candidate-reviews`
looks for `data/candidate-reviews/<violation_id>.candidates.review.md` and parses
it if present (`source: ready_made`). It calls an LLM only when that file is
missing or empty (`source: generated`), and the generated markdown is rendered in
the same shape so it can be saved as a review file and re-read later. Review files
live **outside** the bundle: they are *about* a bundle, not part of it.

**The three decisions.** Each reviewed candidate becomes one proposal, and only
three actions exist (`candidate_review.py`, closed set):

| Action | Effect on the candidate |
| --- | --- |
| `keep` | untouched — the default for a `correct` verdict or an unreviewed candidate |
| `annotate` | appends a `Candidate review:` line to `history_note` and one verification step |
| `withdraw` | removes it from `candidate_articles` |

The review's own recommendation pre-selects the select (`incorrect`/`withdrawn` →
`withdraw`, `uncertain` → `annotate`, `correct` → `keep`), and **the reviewer can
override every one of them**: the review advises, the human decides.

**Two rules the UI must keep.**

- **The candidates, not the table, are the subject.** The proposal list is built
  by iterating `candidate_articles`. A row naming an article the bundle holds as
  *established* is ignored (the real CL-030 review lists three of them), and a
  candidate no row covers is shown as `not reviewed` rather than dropped — "the
  review did not mention it" and "the review cleared it" are different facts.
- **Confirm never writes.** `apply_candidate_review_tool` returns the updated
  `Violation` and nothing else; the UI hands that result to the same persistence
  path as every other S3 edit. So a reviewer who closes the modal instead of
  confirming has changed nothing on disk, and the confirm-twice case re-applies to
  an identical record: it reports a keep and appends no provenance entry.

The three candidate fields an annotation may touch are `history_note`,
`verification_required` and `preliminary_view`; `candidate_name` is the display
name. Nothing promotes a candidate to `established_articles` — that requires a
byte-exact excerpt verified in S7 and is deliberately not offered here.

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
| `proof_evidence_segments` | multi-select | no | pick from S2 segment IDs — stored **scoped** (`<stem>.seg-N`), see below |
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

#### The rendered grid (implemented)

**`seg-36` alone is not an identifier.** The bundle stores `proof_evidence_segments`
entries **scoped by transcript stem** — `I-002_05_NAR-07_STG_7_post_removal_investigation.seg-36` —
because bare `seg-N` numbers repeat across every transcript in a multi-transcript
bundle. The grid must therefore say *which* transcript each column came from, and
the two helpers that make the id legible are:

| Helper | Contract |
| --- | --- |
| `segmentTranscript(id)` | split on the **first** dot only; the local part may itself contain dots. Returns `""` when there is no scope (a bare `seg-1`). |
| `transcriptLabel(stem)` | `<incidence> · <render label>`, e.g. `05 · STG-7`. **Display-only, not a key** — see the uniqueness warning below. |

**The group header is keyed on `segmentTranscript(id)`, never on `transcriptLabel`.**
`STG-N` is *not* unique: two different files in `build/` both render as `STG-2`
(`I-002_02_NAR-02_STG_2_boarding_gate`, `I-002_18_NAR_LATAM_STG_2`). Grouping on the
rendered label silently merges them into one column-group of the wrong size. The
`<thead>` is two rows: a transcript group row (`colspan` per group, full scoped id
in `title=`) over a per-segment row of local ids — so the ordinal disambiguates for
the eye and the full id disambiguates in the data.

**The dot and the proof badge are `<button>`s, not decoration.** Each `cell-on` cell
holds `button.dot-btn` (`data-action="open-segment"`, `data-element=`, `data-segment=`),
and each element row carries `button.proof-hit` (`data-action="open-proof"`). Both
dispatch to one `openEvidenceModal()` — the element *without* a segment opens the
proof statement, the dot opens the segment *inside* that element. Using a `<span>`
would make every marker invisible to the keyboard, and dropping `data-element` from
the dot still "looks right" while the modal opens a segment with no proof attached.

**The modal reads the canonical corpus first.** `segmentDetail(id)` resolves text in
this order and the order is load-bearing:

1. `loadTranscriptDocument(...)` → `data/transcripts/json/<stem>.json` through
   `API.transcript(` — the canonical corpus. Cached in `state.transcriptDocs`.
2. the violation JSON's own `verbatim_es`;
3. `segments_manifest.json` — **last**: the manifest is the record known to drop accents.

The modal keeps its own cache and must **never** read through `state.activeTranscript`.
That is S2's form state; reading a segment through it would move the S2 picker every
time a reviewer tapped a dot mid-edit.

**`differs_from_violation` is compared on collapsed whitespace, never raw.** The corpus
trims every segment while the bundle's `verbatim_es` keeps the trailing space, so a bare
`!==` reports a transcription dispute on segments that say exactly the same thing.
Measured across every bundle in `build/`: **7189 segments agree byte for byte and only
2 disagree** — both CL-030, `seg-300` and `seg-301`, differing by a trailing space
alone, and one of them is reachable from this grid. The banner says the two records
disagree by *more than spacing*, and names neither as preferred.

> **Corpus file shape.** `data/transcripts/json/*.json` uses `index` / `text` /
> `start` / `end` — **not** `segment_id` / `verbatim`. Joining a grid segment to its
> text must go through `violation_pack.mcp_server._transcript(...)`, which composes
> `segment_id` and exposes `verbatim`; reading the file directly raises
> `KeyError: 'segment_id'`.

---

### S5 — Layer 4: Nexus matrix

**Purpose.** Record the fact ↔ norm ↔ element links that make the argument explicit, with a strength rating.

**→** `build_nexus_layer` / MCP `build_nexus_layer_tool`
**Signature:** `build_nexus_layer_tool(violation, entries)`

**User inputs**

| ID | Field | Type | Required | Allowed values |
| --- | --- | --- | --- | --- |
| `F-s5-fact` | `fact_id` | select (S2 segments) | yes | **scoped** `<transcript_id>.seg-N`; the option text is qualified, see below |
| `F-s5-norm` | `norm_id` | select (S3 articles) | yes | — |
| `F-s5-element` | `element_id` | select (S4 elements) | yes | — |
| `F-s5-type` | `nexus_type` | text/select | yes | e.g. `proves`, `supports`, `contradicts` |
| `F-s5-strength` | `strength` | **select** | yes | `high` \| `medium` \| `low` |
| `F-s5-rationale` | `rationale_oneline` | text | yes | one line |

**Behaviours.** The three selects must be populated from state, never typed. Show a coverage matrix: any segment not cited by a nexus row, any element with no incoming nexus, any article with no nexus — these are the gaps the reviewer wants to find. V06/V07 consume this.

#### A segment select must name the transcript

`seg-11` is a segment of *every* transcript in the bundle, so a bare local id is
not a label. Measured on `build/CL-030`: 34 unique nexus `fact_id`s drawn from 5
transcripts, and `seg-11` is in two of them (`05 · STG-7` and `03 · STG-5`) — both
rendered as `seg-11`, which makes choosing a coin flip while the two rows are
different parts of the recording.

Every call site that shows a segment goes through `segmentOptionLabel(id)`, which
is `transcriptLabel(segmentTranscript(id)) · localSegmentId(id)` — e.g.
`05 · STG-7 · seg-36`. It is used by the `s5Fact` picker **and** by the rendered
`#s5NexusRows` ids, because a fixed picker with an unfixed list below it is still
ambiguous.

> **The option's `value` stays the full scoped id.** The pack joins on
> `<transcript_id>.seg-N`, so a picker that *displays* the qualified text but
> *submits* the shortened one would look correct and write a fact that matches
> nothing. An unscoped id has no transcript to name and is returned unchanged,
> rather than rendered as `seg-1 · seg-1`.

Only the *segment* selects are qualified. `s5Element` legitimately uses `shortId()`
— element ids are unique within a bundle, so there is no second id space to
disambiguate them from.

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

> **Implementation divergence (measured).** The three allowed values above are a
> *design proposal*, not a constraint. In `violation_pack/models.py`,
> `Authority.verification_protocol` is declared `str | None` with **no
> validator** — the `Literal` of those three protocol names belongs to
> `VerificationProvenance.protocol`, a different field (V11 validates that one
> against `_KNOWN_PROTOCOLS`). The implemented writer,
> `jurisprudence.py`, puts free prose there:
> `"Qdrant-record=<id>; primary_source_url=<url>"`, which is not one of the
> three literals. `verify_statute_in_bundle` writes
> `"statute_in_bundle_v1; source=…; sha256=…"`. So a `select` restricted to the
> three literals would reject what the library actually produces; either the
> field should be validated as an enum (and `jurisprudence.py` changed to match)
> or this row should be a text input. V16 currently only warns when the field is
> *blank* on a `verified=True` authority, which is all that can be stated
> without settling that question.

**Behaviours**

- The `verification_protocol` select should *drive the S7 form*: choosing `statute_in_bundle_v1` pre-selects the S7 tab and shows the fields that protocol needs.
- Show `verified: false` prominently on every stub. Nothing in the UI should imply a stub is evidence.
- `fabrication_risk_note` is a first-class field — render it as a warning-styled textarea, because it is the guard against LLM-fabricated citations.

**Gate.** Every element with `proof_status` in {`established`, `strong`, `contested`} should be referenced by ≥1 authority `supports` (advisory, not blocking).

#### S6.1 — Attach an official source and verify the stub in place

**Purpose.** Let an operator attach the official document (or its URL) *to the stub it
supports*, have the agent confirm or update the stub from that document, and keep the
document as the proof of the validation. This replaces the "copy the URL into S7" hop:
the artefact is stored under the authority id, so the proof and the stub it proves are
the same record.

**Entry point.** Every authority row in S6 carries a button (`data-action="open-proof-form"`,
`data-authority="<authority_id>"`) opening the proof modal. The modal shows the stub's
proposition, its `supports` elements and its required bibliographic field for the type
(`PROOF_FIELD_LABEL` / `proofPlanFor`), so the operator can see what is still missing
before verifying.

**Three ways to supply the source.** All three post to the same route,
`POST /api/authority-source` (`API.authoritySource`), which stores the document and returns
its text plus a hash; the verify step then calls the protocol tool for the stub's `type`
(`PROOF_PLAN`):

| ID | Control | Notes |
| --- | --- | --- |
| `F-s6-1-url` | Official page (url) | the **server** fetches and stores a copy, so the proof does not depend on the page staying up |
| `F-s6-1-file` | Upload (PDF, saved page, text) | travels as `content_base64` inside JSON — there is no `python-multipart` dependency; the reader is derived from the *served content type* |
| `F-s6-1-paste` | Paste the text | for sources whose file carries no text layer at all (a scanned PDF) or whose reader is not installed |

| `type` | Tool (`PROOF_PLAN[type].tool`) | Required fields |
| --- | --- | --- |
| `statute` | `verify_statute_external_fetch_tool` | `instrument` |
| `jurisprudence` | `verify_human_attested_tool` | `attestor`, `court`, `rol`, `decision_date` |
| `doctrine` | `verify_human_attested_tool` | `attestor`, `author`, `work` |
| `comparative` | `verify_human_attested_tool` | `attestor` |

A stub with no `type` gets no plan, and the verify button is disabled rather than guessing
which protocol to run.

**Reading a PDF needs the `pdf` extra.** `authority_source.py` holds `_PDF_EXTRACTORS` as
`(module_name, callable)` pairs tried in order — `pypdf`, `PyPDF2`, `fitz`, of which only
`pypdf` is declared (the `pdf` extra, and `all`). Without any of them a PDF is still
**stored and SHA-pinned as proof**, but the route reports `needs_text` with a warning
naming `pip install pypdf`, and the modal asks for the passage instead. The registry stores
the *function*, never its name: the first version paired a module name with the string
`"read_pypdf"` and resolved it through `globals()`, so `read_pypdf` vs `_read_pypdf` was a
single underscore between reading a document and a `KeyError` reported as "pypdf is
installed but could not read this PDF" — and because the loop imports the module first and
skips it on `ImportError`, that lookup could only ever run *after* a reviewer had done what
the warning told them and installed one.

**Where the proof lands.** `<bundle root>/Authority sources/<AUTHORITY_ID>__<name>`, plus a
`__…proof.json` sidecar recording `source_uri`, `text_sha256`, `text_chars`, `text_source`
(`fetched` \| `upload` \| `pasted`), `content_type`, `extractor`, `whitespace_collapsed`
and `warnings`. The sidecar exists because `VerificationProvenance` is `extra="forbid"`
with a single `source_uri`; the ingest-time facts have nowhere else to go. Identical bytes
are reused rather than re-written (`artefact.reused`), so re-ingesting the same document is
idempotent.

**The matched text is written down beside the artefact.** When the text is not already the
artefact's own bytes — a PDF, an HTML page, or an upload whose reading disagrees with the
paste — it is stored as a `__…text.txt`, and `text_file` names it. The test is against the
**bytes** (`data != content.encode("utf-8")`), not against the extracted reading: a PDF
that reads *cleanly* has `artefact_text == content`, so asking the reading whether the text
is already on disk answers yes for the one format where the text is certainly not on disk,
leaving `text_sha256` naming a string that exists only inside the PDF and forcing anyone
auditing the bundle to install the same parser to re-derive the hash.

The authority prefix is added to the filename only when it is not already there, so a
reviewer who picks this bundle's *own* stored copy (which is already named
`<AUTHORITY_ID>__…`) re-uses the artefact instead of minting a duplicate under a
double-prefixed name that `_unique_path` cannot recognise by content.

**The verification is not durable until the violation is written.** Every verify protocol
*returns* an updated `Authority` and writes nothing — `write_violation_json_tool` is the
only writer (`pack.py:write_violation_json`). Until it runs, the stub reads as verified
in this page and comes back unverified after a reload. The modal therefore:

1. compares the in-page authority with the copy in the loaded bundle (`proofIsOnDisk`) and,
   when they differ, shows the callout **"In this page only, not in the bundle"** and a
   **Save to the bundle** button (`data-action="proof-save"`);
2. saves by calling `write_violation_json_tool(violation, bundle_root)`, then **re-reads**
   the bundle so the listing and the JSON are read back from disk rather than assumed;
3. the same write happens at S11 "Build package", so either path is sufficient.

Re-reading the listing deliberately refreshes only `state.bundle.files`
(`refreshBundleFiles`) and never `state.violation` — loading the bundle would discard the
unwritten verification the page is there to show.

**Proof on disk.** The modal's footer lists what is already stored for this stub. The set
is `proofArtefactsFor` — a `/Authority sources/` path match **and** the authority id in the
file name — and the fallback when this stub has nothing yet belongs to the listing, not to
the set: `proofArtefactSection` shows the whole directory and labels it *(bundle-wide)*.
Keeping the id test inside `proofArtefactsFor` is what stops one stub's *Delete this source*
button from being offered for another stub's document. The directory row that `/api/bundle`
returns for `Authority sources` is excluded by the trailing slash in that path test — its
own path has nothing after the directory name.

**Replacing a stored source.** Every stored source of *this* stub carries a
**Delete this source** button (`data-action="proof-delete"`), which exists so a stale or
wrong document can be replaced rather than lived with: delete, then attach the replacement.
The three files of a source — the document, its `.proof.json` sidecar and its
`__…text.txt` — are shown and removed as **one** entry, because the two companions are
meaningless without the document: a sidecar left behind names a file the bundle no longer
holds, and would go on claiming a proof that is not there. The grouping is by stem
(`proofStem` in the page, `proof_stem` in the module), which is why `X-2.pdf` — the
neighbour `_unique_path` mints for a same-named upload with different bytes — is a
*different* source and is deleted on its own.

The browser sends **one** file name and the bundle decides the rest
(`POST /api/authority-source/delete`, `delete_source` + `proof_group`). Deleting proof is
irreversible and the bundle may hold the only copy of an official document, so the browser
is not allowed to name the set: it gets the grouping wrong, or sends a name on purpose, and
a file the reviewer was never shown disappears. Two checks stand in front of the unlink,
and both are about *what may be deleted* rather than about the request being well formed —
the name must be a plain file carrying the `<AUTHORITY_ID>__` prefix ingest writes, and it
must resolve inside `Authority sources/`. A name that is a path is **refused, never
normalised**: `Path(name).name` is the right habit for an *upload* (see
`sanitise_filename`) and the bug here, because `sub/<AUTHORITY_ID>__x.pdf` would then be
accepted as the real file.

Two clicks, because the page has no `window.confirm` precedent and a one-click unlink of an
irreplaceable document is the one place a dialog is not enough: the first click arms the
button (`state.proofDelete`), the second is the consent, and the group's own count is on the
button (`Delete 3 files for good`). Arming is matched on the **stem**, so clicking the row
the reviewer can actually read — the sidecar — arms the whole source rather than a fragment.

Removing a source also drops the loaded payload (`state.proofSources[authorityId]`): it was
read out of the file that just went away, and reusing it would hand the protocol a
`source_uri` naming a deleted document and pin a verification to text no bundle holds. When
the stub is already verified, its recorded `source_uri` still names the removed file — the
stub's JSON is only ever written by the write gate — so the modal says so instead of
repairing it silently: *"This stub's verification names …, which has just been removed, so
that record now points at nothing. Verifying the replacement is what repairs it."* A source
fetched by url records the **url**, so nothing matches there, correctly: the local copy is
gone but the page it cites is not.

Removing from disk is not the same as un-verifying: nothing in the page clears `verified`.
A stub whose proof was deleted and not replaced goes to S6 with its verification intact and
a provenance pointing at a file that is no longer there.

**Reading the loaded text, and what a refusal means.** The modal shows the verdict and the
text together, because the two questions a reviewer has when a quote is refused — *what is
in there* and *why did it not match* — are answered by the same pane. Three details are
load-bearing:

1. **The pane is not truncated into uselessness.** Verbatim matching is a plain
   `content.indexOf(quote)`, so the passage a reviewer is being asked to quote can sit
   anywhere in a document of any length (the ingest cap is 8 MiB). When a quote cannot be
   marked, the pane shows the loaded text up to 200,000 characters and says how many more
   there are (`highlightQuote`). The first version capped the *unmarked* view at 3,000 and
   so hid the very passage the refusal was about — the CL-030 sentence it asks for sits at
   offset 3,473 of a 32,302-character reading.
2. **A refusal explains itself.** `proofRefusalNote` names the two causes that are *not*
   the wording. It is only consulted when the quote is absent, so the matched case can
   never reach it:
   - the quote came from a **different source** than the one now loaded. Provenance is per
     *verification*, so a stub's `matched_quote` may be a string found in the source the
     stub was previously verified against, and the box is prefilled from `matched_quote`.
     Attaching a replacement document therefore hands the reviewer the old document's
     sentence — and a quote is evidence only about the document it was found in, so a
     translation is never verbatim. The note names the old and the new `source_uri` and
     says the box holds it because the stub does;
   - **every word is in the text, but not in a row.** A reading can drop page furniture
     *inside* a sentence: CL-030's DTO-100 splits `establecer siempre las garantías de un
     procedimiento y una investigación racionales y justos` with the amendment annotation
     `26.08.2005`. The protocol cannot match across the interruption, so the note asks for
     a run that reads continuously instead.
3. **The required fields are filled from the stub.** `instrument` is required for `statute`
   and is present on the authority, so leaving the box blank refuses a quote that *is*
   verbatim — a refusal about a different thing entirely. The modal fills every field the
   plan asks for that is still empty from the authority (`decision_date` sliced to date
   precision) and never overwrites what the reviewer typed.

The pane is the expensive half of that render and `renderProofSource` runs on every `input`
event in the quote box, so the loaded text is escaped and handed to the DOM once per
*change* rather than once per keystroke: `state.proofPreview` holds `{id, content, quote}`
and a render whose three fields are unchanged writes only the verdict (`proofPreviewIsStale`).
The verdict is deliberately *outside* that guard — it is the half that always changes while
the reviewer types, and a stale pane must not be able to swallow it. The comparison is by
reference, which is exact here: the string in `state.proofSources` is the one the server
hashed, not a copy rebuilt per keystroke.

The converse also holds: a verdict is a statement about a **loaded** text, so it may not
outlive it. When a source is deleted the pane is emptied and re-rendered, and the no-source
branch of `renderProofSource` now writes the neutral prompt back into `#proofMatch` — the
same string the modal's own markup ships, held once as `PROOF_NO_SOURCE` so the cleared line
and the initial line cannot drift apart — and writes it *not* as an error. Without that, the
modal kept showing the last verdict (`Found verbatim at offset 98.`) over an empty pane, for
a document no longer loaded.

**Live check (2026-09-15, delete then replace).** A scratch bundle holding 9 files (one
source, its `-2` same-name sibling, and a second stub's proof) against the running server:
`POST /api/authority-source/delete` named by the **sidecar** removed exactly the three files
of that stem (99,715 bytes), left the `-2` sibling and the other stub's proof alone, and
re-storing the same 66,670-byte PDF reused the same names with `reused: false` — the proof
really went and really came back. Eight refusals (a path, `./name`, `../…`, another stub's
file, an unknown name, a blank authority id, a missing bundle, a non-string name) all
answered 400/404 with the directory byte-for-byte unchanged. In the page: one button per
source naming the document, arm → *Delete 3 files for good* / *Keep them*, cancel disarms,
confirm reports *"Removed 3 files (97.4 KB freed)…"* and the page's own file list drops to 0.

Note on the 2026-09-15 live check above: the uploaded-PDF source it describes is no longer in
`build/CL-030/Authority sources/` — the three `CL.CPR.Art.19.N3__DTO-100_03-MAY-2023.*` files
were removed through `delete_source`, the package's only `unlink()` site (every delete test
runs against a throwaway workspace), leaving the four tracked `CL.DOCTRINE.ETCHEBERRY__*` files.
The paragraph records what was measured, not what is on disk today; re-uploading the same
document restores the same names and hashes.

**Live check (2026-09-15).** BR-001's doctrine stub, pasted text (123 chars, offset 64):
verify → callout + Save → `build/BR-001/BR-001.json` on disk carries `verified: true`,
`verification_protocol: human_attested_v1; source=…; sha256=…` and the full provenance →
reload shows the stub still verified.

**Live check (2026-09-15, a refusal diagnosed on real data).** CL-030's `CL.CPR.Art.19.N3`
stub with the official 97,608-byte `DTO-100_03-MAY-2023.pdf` attached through `F-s6-1-file`:
the box was prefilled with `The legislator must always establish the guarantees of a
rational and just procedure and investigation.` and the modal refused it. The refusal was
**correct**. That sentence is what the stub's *previous* verification recorded —
`statute_in_bundle_v1` against `Legal framework/CONST.md`, offset 3,687 of a 9,767-character
file — while the protocol the stub now runs is `statute_external_fetch_v1` against a
document that does not contain it. Re-run through the page's own `renderProofSource` against
the document's 32,302-character reading, the three messages come out in order: the "came
with the stub, not from this document" note for the English sentence; "every word of this
quote is in the loaded text, but not in a row" for the sentence as the law writes it (split
by `26.08.2005`); and `Found verbatim at offset 3535` for `garantías de un procedimiento y
una investigación racionales y justos`. The `Instrument` field — required for `statute` and
present on the stub — was blank before this change, so the *same* quote would have been
refused twice over.

Four tests cover it, each with its negative branch: a quote with a word missing outright
must *not* be explained as scrambled, and a quote the reviewer typed must *not* be presented
as the stub's. Three mutations reintroduce the memo's defect in each direction — rebuilt
every keystroke, keyed on the source alone, and hoisted above the verdict — and all three
are caught; two more cover the cleared-pane reset (dropped, and written as an error) and are
caught as well. Worth remembering when reading the live evidence: a **pasted** passage *is* the
matched text (`content = pasted or artefact_text`), so a reviewer who pastes the quote to
get past a refusal makes it match at offset 0; the sidecar stays honest about it
(`text_source: "pasted"`, `text_chars: 121`, and the artefact's own `sha256`), and the
metadata line under the verdict reads `pasted text · 121 characters`.

**Live check (2026-09-15, uploaded PDF).** CL-030's `CL.CPR.Art.19.N3` stub, the official
66,670-byte `DTO-100_03-MAY-2023.pdf` (Decreto 100, BCN/leychile) uploaded through
`F-s6-1-file` against the running server: the modal reports
`Found verbatim at offset 498. / uploaded document · read with pypdf · 31303 characters ·
sha256 f104f71e4db9…`, the sidecar flips from `needs_text: true, text_chars: 0,
extractor: null` to `needs_text: false, text_chars: 31303, extractor: "pypdf",
warnings: []`, and `text_file` names a `__…text.txt` on disk whose SHA-256 equals the
recorded `text_sha256` — so the proof is re-checkable without a PDF parser. Re-ingesting
the same document leaves the directory at 9 files: no duplicate artefact.

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

### S10 — Validation V01–V17

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

**The seventeen checks — render each with its semantics so pass/warn/fail is interpretable:**

| ID | Name | Pass / Warn / Fail semantics |
| --- | --- | --- |
| V01 | `segment_resolution` | fail when a segment does not resolve against its transcript |
| V02 | `verbatim_quote_match` | fail when a verbatim quote is not byte-for-byte in the transcript HTML |
| V03 | `article_text_hash` | **fail** when `cache_file_sha256` no longer matches the live cache file, or an excerpt is not a substring of the cache body; the `**Sha256:**` header describes the *upstream* document (not the cache file), so a mismatch there is reported as INFO — never a warning |
| V04 | `article_exists_in_framework_cache` | fail when a cited article is absent from every cache |
| V05 | `cross_references_resolve` | **warn** when there is no bundle-level index to resolve against |
| V06 | `element_coverage` | fail when an established article has no element grid / no coverage |
| V07 | `authorities_verification` | warn/fail on unverified or unbacked authorities |
| V08 | `contract_consistency` | accepts the legacy `violation_number` alias; a purely numeric contract confidence is treated as a **legacy warning**, not a failure |
| V09 | `language_consistency` | fail on inconsistent language fields |
| V10 | `confidence_derivation` | fail when confidence is missing / not derivable |
| V11 | `enrichment_integrity` | includes the known warning `W_AUTH_DANGLING_SUPPORT` |
| V12 | `speaker_attribution` | **warn** when a cited segment's `speaker` is not a label its own source declares; sources with no participant record are skipped |
| V13 | `evidence_nexus_coherence` | **warn** when a nexus row cites a segment its own element does not list in `proof_evidence_segments` |
| V14 | `dead_weight_articles` | **warn** when an established article's grid scores 0 and only dilutes the weighted mean; articles scoring ≤ 0.2 are reported in a passing check |
| V15 | `verbatim_hash_integrity` | fail when `verbatim_sha256` is not the digest of the `verbatim_es` beside it |
| V16 | `authority_verification_coherence` | **fail** when `confidence.authorities_verification_factor` contradicts its own derivation (V10 only compares `confidence.value`); **warn** when an unverified stub leaves both `research_query` and `proposition_to_verify` blank, when a verified authority's pinned `source_sha256` no longer matches the cached framework it was verified against, or when a verified authority leaves `verification_protocol` blank (the prose counterpart of `verification_provenance.protocol`, which no other check reads) |
| V17 | `cross_view_consistency` | **fail** when `open_questions` or `cross_references` disagree with `contract.json`; **warn** when no contract view is supplied. Optional fields are compared with nullability read from the model, so `null` vs `""` is not drift; `related_violations` and edge reciprocity are deliberately not asserted (corpus facts, not per-bundle invariants) |

**Outputs.** `ValidationReport(pipeline_version, ran_at, violation_id, checks)` plus `report.summary` = `{total, pass, warn, fail}`.

**Known-good reference result** (from the demo bundle — use this as a smoke test for the UI):

```
Confidence: 0.74
{'total': 17, 'pass': 12, 'warn': 5, 'fail': 0}
warnings: V03, V05, V07, V11 (W_AUTH_DANGLING_SUPPORT), V17 (no contract view)
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
| `F-s11-backup` | `write_backup` | toggle | **on** | writes `<id>.json.bak` on every run, holding the *previous* generation; the loader reads the live `<id>.json` first and falls back to the `.bak` only when it cannot be read |
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
| Ingest framework | `markdown_path` — **file picker (.md)** | `framework_code` (**read-only**, derived), `framework_name` (defaults to code), `batch_size` (64) |

**Behaviours.** Show a progress bar from the batch counters; `sleep_between_batches` is a rate-limit knob and should have a tooltip saying so. `framework_code` is rendered **read-only** and filled from the loaded bundle's `framework_caches`: it is the code the ingester keys the collection on, so a typo silently splits one framework across two collections. When the bundle carries no cache the field shows a discovered framework's code instead, and the backend's auto-suggest rule (the same `stem.split("_")[0].upper()` as S3) remains the fallback. The neighbouring cache-file field stays editable free text — it names a path, not a code. `readonly` is used rather than `disabled`, so the value stays selectable and `readStepForm()` still collects it.

---

### S14 — Introspection & catalog

| Action | MCP tool / CLI | Output to render |
| --- | --- | --- |
| Embedder info | `embedder_info_tool` | active embedder name (e.g. `hash-384`, `ollama-bge-m3`) + dimension |
| LLM provider info | `llm_provider_info_tool` | resolved provider + model |
| MCP catalog | `violation-pack-catalog --format catalog` | server entry: name, transport, command, env, optional env, 41 tools with tags |
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
| `segment_id` | string | scoped `SRC.local`, where `SRC` is the transcript's `transcript_id` |
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
9. **Backups.** When a step rewrites `<id>.json`, honour the `write_backup` semantics: snapshot the outgoing file to `.bak` first, then read `.bak` only when the live file cannot be read — never in preference to it.
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
    ├── CL-005.json.bak                previous generation (refreshed each run; read only if the live file is unreadable)
    ├── contract.json                  contract
    ├── MANIFEST.txt                   manifest
    ├── Violation bundle/README.md     readme
    ├── Validation/
    │   ├── validation_report.md       validation_report
    │   └── checks.json                validation_checks
    ├── Schema/
    │   └── element_grid_CL-005.json   element_grid
    ├── Authority sources/             official documents kept as proof (S6.1)
    │   ├── <AUTHORITY_ID>__page.html
    │   └── <AUTHORITY_ID>__page.proof.json
    ├── Transcripts/                   transcripts_dir
    │   └── timeline_aeropuerto_STG_7.html
    └── Legal framework/               framework_dir
        └── CHIPENCOD_CP.md
```

Plus, at the bundles root after a batch run: `refine_batch_summary.json` and, when zipping, `CL-005_refined_pack.zip`.
