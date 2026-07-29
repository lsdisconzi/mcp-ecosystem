# JurisSearch — Complete Pipeline & Customer Journey Documentation

## Table of Contents
1. [System Architecture Overview](#1-system-architecture-overview)
2. [Customer Journey: End-to-End Walkthrough](#2-customer-journey-end-to-end-walkthrough)
3. [Component Deep-Dive](#3-component-deep-dive)
4. [Data Flow & Pipelines](#4-data-flow--pipelines)
5. [File System Layout](#5-file-system-layout)
6. [API Reference Map](#6-api-reference-map)
7. [Indexing, Storage & Retrieval](#7-indexing-storage--retrieval)
8. [Background Processes](#8-background-processes)

---

## 1. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        USER FRONTEND                                  │
│  tjrs-frontend/ (React 19 + Vite) — served at /juris on port 8000   │
│  Views: Chat | Search Fields | Results | Downloads | Master Index   │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ HTTP (fetch)
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     FASTAPI BACKEND (main.py, port 8000)              │
│  ┌──────────────┬──────────────┬──────────────┬───────────────────┐ │
│  │ routes_chat  │routes_search │routes_downld │routes_frontend    │ │
│  │ (LLM chat,   │(scraper      │(download     │(static serving)   │ │
│  │  file upload)│ dispatch,    │ inteiro teor,│                   │ │
│  │              │ poll status,  │ poll status, │                   │ │
│  │              │ results)      │ auto-ingest) │                   │ │
│  └──────────────┴──────────────┴──────────────┴───────────────────┘ │
│                                                                      │
│  Background Threads (lifecycle.py):                                   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ Storage Watcher (DOCX + JSON pipeline, every 10s)             │   │
│  │ Master Indexer (juris_indexer.py, every 30s)                  │   │
│  │ Pipeline Catch-Up (straggler documents, every 5min)           │   │
│  └──────────────────────────────────────────────────────────────┘   │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ HTTP
                    ┌───────────┴──────────────┐
                    ▼                          ▼
        ┌──────────────────┐     ┌──────────────────────┐
        │  Qdrant (vectordb)│     │  Neo4j (graph db)    │
        │  via 8066 API     │     │  via 8066 API        │
        │  juris_br_v1      │     │  Cypher + RAG        │
        │  law_br           │     └──────────────────────┘
        │  legal_framework  │
        │  juris_search_    │              ┌──────────────┐
        │    memory         │              │  DeepSeek API │
        └──────────────────┘              │  (external)   │
                                          └──────────────┘
```

**Key Services/Ports:**
- `localhost:8000` — FastAPI backend (serves frontend + REST API)
- `localhost:8066` — Ollama-Compatible Assistants API (Qdrant, Neo4j, Ollama, Agent management)
- `localhost:8114` — Direct Qdrant management endpoint
- `localhost:8116` — MCP server (optional, Node.js)
- DeepSeek API (`api.deepseek.com`) — external LLM for chat

---

## 2. Customer Journey: End-to-End Walkthrough

### Step 0 — Access the UI
User opens `http://localhost:8000/juris` → `routes_frontend.py` serves `tjrs-frontend/dist/index.html`

### Step 1 — Select Courts
User chooses tribunals from 29 courts:
- **5 dedicated scrapers**: TJRS, TJSP, TJMG, TJRJ, STF
- **22 e-SAJ courts** (shared generic scraper): TJSC, TJPR, TJES, TJBA, TJPE, TJCE, TJMA, TJPB, TJRN, TJAL, TJSE, TJPI, TJPA, TJAM, TJRO, TJTO, TJAC, TJRR, TJAP, TJDFT, TJGO, TJMT, TJMS
- **1 Chile**: Poder Judicial de Chile

Multi-select + "ALL" supported.

### Step 2 — AI-Assisted Field Population (Chat tab)
1. User describes what they're searching for in natural language
2. Optionally uploads a document (`.pdf`, `.docx`, `.txt`, `.md`, `.json`, images)
3. `POST /api/chat` (text) or `POST /api/upload` (file) → `routes_chat.py`
4. Backend calls DeepSeek via `modules/deepseek_client.py` with court-specific system prompt
5. DeepSeek returns `<search_fields>{...}</search_fields>` XML → frontend auto-fills fields
6. Fields pulse to indicate they were updated

### Step 3 — Execute Search
1. User reviews fields, clicks "Executar Busca"
2. `POST /api/search` → `routes_search.py`
3. Background thread per court: instantiates Selenium scraper, calls `scraper.search_with_criteria()`, normalizes results
4. Results persisted to `searches_history/search_{timestamp}_{job_id}.json`
5. Frontend polls `GET /api/search/status/{job_id}` every 3s

### Step 4 — Review Results
- Processo number, Tribunal badge, Relator, Órgão Julgador, Comarca, Data, Ementa preview
- Per-court breakdown
- Downloadable results (those with `inteiro_url`) can be checked/selected

### Step 5 — Download
1. User sets folder name → clicks "Baixar"
2. `POST /api/download` → Selenium scrapers download `.doc`/`.docx`/`.pdf` files
3. Files saved to `jurisprudence_downloads/{folder_name}/` with `.metadata.json` sidecars
4. Frontend polls `GET /api/download/status/{job_id}`

### Step 6 — Post-Download Automation (automatic)
1. **Auto-Extraction**: Each file → `court_extractor.extract_and_ingest()` → structured JSON in `extracted_documents/` + Qdrant ingest
2. **Storage Pipeline**: DOCX conversion (.doc→.docx via LibreOffice) + JSON text extraction
3. **Master Index Rebuild**: `juris_indexer.py` scans all folders, enriches, rebuilds `master_index/master_index.json`, pushes to Qdrant
4. **Export Link Sync**: Symlinks to `_shared/cases/juris-search/` and agent directories

### Step 7 — Browse Master Index (Índice Mestre tab)
- Filter by: Tribunal, Year, Outcome, Relator, Assunto, Comarca, free-text
- Paginated document cards → click for detail view
- Detail view shows: full metadata, ementa, assuntos, legislação, partes, correlations (same relator/assunto/legislação → navigable links)

---

## 3. Component Deep-Dive

### 3.1 Frontend (`tjrs-frontend/src/`)

| File | Purpose |
|------|---------|
| `App.jsx` (1925 lines) | Main app: court selector (29 courts), chat interface, search fields form (11 fields), results display with selection, downloads panel with folder naming, storage paths, search history list, master index tabs. Desktop 3-panel layout; mobile single-panel with bottom nav. |
| `MasterIndexView.jsx` | Browse/filter master index. Filters: tribunal (dropdown), outcome (dropdown), year (dropdown), relator, assunto, comarca, text (inputs). Paginated results (50/page). |
| `MasterIndexDetailView.jsx` | Document detail: metadata grid, outcome badges, assunto tags, legislação badges, partes display, full ementa text, document correlations (same relator, same assuntos, same legislação — clickable links). |
| `main.jsx` | React root render in StrictMode |

### 3.2 Backend API (`modules/`)

| Module | Routes | Purpose |
|--------|--------|---------|
| `routes_chat.py` | POST `/api/chat`, POST `/api/upload` | LLM chat via DeepSeek, file upload + text extraction + analysis |
| `routes_search.py` | POST `/api/search`, GET `/api/search/status/{job_id}`, GET `/api/results/{job_id}`, GET `/api/search/history` | Court scraper dispatch (background thread), polling, history list/read |
| `routes_download.py` | POST `/api/download`, POST `/api/download-batch`, GET `/api/download/status/{job_id}` | Download inteiro teor (single/batch), post-download automation chain |
| `routes_master.py` | GET `/api/master-index/stats`, GET `/api/master-index/documents`, GET `/api/master-index/document/{id}`, GET `/api/master-index/document/{id}/correlations`, POST rebuild/pause/resume, GET markdown, POST search | Master index browsing, correlations, management |
| `routes_frontend.py` | GET `/`, GET `/juris` | Serves React SPA from `tjrs-frontend/dist/` |
| `routes_health.py` | GET `/api/health`, GET `/api/stats`, GET `/api/courts` | Health, aggregate statistics, court listing |
| `routes_storage.py` | GET `/api/storage/paths`, GET `/api/docx|json/index`, POST rebuild | Storage paths, pipeline indexes, force rebuild |

**Supporting modules:**

| Module | Purpose |
|--------|---------|
| `config.py` | All env vars, directory paths, default settings, directory creation |
| `courts.py` | 29-court registry (`SUPPORTED_COURTS`), name resolution, multi-court selection resolver, dynamic scraper class importer |
| `state.py` | In-memory `search_jobs` dict, DOCX watch threading primitives, job persistence (`.job_*.json` files for crash recovery), TTL=6h eviction, max 500 jobs |
| `models.py` | Pydantic models: `ChatRequest`, `SearchFields`, `DownloadRequest`, `BatchDownloadRequest` |
| `lifecycle.py` | Startup/shutdown hooks: rehydrate jobs, run storage pipelines, start DOCX watcher + master indexer + pipeline catch-up threads |
| `deepseek_client.py` | DeepSeek API client (OpenAI SDK wrapper) with model aliases and vision support |
| `system_prompt.py` | Builds court-aware system prompts (Portuguese for Brazil, Spanish for Chile) instructing LLM to output `<search_fields>` XML |
| `file_extraction.py` | Text extraction: PDF (PyPDF2), DOCX (python-docx), HTML (BeautifulSoup), images (base64 for vision) |
| `utils.py` | Text cleaning, result normalization, JSON I/O, symlink helpers |
| `master_indexer.py` | Lazy import + lifecycle wrapper for `juris_indexer.JurisMasterIndexer` |

### 3.3 Court Scrapers

| Scraper | File | Portal Type | Search Method |
|---------|------|-------------|---------------|
| TJRS | `tjrs_scraper.py` (1250 lines) | Custom AngularJS portal | Selenium, DOC/DOCX/PDF downloads |
| TJSP | `tjsp_scraper.py` (849 lines) | e-SAJ CJSG | Selenium, reCAPTCHA v3 + image captcha |
| TJMG | `tjmg_scraper.py` (502 lines) | Custom portal | Selenium |
| TJRJ | `tjrj_scraper.py` (481 lines) | Custom portal | Selenium |
| STF | `stf_scraper.py` (676 lines) | HTTP API + Selenium fallback | ICP-Brasil SSL |
| Chile | `chile_scraper.py` (611 lines) | Poder Judicial CL | Selenium, Spanish field mapping |
| 22 e-SAJ | `_shared/esaj_scrapers.py` | e-SAJ CJSG portals | Generic `EsajJurisprudenciaScraper` (774 lines) + per-court wrappers |

**Shared infrastructure:**
- `_shared/chrome_driver.py` — Chrome WebDriver factory (3-strategy fallback), LibreOffice binary locator, sidecar metadata writer
- `_shared/esaj_config.py` — `EsajCourtConfig` dataclass, 22-court registry with URLs, selectors, captcha types

**Common scraper interface:**
- `__init__(headless=True)` — initialize WebDriver
- `search_with_criteria(SearchCriteria)` → `List[Dict]` — search + parse results
- `download_inteiro_teor_url(url, save_dir, metadata)` → `str` — download single document
- `download_all_inteiro_teor(results, save_dir, ...)` → `List[str]` — bulk download
- `close()` — clean up WebDriver

### 3.4 Document Extraction (`court_extractor.py`, ~1155 lines)

Extracts structured fields from downloaded PDF/DOCX into JSON:

```
Input:  jurisprudence_downloads/{folder}/inteiro_teor_*.pdf or *.docx
Output: extracted_documents/{Tribunal}_{source_file_base}.json
```

**Extractor classes (one per tribunal):**

| Extractor | Tribunal | Key Fields Extracted |
|-----------|----------|---------------------|
| `TJSPExtractor` | TJSP | registro, numero_processo (CNJ), classe, orgao_julgador (câmara), comarca, relator, data_julgamento, partes (apelantes/apelados), decisao, voto_numero, votacao, ementa |
| `TJMSExtractor` | TJMS | numero_processo (CNJ), comarca, orgao_julgador, relator, data_sessao, partes, advogados (with OAB numbers), promotor, interessados, decisao, votacao, ementa |
| `TJCEExtractor` | TJCE | gabinete, numero_processo (CNJ), classe, partes, correu, relator, decisao, votacao, data_julgamento, ementa |
| `TJRSExtractor` | TJRS | numero_processo (from filename), classe, cross-reference from master index, preliminares, fatos (numbered crimes with context), dosimetria (sentencing per defendant: pena_anos, pena_meses, pena_dias, regime), decisao, votacao |

**Common fields across all extractors:**
- `schema_version` (int), `extracted_at` (ISO-8601), `source_file`, `tribunal`
- `outcome` — regex-detected: `negado_provimento`, `dado_provimento`, `provimento_parcial`, `reformada`, `mantida`, `procedente`, `improcedente`, `unanime`
- `legislacao_citada` — regex: Lei, Decreto-Lei, Código, Constituição Federal
- `assuntos` — keyword classification (DIREITO PENAL, DANO MORAL, RESPONSABILIDADE CIVIL, etc.)
- `texto_inteiro` (full raw text), `texto_length`
- `extraction_confidence` — per-field: `high`, `medium`, `low`
- `court_specific` — tribunal-specific structured data

**Importable API:**
```python
from court_extractor import extract_file, extract_and_ingest, ingest_extracted_to_qdrant
result = extract_file("/path/to/file.pdf", "TJSP")        # returns dict
result = extract_and_ingest("/path/to/file.pdf", "TJSP")  # extract + Qdrant ingest
```

### 3.5 Qdrant Ingestion (`ingest_to_qdrant.py`, ~296 lines)

Standalone CLI + importable module for batch ingestion into Qdrant:

```
Input:  extracted_documents/*.json
Output: Qdrant collection juris_br_v1 (768-dim vectors)
```

**Process:**
1. Reads all extraction JSONs from `extracted_documents/`
2. For each document, builds embedding text:
   ```
   Tribunal: TJSP | Processo: XXX | Classe: Apelação Cível | ...
   
   EMENTA:
   <ementa text>
   
   DECISÃO:
   <decisao text>
   
   LEGISLAÇÃO CITADA:
   <list>
   ```
3. Sends batches of 50 to `POST /v1/qdrant/collections/structured_ingest` (port 8066)
4. Server-side 768-dim embedding + Qdrant upsert
5. Metadata payload includes all fields for filtered queries

**Importable:**
```python
from ingest_to_qdrant import ingest_single
result = ingest_single(doc_dict, collection="juris_br_v1", api_base="http://localhost:8066")
```

### 3.6 Master Indexer (`juris_indexer.py`, ~1316 lines)

Background watcher that builds the unified `master_index/master_index.json`:

**Input sources (scanned each cycle):**
1. `json_jurisprudence/index.json` — structured JSON records
2. `searches_history/search_*.json` — search history files
3. `extracted_documents/*.json` — court_extractor.py structured output
4. Sidecar `.metadata.json` files — download metadata

**Process (every 30s):**
1. Read `json_jurisprudence/index.json` entries
2. Build `DocRecord` for each entry with:
   - Filename-based identifiers (TJRS `inteiro_teor_N_ANO_CODIGO`, e-SAJ `cdacordao`)
   - Sidecar metadata (downloaded_at, source URL, description)
   - Regex parsing of description lines (relator, tipo, comarca, processo, órgão, datas)
   - Text-derived enrichment (ementa extraction, outcome detection, monetary values, cited processes)
   - Tribunal detection heuristics (URL patterns, process number conventions)
3. Cross-reference with search history — links documents to search jobs/terms/courts
4. Enrich from `court_extractor.py` output (partes, advogados, legislacao, assuntos)
5. Compute aggregates: by_tribunal, by_year, by_outcome, top_relators (25), top_comarcas (25)
6. Push new/changed documents to Qdrant `law_br` collection (batches of 20)
7. Optionally push to `juris_search_memory` awareness collection
8. Write `master_index/master_index.json`
9. Render Markdown view via `render_master_markdown.py`

**Canonical document IDs:**
| Pattern | ID Format | Source |
|---------|-----------|--------|
| e-SAJ | `tjsp_{cdacordao}` | cdacordao from filename |
| TJRS | `tjrs_{numero}_{ano}_{codigo}` | 3-field filename |
| CNJ | `cnj_{digits}` | CNJ process number |
| Generic | `{tribunal}_{numero_processo}` | Process number |
| Fallback | `hash of paths` | SHA-1 |

**Qdrant integration:**
- Only documents with ementa or text_excerpt are ingested
- Tracks ingested signatures in `.qdrant_state.json` to skip unchanged
- Supports `force_ingest=True` for full re-ingestion
- Supports `pause(collection)` / `resume(collection)` per collection or all

---

## 4. Data Flow & Pipelines

### 4.1 Complete Download → Ingestion Chain

```
User clicks "Baixar"
  │
  ▼
POST /api/download  (routes_download.py)
  │
  ├─ Selenium scraper downloads .doc/.docx/.pdf files
  │  → jurisprudence_downloads/{folder_name}/
  │  → Each file gets .metadata.json sidecar
  │
  ▼
[AUTO] _auto_extract_and_ingest(file_path, tribunal)
  │
  ├─ court_extractor.extract_and_ingest()
  │  ├─ Extract text from PDF/DOCX (PyPDF2 / python-docx)
  │  ├─ Run court-specific regex extractor
  │  ├─ Write extracted_documents/{Tribunal}_{id}.json
  │  └─ ingest_to_qdrant.ingest_single(doc)
  │     └─ POST /v1/qdrant/collections/structured_ingest → Qdrant juris_br_v1
  │
  ▼
[AUTO] _refresh_storage_pipelines_best_effort()
  │
  ├─ DOCX pipeline: .doc → .docx (LibreOffice)
  │  → docx_jurisprudence/{path}/*.docx + index.json
  │
  └─ JSON pipeline: extract text from all sources
     → json_jurisprudence/{path}/*.json + index.json
  │
  ▼
[AUTO] _master_indexer.rebuild(force_ingest=True)
  │
  ├─ Scan all 4 folders + search history + extractions
  ├─ Build master_index/master_index.json
  ├─ Enrich with court_extractor data
  ├─ Push to Qdrant law_br via structured_ingest
  ├─ Push to juris_search_memory (if enabled)
  └─ Render master_index.md
  │
  ▼
[AUTO] _sync_export_links()
  ├─ Symlinks → _shared/cases/juris-search/{downloads,docx,json,searches_history}
  └─ Symlinks → agents/agents-groups/la8159/source/juris-search/
```

### 4.2 Search → Persistence Flow

```
POST /api/search
  │
  ├─ Resolves selected courts (modules/courts.py)
  ├─ For each court:
  │  ├─ Dynamically imports scraper class
  │  ├─ Builds court-specific SearchCriteria
  │  ├─ Instantiates headless Selenium scraper
  │  ├─ Calls scraper.search_with_criteria(criteria)
  │  └─ Normalizes results to canonical field names
  │
  ├─ Merges all court results
  ├─ Persists to searches_history/search_{timestamp}_{job_id}.json
  │  { job_id, saved_at, fields, total, results: [...] }
  │
  └─ Updates in-memory job state → frontend receives via polling
```

### 4.3 Storage Pipeline (background, every 10s)

**DOCX Pipeline** (`modules/storage_docx.py`):
1. Discover `.doc` and `.docx` files in `jurisprudence_downloads/`
2. `.doc` → LibreOffice headless conversion → `.docx`
3. `.docx` → optional LibreOffice re-normalization (compatibility)
4. Output to `docx_jurisprudence/` (mirrors directory structure)
5. Maintains `docx_jurisprudence/index.json` and `.watch_state.json`
6. Change detection via file size + mtime signature

**JSON Pipeline** (`modules/storage_json.py`):
1. Discover supported files: `.doc`, `.docx`, `.pdf`, `.html`, `.htm`, `.txt`, `.rtf`, `.md`, `.json`, `.xml`
2. Extract text by type:
   - `.doc` → via DOCX fallback (requires prior conversion)
   - `.docx` → `python-docx`
   - `.pdf` → `PyPDF2`
   - `.html`/`.htm` → BeautifulSoup
   - plain text → direct read
3. Load `.metadata.json` sidecar for download metadata
4. Output per-file JSON to `json_jurisprudence/`:
   ```json
   {
     "id", "source_path", "source_signature", "source_metadata",
     "content_type", "parser", "text", "text_chars", "docx_fallback"
   }
   ```
5. Maintains `json_jurisprudence/index.json` and `.watch_state.json`

### 4.4 Pipeline Catch-Up (background, every 5min)

Scans `jurisprudence_downloads/` for `.pdf`/`.docx`/`.html` files not yet extracted:
1. Collects already-extracted `source_file` names from `extracted_documents/`
2. Finds downloads missing extraction
3. For each missing file: guesses tribunal from filename → calls `court_extractor.extract_and_ingest()`
4. After processing: rebuilds master index

### 4.5 Master Index → CSV Export (Graph Analytics)

`master_index/master_index_to_csv.py` exports 12 CSV files for Neo4j bulk import:
- **7 node types**: decisions, tribunais, relators, outcomes, assuntos, legislacao, comarcas
- **5 relationship types**: outcome edges, assunto edges, legislacao edges, relator edges, comarca edges
- Output: `master_index/csv_exports/`

---

## 5. File System Layout

```
/home/disconzi1986_gmail_com/juris-search-VPS/
├── main.py                          # FastAPI entry point (uvicorn, port 8000)
├── api.py                           # Backward-compat shim → main.py
│
├── juris_indexer.py                 # Master index builder (background watcher)
├── court_extractor.py               # Mechanical PDF/DOCX → JSON extractor
├── ingest_to_qdrant.py              # Batch Qdrant ingestion (CLI + importable)
├── ingest_laws.py                   # Legal framework article ingestion
├── flatten_corpus.py                # Content-hash dedup → corpus_flat/
├── parallel_convert.py              # Parallel .doc → .docx (multiprocessing)
├── rebuild_olivia_index.py          # Rebuild index from extracted_documents
├── render_master_markdown.py        # Render master_index.json → Markdown
│
├── modules/
│   ├── config.py                    # Env vars, paths, directory creation
│   ├── state.py                     # Job state, crash recovery, eviction
│   ├── models.py                    # Pydantic request models
│   ├── lifecycle.py                 # Startup/shutdown, pipeline catch-up
│   ├── courts.py                    # 29-court registry + resolver
│   ├── routes_chat.py               # /api/chat, /api/upload
│   ├── routes_search.py             # /api/search, /api/results, history
│   ├── routes_download.py           # /api/download, auto-ingestion chain
│   ├── routes_master.py             # /api/master-index/* (browse, detail, correlations)
│   ├── routes_frontend.py           # Static React SPA serving
│   ├── routes_health.py             # /api/health, stats, courts list
│   ├── routes_storage.py            # /api/storage/*, pipeline management
│   ├── storage_watcher.py           # DOCX+JSON pipeline orchestrator
│   ├── storage_docx.py              # DOCX conversion pipeline
│   ├── storage_json.py              # JSON text extraction pipeline
│   ├── storage_utils.py             # Shared: discovery, symlinks, stats
│   ├── file_extraction.py           # Low-level text extraction
│   ├── deepseek_client.py           # DeepSeek API client
│   ├── system_prompt.py             # LLM system prompts (PT-BR / ES-CL)
│   ├── utils.py                     # JSON I/O, text normalization
│   └── master_indexer.py            # Indexer lifecycle wrapper
│
├── _shared/
│   ├── chrome_driver.py             # Selenium WebDriver + LibreOffice
│   ├── esaj_config.py               # 22 e-SAJ court configs
│   ├── esaj_scraper.py              # Generic e-SAJ scraper (774 lines)
│   └── esaj_scrapers.py             # 22 per-court wrapper classes
│
├── <court>_scraper.py               # TJRS, TJSP, TJMG, TJRJ, STF, Chile scrapers
│
├── master_index/
│   ├── master_index.json            # 4.7MB unified index
│   ├── master_index.md              # Rendered Markdown
│   ├── master_index_to_csv.py       # → 12 Neo4j CSV files
│   ├── csv_exports/                 # 7 node + 5 relationship CSVs
│   └── .qdrant_state.json           # Qdrant ingestion tracking
│
├── extracted_documents/             # court_extractor.py output (~350+ JSONs)
├── jurisprudence_downloads/         # Raw downloads + .metadata.json sidecars
├── docx_jurisprudence/              # Normalized DOCX + index.json
├── json_jurisprudence/              # Text-extracted JSON + index.json
├── searches_history/                # search_*.json + .job_*.json
├── corpus_flat/                     # Deduplicated symlinks by tribunal
│
├── tjrs-frontend/
│   ├── src/App.jsx                  # Main React application
│   ├── src/MasterIndexView.jsx      # Master index browser
│   ├── src/MasterIndexDetailView.jsx# Document detail + correlations
│   └── dist/                        # Vite build output (served by FastAPI)
│
├── mcp/                             # Node.js MCP server (port 8116)
├── docs/                            # ingestion_schema.md, 8066.json
├── test_integration.py              # Integration tests
├── start.sh / stop.sh               # Service lifecycle scripts
└── PIPELINE.md                      # This file
```

---

## 6. API Reference Map

### Frontend → Backend API Calls

| User Action | Method | Endpoint | Module |
|------------|--------|----------|--------|
| Chat message | POST | `/api/chat` | routes_chat.py |
| Upload document | POST | `/api/upload` | routes_chat.py |
| Start search | POST | `/api/search` | routes_search.py |
| Poll search status | GET | `/api/search/status/{job_id}` | routes_search.py |
| Get search results | GET | `/api/results/{job_id}` | routes_search.py |
| Search history list | GET | `/api/search/history` | routes_search.py |
| Search history file | GET | `/api/search/history/{filename}` | routes_search.py |
| Start download | POST | `/api/download` | routes_download.py |
| Poll download | GET | `/api/download/status/{job_id}` | routes_download.py |
| Batch download | POST | `/api/download-batch` | routes_download.py |
| Master index stats | GET | `/api/master-index/stats` | routes_master.py |
| List documents | GET | `/api/master-index/documents?tribunal=&year=&relator=...` | routes_master.py |
| Get document | GET | `/api/master-index/document/{id}` | routes_master.py |
| Correlations | GET | `/api/master-index/document/{id}/correlations` | routes_master.py |
| Rebuild index | POST | `/api/master-index/rebuild` | routes_master.py |
| Pause/resume ingestion | POST | `/api/master-index/pause`, `/resume` | routes_master.py |
| Semantic search | POST | `/api/master-index/search` | routes_master.py |
| Storage paths | GET | `/api/storage/paths` | routes_storage.py |
| Health check | GET | `/api/health` | routes_health.py |
| Stats | GET | `/api/stats` | routes_health.py |
| Court list | GET | `/api/courts` | routes_health.py |

### Management API (port 8066 — via Ollama-Compatible Assistants)

| Purpose | Endpoint |
|---------|----------|
| Bulk folder ingest | `POST /v2/legal-ingestion/ingest-legal-folder` |
| Single file ingest | `POST /v1/ingestion/ingest-legal-file` |
| Analyze document structure | `POST /v2/legal-ingestion/analyze-document-structure` |
| Structured ingest | `POST /v1/qdrant/collections/structured_ingest` |
| Semantic search | `POST /legal-ingestion/search/{collection}` |
| Knowledge base query | `POST /v1/knowledge/query` |
| Vector search | `POST /v1/qdrant/qdrant/search` |
| Qdrant collections CRUD | `GET/POST/DELETE /v1/qdrant/collections` |
| Ensure indexes | `POST /v1/qdrant/collections/{name}/ensure-indexes` |
| Collection stats | `GET /v1/knowledge/collection/{name}/stats` |
| Neo4j health/Cypher/RAG | `GET /v1/neo4j/health`, `POST /v1/neo4j/cypher`, `POST /v1/neo4j/rag-context` |
| Agent management | `POST/GET/PUT/DELETE /v1/openclaude/agents` |
| Chat completions | `POST /v1/chat/completions` |

---

## 7. Document Identity, Indexing & Retrieval

### 7.1 Canonical Document IDs

| Source Pattern | ID Format | Example |
|---------------|-----------|---------|
| e-SAJ (cdAcordao) | `tjsp_{cdacordao}` | `tjsp_19436885` |
| TJRS 3-field | `tjrs_{numero}_{ano}_{codigo}` | `tjrs_70084126507_2020_649456` |
| CNJ number | `cnj_{digits}` | `cnj_10043824420228260003` |
| Generic | `{tribunal}_{numero_processo}` | `tjms_08000012220238120001` |
| Fallback | SHA-1 hash of paths | `a1b2c3d4e5f6g7h8` |

### 7.2 Qdrant Vector Collections

| Collection | Source | Vector Size | Populated By |
|-----------|--------|-------------|--------------|
| `juris_br_v1` | `extracted_documents/*.json` | 768 | `ingest_to_qdrant.py`, `court_extractor.py` |
| `law_br` | `master_index/master_index.json` | 768 | `juris_indexer.py` (master indexer) |
| `legal_framework` | Laws JSON files | 768 | `ingest_laws.py` |
| `juris_search_memory` | Master index (opt-in) | 768 | `juris_indexer.py` (awareness) |

**Point payload structure (juris_br_v1):**
```json
{
  "id": "uuid5 of doc_id",
  "doc_id": "canonical_id",
  "text": "Tribunal: TJSP | Processo: XXX | ...\n\nEMENTA:\n...",
  "content": "<same as text>",
  "metadata": {
    "doc_id", "tribunal", "numero_processo", "cnj_numero",
    "classe", "relator", "orgao_julgador", "comarca",
    "data_julgamento", "ementa", "decisao", "outcome",
    "assuntos", "legislacao_citada", "partes", "advogados",
    "votacao", "texto_length", "source_file", "extracted_at",
    "court_specific", "source": "juris-search-court-extractor"
  }
}
```

### 7.3 Search History Files

Located at `searches_history/search_{timestamp}_{job_id}.json`:
```json
{
  "job_id": "a1b2c3d4",
  "saved_at": "2026-05-28T12:00:00Z",
  "fields": { "search_text": "...", "courts": ["TJSP", "TJRS"], ... },
  "total": 42,
  "results": [
    {
      "numero_processo": "...",
      "tribunal": "TJSP",
      "inteiro_url": "...",
      "relator": "...",
      "orgao_julgador": "...",
      "comarca_origem": "...",
      "data_julgamento": "...",
      "ementa_trecho": "...",
      "cdacordao": "..."
    }
  ]
}
```

Job state files (`.job_{job_id}.json`) provide crash recovery — completed jobs with valid history files are restored to memory on startup.

### 7.4 Export Symlinks

On each pipeline cycle, symlinks are created from storage dirs to:
- `_shared/cases/juris-search/{downloads, docx, json, searches_history}`
- `agents/agents-groups/la8159/source/juris-search/{downloads, docx, json, searches_history}`

---

## 8. Background Processes

All run as daemon threads inside the FastAPI process:

| Process | Interval | File | Purpose |
|---------|----------|------|---------|
| Storage Watcher | 10s | `modules/storage_watcher.py` | DOCX + JSON pipeline scan, job eviction |
| Master Indexer | 30s | `juris_indexer.py` | Rebuild master index, Qdrant ingestion |
| Pipeline Catch-Up | 300s (5min) | `modules/lifecycle.py` | Find & process unextracted downloads |
| Job Eviction | Every watcher cycle | `modules/state.py` | Remove jobs >6h old, keep ≤500 in memory |

### Lifecycle Sequence

```
FASTAPI STARTUP
  ├─ _rehydrate_jobs_from_disk()        — recover crashed jobs
  ├─ _refresh_storage_pipelines()       — initial DOCX + JSON scan
  ├─ _sync_export_links()               — create symlinks
  ├─ THREAD: _start_docx_watcher()      → loop every 10s
  ├─ THREAD: _start_master_indexer()    → loop every 30s
  └─ THREAD: _start_pipeline_catch_up() → loop every 5min

FASTAPI SHUTDOWN
  ├─ Stop DOCX watcher
  ├─ Stop master indexer
  └─ Stop pipeline catch-up
```

### Key Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `JURIS_SEARCH_DEFAULT_COURT` | `TJRS` | Default tribunal |
| `JURIS_SEARCH_DOWNLOAD_DIR` | `jurisprudence_downloads/` | Raw downloads |
| `JURIS_SEARCH_HISTORY_DIR` | `searches_history/` | Search history |
| `JURIS_SEARCH_DOCX_DIR` | `docx_jurisprudence/` | Normalized DOCX |
| `JURIS_SEARCH_JSON_DIR` | `json_jurisprudence/` | JSON text extraction |
| `JURIS_SEARCH_MASTER_INDEX_DIR` | `master_index/` | Master index |
| `JURIS_SEARCH_EXTRACTIONS_DIR` | `extracted_documents/` | Extraction output |
| `JURIS_SEARCH_QDRANT_INGEST` | `1` | Auto Qdrant ingestion |
| `JURIS_SEARCH_QDRANT_API` | `http://localhost:8114` | Qdrant management URL |
| `JURIS_SEARCH_QDRANT_COLLECTION` | `juris_br_v1` | Qdrant collection |
| `JURIS_SEARCH_AWARENESS_INGEST` | `0` | Awareness memory |
| `JURIS_SEARCH_DOCX_WATCH` | `1` | DOCX watcher enabled |
| `JURIS_SEARCH_MASTER_INDEX` | `1` | Master indexer enabled |
| `JURIS_SEARCH_PIPELINE_CATCHUP_INTERVAL` | `300` | Catch-up interval (seconds) |
| `DEEPSEEK_API_KEY` | `` | DeepSeek API key |
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` | LLM model |

---

## Summary: What Happens When...

**...a user searches?**
Court selector → scraper class resolution → Selenium browsers scrape court portals → results normalized → persisted to `searches_history/` → returned to frontend via polling

**...a user downloads?**
Selenium browsers download files → `.metadata.json` sidecars → auto-extraction to `extracted_documents/` → auto-ingestion to Qdrant → storage pipeline sync → master index rebuild → export symlinks

**...documents are extracted?**
PDF/DOCX text extracted → court-specific regex patterns extract fields → outcomes, legislação, assuntos detected → structured JSON with confidence scores

**...documents are ingested to Qdrant?**
Embedding text composed from structured fields + ementa → `POST /v1/qdrant/collections/structured_ingest` → server-side 768-dim embedding → upsert with full metadata payload

**...the master index is rebuilt?**
JSON pipeline index scanned → DocRecords with filename/sidecar/description enrichment → search history cross-referenced → extraction data merged → aggregates computed → `master_index.json` written → Qdrant push (with delta tracking via `.qdrant_state.json`)
