# Discovery

**Awareness-AI · Accountable by Design**

Point any folder on your machine → get a fully categorized, searchable, API-ready file organization dashboard in seconds.

## Quick Start

```bash
./start.sh
```

That's it. The dashboard opens in your browser at **http://localhost:3010**.

On server/VPS runs, `./start.sh` installs only the runtime Node dependencies for the single Discovery service (UI + API). Electron build dependencies are not required unless you explicitly want desktop packaging.

## Desktop App Build

For a real double-clickable app on macOS and Windows, build the Electron wrapper:

```bash
npm install
npm start
```

If you only want the local browser/server mode during development:

```bash
./start.sh
```

Legacy helper (UI/API only) is also available:

```bash
./start_ui_only.sh
```

## MCP Server (Discovery Tools)

Discovery now includes an MCP server that exposes Discovery services as MCP tools.

Install dependencies:

```bash
npm install
```

Run the MCP server (stdio transport):

```bash
npm run mcp:start
```

Optional inspector:

```bash
npm run mcp:inspect
```

Regenerate MCP readiness artifacts (endpoint inventory + readiness report):

```bash
npm run mcp:readiness
```

By default it targets `http://127.0.0.1:3010`. Override with:

```bash
DISCOVERY_BASE_URL=http://127.0.0.1:3010 npm run mcp:start
```

Main MCP tool groups:

- Service control: `discovery_start_service`, `discovery_stop_service`, `discovery_set_base_url`, `discovery_health`
- Core Discovery API: `discovery_manifest`, `discovery_endpoints`, `discovery_files`, `discovery_categories`, `discovery_search`, `discovery_tree`, `discovery_rebuild`, `discovery_organize`
- Session/upload: `discovery_init_session`, `discovery_reset_session`, `discovery_upload_files`, `discovery_export_session`, `discovery_import_session`
- Pipeline: `discovery_file_detail`, `discovery_pipeline_entities`, `discovery_pipeline_relationships`, `discovery_pipeline_timeline`, `discovery_pipeline_stats`, `discovery_pipeline_search`
- Intelligence: `discovery_intelligence_status`, `discovery_intelligence_run`, `discovery_intelligence_run_stream`, `discovery_intelligence_summary`, `discovery_intelligence_case_graph`, `discovery_intelligence_violations`, `discovery_intelligence_timeline`, `discovery_intelligence_narrative`, `discovery_intelligence_gap_report`, `discovery_intelligence_law_registry`, `discovery_intelligence_dedup_report`
- Events/case/comprehension/law: `discovery_events`, `discovery_event_graph`, `discovery_case_state`, `discovery_case_phase`, `discovery_case_findings`, `discovery_case_next_steps`, `discovery_comprehend_run`, `discovery_comprehend_run_stream`, `discovery_comprehend_overview`, `discovery_comprehend_guide`, `discovery_comprehend_groups`, `discovery_comprehend_strategies`, `discovery_law_frameworks`, `discovery_law_framework_articles`
- UI/static: `discovery_ui_server`, `discovery_ui_home`, `discovery_ui_agent_workspace`, `discovery_ui_awareness_agent_workspace`, `discovery_assets_file`, `discovery_static_file`

Utility tool:

- `discovery_raw_file` returns `/api/raw` file payload as base64 with metadata.

Note: `start.sh`, `stop.sh`, and `start_ui_only.sh` are shell scripts. Run them with `./...` (not `python`/`python3`).

Create installers on each target OS:

```bash
# macOS
npm run dist:mac

# Windows
npm run dist:win
```

Build artifacts are written to `dist/`.

Use the target OS for the final build, or a CI runner for that OS. In practice: build `.dmg` on macOS and `.exe` on Windows.

What users get:

- macOS: `.dmg` and zipped `.app`
- Windows: installer `.exe` and portable `.exe`

Inside the desktop app, the **Procurar** button opens a native folder picker and fills the absolute path automatically.

## Requirements

| Tool | Version |
|------|---------|
| Node.js | 18+ |
| npm | (comes with Node) |

The browser-based developer start script installs everything else automatically. Distributed desktop builds do not require end users to install Node.

## What It Does

1. **You point to a folder** — any directory on your file system
2. **It scans every file** — identifies type, format, content group
3. **Categorizes** by path structure, naming patterns, and content
4. **Generates metadata** — human-readable names, descriptions, MIME types
5. **Serves each file via REST** — every file gets its own URL
6. **Shows a dashboard** — browse, search, filter, export

Nothing is uploaded. Nothing leaves your machine. Discovery creates URLs that only work on your local network.

## Structure

```
Discovery/
├── package.json                 ← Desktop build + packaging
├── electron/
│   ├── main.js                  ← Electron main process
│   └── preload.js               ← Native folder picker integration
├── start.sh                    ← Run this
├── stop.sh                     ← Stop services
├── case-server/
│   ├── auto_server_builder.js  ← Core engine (Node/Express)
│   └── package.json
└── ui/
    └── discovery_ui.html       ← The dashboard
```

## Ports

| Service | Port | Purpose |
|---------|------|---------|
| discovery | 3010 | Dashboard frontend + file organization engine + REST API |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/manifest` | GET | Full manifest with all file metadata |
| `/api/endpoints` | GET | All files as endpoint array |
| `/api/files` | GET | Filterable: `?category=&ext=&kind=&group=` |
| `/api/categories` | GET | Category summary with counts |
| `/api/search?q=` | GET | Text search across all metadata |
| `/api/tree` | GET | Recursive directory tree |
| `/api/raw?file=` | GET | Direct file access |
| `/api/rebuild` | POST | Hot-reload: `{"root_dir":"..."}` |

## Dashboard Features

- **Browse** — native folder picker in desktop builds, browser picker + path input in web mode
- **Search** — full-text search across names, descriptions, categories
- **Filter** — by category, file type, content group
- **Export** — download all organized metadata as JSON
- **Import** — load a previous export, auto-detect changes (new/removed/modified files)
- **4 views** — Overview, All Files, Pipeline Ready, API Access

## Stop

```bash
./stop.sh
```

---

*© 2026 Discovery · Awareness-AI · Ontology v2.4 · Accountable by Design*
