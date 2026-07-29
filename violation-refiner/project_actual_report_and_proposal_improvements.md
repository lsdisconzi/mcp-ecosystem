# Project Audit Report: ViolationRefiner

## 1. Executive Summary
- **Status**: NEEDS ATTENTION
- **% Complete**: ~85% of declared functionality is working. Core enrichment pipeline (layers 1-5, validation V01-V11, pack/bundle) is complete and well-tested. LLM enrichment stages exist but are runtime-dependent on external API keys. Extension implementations (Qdrant, Neo4j, Jurisprudence) ship with the package. MCP server wraps everything but has an architecture mismatch with `start.sh`.
- **Key Risk**: The `start.sh` script uses `nohup` + `tail -f /dev/null | ...` piping to stdin — a known failure pattern for MCP stdio servers (see team memory). Combined with `MCP_TRANSPORT=streamable-http` env vars that the server code completely ignores, the operational startup path is broken by design.

## 2. Declared Purpose & Requirements

Extracted from README.md, docstrings, pyproject.toml, and source comments:

**What it is**: A Python library (`violation-pack`) that turns prose-heavy "violation files" into layered, verifiable, validatable legal artifacts. Implements five enrichment layers, ten (actually eleven) validation checks, derived confidence scoring, signed manifests, and zipped bundles.

**Core features claimed**:
1. **Layer 1 - Evidence Anchoring** (`build_evidence_layer`): Anchors verbatim transcript segments to HTML source artifacts with byte-accurate SHA verification. Rejects fabricated segment IDs.
2. **Layer 2 - Norm Anchoring** (`build_norms_layer`): Anchors cited legal articles against framework cache files. Substring-verifies excerpts. Separates `CachedArticle` (verified) from `CandidateArticle` (pending).
3. **Layer 3 - Element Grid** (`add_element_grid`): Doctrinal element decomposition per article with 7 proof statuses (established/strong/contested/weak/missing/not_applicable/not_developed).
4. **Layer 4 - Nexus Matrix** (`build_nexus_layer`): Typed edges from facts (segments) to doctrinal elements with strength (high/medium/low).
5. **Layer 5 - Authorities** (`add_authority_stub`): Stubs only — never auto-fills rol/sala/fecha. Structural anti-fabrication guard.
6. **Confidence** (`derive_confidence`): Transparent weighted-mean formula over element grids, scaled by authority verification ratio. Auditable; recomputed by V10.
7. **Validation pipeline** (`run_pipeline`): V01-V11 checks covering segment resolution, verbatim match, article hashing, framework presence, cross-references, element coverage, authority verification, contract consistency, language consistency, confidence derivation, and enrichment integrity.
8. **Packaging** (`write_violation_json`, `build_manifest`, `zip_bundle`): Canonical bundle layout with MANIFEST.txt.
9. **MCP server**: All layer functions + validation + packaging exposed as MCP tools. Qdrant/Neo4j/Jurisprudence tools auto-registered. LLM enrichment tools.
10. **LLM enrichment** (`enrich_violation`): 8 stages (segments, subsections, element_grids, nexus, candidates, authorities, open_questions, cross_references) driven by pluggable LLM backends.
11. **Extensions**: `VectorIndex` (Qdrant), `KnowledgeGraph` (Neo4j), `JurisprudenceProvider` — Protocol interfaces with concrete implementations (`QdrantVectorIndex`, `Neo4jKnowledgeGraph`, `QdrantJurisprudenceProvider`) shipped in-package.
12. **Bulk ingest**: `JurisprudenceIngester`, `TranscriptIngester`, `FrameworkIngester` for populating Qdrant collections from corpus data.
13. **Batch refiner** (`refine_batch.py`): Walks CL-* directories, normalizes legacy schemas, runs enrichment + validation, writes refined outputs.

**External services integrated with**:
- Qdrant (vector database) — optional, via `qdrant-client` package
- Neo4j (graph database) — optional, via `neo4j` package
- LLM providers: OpenRouter, Anthropic, DeepSeek, OpenAI, Ollama — via `httpx`
- Embedding providers: Voyage AI, OpenAI, Cohere, Ollama — via urllib
- Poder Judicial (pjud.cl) / BCN (bcn.cl/leychile) — referenced but NOT connected (human-attestation protocol)

**Interface/API surface**:
- Python library (`from violation_pack import ...`) — 20+ public symbols
- MCP server (`violation-pack-mcp` / `python -m violation_pack.mcp_server`) — 30 tools
- CLI: `violation-pack-catalog` for MCP catalog/config snippet generation
- Scripts: `examples/refine_cl005.py`, `examples/refine_batch.py`, `examples/wire_extensions.py`

## 3. Feature Completeness Matrix

| Feature | Declared | Implemented | Working? | Notes |
|---------|----------|-------------|----------|-------|
| Layer 1 - Evidence Anchoring | Yes | `layers.py:54` | Yes | Tests verify idempotence + fabrication rejection |
| Layer 2 - Norm Anchoring | Yes | `layers.py:128` | Yes | Tests verify substring enforcement |
| Layer 3 - Element Grid | Yes | `layers.py:227` | Yes | Merge-by-ID; tests compose with L1+L4 |
| Layer 4 - Nexus Matrix | Yes | `layers.py:250` | Yes | Upsert by (fact_id, norm_id, element_id) key |
| Layer 5 - Authority Stubs | Yes | `layers.py:285` | Yes | Never auto-fills forbidden fields; tests confirm |
| Confidence Derivation | Yes | `confidence.py:31` | Yes | Weighted mean formula, auditable |
| Validation V01-V10 | Yes | `validation.py` | Yes | 10 checks in DEFAULT_PIPELINE |
| Validation V11 | Yes | `verifier.py:345` | Yes | Enrichment integrity; included in DEFAULT_PIPELINE |
| Pack/Manifest/Zip | Yes | `pack.py` | Yes | Bundle layout + MANIFEST.txt |
| MCP Server (core tools) | Yes | `mcp_server.py:89` | Yes | 30 registered tools; wraps all layers + validation |
| LLM Enrichment | Yes | `enrich.py:859` | Yes | 8 stages, multi-provider, LLM output verified by verifier |
| Qdrant Extension | README says shipped | `qdrant_index.py` | Yes | `QdrantVectorIndex` implements `VectorIndex` Protocol |
| Neo4j Extension | README says shipped | `neo4j_graph.py` | Yes | `Neo4jKnowledgeGraph` implements `KnowledgeGraph` Protocol |
| Jurisprudence Extension | README says shipped | `jurisprudence.py` | Yes | `QdrantJurisprudenceProvider`, verify() requires primary_source_url |
| Embeddings (multi-provider) | Yes | `embeddings.py` | Yes | Voyage/OpenAI/Cohere/Ollama/Hash; auto-select |
| Bulk Ingesters | Yes | `ingesters.py` | Yes | Jurisprudence/Transcript/Framework; all tested with fake Qdrant |
| Batch Refiner | Yes | `examples/refine_batch.py` | Yes | Normalizes legacy -> canonical schema; CLI with --enrich |
| One-shot runner | Yes | `examples/run_one.sh` | Yes | Interactive; stage->refine->upsert pipeline |
| Authority Verification (statute_in_bundle) | Yes | `authority_verification.py:102` | Yes | Substring-match against framework cache; V11-revalidatable |
| Authority Verification (statute_external) | Yes | `authority_verification.py:193` | Yes | Network-free; caller supplies fetched content |
| Authority Verification (human_attested) | Yes | `authority_verification.py:262` | Yes | For jurisprudence/doctrine; requires court+rol+date |
| MCP Catalog | Yes | `mcp_catalog.py` | Yes | CLI + Python API; VS Code / Claude snippet generation |
| `docs/mcp_mapping.md` | Yes (README) | **MISSING** | No | `docs/` directory does not exist |

## 4. Implementation Details

### Core architecture

The project is a well-layered Python library with clear separation of concerns:

**Data layer** (`violation_pack/models.py` — 370 lines):
- 18 Pydantic models covering all 5 enrichment layers + confidence + validation
- `Violation` is the top-level container with fields for each layer output
- All models use `ConfigDict(extra="forbid")` — schema drift caught at parse time
- Every entity has a stable ID (segment_id, article_id, element_id, authority_id)
- `PROOF_WEIGHTS` dict maps proof statuses to numeric scores
- Bilingual fields use dedicated `_es` / `_en` suffixes

**Source-of-truth readers** (`violation_pack/sources.py` — 250 lines):
- `TranscriptSource` Protocol (4 methods) + `HtmlTranscriptSource` concrete impl
- `FrameworkSource` Protocol (5 methods) + `MarkdownFrameworkSource` concrete impl
- HTML parsing via regex `_SEGMENT_PATTERN` for `timeline_*.html` artifacts
- Markdown parsing via `_ARTICLE_HEADER_PATTERN` for framework cache files
- SHA256 computed at construction time; article lookup supports prefix matching

**Enrichment layers** (`violation_pack/layers.py` — 328 lines):
- 5 pure functions, each takes Violation + inputs, returns Violation with provenance
- All idempotent via `_merge_by_id()` helper
- Layer 1 raises `ValueError` on unknown segment IDs (anti-fabrication)
- Layer 2 raises `ValueError` if excerpt is not substring of cache body
- Layer 3 is a thin merge-by-article_id helper
- Layer 4 deduplicates by (fact_id, norm_id, element_id) triple
- Layer 5 deliberately accepts only safe fields (research_query, proposition_to_verify)

**LLM enrichment** (`violation_pack/enrich.py` — 990 lines):
- 8 enrichment stages in topological order
- Each stage: LLM proposes -> layer functions enforce Pydantic schema -> verifier checks invariants
- LLM responses are stripped of forbidden authority fields (defense in depth)
- Known framework prefix guardrail (`_KNOWN_FRAMEWORK_PREFIXES`) blocks hallucinated framework codes
- Retry logic for sparse element grids and empty nexus matrices
- Uses `LLMClient` Protocol — 5 backends (OpenRouter, Anthropic, DeepSeek, OpenAI, Ollama)

**LLM client** (`violation_pack/llm.py` — 299 lines):
- `LLMClient` Protocol with single `chat_json()` method
- `OpenAICompatibleClient` for 4 backends (OpenRouter, DeepSeek, OpenAI, Ollama)
- `AnthropicClient` for Anthropic native Messages API
- JSON code fence stripping via `_strip_code_fence()`
- `PROVIDER_DEFAULTS` with per-provider base URLs, API key env names, and default models

**Confidence** (`violation_pack/confidence.py` — 115 lines):
- Formula: weighted mean of element grid scores * authority verification factor
- Verification factor: floor 0.85 + 0.15 * (verified / total)
- No authorities = 0.85; all verified = 1.0
- `attach_confidence()` preserves prior values in `history` list

**Validation** (`violation_pack/validation.py` — 341 lines):
- 11 checks (V01-V11) as pure functions: `(Violation, sources) -> CheckResult`
- V10 re-derives confidence and checks against stored value (anti-tampering)
- V11 delegates to `verifier.py:verify_enrichment()` which returns `VerificationReport`
- `run_pipeline()` accepts `extra_checks` for extensibility

**Verifier** (`violation_pack/verifier.py` — 377 lines):
- 7 integrity checks covering segment references, excerpt substrings, nexus integrity, authority fabrication, candidate verification steps, cross-reference resolution, open question blocks
- Error/warning severity distinction
- Defendant-fit heuristic (W_AGENT_MISFIT): detects public-official articles cited against private defendants

**Authority verification** (`violation_pack/authority_verification.py` — 354 lines):
- Three protocols: `statute_in_bundle_v1`, `statute_external_fetch_v1`, `human_attested_v1`
- ALL protocols substring-match target_quote against source content
- `VerificationError` raised on failure — NO partial state written
- `VerificationProvenance` records protocol, source SHA, matched quote + offset
- V11 re-validates provenance on read

**Qdrant extension** (`violation_pack/qdrant_index.py` — 371 lines):
- 4 collections: `{prefix}_segments`, `{prefix}_articles`, `{prefix}_authorities`, `{prefix}_jurisprudence`
- UUID5-based stable point IDs for idempotent upserts
- Dimension mismatch detection with clear error directing to `reset_collections()`
- Batched embedding in `upsert_violation()` for API quota efficiency

**Neo4j extension** (`violation_pack/neo4j_graph.py` — 332 lines):
- Full schema: 6 node types + 6 edge types matching the `extensions.py` Protocol
- MERGE-based idempotent writes
- Community Edition graceful degradation (CREATE DATABASE failure caught)
- `link_cross_references()` handles violation-to-violation edges

**Jurisprudence provider** (`violation_pack/jurisprudence.py` — 128 lines):
- `search()` returns unverified stubs (court/rol/date = None)
- `verify()` only flips `verified=True` when Qdrant record has `primary_source_url`
- Conservative default: `require_primary_source_url=True`

**Embeddings** (`violation_pack/embeddings.py` — 373 lines):
- 5 embedders: Voyage, OpenAI, Cohere, Ollama, Hash
- All implement `Embedder` Protocol (name, dim, embed)
- `default_embedder()` auto-selects: Voyage > OpenAI > Cohere > Ollama > Hash
- Exponential backoff with Retry-After respect in `_post_json()`

**Bulk ingesters** (`violation_pack/ingesters.py` — 652 lines):
- Text chunking with paragraph/sentence boundary awareness
- Batched embedding + Qdrant upsert
- Idempotent via UUID5 point IDs
- `IngestStats` dataclass returned with scanned/upserted/skipped/failed counts

**MCP server** (`violation_pack/mcp_server.py` — 769 lines):
- 30 registered tools: all layers, validation, packaging, Qdrant ops, Neo4j ops, jurisprudence ops, LLM enrichment, bulk ingest, embedder info, destructive resets
- `enrich_violation_tool` and `enrich_stage_tool` for individual enrichment stages
- `verify_enrichment_tool` to run V11-level checks independently
- `refine_batch_tool` imports `examples/refine_batch` dynamically via `sys.path` manipulation (fragile)

**Configuration** (`violation_pack/config.py` — 205 lines):
- `Settings` frozen dataclass with `.from_env()` factory
- Manual `.env` parser (no `python-dotenv` dependency)
- LLM provider auto-inference from `LLM_BASE_URL`
- Provider-specific API key resolution with `LLM_API_KEY` fallback
- `settings.llm_client()` lazy-imports `llm.py`

### Key files and their roles
| File | Lines | Role |
|------|-------|------|
| `violation_pack/models.py` | 370 | All Pydantic schemas |
| `violation_pack/layers.py` | 328 | 5 enrichment layer functions |
| `violation_pack/enrich.py` | 990 | LLM-driven enrichment orchestration |
| `violation_pack/verifier.py` | 377 | Enrichment integrity checks (V11) |
| `violation_pack/validation.py` | 341 | V01-V11 pipeline |
| `violation_pack/mcp_server.py` | 769 | MCP server with 30 tools |
| `violation_pack/qdrant_index.py` | 371 | Qdrant VectorIndex impl |
| `violation_pack/neo4j_graph.py` | 332 | Neo4j KnowledgeGraph impl |
| `violation_pack/ingesters.py` | 652 | Bulk corpus ingestion |
| `violation_pack/embeddings.py` | 373 | Multi-provider embedding |
| `violation_pack/config.py` | 205 | Environment-driven configuration |
| `violation_pack/authority_verification.py` | 354 | Authority verification protocols |
| `violation_pack/llm.py` | 299 | Multi-provider LLM client |
| `violation_pack/sources.py` | 250 | Transcript/framework readers |
| `violation_pack/jurisprudence.py` | 128 | JurisprudenceProvider impl |
| `violation_pack/confidence.py` | 115 | Confidence derivation formula |
| `violation_pack/pack.py` | 93 | Bundle layout + zip |
| `violation_pack/extensions.py` | 150 | Protocol definitions |
| `violation_pack/mcp_catalog.py` | 180 | MCP catalog CLI |
| `violation_pack/__init__.py` | 165 | Public API surface + factory functions |

### Example files
| File | Lines | Role |
|------|-------|------|
| `examples/refine_cl005.py` | 405 | Canonical CL-005 end-to-end demo |
| `examples/refine_batch.py` | 754 | Batch refiner over CL-* dirs with --enrich |
| `examples/run_one.sh` | 240 | Interactive single-violation pipeline |
| `examples/wire_extensions.py` | 100 | Qdrant+Neo4j wiring demo |
| `examples/stage_cl_batch.py` | N/A | Legacy bundle staging (read but not fully reviewed) |

### Test files
| File | Lines | What it tests |
|------|-------|---------------|
| `tests/conftest.py` | 28 | Transcript + framework fixtures from cl005_source |
| `tests/test_layers.py` | 174 | Layer 1-5 functions: idempotence, fabrication rejection, composition |
| `tests/test_end_to_end.py` | 63 | Full CL-005 rebuild: segment count, article count, weighted_score, validation pass/fail, bundle files exist |
| `tests/test_verifier.py` | 130 | Verifier failure modes: fabricated rol, LLM-verified authority, unknown nexus segment, empty verification_required, unresolved cross-refs |
| `tests/test_extensions.py` | 277 | HashEmbedder determinism, in-memory fake Qdrant for upsert/search, fake Neo4j driver for CYPHER generation, jurisprudence verify() contract enforcement |
| `tests/test_ingesters.py` | 262 | Fake corpus for JurisprudenceIngester (chunking, idempotence, cap), fake transcript bundle for TranscriptIngester (empty skip, audio tags), FrameworkIngester article header parsing |

## 5. Issues Found

### 5.1 Critical (broken functionality, security)

1. **`start.sh` MCP transport mismatch — server will not function as configured**
   - File: `/awareness/services/ViolationRefiner/start.sh`, line 17, lines 37-38
   - `start.sh` sets `MCP_TRANSPORT=streamable-http` and passes `MCP_HOST`/`MCP_PORT`
   - The MCP server (`mcp_server.py:764`) calls `server.run()` with FastMCP (stdio transport)
   - The server code NEVER reads `MCP_TRANSPORT`, `MCP_HOST`, or `MCP_PORT` env vars
   - The `--transport` CLI arg is not exposed in `mcp_server.py`'s argument parser
   - Result: start.sh advertises HTTP transport on port 8785, but the server only speaks stdio

2. **`start.sh` uses `nohup` + `tail -f /dev/null |` to pipe stdin — known exit pattern**
   - File: `/awareness/services/ViolationRefiner/start.sh`, lines 37-38
   - Matches the exact pattern documented in team memory as causing silent exit
   - `nohup` redirects stdin to `/dev/null`; MCP stdio server receives EOF and exits
   - The `tail -f /dev/null |` workaround attempts to keep stdin open but is fragile with `nohup`

3. **`refine_batch_tool` uses `sys.path` manipulation to import from `examples/`**
   - File: `mcp_server.py`, lines 385-390
   - `sys.path.insert(0, str(examples_dir))` followed by `import refine_batch` then `sys.path.pop(0)`
   - This is fragile: if `refine_batch.py` has side-effects on import or if multiple threads call this tool, path state corruption is possible
   - The `refine_batch` module is not a proper installable package dependency

### 5.2 Important (bugs, missing features, reliability)

4. **`docs/mcp_mapping.md` referenced in README but does not exist**
   - File: `/awareness/services/ViolationRefiner/README.md`, lines 84, 139, 162
   - The `docs/` directory does not exist in the repository
   - Any user following the README to understand MCP tool mapping will hit a dead end

5. **`.env.example` is missing LLM configuration fields**
   - File: `/awareness/services/ViolationRefiner/.env.example`
   - The code (`config.py`) reads: `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `LLM_TOKEN_BUDGET`, `LLM_TIMEOUT_SECONDS`
   - The `.env.example` only documents embedding configs — none of the LLM configs are documented
   - `.env.example` also uses `NEO4J_LOCAL_*` prefix names but `config.py:158-166` falls back to `NEO4J_*` names — the fallback names are undocumented

6. **`mcp_catalog.py:83` lists `neo4j_query_tool` but the server registers `neo4j_*_tool` variants**
   - The catalog has `ToolEntry("neo4j_query_tool", "Cypher passthrough on the OliviaLegal graph.", ["neo4j"])`
   - No such tool exists on the server. The actual tools are `neo4j_upsert_violation_tool`, `neo4j_find_violations_citing_tool`, `neo4j_find_violations_with_contested_element_tool`, `neo4j_walk_implications_tool`
   - The catalog also omits the actual Neo4j tools that DO exist

7. **`mcp_catalog.py:69-76` lists 15 tools but the server registers 30**
   - The catalog is incomplete: missing `neo4j_reset_database_tool`, `qdrant_reset_collections_tool`, `embedder_info_tool`, and several others
   - The catalog is a "single source of truth" per its own docstring but is out of date

8. **`generate_map.py` hardcodes paths that won't work outside a specific setup**
   - File: `/awareness/services/ViolationRefiner/generate_map.py`, line 6
   - `base_dir = Path("build/cl_batch")` — hardcoded relative path with no CLI arguments
   - Reads from a `status` object format that doesn't match the actual refined JSON schema (uses `data.get("status", {}).get("pass")` but refined JSON uses `validation` or nested `checks` structures)
   - This script appears to be a one-off data generation script, not a reusable tool

9. **`enrich.py` has a TODO about configuring the authority verification floor**
   - File: `violation_pack/confidence.py`, line 77
   - `# researched yet (this is configurable — see TODO below).`
   - The 0.85 floor for authority verification is hardcoded; the TODO suggests making it configurable but this hasn't been done

10. **Missing `FrameworkSource` Protocol implementations for non-filesystem sources**
    - File: `violation_pack/sources.py`
    - Only `HtmlTranscriptSource` (disk HTML) and `MarkdownFrameworkSource` (disk MD) are concrete
    - The Protocols mention Qdrant-backed readers as future possibilities, but none exist
    - When a transcript is too large for local disk, the pipeline can't work

### 5.3 Minor (cleanup, style, optimization)

11. **Chat log files in project root are not source code**
    - Files: `3am_chat_cut_off_to_continue.md` (71KB), `5am_respose_cut_out_to_be_continued.md` (51KB), `whole_chat_claude.md` (37KB)
    - These are ~160KB of Claude session transcripts from development
    - Should be removed or moved to a separate directory if kept for reference

12. **`.venv/` directory (217MB) in project tree**
    - The virtual environment is in the project directory and is not gitignored (though `.venv/` IS in `.gitignore`)
    - Normal practice: venvs live outside the project or are fully gitignored
    - `.gitignore` does include `.venv/` so this is only a local filesystem concern, not a commit risk

13. **`examples/refine_batch.py.bak` backup file**
    - File: `/awareness/services/ViolationRefiner/examples/refine_batch.py.bak`
    - Backup of a current source file — likely accidental or leftover from development
    - Should be removed

14. **`violation_pack.egg-info/` directory in project**
    - This is an installed-package artifact (generated by `pip install -e .`)
    - Should be added to `.gitignore` if not already (`.gitignore` has `*.egg-info/` which covers this)

15. **`start.sh` hardcodes `.venv/bin/python` and `.venv/bin/pip` paths**
    - File: `start.sh`, lines 15-16
    - The shell script assumes the venv at a specific relative path
    - Makes the script non-portable to different Python installations

16. **`stop.sh` uses `pkill` which kills ALL processes matching the pattern**
    - File: `stop.sh`, lines 38-39
    - `pkill -f "violation_pack.mcp_server"` and `pkill -f "violation-pack-mcp"` will kill ALL matching processes system-wide, not just the ones started by this project's start.sh

17. **`enrich.py:399-403` imports from `violation_pack.models` inside a function using a string path**
    - `from violation_pack.models import PROOF_WEIGHTS` — uses full package name instead of relative import
    - Works because of install, but inconsistent with the rest of the file which uses relative imports

18. **Code duplication: `_sha256_text()` defined in both `layers.py` and `refine_batch.py`**
    - `layers.py:36` and `refine_batch.py:53` both define identical `_sha256_text()` functions
    - Similarly, `_parse_time_seconds()` in `refine_batch.py` reimplements time parsing that might better live in a shared utility

19. **`tests/test_extensions.py:22-51` and `tests/test_ingesters.py:22-86` duplicate `_FakeQdrantClient`**
    - The fake client is ~60 lines duplicated verbatim between two test files
    - Test file comment acknowledges this is deliberate but suggests a shared conftest fixture

## 6. Directory Cleanups Needed

- [x] Files to delete (with reasons):
  - `3am_chat_cut_off_to_continue.md` — 71KB Claude session transcript; not source code
  - `5am_respose_cut_out_to_be_continued.md` — 51KB Claude session transcript; not source code
  - `whole_chat_claude.md` — 37KB Claude session transcript; not source code
  - `examples/refine_batch.py.bak` — stale backup; the active file is `examples/refine_batch.py`
  - `build/violations_baseline_18.tar.gz` — 1MB binary artifact; should not live in version control
  - `build/cl_batch/refine_batch_summary.json` — runtime output; belongs in .gitignore

- [x] Files to move (with target locations):
  - (None identified — no source files in wrong locations)

- [x] Files to add to .gitignore:
  - `.logs/` — runtime log output
  - `.run/` — runtime PID files
  - `build/` — build artifacts (if not already gitignored — currently not in .gitignore)
  - (`.venv/` and `*.egg-info/` are already in .gitignore)

## 7. Improvement Proposals

### 7.1 Fix the MCP server startup (CRITICAL)

**Problem**: `start.sh` advertises HTTP transport but the server only supports stdio. The `nohup` + `tail -f /dev/null |` pattern is known to cause silent exit for stdio MCP servers.

**Proposal A** (if stdio is sufficient):
Replace `start.sh` with a direct stdio invocation that doesn't pretend to be HTTP. Remove `MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT` env vars. Remove the `nohup` + `tail -f /dev/null |` pipe. The `start.sh` should just run the server with appropriate logging:
```bash
"$PYTHON_BIN" -m violation_pack.mcp_server >>"$LOG_DIR/mcp.log" 2>&1 &
```
MCP clients (VS Code, Claude Desktop) connect via stdio — the entry in `.vscode/mcp.json` already correctly specifies `"type": "stdio"`.

**Proposal B** (if HTTP/SSE is needed):
FastMCP supports SSE transport. The `mcp_server.py` entry point would need to accept `--transport sse --host ... --port ...` arguments, and `start.sh` would use them. But this requires the `mcp` package to support SSE (check version compatibility).

### 7.2 Remove `sys.path` hack in `refine_batch_tool`

**File**: `violation_pack/mcp_server.py`, lines 385-390

Move the shared batch logic from `examples/refine_batch.py` into `violation_pack/refine_batch_core.py` (or similar) that can be properly imported. Keep the CLI wrapper in `examples/refine_batch.py` as a thin caller. The `refine_batch_tool` in the MCP server would then do:
```python
from violation_pack.refine_batch_core import run
```
instead of the current `sys.path` manipulation.

### 7.3 Create `docs/mcp_mapping.md`

Either create the file or remove the references from README.md. The README already has a table of MCP tools (lines 183-196) and the MCP catalog tool can generate this information dynamically. Simplest fix: remove the references to `docs/mcp_mapping.md` and point users to `violation-pack-catalog --format catalog` instead.

### 7.4 Complete `.env.example` with all configurable fields

Add missing LLM configuration to `.env.example`:
```
# --- LLM enrichment -------------------------------------------------------
LLM_PROVIDER=openrouter          # or anthropic | deepseek | openai | ollama
LLM_MODEL=anthropic/claude-3.5-sonnet
LLM_API_KEY=${LLM_API_KEY}       # generic fallback
LLM_BASE_URL=                    # override provider default
LLM_TEMPERATURE=0.1
LLM_MAX_TOKENS=8000
LLM_TOKEN_BUDGET=250000
LLM_TIMEOUT_SECONDS=90

# Provider-specific keys (at least one required for enrichment):
OPENROUTER_API_KEY=
ANTHROPIC_API_KEY=
DEEPSEEK_API_KEY=
OPENAI_API_KEY=                  # (also used by OpenAIEmbedder if EMBED_PROVIDER=openai)
# OLLAMA_API_KEY= usually unset for local Ollama
```

Also document `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` as alternative names to `NEO4J_LOCAL_*`.

### 7.5 Update `mcp_catalog.py` to match actual registered tools

The catalog in `mcp_catalog.py:67-85` lists 15 tools but the server registers 30. Update the tool list to match or, better, generate it dynamically by introspecting the built server.

### 7.6 Make authority verification floor configurable

**File**: `violation_pack/confidence.py`, line 77-84

Expose the 0.85 floor as a parameter:
```python
def derive_confidence(
    violation: Violation,
    article_weights: dict[str, float] | None = None,
    authority_verification_floor: float = 0.85,
) -> ConfidenceDerivation:
```
And read it from environment via `Settings`.

### 7.7 Move `_sha256_text()` to a shared utility module

`layers.py:36` and `refine_batch.py:53` both define the same function. Move it to `violation_pack/_utils.py` or make it a method on a shared base.

### 7.8 Clean up chat logs

Remove `3am_chat_cut_off_to_continue.md`, `5am_respose_cut_out_to_be_continued.md`, and `whole_chat_claude.md` from the repository root. If they contain valuable decision history, extract the relevant decisions and discard the rest. These are ~160KB of raw Claude transcripts.

### 7.9 Make `generate_map.py` a proper tool or remove it

Currently `generate_map.py` hardcodes paths and reads from a non-existent schema. Either:
- Make it a proper CLI tool with `--input` argument that reads from the actual refined JSON schema
- Or remove it (it appears to be a one-off script for a specific report)

### 7.10 Add `build/` to `.gitignore`

The `build/` directory contains runtime artifacts (refined packs, zips, tar.gz) that should not be committed. Currently `.gitignore` does not include `build/`.

## 8. Dependency Audit

### Used but undeclared:
- None identified. All runtime dependencies are declared in `pyproject.toml` under either `dependencies` (pydantic) or `optional-dependencies` (pytest, mcp, qdrant-client, neo4j, httpx).

### Declared but unused:
- None identified. All declared packages are imported (with lazy imports for optional deps):
  - `pydantic` — used throughout models
  - `qdrant-client` — lazy-imported in `qdrant_index.py`, `ingesters.py`, `jurisprudence.py`
  - `neo4j` — lazy-imported in `neo4j_graph.py`
  - `mcp` — lazy-imported in `mcp_server.py`
  - `httpx` — lazy-imported in `llm.py`
  - `pytest` — used by test suite

### Version concerns:
- `pydantic>=2.5` — pinned loosely. Current usage (model_validate, model_dump_json, model_copy, ConfigDict) is stable across 2.x.
- `qdrant-client>=1.7` — uses `query_points` with fallback to `search` for older versions. Compatible.
- `neo4j>=5` — standard driver; no Neo4j 5-specific features used.
- `mcp>=1.2` — uses `FastMCP` and `server.run()`. Version constraint is appropriate.
- `httpx>=0.27` — only basic `post()` used. Very loose constraint.
- `setuptools>=68` — build-time only. Adequate.

## 9. Architecture Assessment

### Current architecture

```
violation_pack/
├── models.py          [Data]       Pydantic schemas for all 5 layers
├── sources.py         [I/O]        Transcript/framework source readers (Protocols + disk impls)
├── layers.py          [Transform]  5 pure enrichment functions
├── confidence.py      [Derive]     Weighted-mean confidence formula
├── validation.py      [Verify]     V01-V11 validation pipeline
├── verifier.py        [Verify]     LLM-output enrichment integrity checks
├── authority_verification.py [Verify] 3 verification protocols
├── pack.py            [Output]     Bundle serialization, manifest, zip
├── extensions.py      [Interface]  JurisprudenceProvider, VectorIndex, KnowledgeGraph Protocols
├── qdrant_index.py    [Ext]       Qdrant VectorIndex implementation
├── neo4j_graph.py     [Ext]       Neo4j KnowledgeGraph implementation
├── jurisprudence.py   [Ext]       Qdrant-backed JurisprudenceProvider
├── embeddings.py      [Infra]     Multi-provider embedding (Voyage/OpenAI/Cohere/Ollama/Hash)
├── ingesters.py       [Infra]     Bulk corpus ingestion
├── enrich.py          [Enrich]    LLM-driven enrichment (8 stages)
├── llm.py             [Infra]     Multi-provider LLM client
├── config.py          [Infra]     Environment-driven Settings
├── mcp_server.py      [API]       MCP server with 30 tools
├── mcp_catalog.py     [API]       MCP catalog CLI + snippet generator
└── __init__.py        [API]       Public surface + factory functions
```

### Strengths

1. **Well-layered separation of concerns**: Data (models) -> Transform (layers) -> Verify (validation, verifier) -> Output (pack) is a clean pipeline. Each module has a single clear purpose.

2. **Protocol-based extension points**: `TranscriptSource`, `FrameworkSource`, `VectorIndex`, `KnowledgeGraph`, `JurisprudenceProvider`, `LLMClient` are all Protocols. This means extensions can be written without inheriting from any base class, and the core library stays dependency-free.

3. **Anti-fabrication design is thorough**: Layer 1 rejects unknown segment IDs. Layer 2 rejects non-substring excerpts. Layer 5 never accepts roll numbers. The verifier (V11) independently re-checks every invariant. The authority verification module is the ONLY code path that can flip `verified=True`. Defense in depth.

4. **Strong test coverage**: Tests cover idempotence, fabrication rejection, composition, end-to-end CL-005 rebuild, verifier failure modes, and both extension backends with in-memory fakes. The fake Qdrant client pattern allows testing vector operations without network.

5. **Idempotent operations**: All layer functions merge by ID. Qdrant uses UUID5. Neo4j uses MERGE. Re-running the pipeline is a no-op.

6. **Lazy imports keep core dependency-free**: `pip install violation-pack` only pulls in Pydantic. Everything else requires explicit `[mcp]`, `[qdrant]`, `[neo4j]`, or `[llm]` extras.

### Weaknesses

1. **MCP server startup is broken**: The most serious architectural gap. `start.sh` and the MCP server code have fundamentally incompatible ideas about transport (HTTP vs stdio). This is the project's primary operational interface and it cannot work as configured.

2. **No `setup.py` or `pyproject.toml` entry point for the batch refiner**: `refine_batch.py` lives under `examples/` and is not importable as a proper module. The MCP server hacks around this with `sys.path` manipulation. This is fragile and prevents the batch refiner from being properly tested or versioned.

3. **`generate_map.py` is dead code**: A one-off script hardcoded to a specific directory structure that doesn't match the current schema.

4. **Catalog is out of sync with actual tools**: The `mcp_catalog.py` lists tools that don't exist and omits tools that do. The docstring claims it's the "single source of truth" but it's demonstrably false.

5. **Missing documentation file**: `docs/mcp_mapping.md` is referenced in the README layout diagram and in the "What's next" section, but the directory and file don't exist.

6. **Start/stop scripts have portability issues**: Hardcoded `.venv/bin/python` paths, system-wide `pkill` in stop.sh, and transport assumptions that don't match the server code.

### Recommended architectural changes

1. **Decide on MCP transport and make it consistent**: Either go full stdio (simplify start.sh) or add SSE support to the MCP server (requires changes to `mcp_server.py`). The current halfway state is the single biggest risk.

2. **Promote `refine_batch.py` to a library module**: Move the core logic (`run()`, `_normalize()`, `_process_one()`) into `violation_pack/refine_batch_core.py` and keep only the CLI `main()` in `examples/refine_batch.py`. This fixes the `sys.path` hack in the MCP server and makes batch logic testable.

3. **Generate the MCP catalog dynamically**: Instead of maintaining a manual list in `mcp_catalog.py`, have the catalog generator introspect the built server's registered tools.

4. **Add a shared utilities module**: Move `_sha256_text()`, time parsing, and other small helpers duplicated between `layers.py` and `refine_batch.py` into `violation_pack/_utils.py`.

5. **Create `docs/` directory or remove references**: Either create `docs/mcp_mapping.md` with the actual tool mapping, or update the README to remove non-existent paths.
