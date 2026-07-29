# Garage — AI Tools & Services Hub

> Standalone FastAPI service · Port 8066

## Overview

Garage is a modular tooling and services hub that can run independently. It provides
an AssistantCore runtime, Qdrant vector database management, file operations,
chat completion, prompt engineering, and specialized ingestion pipelines for
legal documents, transcripts, and corpus data.

## Key Features

- **AssistantCore** — configurable AI assistant runtime with tool routing
- **Qdrant Manager** — collection CRUD, vector search, document ingestion
- **File Management** — upload, list, read, delete workspace files
- **Chat Completion** — streaming AI chat via DeepSeek / Ollama
- **Prompt Engineering** — prompt lab with template management
- **Knowledge Base** — query and attach files to assistant context
- **Legal Ingestion** — bulk ingest legal framework documents into Qdrant
- **Transcript Ingestion** — ingest and chunk transcript files
- **Tools Registry** — extensible tool definitions with execution engine

## Architecture

```
garage/
├── main.py                  # FastAPI entrypoint (port 8066)
├── core/
│   └── assistant.py         # AssistantCore — main AI runtime
├── config/
│   └── settings.py          # Environment-based settings
├── api/
│   ├── assistants.py        # Assistant CRUD router
│   ├── chat.py              # Chat completion router
│   ├── files.py             # File management router
│   ├── knowledge_router.py  # Knowledge base queries
│   ├── prompt_engineer.py   # Prompt lab router
│   ├── threads.py           # Thread management (optional)
│   └── tools.py             # Tool execution router
├── routes/
│   ├── qdrant_router.py     # Qdrant collection and vector management
│   ├── legal_ingestion.py   # Legal framework ingestion
│   ├── legal_doc_ingestion_v2.py  # V2 legal doc pipeline
│   └── transcript_ingestion.py   # Transcript ingestion
├── services/                # Business logic services
├── schemas/                 # Pydantic models
├── data/
│   └── tools/               # Tool definition registry
├── templates/               # Jinja2 templates
├── static/                  # CSS, JS, images
├── storage/                 # File storage root
├── qdrant_storage/          # Local Qdrant data
└── utils/                   # Shared utilities
```

## Quick Start

```bash
cd garage
python3 -m venv .venv && source .venv/bin/activate
uv pip install -r requirements.txt
./start.sh
# → http://localhost:8066

# stop the API
./stop.sh
```

Optional multi-service startup (Ollama and MCP servers are opt-in):

```bash
START_OLLAMA=1 START_MCP_MEMORY=1 START_MCP_SEQUENTIAL=1 START_MCP_FILESYSTEM=1 ./start_all.sh
```

To also launch Garage-native MCP wrappers from this repo:

```bash
START_MCP_GARAGE_QDRANT=1 START_MCP_GARAGE_CORE=1 START_MCP_GARAGE_INGESTION=1 START_MCP_GARAGE_PROMPT=1 START_MCP_GARAGE_FILES=1 ./start_all.sh
```

Garage-native MCP server wrappers are available in this repo:

- [mcp/servers/qdrant_server.py](mcp/servers/qdrant_server.py)
- [mcp/servers/core_server.py](mcp/servers/core_server.py)
- [mcp/servers/ingestion_server.py](mcp/servers/ingestion_server.py)
- [mcp/servers/prompt_server.py](mcp/servers/prompt_server.py)
- [mcp/servers/files_server.py](mcp/servers/files_server.py)
- [mcp/mcpServers.example.json](mcp/mcpServers.example.json)
- [mcp/generate_tool_catalog.py](mcp/generate_tool_catalog.py)

They expose Garage services as stdio MCP tools using the Python MCP SDK.

Enable legal framework catalog generation/watching for the Pinocchio multi-framework panel:

```bash
GENERATE_FRAMEWORK_LIST_ON_START=1 START_FRAMEWORK_WATCHER=1 ./start_all.sh
```

## Included Routers

| Router | Prefix | Purpose |
|--------|--------|---------|
| `chat` | — | AI chat completion (streaming) |
| `files` | — | File upload, list, read, delete |
| `assistants` | — | Assistant CRUD |
| `qdrant` | — | Qdrant collection and vector management |
| `knowledge` | `/v1/knowledge` | Knowledge base queries |
| `tools` | `/v1` | Tool execution engine |
| `prompt_engineer` | — | Prompt lab |
| `ingestion` | — | General document ingestion |
| `legal_ingestion` | — | Legal framework bulk ingest |
| `legal_doc_ingestion_v2` | — | V2 legal document pipeline |
| `transcript_ingestion` | — | Transcript chunking and ingest |
| `threads` | — | Thread management (optional) |

## Related Documentation

- [AUDIT.md](AUDIT.md) — architectural audit with security findings

---

*Awareness-AI · Garage · Tools & Services Hub · 2026*
# garage
