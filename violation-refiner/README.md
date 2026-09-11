# violation-pack

A small Python library that turns prose-heavy "violation files" into layered,
verifiable, validatable artifacts — so the work I demoed on CL-005 becomes
something you can run on every other violation file with one function call
per layer.

The core pipeline was demonstrated end-to-end on CL-005 and generalizes to
every other violation file. The seams for jurisprudence verification, vector
indexing (Qdrant), and the chronological / implication graph (Neo4j) are
defined as Protocols in `violation_pack/extensions.py` and now ship with
reference implementations in-package, behind optional extras.

## What it does today

Five enrichment layers, eleven validation checks (V01–V11), derived
confidence, signed manifest, zipped bundle. Each layer is a pure function:
takes a current `Violation` state, returns a new one with provenance appended.

| Layer | Function | What it produces |
| --- | --- | --- |
| 1. Evidence anchoring | `build_evidence_layer` | `EvidenceSegment[]` with byte-accurate verbatim, real audio offsets, and SHAs that resolve to a source transcript |
| 2. Norm anchoring | `build_norms_layer` | `CachedArticle[]` whose excerpts are substring-verified against a framework cache, plus `CandidateArticle[]` for theories pending verification (so misciting is recorded, not silently asserted) |
| 3. Element grid | `add_element_grid` | One `ArticleElementGrid` per cited article, each element with `proof_status ∈ {established, strong, contested, weak, missing, not_applicable, not_developed}` |
| 4. Nexus matrix | `build_nexus_layer` | Typed edges from segments to elements with `strength ∈ {high, medium, low}` — the table a brief consumes |
| 5. Authorities | `add_authority_stub` | Stubs only. Never auto-fills rol/sala/fecha. Built-in safeguard against the exact failure mode that produced the Art. 497 / Art. 269_ter fabrications in the original CL-005 |

Confidence is then `derive_confidence(violation)` — formula visible, history
appended each time it's re-derived. Validation is `run_pipeline(violation,
transcripts=..., frameworks=...)` and returns a `ValidationReport` with V01
through V11.

## Extension seams

`violation_pack/extensions.py` defines three Protocols. Reference
implementations ship in-package (see [Extensions](#extensions--qdrant--neo4j--jurisprudence)
below); the Protocols remain the seam so alternative backends can be dropped
in without touching the core:

* **`JurisprudenceProvider`** — `search(query, supports, ...) -> Authority[]`
  and `verify(authority) -> Authority`. `search()` returns unverified stubs;
  `verify()` only flips `verified=True` when the backing store can point to a
  `primary_source_url`.

* **`VectorIndex`** — Qdrant-shaped retrieval primitive over segments,
  articles, elements, and indexed jurisprudence. Useful for "find segments
  across the corpus that look like seg-55" or "find elements established
  elsewhere that match this contested one".

* **`KnowledgeGraph`** — Neo4j-shaped view for the chronological / implication
  walks. The docstring sketches the typed edges (`HAS_SEGMENT`, `CITES`,
  `SUPPORTS`, `CROSS_REFERENCES`, `BLOCKS`) and the queries it answers ("what
  other violations cite Art. 193 with a contested documento_oficial?", "if
  OQ-CL005-PDI-PARTE flips to resolved, which elements upgrade and which
  sibling violations' confidence values move?").

The core library never imports `qdrant_client` or `neo4j`. That keeps the
install footprint to one dependency (Pydantic), with the stores pulled in
only through the `[qdrant]` / `[neo4j]` extras.

## Layout

```
violation-pack/
├── pyproject.toml
├── README.md
├── .env.example              # every Settings.from_env() var + the MCP_* transport vars
├── start.sh / stop.sh        # MCP server lifecycle (stdio or streamable-http)
├── docs/
│   ├── mcp_mapping.md        # MCP tool → library function → file:line → UI step
│   └── ui_structural_skeleton.md  # front-end spec: steps S0–S14, every field
├── violation_pack/
│   ├── __init__.py           # public API surface + get_* factory helpers
│   ├── models.py             # Pydantic models for every layer
│   ├── sources.py            # TranscriptSource/FrameworkSource Protocols + filesystem impls
│   ├── _utils.py             # shared helpers (sha256_text)
│   ├── layers.py             # build_evidence_layer, build_norms_layer, ...
│   ├── confidence.py         # derive_confidence; configurable verification floor
│   ├── validation.py         # V01–V11 + run_pipeline
│   ├── verifier.py           # V11 enrichment-integrity checks
│   ├── authority_verification.py  # statute_in_bundle / statute_external_fetch / human_attested
│   ├── pack.py               # MANIFEST, zip, canonical bundle layout
│   ├── extensions.py         # Protocols: JurisprudenceProvider, VectorIndex, KnowledgeGraph
│   ├── qdrant_index.py       # QdrantVectorIndex              [qdrant] extra
│   ├── neo4j_graph.py        # Neo4jKnowledgeGraph            [neo4j]  extra
│   ├── jurisprudence.py      # QdrantJurisprudenceProvider
│   ├── embeddings.py         # Voyage / OpenAI / Cohere / Ollama / Hash
│   ├── ingesters.py          # bulk corpus ingestion
│   ├── enrich.py             # LLM-driven enrichment (8 stages)
│   ├── llm.py                # multi-provider LLM client       [llm]   extra
│   ├── config.py             # env-driven Settings
│   ├── refine_batch_core.py  # importable batch-refiner core
│   ├── mcp_server.py         # MCP server (39 tools)           [mcp]   extra
│   └── mcp_catalog.py        # MCP catalog CLI + snippet generator
├── examples/
│   ├── cl005_source/         # the real CL-005 source files as fixtures
│   ├── refine_cl005.py       # end-to-end demo
│   ├── refine_batch.py       # thin CLI over refine_batch_core
│   ├── wire_extensions.py    # Qdrant + Neo4j wiring demo
│   └── ...                   # ingest / validate / triage helper scripts
└── tests/
    ├── conftest.py
    ├── _fakes.py             # shared in-memory Qdrant fake (FakeQdrantClient)
    ├── test_layers.py        # idempotence, fabrication rejection, etc.
    ├── test_verifier.py      # V11 failure modes
    ├── test_extensions.py    # Qdrant/Neo4j/jurisprudence contracts (in-memory fakes)
    ├── test_ingesters.py     # bulk ingestion
    ├── test_catalog_sync.py  # fails if mcp_catalog.py drifts from the server
    └── test_end_to_end.py    # rebuild CL-005, assert 0 fails
```

## Quick start

```bash
pip install -e '.[all,test]'
cp .env.example .env            # optional; only needed for LLM/Qdrant/Neo4j work
python examples/refine_cl005.py
pytest
```

> Use the `all` extra, not just `test`. Without `qdrant-client` and `neo4j` the
> eight extension and ingester tests **skip silently** instead of failing, so a
> `.[test]`-only install reports green while exercising less. Expected: `38
> passed` in about two seconds.

Expected end-to-end output (and what the tests assert):

```
Bundle written to: build/CL-005
Zip:               build/CL-005_refined_pack.zip
Confidence:        0.74
Validation:        {'total': 11, 'pass': 7, 'warn': 4, 'fail': 0}
  ✓ V01 segment_resolution
  ✓ V02 verbatim_quote_match
  ! V03 article_text_hash
  ✓ V04 article_exists_in_framework_cache
  ! V05 cross_references_resolve
  ✓ V06 element_coverage
  ! V07 authorities_verification
  ✓ V08 contract_consistency
  ✓ V09 language_consistency
  ✓ V10 confidence_derivation
  ! V11 enrichment_integrity
```

The four warnings are external-action items, not internal bugs:

* **V03** — the framework cache's self-reported SHA in its metadata header
  doesn't match the file's actual content hash. Either re-hash or clarify the
  scope the header SHA was computed over.
* **V05** — cross-references can't be resolved from an isolated pack; needs
  the bundle-level violation index.
* **V07** — authorities all `verified=False`. Correct behavior; flips
  to `pass` once a `JurisprudenceProvider` verifies them against a primary
  source.
* **V11** — one `W_AUTH_DANGLING_SUPPORT` warning: an authority's `supports`
  entry references an article/element id that isn't present in the bundle.
  Register the cited element or drop the support link.

## Documentation

| Document | Covers |
| --- | --- |
| [`docs/ui_structural_skeleton.md`](docs/ui_structural_skeleton.md) | Front-end specification for building a UI over the pipeline: the wizard steps S0–S14, every input field, every drop target, the global shell, and the state/persistence/concurrency model. |
| [`docs/mcp_mapping.md`](docs/mcp_mapping.md) | Every MCP tool → library function → module → `file:line` → UI step, plus the stage functions, Protocol implementations, and class methods that no tool exposes. |
| [`agent_violation_refiner.md`](agent_violation_refiner.md) | Agent-facing orientation: known issues with their resolution status, development conventions, and infrastructure notes. |
| [`project_actual_report_and_proposal_improvements.md`](project_actual_report_and_proposal_improvements.md) | The full audit report; its top-of-file resolution ledger tracks every finding to FIXED or OPEN. |
| [`.env.example`](.env.example) | Every `Settings.from_env()` variable plus the `MCP_*` transport variables, grouped by provider. |

Run `violation-pack-catalog --format catalog` for the machine-readable tool list.

## Design principles

1. **No layer trusts any other layer's prose.** Layer 1 won't accept a
   "verbatim" string that isn't actually in the transcript. Layer 2 won't
   accept an article excerpt that isn't a substring of the framework cache.
   The validator re-checks every assertion against the sources at run time.

2. **Every entity has a stable ID.** That's the seam that makes the future
   Neo4j ingestion mechanical: each model → a node, each ID reference → a
   typed edge.

3. **Provenance is structured, not narrative.** Every refinement appends a
   `ProvenanceEntry` with timestamp, actor, operation, and layer. The full
   list is the chronology — replayable by humans and by the future graph
   store.

4. **The wrong way to extend is easy to spot.** Authority stubs CANNOT take
   a `court` or `rol` keyword — the constructor doesn't accept them. The
   only way to set those fields is via `JurisprudenceProvider.verify()`,
   which an implementation has to write deliberately. This is the structural
   guard against the kind of citation fabrication that produced the original
   CL-005's Art. 497 / Art. 269_ter errors.

5. **Every function is MCP-shaped from day one.** Single responsibility,
   JSON-serializable in/out, idempotent, no global state. See the
   [MCP server](#mcp-server) section below for the function → tool mapping.

## What's next (in suggested order)

1. **Run it over the rest of your violation files.** Use
   `python examples/refine_batch.py --input /path/to/CL` (add `--enrich` to
   run the LLM stages, `--zip` to emit bundles). For one-off cases, copy
   `examples/refine_cl005.py` and change the segment/article specs.

2. **Point the `JurisprudenceProvider` at your corpus.** Index your rulings
   with `JurisprudenceIngester`, then `verify()` will flip authorities to
   `verified=True` where a `primary_source_url` is present — V07 starts
   passing and confidence rises accordingly.

3. **Use `VectorIndex` for cross-corpus retrieval.** Index segments, articles,
   and elements, then find similar segments across the corpus to help build
   element grids for new violations from ones that already exist for the same
   article.

4. **Use `KnowledgeGraph` for graph walks.** Cross-reference propagation,
   open-question blast radius, and confidence re-derivation triggers.

5. **Supply the bundle-level violation index** so V05 can resolve
   cross-references across violations instead of warning.

## MCP server

Each layer + the validation/packaging utilities are exposed as MCP tools so
any MCP-aware client (VS Code Copilot, Claude Desktop, etc.) can drive the
pipeline. Tools are thin JSON-in / JSON-out wrappers around the same pure
functions used by the tests and the batch refiner.

Install and run:

```bash
pip install -e '.[mcp]'
python -m violation_pack.mcp_server           # stdio (default)
violation-pack-mcp                            # entry point, after install
MCP_TRANSPORT=streamable-http MCP_PORT=8124 python -m violation_pack.mcp_server
```

`MCP_TRANSPORT` accepts `stdio` (default), `sse`, or `streamable-http`;
`MCP_HOST`/`MCP_PORT` configure the HTTP bind (default `127.0.0.1:8124`).
When running over HTTP a `GET /health` endpoint returns
`{"status": "ok"}`. `start.sh` sources `.env`, boots the server, and waits
for `/health`; `stop.sh` shuts it down.

**39 tools** are registered. They fall into these groups:

| Group | Tools |
| --- | --- |
| Startup | `init_violation` |
| Layers 1–5 | `build_evidence_layer_tool`, `build_norms_layer_tool`, `add_element_grid_tool`, `build_nexus_layer_tool`, `add_authority_stub_tool` |
| Confidence | `derive_confidence_tool`, `attach_confidence_tool` |
| Validation | `run_pipeline_tool` (V01–V11), `verify_enrichment_tool` |
| Authority verification | `verify_statute_in_bundle_tool`, `verify_statute_external_fetch_tool`, `verify_human_attested_tool` |
| Packaging | `write_violation_json_tool`, `build_manifest_tool`, `zip_bundle_tool`, `copy_source_into_bundle_tool` |
| Batch | `refine_batch_tool` |
| LLM enrichment | `enrich_violation_tool`, `enrich_stage_tool`, `llm_provider_info_tool` |
| Qdrant | `qdrant_index_violation_tool`, `qdrant_search_segments_tool`, `qdrant_search_articles_tool`, `qdrant_search_authorities_tool`, `qdrant_search_jurisprudence_tool`, `qdrant_upsert_jurisprudence_tool`, `qdrant_reset_collections_tool` |
| Neo4j | `neo4j_upsert_violation_tool`, `neo4j_find_violations_citing_tool`, `neo4j_find_violations_with_contested_element_tool`, `neo4j_walk_implications_tool`, `neo4j_reset_database_tool` |
| Jurisprudence | `jurisprudence_search_tool`, `jurisprudence_verify_tool` |
| Bulk ingest | `jurisprudence_ingest_tool`, `transcript_ingest_tool`, `framework_ingest_tool` |
| Introspection | `embedder_info_tool` |

The machine-readable list (with tags and env keys) is generated by
`mcp_catalog.py`:

```bash
violation-pack-catalog --format catalog   # full catalog
violation-pack-catalog --format vscode    # VS Code mcp.json snippet
violation-pack-catalog --format claude    # Claude Desktop snippet
```

The catalog is declared by hand in `violation_pack/mcp_catalog.py`, but it can
no longer silently drift: `tests/test_catalog_sync.py` parses `mcp_server.py`
and `config.py` and fails if a registered tool is missing from the catalog, if
the catalog advertises a tool that no longer exists, or if it advertises an env
var no module reads.

## Extensions — Qdrant + Neo4j + Jurisprudence

The three Protocols in [`violation_pack/extensions.py`](violation_pack/extensions.py)
now ship with reference implementations. They stay optional dependencies —
the core library still installs with only Pydantic.

```bash
pip install -e '.[qdrant,neo4j]'   # or .[all] for everything
cp .env.example .env               # then set QDRANT_URL, NEO4J_URI/USER/PASSWORD,
                                   # and the LLM_* keys — see violation_pack/config.py
```

| Module | Class | Wires |
| --- | --- | --- |
| [`violation_pack/qdrant_index.py`](violation_pack/qdrant_index.py) | `QdrantVectorIndex` | `VectorIndex` |
| [`violation_pack/neo4j_graph.py`](violation_pack/neo4j_graph.py) | `Neo4jKnowledgeGraph` | `KnowledgeGraph` |
| [`violation_pack/jurisprudence.py`](violation_pack/jurisprudence.py) | `QdrantJurisprudenceProvider` | `JurisprudenceProvider` |

The factory helpers in [`violation_pack/__init__.py`](violation_pack/__init__.py)
read `.env` automatically:

```python
from violation_pack import get_vector_index, get_knowledge_graph, get_jurisprudence_provider

idx = get_vector_index()
kg  = get_knowledge_graph()
jp  = get_jurisprudence_provider()
```

End-to-end example (indexes CL-005 into both stores):

```bash
python examples/wire_extensions.py
```

Embeddings: by default, [`violation_pack/embeddings.py`](violation_pack/embeddings.py)
uses Ollama (`/api/embeddings`) when `OLLAMA_HOST` is reachable; otherwise it
falls back to a deterministic in-process `HashEmbedder` so the plumbing is
always testable.

The `JurisprudenceProvider` is contract-faithful: `search()` returns
unverified `Authority` stubs only; `verify()` refuses to flip `verified=True`
unless the backing Qdrant record carries a `primary_source_url`. The
fabrication safeguard from the original design holds.

### Extension MCP tools

The Qdrant / Neo4j / jurisprudence tools are registered alongside the core
tools when the corresponding optional dependency is installed — see the
grouped list in the [MCP server](#mcp-server) section for the full set.
