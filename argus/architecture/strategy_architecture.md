---

# ARGUS — Full Architectural Audit Report
**Mode:** Audit Mode (read-only) · **Date:** 2026-03-04 · **Auditor:** awareness-architectural-auditor

---

## 1. Executive Structural Summary

Argus is an **AI-powered legal framework generator**. It ingests legal documents (PDF or plain text), uses an external AI model (DeepSeek Reasoner via a local proxy) to reason over them, and emits portable JavaScript analyzers that can detect legal violations in conversation transcripts.

The codebase is in an **early-to-mid prototype stage**. The domain model is conceptually sophisticated — structured canonical entities, multi-jurisdiction article parsing, severity-classified violations — but the implementation is **architecturally flat**, **version-fragmented**, and **structurally unsafe** in multiple dimensions. There are no tests, no service interfaces, no DI, and several broken runtime dependencies.

The system cannot be considered production-ready. It is a working prototype with strong domain intelligence embedded in technically unstructured code.

---

## 2. Stack Detection

| Signal | Result |
|---|---|
| requirements.txt present | **Python** |
| `Flask`, `Flask-CORS`, `Werkzeug` | **Flask API** (Presentation layer) |
| `PyPDF2` | PDF infrastructure library |
| `requests` | External HTTP calls |
| `typer` (imported, not in requirements) | Orphaned CLI dependency |
| `spacy` (imported, not in requirements) | Broken NLP dependency |
| No `package.json` / `pyproject.toml` / `.csproj` | Pure Python single-stack |
| Generated output | JavaScript / HTML (embedded in prompt engineering) |

**Verdict:** Python/Flask monolith, generating JavaScript outputs.

---

## 3. Repository Map

```
Argus/                                   ← Root (flat, no layer separation)
├── app.py                               ← PRIMARY Flask entry point (344 lines)
├── app_extra.py                         ← PARALLEL/EXPERIMENTAL Flask app (470 lines)
├── requirements.txt                     ← 6 declared deps (3 missing at runtime)
├── README.md                            ← Describes wrong entrypoint filename
│
├── ingestors/                           ← ALL logic (no layer separation)
│   ├── integrated_legal_framework_parser.py     ← Parser v1 (1,252 lines)
│   ├── integrated_legal_framework_parser_v2.py  ← Parser v2 (1,118 lines)
│   ├── integrated_legal_framework_parser_v3.py  ← Parser v3 (1,550 lines)
│   ├── v4.py                                    ← Parser v4 (1,474 lines)
│   └── violation_object_normalizer.py           ← NLP normalizer (543 lines, broken)
│
├── data/                                ← Assets stored INSIDE repo
│   ├── analyzers/CBAAnalyzer/           ← Generated artifacts (JS, config)
│   ├── analyzers/MC99Analyzer/
│   ├── case_analysis/ (15 folders)      ← Run outputs committed to repo
│   ├── transcripts/ (~40 JSON files)    ← Input data committed to repo
│   └── law/law_actual/BR|CL|INT/        ← Law corpus in repo
│
├── ontology/                            ← Empty (declared intent, no content)
├── templates/frameworks.html           ← Frontend UI
├── architecture/                       ← Agent/process documentation
├── docs/                               ← Ecosystem/integration docs
└── venv/                               ← Virtual environment inside repo
```

---

## 4. Current Architecture Assessment

**Pattern identified:** Flat single-module monolith with iterative versioning by file copy.

**Deviation from Clean Architecture:** Extreme. There are no layers. Every concern — routing, business logic, domain modeling, infrastructure I/O, AI calls, PDF parsing, UI strings — lives either in app.py or in a single God class in ingestors.

```
Current (actual)                    Target (Clean Architecture)
─────────────────────────────────   ────────────────────────────────────
app.py ─────────────────────────►  presentation/  (routes only)
  └─ UI strings hardcoded                ↓
  └─ parser instantiated directly   application/  (services, DTOs)
  └─ framework logic in route            ↓
                                    domain/       (entities, interfaces)
ingestors/parser_v1..v4.py ──────►      ↑
  └─ Domain logic                   infrastructure/ (PDF, HTTP, file I/O)
  └─ PDF extraction (PyPDF2)
  └─ HTTP call to AI endpoint
  └─ File I/O (temp files)
  └─ Canonical entity dataclasses
  └─ Schema versioning logic
```

---

## 5. Architectural Strengths

| Strength | Evidence |
|---|---|
| Strong domain modeling intent | `CanonicalViolation`, `CanonicalEvidence`, `CanonicalSegment`, `CanonicalArticle` dataclasses defined in v3/v4 |
| Multi-language output support | UI string dictionaries for EN/ES/PT/IT/HI in app.py |
| Legal precision in parsing | Multi-pattern article extraction, jurisdiction detection, civil vs common law classification |
| Severity taxonomy | 4-tier scale (CRITICAL/HIGH/MODERATE/LOW) with legal justification |
| `eli_id` structured ontology | `BR.CBA.T3.C1.Art.74` — ELI-style article identifiers pointing toward graph-ready modeling |
| Chain analysis schema | `chain_analysis.json` captures pipeline chain context, framework chaining, and payload metadata |
| Articles mode vs text mode | app.py already differentiates user-supplied pre-parsed articles from raw text |
| Input validation (path traversal) | `".." in template_path` guard in `/view` route |

---

## 6. Architectural Weaknesses

| Category | Description |
|---|---|
| Version fragmentation | 4 near-identical parsers exist simultaneously with no deprecation markers |
| Dual entrypoint | app.py and app_extra.py both define a full Flask app; unclear which is production |
| God class | Each parser is 1,100–1,550 lines with no method-to-concern separation |
| No abstraction layer | app.py directly calls `IntegratedLegalFrameworkParser()` — no interface, no DI |
| Broken runtime dependencies | `spacy`, `attrs`, `typer` imported but not in requirements.txt |
| Data inside repo | Transcripts, law texts, case outputs, and generated JS all committed to git |
| Empty ontology | ontology directory is completely empty despite being central to the domain |
| No tests | Zero test files anywhere in the project |
| README describes wrong file | README references `app-framework-builder.py` which doesn't exist |
| `tempfile.mktemp()` insecure usage | TOCTOU-vulnerable in app.py PDF extraction route |

---

## 7. Violation Matrix

| Rule Violated | File | Layer | Severity | Fix Recommendation |
|---|---|---|---|---|
| Business logic in route handler | app.py | Presentation | **Critical** | Move UI string map and parser instantiation to a service class |
| Infrastructure call inside domain class | integrated_legal_framework_parser.py | Domain | **Critical** | Extract PDF reading and HTTP calls to `infrastructure/` |
| Duplicate God class (4 versions) | ingestors | All | **Critical** | Consolidate into one versioned implementation behind an interface |
| Domain importing infrastructure lib | v4.py, integrated_legal_framework_parser_v3.py | Domain | **High** | `PyPDF2` must live in infrastructure, not in the parser |
| Missing `spacy` in requirements | violation_object_normalizer.py | Infrastructure | **High** | Add `spacy>=3.7` and `en_core_web_sm` to requirements; or remove dependency |
| Missing `attrs` in requirements | app_extra.py | Presentation | **High** | Add `attrs` to requirements or remove the import |
| Missing `typer` in requirements | v4.py, integrated_legal_framework_parser_v3.py | Domain | **High** | Remove `from typer import prompt` — it is unused |
| `requests` version conflict | requirements.txt | Infrastructure | **High** | Bump `requests` to `>=2.32.3` |
| No repository abstraction | all | Application | **High** | Define `IFrameworkParser` abstract base class in a domain layer |
| Insecure `tempfile.mktemp()` | app.py | Presentation | **High** | Replace with `tempfile.NamedTemporaryFile(delete=False)` |
| Dual Flask entrypoint | app.py, app_extra.py | Presentation | **Medium** | Delete app_extra.py or rename to `app_experiment.py` and exclude from production |
| Raw data committed to repository | data | Infrastructure | **Medium** | Move transcripts, case_analysis, law to .gitignore or external store |
| SyntaxWarning in v4.py | v4.py | Infrastructure | **Medium** | Fix invalid escape sequences `'\`'` → use raw strings or `'\\'` |
| Empty ontology directory | ontology | Domain | **Medium** | Populate with canonical entity schemas or remove from tree |
| venv inside repo | venv | Infrastructure | **Low** | Add venv to .gitignore |
| README wrong entrypoint | README.md | Documentation | **Low** | Update to reference app.py |
| No tests | — | All | **High** | Add `tests/` with unit tests for parser, normalizer, and route handlers |

---

## 8. Structural Risk Assessment

### Critical Risks
- **4 live parser versions with no winner**: `parser.py`, `parser_v2.py`, `parser_v3.py`, v4.py all define a class named `IntegratedLegalFrameworkParser`. app.py uses v1; app_extra.py uses v3. The domain model in v3/v4 is far more advanced (canonical dataclasses, checksum generation, chain analysis) but is **not used by the active app**. Every manual update must be applied 4 times or divergence continues.
- **Business logic in HTTP handler**: `build_framework_analyzer()` in app.py (lines ~170–320) contains `~50 lines` of hardcoded UI string dictionaries, 2 branching execution modes, and direct parser instantiation. This is untestable and unmaintainable as the handler grows.
- **Broken runtime for violation_object_normalizer.py**: `spacy.load("en_core_web_sm")` will throw `OSError` at startup since neither `spacy` nor the model are installed. This is a silent runtime bomb.

### High Risks
- **No interface contract for parsers**: Any consumer can call any method on any version. There is no `IFrameworkParser` protocol to enforce consistent behavior across versions.
- **`tempfile.mktemp()` TOCTOU**: In `extract_pdf_text()`, the temp file path is created with `mktemp()` (not `mkstemp()`). Between path creation and file write, another process could create a file at that path — a classic TOCTOU race. `mkstemp()` is already used correctly 8 lines later in `build_framework_analyzer()`, creating an inconsistency.
- **`requests` pinned below `instructor`'s minimum**: requirements.txt pins `requests==2.31.0` but the installed `instructor` package requires `>=2.32.3`. `pip check` confirms this conflict. This will manifest as a runtime incompatibility.

### Medium Risks
- **Data stored in the repository**: case_analysis (15 run folders), transcripts (~40 JSON files), and law (law corpus) are inside the repo. This bloats the git history and creates ambiguity between code and data.
- **`argparse` imported but no CLI defined** in parsers v1/v2: `import argparse` appears but no `argparse.ArgumentParser` is ever constructed, indicating dead code copied across versions.
- **app_extra.py imports `datetime` and `attrs` but `attrs.asdict` is imported without usage context**: The `from attrs import asdict` import is at the top but no `attrs`-decorated class exists in that file.

### Low Risks
- venv directory inside the project folder. Should be .gitignored.
- README.md references `app-framework-builder.py` which doesn't exist — confusing for new contributors.
- .DS_Store files scattered throughout data — should be .gitignored.

---

## 9. Dependency Direction Report

```
Import graph (actual):

app.py (Presentation)
  └──► ingestors.integrated_legal_framework_parser (Domain+Infrastructure mixed)
          └──► PyPDF2            [VIOLATION: infra lib in domain class]
          └──► requests.post()   [VIOLATION: infra HTTP call inside domain class]
          └──► os/tempfile       [VIOLATION: infra file I/O inside domain class]

app_extra.py (Presentation)
  └──► ingestors.integrated_legal_framework_parser_v3 (Domain+Infrastructure mixed)
          └──► typer             [VIOLATION: unused CLI framework imported in domain]
          └──► PyPDF2            [VIOLATION: infra lib in domain class]

ingestors/violation_object_normalizer.py (Domain+Infrastructure mixed)
  └──► spacy                     [VIOLATION: NLP infra in domain object]
                                  [CRITICAL: not in requirements.txt → runtime crash]

ingestors/v4.py (Everything mixed)
  └──► typer                     [VIOLATION: unused CLI framework]
  └──► SyntaxWarnings            [BAD: invalid escape sequences]
```

**Violations by direction:**

| Direction | Source | Target | Severity |
|---|---|---|---|
| Domain → Infrastructure | `parser.py::generate_integrated_js_analyzer` | `requests.post()` AI endpoint | Critical |
| Domain → Infrastructure | All parsers | `PyPDF2.PdfReader` | High |
| Domain → Infrastructure | violation_object_normalizer.py | `spacy.load()` | High |
| Presentation → Domain (direct, no interface) | app.py | `IntegratedLegalFrameworkParser()` | High |
| Domain → unused framework | v4.py, `parser_v3.py` | `typer.prompt` | Medium |

---

## 10. AI-Native Readiness Score

| Dimension | Score | Justification |
|---|---|---|
| **Entity Behavioral Richness** | 45/100 | `CanonicalViolation`, `CanonicalEvidence`, etc. are defined in v3/v4 but are pure data containers (no behavior). The active v1 parser doesn't use them at all. |
| **Event Emission Capability** | 10/100 | No domain events. No event bus. `chain_analysis.json` hints at sequence but there is no event object model. |
| **Repository Abstraction Quality** | 15/100 | No repository interface. Data access (file I/O, JSON loading) is inline in God class methods. |
| **Domain Purity** | 20/100 | Parser classes mix PyPDF2 reads, regex extraction, HTTP calls, and domain logic in the same class. Domain is contaminated by infrastructure in all four versions. |
| **Replaceability of Persistence** | 25/100 | The data directory and local file paths are hardcoded in method bodies. No storage adapters. Cannot swap file storage for a database without rewriting parser methods. |
| **Traceability Readiness** | 55/100 | `chain_analysis.json` schema captures pipeline metadata (chain_id, model, temperature, framework_mode). `provenance` dict is in canonical entity base class. Structure is present; plumbing is not wired end-to-end. |
| **Causality Tracking Support** | 30/100 | `action_ids` and `actor_ids` exist in `CanonicalViolation`. `eli_id` links articles to violations. The vocabulary is correct but there is no runtime mechanism that populates or traverses these relationships. |

**Overall AI-Native Readiness: 29/100** — Strong conceptual schema, weak runtime implementation.

---

## 11. Dependency Overview

### Declared (requirements.txt)
| Package | Version | Status |
|---|---|---|
| Flask | 2.3.3 | OK |
| Flask-CORS | 4.0.0 | OK |
| python-multipart | 0.0.6 | OK |
| Werkzeug | 2.3.7 | OK |
| PyPDF2 | >=3.0.0 | OK |
| requests | 2.31.0 | **CONFLICT** — `instructor` needs >=2.32.3 |

### Imported but NOT declared
| Package | File | Severity |
|---|---|---|
| `spacy` | violation_object_normalizer.py | **Critical** — runtime crash |
| `attrs` | app_extra.py | **High** — runtime crash |
| `typer` | v4.py, `parser_v3.py` | **Medium** — unused import |
| `pdfminer` | app.py, app_extra.py | Low — optional fallback, gracefully handled |

### External Service Dependencies
| Service | Endpoint | Declared |
|---|---|---|
| DeepSeek Reasoner proxy | `http://localhost:8019/v1/assistants/deepseek-stream-proxy` | Not documented in README; hardcoded in route handlers |

---

## 12. Transformation Plan

### Phase 1: Non-Breaking Stabilization (Immediate)

1. **Fix broken imports** — Add `spacy`, `attrs` to requirements.txt; remove unused `typer` imports from v4.py and `parser_v3.py`
2. **Fix `requests` version** — Bump to `requests>=2.32.3` in requirements.txt
3. **Fix `tempfile.mktemp()`** — Replace with `tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')` in app.py's PDF extraction route
4. **Fix SyntaxWarnings** — Correct invalid escape sequences in v4.py lines 1385, 1386, 1416
5. **Update .gitignore** — Add venv, `*.DS_Store`, case_analysis, transcripts (or move data outside repo)
6. **Fix README** — Change `app-framework-builder.py` → app.py

### Phase 2: Version Consolidation

7. **Designate canonical parser** — Choose v3 or v4 as the canonical implementation (v3/v4 have the richer canonical entity model)
8. **Archive old versions** — Move `parser_v1`, `parser_v2`, v4.py into `archive/` or delete them
9. **Clarify dual entrypoint** — Either merge app_extra.py into app.py or rename it `app_experiment.py` with an explicit comment

### Phase 3: Layer Introduction

10. **Create `domain/` layer** — Move `CanonicalViolation`, `CanonicalEvidence`, `CanonicalArticle`, `CanonicalSegment`, severity enums, and article classification logic here. Zero infrastructure imports.
11. **Create `application/` layer** — Extract `FrameworkBuildService` and `LegalAnalysisService` from God class. These orchestrate domain operations and delegate I/O to infrastructure.
12. **Create `infrastructure/` layer** — Move `PyPDF2` extraction, `requests.post()` AI calls, and file I/O into dedicated adapters (`PdfExtractor`, `AiProxyClient`, `FileSystemStorage`)
13. **Define `IFrameworkParser` protocol** in domain layer — one abstract interface, multiple implementations if needed
14. **Refactor app.py routes** — Routes should delegate immediately to application service; UI strings move to a config/locale module

### Phase 4: AI-Native Infrastructure

15. **Populate ontology** — Define canonical JSON-LD or dataclass schemas for all entity types here; this becomes the single source of truth
16. **Introduce domain events** — `ViolationDetected`, `FrameworkParsed`, `ArticleClassified` events for event-sourcing readiness
17. **Wire causality** — Ensure every `CanonicalViolation.action_ids` is populated at generation time in the service layer
18. **Add test suite** — `tests/unit/`, `tests/integration/` covering parser, normalizer, and route handlers
19. **Introduce `IStorageAdapter`** — Allow the file-based storage to be swapped for S3/DB without touching domain code

---

## 13. Suggested Directory Restructure

**Before (current):**
```
Argus/
├── app.py
├── app_extra.py
├── ingestors/
│   ├── integrated_legal_framework_parser.py
│   ├── integrated_legal_framework_parser_v2.py
│   ├── integrated_legal_framework_parser_v3.py
│   ├── v4.py
│   └── violation_object_normalizer.py
├── ontology/                 ← empty
└── templates/
```

**After (Clean Architecture target):**
```
Argus/
├── app.py                    ← thin entrypoint only (app factory + run)
│
├── presentation/             ← Flask routes, no business logic
│   └── routes/
│       ├── framework_routes.py
│       └── pdf_routes.py
│
├── application/              ← services, orchestration, DTOs
│   ├── services/
│   │   ├── framework_build_service.py
│   │   └── legal_analysis_service.py
│   └── dto/
│       ├── framework_config_dto.py
│       └── build_result_dto.py
│
├── domain/                   ← pure domain, zero infrastructure imports
│   ├── entities/
│   │   ├── canonical_violation.py
│   │   ├── canonical_evidence.py
│   │   ├── canonical_article.py
│   │   └── canonical_segment.py
│   ├── interfaces/
│   │   ├── i_framework_parser.py
│   │   └── i_storage_adapter.py
│   ├── enums/
│   │   └── severity.py
│   └── services/
│       └── article_classifier.py     ← legal classification logic, pure
│
├── infrastructure/           ← I/O adapters
│   ├── pdf/
│   │   └── pdf_extractor.py          ← PyPDF2 wrapper
│   ├── ai/
│   │   └── deepseek_proxy_client.py  ← requests.post wrapper
│   ├── storage/
│   │   └── file_system_storage.py    ← local file read/write
│   └── parsers/
│       └── integrated_parser.py      ← single canonical parser (from v3/v4)
│
├── ontology/                 ← Canonical entity schemas (JSON-LD / dataclasses)
├── templates/                ← HTML frontend
├── tests/
│   ├── unit/
│   └── integration/
├── data/                     ← (gitignored) runtime data
└── requirements.txt
```

---

## 14. Technology-Specific Migration Guide (Python/Flask)

- **Domain entities**: Pure `@dataclass` classes — zero `PyPDF2`, `spacy`, or `requests` imports. `CanonicalViolation` etc. already exist in v3/v4; just move them and strip infrastructure noise.
- **Repository interfaces**: Define `IFrameworkParser(ABC)` and `IStorageAdapter(ABC)` in `domain/interfaces/`. Parser implementations go in `infrastructure/parsers/`.
- **DTOs**: Pydantic models or dataclasses in `application/dto/` separating HTTP request/response from internal domain objects. The current config dict passed end-to-end should become a typed `FrameworkConfigDto`.
- **DI**: `dependency_injector` container or simple factory function in `infrastructure/di.py` replacing direct `IntegratedLegalFrameworkParser()` instantiation.
- **Service layer**: `FrameworkBuildService` holds the branching logic currently in `build_framework_analyzer()` route. `LegalAnalysisService` holds the orchestration of detect → extract → classify → prompt-build.
- **Pitfall — circular imports**: When moving to layered structure, ensure `domain` never imports from `application` or `infrastructure`. Use abstract interfaces defined in `domain/interfaces/` to break any inversion.
- **pitfall — `typer` import**: `from typer import prompt` was imported into domain files. Remove completely — `typer` is a CLI toolkit and `prompt` is its interactive input function. It is completely unused and `typer` is not in requirements.

---

## 15. Suggested Documentation Additions

| Document | Priority | Contents |
|---|---|---|
| `ARCHITECTURE.md` | **High** | Layer map, dependency rules, canonical entity types, data flow diagram |
| `REFACTOR_PLAN.md` | **High** | The phased plan from this audit, with file-level assignments per phase |
| `ontology/CANONICAL_SCHEMA.md` | **High** | Formal definition of `CanonicalViolation`, `CanonicalArticle`, `eli_id` format, severity taxonomy |
| `docs/DEPLOYMENT.md` | **High** | Correct entrypoint (app.py), environment variables (`FLASK_DEBUG`), AI proxy dependency at `localhost:8019` |
| `FILE_INDEX.md` | **Medium** | Annotated index of all significant files — especially clarifying which parser version is active |
| `CHANGE_LOG.md` | **Medium** | Begin tracking parser version history and deliberate decisions |
| .gitignore additions | **Immediate** | venv, `*.DS_Store`, case_analysis, transcripts |

---

## Overall Scores

| Dimension | Score | Notes |
|---|---|---|
| **Modularity** | 12/100 | Flat structure; no layer boundaries |
| **Replaceability of Infrastructure** | 10/100 | PyPDF2, requests, and file I/O wired directly into domain class |
| **Scalability Potential** | 20/100 | God class will become a bottleneck; no concurrency model |
| **Testability** | 5/100 | Zero tests; untestable route handlers; no interface mocking possible |
| **Separation of Concerns** | 15/100 | All concerns mixed in ingestors; 4 redundant versions |
| **Domain Purity** | 20/100 | Excellent domain vocabulary; polluted by infrastructure in same files |
| **AI-Native Readiness** | 29/100 | Strong schema intent; weak runtime wiring |

**Composite:** 16/100 — Prototype quality with strong domain intelligence. Transformation is achievable in 4 phases with no full rewrites required — the domain model already exists in v3/v4 and just needs to be extracted and wired correctly.

---

*This is a read-only audit. No files were modified. To proceed to Proposal Mode or Migration Assist Mode, explicitly request it.*