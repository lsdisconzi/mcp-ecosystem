# juris-search MCP

MCP server that exposes `juris-search` FastAPI capabilities as tools.

## Install

```bash
cd mcp
npm install
```

## Run

```bash
cd mcp
npm start
```

## MCPO setup

Use [mcpo.config.example.json](mcpo.config.example.json) as a template in your MCP/MCPO client.

- Server command: `node /home/disconzi1986_gmail_com/juris-search-VPS/mcp/juris_mcp_server.js`
- Optional env: `JURIS_SEARCH_BASE_URL=http://127.0.0.1:8000`

## Development checks

```bash
cd mcp
npm run check
npm run readiness
```

## Tool groups

- Service control: `juris_set_base_url`, `juris_start_service`, `juris_stop_service`
- Search lifecycle: chat, upload, search, results, history
- Download lifecycle: batch/single download flows and status polling
- Storage pipeline: docx/json indexes + rebuild actions
- Master index: stats, list/get docs, rebuild, markdown, semantic search
- UI/static fetch helpers for debugging frontend build/mount outputs
