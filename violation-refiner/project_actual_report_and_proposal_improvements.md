# Project Audit Report: ViolationRefiner

> **REVISION — 2026-09-11.** This report was produced on **2026-05-16**. The
> codebase advanced substantially since then. The **Resolution Ledger** below
> supersedes any conflicting statement in the body: item numbers in sections
> 5–7 are annotated here with their current status. Only entries marked
> **OPEN** remain live.
>
> ### Resolution Ledger (by section/item)
>
> | Item | Finding | Status now | Evidence |
> | --- | --- | --- | --- |
> | 5.1-1 | `start.sh` / server transport mismatch | ✅ FIXED | `mcp_server.py:main()` reads `MCP_TRANSPORT`/`MCP_HOST`/`MCP_PORT`, supports `stdio`/`sse`/`streamable-http`, exposes `GET /health` |
> | 5.1-2 | `nohup` + `tail -f /dev/null \|` stdin pipe | ✅ FIXED | `start.sh` uses centralized `start_logging` + `/health` wait; no stdin pipe |
> | 5.1-3 | `refine_batch_tool` `sys.path` hack | ✅ FIXED | tool imports `violation_pack.refine_batch_core`; `examples/refine_batch.py` is now a thin 109-line CLI |
> | 5.2-4 | `docs/mcp_mapping.md` missing | ✅ FIXED | created — 13 sections mapping every MCP tool → library function → `file:line` → UI step |
> | 5.2-5 | `.env.example` incomplete | ✅ FIXED | created — documents all **31** `Settings.from_env()` vars plus the 3 `MCP_*` transport vars, grouped by provider |
> | 5.2-6 | phantom `neo4j_query_tool` in catalog | ✅ FIXED | catalog lists the four real `neo4j_*_tool` entries |
> | 5.2-7 | catalog lists 15 vs 30 tools | ✅ FIXED | catalog lists all **39** registered tools |
> | 5.2-8 | `generate_map.py` dead code | ✅ FIXED (removed) | file no longer present |
> | 5.2-9 | authority-verification floor hardcoded | ✅ FIXED | `derive_confidence(..., authority_verification_floor=0.85)` + `AUTHORITY_VERIFICATION_FLOOR` env var |
> | 5.2-10 | no non-filesystem `FrameworkSource` | ⚠️ OPEN | only `HtmlTranscriptSource` / `MarkdownFrameworkSource` ship |
> | 5.3-11 | chat logs in root | ✅ FIXED (removed) | not present |
> | 5.3-12 | `.venv/` in project tree | ➖ N/A | gitignored; local-only concern |
> | 5.3-13 | `examples/refine_batch.py.bak` | ✅ FIXED (removed) | not present |
> | 5.3-14 | `egg-info/` in project tree | ➖ N/A | covered by `*.egg-info/` in `.gitignore` |
> | 5.3-15 | `start.sh` hardcodes venv paths | ✅ FIXED | `resolve_python()` tries `.venv/bin/python` → `python3` → `python`, errors helpfully if none, and echoes the interpreter used |
> | 5.3-16 | `stop.sh` system-wide `pkill` | ✅ FIXED | replaced by `reap_local_server_processes()`, scoped by each PID's cwd to this checkout |
> | 5.3-17 | absolute import inside `enrich.py` | ✅ FIXED | `PROOF_WEIGHTS` moved to the module-level `from .models import (...)` block |
> | 5.3-18 | `_sha256_text()` duplicated | ✅ FIXED | single `sha256_text()` in `violation_pack/_utils.py`, imported by `layers.py` + `refine_batch_core.py` |
> | 5.3-19 | duplicated `_FakeQdrantClient` in tests | ✅ FIXED | shared `tests/_fakes.py` (`FakeCollections`, `FakeQdrantClient`); both test modules import it |
> | 6 | directory cleanup | ✅ DONE | transcripts / `.bak` / tarball gone; `.logs/`, `.run/`, **`build/`, `dist/`** gitignored |
> | 7.1 | fix MCP startup | ✅ DONE | transport now configurable (covers both Proposal A and B) |
> | 7.2 | remove `sys.path` hack | ✅ DONE | via `refine_batch_core.py` |
> | 7.3 | create `docs/mcp_mapping.md` | ✅ DONE | file created; the "remove the references" carve-out was not needed |
> | 7.4 | complete `.env.example` | ✅ DONE | file created from the real `config.py` surface (no phantom `EMBEDDING_MODEL` / `EMBEDDING_DIM`) |
> | 7.5 | update / generate catalog | ✅ DONE | catalog corrected **and** drift now fails CI via `tests/test_catalog_sync.py`, which AST-derives tool names from `mcp_server.py` and env names from `config.py` |
> | 7.6 | configurable authority floor | ✅ DONE | parameter + `AUTHORITY_VERIFICATION_FLOOR` env var |
> | 7.7 | move `_sha256_text()` | ✅ DONE | `violation_pack/_utils.py` |
> | 7.8 | remove chat logs | ✅ DONE | removed |
> | 7.9 | fix/remove `generate_map.py` | ✅ DONE (removed) | file absent |
> | 7.10 | add `build/` to `.gitignore` | ✅ DONE | `build/` and `dist/` added to the runtime-artifacts block |
>
> **Current metrics (verified 2026-09-11):** 39 MCP tools (was 30); V01–V11
> (11 checks, not 10); `python examples/refine_cl005.py` →
> `Confidence: 0.74`, `Validation: {'total': 11, 'pass': 7, 'warn': 4, 'fail': 0}`
> (V03, V05, V07, and V11 warn; V11 is `W_AUTH_DANGLING_SUPPORT`).
>
> **Test suite (verified 2026-09-11):** `38 passed` in ~2.0 s with the `test`,
> `mcp`, `qdrant` and `neo4j` extras installed. Previously **8 of 38 were
> silently skipped** because `qdrant_client` / `neo4j` were absent, which meant
> the extension and ingester paths — including the shared test doubles — were
> never exercised locally.
>
> **Documentation surface (verified 2026-09-11):** three top-level documents
> (`README.md`, `agent_violation_refiner.md`, this report) plus two new files in
> `docs/`: `docs/ui_structural_skeleton.md` (complete UI structural skeleton,
> steps S0–S14) and `docs/mcp_mapping.md` (tool → function → `file:line` map).

## 1. Executive Summary (revised 2026-09-11)
- **Status**: HEALTHY (was NEEDS ATTENTION)
- **% Complete**: Core enrichment pipeline (layers 1–5, validation V01–V11,
  pack/bundle, confidence) is complete and exercised by the CL-005 demo.
  LLM enrichment stages exist and are runtime-dependent on external API keys.
  Extension implementations (Qdrant, Neo4j, Jurisprudence) ship in-package.
  The MCP server wraps everything and its transport now matches `start.sh`.
- **Resolved key risk**: the former `start.sh` / server transport mismatch is
  fixed — the server reads `MCP_TRANSPORT` / `MCP_HOST` / `MCP_PORT`, supports
  `stdio` and `streamable-http`, and serves `GET /health`.
- **Remaining risk (low)**: one design gap only — there is still no
  non-filesystem `FrameworkSource` implementation (ledger 5.2-10). The former
  documentation/config hygiene items are all closed: `.env.example` exists,
  `docs/mcp_mapping.md` exists, `build/` and `dist/` are gitignored, and the
  system-wide `pkill` fallback in `stop.sh` has been replaced by a
  cwd-scoped reaper. See the ledger above.

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
- MCP server (`violation-pack-mcp` / `python -m violation_pack.mcp_server`) — 39 tools
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
| Validation V01–V10 (core) | Yes | `validation.py` | Yes | 10 deterministic checks; `DEFAULT_PIPELINE` runs all 11 alongside V11 |
| Validation V11 | Yes | `verifier.py:345` | Yes | Enrichment integrity; included in DEFAULT_PIPELINE |
| Pack/Manifest/Zip | Yes | `pack.py` | Yes | Bundle layout + MANIFEST.txt |
| MCP Server (core tools) | Yes | `mcp_server.py` | Yes | **39** registered tools; wraps all layers + validation |
| LLM Enrichment | Yes | `enrich.py:859` | Yes | 8 stages, multi-provider, LLM output verified by verifier |
| Qdrant Extension | README says shipped | `qdrant_index.py` | Yes | `QdrantVectorIndex` implements `VectorIndex` Protocol |
| Neo4j Extension | README says shipped | `neo4j_graph.py` | Yes | `Neo4jKnowledgeGraph` implements `KnowledgeGraph` Protocol |
| Jurisprudence Extension | README says shipped | `jurisprudence.py` | Yes | `QdrantJurisprudenceProvider`, verify() requires primary_source_url |
| Embeddings (multi-provider) | Yes | `embeddings.py` | Yes | Voyage/OpenAI/Cohere/Ollama/Hash; auto-select |
| Bulk Ingesters | Yes | `ingesters.py` | Yes | Jurisprudence/Transcript/Framework; all tested with fake Qdrant |
| Batch Refiner | Yes | `violation_pack/refine_batch_core.py` (+ `examples/refine_batch.py` CLI) | Yes | Normalizes legacy -> canonical schema; CLI with --enrich |
| One-shot runner | Yes | `examples/run_one.sh` | Yes | Interactive; stage->refine->upsert pipeline |
| Authority Verification (statute_in_bundle) | Yes | `authority_verification.py:102` | Yes | Substring-match against framework cache; V11-revalidatable |
| Authority Verification (statute_external) | Yes | `authority_verification.py:193` | Yes | Network-free; caller supplies fetched content |
| Authority Verification (human_attested) | Yes | `authority_verification.py:262` | Yes | For jurisprudence/doctrine; requires court+rol+date |
| MCP Catalog | Yes | `mcp_catalog.py` | Yes | CLI + Python API; VS Code / Claude snippet generation |
| `docs/mcp_mapping.md` | Was (README) | **MISSING** | No | `docs/` still absent; README references were removed (open item 7.3) |

## 4. Implementation Details

### Core architecture

The project is a well-layered Python library with clear separation of concerns:

**Data layer** (`violation_pack/models.py` — 369 lines):
- 18 Pydantic models covering all 5 enrichment layers + confidence + validation
- `Violation` is the top-level container with fields for each layer output
- All models use `ConfigDict(extra="forbid")` — schema drift caught at parse time
- Every entity has a stable ID (segment_id, article_id, element_id, authority_id)
- `PROOF_WEIGHTS` dict maps proof statuses to numeric scores
- Bilingual fields use dedicated `_es` / `_en` suffixes

**Source-of-truth readers** (`violation_pack/sources.py` — 249 lines):
- `TranscriptSource` Protocol (4 methods) + `HtmlTranscriptSource` concrete impl
- `FrameworkSource` Protocol (5 methods) + `MarkdownFrameworkSource` concrete impl
- HTML parsing via regex `_SEGMENT_PATTERN` for `timeline_*.html` artifacts
- Markdown parsing via `_ARTICLE_HEADER_PATTERN` for framework cache files
- SHA256 computed at construction time; article lookup supports prefix matching

**Enrichment layers** (`violation_pack/layers.py` — 323 lines):
- 5 pure functions, each takes Violation + inputs, returns Violation with provenance
- All idempotent via `_merge_by_id()` helper
- Layer 1 raises `ValueError` on unknown segment IDs (anti-fabrication)
- Layer 2 raises `ValueError` if excerpt is not substring of cache body
- Layer 3 is a thin merge-by-article_id helper
- Layer 4 deduplicates by (fact_id, norm_id, element_id) triple
- Layer 5 deliberately accepts only safe fields (research_query, proposition_to_verify)

**LLM enrichment** (`violation_pack/enrich.py` — 989 lines):
- 8 enrichment stages in topological order
- Each stage: LLM proposes -> layer functions enforce Pydantic schema -> verifier checks invariants
- LLM responses are stripped of forbidden authority fields (defense in depth)
- Known framework prefix guardrail (`_KNOWN_FRAMEWORK_PREFIXES`) blocks hallucinated framework codes
- Retry logic for sparse element grids and empty nexus matrices
- Uses `LLMClient` Protocol — 5 backends (OpenRouter, Anthropic, DeepSeek, OpenAI, Ollama)

**LLM client** (`violation_pack/llm.py` — 298 lines):
- `LLMClient` Protocol with single `chat_json()` method
- `OpenAICompatibleClient` for 4 backends (OpenRouter, DeepSeek, OpenAI, Ollama)
- `AnthropicClient` for Anthropic native Messages API
- JSON code fence stripping via `_strip_code_fence()`
- `PROVIDER_DEFAULTS` with per-provider base URLs, API key env names, and default models

**Confidence** (`violation_pack/confidence.py` — 117 lines):
- Formula: weighted mean of element grid scores * authority verification factor
- Verification factor: floor 0.85 + 0.15 * (verified / total)
- No authorities = 0.85; all verified = 1.0
- `attach_confidence()` preserves prior values in `history` list

**Validation** (`violation_pack/validation.py` — 340 lines):
- 11 checks (V01-V11) as pure functions: `(Violation, sources) -> CheckResult`
- V10 re-derives confidence and checks against stored value (anti-tampering)
- V11 delegates to `verifier.py:verify_enrichment()` which returns `VerificationReport`
- `run_pipeline()` accepts `extra_checks` for extensibility

**Verifier** (`violation_pack/verifier.py` — 376 lines):
- 7 integrity checks covering segment references, excerpt substrings, nexus integrity, authority fabrication, candidate verification steps, cross-reference resolution, open question blocks
- Error/warning severity distinction
- Defendant-fit heuristic (W_AGENT_MISFIT): detects public-official articles cited against private defendants

**Authority verification** (`violation_pack/authority_verification.py` — 353 lines):
- Three protocols: `statute_in_bundle_v1`, `statute_external_fetch_v1`, `human_attested_v1`
- ALL protocols substring-match target_quote against source content
- `VerificationError` raised on failure — NO partial state written
- `VerificationProvenance` records protocol, source SHA, matched quote + offset
- V11 re-validates provenance on read

**Qdrant extension** (`violation_pack/qdrant_index.py` — 370 lines):
- 4 collections: `{prefix}_segments`, `{prefix}_articles`, `{prefix}_authorities`, `{prefix}_jurisprudence`
- UUID5-based stable point IDs for idempotent upserts
- Dimension mismatch detection with clear error directing to `reset_collections()`
- Batched embedding in `upsert_violation()` for API quota efficiency

**Neo4j extension** (`violation_pack/neo4j_graph.py` — 331 lines):
- Full schema: 6 node types + 6 edge types matching the `extensions.py` Protocol
- MERGE-based idempotent writes
- Community Edition graceful degradation (CREATE DATABASE failure caught)
- `link_cross_references()` handles violation-to-violation edges

**Jurisprudence provider** (`violation_pack/jurisprudence.py` — 127 lines):
- `search()` returns unverified stubs (court/rol/date = None)
- `verify()` only flips `verified=True` when Qdrant record has `primary_source_url`
- Conservative default: `require_primary_source_url=True`

**Embeddings** (`violation_pack/embeddings.py` — 372 lines):
- 5 embedders: Voyage, OpenAI, Cohere, Ollama, Hash
- All implement `Embedder` Protocol (name, dim, embed)
- `default_embedder()` auto-selects: Voyage > OpenAI > Cohere > Ollama > Hash
- Exponential backoff with Retry-After respect in `_post_json()`

**Bulk ingesters** (`violation_pack/ingesters.py` — 651 lines):
- Text chunking with paragraph/sentence boundary awareness
- Batched embedding + Qdrant upsert
- Idempotent via UUID5 point IDs
- `IngestStats` dataclass returned with scanned/upserted/skipped/failed counts

**MCP server** (`violation_pack/mcp_server.py` — 790 lines):
- **39** registered tools: all layers, validation, packaging, Qdrant ops, Neo4j ops, jurisprudence ops, LLM enrichment, bulk ingest, embedder info, destructive resets
- `enrich_violation_tool` and `enrich_stage_tool` for individual enrichment stages
- `verify_enrichment_tool` to run V11-level checks independently
- Transport + bind configurable via `MCP_TRANSPORT` / `MCP_HOST` / `MCP_PORT`; exposes a `GET /health` endpoint in HTTP mode
- `refine_batch_tool` calls the importable `violation_pack.refine_batch_core` directly (no `sys.path` hack)

**Configuration** (`violation_pack/config.py` — 210 lines):
- `Settings` frozen dataclass with `.from_env()` factory
- Manual `.env` parser (no `python-dotenv` dependency)
- LLM provider auto-inference from `LLM_BASE_URL`
- Provider-specific API key resolution with `LLM_API_KEY` fallback
- `settings.llm_client()` lazy-imports `llm.py`

### Key files and their roles (line counts re-verified 2026-09-11)
| File | Lines | Role |
|------|-------|------|
| `violation_pack/models.py` | 369 | All Pydantic schemas |
| `violation_pack/layers.py` | 323 | 5 enrichment layer functions |
| `violation_pack/enrich.py` | 989 | LLM-driven enrichment orchestration |
| `violation_pack/verifier.py` | 376 | Enrichment integrity checks (V11) |
| `violation_pack/validation.py` | 340 | V01-V11 pipeline |
| `violation_pack/refine_batch_core.py` | 662 | Importable batch-refiner core (new) |
| `violation_pack/mcp_server.py` | 790 | MCP server with **39** tools |
| `violation_pack/qdrant_index.py` | 370 | Qdrant VectorIndex impl |
| `violation_pack/neo4j_graph.py` | 331 | Neo4j KnowledgeGraph impl |
| `violation_pack/ingesters.py` | 651 | Bulk corpus ingestion |
| `violation_pack/embeddings.py` | 372 | Multi-provider embedding |
| `violation_pack/config.py` | 210 | Environment-driven configuration |
| `violation_pack/authority_verification.py` | 353 | Authority verification protocols |
| `violation_pack/llm.py` | 298 | Multi-provider LLM client |
| `violation_pack/sources.py` | 249 | Transcript/framework readers |
| `violation_pack/jurisprudence.py` | 127 | JurisprudenceProvider impl |
| `violation_pack/confidence.py` | 117 | Confidence derivation formula (configurable floor) |
| `violation_pack/pack.py` | 92 | Bundle layout + zip |
| `violation_pack/extensions.py` | 149 | Protocol definitions |
| `violation_pack/mcp_catalog.py` | 203 | MCP catalog CLI |
| `violation_pack/_utils.py` | 9 | Shared helpers (`sha256_text`) |
| `violation_pack/__init__.py` | 164 | Public API surface + factory functions |

### Example files
| File | Lines | Role |
|------|-------|------|
| `examples/refine_cl005.py` | 404 | Canonical CL-005 end-to-end demo |
| `examples/refine_batch.py` | 109 | Thin CLI over `violation_pack.refine_batch_core` (was 754) |
| `examples/run_one.sh` | 240 | Interactive single-violation pipeline |
| `examples/wire_extensions.py` | 99 | Qdrant+Neo4j wiring demo |
| `examples/stage_cl_batch.py` | 639 | Legacy bundle staging (read but not fully reviewed) |

### Test files
| File | Lines | What it tests |
|------|-------|---------------|
| `tests/conftest.py` | 27 | Transcript + framework fixtures from cl005_source |
| `tests/test_layers.py` | 173 | Layer 1-5 functions: idempotence, fabrication rejection, composition |
| `tests/test_end_to_end.py` | 62 | Full CL-005 rebuild: segment count, article count, weighted_score, **11 checks**, validation pass/fail, bundle files exist |
| `tests/test_verifier.py` | 129 | Verifier failure modes: fabricated rol, LLM-verified authority, unknown nexus segment, empty verification_required, unresolved cross-refs |
| `tests/test_extensions.py` | 276 | HashEmbedder determinism, in-memory fake Qdrant for upsert/search, fake Neo4j driver for CYPHER generation, jurisprudence verify() contract enforcement |
| `tests/test_ingesters.py` | 261 | Fake corpus for JurisprudenceIngester (chunking, idempotence, cap), fake transcript bundle for TranscriptIngester (empty skip, audio tags), FrameworkIngester article header parsing |

> Note: the review-time `.venv/` had no `pytest` installed. As of 2026-09-11 the
> suite runs green (`38 passed`) after
> `pip install -e '.[all,test]'` — the extras matter, because without
> `qdrant-client` and `neo4j` eight tests skip silently rather than fail.

## 5. Issues Found

> ⚠️ Superseded in part — see the Resolution Ledger at the top. Items
> 5.1-1/2/3, 5.2-4/5/6/7/8/9, 5.3-11/13/15/16/17/18/19 are **FIXED**. Still
> **OPEN**: 5.2-10 only.
>
> Paths cited below (`/awareness/services/ViolationRefiner/...`) are from the
> original review checkout; the project now lives at
> `/Users/leandrodisconzi/repos/mcp-ecosystem/violation-refiner`. Findings are
> kept verbatim as a historical record.

### 5.1 Critical (broken functionality, security) — ✅ ALL RESOLVED

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

5. **`.env.example` is missing LLM configuration fields** — ✅ FIXED 2026-09-11. A
   `.env.example` now exists and documents the full surface: all 31
   `Settings.from_env()` variables (LLM tuning, provider credentials, Ollama,
   Qdrant, Neo4j incl. the `NEO4J_LOCAL_*` fallbacks, governance) plus
   `MCP_TRANSPORT` / `MCP_HOST` / `MCP_PORT`.
   - Original finding, kept verbatim:
   - File: `/awareness/services/ViolationRefiner/.env.example`
   - The code (`config.py`) reads: `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `LLM_TOKEN_BUDGET`, `LLM_TIMEOUT_SECONDS`
   - The `.env.example` only documents embedding configs — none of the LLM configs are documented
   - `.env.example` also uses `NEO4J_LOCAL_*` prefix names but `config.py:158-166` falls back to `NEO4J_*` names — the fallback names are undocumented
   - Note: the original file also carried `EMBEDDING_MODEL` / `EMBEDDING_DIM`
     entries that **no module reads**; those were dropped rather than carried
     forward, and `tests/test_catalog_sync.py` now fails if any advertised env
     var is not actually read by `config.py` or `mcp_server.py`.

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

> Status (2026-09-11): **mostly DONE.** Transcripts, `.bak`, and the tarball
> are gone; `.logs/` and `.run/` are gitignored. **Remaining:** `build/` is
> still not in `.gitignore`.

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

## 7. Improvement Proposals

> Status (2026-09-11): 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9 and 7.10 are
> all **DONE**. 7.5 was closed by adding an automated drift guard rather than by
> generating the catalog dynamically — see the note under 7.5.

### 7.1 Fix the MCP server startup (CRITICAL) — ✅ DONE

**Problem**: `start.sh` advertises HTTP transport but the server only supports stdio. The `nohup` + `tail -f /dev/null |` pattern is known to cause silent exit for stdio MCP servers.

**Proposal A** (if stdio is sufficient):
Replace `start.sh` with a direct stdio invocation that doesn't pretend to be HTTP. Remove `MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT` env vars. Remove the `nohup` + `tail -f /dev/null |` pipe. The `start.sh` should just run the server with appropriate logging:
```bash
"$PYTHON_BIN" -m violation_pack.mcp_server >>"$LOG_DIR/mcp.log" 2>&1 &
```
MCP clients (VS Code, Claude Desktop) connect via stdio; `violation-pack-catalog --format vscode` prints a ready-made client config snippet.
**Proposal B** (if HTTP/SSE is needed):
FastMCP supports SSE transport. The `mcp_server.py` entry point would need to accept `--transport sse --host ... --port ...` arguments, and `start.sh` would use them. But this requires the `mcp` package to support SSE (check version compatibility).

### 7.2 Remove `sys.path` hack in `refine_batch_tool` — ✅ DONE

**File**: `violation_pack/mcp_server.py`, lines 385-390

Move the shared batch logic from `examples/refine_batch.py` into `violation_pack/refine_batch_core.py` (or similar) that can be properly imported. Keep the CLI wrapper in `examples/refine_batch.py` as a thin caller. The `refine_batch_tool` in the MCP server would then do:
```python
from violation_pack.refine_batch_core import run
```
instead of the current `sys.path` manipulation.

### 7.3 Create `docs/mcp_mapping.md` — ✅ DONE

The file was created rather than removing the references, because the README's
tool table gives names only: `docs/mcp_mapping.md` supplies the tool → library
function → `file:line` → UI-step mapping, and records the one tool with no
library counterpart (`init_violation`, `mcp_server.py:101`) plus the fact that
`v11_enrichment_integrity` lives in `verifier.py`, not `validation.py`.

### 7.4 Complete `.env.example` with all configurable fields — ✅ DONE

The suggested fields below were used as the starting point; the shipped file
groups all **31** `Settings.from_env()` variables by provider and adds the three
`MCP_*` transport variables that `mcp_server.main()` reads directly.
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

> ✅ Note (2026-09-11): `.env.example` now exists. The full set of variables
> `config.py` reads also includes `QDRANT_URL`, `QDRANT_API_KEY`,
> `QDRANT_COLLECTION_PREFIX`, `NEO4J_DATABASE`, the per-provider `*_MODEL`
> vars, and `OLLAMA_HOST` / `OLLAMA_EMBED_MODEL`. The phantom
> `EMBEDDING_MODEL` / `EMBEDDING_DIM` names that appeared in the old example
> were **not** carried forward, because no module reads them.

### 7.5 Update `mcp_catalog.py` to match actual registered tools — ✅ DONE

*(As recorded in the 2026-05-16 audit.)* The catalog then listed 15 tools while
the server registered 30. It now lists all **39** real tools, and the two
remaining risks are closed:

- the stale `optional_env` entries (`EMBEDDING_MODEL`, `EMBEDDING_DIM`) were
  replaced with the real names grouped by provider; and
- drift is now detected automatically. `tests/test_catalog_sync.py` parses
  `mcp_server.py` and `config.py` with `ast` and fails if a registered tool is
  missing from the catalog, if the catalog advertises a tool that no longer
  exists, or if it advertises an env var no module reads.

Generating the catalog dynamically by introspecting the built server is still a
reasonable future simplification, but it is no longer needed for correctness.

### 7.6 Make authority verification floor configurable — ✅ DONE

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

### 7.7 Move `_sha256_text()` to a shared utility module — ✅ DONE

`layers.py:36` and `refine_batch.py:53` both define the same function. Move it to `violation_pack/_utils.py` or make it a method on a shared base.

### 7.8 Clean up chat logs — ✅ DONE

Remove `3am_chat_cut_off_to_continue.md`, `5am_respose_cut_out_to_be_continued.md`, and `whole_chat_claude.md` from the repository root. If they contain valuable decision history, extract the relevant decisions and discard the rest. These are ~160KB of raw Claude transcripts.

### 7.9 Make `generate_map.py` a proper tool or remove it — ✅ DONE (removed)

Currently `generate_map.py` hardcodes paths and reads from a non-existent schema. Either:
- Make it a proper CLI tool with `--input` argument that reads from the actual refined JSON schema
- Or remove it (it appears to be a one-off script for a specific report)

### 7.10 Add `build/` to `.gitignore` — ✅ DONE

The runtime-artifacts block now ignores both `build/` and `dist/`.

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
├── _utils.py          [Util]       Shared helpers (sha256_text)
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
├── refine_batch_core.py [Transform] Importable batch-refiner core
├── mcp_server.py      [API]       MCP server with 39 tools
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

### Weaknesses (status as of 2026-09-11)

1. ~~**MCP server startup is broken**~~ ✅ **RESOLVED.** The server reads
   `MCP_TRANSPORT`/`MCP_HOST`/`MCP_PORT`, supports `stdio` and
   `streamable-http`, and exposes `GET /health`; `start.sh` matches.

2. ~~**No importable batch refiner**~~ ✅ **RESOLVED.** Core logic lives in
   `violation_pack/refine_batch_core.py`; `examples/refine_batch.py` is a
   109-line CLI.

3. ~~**`generate_map.py` is dead code**~~ ✅ **RESOLVED (removed).**

4. ~~**Catalog out of sync**~~ ✅ **RESOLVED.** `mcp_catalog.py` lists all 39
   real tools, and `tests/test_catalog_sync.py` fails the suite if the catalog
   and the server ever diverge again.

5. ~~**Missing `docs/mcp_mapping.md`**~~ ✅ **RESOLVED.** Created, along with
   `docs/ui_structural_skeleton.md`.

6. ~~**Start/stop portability**~~ ✅ **RESOLVED.** `start.sh` resolves its
   interpreter rather than hardcoding `.venv`, honours `MCP_PORT`, and probes
   `/health` on a concrete host; `stop.sh` replaced the system-wide `pkill`
   with a reaper scoped to this checkout.

7. **No non-filesystem `FrameworkSource`** — ⚠️ **OPEN.** Only
   `HtmlTranscriptSource` and `MarkdownFrameworkSource` ship. Everything that
   reads a framework must have it on local disk.

### Recommended architectural changes (status)

1. **Decide on MCP transport and make it consistent** — ✅ **DONE.** Both stdio
   and HTTP/SSE are supported and configurable.

2. **Promote `refine_batch.py` to a library module** — ✅ **DONE** (see
   `refine_batch_core.py`).

3. **Generate the MCP catalog dynamically** — ✅ **MITIGATED.** The catalog is
   correct and `tests/test_catalog_sync.py` now enforces sync via AST
   introspection of `mcp_server.py` and `config.py`. Introspecting the *built*
   server remains the more elegant end state.

4. **Add a shared utilities module** — ✅ **DONE** (`violation_pack/_utils.py`).

5. **Create `docs/` directory or remove references** — ✅ **DONE.** `docs/`
   exists with `mcp_mapping.md` and `ui_structural_skeleton.md`.
