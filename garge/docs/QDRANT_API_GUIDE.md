# Qdrant API Documentation & Jurisprudence Search Guide

This guide documents the available Qdrant API endpoints in the project and provides strategic examples for identifying jurisprudence relevant to the **LATAM / André BD Marinho** case.

---

## 1. Collection Management

### List All Collections
Retrieve a list of all existing collections in the Qdrant instance.
- **Endpoint**: `GET /v1/qdrant/collections`
- **Example**:
```bash
curl -X GET "http://localhost:8066/v1/qdrant/collections"
```

### Create a New Collection
Initialize a new collection with specific vector dimensions and distance metrics.
- **Endpoint**: `POST /v1/qdrant/collections`
- **Payload**:
```json
{
  "name": "jurisprudence_tjsc",
  "vector_size": 768,
  "distance_metric": "cosine"
}
```
- **Note**: Creating a collection automatically initializes standard legal metadata indexes (tribunal, relator, citations, etc.).

### Ensure Legal Indexes
Manually trigger the creation of `KEYWORD` indexes for legal metadata fields on an existing collection.
- **Endpoint**: `POST /v1/qdrant/collections/{collection_name}/ensure-indexes`
- **Example**:
```bash
curl -X POST "http://localhost:8066/v1/qdrant/collections/jur_tjrs_latam_ofensa/ensure-indexes"
```

---

## 2. Data Ingestion

### Enhanced Legal Ingestion (V2)
Optimized for legal documents (.doc, .docx, .pdf). Preserves document structure (sections like "Relatório", "Voto", "Acórdão") and extracts rich metadata.
- **Endpoint**: `POST /v2/legal-ingestion/ingest-legal-file-enhanced`
- **Format**: `multipart/form-data`
- **Example**:
```bash
curl -X POST "http://localhost:8066/v2/legal-ingestion/ingest-legal-file-enhanced" \
     -F "files=@inteiro_teor.doc" \
     -F "collection_name=jur_tjrs_latam_ofensa" \
     -F "preserve_sections=true"
```

### Folder Ingestion
Scan and ingest all legal documents within a server-side directory.
- **Endpoint**: `POST /v2/legal-ingestion/ingest-legal-folder`
- **Payload**:
```json
{
  "folder_path": "/path/to/jurisprudencia",
  "collection_name": "jur_tjrs_latam_ofensa",
  "recursive": true
}
```

### Supported Document Types
The ingestion pipeline automatically detects and categorizes the following types:
- **Jurisprudence**: `acordao`, `sentenca`, `recurso_inominado`, `apelacao_civel`, `agravo`, `embargos`.
- **Regulations**: `resolucao` (ANAC), `portaria`, `decreto`, `instrucao_normativa`, `rbac`.
- **Others**: `sumula`, `transcript`, `generic`.

---

## 3. Search & Query

### Text-to-Vector Search (Recommended)
The most powerful search endpoint. It automatically converts your text query into a vector using the appropriate model (e.g., Portuguese BERT for 768-dim) and supports complex metadata filtering.
- **Endpoint**: `POST /v1/qdrant/collections/{collection_name}/query/vector`
- **Payload**:
```json
{
  "query_vector": "dano moral ofensas verbais preposto",
  "limit": 5,
  "filter": {
    "must": [
      { "key": "legislacao_citada", "match": { "value": "Art. 186" } }
    ]
  }
}
```

### Advanced Filtering
You can combine multiple conditions using `must`, `should`, and `must_not`.

#### Example: Search for "atraso de voo" but EXCLUDE "cancelamento"
```json
{
  "query_vector": "atraso de voo",
  "filter": {
    "must": [{ "key": "document_type", "match": { "value": "acordao" } }],
    "must_not": [{ "key": "text", "match": { "text": "cancelamento" } }]
  }
}
```

### Filter Sanitization & Robustness
The API includes a sanitization layer that:
1. **Handles Empty Filters**: If you pass `{}` or `null`, the API safely ignores the filter instead of crashing.
2. **Removes Junk Keys**: Automatically strips `additionalProp1` and other artifacts often injected by Swagger UI or frontend frameworks.
3. **Case-Insensitive Normalization**: Automatically converts values in legal fields (like `legislacao_citada`) to lowercase to match the indexed data.

---

## 4. Jurisprudence Search Strategies (Case: LATAM / André BD Marinho)

### Strategy A: Ofensas Verbais por Preposto
```bash
curl -X POST "http://localhost:8066/v1/qdrant/collections/jur_tjrs_latam_ofensa/query/vector" \
     -H "Content-Type: application/json" \
     -d '{
       "query_vector": "dano moral ofensas verbais funcionário xingamento humilhação pública",
       "limit": 5,
       "filter": {
         "must": [
           { "key": "legislacao_citada", "match": { "value": "Art. 932" } }
         ]
       }
     }'
```

### Strategy B: Falha de Assistência + Atraso (ANAC 400)
```bash
curl -X POST "http://localhost:8066/v1/qdrant/collections/jur_tjrs_latam_ofensa/query/vector" \
     -H "Content-Type: application/json" \
     -d '{
       "query_vector": "atraso voo falta assistência material alimentação pernoite aeroporto",
       "limit": 5,
       "filter": {
         "must": [
           { "key": "legislacao_citada", "match": { "value": "Resolução 400" } }
         ]
       }
     }'
```

---

## 5. Metadata Fields Reference

| Field | Description | Example Value |
|-------|-------------|---------------|
| `legislacao_citada` | Laws/Articles cited in the text | `art. 186`, `cdc`, `anac 400` |
| `jurisprudencia_citada` | Case law references (REsp, Apelação) | `resp 959.780`, `ai 825520` |
| `tribunal` | Court name | `tjrs`, `tjsp`, `stj` |
| `relator` | Name of the reporting judge | `des. antonio maria` |
| `document_type` | Type of legal document | `apelacao_civel`, `resolucao`, `portaria` |
| `section_type` | Specific part of the document | `votos`, `relatorio`, `ementa` |

---

## 6. Troubleshooting

### Error: `500 Internal Server Error` (Vector query failed)
- **Cause**: Usually caused by passing a filter with unexpected keys (e.g., `additionalProp1`) or an empty object that the Qdrant client cannot validate.
- **Solution**: Ensure your filter follows the Qdrant `Filter` model. The API now includes a `sanitize_qdrant_filter` to mitigate this, but check your JSON structure if the error persists.

### Error: `404 Not Found` (Collection not found)
- **Cause**: The `collection_name` in the URL or payload does not exist.
- **Solution**: Use `GET /v1/qdrant/collections` to verify the exact name.

### Error: `422 Unprocessable Entity`
- **Cause**: Missing required fields or wrong data types (e.g., `query_vector` as a string when the endpoint expects a list of floats).
- **Solution**: Use the `/query/vector` endpoint if you want to pass a **string** (text-to-vector). Use the `/query` endpoint if you are passing a **list of floats**.

---

## 7. Best Practices for Legal Search

1. **Use Specific Articles**: Filtering by `Art. 932` or `Art. 186` significantly improves precision when looking for specific legal liabilities.
2. **Leverage Portuguese BERT**: Ensure your collection is created with `vector_size: 768` to use the `neuralmind/bert-base-portuguese-cased` model, which understands Brazilian legal nuances much better than generic models.
3. **Section-Aware Search**: If you only care about the final decision, filter by `section_type: "acordao"` or `section_type: "ementa"`.
4. **Case Normalization**: The API handles normalization, but for best results, use lowercase in your filter values if you are bypassing the project's API.
