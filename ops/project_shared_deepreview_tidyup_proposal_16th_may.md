# Ops Dashboard -- Deep Review & Tidy-Up Proposal

**Date:** 16th May 2026  
**Project:** `/awareness/ops`  
**Reviewer:** lsdisconzi

---

## Executive Summary

**Ops Dashboard** is a single-process Flask monitoring and control panel for the Awareness-AI platform ecosystem. It serves as the operations nerve centre: it tracks ~30 services (Docker containers, host processes, cloud instances), exposes their health status, provides start/stop/restart controls, tails logs, runs API test suites, manages page deployments to VPS, collects network telemetry, and provides an observatory dashboard with real-time metrics. The application is packaged as a monolithic 7,290-line Python file with two large single-page HTML templates. It is actively developed and largely functional, but suffers from significant technical debt from rapid organic growth -- security issues, code organisation problems, hardcoded values, and missing infrastructure (no tests, no CI, no .gitignore) being the most pressing concerns.

---

## Project Structure

```
/awareness/ops/
|
|-- app.py                          # (7,290 lines) Monolithic Flask app -- everything
|-- requirements.txt                # Flask, psutil, docker (3 deps, no versions pinned)
|-- README.md                       # Project documentation (somewhat outdated)
|-- BUSINESS_PLAN.md                # Strategic roadmap (4 phases)
|
|-- start.sh                        # Resilient bash launcher (daemon/foreground modes)
|-- stop.sh                         # Resilient bash stopper (graceful/kill fallback)
|
|-- ops-dashboard.service           # systemd unit file (STALE: references /Users/dev)
|-- deploy/
|   |-- ops-dashboard.service       # systemd unit file (DUPLICATE, slightly different)
|
|-- templates/
|   |-- dashboard.html              # (3,172 lines) Main SPA: services, quick links, page deployer, ecosystem
|   |-- observatory.html            # (4,575 lines) Observatory SPA: network telemetry, logs, agents, architecture
|   |-- login.html                  # Login/change-password page
|
|-- static/
|   |-- css/
|       |-- awareness-brand.css     # Minimal CSS custom properties placeholder
|
|-- network_traffic_store.json      # (346 KB, ~8,200 lines) Live captured HTTP traffic data
|-- convert_report_to_json.py       # (110 lines) Utility: API test report format converter (UNTRACKED, undocumented)
|
|-- .ops-dashboard-password.txt     # Persistent password store (SENSITIVE, currently "olivia")
|-- .ops-dashboard.pid              # PID file from daemon mode (DELETED from tracking)
|-- .venv/                          # Virtual environment (python 3.12, Flask 3.1.3, docker 7.1, psutil 7.2)
|-- .git/                           # Git repository
```

**No `.gitignore` exists.** Sensitive/temporary files are not excluded from tracking.

---

## Requirements Analysis

### Explicit Requirements (from README.md and BUSINESS_PLAN.md)

1. **Service Monitoring** -- live health status for platform services
2. **Container Control** -- start/stop/restart Docker Compose services
3. **System Metrics** -- CPU, memory, disk, uptime, load average
4. **Log Viewer** -- tail logs per service (Docker, file, journalctl)
5. **Project Browser** -- list key files with timestamps per project
6. **Nginx Status** -- reverse proxy health check
7. **Authentication** -- login gate with access code
8. **VPS Deployment** -- page sync to production server
9. **API Test Suite** -- run endpoint health checks across all services
10. **Network Observability** -- capture and display HTTP traffic
11. **Agent Architecture Management** -- view/edit agent architecture JSX, proxy to agent service
12. **Database/Cloud Checks** -- Qdrant Cloud, Neo4j Aura health
13. **Environment Management** -- view/edit shared .env variables

### Implicit Requirements (from code)

14. Quick Links management (CRUD) with custom links
15. Ecosystem service registry with endpoint enrichment
16. Contract and ontology document browsing                       
17. MCP (Model Context Protocol) server catalog inspection
18. Jurisprudence search (TJRS legal database integration)
19. Runtime fresh-start/reset workflows (kout, coremu, awareness)
20. Page deployer with staging/upload/deploy pipeline
21. Endpoint mapper pipeline (scan, enrich, test, store, graph, report)
22. Cross-mode operation (local development vs. VPS production)
23. Agent observatory (chat logs, artifacts, bridge sessions)

---

## Implementation Review

### 1. Core Application (`app.py`) -- 7,290 lines

**What it does:** A monolithic Flask application serving ~85 routes across these functional domains:

- **Auth** (lines 1046-1104): Login, password-change, brute-force protection (8 attempts per 5-min window). Uses constant-time comparison via SHA-256 hash. Supports persistent custom password via filesystem.
- **System API** (line 1204-1226): CPU/memory/disk/uptime via psutil.
- **Service Registry** (lines 216-501, 1401-1500): Massive dual-mode service list (VPS_SERVICES: 24 entries, LOCAL_SERVICES: 28 entries). Many are duplicates with slight differences. Includes cloud services (Qdrant Cloud, Neo4j Aura). Service alias/override normalization system.
- **Service Control** (lines 925-1043, 1549-1685): Start/stop/restart for both Docker compose services and host-level process services. Uses subprocess for compose commands, psutil for host processes.
- **Log Viewer** (lines 1229-1398): Multi-source log tailing (Docker, filesystem, journalctl). Smart candidate search by service name and aliases.
- **Nginx Status** (lines 1728-1752): Docker exec nginx -t check + access logs.
- **Projects Browser** (lines 849-866, 1687-1725): Hardcoded project directory registry with key files.
- **Quick Links** (lines 1756-2089): Builtin links catalog + full CRUD API for custom links. Persistent storage in `custom_quicklinks.json`.
- **Ecosystem Index** (lines 2091-2162): Serves enriched service map from `ecosystem_index.json` with endpoint counts.
- **Contracts & Ontology** (lines 2165-2244): Markdown file browser for contracts and ontology specs.
- **Agent Architecture** (lines 1131-1188, 2247-2354): Static file serving, API proxy to port 8120, source file read/write.
- **Observatory / Network Telemetry** (lines 2357-3274): The most complex subsystem. Monkey-patches `requests.sessions.Session.request` globally to capture all outbound HTTP. Flask before/after request hooks capture inbound traffic. Stores events in `network_traffic_store.json` with a 10MB rollover threshold. Provides filtered feed, summary statistics, CSV/JSON export, HTTP proxy-forward capability.
- **API Logger** (lines 2688-2876): Separate log store for structured API logs, with push/pull/clear endpoints.
- **Observatory Proxies** (lines 3277-3579): Internal service queries to Manus (port 8078), Kout (port 3019), Coremu (port 3119).
- **Coremu Fresh-Start** (lines 3597-3918): Complex backup-wipe-import-verify workflow for COREMU residency agent project.
- **Awareness Fresh-Start** (lines 3921-4427): Similar backup-wipe-import-verify workflow for Awareness runtime with group-based bundle selection.
- **Observatory -- Services/Agents/Memory** (lines 4430-5115): Consolidated service health, agent lists with background status, memory collection stats with Manus-to-Kout fallback.
- **Jurisprudence Search** (lines 4506-4920): TJRS legal search integration with advanced filters, log streaming.
- **Datasets** (lines 5178-5240): Filesystem stats for data directories.
- **Environment/Settings** (lines 5243-5348): Read/write for shared .env file with key allowlist.
- **MCP Registry** (lines 5351-5483): MCP bridge configuration and tool catalog browser.
- **Deploy / VPS Sync** (lines 5486-5703): Git fetch/diff/pull, Docker Compose restart, infrastructure classification.
- **API Test Suite** (lines 5705-6300): Hardcoded ~75 endpoint definitions for VPS mode, ~12 for local mode. Dynamic loading from endpoints.json with caching. Test runner with pass/fail/status/timing. Custom JSON import for tests.
- **Endpoint Mapper Pipeline** (lines 6303-6580): Async job runner for endpoint discovery, enrichment, testing, storage, graph building.
- **Page Deployer** (lines 6583-7048): File upload staging, preview, deploy to VPS via SSH/SCP or local filesystem copy. Nginx route registration.
- **VPS Deployment** (lines 7050-7272): VPS status check, page listing, sync, delete. Dual-mode (on-VPS vs remote SSH).
- **Health Check** (lines 7275-7281): Simple /health endpoint.
- **Main entry** (lines 7284-7290): Starts Flask on port from env (default 9000).

**State:** FUNCTIONAL but severely bloated. The file has ballooned to 7,290 lines through successive feature additions with no refactoring. Every subsystem lives in one module.

**Key issues:**
- No architectural separation (routes, services, models all in one file)
- Global mutable state everywhere (`_NETWORK_STORE_CACHE`, `_OBS_THREAD_CTX`, `_MAPPER_JOBS`, `_PAGE_UPLOADS`, `_endpoints_cache`, etc.)
- Monkey-patching `requests.sessions.Session.request` at module load time affects ALL code using the `requests` library globally
- Thread safety is handled ad-hoc (one lock for network store, but nothing for the log store, mapper jobs, page uploads)
- The `list_projects()` function (line 1687) has no route decorator -- it appears to be dead code

### 2. Shell Scripts

**`start.sh` (87 lines):** Well-structured launcher with daemon/foreground modes, optional port config, venv auto-creation, PID file management, health-check polling. Good quality.

**`stop.sh` (97 lines):** Resilient stopper with graceful kill, escalating to SIGKILL after timeout. Scans both PID file and port. Good quality.

**Issues:** Both reference `$DEV_LOG_DIR` and `$HOME/.dev-logs` which are not portable. `for _ in {1..30}` uses brace expansion incorrectly in some shells (should be `for ((i=0;i<30;i++))`).

### 3. Systemd Unit Files

**Two files exist:**
- `/awareness/ops/ops-dashboard.service` -- references `/Users/dev/` paths (macOS), uses `EnvironmentFile`
- `/awareness/ops/deploy/ops-dashboard.service` -- similar but uses inline `Environment` directives instead

Both are stale. The macOS paths won't work on Linux. Only one should exist, with correct paths for the target environment.

### 4. Templates (Frontend)

**`dashboard.html` (3,172 lines):** A fully inline SPA with embedded CSS and JavaScript. Implements service cards with status badges, action buttons (restart/stop/start/log), system metrics bar, quick links editor with CRUD, page deployer with multi-tab interface, and ecosystem service browser. Uses Font Awesome for icons, Inter/JetBrains Mono fonts. Calls ~15 API endpoints. All JS is vanilla, no framework.

**`observatory.html` (4,575 lines):** A larger SPA with sidebar navigation and multiple views: network telemetry feed, backend logs, services overview, eco-map, agents, architecture workspace, cloud services, contracts, datasets, environment settings, MCP registry. Uses Chart.js for visualisation. Implements filtering, auto-refresh, CSV/JSON export. All JS is vanilla.

**`login.html` (50 lines):** Clean, minimal login page.

**State:** FUNCTIONAL but concerning. Both SPAs are single files each over 3,000 lines. No code splitting, no modern JS framework, no build system. CSS is embedded (no preprocessor). API calls use hardcoded `/ops` prefix paths. This will become unmaintainable as features grow.

### 5. Data Files

**`network_traffic_store.json`:** Contains captured production traffic including request headers, user agents, client IPs. At 346KB with 8,207 lines, it is actively growing. This file is in the git working tree and shows in `git diff` as having modifications.

**`custom_quicklinks.json`:** Referenced in code (line 199) but may not yet exist on disk. Used for persistent custom link storage.

**`_PAGE_UPLOADS`:** In-memory dict for staging uploaded pages. Not persisted -- lost on restart.

### 6. Utility Script

**`convert_report_to_json.py`:** Converts API test reports to a format compatible with the `test/from-json` endpoint. Well-written with proper type hints and docstrings. Untracked (new file). Could be integrated into the dashboard itself.

---

## Issues Found

### CRITICAL (Security)

1. **Plaintext password on disk** -- `.ops-dashboard-password.txt` contains the literal password "olivia" and is committed to git (or tracked). This is a hardcoded credential leak.

2. **No .gitignore** -- Sensitive files (`.ops-dashboard-password.txt`, `.ops-dashboard.pid`, `network_traffic_store.json`) are not excluded. The traffic store contains real request data including cookies (sanitised to `***` but the file is still large).

3. **Default password "1234"** -- If no `OPS_CODE` env var and no custom password file exist, the dashboard accepts "1234". This is trivially guessable.

4. **Hardcoded secrets in code** -- The VPS host IP `72.60.143.139`, Qdrant Cloud instance ID `2858642c-bbc7-48a2-887f-fc6ab50d4e5a`, Neo4j instance references, and the Awareness domain are all hardcoded in `app.py` (lines 7053, 4974-4975, 5714, 1789). These should be environment variables.

5. **SHA-256 for password comparison** -- While constant-time, SHA-256 is not suitable for password hashing. Use bcrypt or argon2.

6. **Session secret hardcoded fallback** -- `app.secret_key` falls back to `"ops-awareness-2026-default-key"` on line 30. This makes session forgery possible if the env var is not set.

7. **Proxy allowlist permissive** -- The proxy endpoint (`/api/observatory/network/proxy`) allows requests to `localhost,127.0.0.1,::1` by default (line 2410). This could enable SSRF attacks against internal services.

### HIGH (Bugs / Architecture)

8. **`list_projects()` has no route** -- Line 1687 defines the function but there is no `@app.route("/api/projects")` above it. The README references `GET /api/projects` but it is not wired. (The `@ops_login_required` decorator on line 1687 has no matching route.)

9. **Duplicate systemd unit files** -- Two versions exist (`ops-dashboard.service` roots, `deploy/ops-dashboard.service`). Both reference macOS paths (`/Users/dev/`) that won't work on the target Linux VPS.

10. **Bash brace expansion bug** -- `start.sh` and `stop.sh` use `for _ in {1..30}` in POSIX-like context where `{1..30}` may not expand. Use C-style `for ((...))` instead.

11. **Monkey-patch has global side effects** -- `requests.sessions.Session.request = _observed_requests_request` at line 2685 modifies every `requests` user in the process. This breaks isolation and could cause issues if any library uses `requests` internally.

12. **In-memory upload store never cleaned** -- `_PAGE_UPLOADS` dict grows without bound. No TTL, no cleanup, lost on restart.

13. **Thread safety gaps** -- Only the network store has a lock. The log store (`_LOG_STORE_FILE`), mapper jobs (`_MAPPER_JOBS`), and page uploads (`_PAGE_UPLOADS`) are accessed from request threads and background threads with no synchronisation.

14. **Service definition duplication** -- `VPS_SERVICES` and `LOCAL_SERVICES` share ~80% overlap. Changes to one often need to be mirrored in the other.

### MEDIUM (Quality / Maintainability)

15. **Monolithic file** -- 7,290 lines in a single Python file. No modules, no packages, no separation of concerns. This is unsustainable at the current growth rate.

16. **No tests** -- Zero test files exist. No unit tests, integration tests, or end-to-end tests. The only "testing" is the built-in API test runner which is itself poorly isolated.

17. **No logging framework** -- Uses `print()` statements (e.g., line 4501). No structured logging, no log levels, no rotation.

18. **Hardcoded FQDN in many places** -- `https://awareness-ai.com.br` appears ~80+ times in `app.py`. Should be a single config variable.

19. **Incomplete requirements.txt** -- Only 3 packages listed with loose version constraints (`>=`). Missing: `requests` (used extensively), `uuid` (stdlib but should not be imported inline), `urllib3` (used via requests). No hashes, no dev dependencies.

20. **Massive inline data** -- ~75 hardcoded endpoint test definitions (lines 5813-5919), ~25 quick links (lines 1757-1787), ~30 services (lines 217-400). These should be data files, not code.

21. **CSS as string literals** -- Both HTML templates embed thousands of lines of CSS in `<style>` tags. No CSS reuse between dashboard and observatory despite overlapping design language. No preprocessor, no variables file.

22. **README outdated** -- Says "9 platform services" but code manages 28+. API endpoint table is incomplete. Quick Start references `pip install` instead of `pip install -r requirements.txt`.

23. **`convert_report_to_json.py` untracked** -- This utility is not integrated into the project. It is not mentioned in README, has no tests, and is not part of any workflow.

24. **Magic numbers** -- Timeouts, limits, thresholds are scattered as literals (30, 60, 120, 300, 500, 1000, 10000, etc.) with no named constants.

### LOW (Minor / Cosmetic)

25. **No type hints** -- Most functions lack type annotations except a few newer ones like `convert_report_to_json.py`. The codebase uses Python 3.12 but doesn't leverage modern typing.

26. **Inconsistent string quoting** -- Mix of single and double quotes throughout.

27. **Inline imports** -- Several functions import modules at call time (`import csv`, `import io`, `import uuid`, `import platform`, `import re`). Some imports are at the top of the file (line 7-22), others mid-file (line 5707). Inconsistent.

28. **`BUSINESS_PLAN.md`** -- While useful context, marketing documents don't belong in the code repository alongside source.

29. **Bare except clauses** -- Several `except Exception:` blocks swallow errors silently (e.g., lines 610, 754, 903, etc.).

---

## Improvement Proposals

### 1. Split `app.py` into modules (HIGH PRIORITY)

Current structure is unsustainable. Propose the following package layout:

```
ops/
  app.py                  # Flask app factory, config, middleware, main entry (~200 lines)
  auth.py                 # Login, password, session management
  services/
    registry.py           # Service definitions (VPS, LOCAL), aliases, lookups
    control.py            # Start/stop/restart logic
    monitoring.py         # Docker/psutil status checks, cloud checks
    logs.py               # Log reading (Docker, file, journalctl)
  observatory/
    network.py            # Network telemetry capture and storage
    agents.py             # Agent listing, Manus/Kout/Coremu queries
    architecture.py       # Agent-architecture workspace
    memory.py             # Memory/vector/collection stats
    jurisprudence.py      # TJRS legal search
    fresh_reset.py        # Runtime fresh-start workflows
  deploy/
    vps.py                # VPS deployment (sync, pages, status)
    page_deployer.py      # Page upload/staging/deploy
    git_ops.py            # Git pull, status, restart
  test/
    runner.py             # API test execution
    endpoint_catalog.py   # Endpoint definitions (load from JSON)
    mapper.py             # Endpoint mapper pipeline
  quicklinks.py           # Quick links CRUD
  ecosystem.py            # Ecosystem index, contracts, ontology
  mcp.py                  # MCP registry
  datasets.py             # Dataset stats
  env_manager.py          # Environment variable read/write
  templates/              # (unchanged)
  static/                 # (unchanged)
```

### 2. Security Hardening (CRITICAL)

- **Immediately:** Add `.gitignore` to exclude `.ops-dashboard-password.txt`, `.ops-dashboard.pid`, `network_traffic_store.json`, `custom_quicklinks.json`, `last_api_test_report.json`, `api_log_store.json`, `*.log`, `.venv/`, `__pycache__/`.
- **Immediately:** Remove or rotate the exposed password in `.ops-dashboard-password.txt`.
- Replace SHA-256 with `hashlib.pbkdf2_hmac` or `bcrypt` for password verification.
- Change default `OPS_SECRET` fallback to a random value or raise an error if unset.
- Move all hardcoded credentials, IPs, and instance IDs to environment variables with no defaults.
- Restrict the proxy allowlist to only the production domain unless explicitly configured otherwise.

### 3. Configuration Management (HIGH PRIORITY)

Create a single `config.py` or use environment-based configuration:

```python
# Example approach
class Config:
    VPS_HOST = os.environ.get("OPS_VPS_HOST", "")
    DOMAIN = os.environ.get("OPS_DOMAIN", "awareness-ai.com.br")
    # ... all other config
```

Extract all hardcoded URLs, domains, ports, IPs, instance IDs into this config with sensible defaults for development and required overrides for production.

### 4. Frontend Refactoring (MEDIUM PRIORITY)

- Split `dashboard.html` and `observatory.html` into reusable components.
- Extract shared CSS into a common stylesheet (currently the two SPAs duplicate hundreds of lines of identical CSS).
- Consider a lightweight framework (Alpine.js, htmx, or vanilla web components) to reduce boilerplate.
- Move JavaScript to external files instead of inline `<script>` tags.

### 5. Testing Infrastructure (MEDIUM PRIORITY)

- Add `pytest` as a dev dependency.
- Write unit tests for service registry, alias resolution, canonicalisation.
- Write integration tests for auth flows, CRUD operations.
- The existing API test runner should be refactored to use pytest fixtures instead of being embedded in Flask routes.

### 6. Replace Monkey-Patch with Explicit Instrumentation (HIGH PRIORITY)

Instead of globally patching `requests.sessions.Session.request`, create a thin wrapper class or use a context manager:

```python
class ObservedSession:
    def __init__(self):
        self._session = requests.Session()
    
    def request(self, method, url, **kwargs):
        # ... timing and capture logic ...
```

This keeps the telemetry opt-in per service call rather than global.

### 7. Add Proper Logging (MEDIUM PRIORITY)

Replace `print()` with Python's `logging` module. Use structured logging (JSON format) for the network/store logs. Add log rotation.

### 8. Remove Duplicate systemd Unit

Keep only the `deploy/ops-dashboard.service` file (more complete). Update paths to use environment-appropriate locations. Remove the root-level duplicate.

### 9. Data File Management

- `network_traffic_store.json` should have a configurable max age (delete entries older than N days) in addition to the size-based rollover.
- Add a periodic cleanup thread for `_PAGE_UPLOADS` (or persist to disk with TTL).
- Consider SQLite instead of raw JSON for the traffic store and log store for better query performance and concurrent access safety.

---

## Cleanup Proposals

### Files to Remove or Archive

| File | Reason |
|------|--------|
| `ops-dashboard.service` (root) | Duplicate of `deploy/ops-dashboard.service` |
| `BUSINESS_PLAN.md` | Belongs in docs/wiki, not in code repo |
| `.ops-dashboard.pid` | Process artifact, should be gitignored |
| `.ops-dashboard-password.txt` | SECURITY: contains credentials, must be removed from git and gitignored |

### Data Files to Exclude from Git

Add to `.gitignore`:
```
.ops-dashboard-password.txt
.ops-dashboard.pid
network_traffic_store.json
custom_quicklinks.json
last_api_test_report.json
api_log_store.json
*.log
.venv/
__pycache__/
*.pyc
```

### Code to Remove

1. **Dead function `list_projects()`** (line 1687) -- has no route, cannot be called via HTTP. Either wire it up or remove it.

2. **Unused `@ops_login_required` decorator** on `list_projects()` -- if the function is kept, it needs a route. Otherwise remove the decorator too.

3. **Bare `except Exception: pass` blocks** -- audit and add at minimum a log warning. Particularly in network capture code where errors are silently discarded.

### Consolidation Opportunities

1. Merge `VPS_SERVICES` and `LOCAL_SERVICES` into a single `ALL_SERVICES` list with a `modes: ["vps", "local"]` field per service. The `_active_services()` function filters by mode.

2. Merge `_API_TEST_ENDPOINTS` and `_LOCAL_API_TEST_ENDPOINTS` into a single data structure or, better, load both from JSON files.

3. Extract the ~500 lines of hardcoded `SERVICE_PATH_HINTS` and `SERVICE_NAME_OVERRIDES` into data files (JSON).

4. Consolidate the three nearly-identical fresh-reset workflows (kout, coremu, awareness) into a shared base function with service-specific parameterisation. Currently ~700 lines of duplicated logic.

---

## Overall Assessment

**Project health: C+ (Functional but at-risk)**

The Ops Dashboard does its job -- it monitors services, controls containers, collects telemetry. The developer clearly understands the domain deeply and has built comprehensive operational tooling. However, the codebase has the hallmarks of a project that grew without architectural discipline:

- A single 7,290-line Python file
- Two single-file SPAs totaling 7,747 lines of HTML/CSS/JS
- Global mutable state shared across endpoints
- Security vulnerabilities from hardcoded credentials and missing protections
- No tests, no CI, no code quality tooling
- Documentation that has fallen behind implementation

The project is at a tipping point. Continuing to add features to the monolith will make future changes increasingly risky and slow. The top three actions that would yield the highest return on effort:

1. **Add .gitignore and remove secrets from the repository** (30 minutes, addresses the most critical security issue)
2. **Split app.py into modules** (2-3 days, enables future development velocity)
3. **Add a test suite for the service registry and auth flows** (1-2 days, prevents regressions during refactoring)

The business plan correctly identifies Docker containerization and tests as the next hardening priority. The code quality improvements proposed here directly support those goals.
