# MCP Tool → Implementation Map

**Generated from source, verified against `violation_pack/` on 2026-09-11.**
Server implementation: `violation_pack/mcp_server.py` (39 tools).
Machine-readable equivalent: `violation-pack-catalog --format catalog`.

The MCP layer is deliberately thin: each tool validates/coerces its arguments, calls a
library function, and returns a JSON-serializable dict. When a tool and a library
function disagree, **the library function is authoritative**.

Step numbers (`S0`–`S14`) refer to `docs/ui_structural_skeleton.md` §4.

---

## 1. Startup / identity

| MCP tool | Implementation | Module | Step |
| --- | --- | --- | --- |
| `init_violation` | inline (no library counterpart) | `mcp_server.py:101` | S1 |

> Note: `init_violation` is the only tool with no library backing — it constructs a
> `Violation` directly. Every other tool delegates.

## 2. Enrichment layers

| MCP tool | Implementation | Module | Step |
| --- | --- | --- | --- |
| `build_evidence_layer_tool` | `build_evidence_layer` | `layers.py:50` | S2 |
| `build_norms_layer_tool` | `build_norms_layer` | `layers.py:124` | S3 |
| `add_element_grid_tool` | `add_element_grid` | `layers.py:223` | S4 |
| `build_nexus_layer_tool` | `build_nexus_layer` | `layers.py:246` | S5 |
| `add_authority_stub_tool` | `add_authority_stub` | `layers.py:281` | S6 |

## 3. Authority verification

| MCP tool | Implementation | Module | Protocol literal | Step |
| --- | --- | --- | --- | --- |
| `verify_statute_in_bundle_tool` | `verify_statute_in_bundle` | `authority_verification.py:102` | `statute_in_bundle_v1` | S7a |
| `verify_statute_external_fetch_tool` | `verify_statute_external_fetch` | `authority_verification.py:193` | `statute_external_fetch_v1` | S7b |
| `verify_human_attested_tool` | `verify_human_attested` | `authority_verification.py:262` | `human_attested_v1` | S7c |

All three raise `ValueError("verification_failed: …")` (backed by `VerificationError`,
`authority_verification.py:54`).

## 4. Confidence

| MCP tool | Implementation | Module | Step |
| --- | --- | --- | --- |
| `derive_confidence_tool` | `derive_confidence` | `confidence.py:31` | S8 |
| `attach_confidence_tool` | `attach_confidence` | `confidence.py:107` | S8 |

## 5. Validation

| MCP tool | Implementation | Module | Step |
| --- | --- | --- | --- |
| `run_pipeline_tool` | `run_pipeline` (+ `DEFAULT_PIPELINE`, 11 checks) | `validation.py:317` | S10 |

Individual checks live in `validation.py` as `v01_segment_resolution` (40),
`v02_verbatim_quote_match` (58), `v03_article_text_hash` (75),
`v04_article_exists_in_framework_cache` (121), `v05_cross_references_resolve` (140),
`v06_element_coverage` (160), `v07_authorities_verification` (177),
`v08_contract_consistency` (197), `v09_language_consistency` (260),
`v10_confidence_derivation` (275).

**`v11_enrichment_integrity` is not in `validation.py`** — it lives in
`verifier.py:345` and is passed to `run_pipeline` as an extra check.

## 6. Packaging / I/O

| MCP tool | Implementation | Module | Step |
| --- | --- | --- | --- |
| `write_violation_json_tool` | `write_violation_json` | `pack.py:37` | S11 |
| `build_manifest_tool` | `build_manifest` | `pack.py:45` | S11 |
| `zip_bundle_tool` | `zip_bundle` | `pack.py:74` | S11 |
| `copy_source_into_bundle_tool` | `copy_source_into_bundle` | `pack.py:85` | S0 |

`bundle_path` (`pack.py:32`) resolves the `BUNDLE_LAYOUT` keys used by
`copy_source_into_bundle_tool`.

## 7. Batch

| MCP tool | Implementation | Module | Step |
| --- | --- | --- | --- |
| `refine_batch_tool` | `refine_batch_core.run` | `refine_batch_core.py:597` | S11 |

CLI wrapper: `examples/refine_batch.py`. Reference end-to-end script:
`examples/refine_cl005.py`.

## 8. LLM enrichment

| MCP tool | Implementation | Module | Step |
| --- | --- | --- | --- |
| `enrich_violation_tool` | `enrich_violation` (8 stages) | `enrich.py:859` | S9 |
| `enrich_stage_tool` | `enrich_violation` with a one-item `stages` list | `enrich.py:859` | S9 |
| `verify_enrichment_tool` | `verify_enrichment` | `verifier.py:118` | S9 |
| `llm_provider_info_tool` | `Settings.llm_client()` → provider/model | `config.py` + `llm.py:254` | S14 |

Stage functions behind `ENRICHMENT_STAGES` (`enrich.py:847`):

| Stage | Function | Line |
| --- | --- | --- |
| `segments` | `propose_segment_metadata` | 163 |
| `subsections` | `propose_article_subsections` | 220 |
| `element_grids` | `propose_element_grid` | 338 |
| `nexus` | `propose_nexus` | 461 |
| `candidates` | `propose_candidates` | 597 |
| `authorities` | `propose_authorities` | 662 |
| `open_questions` | `propose_open_questions` | 745 |
| `cross_references` | `propose_cross_references` | 804 |

LLM clients: `OpenAICompatibleClient` (`llm.py:100`), `AnthropicClient` (`llm.py:158`),
built by `build_client` (`llm.py:254`). Errors raise `LLMError` (`llm.py:33`).

## 9. Qdrant

| MCP tool | Implementation | Module | Destructive |
| --- | --- | --- | --- |
| `qdrant_index_violation_tool` | `QdrantVectorIndex.upsert_violation` (`:277`, which fans out to `upsert_segment`/`upsert_authority`/`upsert_article`) | `qdrant_index.py:31` | no |
| `qdrant_search_segments_tool` | `QdrantVectorIndex.search_segments` (`:199`) | `qdrant_index.py` | no |
| `qdrant_search_articles_tool` | `QdrantVectorIndex.search_articles` (`:251`) | `qdrant_index.py` | no |
| `qdrant_search_authorities_tool` | `QdrantVectorIndex.search_authorities` (`:227`) | `qdrant_index.py` | no |
| `qdrant_search_jurisprudence_tool` | `QdrantVectorIndex.search_jurisprudence` (`:255`) | `qdrant_index.py` | no |
| `qdrant_upsert_jurisprudence_tool` | `QdrantVectorIndex.upsert_jurisprudence_record` (`:261`) | `qdrant_index.py` | no |
| `qdrant_reset_collections_tool` | `QdrantVectorIndex.reset_collections` (`:115`) | `qdrant_index.py` | **YES** |

`ensure_collections` (`:82`) and `collections` (`:74`) are lifecycle helpers with no
dedicated tool. `QdrantVectorIndex` satisfies the `VectorIndex` Protocol
(`extensions.py:71`).

## 10. Neo4j

| MCP tool | Implementation | Module | Destructive |
| --- | --- | --- | --- |
| `neo4j_upsert_violation_tool` | `Neo4jKnowledgeGraph.upsert_violation` (`:109`) | `neo4j_graph.py:33` | no |
| `neo4j_find_violations_citing_tool` | `Neo4jKnowledgeGraph.find_violations_citing` (`:288`) | `neo4j_graph.py` | no |
| `neo4j_find_violations_with_contested_element_tool` | `Neo4jKnowledgeGraph.find_violations_with_contested_element` (`:299`) | `neo4j_graph.py` | no |
| `neo4j_walk_implications_tool` | `Neo4jKnowledgeGraph.walk_implications_of_open_question` (`:315`) | `neo4j_graph.py` | no |
| `neo4j_reset_database_tool` | `Neo4jKnowledgeGraph.reset_database` (`:82`) | `neo4j_graph.py` | **YES** |

Also on the class but untooled: `close` (`:55`), `ensure_database` (`:66`),
`ensure_constraints` (`:94`), `link_cross_references` (`:273`). Satisfies the
`KnowledgeGraph` Protocol (`extensions.py:105`).

## 11. Jurisprudence

| MCP tool | Implementation | Module |
| --- | --- | --- |
| `jurisprudence_search_tool` | `QdrantJurisprudenceProvider.search` (`:42`) | `jurisprudence.py:31` |
| `jurisprudence_verify_tool` | `QdrantJurisprudenceProvider.verify` (`:73`) | `jurisprudence.py` |

Satisfies the `JurisprudenceProvider` Protocol (`extensions.py:30`).

## 12. Bulk ingest

| MCP tool | Implementation | Module |
| --- | --- | --- |
| `jurisprudence_ingest_tool` | `JurisprudenceIngester.ingest` (`:166`) | `ingesters.py:128` |
| `transcript_ingest_tool` | `TranscriptIngester.ingest_bundle` (`:342`) / `ingest_paths` (`:354`) | `ingesters.py:304` |
| `framework_ingest_tool` | `FrameworkIngester.ingest_markdown` (`:567`) | `ingesters.py:542` |

All return `IngestStats` (`ingesters.py:87`, `as_dict` at `:96`).

## 13. Introspection

| MCP tool | Implementation | Module |
| --- | --- | --- |
| `embedder_info_tool` | `default_embedder` (`:302`) → `Embedder.name` | `embeddings.py:28` |

Embedder implementations: `HashEmbedder` (`:85`, name `hash-384`),
`OllamaEmbedder` (`:111`), `VoyageEmbedder` (`:164`), `OpenAIEmbedder` (`:213`),
`CohereEmbedder` (`:259`).

---

## Appendix — Layer/Protocol inventory

**Layer functions** (`layers.py`, 5): `build_evidence_layer`, `build_norms_layer`,
`add_element_grid`, `build_nexus_layer`, `add_authority_stub`.

**Source Protocols** (`sources.py`): `TranscriptSource`, `FrameworkSource`, with
concrete `HtmlTranscriptSource` (registers segments from `timeline_*.html`) and
`MarkdownFrameworkSource` (registers articles from `*_*.md`).

**Extension Protocols** (`extensions.py`, 3): `JurisprudenceProvider`, `VectorIndex`,
`KnowledgeGraph`.

**Public re-exports** (`violation_pack/__init__.py`, `__all__`): models, sources,
layers, authority verification, confidence, validation, packing, extension Protocols,
ingesters, and `Settings`/`load_dotenv`.
