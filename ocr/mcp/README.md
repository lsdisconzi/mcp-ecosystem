# OCR-main MCP Servers

This project exposes MCP tools using the `python-fastmcp-multi` pattern.

## Servers

- `mcp/servers/ocr_server.py`
- `mcp/servers/pdf_server.py`

## Prerequisites

1. Python 3.10+ recommended
2. Install project dependencies:

```bash
pip install -r requirements.txt
```

## Environment Variables

Set runtime variables before launching servers:

- `OCR_PROJECT_ROOT` (optional): absolute path to the repository root. Defaults to auto-detected project root.
- `DEEPSEEK_API_KEY` (required for LLM-enabled tools)
- `DEEPSEEK_API_BASE_URL` (optional, request API URL override for request-based clients)

Example:

```bash
export OCR_PROJECT_ROOT="/Users/dev/services/OCR"
export DEEPSEEK_API_KEY="<your-token>"
export DEEPSEEK_API_BASE_URL="https://api.deepseek.com/v1/chat/completions"
```

## OCR Tool Inventory

- `ocr_list_images`: list candidate image files.
- `ocr_process_image`: run OCR on one image, optional LLM refinement.
- `ocr_compare_results`: compare raw OCR and refined output.
- `ocr_run_batch`: run directory batch OCR pipeline.
- `ocr_list_output_artifacts`: list generated artifacts in output directories.

## PDF Tool Inventory

- `pdf_scan_files`: recursively index PDF files.
- `pdf_extract_text`: extract page text and table blocks from one PDF.
- `pdf_analyze_pdf`: extract + optional LLM analysis for one PDF.
- `pdf_convert_analysis_directory_to_csv`: convert JSON analyses to CSV outputs.
- `pdf_generate_renaming_plan_from_csv`: create deterministic renaming plan from metadata CSV.
- `pdf_apply_renaming_plan`: apply plan (requires `confirm=true` when `dry_run=false`).
- `pdf_run_pipeline`: execute the end-to-end PDF pipeline.

## Safety Rules Applied

- All tool names are snake_case and service-prefixed (`ocr_` or `pdf_`).
- Destructive operation `pdf_apply_renaming_plan` enforces `confirm=true` when `dry_run=false`.
- API token is read from environment variables.
- No hardcoded secrets are used.

## Run Servers Manually

- source .venv/bin/activate

From repository root:

```bash
python mcp/servers/ocr_server.py
python mcp/servers/pdf_server.py
```

## Client Configuration

Use `mcp/mcpServers.example.json` as a template for MCP clients.

## Readiness Artifacts

- Architecture: `mcp/MCP_ARCHITECTURE.md`
- Generator: `mcp/generate_readiness_report.py`
- Report JSON: `mcp/readiness_report.json`
- Report Markdown: `mcp/readiness_report.md`
