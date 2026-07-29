# Ingestion & Indexing Plan — juris-search

Generated: 2026-05-27

## Pipeline Architecture

```
court_samples/jurisprudence-documents/
  PDF/   (461 PDFs — TJSP, TJMS, TJCE)
  docx/  (245 DOCXs — TJRS)
       ↓
court_extractor.py  (mechanical regex extraction)
       ↓
extracted_documents/  (one JSON per document)
       ↓
juris_indexer.py  (_scan → _enrich_from_extraction → aggregate)
       ↓
master_index/master_index.json  (unified index)
       ↓
Qdrant  (law_br collection, 768-dim vectors)
```

## Current State

| Layer | Count | Status |
|---|---|---|
| Source PDFs (TJSP, TJMS, TJCE) | 461 | Done |
| Source DOCXs (TJRS) | 245 | Needs .doc conversion |
| Extracted JSONs | 466 | Done for TJSP/TJMS/TJCE + 5 TJRS |
| Master index | 1,069 docs | Needs rebuild |
| Qdrant law_br | 1,051 vectors | Needs re-ingestion |

## Master Index Rebuild

The juris_indexer.py `_scan()` method reads `json_jurisprudence/index.json` to discover
documents. That directory was cleaned up. The new pipeline uses `extracted_documents/` instead.

Two options:

### Option A: Adapt the master indexer (RECOMMENDED)
1. Point `JURIS_SEARCH_JSON_DIR` to a temporary empty directory (so old index.json isn't used)
2. Ensure `extracted_documents/` has all 466+ JSONs
3. Run the indexer's `_scan(force_ingest=True)` which will:
   - Read old master_index.json for the existing 1,049 docs
   - Scan `extracted_documents/` for structured extractions
   - Cross-reference by `numero_processo` + tribunal
   - Enrich records with partes, advogados, ementa, assuntos, etc.
   - Write updated master_index.json
4. Trigger Qdrant ingestion

### Option B: Rebuild from scratch
1. Write a new script that reads all `extracted_documents/*.json` + master_index metadata
2. Build DocRecords directly from the structured extractions
3. Write fresh master_index.json
4. Ingest to Qdrant

**Recommendation**: Option B — cleaner, no dependence on old pipeline state.

## Qdrant Ingestion Format

Each document vector goes to the `law_br` collection (768 dimensions). The embedding text
for each document should include:

```
Tribunal: {tribunal}
Processo: {numero_processo}
Relator: {relator}
Data: {data_julgamento}
Órgão: {orgao_julgador}
Comarca: {comarca}
Classe: {classe}
Assuntos: {assuntos}

EMENTA:
{ementa}

DECISÃO:
{decisao}

LEGISLAÇÃO CITADA:
{legislacao_citada}
```

This structured format produces better semantic search results than raw document text alone.

## Qdrant Collection Setup

**Collection**: `law_br`
**Vector size**: 768 (matches the embedding model)
**Indexes**: 
- `legal_document_type` (acórdão, sentença, decisão monocrática)
- `tribunal` (TJSP, TJMS, TJCE, TJRS, etc.)
- `data_julgamento` (as datetime, not keyword)
- `relator` (keyword)
- `assuntos` (keyword array)

**Metadata payload** per point:
```json
{
  "tribunal": "TJSP",
  "numero_processo": "1000137-61.2021.8.26.0411",
  "relator": "MARCOS ZILLI",
  "data_julgamento": "2026-05-19",
  "classe": "Apelação Criminal",
  "ementa": "...",
  "partes": {"apelantes": [...], "apelados": [...]},
  "outcome": ["dado_provimento"],
  "assuntos": ["DIREITO PENAL", ...],
  "legislacao_citada": ["art. 90 da Lei 8.666/1993"],
  "court_specific": {...},
  "source_file": "inteiro_teor_20559855.pdf"
}
```

## Ingestion API

The Qdrant management API at `http://localhost:8066` handles ingestion:

**Collection setup**:
```
POST /v1/qdrant/collections
{"name": "law_br", "vector_size": 768}
```

**Batch ingestion**:
```
POST /v1/qdrant/collections/structured_ingest
{
  "collection": "law_br",
  "items": [
    {
      "id": "tjsp_20559855",
      "tribunal": "TJSP",
      "text_for_embedding": "...",
      "metadata": {...}
    }
  ]
}
```

The existing `_ingest_to_collection()` method in juris_indexer.py (line ~980) handles this.
The management API's embeddings endpoint generates vectors server-side.

## Next Steps

1. Convert TJRS .doc files to .docx (run `parallel_convert.py`)
2. Run `court_extractor.py --courts TJRS` on all 245 TJRS DOCXs
3. Rebuild master_index.json from extracted_documents/
4. Reset Qdrant law_br collection (clear old vectors with ID mismatch)
5. Ingest all 700+ documents with structured metadata
6. Verify search quality with test queries

## Search Example (after ingestion)

```bash
curl -X POST http://localhost:8066/v1/qdrant/search \
  -H "Content-Type: application/json" \
  -d '{"collection":"law_br","query":"tráfico de drogas associacao criminosa","limit":5}'
```

Expected: Returns 5 most relevant acórdãos about drug trafficking + criminal association,
with full metadata (tribunal, relator, ementa, outcome) in the response payload.
