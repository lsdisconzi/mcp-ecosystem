# Garage — Architectural Audit

> **Original date:** 2026-03-05 · **Last reviewed:** 2026-03-05  
> **Auditor:** GitHub Copilot (awareness-architectural-auditor)  
> **Scope:** Full codebase — `main.py`, `api/`, `routes/`, `core/`, `services/`, `config/`, `utils/`

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Critical Security Findings](#2-critical-security-findings)
3. [Architectural Findings](#3-architectural-findings)
4. [Code Quality Findings](#4-code-quality-findings)
5. [Dependency Audit](#5-dependency-audit)
6. [Remediation Roadmap](#6-remediation-roadmap)
7. [Fix Tracking](#7-fix-tracking)

---

## 1. Project Overview

A FastAPI-based local AI assistant backend that:

- Wraps **Ollama** (local LLMs) with an OpenAI-compatible REST API
- Integrates with **Qdrant** (vector DB, both local and Qdrant Cloud)
- Provides file management, thread/conversation memory (SQLite), tool execution
- Includes multiple document-ingestion pipelines: legal documents (Brazilian/Chilean aviation law), transcripts, generic files
- Serves three HTML UIs: `garage.html`, `qdrant-vector.html`, `garage-prompt.html`

**Entry point:** `main.py` — FastAPI app on port `8066`

**Router layout (as found):**

| Mount path | Module |
|---|---|
| `/v1/files` | `api/files.py` + inline `main.py` |
| `/v1/assistants` | `api/assistants.py` |
| `/v1/qdrant` | `routes/qdrant_router.py` |
| `/v1/knowledge` | `api/knowledge_router.py` |
| `/v1/tools` | `api/tools.py` |
| `/v1/ingestion` | `routes/ingestion.py` |
| `/legal-ingestion` | `routes/legal_ingestion.py` |
| `/v2/legal-ingestion` | `routes/legal_doc_ingestion_v2.py` |
| `/v2/transcripts` | `routes/transcript_ingestion.py` |
| `/prompt-engineer` | `api/prompt_engineer.py` |
| `/v1/threads` | `api/threads.py` (conditional) |

---

## 2. Critical Security Findings

### 🔴 S1 — Arbitrary File Read & Directory Listing (Path Traversal)

**Severity:** Critical  
**Files:** [`api/files.py`](api/files.py) — `GET /v1/files/list`, `GET /v1/files/read`  
**Status:** ✅ Fixed

Both `api/files.py` and `main.py` now use `_safe_path()` / `_safe_file_path()` helpers that resolve all paths against the project root and reject anything that resolves outside it with HTTP 403:

```python
# api/files.py
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()

def _safe_path(raw: str) -> Path:
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = _PROJECT_ROOT / candidate
    resolved = candidate.resolve()
    if not str(resolved).startswith(str(_PROJECT_ROOT)):
        raise HTTPException(status_code=403, detail="Access denied: path is outside the allowed directory")
    return resolved
```

⚠️ **Residual risk:** `main.py` still registers its own `GET /v1/files/read` inline handler (line 303) with its own `_safe_file_path()` helper pointing to the project root. Because `main.py` routes are registered *after* `api/files.py` routers, these duplicate definitions shadow each other — see A3 / N1.

---

### 🔴 S2 — Live Secrets Committed to Repo

**Severity:** Critical  
**File:** `.env` (no `.gitignore` existed)  
**Status:** ✅ `.gitignore` + `.env.example` created — **credentials must still be rotated**

| Secret | Action required |
|---|---|
| `QDRANT_API_KEY` | **Rotate immediately** |
| `OLLAMA_API_KEY` | **Rotate immediately** |
| `GOOGLE_CLIENT_SECRET` | **Rotate immediately** |
| `JWT_SECRET` | **Replace with `openssl rand -hex 32`** |
| `SECRET_KEY` | **Replace with `openssl rand -hex 32`** |

---

### 🔴 S3 — CORS Wildcard + `allow_credentials=True`

**Severity:** High  
**File:** [`main.py`](main.py#L122)  
**Status:** ✅ Fixed

CORS now reads from the `ALLOWED_ORIGINS` environment variable (defaults to `http://localhost:8066`):

```python
_allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:8066").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_allowed_origins, allow_credentials=True, ...)
```

---

### 🔴 S4 — Hardcoded Absolute Filesystem Paths Exposing Developer Identity

**Severity:** High  
**File:** [`api/files.py`](api/files.py)  
**Status:** ✅ Fixed

Hardcoded `/Users/leandrodisconzi/...` paths replaced with env-var driven, settings-backed `Path` objects:

```python
_TRANSCRIPTS_PATH = Path(os.getenv("TRANSCRIPTS_DIR", "data/documents/transcripts"))
_EVIDENCE_PATH    = Path(os.getenv("EVIDENCE_DIR",    "data/documents/evidence"))
_LAWS_PATH        = Path(os.getenv("LAWS_DIR",        "data/documents/laws"))
```

---

### ✅ S5 — Weak / Placeholder JWT Secret

**Severity:** High  
**Status:** ✅ Fixed

Both `JWT_SECRET` and `SECRET_KEY` in `.env` have been replaced with `openssl rand -hex 32` generated 64-character hex values. No weak placeholder secrets remain.

---

## 3. Architectural Findings

### 🔴 A1 — Five Duplicate Qdrant Client Implementations

**Status:** ✅ Canonical module established; race condition also fixed (see A4)

`services/qdrant_client.py` is the single canonical module with a `CANONICAL MODULE` docstring comment and a `threading.Lock` singleton guard. All other modules should import `get_qdrant_client` from here.

---

### 🔴 A2 — Parallel, Conflicting Router Directories

**Status:** ✅ Resolved

Legacy `api/qdrant.py` and the parallel `routers/` stack were removed during repository cleanup. `main.py` uses only `routes/qdrant_router.py` for `/v1/qdrant`.

---

### 🔴 A3 — Bloated `main.py` with Inline Business Logic

**Status:** ✅ Fixed

`api/chat.py` was extracted (chat completions + model list). The remaining 8 duplicate assistant CRUD handlers and the duplicate `GET /v1/files/read` handler have all been removed from `main.py`. `main.py` is now **639 lines** (down from 894). The DeepSeek proxy handlers and the `POST /v1/assistants/{id}/tools` handler remain in `main.py` as they have no counterpart in any router yet and are clearly demarcated.

---

### 🔴 N1 — Route Shadowing Between `main.py` and `api/files.py`

**Status:** ✅ Fixed

The duplicate `GET /v1/files/read` handler has been removed from `main.py`. All 8 assistant CRUD handlers that were silently dead code (registered after the router) have also been removed.

---

### 🟠 A4 — Race Condition in Singleton Qdrant Client

**Status:** ✅ Fixed

`services/qdrant_client.py` now uses a `threading.Lock` (`_qdrant_client_lock`) around the `if _qdrant_client is None:` check, eliminating the possibility of multiple clients being created under concurrent startup.

---

### 🟠 A5 — Global Pipeline State with Same Race Condition

**Status:** ✅ Fixed

Both `routes/ingestion.py` and `routes/legal_doc_ingestion_v2.py` have been updated to use thread-safe singleton patterns:
- `routes/ingestion.py`: `_pipeline` + `_pipeline_lock = threading.Lock()`
- `routes/legal_doc_ingestion_v2.py`: `_legal_pipeline` + `_legal_pipeline_lock = threading.Lock()` (also changed from a factory function to a true singleton so it no longer creates a new pipeline on every call)

---

### 🟠 A6 — Deprecated `@app.on_event` Lifecycle Hook

**Status:** ✅ Fixed

Replaced with `@asynccontextmanager` lifespan. The global `httpx.AsyncClient` is now closed cleanly in the lifespan `finally` block.

---

### 🟠 A7 — Blocking `subprocess.run` Inside Async Chat Handler

**Status:** ✅ Fixed

`api/chat.py` now uses an in-memory TTL cache (`_OLLAMA_MODELS_CACHE`, 60 s) and `asyncio.create_subprocess_exec` to fetch model names without blocking the event loop.

---

### 🟡 A8 — No Authentication on Any Endpoint

**Status:** 📝 Documented (acceptable for local dev; must not be deployed publicly without auth layer)

---

### 🟡 A9 — SQLite Queries Without Parameterization

**Status:** ✅ Reviewed — no SQL injection risk found

All f-strings in `core/memory.py` are used for log messages and internal ID construction, not for SQL query building. All SQL queries use `?` parameter binding.

---

## 4. Code Quality Findings

| ID | Finding | File | Status |
|---|---|---|---|
| Q1 | `get_assistant_from_file` / `save_assistant_to_file` duplicated in `main.py` (lines 184, 196) **and** `api/assistants.py` | `main.py` + `api/assistants.py` | ✅ Definitions removed from `main.py`; now imported from `api/assistants.py` |
| Q2 | `scripts/api_failures_by_component_20251203_184631/` committed | `scripts/` | ✅ Removed |
| Q3 | `qdrant_router.bkup.py` committed | `routers/` | ✅ Removed |
| Q4 | `import base64` inside method body (line 89) | `core/assistant.py` | ✅ Moved to module-level imports |
| Q5 | Machine-specific `LOG_FILE` and `DATABASE_URL` in `.env` | `.env` | ✅ Fixed in `.env.example` |
| Q6 | Two `logger = logging.getLogger(__name__)` declarations (lines 37 and 125) | `routes/qdrant_router.py` | ✅ Duplicate removed |

---

## 5. Dependency Audit

### Previously missing — now added to `requirements.txt` ✅

| Package | Status |
|---|---|
| `qdrant-client==1.16.1` | ✅ Added |
| `sentence-transformers==3.0.0` | ✅ Added |
| `pandas>=2.0.0` | ✅ Added |
| `langchain>=0.1.0` + `langchain-text-splitters` | ✅ Added |

### Redundant / deprecated — now resolved ✅

| Packages | Resolution |
|---|---|
| `PyPDF2` (deprecated) | ✅ Removed; `pypdf` is the successor and remains |
| `python-jose` | ✅ Removed; `PyJWT` is the single JWT library |
| `watchdog` | ✅ Removed; `watchfiles` is the single file-watcher |

### Remaining concerns

| Packages | Issue |
|---|---|
| ~~`PyMuPDF` + `pdfplumber` + `pypdf`~~ | ✅ Consolidated — `pdfplumber` removed from `requirements.txt`; `PyMuPDF (fitz)` primary + `pypdf` fallback. `directory_indexer.py` migrated to `pypdf.PdfReader`; `document_processor/tool.py` migrated to `fitz`. |
| `torch>=2.6.0` | Transitive dep of `sentence-transformers`; pinning a floor without an upper bound can pull in a multi-GB install — consider `torch>=2.0.0,<3` |

---

## 6. Remediation Roadmap

### Phase 1 — Immediate (Security) · ✅ Largely complete

| # | Action | File(s) | Status |
|---|---|---|---|
| 1.1 | Create `.gitignore` protecting `.env` | `.gitignore` | ✅ |
| 1.2 | Create `.env.example` template | `.env.example` | ✅ |
| 1.3 | **Rotate** all leaked credentials (manual) | external services | ⏳ Manual |
| 1.4 | Fix path traversal in file endpoints | `api/files.py`, `main.py` | ✅ |
| 1.5 | Fix CORS: use `ALLOWED_ORIGINS` env var | `main.py` | ✅ |
| 1.6 | Generate strong `JWT_SECRET` and `SECRET_KEY` | `.env` (local only) | ⏳ Manual |

### Phase 2 — High (Architecture) · ⚠️ Partially complete

| # | Action | File(s) | Status |
|---|---|---|---|
| 2.1 | Consolidate to one Qdrant client module | `services/qdrant_client.py` | ✅ |
| 2.2 | Remove duplicate `get_assistant_*` helpers from `main.py` | `main.py` | ✅ |
| 2.3 | Move `/v1/models` and `/v1/chat/completions` to dedicated router | `api/chat.py` | ✅ |
| 2.4 | **Remove all inline file + assistant handlers from `main.py`** (N1 / A3) | `main.py` | ✅ |
| 2.5 | Fix blocking subprocess in chat handler | `api/chat.py` | ✅ |
| 2.6 | Replace `@app.on_event` with lifespan | `main.py` | ✅ |
| 2.7 | Add `threading.Lock` to Qdrant singleton | `services/qdrant_client.py` | ✅ |
| 2.8 | Fix global pipeline state race (A5) | `routes/ingestion.py`, `routes/legal_doc_ingestion_v2.py` | ✅ |

### Phase 3 — Medium (Quality) · ⚠️ Partially complete

| # | Action | File(s) | Status |
|---|---|---|---|
| 3.1 | Delete debug snapshot directory | `scripts/` | ✅ |
| 3.2 | Delete `.bkup` file | `routers/` | ✅ |
| 3.3 | Replace hardcoded dev paths | `api/files.py` | ✅ |
| 3.4 | Add missing packages to `requirements.txt` | `requirements.txt` | ✅ |
| 3.5 | Remove redundant PDF / JWT / watcher deps | `requirements.txt` | ✅ |
| 3.6 | Remove duplicate logger in `routes/qdrant_router.py` (Q6) | `routes/qdrant_router.py` | ✅ |
| 3.7 | Move `import base64` to module level (Q4) | `core/assistant.py` | ✅ |
| 3.8 | Consolidate three PDF libraries to one | `requirements.txt` | ✅ |

---

## 7. Fix Tracking

| ID | Description | Status |
|---|---|---|
| S1 | Path traversal fix in `api/files.py` + `main.py` | ✅ Fixed |
| S2 | `.gitignore` + `.env.example` created | ✅ Fixed |
| S3 | CORS wildcard → `ALLOWED_ORIGINS` | ✅ Fixed |
| S4 | Hardcoded paths → env vars + settings | ✅ Fixed |
| S5 | JWT / secret key rotation | ✅ Fixed |
| Dep 3.8 | PDF library consolidation — `pdfplumber` removed; `PyMuPDF` (primary) + `pypdf` (fallback) remain; `directory_indexer.py` → `pypdf`; `document_processor/tool.py` → `fitz` | ✅ Fixed |
| A1 | Canonical `services/qdrant_client.py` established | ✅ Fixed |
| A2 | Legacy `api/qdrant.py` + `routers/` stack removed; only `routes/qdrant_router.py` remains | ✅ Resolved |
| A3 | Chat/models → `api/chat.py`; 8 duplicate assistant CRUD handlers + 1 duplicate file handler removed from `main.py` (894 → 639 lines) | ✅ Fixed |
| A4 | `threading.Lock` added to Qdrant singleton in `services/qdrant_client.py` | ✅ Fixed |
| A5 | Thread-safe singleton pattern added to `routes/ingestion.py` (`_pipeline` + `_pipeline_lock`) and `routes/legal_doc_ingestion_v2.py` (`_legal_pipeline` + `_legal_pipeline_lock`) | ✅ Fixed |
| A6 | Deprecated lifecycle hook → lifespan | ✅ Fixed |
| A7 | Blocking subprocess → `asyncio.create_subprocess_exec` + TTL cache | ✅ Fixed |
| A8 | No auth — local dev acceptable | 📝 Documented |
| A9 | SQLite parameterization reviewed | ✅ No issues found |
| N1 | Route shadowing: duplicate `GET /v1/files/read` removed from `main.py`; 8 dead assistant CRUD handlers removed | ✅ Fixed |
| Q1 | `get_assistant_from_file` / `save_assistant_to_file` definitions removed from `main.py`; imported from canonical `api/assistants.py` | ✅ Fixed |
| Q2 | Debug snapshot directory removed | ✅ Fixed |
| Q3 | `.bkup` file removed | ✅ Fixed |
| Q4 | `import base64` moved to module level in `core/assistant.py` | ✅ Fixed |
| Q5 | `.env.example` uses relative paths | ✅ Fixed |
| Q6 | Duplicate `logger` declaration removed from `routes/qdrant_router.py` | ✅ Fixed |
| Deps | Added `qdrant-client`, `sentence-transformers`, `pandas`, `langchain`; removed `PyPDF2`, `python-jose`, `watchdog` | ✅ Fixed |
| R1 | `GET /` returned 405 — files router had bare `@router.post("/")` shadowing root; confirmed workspace `api/files.py` correct (`/v1/files`) | ✅ Fixed |
| R2 | `POST /v1/files` duplicate removed from `main.py` — caused duplicate operation IDs and route shadowing with `files_router` | ✅ Fixed |
| R3 | Two stale `@router.get` routes removed from `api/assistants.py`: `GET /v1/assistants/assistants` and `GET /v1/assistants/v1/assistants` — both registered duplicate `list_assistants` function name causing 7× OpenAPI duplicate operation ID warnings | ✅ Fixed |
| R4 | `ForwardRef._evaluate()` crash on Python 3.12 — `import spacy` at module level in all three `deep_reasoning*` tools triggered pydantic v1 introspection failure; wrapped in `try/except` with `nlp = None` fallback | ✅ Fixed |
| R5 | `DEEPSEEK_API_KEY` global used directly in `deepseek-stream-proxy` headers — would send `Bearer None` if env var unset; now guarded with explicit 500 check before headers are built | ✅ Fixed |
| R6 | Brand system applied: `templates/index.html` created (1 067 lines, full Awareness-AI landing page); `static/css/awareness-brand.css` created (437-line shared override layer); Google Fonts + brand CSS injected into `garage.html`, `qdrant-vector.html`, `garage-prompt.html` | ✅ Fixed |
| R7 | Canonical codebase established: `awareness_development/garage/` (stale running copy) deleted; `awareness-ai/garage` is the single source of truth | ✅ Fixed |
