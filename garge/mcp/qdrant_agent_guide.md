# Garage MCP Qdrant Agent Guide

This document describes how an agent can access and use all available MCP Qdrant tools in the Garage workspace.

## Purpose

Use this guide to:
- start the Garage API and Qdrant MCP server when needed
- understand the available Qdrant MCP tools
- know which tool names, arguments, and behaviors are supported
- verify and access the service if it is already running
- safely run destructive collection operations

## Setup

If Garage and the Qdrant MCP server are already running, skip directly to the tool usage section and use `qdrant_connect()` to verify connectivity.

If the service is not running yet, follow these steps:

1. Start the Garage API first:

```bash
./start.sh
```

2. Create and activate the MCP virtual environment if needed:

```bash
python3 -m venv .venv-mcp
.venv-mcp/bin/pip install -r mcp/requirements.txt
```

3. Start the Qdrant MCP server:

```bash
.venv-mcp/bin/python3 mcp/servers/qdrant_server.py
```

Alternatively, use the helper script:

```bash
./mcp/start_server.sh qdrant
```

## Running state verification

- If the agent is told the service is already running, it should not restart Garage or the MCP server unnecessarily.
- Instead, use `qdrant_connect()` first to verify that the `garage-qdrant` MCP server is available and connected to Qdrant.
- If `qdrant_connect()` succeeds, proceed directly with ingestion and search tools.
- If it fails, then start the service using `./start.sh` and `mcp/servers/qdrant_server.py` or the helper script.

## How an Agent Should Use These Tools

The Qdrant MCP tools are exposed through the `garage-qdrant` MCP server.
An agent should call tools by their exact names and supply JSON-style arguments.
The server forwards requests through Garage to the Qdrant-enabled API endpoints.

### Agent instructions

- Always prefer the exact tool name listed below.
- Provide valid collection names and query content.
- Use `confirm=true` for destructive operations.
- For ingest and embed operations, expect longer runtime; the server supports larger timeouts.
- If the Qdrant client is not connected yet, run `qdrant_connect()` first.

## Qdrant MCP Tools

### qdrant_connect()
- Description: Check connectivity between Garage and the configured Qdrant instance.
- Arguments: none
- Returns: connection health and Qdrant availability information

### qdrant_list_collections()
- Description: List all available collections with vector metadata.
- Arguments: none
- Returns: collection names and metadata

### qdrant_create_collection(name, vector_size, distance_metric="cosine")
- Description: Create or recreate a collection with a specific vector size and distance metric.
- Arguments:
  - `name` (string) — collection name
  - `vector_size` (int) — embedding dimension
  - `distance_metric` (string, optional) — usually `cosine` or `dot`

### qdrant_collection_summary(collection_name)
- Description: Return points count and document metadata breakdown for a collection.
- Arguments:
  - `collection_name` (string)

### qdrant_search(collection_name, query_text, limit=10, min_score=0.0, filters=None)
- Description: Run semantic search over a collection using Garage embeddings.
- Arguments:
  - `collection_name` (string)
  - `query_text` (string)
  - `limit` (int, optional)
  - `min_score` (float, optional)
  - `filters` (object, optional)

### qdrant_structured_ingest(collection_name, data_type, items)
- Description: Ingest structured transcript, violation, law, or generic payloads.
- Arguments:
  - `collection_name` (string)
  - `data_type` (string)
  - `items` (array of objects)

### qdrant_ensure_legal_indexes(collection_name)
- Description: Ensure legal metadata payload indexes exist for a collection.
- Arguments:
  - `collection_name` (string)

### qdrant_ingest_file(collection_name, file_path, use_auto_chunking=true, chunk_size=None, doc_type=None)
- Description: Ingest a local file into a Qdrant collection via multipart upload.
- Arguments:
  - `collection_name` (string)
  - `file_path` (string) — local path on the Garage host
  - `use_auto_chunking` (boolean)
  - `chunk_size` (int, optional)
  - `doc_type` (string, optional)

### qdrant_embed_case_directory(case_directory, collection_name, embedding_dim=384)
- Description: Scan and ingest an entire case directory into a collection.
- Arguments:
  - `case_directory` (string)
  - `collection_name` (string)
  - `embedding_dim` (int, optional)

### qdrant_query(collection_name, query_vector, limit=10)
- Description: Run a direct vector query against a collection.
- Arguments:
  - `collection_name` (string)
  - `query_vector` (array of floats)
  - `limit` (int, optional)

### qdrant_index_reviewed_transcript(transcript_id, collection="reviewed_transcripts")
- Description: Idempotently index reviewed transcript segments into Qdrant.
- Arguments:
  - `transcript_id` (string)
  - `collection` (string, optional) — defaults to `reviewed_transcripts`

### qdrant_search_legacy(collection_name, query_text, limit=10, min_score=0.0, filters=None)
- Description: Run the legacy Qdrant search endpoint.
- Arguments:
  - `collection_name` (string)
  - `query_text` (string)
  - `limit` (int, optional)
  - `min_score` (float, optional)
  - `filters` (object, optional)

### qdrant_query_vector(collection_name, query_vector, limit=10, score_threshold=None, with_payload=true, qdrant_filter=None)
- Description: Query a collection using text or vector through the vector endpoint.
- Arguments:
  - `collection_name` (string)
  - `query_vector` (array or text value)
  - `limit` (int, optional)
  - `score_threshold` (float, optional)
  - `with_payload` (boolean, optional)
  - `qdrant_filter` (object, optional)

### qdrant_delete_collection(collection_name, confirm=false)
- Description: Delete a collection from Qdrant.
- Arguments:
  - `collection_name` (string)
  - `confirm` (boolean, required for deletion)
- Important: Set `confirm=true` explicitly to execute deletion.

## Safe agent behavior

- Use `qdrant_connect()` first to initialize or verify the Qdrant connection.
- Use `qdrant_list_collections()` to discover collection names before querying.
- Use `qdrant_collection_summary()` for inventory and dimension checks.
- Use `qdrant_create_collection()` when a new schema is needed.
- Use `qdrant_delete_collection(..., confirm=true)` only when the collection must be removed.
- Prefer `qdrant_search()` for most semantic retrieval tasks.
- Use `qdrant_query()` or `qdrant_query_vector()` only when a raw vector query is available.
- For file ingestion, pass a host-local path that Garage can access.

## Notes

- The Qdrant MCP server is implemented in `mcp/servers/qdrant_server.py`.
- These tools are wrappers over Garage’s `/v1/qdrant/*` endpoints.
- If you need endpoint-level details, the generated OpenAPI catalog is in `mcp/catalog/garage_openapi_catalog.md` and `mcp/catalog/garage_openapi_catalog.json`.

## Example agent prompt

Use this prompt when handing the tools to an agent:

```
You are connected to the Garage Qdrant MCP server. Use only the following tools:
- qdrant_connect
- qdrant_list_collections
- qdrant_create_collection
- qdrant_collection_summary
- qdrant_search
- qdrant_structured_ingest
- qdrant_ensure_legal_indexes
- qdrant_ingest_file
- qdrant_embed_case_directory
- qdrant_index_reviewed_transcript
- qdrant_query
- qdrant_search_legacy
- qdrant_query_vector
- qdrant_delete_collection

For destructive actions, require explicit approval and set confirm=true.
For search tasks, prefer qdrant_search with query_text and filters.
For raw vector lookups, use qdrant_query or qdrant_query_vector.
```
