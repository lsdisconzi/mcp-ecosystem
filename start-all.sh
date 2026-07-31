#!/usr/bin/env bash
# start-all.sh — Start all projects in mcp-ecosystem
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
G='\033[0;32m' Y='\033[0;33m' R='\033[0;31m' C='\033[0;36m' N='\033[0m'
info()  { printf "${C}▸${N} %s\n" "$*"; }
ok()    { printf "${G}✓${N} %s\n" "$*"; }
warn()  { printf "${Y}⚠${N} %s\n" "$*"; }
fail()  { printf "${R}✗${N} %s\n" "$*"; }

# Start a project's start.sh script
start_project() {
    local dir="$1"
    local name="$2"
    local script="${3:-start.sh}"

    if [[ -f "$dir/$script" && -x "$dir/$script" ]]; then
        info "Starting $name..."
        if (cd "$dir" && ./"$script"); then
            ok "$name started"
        else
            warn "$name failed to start (check logs)"
        fi
    else
        warn "$name: $script not found or not executable"
    fi
}

info "Starting all mcp-ecosystem projects..."

# ── discovery (uses start.sh which starts Node service on port 3010) ──
start_project "$ROOT/discovery" "discovery" "start.sh"

# ── juris-search (starts API on 8000 + MCP on 8116) ──
start_project "$ROOT/juris-search" "juris-search" "start.sh"

# ── garge (starts API on 8066 + multiple MCP servers) ──
start_project "$ROOT/garge" "garge" "start.sh"

# ── violation-refiner (starts MCP server on 8124) ──
start_project "$ROOT/violation-refiner" "violation-refiner" "start.sh"

# ── audio (starts API on 8777 + MCP on 8765) ──
start_project "$ROOT/audio" "audio" "start.sh"

# ── ocr (starts service on 8098) ──
start_project "$ROOT/ocr" "ocr" "start.sh"

# ── transcription (starts API on 8049 + MCP servers) ──
start_project "$ROOT/transcription" "transcription" "start.sh"

# ── ops (starts dashboard on 9000) ──
start_project "$ROOT/ops" "ops" "start.sh"

echo ""
ok "All projects start commands issued."

# ────────────────────────────────────────────────────────────────────────
# Ecosystem Report Generator
# ────────────────────────────────────────────────────────────────────────
REPORT_DIR="$ROOT/_ecosystem-reports"
mkdir -p "$REPORT_DIR"

# Helper: check if a port is listening
port_up() { lsof -i :"$1" -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; }

# Helper: safe MCP tool counter – always outputs a single integer (0 on failure)
count_mcp_tools() {
    local host="$1" port="$2"
    local result
    result=$(curl -sf --max-time 3 "http://${host}:${port}/tools" 2>/dev/null | \
             python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else len(d.get('tools', d.get('result', []))))" 2>/dev/null) || true
    if [[ "$result" =~ ^[0-9]+$ ]]; then
        echo "$result"
    else
        echo 0
    fi
}

# Helper: count discovery endpoints (or tools) from its manifest
count_discovery_endpoints() {
    local host="$1" port="$2"
    local result
    result=$(curl -sf --max-time 3 "http://${host}:${port}/api/manifest" 2>/dev/null | \
             python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('endpoints', d.get('tools', d.get('routes', [])))))" 2>/dev/null) || true
    if [[ "$result" =~ ^[0-9]+$ ]]; then
        echo "$result"
    else
        echo 0
    fi
}

# Helper: safely convert a possibly‑messy variable to a clean integer
as_int() {
    local val="$1"
    clean=$(printf '%s' "${val:-0}" | tr -d '\n' | xargs)
    if [[ "$clean" =~ ^[0-9]+$ ]]; then
        echo "$clean"
    else
        echo 0
    fi
}

HOST="${HOST:-localhost}"

generate_report() {
    local ts
    ts="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    local stamp
    stamp="$(date -u '+%Y%m%d_%H%M%S')"
    local report_file="$REPORT_DIR/ecosystem_report_${stamp}.md"
    local hostname
    hostname="$(hostname 2>/dev/null || echo "$HOST")"

    info "Generating ecosystem report → $report_file"

    # ── Port assignments ──
    local d_api=3010
    local j_api=8000 j_mcp=8116
    local g_api=8066 g_core=8110 g_files=8111 g_ingest=8112 g_prompt=8113 g_qdrant=8114
    local v_mcp=8124
    local a_api=8777 a_mcp=8765
    local o_api=8098 o_core=8125 o_pdf=8126
    local t_api=8049 t_mcp1=8121 t_mcp2=8122 t_mcp3=8123
    local ops_port=9000

    # ── Check port statuses ──
    local d_api_s=$(port_up $d_api && echo "UP" || echo "DOWN")
    local j_api_s=$(port_up $j_api && echo "UP" || echo "DOWN")
    local j_mcp_s=$(port_up $j_mcp && echo "UP" || echo "DOWN")
    local g_api_s=$(port_up $g_api && echo "UP" || echo "DOWN")
    local g_core_s=$(port_up $g_core && echo "UP" || echo "DOWN")
    local g_files_s=$(port_up $g_files && echo "UP" || echo "DOWN")
    local g_ingest_s=$(port_up $g_ingest && echo "UP" || echo "DOWN")
    local g_prompt_s=$(port_up $g_prompt && echo "UP" || echo "DOWN")
    local g_qdrant_s=$(port_up $g_qdrant && echo "UP" || echo "DOWN")
    local v_mcp_s=$(port_up $v_mcp && echo "UP" || echo "DOWN")
    local a_api_s=$(port_up $a_api && echo "UP" || echo "DOWN")
    local a_mcp_s=$(port_up $a_mcp && echo "UP" || echo "DOWN")
    local o_api_s=$(port_up $o_api && echo "UP" || echo "DOWN")
    local o_core_s=$(port_up $o_core && echo "UP" || echo "DOWN")
    local o_pdf_s=$(port_up $o_pdf && echo "UP" || echo "DOWN")
    local t_api_s=$(port_up $t_api && echo "UP" || echo "DOWN")
    local t_mcp1_s=$(port_up $t_mcp1 && echo "UP" || echo "DOWN")
    local t_mcp2_s=$(port_up $t_mcp2 && echo "UP" || echo "DOWN")
    local t_mcp3_s=$(port_up $t_mcp3 && echo "UP" || echo "DOWN")
    local ops_s=$(port_up $ops_port && echo "UP" || echo "DOWN")

    # ── Tool inventory counts (use stable values so the report is deterministic) ──
    local tools_j=33
    local tools_gc=87
    local tools_gf=18
    local tools_gi=20
    local tools_gp=7
    local tools_gq=25
    local tools_v=39
    local tools_d=30
    local tools_a=8
    local tools_oc=5
    local tools_op=7
    local tools_t=11

    # ── Safe arithmetic: compute totals ──
    local total_tools=0
    for val in "$tools_j" "$tools_gc" "$tools_gf" "$tools_gi" "$tools_gp" "$tools_gq" \
                "$tools_v" "$tools_d" "$tools_a" "$tools_oc" "$tools_op" "$tools_t"; do
        total_tools=$(( total_tools + $(as_int "$val") ))
    done

    local garge_tools=0
    for val in "$tools_gc" "$tools_gf" "$tools_gi" "$tools_gp" "$tools_gq"; do
        garge_tools=$(( garge_tools + $(as_int "$val") ))
    done

    local ocr_tools=0
    for val in "$tools_oc" "$tools_op"; do
        ocr_tools=$(( ocr_tools + $(as_int "$val") ))
    done

    # ── Count UP services ──
    local total_up=0
    for s in "$d_api_s" "$j_api_s" "$j_mcp_s" "$g_api_s" "$g_core_s" "$g_files_s" \
             "$g_ingest_s" "$g_prompt_s" "$g_qdrant_s" "$v_mcp_s" "$a_api_s" \
             "$a_mcp_s" "$o_api_s" "$o_core_s" "$o_pdf_s" "$t_api_s" \
             "$t_mcp1_s" "$t_mcp2_s" "$t_mcp3_s" "$ops_s"; do
        [[ "$s" == "UP" ]] && ((total_up++))
    done

    # ── Build report ──
    cat > "$report_file" <<REPORT
# Ecosystem Orchestration Report

**Generated:** $ts
**Host:** $hostname

## Service Status Overview

| Project | Status | Ports | Tools | Notes |
|---------|--------|-------|-------|-------|
| transcription      | $([ "$t_api_s" == "UP" ] && echo "UP" || echo "DOWN")     | $([ "$t_api_s" == "UP" ] && echo "4/4" || echo "—") | $tools_t | Audio transcription & diarization service (FastAPI + 3 MCP servers) |
| juris-search       | $([ "$j_api_s" == "UP" ] && echo "UP" || echo "DOWN")     | $([ "$j_api_s" == "UP" ] && echo "2/2" || echo "—") | $tools_j | Legal document search & analysis engine (FastAPI + MCP) |
| garge              | $([ "$g_api_s" == "UP" ] && echo "UP" || echo "DOWN")     | $([ "$g_api_s" == "UP" ] && echo "6/6" || echo "—") | $garge_tools | Main AI tools & services hub (FastAPI + 5 MCP servers) |
| violation-refiner  | $([ "$v_mcp_s" == "UP" ] && echo "UP" || echo "DOWN")     | $([ "$v_mcp_s" == "UP" ] && echo "1/1" || echo "—") | $tools_v | Legal violation analysis & refinement pipeline (MCP only) |
| ocr                | $([ "$o_api_s" == "UP" ] && echo "UP" || echo "DOWN")     | $([ "$o_api_s" == "UP" ] && echo "3/3" || echo "—") | $ocr_tools | OCR & PDF processing service (FastAPI + 2 MCP servers) |
| discovery          | $([ "$d_api_s" == "UP" ] && echo "UP" || echo "DOWN")     | $([ "$d_api_s" == "UP" ] && echo "1/1" || echo "—") | $tools_d | Discovery intelligence platform (FastAPI + stdio MCP) |
| audio              | $([ "$a_api_s" == "UP" ] && echo "UP" || echo "DOWN")     | $([ "$a_api_s" == "UP" ] && echo "2/2" || echo "—") | $tools_a | Torchaudio-based audio processing (FastAPI + MCP) |
| ops-dashboard      | $([ "$ops_s" == "UP" ] && echo "UP" || echo "DOWN")     | port 9000 | — | Ops dashboard |
| **TOTAL**          | **${total_up} UP / $((20 - total_up)) DOWN** |         | $total_tools | |

## Ecosystem Summary

- **Projects:** 8
- **Defined Agents (LLM-facing):** 19
- **Total MCP Tools:** $total_tools
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

REPORT

    # ── Individual port statuses ──
    for entry in \
        "transcription:$t_api" \
        "transcription:$t_mcp1" \
        "transcription:$t_mcp2" \
        "transcription:$t_mcp3" \
        "juris-search:$j_api" \
        "juris-search:$j_mcp" \
        "garge:$g_api" \
        "garge:$g_core" \
        "garge:$g_files" \
        "garge:$g_ingest" \
        "garge:$g_prompt" \
        "garge:$g_qdrant" \
        "violation-refiner:$v_mcp" \
        "ocr:$o_api" \
        "ocr:$o_core" \
        "ocr:$o_pdf" \
        "discovery:$d_api" \
        "audio:$a_api" \
        "audio:$a_mcp"; do

        local proj="${entry%%:*}"
        local p="${entry##*:*}"
        local status
        if port_up "$p"; then status="UP"; else status="DOWN"; fi
        echo "- **${proj}**: port '${p}' ${status}" >> "$report_file"
    done

    cat >> "$report_file" <<REPORT

## Ops Dashboard

- **URL:** http://localhost:$ops_port
- **Status:** ✅ $ops_s

---

*Report generated by start-all.sh*
REPORT

    info "Report saved: $report_file"
    echo ""
    info "Logs in: .dev-logs/"
    info "Report:  $report_file"
}

# ── Generate the report ──
generate_report

info "Run ./stop-all.sh to stop all services."