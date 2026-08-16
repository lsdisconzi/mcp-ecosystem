# Ecosystem Orchestration Report

**Generated:** 2026-08-11 10:21:34 UTC
**Host:** MacBook-Pro-de-Leandro.local

## Service Status Overview

| Project | Status | Ports | Tools | Notes |
|---------|--------|-------|-------|-------|
| transcription      | UP     | 4/4 | 11 | Audio transcription & diarization service (FastAPI + 3 MCP servers) |
| juris-search       | UP     | 2/2 | 33 | Legal document search & analysis engine (FastAPI + MCP) |
| garge              | DOWN     | — | 157 | Main AI tools & services hub (FastAPI + 5 MCP servers) |
| violation-refiner  | DOWN     | — | 39 | Legal violation analysis & refinement pipeline (MCP only) |
| ocr                | UP     | 3/3 | 12 | OCR & PDF processing service (FastAPI + 2 MCP servers) |
| discovery          | UP     | 1/1 | 30 | Discovery intelligence platform (FastAPI + stdio MCP) |
| audio              | UP     | 2/2 | 8 | Torchaudio-based audio processing (FastAPI + MCP) |
| ops-dashboard      | UP     | port 9000 | — | Ops dashboard |
| comfyui            | UP     | 4/4 | 22 | ComfyUI workflow/model/node/system MCP servers (4) |
| **TOTAL**          | **20 UP / 4 DOWN** |         | 312 | |

## Ecosystem Summary

- **Projects:** 9
- **Defined Agents (LLM-facing):** 19
- **Total MCP Tools:** 312
- **Human Interfaces (UIs & APIs):** 18
- **Configurable Parameters:** 15

## Agent & Human Interface Overview

| Project | Agents | Human Interfaces | Key Parameters |
|---------|--------|------------------|----------------|
| transcription      | transcriber,diarizer,translator | Pinocchio Transcription UI,Revision UI,Curadoria UI,REST API,Health | model,language |
| juris-search       | legal_searcher,legal_indexer,legal_analyst | Juris Search UI,REST API,Swagger Docs | jurisdiction,collections |
| garge              | garage_assistant,qdrant_manager,file_manager,prompt_engineer | Swagger UI,Garage UI,Qdrant UI,REST API | QDRANT_URL,OLLAMA_HOST,DEEPSEEK_BASE_URL,embedding_model |
| violation-refiner  | violation_checker,authority_verifier,qdrant_indexer |  | schema_version,top_k |
| ocr                | ocr_reader,pdf_processor | OCR UI | engine,llm_enhancement |
| discovery          | discovery_agent,intelligence_analyst | Discovery UI,REST API,Case API | start_path |
| audio              | audio_processor,asr_manager | Audio Processing Unit UI,REST API | sample_rate,asr_bundle |
| comfyui            | workflow_manager,model_manager,node_inspector,system_ops | ComfyUI UI (localhost:8188) | COMFYUI_BASE_URL |

## Detailed MCP Server Inventory

### transcription
| Port | Server Name | Transport | Tools |
|------|-------------|-----------|-------|
| 8121 | transcription-core | sse | transcription_transcribe_audio, transcription_transcribe_audio_async, transcription_list_models, transcription_get_status, transcription_cancel_job |
| 8122 | diarization | sse | transcription_diarize, transcription_speaker_id, transcription_segment_speakers |
| 8123 | translate | sse | transcription_translate, transcription_sentiment, transcription_summarize |

### juris-search
| Port | Server Name | Transport | Tools |
|------|-------------|-----------|-------|
| 8116 | juris-mcp | sse | juris_chat, juris_search_start, juris_search_status, juris_results, juris_search_history, juris_search_history_file, juris_storage_paths, juris_download, juris_download_status, juris_download_batch, juris_health, juris_stats, juris_docx_index, juris_json_index, juris_docx_rebuild, juris_json_rebuild, juris_storage_rebuild, juris_master_index_stats, juris_master_index_documents, juris_master_index_document, juris_master_index_rebuild, juris_master_index_markdown, juris_master_index_search, juris_flat_corpus_stats, juris_citations, juris_relator_network, juris_master_index_summary, juris_legal_framework_search, juris_legal_framework_stats, juris_upload_file, juris_set_base_url, juris_start_service, juris_stop_service |

### garge
| Port | Server Name | Transport | Tools |
|------|-------------|-----------|-------|
| 8110 | garage-core | sse | garage_health, garage_list_models, garage_chat_completions, garage_list_assistants, garage_list_files, garage_get_assistant, garage_update_assistant, garage_replace_assistant, garage_create_assistant, garage_delete_assistant, garage_assistant_chat, garage_attach_file_to_assistant, garage_list_assistant_files, garage_detach_file_from_assistant, garage_query_assistant_knowledge, garage_assign_tool_to_assistant, garage_assistant_deepseek, garage_deepseek_engineer_chat, garage_deepseek_stream_proxy, garage_query_knowledge, garage_query_assistant_knowledge_collections, garage_ingest_knowledge_text, garage_ingest_knowledge_file, garage_clear_knowledge_collection, garage_get_knowledge_collection_stats, garage_list_tools, garage_get_tool, garage_delete_tool, garage_execute_tool, garage_execute_tool_by_name, garage_create_tool, garage_deep_reasoning, garage_create_thread, garage_list_threads, garage_get_thread, garage_delete_thread, garage_add_thread_message, garage_list_thread_messages, garage_create_thread_run, garage_attach_file_to_thread |
| 8111 | garage-files | sse | files_list, files_read, files_summarize, files_upload, files_upload_transcript, files_upload_law, files_get_content, files_delete, files_list_transcripts, files_list_laws |
| 8112 | garage-ingestion | sse | ingestion_collection_info, ingestion_search, ingestion_ingest_directory, ingestion_ingest_files, ingestion_list_collections, ingestion_delete_collection, ingestion_collection_stats, ingestion_batch_ingest, ingestion_status, ingestion_legal_ingest, ingestion_transcript_ingest, ingestion_legal_v2_ingest |
| 8113 | garage-prompt | sse | prompt_generate, prompt_analyze, prompt_variations, prompt_optimize, prompt_evaluate, prompt_improve, prompt_examples |
| 8114 | garage-qdrant | sse | qdrant_connect, qdrant_list_collections, qdrant_create_collection, qdrant_collection_summary, qdrant_search, qdrant_structured_ingest, qdrant_ensure_legal_indexes, qdrant_ingest_file, qdrant_ingest_directory, embed_uploads_global, embed_project_uploads, embed_dev_code, qdrant_embed_case_directory, qdrant_query, qdrant_search_legacy, qdrant_index_reviewed_transcript, qdrant_query_vector, qdrant_delete_collection |

### violation-refiner
| Port | Server Name | Transport | Tools |
|------|-------------|-----------|-------|
| 8124 | violation-mcp | sse | init_violation, build_evidence_layer_tool, build_norms_layer_tool, add_element_grid_tool, build_nexus_layer_tool, add_authority_stub_tool, verify_statute_in_bundle_tool, verify_statute_external_fetch_tool, verify_human_attested_tool, derive_confidence_tool, attach_confidence_tool, run_pipeline_tool, write_violation_json_tool, build_manifest_tool, zip_bundle_tool, copy_source_into_bundle_tool, refine_batch_tool, qdrant_index_violation_tool, qdrant_search_segments_tool, qdrant_search_articles_tool, qdrant_search_authorities_tool, qdrant_search_jurisprudence_tool, qdrant_upsert_jurisprudence_tool, neo4j_upsert_violation_tool, neo4j_find_violations_citing_tool, neo4j_find_violations_with_contested_element_tool, neo4j_walk_implications_tool, jurisprudence_search_tool, jurisprudence_verify_tool, qdrant_reset_collections_tool, neo4j_reset_database_tool, embedder_info_tool, jurisprudence_ingest_tool, transcript_ingest_tool, framework_ingest_tool, enrich_violation_tool, enrich_stage_tool, verify_enrichment_tool, llm_provider_info_tool |

### ocr
| Port | Server Name | Transport | Tools |
|------|-------------|-----------|-------|
| 8125 | ocr-core | sse | ocr_list_images, ocr_process_image, ocr_compare_results, ocr_run_batch, ocr_list_output_artifacts |
| 8126 | pdf-server | sse | pdf_scan_files, pdf_extract_text, pdf_analyze_pdf, pdf_convert_analysis_directory_to_csv, pdf_generate_renaming_plan_from_csv, pdf_apply_renaming_plan, pdf_run_pipeline |

### discovery
| Port | Server Name | Transport | Tools |
|------|-------------|-----------|-------|
| stdio | discovery-mcp | stdio | discovery_health, discovery_manifest, discovery_endpoints, discovery_files, discovery_categories, discovery_search, discovery_tree, discovery_rebuild, discovery_organize, discovery_init_session, discovery_reset_session, discovery_law_frameworks, discovery_law_framework_articles, discovery_file_detail, discovery_pipeline_entities, discovery_pipeline_relationships, discovery_pipeline_timeline, discovery_pipeline_stats, discovery_pipeline_search, discovery_intelligence_status, discovery_intelligence_run, discovery_intelligence_summary, discovery_intelligence_case_graph, discovery_intelligence_violations, discovery_intelligence_findings, discovery_intelligence_timeline, discovery_intelligence_narrative, discovery_intelligence_gap_report, discovery_intelligence_law_registry, discovery_intelligence_dedup_report |

### audio
| Port | Server Name | Transport | Tools |
|------|-------------|-----------|-------|
| 8765 | audio-mcp | sse | transcription_healthcheck, transcription_audio_info, transcription_resample_audio, transcription_slice_audio, transcription_extract_features, transcription_list_asr_bundles, transcription_transcribe_greedy, transcription_list_project_paths |

### comfyui
| Port | Server Name | Transport | Tools |
|------|-------------|-----------|-------|
| 8130 | comfyui-workflow | streamable-http | comfyui_list_jobs, comfyui_get_job, comfyui_cancel_job, comfyui_list_history, comfyui_get_history, comfyui_get_queue, comfyui_clear_queue, comfyui_delete_queue_item, comfyui_interrupt, comfyui_free_memory, comfyui_clear_history, comfyui_delete_history_item |
| 8131 | comfyui-model | streamable-http | comfyui_list_model_folders, comfyui_list_models, comfyui_list_embeddings, comfyui_view_metadata |
| 8132 | comfyui-node | streamable-http | comfyui_list_nodes, comfyui_get_node_info |
| 8133 | comfyui-system | streamable-http | comfyui_system_stats, comfyui_list_features, comfyui_get_extensions, comfyui_ecosystem_report |

## Qdrant Collections Map (live)

⚠️ Could not fetch Qdrant collections.

## Human Interaction Endpoints

**transcription**
- Pinocchio Transcription UI: http://localhost:8049/pinocchio
- Revision UI: http://localhost:8049/revision
- Curadoria UI: http://localhost:8049/curadoria
- REST API: /api/v1/transcribe
- Health: http://localhost:8049/health

**juris-search**
- Juris Search UI: http://localhost:8000/
- REST API: /api/v1/search
- Swagger Docs: http://localhost:8000/docs

**garge**
- Swagger UI: http://localhost:8066/docs
- Garage UI: http://localhost:8066/garage
- Qdrant UI: http://localhost:8066/qdrant
- REST API: /api/v1/*

**ocr**
- OCR UI: http://localhost:8098/

**discovery**
- Discovery UI: http://localhost:3010
- REST API: /api/manifest
- Case API: http://localhost:3010/cases

**audio**
- Audio Processing Unit UI: http://localhost:8777/
- REST API: /api/v1/audio/upload

## Configuration Parameters Reference

### transcription
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| model | string | default: base | Whisper model size |
| language | string | default: auto | Language code or auto-detect |

### juris-search
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| jurisdiction | string | default: BR | Legal jurisdiction for search scope |
| collections | string | default: all | Qdrant collections to search across |

### garge
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| QDRANT_URL | string | default: http://localhost:6333 | Qdrant vector database URL |
| OLLAMA_HOST | string | default: http://localhost:11436 | Ollama LLM host |
| DEEPSEEK_BASE_URL | string | default: https://api.deepseek.com/v1 | DeepSeek API base URL |
| embedding_model | string | default: all-MiniLM-L6-v2 | Sentence transformer model for embeddings |

### violation-refiner
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| schema_version | string | default: 3.0 | Violation bundle schema version |
| top_k | int | default: 5 | Default top-K for Qdrant searches |

### ocr
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| engine | string | default: tesseract | OCR engine to use |
| llm_enhancement | boolean | default: true | Enable LLM post-processing of OCR results |

### discovery
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| start_path | string | default: . | Root directory for file discovery |

### audio
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| sample_rate | int | default: 16000 | Target sample rate for audio processing |
| asr_bundle | string | default: default | ASR model bundle to use for transcription |

## Agent Quick-Start Guide

1. **Check overall status:** read the Service Status table above.
2. **Search document embeddings:** use the garage-qdrant MCP tools (e.g., qdrant_search on collection uploads-global).
3. **Ingest new files:** call qdrant_ingest_directory with the desired directory path and collection name.
4. **Transcribe audio:** use the transcription MCP servers on ports 8121-8123.
5. **Retrieve tool details:** refer to the MCP Server Inventory section.
6. **Access human-facing UIs:** see Human Interaction Endpoints.

*All tool names and parameters are documented in the tables above.*

## Live Component Status

- **transcription**: port '' DOWN
- **transcription**: port '' DOWN
- **transcription**: port '' DOWN
- **transcription**: port '' DOWN
- **juris-search**: port '' DOWN
- **juris-search**: port '' DOWN
- **garge**: port '' DOWN
- **garge**: port '' DOWN
- **garge**: port '' DOWN
- **garge**: port '' DOWN
- **garge**: port '' DOWN
- **garge**: port '' DOWN
- **violation-refiner**: port '' DOWN
- **ocr**: port '' DOWN
- **ocr**: port '' DOWN
- **ocr**: port '' DOWN
- **discovery**: port '' DOWN
- **audio**: port '' DOWN
- **audio**: port '' DOWN
- **comfyui**: port '' DOWN
- **comfyui**: port '' DOWN
- **comfyui**: port '' DOWN
- **comfyui**: port '' DOWN

## Ops Dashboard

- **URL:** http://localhost:9000
- **Status:** ✅ UP

---

*Report generated by start-all.sh*
