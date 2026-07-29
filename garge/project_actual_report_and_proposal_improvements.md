# Garage Project Audit Report

> **Audit Date:** 2026-05-16
> **Scope:** Full codebase at `/awareness/services/garge`
> **Auditor:** OpenClaude (automated comprehensive audit)

---

## 1. Project Overview

### 1.1 What the Project Actually Is

Garage is a **FastAPI-based AI Tools & Services Hub** running on port 8066. It serves as a local development platform wrapping local LLMs (Ollama), a vector database (Qdrant), and diverse ingestion pipelines into a unified OpenAI-compatible REST API. It also exposes MCP (Model Context Protocol) servers for integration with LLM agent frameworks (Claude Desktop, OpenClaude).

**Primary entry point:** `/awareness/services/garge/main.py` -- FastAPI app instance `app` with 13 routers registered.

**Two virtual environments** isolate incompatible dependencies:
- `.venv/` -- API server (FastAPI 0.104.1, starlette 0.27.x, anyio 3.x, sentence-transformers 3.0.0)
- `.venv-mcp/` -- MCP servers (mcp SDK >=1.0.0, httpx >=0.27.1, newer anyio/starlette)

### 1.2 Declared Features vs Reality

The README defines 12+ features. The table below maps each to implementation status:

| Declared Feature | Implemented? | Evidence |
|---|---|---|
| Assistant Core (CRUD + chat) | YES | `api/assistants.py` (531 lines), `core/assistant.py` (497 lines) |
| Qdrant Manager | YES | `routes/qdrant_router.py` (1621 lines) |
| File Management | YES | `api/files.py` (444 lines), inline in `main.py` |
| Chat Completion | YES | `api/chat.py` (309 lines) |
| Prompt Engineering | YES | `api/prompt_engineer.py` (627 lines) |
| Knowledge Base | YES | `api/knowledge_router.py` (434 lines) |
| Legal Ingestion | YES | `routes/legal_ingestion.py` (578 lines), `routes/legal_doc_ingestion_v2.py` (301 lines) |
| Transcript Ingestion | YES | `routes/transcript_ingestion.py` (314 lines) |
| Tools Registry | YES | `data/tools/registry.py` (116 lines), `api/tools.py` (180 lines) |
| Transcribe/Diarization (Pinocchio proxy) | YES | Inline in `main.py` (endpoints `/v1/transcribe`, `/v1/pyannote`, `/v1/voiceprint`) |
| Neo4j Graph (Manus proxy) | YES | `routes/neo4j_router.py` (162 lines) |
| DeepSeek Integration | YES | Inline in `main.py` (`/v1/assistants/deepseek-stream-proxy`, `/api/deepseek/{path}`) |
| External Provider Chat (OpenAI, Anthropic, etc.) | YES | `api/chat.py` routes to OpenAI, Anthropic, Groq, xAI |
| MCP Servers (5 servers) | YES | 5 files in `mcp/servers/` (core, files, ingestion, prompt, qdrant) |
| OpenClaude Agent Integration | YES | `api/openclaude_router.py` (1075 lines) |
| Framework Jurisdiction Enrichment | YES | `services/watch_frameworks.py` (468 lines) |
| Google Drive OAuth | PLACEHOLDER ONLY | Settings exist, no implementation beyond config fields |

---

## 2. Project Structure

### 2.1 Directory Tree

```
/awareness/services/garge/
├── main.py                          # FastAPI entry point (996 lines)
├── requirements.txt                 # API venv dependencies (132 lines)
├── Dockerfile                       # Docker image definition
├── start.sh                         # Startup script (API + 5 MCP servers)
├── stop.sh                          # Graceful shutdown script
├── README.md                        # Project overview documentation
├── BUSINESS_PLAN.md                 # Platform role document
├── PROJECT_STATUS.md                # Live project status
├── AUDIT.md                         # Previous March 2026 audit
├── export_functionalities_collections-qdrant.md  # Qdrant export guide
├── .env.example                     # Environment template
├── .gitignore                       # Git ignore rules
│
├── api/                             # REST API route modules (8 files)
│   ├── assistants.py                # Assistant CRUD (531 lines)
│   ├── chat.py                      # Chat completions (309 lines)
│   ├── files.py                     # File management (444 lines)
│   ├── knowledge_router.py          # Knowledge base queries (434 lines)
│   ├── openclaude_router.py         # OpenClaude agent integration (1075 lines)
│   ├── prompt_engineer.py           # Prompt lab (627 lines)
│   ├── schemas.py                   # Pydantic models (802 lines)
│   ├── threads.py                   # Threads/messages (312 lines)
│   └── tools.py                     # Tool CRUD (180 lines)
│
├── routes/                          # Backend routing modules (5 files)
│   ├── legal_ingestion.py           # V1 legal ingestion (578 lines)
│   ├── legal_doc_ingestion_v2.py    # V2 enhanced legal ingestion (301 lines)
│   ├── transcript_ingestion.py      # Transcript ingestion (314 lines)
│   ├── neo4j_router.py              # Neo4j graph proxy (162 lines)
│   └── qdrant_router.py             # Qdrant operations (1621 lines) — LARGEST FILE
│
├── core/                            # Business logic core (5 files + 1 dir)
│   ├── assistant.py                 # AssistantCore class (497 lines)
│   ├── file_processor.py            # Text extraction (42 lines)
│   ├── local_llm.py                 # Ollama HTTP client (314 lines)
│   ├── memory.py                    # SQLite conversation memory (175 lines)
│   ├── qdrant_client.py             # Canonical shim (18 lines) → services/qdrant_client.py
│   └── ingestion/                   # Ingestion pipeline submodules
│       ├── ingestion_pipeline.py    # Pipeline orchestrator (351 lines)
│       ├── document_processor.py    # Multi-format reader (487 lines)
│       ├── embedding_generator.py   # SentenceTransformer wrapper (41 lines)
│       ├── vector_store.py          # Qdrant operations (355 lines)
│       ├── transcript_processor.py  # Transcript chunking (317 lines)
│       └── legal_document_processor.py  # Legal section extraction (344 lines)
│
├── config/                          # Configuration
│   └── settings.py                  # Pydantic BaseSettings (142 lines)
│
├── services/                        # Service layer (6 files)
│   ├── qdrant_client.py             # Canonical Qdrant singleton (171 lines)
│   ├── embedding_service.py         # Multi-model embedding (169 lines)
│   ├── legal_document_ingestor.py   # CSV legal ingestion (627 lines)
│   ├── legal_doc_processor.py       # Legal pipeline (559 lines)
│   ├── legal_qdrant_config.py       # Optimized Qdrant collections (102 lines)
│   └── watch_frameworks.py          # Jurisdiction watcher (468 lines)
│
├── utils/                           # Utility modules (3 files)
│   ├── document_ingestor.py         # Smart chunking + doc type detection (405 lines)
│   ├── document_processor.py        # PDF text extraction (242 lines)
│   └── legal_csv_processor.py       # CSV cleaning + metadata extraction (343 lines)
│
├── data/tools/                      # Tool registry (18 items)
│   ├── registry.py                  # ToolRegistry singleton (116 lines)
│   ├── base_tool.py                 # BaseTool ABC (53 lines)
│   ├── json_tool.py                 # JSON-defined tools (5181 bytes)
│   ├── mcp_tool.py                  # MCP tool wrapper
│   ├── deep_reasoning.py            # Deep reasoning tool
│   ├── deepseek_client.py           # DeepSeek API client
│   ├── web_search.py                # Web search tool
│   ├── time_now.py                  # Time utility tool
│   ├── deep_reasoning/              # Sub-module
│   ├── deep_reasoning_timeline/     # Sub-module
│   ├── deep_reasoning_violation/    # Sub-module
│   ├── document_processing/         # Sub-module
│   ├── filesystem/                  # Sub-module
│   ├── http/                        # Sub-module
│   ├── indexing/                    # Sub-module
│   ├── integrations/                # Sub-module
│   ├── medical/                     # Sub-module
│   ├── reasoning/                   # Sub-module
│   ├── summarization/               # Sub-module
│   ├── web_search/                  # Sub-module
│   └── user_defined/                # User JSON tool definitions
│
├── mcp/                             # Model Context Protocol servers
│   ├── README.md                    # MCP tool list
│   ├── MCP_ARCHITECTURE.md          # Architecture standard doc (468 lines)
│   ├── requirements.txt             # MCP-only deps (2 lines: mcp>=1.0.0, httpx>=0.27.1)
│   ├── MCP_READINESS_REPORT_2026-04-24.md
│   └── servers/                     # 5 independent MCP server files
│       ├── common.py                # Shared HTTP client (171 lines)
│       ├── core_server.py           # Assistants, chat, threads, tools (578 lines)
│       ├── files_server.py          # File storage tools (159 lines)
│       ├── ingestion_server.py      # Legal + transcript ingestion (422 lines)
│       ├── prompt_server.py         # Prompt engineering tools (116 lines)
│       └── qdrant_server.py         # Qdrant operations (252 lines)
│
├── scripts/                         # Operational scripts (18 files)
│   ├── build_unirg_navigable.py     # UNIRG navigation builder
│   ├── check_qdrant_health.py       # Qdrant health checker
│   ├── document_crawler.py          # Legal document crawler
│   ├── document_crawler_gpi.py      # GPI crawler variant
│   ├── embed_case_dir_runner.py     # Case directory embedder
│   ├── ingest_legal_csv.py          # CSV ingestion runner
│   ├── quickstart_legal_ingestion.sh# Quickstart script
│   ├── reproduce_deepseek.py        # DeepSeek reproduction
│   ├── test_chunking.py             # Chunking test
│   ├── test_doc_extraction.py       # Document extraction test
│   ├── test_empty_filter.py         # Empty filter test
│   ├── tjrs_scraper.py              # TJRS court scraper (~57KB)
│   ├── tjrs_scraper_2.py            # TJRS scraper variant (~57KB)
│   ├── transcript_analyzer.py       # Transcript analysis
│   ├── unirg-sidebar-scraper.py     # UNIRG sidebar scraper
│   ├── website-crawler.py           # Generic website crawler
│   ├── website-crawler-gpi.py       # GPI website crawler
│   └── website-crawler-rs.py        # RS website crawler
│
├── docs/                            # Additional documentation (8 files)
│   ├── PROJECT_OVERVIEW.md
│   ├── IMPLEMENTATION_SUMMARY.md
│   ├── QUICK_REFERENCE.md
│   ├── README-LEGAL-INGESTION.md
│   ├── TRANSCRIPT_INGESTION_GUIDE.md
│   ├── README-QDRANT.md
│   ├── QDRANT_API_GUIDE.md
│   ├── TRANSCRIPT_SYSTEM_README.md
│   └── collection_data_info/        # Qdrant collection payloads
│
├── static/                          # Static assets
│   ├── templates/                   # HTML UI templates
│   └── js/                          # JavaScript frontend
│       ├── legal_frameworks/        # Framework analyzer files
│       ├── legalframeworks-repository/  # Jurisdiction index
│       └── garage-fragmented/       # Garage UI modules
│
├── .github/                         # GitHub integration
│   ├── agents/                      # OpenClaude agent definitions (*.agent.md)
│   ├── prompts/                     # Prompt templates
│   └── instructions/                # Instruction sets
│
├── workspace/                       # Case research workspaces
```

### 2.2 Unusual Items Noted

1. **Two nearly identical `tjrs_scraper.py` files** (56,728 bytes and 56,731 bytes) in `scripts/` -- `tjrs_scraper.py` and `tjrs_scraper_2.py`. These are 99.9% duplicates.
2. **Two nearly identical `website-crawler.py` variants** (`website-crawler-gpi.py` 22,959 bytes, `website-crawler-rs.py` 15,493 bytes, `website-crawler.py` 13,347 bytes) -- three variants with overlapping functionality.
3. **`start.sh` uses MCP server startup pattern** `sh -c "cd /tmp && tail -f /dev/null | ..."` -- this is a workaround for the MCP stdio/nohup issue documented in team memory. The `tail -f /dev/null` keeps stdin open so the MCP stdio transport doesn't exit.
4. **`.log/` directory exists on filesystem** but `.gitignore` lists `logs/` (without the dot prefix). Log files may be at risk of being committed.
5. **`routes/__init__.py` is empty** (1 line) -- the routes directory is not a proper Python package.
6. **Dual `LegalDocumentChunker` classes** exist in both `core/ingestion/legal_document_processor.py` (line 238) and `services/legal_doc_processor.py` (line 257). These are near-identical code clones; `core/ingestion/` version uses `LegalDocumentExtractor` from within the same file while `services/` version has a standalone `LegalDocumentExtractor` in the same file.

### 2.3 .gitignore Concerns

File `.gitignore` targets `logs/` but actual directory is `.logs/` (with leading dot). The startup script creates directories `$LOG_DIR` which maps to `.logs/`. This means log files with potential sensitive data could be committed if `.logs/` is not explicitly ignored.

---

## 3. Feature Trace

### 3.1 Feature Completeness Matrix

| Feature | Router | Endpoints | Validated | Notes |
|---|---|---|---|---|
| Health | main.py inline | GET /health | Yes | Simple status check |
| File Management | api/files.py + main.py | CRUD + list/read/upload | Yes | Path traversal protection added |
| Chat Completions | api/chat.py | POST /v1/chat/completions, GET /v1/models | Yes | Routes to external providers |
| Assistants | api/assistants.py | Full CRUD + chat + knowledge query | Yes | JSON file storage |
| Qdrant | routes/qdrant_router.py | Collections, search, structured ingest | Yes | Largest module (1621 lines) |
| Knowledge Base | api/knowledge_router.py | Query, ingest text/file, collection stats | Yes | Has buggy imports (see Section 4.2) |
| Prompt Engineering | api/prompt_engineer.py | Generate, analyze, variations, optimize, evaluate | Yes | Uses Ollama directly |
| Legal Ingestion V1 | routes/legal_ingestion.py | Upload CSV, search, collections CRUD | Yes | Uses LegalDocumentIngestor |
| Legal Ingestion V2 | routes/legal_doc_ingestion_v2.py | Enhanced + folder ingestion, analyze | Yes | Uses LegalDocumentPipeline |
| Transcript Ingestion | routes/transcript_ingestion.py | Analyze, ingest-enhanced, ingest-json | Yes | Speaker-aware chunking |
| Threads | api/threads.py | CRUD + messages + runs | Partial | File association TODO at line 307 |
| Tools | api/tools.py | CRUD + execute + deep_reasoning | Yes | JsonTool + registry |
| Neo4j | routes/neo4j_router.py | Thin proxy to Manus | Yes | Block destructive queries by default |
| DeepSeek | main.py inline | Stream proxy + gateway | Yes | Direct HTTP calls |
| Pinocchio | main.py inline | Transcribe, pyannote, voiceprint | Yes | Proxy endpoints |
| MCP Servers | mcp/servers/*.py | 5 servers, ~50+ tools | Yes | Wraps all Garage endpoints |
| OpenClaude | api/openclaude_router.py | Agent CRUD, import/export, run | Yes | Largest single API file (1075 lines) |
| Framework Watcher | services/watch_frameworks.py | Directory monitor + jurisdiction enrichment | Yes | watchdog optional |

### 3.2 Dead/Unused Code

1. **`api/knowledge_router.py` line 18:** `from networkx import cut_size` -- `cut_size` is a function reference from networkx, NOT an integer. Used at line 378 as `chunk_size=cut_size` which will cause `TypeError` at runtime if that code path is ever reached.

2. **`api/knowledge_router.py` lines 344-351:** References to undefined variable `metadata` -- the variable is only defined inside the `if metadata_json:` block on line 106 of `ingest_file`. When called in the `ingest_text` flow, `metadata` variable does not exist.

3. **`api/knowledge_router.py` line 12:** `from core.ingestion import IngestionPipeline` -- this import path does not exist. The actual class is at `core.ingestion.ingestion_pipeline.IngestionPipeline`. This would cause `ImportError` at runtime.

4. **`api/files.py` line 28:** `from networkx import cut_size` -- same unused import as in `knowledge_router.py`. This function is never used in `files.py`.

5. **`routes/qdrant_router.py` lines 52-122 and 248-319:** `TEST_SAMPLES` dictionary defined twice with nearly identical content -- the first definition at line 52 is dead code (the second at line 248 is the one that's used).

6. **3 identical `test_*.py` scripts in `scripts/`:** `test_chunking.py`, `test_doc_extraction.py`, `test_empty_filter.py` -- these are ad-hoc test scripts, not part of a proper test suite.

7. **`services/legal_doc_processor.py` and `core/ingestion/legal_document_processor.py`:** Complete duplication of `LegalDocumentExtractor`, `LegalDocumentChunker`, `LegalSectionType`, `LegalDocumentSection` classes. These two files share ~90% of their code but are independently maintained.

8. **`scripts/tjrs_scraper.py` and `scripts/tjrs_scraper_2.py`:** Near-identical scraper scripts (differ by 3 bytes). One is dead code.

### 3.3 Error Handling Audit

| Module | Error Handling | Issues |
|---|---|---|
| `api/files.py` | Good -- proper HTTPException usage, path validation | None |
| `api/chat.py` | Adequate -- returns structured error responses | HTTP errors from external providers return generic messages |
| `api/knowledge_router.py` | Poor -- undefined variables, broken imports | See Section 3.2 items 1-3 |
| `api/prompt_engineer.py` | Adequate -- catches Ollama exceptions | Bare except blocks without logging details |
| `api/threads.py` | Good -- EmergencyAssistantCore fallback on DB corruption | None |
| `core/assistant.py` | Adequate -- returns fallback on all failures | Can fail silently without surfacing root cause |
| `core/memory.py` | Good -- SQLite recovery, parameterized queries | None |
| `core/ingestion/document_processor.py` | Good -- multi-strategy DOC extraction with clear error messages | None |
| `routes/qdrant_router.py` | Adequate -- most handlers have try/except | Some search operations return empty list on error (may mask failures) |
| `routes/transcript_ingestion.py` | Good -- proper HTTPException with detail messages | None |
| `services/watch_frameworks.py` | Good -- handles missing watchdog gracefully | None |

---

## 4. Code Quality & Architecture Assessment

### 4.1 Architectural Patterns

**Good patterns observed:**
- Canonical Qdrant singleton in `services/qdrant_client.py` with thread-safe lock (result of prior audit remediation)
- Compatibility shim `core/qdrant_client.py` → `services/qdrant_client.py` for backward compatibility
- MCP server isolation via separate virtual environment (`.venv-mcp`)
- Shared HTTP client (`mcp/servers/common.py`) used by all MCP servers
- Multi-server MCP architecture (5 domain-split servers) with documented architecture standards in `MCP_ARCHITECTURE.md`
- Prompt Engineering Lab with comprehensive evaluation/metrics pipeline
- OpenClaude integration using markdown-based agent format with RFC 2822-style fields

**Concerning patterns:**
- `main.py` still contains inline endpoint definitions for DeepSeek proxy, Pinocchio proxy, Manus proxy, and file management (~350 lines of non-router code)
- `routes/qdrant_router.py` at 1621 lines is severely oversized and needs decomposition (noted in PROJECT_STATUS.md as GAR-01)
- Three separate ingestion systems (V1 legal, V2 legal, transcript) with significant code duplication across `core/ingestion/`, `services/`, and `routes/`
- `api/openclaude_router.py` at 1075 lines is single-responsibility but very large
- API and routes directories are separate but serve the same purpose (historical artifact of restructuring)

### 4.2 Specific Bug Instances

| Bug ID | File | Line(s) | Description | Severity |
|---|---|---|---|---|
| B1 | `api/knowledge_router.py` | 18 | `from networkx import cut_size` -- cut_size is a function, not integer. Used as `chunk_size=cut_size` at line 378 | HIGH -- runtime TypeError |
| B2 | `api/knowledge_router.py` | 344-351 | Undefined variable `metadata` in text ingestion flow; only defined in file ingestion path at line 106 | HIGH -- NameError |
| B3 | `api/knowledge_router.py` | 12 | `from core.ingestion import IngestionPipeline` -- module path does not exist. Correct would be `from core.ingestion.ingestion_pipeline import IngestionPipeline` | CRITICAL -- ImportError prevents module load |
| B4 | `api/files.py` | 28 | `from networkx import cut_size` -- unused import | LOW -- dead import only |
| B5 | `api/threads.py` | 307 | `TODO: Implement logic to associate file_id with thread_id in your DB` -- incomplete feature | MEDIUM -- incomplete feature |
| B6 | `routes/qdrant_router.py` | 52-122 | `TEST_SAMPLES` defined twice, first definition is dead code | LOW -- unused variable |
| B7 | `routes/qdrant_router.py` | ~90, ~310 | Embedding models loaded at module import time (module-level `SentTransformer()` calls) -- slows startup, memory overhead even if Qdrant not used | MEDIUM -- eager loading |
| B8 | `utils/document_ingestor.py` | 400 | `from routes.qdrant_router import embedding_models` -- import at call site at bottom of function, creates circular dependency risk | MEDIUM -- late import in function body |
| B9 | `routes/qdrant_router.py` | 1094 | Hardcoded path `./static/latam/violations_data/Case/latam_fiasco/transcript_analyses` | MEDIUM -- hardcoded path |

### 4.3 Security Assessment

| Finding | Status | Detail |
|---|---|---|
| Path traversal in file endpoints | FIXED | `_safe_path()` and `_safe_file_path()` helpers resolve against project root |
| CORS wildcard | FIXED | Now reads `ALLOWED_ORIGINS` env var; defaults to `http://localhost:8066` |
| Hardcoded dev paths | FIXED | Replaced with env-var driven Path objects |
| JWT secret | FIXED | Strong secrets generated via `openssl rand -hex 32` |
| `.env` in repo | FIXED | `.gitignore` added, `.env.example` created |
| Credential rotation | PENDING | Must manually rotate Qdrant, Ollama, Google keys (from previous audit) |
| No authentication layer | OPEN | All endpoints are unauthenticated; acceptable for local dev, must not be deployed publicly (AUDIT.md A8) |
| `DEEPSEEK_API_KEY` unset guard | FIXED | Now checks and returns 500 before sending `Bearer None` headers (AUDIT.md R5) |
| `.log/` directory not in `.gitignore` | OPEN | Directory is `.log/` but `.gitignore` lists `logs/` (no dot) |
| Manus/Neo4j proxy allows arbitrary Cypher | PARTIALLY MITIGATED | Destructive keywords blocked by default but configurable via env |

### 4.4 Test Coverage

**There is no formal test suite.** The project has zero unit tests, zero integration tests, zero end-to-end tests. What exists:

- `scripts/test_chunking.py` (1066 bytes) -- ad-hoc chunking test
- `scripts/test_doc_extraction.py` (937 bytes) -- ad-hoc extraction test
- `scripts/test_empty_filter.py` (692 bytes) -- ad-hoc empty filter test
- `data/tools/user_defined/test_calculator.py` -- a test tool registration, not a test
- `static/js/garage-fragmented/garage-tests.js` -- frontend JS tests (not reviewed in detail)

**Test coverage: 0%** (no pytest, unittest, or any testing framework configured).

### 4.5 Buildability

- **Dockerfile works** but copies the entire project directory including `.venv/` and `.venv-mcp/` -- these should be in `.dockerignore`
- **No `setup.py` or `pyproject.toml`** -- project has no installable package definition
- **`requirements.txt`** is valid with pinned versions (starlette==0.27.1, anyio==3.7.1) to maintain API compat while MCP uses its own venv for newer anyio
- **MCP server startup** requires a `socat`-style stdin-keeper workaround (`tail -f /dev/null |`) due to the nature of MCP stdio transport with nohup (documented in team memory)

---

## 5. Dependencies & Configuration Audit

### 5.1 Python Dependencies Analysis

**API Virtual Environment (`.venv`):**
- `fastapi>=0.104.0,<0.105.0` -- major version locked for stability
- `starlette==0.27.1`, `anyio==3.7.1` -- pinned to avoid MCP incompatibility
- `sentence-transformers==3.0.0` -- pulls in `torch>=2.6.0` (~2GB)
- `qdrant-client==1.17.0` -- vector DB client
- `ollama>=0.4.0` -- local LLM client
- `pypdf>=3.17.0`, `pdfplumber`, `PyMuPDF` -- three PDF libraries (noted in prior audit, PDFPlumber has been removed since)
- `langchain>=0.1.0`, `langchain-text-splitters` -- used as dependency but only for the text splitter fallback

**MCP Virtual Environment (`.venv-mcp`):**
- `mcp>=1.0.0` -- MCP SDK
- `httpx>=0.27.1` -- async HTTP client

**Key concern:** `torch>=2.6.0` has no upper bound. This can pull a multi-GB CUDA installation. Consider `torch>=2.0.0,<3.0.0`.

### 5.2 Configuration Audit

`config/settings.py` uses Pydantic `BaseSettings` with `extra = "allow"` -- this means unknown env variables are silently accepted. Key observations:

- `jwt_secret` defaults to `"dev-secret-change-me"` (placeholder) -- actual env overrides this
- `qdrant_url` is `Optional[str]` (None default) -- if unset, falls back to `qdrant_host`/`qdrant_port`
- Qdrant chunking parameters are configurable via environment (7 parameters, lines 41-56)
- `init_directories()` called at module import time (line 141) -- causes filesystem side effects on import
- Feature flags `enable_tools`, `enable_vision`, `enable_embeddings` are defined but `enable_vision` and `enable_embeddings` have no usage found in codebase
- `data_dir` is a relative string `"data"` resolved against `base_dir` at runtime -- safe but could cause issues if working directory changes
- `google_drive_api_key`, `runpod_api_key`, `datajud_api_key`, `argus_api` are defined but Google Drive/Runpod/DataJud/Argus integrations are either placeholders or external service stubs

### 5.3 Integration Dependencies

| Service | Required? | Default URL | Configurable? |
|---|---|---|---|
| Ollama | Yes (core LLM) | `http://localhost:11436` | Via `OLLAMA_HOST` env |
| Qdrant | Yes (vector DB) | `localhost:6333` | Via `QDRANT_URL` or host/port |
| Manus (Neo4j proxy) | Optional | `http://localhost:8000` | Via `MANUS_API_URL` env |
| Pinocchio (audio) | Optional | Configurable | Via env vars |
| DeepSeek API | Optional | External | Via `DEEPSEEK_API_KEY` env |
| Google Drive | Placeholder | N/A | Not implemented |
| RunPod | Placeholder | N/A | Not implemented |

---

## 6. Non-Obvious Functionality & Integration Points

### 6.1 Hidden/Undocumented Features

1. **MCP Server Stdio Workaround:** `start.sh` lines 90-99 use `sh -c "cd /tmp && tail -f /dev/null | ... python server.py"` to keep MCP stdio transport alive under nohup. This is a non-obvious workaround for MCP's strict stdio requirement and is documented in team memory.

2. **OpenClaude Agent Format:** The system supports importing/exporting agents in a markdown format with YAML frontmatter, stored in `.agent.md` files. This is documented in `api/openclaude_router.py` but not mentioned in the main README's feature list.

3. **Framework Jurisdiction Enrichment:** The `services/watch_frameworks.py` service monitors a legal frameworks directory and automatically infers jurisdiction (country) and flag from entity names (e.g., "ANAC" → Brazil flag). This is a standalone service not referenced in the README.

4. **Dual Ingestion Systems:** There are two completely separate legal document ingestion systems:
   - V1 (`routes/legal_ingestion.py`): CSV-focused, uses `LegalDocumentIngestor` from `services/`
   - V2 (`routes/legal_doc_ingestion_v2.py`): Section-aware DOCX/PDF, uses `LegalDocumentPipeline` from `services/legal_doc_processor.py`
   - The `IngestionPipeline` in `core/ingestion/` is yet a THIRD ingestion system, used by `api/knowledge_router.py` (which has broken imports)

5. **Compatibility Shim Chain:** `config/qdrant_config.py` → `core/qdrant_client.py` → `services/qdrant_client.py` -- there are three layers of import indirection for Qdrant client configuration.

6. **DeepSeek Model Routing:** The DeepSeek proxy at `main.py` line ~700 supports model routing with provider mapping (OpenAI, Ollama, local) based on the requested model name and configured external API keys.

7. **Neo4j via Manus Proxy:** `routes/neo4j_router.py` wraps Manus service endpoints at two paths: `/cypher` (POST) and `/clear-db` (POST). It blocks destructive keywords like `DELETE`, `DETACH DELETE`, `DROP`, `REMOVE` by default but this is configurable.

### 6.2 Integration Paths Discovered Through Code

- **Garage ↔ Manus:** HTTP proxy on `/manus/{path}` forwarding to `MANUS_API_URL`
- **Garage ↔ Pinocchio:** HTTP proxy on `/v1/transcribe`, `/v1/pyannote`, `/v1/voiceprint`
- **Garage ↔ DeepSeek:** HTTP gateway on `/api/deepseek/{path}` with API key auth
- **Garage ↔ Ollama:** Direct HTTP to `localhost:11436` via `ollama` Python package
- **Garage ↔ Qdrant:** Direct via `qdrant-client` on `localhost:6333` or Qdrant Cloud via `QDRANT_URL`
- **Garage ↔ External LLM Providers:** OpenAI, Anthropic, Groq, xAI routed from `api/chat.py` with per-provider API key support
- **MCP ↔ Garage:** All 5 MCP servers proxy to Garage API via `GARAGE_BASE_URL` with optional `GARAGE_API_KEY` auth
- **OpenClaude ↔ Garage:** Agent import/export via `api/openclaude_router.py`, remote catalog proxy to port 8120

---

## 7. Recommendations & Improvement Proposals

### 7.1 Critical (Immediate Action)

| # | Issue | Action | Effort |
|---|---|---|---|
| C1 | `knowledge_router.py` broken imports (B1-B3) | Fix import of `IngestionPipeline` to correct module path; remove `from networkx import cut_size`; fix undefined `metadata` variable | 1 hour |
| C2 | No test suite | Create basic pytest harness with smoke tests for health endpoint and assistant CRUD | 4 hours |
| C3 | `.gitignore` missing `.logs/` | Add `.logs/` to `.gitignore` to prevent log file commits | 1 minute |
| C4 | Credential rotation pending from prior audit | Rotate all API keys listed in AUDIT.md Section 2 (Qdrant, Ollama, Google) | 30 minutes |

### 7.2 High Priority

| # | Issue | Action | Effort |
|---|---|---|---|
| H1 | Decompose `qdrant_router.py` (1621 lines) | Split into crud_router, search_router, ingest_router, structured_router sub-modules | 8 hours |
| H2 | Consolidate duplicate LegalDocumentChunker + Extractor | Choose one canonical location (`core/ingestion/legal_document_processor.py` or `services/legal_doc_processor.py`) and have all consumers import from there | 3 hours |
| H3 | Remove `main.py` inline business logic | Move DeepSeek proxy, Pinocchio proxy, and file management inline handlers into dedicated API modules | 4 hours |
| H4 | Consolidate ingestion systems | Merge V1/V2/core ingestion into unified pipeline with configurable strategies | 12 hours |
| H5 | Conditional embedding model loading | Load SentenceTransformer models lazily (on first use) instead of at module import time in `routes/qdrant_router.py` | 2 hours |
| H6 | Remove dead TEST_SAMPLES definition | Remove lines 52-122 in `routes/qdrant_router.py` | 1 minute |

### 7.3 Medium Priority

| # | Issue | Action | Effort |
|---|---|---|---|
| M1 | Remove dead code in `api/files.py` | Remove unused `from networkx import cut_size` import | 1 minute |
| M2 | Complete thread file_id association | Implement the TODO at `api/threads.py` line 307 | 2 hours |
| M3 | Remove duplicate scraper scripts | Keep one `tjrs_scraper.py`, remove `tjrs_scraper_2.py`. Consolidate `website-crawler*.py` variants | 1 hour |
| M4 | Add `torch` upper bound | Change `torch>=2.6.0` to `torch>=2.0.0,<3.0.0` to prevent accidental multi-GB CUDA install | 1 minute |
| M5 | Replace hardcoded path in `qdrant_router.py:1094` | Move `./static/latam/violations_data/Case/latam_fiasco/transcript_analyses` to config/settings | 30 minutes |
| M6 | Remove Google Drive/RunPod placeholder config | Remove unused `google_drive_api_key`, `runpod_api_key`, `datajud_api_key`, `argus_api` from settings or add TODO comments | 30 minutes |
| M7 | Remove unused feature flags | `enable_vision` and `enable_embeddings` have no consumers in the codebase; add implementations or remove | 1 hour |
| M8 | Create `.dockerignore` | Prevent `.venv/`, `.venv-mcp/`, `.git/`, `.log/`, `__pycache__/` from being copied into Docker image | 30 minutes |

### 7.4 Low Priority / Nice to Have

| # | Issue | Action | Effort |
|---|---|---|---|
| L1 | Add `pyproject.toml` | Define project metadata, dependencies, and scripts properly | 2 hours |
| L2 | Add type hints throughout | Many functions lack return type annotations | Ongoing |
| L3 | Replace `init_directories()` module-level side effect | Move directory initialization into app lifespan handler instead of import time | 1 hour |
| L4 | Document integration architecture | Create architecture diagram showing Garage ↔ service interactions | 2 hours |
| L5 | Add pre-commit hooks | Add ruff/mypy/black pre-commit hooks for consistent code quality | 2 hours |

### 7.5 Architecture Improvement Proposal

**Recommended Target Architecture:**

```
api/                    # REST API layer (pure HTTP)
├── assistants.py
├── chat.py
├── files.py
├── deepseek.py         # NEW: extract from main.py
├── pinocchio.py        # NEW: extract from main.py
├── manus.py            # NEW: extract from main.py (replace routes/neo4j_router.py)
├── knowledge.py        # RENAMED: from knowledge_router.py (fix all bugs)
├── openclaude.py
├── prompt.py           # RENAMED: from prompt_engineer.py
├── threads.py
├── tools.py
└── schemas.py

ingestion/              # Unified ingestion (merge core/ingestion + routes/ + services/)
├── pipeline.py         # Canonical IngestionPipeline
├── document_processor.py   # Multi-format reader
├── embedding_generator.py  # SentenceTransformer wrapper
├── vector_store.py         # Qdrant operations (optimized collections)
├── transcript_processor.py # Transcript chunking
├── legal_processor.py      # Legal section extraction (canonical - remove duplicate)
├── legal_ingestion_v1.py   # CSV-focused ingestion
├── legal_ingestion_v2.py   # Section-aware DOCX/PDF ingestion
└── transcript_ingestion.py # Speaker-aware transcript ingestion

core/                   # Business logic
├── assistant.py
├── llm.py              # RENAMED: from local_llm.py
├── memory.py
├── file_processor.py
└── qdrant_client.py    # Shim (keep)

services/               # Backend service integrations
├── qdrant_client.py    # Canonical Qdrant singleton
├── embedding_service.py
└── watch_frameworks.py

mcp/                    # Model Context Protocol (unchanged)
└── servers/

scripts/                # Operational scripts (clean up duplicates)
tests/                  # NEW: pytest test suite
```

---

## 8. Code Metric Summary

| Metric | Count |
|---|---|
| Total Python source files | ~65 (excluding venvs, git, caches) |
| Total lines of Python | ~18,500+ (estimated) |
| Largest file | `routes/qdrant_router.py` (1,621 lines) |
| Second largest | `api/openclaude_router.py` (1,075 lines) |
| Third largest | `main.py` (996 lines) |
| API endpoints | ~110+ (across all routers + inline handlers) |
| MCP tools | ~50+ (across 5 servers) |
| Virtual environments | 2 (`.venv` API, `.venv-mcp` MCP) |
| Scripts (operational) | 18 |
| Documentation files (md) | ~15 |
| Test files | 0 (formal), 3 (ad-hoc scripts) |
| Buggy imports | 3 (knowledge_router.py) |
| Code clones | 4 pairs (LegalDocumentChunker, Extractor, tjrs_scraper, TEST_SAMPLES) |
| Hardcoded paths | 1 remaining (`qdrant_router.py:1094`) |
| Security issues open | 2 (no auth layer, .logs/ not in .gitignore) |

---

## 9. Summary Assessment

### Strengths

1. **Comprehensive MCP integration:** The multi-server MCP architecture with documented standards is well-designed and covers nearly all Garage backend endpoints.
2. **Security improvements from prior audit:** Path traversal, CORS, and hardcoded credential issues have all been properly fixed.
3. **Multi-format ingestion:** The system handles PDF, DOCX, DOC, EML, JSON, CSV, Markdown, HTML, XML, and code files with appropriate extractors and multi-strategy fallbacks.
4. **OpenAI API compatibility:** The assistant/thread/message/run abstraction provides a familiar API surface for LLM application integration.
5. **Speaker-aware transcript processing:** The transcript pipeline with speaker role detection and conversation flow preservation is a sophisticated feature.
6. **Dual venv isolation:** The `.venv`/`.venv-mcp` separation successfully isolates incompatible dependency versions.

### Critical Weaknesses

1. **No test suite:** Zero formal tests for an 18,500+ line codebase is a significant risk, especially given the multiple ingestion pipelines and complex state management.
2. **Buggy knowledge_router.py:** Three distinct bugs (broken import, undefined variable, wrong type for chunk_size) make the knowledge base ingestion flow non-functional in its current state.
3. **Unsustainable qdrant_router.py:** At 1,621 lines with mixed concerns (CRUD, search, structured ingest, file ingest, case directory embedding), this module is a maintenance bottleneck.
4. **Code duplication:** Four separate code clone pairs across the codebase increase maintenance burden and risk of divergent bug fixes.
5. **`main.py` bloat:** Despite prior cleanup reducing it from 894 to 639 lines (per AUDIT.md), it has since grown back to 996 lines with inline DeepSeek, Pinocchio, and Manus proxy handlers.
6. **Triple ingestion system:** Three separate ingestion implementations (V1 legal, V2 legal, core) with overlapping functionality and no clear canonical path.

### Overall Rating: **C+**

The project has good architecture fundamentals (API design, MCP integration, OpenAI compatibility) but is held back by critical maintainability issues (no tests, code duplication, oversized modules, broken imports). The prior audit remediation was thorough but the codebase has regressed since then. Immediate action on the critical findings (C1-C4) would bring it to B- status; completing the high-priority items would reach B+.

---

*Report generated by OpenClaude automated audit, 2026-05-16. All claims backed by direct source file inspection.*
