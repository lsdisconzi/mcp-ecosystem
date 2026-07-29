# Garage OpenAPI Tool Catalog

Source: http://127.0.0.1:8066/openapi.json

Total tools: 113

| Tool Name | Method | Path | Tags |
|---|---|---|---|
| get_audio_file_api_audio_filename_get | GET | /api/audio/{filename} | files |
| deepseek_gateway_delete | DELETE | /api/deepseek/{path} | Gateway |
| deepseek_gateway_get | GET | /api/deepseek/{path} | Gateway |
| deepseek_gateway_post | POST | /api/deepseek/{path} | Gateway |
| deepseek_gateway_put | PUT | /api/deepseek/{path} | Gateway |
| regenerate_framework_list_api_frameworks_regenerate_list_post | POST | /api/frameworks/regenerate-list | System |
| get_transcripts_api_transcripts_get | GET | /api/transcripts | files |
| debug_routes_debug_routes_get | GET | /debug-routes | Debug |
| debug_schema_debug_schema_get | GET | /debug-schema | Debug |
| health_check_health_get | GET | /health | System |
| delete_collection_legal_ingestion_collection_collection_name_delete | DELETE | /legal-ingestion/collection/{collection_name} | Legal Document Ingestion |
| get_collection_info_legal_ingestion_collection_collection_name_info_get | GET | /legal-ingestion/collection/{collection_name}/info | Legal Document Ingestion |
| list_collections_legal_ingestion_collections_get | GET | /legal-ingestion/collections | Legal Document Ingestion |
| ingest_from_file_path_legal_ingestion_ingest_file_post | POST | /legal-ingestion/ingest-file | Legal Document Ingestion |
| search_legal_documents_legal_ingestion_search_collection_name_post | POST | /legal-ingestion/search/{collection_name} | Legal Document Ingestion |
| upload_and_ingest_csv_legal_ingestion_upload_csv_post | POST | /legal-ingestion/upload-csv | Legal Document Ingestion |
| list_assistants_v1_assistants_get | GET | /v1/assistants/ | Assistants |
| create_assistant_v1_assistants_post | POST | /v1/assistants/ | Assistants |
| deepseek_streaming_proxy_v1_assistants_deepseek_stream_proxy_post | POST | /v1/assistants/deepseek-stream-proxy |  |
| delete_assistant_v1_assistants_assistant_id_delete | DELETE | /v1/assistants/{assistant_id} | Assistants |
| get_assistant_v1_assistants_assistant_id_get | GET | /v1/assistants/{assistant_id} | Assistants |
| update_assistant_v1_assistants_assistant_id_patch | PATCH | /v1/assistants/{assistant_id} | Assistants |
| replace_assistant_v1_assistants_assistant_id_put | PUT | /v1/assistants/{assistant_id} | Assistants |
| chat_with_assistant_v1_assistants_assistant_id_chat_post | POST | /v1/assistants/{assistant_id}/chat | Assistants |
| deepseek_proxy_v1_assistants_assistant_id_deepseek_post | POST | /v1/assistants/{assistant_id}/deepseek | DeepSeek |
| list_assistant_files_v1_assistants_assistant_id_files_get | GET | /v1/assistants/{assistant_id}/files | Assistants |
| attach_file_to_assistant_v1_assistants_assistant_id_files_post | POST | /v1/assistants/{assistant_id}/files | Assistants |
| detach_file_from_assistant_v1_assistants_assistant_id_files_file_id_delete | DELETE | /v1/assistants/{assistant_id}/files/{file_id} | Assistants |
| query_assistant_knowledge_v1_assistants_assistant_id_query_knowledge_post | POST | /v1/assistants/{assistant_id}/query-knowledge | Assistants |
| assign_tool_to_assistant_v1_assistants_assistant_id_tools_post | POST | /v1/assistants/{assistant_id}/tools | Assistants |
| chat_completions_v1_chat_completions_post | POST | /v1/chat/completions | Chat |
| deepseek_engineer_chat_v1_deepseek_engineer_chat_post | POST | /v1/deepseek-engineer/chat | DeepSeek |
| list_files_v1_files_get | GET | /v1/files | Files |
| upload_file_v1_files_post | POST | /v1/files | files |
| list_law_files_v1_files_laws_get | GET | /v1/files/laws | files |
| list_files_in_directory_v1_files_list_get | GET | /v1/files/list | files |
| read_file_v1_files_read_get | GET | /v1/files/read | files |
| summarize_files_v1_files_summarize_post | POST | /v1/files/summarize | files |
| list_transcript_files_v1_files_transcripts_get | GET | /v1/files/transcripts | files |
| upload_law_file_v1_files_upload_law_post | POST | /v1/files/upload/law | files |
| upload_transcript_file_v1_files_upload_transcript_post | POST | /v1/files/upload/transcript | files |
| delete_file_v1_files_file_id_delete | DELETE | /v1/files/{file_id} | Files |
| get_file_content_v1_files_file_id_content_get | GET | /v1/files/{file_id}/content | Files |
| analyze_document_structure_v1_ingestion_analyze_document_structure_post | POST | /v1/ingestion/analyze-document-structure | Ingestion |
| get_collection_info_v1_ingestion_collections_collection_name_info_get | GET | /v1/ingestion/collections/{collection_name}/info | Ingestion |
| ingest_directory_v1_ingestion_ingest_directory_post | POST | /v1/ingestion/ingest-directory | Ingestion |
| ingest_file_v1_ingestion_ingest_file_post | POST | /v1/ingestion/ingest-file | Ingestion |
| ingest_legal_file_v1_ingestion_ingest_legal_file_post | POST | /v1/ingestion/ingest-legal-file | Ingestion |
| search_documents_v1_ingestion_search_post | POST | /v1/ingestion/search | Ingestion |
| assistant_query_knowledge_v1_knowledge_assistant_assistant_id_query_post | POST | /v1/knowledge/assistant/{assistant_id}/query | knowledge |
| clear_collection_v1_knowledge_collection_collection_name_clear_delete | DELETE | /v1/knowledge/collection/{collection_name}/clear | knowledge |
| get_collection_stats_v1_knowledge_collection_collection_name_stats_get | GET | /v1/knowledge/collection/{collection_name}/stats | knowledge |
| ingest_file_v1_knowledge_ingest_file_post | POST | /v1/knowledge/ingest/file | knowledge |
| knowledge_query_v1_knowledge_query_post | POST | /v1/knowledge/query | knowledge |
| list_models_v1_models_get | GET | /v1/models | Models |
| cypher_v1_neo4j_cypher_post | POST | /v1/neo4j/cypher | neo4j |
| health_v1_neo4j_health_get | GET | /v1/neo4j/health | neo4j |
| rag_context_v1_neo4j_rag_context_post | POST | /v1/neo4j/rag-context | neo4j |
| stats_v1_neo4j_stats_get | GET | /v1/neo4j/stats | neo4j |
| list_agents_v1_openclaude_agents_get | GET | /v1/openclaude/agents | OpenClaude |
| create_agent_v1_openclaude_agents_post | POST | /v1/openclaude/agents | OpenClaude |
| export_to_assistant_v1_openclaude_agents_export_to_assistant_name_post | POST | /v1/openclaude/agents/export-to-assistant/{name} | OpenClaude |
| import_from_assistant_v1_openclaude_agents_import_from_assistant_assistant_id_post | POST | /v1/openclaude/agents/import-from-assistant/{assistant_id} | OpenClaude |
| import_from_catalog_v1_openclaude_agents_import_from_catalog_name_post | POST | /v1/openclaude/agents/import-from-catalog/{name} | OpenClaude |
| import_from_markdown_v1_openclaude_agents_import_markdown_post | POST | /v1/openclaude/agents/import-markdown | OpenClaude |
| validate_agent_v1_openclaude_agents_validate_post | POST | /v1/openclaude/agents/validate | OpenClaude |
| delete_agent_v1_openclaude_agents_name_delete | DELETE | /v1/openclaude/agents/{name} | OpenClaude |
| get_agent_v1_openclaude_agents_name_get | GET | /v1/openclaude/agents/{name} | OpenClaude |
| update_agent_v1_openclaude_agents_name_put | PUT | /v1/openclaude/agents/{name} | OpenClaude |
| run_agent_v1_openclaude_agents_name_run_post | POST | /v1/openclaude/agents/{name}/run | OpenClaude |
| catalog_list_agents_v1_openclaude_catalog_agents_get | GET | /v1/openclaude/catalog/agents | OpenClaude |
| catalog_get_agent_v1_openclaude_catalog_agents_name_get | GET | /v1/openclaude/catalog/agents/{name} | OpenClaude |
| analyze_needs_v1_prompt_engineer_analyze_post | POST | /v1/prompt-engineer/analyze | Prompt Engineer |
| evaluate_prompt_v1_prompt_engineer_evaluate_post | POST | /v1/prompt-engineer/evaluate | Prompt Engineer |
| get_prompt_examples_v1_prompt_engineer_examples_get | GET | /v1/prompt-engineer/examples | Prompt Engineer |
| generate_prompt_v1_prompt_engineer_generate_post | POST | /v1/prompt-engineer/generate | Prompt Engineer |
| suggest_improvements_v1_prompt_engineer_improve_post | POST | /v1/prompt-engineer/improve | Prompt Engineer |
| optimize_prompt_v1_prompt_engineer_optimize_post | POST | /v1/prompt-engineer/optimize | Prompt Engineer |
| generate_variations_v1_prompt_engineer_variations_post | POST | /v1/prompt-engineer/variations | Prompt Engineer |
| list_collections_v1_qdrant_collections_get | GET | /v1/qdrant/collections | Qdrant |
| create_collection_v1_qdrant_collections_post | POST | /v1/qdrant/collections | Qdrant |
| structured_ingest_v1_qdrant_collections_structured_ingest_post | POST | /v1/qdrant/collections/structured_ingest | Qdrant |
| delete_collection_v1_qdrant_collections_collection_name_delete | DELETE | /v1/qdrant/collections/{collection_name} | Qdrant |
| ensure_legal_indexes_v1_qdrant_collections_collection_name_ensure_indexes_post | POST | /v1/qdrant/collections/{collection_name}/ensure-indexes | Qdrant |
| ingest_files_v1_qdrant_collections_collection_name_ingest_post | POST | /v1/qdrant/collections/{collection_name}/ingest | Qdrant |
| query_with_vector_v1_qdrant_collections_collection_name_query_vector_post | POST | /v1/qdrant/collections/{collection_name}/query/vector | Qdrant |
| get_collection_summary_v1_qdrant_collections_collection_name_summary_get | GET | /v1/qdrant/collections/{collection_name}/summary | Qdrant |
| connect_to_qdrant_v1_qdrant_connect_post | POST | /v1/qdrant/connect | Qdrant |
| embed_case_directory_v1_qdrant_embed_case_directory_post | POST | /v1/qdrant/embed-case-directory | Qdrant |
| search_qdrant_v1_qdrant_qdrant_search_post | POST | /v1/qdrant/qdrant/search | Qdrant |
| query_points_v1_qdrant_query_post | POST | /v1/qdrant/query | Qdrant |
| search_with_text_v1_qdrant_search_post | POST | /v1/qdrant/search | Qdrant |
| list_threads_v1_threads_get | GET | /v1/threads/ | Threads |
| create_thread_v1_threads_post | POST | /v1/threads/ | Threads |
| delete_thread_v1_threads_thread_id_delete | DELETE | /v1/threads/{thread_id} | Threads |
| get_thread_v1_threads_thread_id_get | GET | /v1/threads/{thread_id} | Threads |
| attach_file_to_thread_v1_threads_thread_id_files_post | POST | /v1/threads/{thread_id}/files | Threads |
| list_messages_v1_threads_thread_id_messages_get | GET | /v1/threads/{thread_id}/messages | Threads |
| add_message_v1_threads_thread_id_messages_post | POST | /v1/threads/{thread_id}/messages | Threads |
| create_run_v1_threads_thread_id_runs_post | POST | /v1/threads/{thread_id}/runs | Threads |
| list_tools_v1_tools_get | GET | /v1/tools |  |
| deep_reasoning_v1_tools_deep_reasoning_post | POST | /v1/tools/deep_reasoning |  |
| execute_tool_by_name_v1_tools_execute_post | POST | /v1/tools/execute |  |
| delete_tool_v1_tools_tool_name_delete | DELETE | /v1/tools/{tool_name} |  |
| get_tool_v1_tools_tool_name_get | GET | /v1/tools/{tool_name} |  |
| execute_tool_v1_tools_tool_name_execute_post | POST | /v1/tools/{tool_name}/execute |  |
| create_tool_v1_v1_tools_post | POST | /v1/v1/tools |  |
| analyze_document_structure_v2_legal_ingestion_analyze_document_structure_post | POST | /v2/legal-ingestion/analyze-document-structure | Legal Document Ingestion V2 |
| ingest_legal_file_enhanced_v2_legal_ingestion_ingest_legal_file_enhanced_post | POST | /v2/legal-ingestion/ingest-legal-file-enhanced | Legal Document Ingestion V2 |
| ingest_legal_folder_v2_legal_ingestion_ingest_legal_folder_post | POST | /v2/legal-ingestion/ingest-legal-folder | Legal Document Ingestion V2 |
| analyze_transcript_structure_v2_transcripts_analyze_post | POST | /v2/transcripts/analyze | Transcript Ingestion |
| ingest_transcript_enhanced_v2_transcripts_ingest_enhanced_post | POST | /v2/transcripts/ingest-enhanced | Transcript Ingestion |
| ingest_transcript_json_v2_transcripts_ingest_json_post | POST | /v2/transcripts/ingest-json | Transcript Ingestion |