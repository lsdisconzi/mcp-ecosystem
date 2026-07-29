# Garage MCP Servers

This directory contains stdio MCP servers that expose Garage API capabilities as MCP tools.

## Servers

- qdrant_server.py (14 tools)
  - qdrant_connect
  - qdrant_list_collections
  - qdrant_create_collection
  - qdrant_collection_summary
  - qdrant_search
  - qdrant_structured_ingest
  - qdrant_ensure_legal_indexes
  - qdrant_ingest_file
  - qdrant_embed_case_directory
  - qdrant_search_legacy
  - qdrant_query_vector
  - qdrant_index_reviewed_transcript
  - qdrant_query
  - qdrant_delete_collection (requires confirm=true)

- core_server.py (40 tools)
  - garage_health
  - garage_list_models
  - garage_chat_completions
  - garage_list_assistants
  - garage_list_files
  - garage_get_assistant
  - garage_update_assistant
  - garage_replace_assistant
  - garage_create_assistant
  - garage_delete_assistant (requires confirm=true)
  - garage_assistant_chat
  - garage_attach_file_to_assistant
  - garage_list_assistant_files
  - garage_detach_file_from_assistant
  - garage_query_assistant_knowledge
  - garage_assign_tool_to_assistant
  - garage_assistant_deepseek
  - garage_deepseek_engineer_chat
  - garage_deepseek_stream_proxy
  - garage_query_knowledge
  - garage_query_assistant_knowledge_collections
  - garage_ingest_knowledge_text
  - garage_ingest_knowledge_file
  - garage_clear_knowledge_collection (requires confirm=true)
  - garage_get_knowledge_collection_stats
  - garage_list_tools
  - garage_get_tool
  - garage_delete_tool (requires confirm=true)
  - garage_execute_tool
  - garage_execute_tool_by_name
  - garage_create_tool
  - garage_deep_reasoning
  - garage_create_thread
  - garage_list_threads
  - garage_get_thread
  - garage_delete_thread (requires confirm=true)
  - garage_add_thread_message
  - garage_list_thread_messages
  - garage_create_thread_run
  - garage_attach_file_to_thread

- ingestion_server.py (18 tools)
  - ingestion_collection_info
  - ingestion_search
  - ingestion_ingest_directory
  - ingestion_ingest_file
  - ingestion_ingest_legal_file
  - ingestion_analyze_document_structure
  - legal_search
  - legal_list_collections
  - legal_collection_info
  - legal_delete_collection (requires confirm=true)
  - legal_upload_csv
  - legal_ingest_file
  - legal_v2_ingest_enhanced_file
  - legal_v2_ingest_folder
  - legal_v2_analyze_document_structure
  - transcript_ingest_json
  - transcript_analyze_file
  - transcript_ingest_enhanced_file

- juris_server.py (18 tools)
  - juris_process_file
  - juris_extract_file
  - juris_ingest_extracted_to_qdrant
  - juris_extract_and_ingest
  - juris_ensure_collection
  - juris_ingest_single
  - juris_ingest_batch
  - juris_indexer_start
  - juris_indexer_stop
  - juris_indexer_pause
  - juris_indexer_resume
  - juris_indexer_paused_state
  - juris_indexer_rebuild
  - juris_indexer_stats
  - juris_indexer_get_document
  - juris_indexer_list_documents
  - juris_indexer_correlate_document

- prompt_server.py (7 tools)
  - prompt_generate
  - prompt_analyze
  - prompt_variations
  - prompt_optimize
  - prompt_evaluate
  - prompt_improve
  - prompt_examples

- files_server.py (10 tools)
  - files_list
  - files_read
  - files_summarize
  - files_upload
  - files_upload_transcript
  - files_upload_law
  - files_get_content
  - files_delete (requires confirm=true)
  - files_list_transcripts
  - files_list_laws

## Requirements

Create a dedicated MCP virtual environment (recommended):

```bash
python3 -m venv .venv-mcp
.venv-mcp/bin/pip install -r mcp/requirements.txt
```

This avoids `anyio` version conflicts with the main API dependency set.

## Run Locally

Start Garage API first:

```bash
./start.sh
```

Then run an MCP server in another terminal:

```bash
.venv-mcp/bin/python3 mcp/servers/qdrant_server.py
```

Or use the helper script (bootstraps `.venv-mcp` automatically if missing):

```bash
./mcp/start_server.sh qdrant
```

Run a one-command API + MCP validation:

```bash
./mcp/health_check.sh
```

## Client Configuration

Use mcpServers.example.json as a base for your MCP client config.
Replace each `/path/to/garage-main` entry with the absolute path to your local clone.
For this workspace, a machine-ready template is available at `mcp/mcpServers.local.json`.

Environment variables:

- GARAGE_BASE_URL: Garage API base URL (default: http://127.0.0.1:8066)
- GARAGE_API_KEY: Optional bearer token if auth is enabled

## Notes

- These MCP tools call existing HTTP endpoints in Garage. No Qdrant business logic is duplicated.
- Add tools incrementally and keep destructive operations gated behind explicit confirmations.

## OpenAPI Tool Catalog

Generate a catalog of endpoint-to-tool mappings from Garage OpenAPI:

```bash
.venv/bin/python3 mcp/generate_tool_catalog.py
```

Outputs:

- `mcp/catalog/garage_openapi_catalog.json`
- `mcp/catalog/garage_openapi_catalog.md`
