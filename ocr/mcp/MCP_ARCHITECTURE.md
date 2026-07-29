# MCP Architecture

## Pattern

This repository uses the approved `python-fastmcp-multi` pattern:

- Multiple domain servers under `mcp/servers/`
- Shared utility layer in `mcp/servers/common.py`

## Domain Servers

### OCR Domain

Implementation: `mcp/servers/ocr_server.py`

Scope:

- Image discovery
- OCR extraction
- Optional LLM refinement and comparison
- Batch processing and artifact listing

Mapped project modules:

- `ocr_with_llm_enhancement.py`

### PDF Domain

Implementation: `mcp/servers/pdf_server.py`

Scope:

- PDF scanning/indexing
- PDF text/table extraction
- Optional LLM report analysis
- CSV conversion from analysis
- Renaming plan generation and application
- Full pipeline execution

Mapped project modules:

- `pdf_pipeline.py`
- Metadata-driven renaming logic compatible with `generate_renaming_plan.py`

## Safety Architecture

- Path sandboxing: all paths are resolved and validated inside `OCR_PROJECT_ROOT`.
- Destructive guard: `pdf_apply_renaming_plan` rejects write operations unless `confirm=true` when `dry_run=false`.
- Secret handling: no tokens in source code; `DEEPSEEK_API_KEY` required for LLM operations.

## Data Flow

1. MCP client calls service-prefixed tool (`ocr_*` or `pdf_*`).
2. Tool validates inputs and resolves project-local paths.
3. Tool delegates to existing project functions/classes.
4. Tool returns JSON payload with `ok` status and detailed result metadata.

## Files

- `mcp/servers/common.py`
- `mcp/servers/ocr_server.py`
- `mcp/servers/pdf_server.py`
- `mcp/mcpServers.example.json`
- `mcp/generate_readiness_report.py`
- `mcp/readiness_report.json`
- `mcp/readiness_report.md`
