# violation-pack

A small Python library that turns prose-heavy "violation files" into layered,
verifiable, validatable artifacts — so the work I demoed on CL-005 becomes
something you can run on every other violation file with one function call
per layer.

The library implements only what was demonstrated to work on CL-005. The
seams for jurisprudence verification, vector indexing (Qdrant), and the
chronological / implication graph (Neo4j) are present as Protocols in
`violation_pack/extensions.py` — implementations live elsewhere.

## What it does today

Five enrichment layers, ten validation checks, derived confidence, signed
manifest, zipped bundle. Each layer is a pure function: takes a current
`Violation` state, returns a new one with provenance appended.

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
through V10.

## What's deferred — by design

`violation_pack/extensions.py` defines three Protocols with no
implementations:

* **`JurisprudenceProvider`** — `search(query, supports, ...) -> Authority[]`
  and `verify(authority) -> Authority`. An implementation must source rol /
  decision_date / holding from a primary source it can point to. Today: nothing
  satisfies this Protocol. Wire your own when you have the corpus.

* **`VectorIndex`** — Qdrant-shaped retrieval primitive over segments,
  articles, elements, and indexed jurisprudence. Today: not implemented. The
  natural consumer is a `JurisprudenceProvider` backed by a vector store, but
  the index itself is also useful for "find segments across the corpus that
  look like seg-55" or "find elements established elsewhere that match this
  contested one".

* **`KnowledgeGraph`** — Neo4j-shaped view for the chronological / implication
  walks. Today: not implemented. The schema is sketched in the docstring,
  including the typed edges (`HAS_SEGMENT`, `CITES`, `SUPPORTS`,
  `CROSS_REFERENCES`, `BLOCKS`) and the queries it should answer ("what other
  violations cite Art. 193 with a contested documento_oficial?", "if
  OQ-CL005-PDI-PARTE flips to resolved, which elements upgrade and which
  sibling violations' confidence values move?").

The core library never imports `qdrant_client` or `neo4j`. That keeps the
install footprint to one dependency (Pydantic) and lets the extensions ship
as separate packages on their own release cadence.

## Layout

```
violation-pack/
├── pyproject.toml
├── README.md
├── violation_pack/
│   ├── __init__.py           # public API surface — kept small and explicit
│   ├── models.py             # Pydantic models for every layer
│   ├── sources.py            # TranscriptSource & FrameworkSource Protocols + filesystem impls
│   ├── layers.py             # build_evidence_layer, build_norms_layer, ...
│   ├── confidence.py         # derive_confidence; formula lives here so it's auditable
│   ├── validation.py         # V01–V10 + run_pipeline
│   ├── pack.py               # MANIFEST, zip, canonical bundle layout
│   └── extensions.py         # Protocols only: JurisprudenceProvider, VectorIndex, KnowledgeGraph
├── examples/
│   ├── cl005_source/         # the real CL-005 source files as fixtures
│   └── refine_cl005.py       # end-to-end demo — also the template MCP tools wrap on top of
├── tests/
│   ├── conftest.py
│   ├── test_layers.py        # idempotence, fabrication rejection, etc.
│   └── test_end_to_end.py    # rebuild CL-005, assert 0 fails
```

## Quick start

```bash
pip install -e .
python examples/refine_cl005.py
pytest
```

Expected end-to-end output (and what the tests assert):

```
Bundle written to: build/CL-005
Zip:               build/CL-005_refined_pack.zip
Confidence:        0.74 (derived)
Validation:        {'total': 10, 'pass': 7, 'warn': 3, 'fail': 0}
```

The three warnings are external-action items, not internal bugs:

* **V03** — the framework cache's self-reported SHA in its metadata header
  doesn't match the file's actual content hash. Either re-hash or clarify the
  scope the header SHA was computed over.
* **V05** — cross-references can't be resolved from an isolated pack; needs
  the bundle-level violation index.
* **V07** — authorities all `verified=False`. Correct behavior; flips
  to `pass` when a `JurisprudenceProvider` is wired up.

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

1. **Wire the library to the rest of your violation files.** Move
   `examples/refine_cl005.py` into a `cases/` directory and write a sibling
   `refine_<violation_id>.py` for each one. Most of the function-call shape
   is shared; only the segment specs and article specs differ.

2. **Implement `JurisprudenceProvider`.** You said you already have plenty
   of jurisprudence — write the adapter that exposes it through the Protocol.
   Once `verify()` flips authorities to `verified=True`, V07 starts passing
   automatically and confidence values rise accordingly.

3. **Implement `VectorIndex` (Qdrant).** Index segments, articles, and
   elements. Useful first query: cross-corpus segment similarity to help
   build element grids for new violations by copying ones that already
   exist for the same article.

4. **Implement `KnowledgeGraph` (Neo4j).** Now the chronological and
   implication walks work. Cross-reference propagation, open-question
   blast radius, confidence re-derivation triggers.

5. **MCP-wrap each layer function.** The same pure functions are exposed —
   the mapping is documented in the [MCP server](#mcp-server) section. At that
   point the same enrichment pipeline is callable from agents in any project.

## MCP server

Each layer + the validation/packaging utilities are exposed as MCP tools so
any MCP-aware client (VS Code Copilot, Claude Desktop, etc.) can drive the
pipeline. Tools are thin JSON-in / JSON-out wrappers around the same pure
functions used by the tests and the batch refiner.

Install and run:

```bash
pip install -e '.[mcp]'
python -m violation_pack.mcp_server           # stdio transport
# or, after install:
violation-pack-mcp
```

Registered tools:

| Tool | Wraps |
| --- | --- |
| `init_violation` | `Violation(...)` constructor |
| `build_evidence_layer_tool` | `build_evidence_layer` (Layer 1) |
| `build_norms_layer_tool` | `build_norms_layer` (Layer 2) |
| `add_element_grid_tool` | `add_element_grid` (Layer 3) |
| `build_nexus_layer_tool` | `build_nexus_layer` (Layer 4) |
| `add_authority_stub_tool` | `add_authority_stub` (Layer 5) |
| `derive_confidence_tool` | `derive_confidence` |
| `attach_confidence_tool` | `attach_confidence` |
| `run_pipeline_tool` | `run_pipeline` (V01-V10) |
| `write_violation_json_tool` | `write_violation_json` |
| `build_manifest_tool` | `build_manifest` |
| `zip_bundle_tool` | `zip_bundle` |
| `copy_source_into_bundle_tool` | `copy_source_into_bundle` |
| `refine_batch_tool` | the batch refiner over a folder of CL-* bundles |

VS Code: the workspace ships a [`.vscode/mcp.json`](.vscode/mcp.json) so the
server is discoverable as soon as the dependency is installed.

## Extensions — Qdrant + Neo4j + Jurisprudence

The three Protocols in [`violation_pack/extensions.py`](violation_pack/extensions.py)
now ship with reference implementations. They stay optional dependencies —
the core library still installs with only Pydantic.

```bash
pip install -e '.[qdrant,neo4j]'   # or .[all] for everything
cp .env.example .env               # then fill in URLs / credentials
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

### New MCP tools (registered automatically)

```
qdrant_index_violation_tool
qdrant_search_segments_tool
qdrant_search_articles_tool
qdrant_search_authorities_tool
qdrant_search_jurisprudence_tool
qdrant_upsert_jurisprudence_tool
neo4j_upsert_violation_tool
neo4j_find_violations_citing_tool
neo4j_find_violations_with_contested_element_tool
neo4j_walk_implications_tool
jurisprudence_search_tool
jurisprudence_verify_tool
```
