# Juris MCP Route Catalog

Source: http://127.0.0.1:8000/openapi.json

Routes: 70

| Method | Path | Tags | Tool |
|---|---|---|---|
| GET | /api/admin/qdrant-collections |  | qdrant_collections_api_admin_qdrant_collections_get |
| POST | /api/chat |  | chat_endpoint_api_chat_post |
| GET | /api/courts |  | list_courts_api_courts_get |
| GET | /api/docx/index |  | docx_index_api_docx_index_get |
| POST | /api/docx/rebuild |  | docx_rebuild_api_docx_rebuild_post |
| POST | /api/download |  | download_inteiro_teor_api_download_post |
| POST | /api/download-batch |  | download_batch_compat_api_download_batch_post |
| GET | /api/download/status/{job_id} |  | download_status_api_download_status_job_id_get |
| GET | /api/health |  | health_api_health_get |
| GET | /api/json/index |  | json_index_api_json_index_get |
| POST | /api/json/rebuild |  | json_rebuild_api_json_rebuild_post |
| GET | /api/master-index/document/{doc_id} |  | master_index_document_api_master_index_document_doc_id_get |
| GET | /api/master-index/document/{doc_id}/correlations |  | master_index_document_correlations_api_master_index_document_doc_id_correlations_get |
| GET | /api/master-index/documents |  | master_index_documents_api_master_index_documents_get |
| GET | /api/master-index/download-file |  | master_index_download_file_api_master_index_download_file_get |
| GET | /api/master-index/jurisprudence |  | master_index_jurisprudence_api_master_index_jurisprudence_get |
| GET | /api/master-index/jurisprudence/markdown |  | master_index_jurisprudence_markdown_api_master_index_jurisprudence_markdown_get |
| GET | /api/master-index/markdown |  | master_index_markdown_api_master_index_markdown_get |
| POST | /api/master-index/pause |  | master_index_pause_api_master_index_pause_post |
| POST | /api/master-index/rebuild |  | master_index_rebuild_api_master_index_rebuild_post |
| POST | /api/master-index/resume |  | master_index_resume_api_master_index_resume_post |
| POST | /api/master-index/search |  | master_index_semantic_search_api_master_index_search_post |
| GET | /api/master-index/stats |  | master_index_stats_api_master_index_stats_get |
| GET | /api/results/{job_id} |  | get_results_api_results_job_id_get |
| POST | /api/search |  | start_search_api_search_post |
| GET | /api/search/history |  | list_search_history_api_search_history_get |
| GET | /api/search/history/{filename} |  | get_search_history_file_api_search_history_filename_get |
| GET | /api/search/status/{job_id} |  | search_status_api_search_status_job_id_get |
| GET | /api/stats |  | stats_compat_api_stats_get |
| GET | /api/storage/paths |  | get_storage_paths_api_storage_paths_get |
| POST | /api/storage/rebuild |  | storage_rebuild_api_storage_rebuild_post |
| POST | /api/upload |  | upload_file_api_upload_post |
| GET | /courts |  | list_courts_courts_get |
| GET | /health |  | health_legacy_health_get |
| GET | /juris/api/admin/qdrant-collections |  | qdrant_collections_juris_api_admin_qdrant_collections_get |
| POST | /juris/api/chat |  | chat_endpoint_juris_api_chat_post |
| GET | /juris/api/courts |  | list_courts_juris_api_courts_get |
| GET | /juris/api/docx/index |  | docx_index_juris_api_docx_index_get |
| POST | /juris/api/docx/rebuild |  | docx_rebuild_juris_api_docx_rebuild_post |
| POST | /juris/api/download |  | download_inteiro_teor_juris_api_download_post |
| POST | /juris/api/download-batch |  | download_batch_compat_juris_api_download_batch_post |
| GET | /juris/api/download/status/{job_id} |  | download_status_juris_api_download_status_job_id_get |
| GET | /juris/api/health |  | health_juris_api_health_get |
| GET | /juris/api/json/index |  | json_index_juris_api_json_index_get |
| POST | /juris/api/json/rebuild |  | json_rebuild_juris_api_json_rebuild_post |
| GET | /juris/api/master-index/document/{doc_id} |  | master_index_document_juris_api_master_index_document_doc_id_get |
| GET | /juris/api/master-index/document/{doc_id}/correlations |  | master_index_document_correlations_juris_api_master_index_document_doc_id_correlations_get |
| GET | /juris/api/master-index/documents |  | master_index_documents_juris_api_master_index_documents_get |
| GET | /juris/api/master-index/download-file |  | master_index_download_file_juris_api_master_index_download_file_get |
| GET | /juris/api/master-index/jurisprudence |  | master_index_jurisprudence_juris_api_master_index_jurisprudence_get |
| GET | /juris/api/master-index/jurisprudence/markdown |  | master_index_jurisprudence_markdown_juris_api_master_index_jurisprudence_markdown_get |
| GET | /juris/api/master-index/markdown |  | master_index_markdown_juris_api_master_index_markdown_get |
| POST | /juris/api/master-index/pause |  | master_index_pause_juris_api_master_index_pause_post |
| POST | /juris/api/master-index/rebuild |  | master_index_rebuild_juris_api_master_index_rebuild_post |
| POST | /juris/api/master-index/resume |  | master_index_resume_juris_api_master_index_resume_post |
| POST | /juris/api/master-index/search |  | master_index_semantic_search_juris_api_master_index_search_post |
| GET | /juris/api/master-index/stats |  | master_index_stats_juris_api_master_index_stats_get |
| GET | /juris/api/results/{job_id} |  | get_results_juris_api_results_job_id_get |
| POST | /juris/api/search |  | start_search_juris_api_search_post |
| GET | /juris/api/search/history |  | list_search_history_juris_api_search_history_get |
| GET | /juris/api/search/history/{filename} |  | get_search_history_file_juris_api_search_history_filename_get |
| GET | /juris/api/search/status/{job_id} |  | search_status_juris_api_search_status_job_id_get |
| GET | /juris/api/stats |  | stats_compat_juris_api_stats_get |
| GET | /juris/api/storage/paths |  | get_storage_paths_juris_api_storage_paths_get |
| POST | /juris/api/storage/rebuild |  | storage_rebuild_juris_api_storage_rebuild_post |
| POST | /juris/api/upload |  | upload_file_juris_api_upload_post |
| GET | /juris/courts |  | list_courts_juris_courts_get |
| GET | /juris/health |  | health_legacy_juris_health_get |
| GET | /juris/stats |  | stats_compat_juris_stats_get |
| GET | /stats |  | stats_compat_stats_get |