# 🎯 QUICK REFERENCE - Transcript Ingestion System

## One-Liner Tests

```bash
# Analyze CLI
python scripts/transcript_analyzer.py aeropuerto_STG_22_sample.json

# Analyze API
curl -X POST http://localhost:8066/v2/transcripts/analyze -F file=@aeropuerto_STG_22_sample.json | jq .

# Ingest
curl -X POST http://localhost:8066/v2/transcripts/ingest-enhanced \
  -F file=@aeropuerto_STG_22_sample.json \
  -F collection_name=test_transcripts_demo | jq .status

# Search
curl -X POST http://localhost:8066/v1/qdrant/search \
  -H "Content-Type: application/json" \
  -d '{"collection_name":"test_transcripts_demo","query_text":"check in","limit":3}' | jq '.results | length'
```

## File Locations

| What | Where |
|------|-------|
| **Analyzer CLI** | `scripts/transcript_analyzer.py` |
| **Processor Module** | `core/ingestion/transcript_processor.py` |
| **API Routes** | `routes/transcript_ingestion.py` |
| **User Guide** | `TRANSCRIPT_INGESTION_GUIDE.md` |
| **Tech Details** | `IMPLEMENTATION_SUMMARY.md` |
| **This Guide** | `TRANSCRIPT_SYSTEM_README.md` |
| **Sample Transcript** | `aeropuerto_STG_22_sample.json` |

## Key Classes

```python
# core/ingestion/transcript_processor.py

TranscriptExtractor()
  .extract_utterances(transcript_data)
  .extract_transcript_metadata(transcript_data)
  .normalize_speaker_role(speaker_label)

TranscriptChunker(min=200, max=1000, overlap=150)
  .chunk_utterances(utterances, metadata)

TranscriptProcessor(chunk_size=1000, preserve_turns=True)
  .process_transcript_file(file_path)
  .process_transcript_data(transcript_data)
  .convert_chunks_to_document_chunks(chunks, doc_hash)
```

## API Endpoints

```
POST /v2/transcripts/analyze
  Input:  file (multipart)
  Output: speaker_roles, duration, recommendations

POST /v2/transcripts/ingest-enhanced
  Input:  file, collection_name, chunk_size, preserve_speaker_turns, model_name
  Output: chunks_created, speakers_identified, transcript_id

POST /v2/transcripts/ingest-json
  Input:  transcript (JSON body), collection_name, ...
  Output: (same as ingest-enhanced)

POST /v1/qdrant/search
  Input:  collection_name, query_text, limit, (optional filter)
  Output: results with score, text, payload metadata
```

## Payload Schema (Searchable Fields)

```
INDEXED (fast queries):
  - speaker (keyword)
  - speaker_role (keyword)
  - speaker_roles (keyword array)
  - recording_date (datetime)
  - location (keyword)
  - start_time (float)
  - end_time (float)
  - duration (float)
  - utterance_count (integer)
  - chunk_index (integer)
  - total_chunks (integer)
  - transcript_id (keyword)
  - transcript_hash (keyword)
  - source (keyword)
  - text (full-text search)

NOT INDEXED (metadata only):
  - utterance_indices, utterance_range
  - chunk_size, original_filename
  - ingestion_timestamp, custom_metadata
```

## Smart Chunking Features

| Feature | Behavior |
|---------|----------|
| Speaker Turns | Won't split conversations between speakers |
| Pause Detection | Treats gaps >2 seconds as natural breaks |
| Size Adaptation | 200-1500 chars, configured per request |
| Context Overlap | 150 char default, configurable |
| Metadata | Preserves timestamps and speaker info |

## Default Embeddings

- Model: `paraphrase-multilingual-MiniLM-L12-v2`
- Dimension: 384
- Languages: Spanish, Portuguese, English, +50 more
- Speed: ~100 chunks/second

## Speaker Roles (Auto-Detected)

- `passenger` - Customer/traveler
- `staff` - Ground crew/service
- `security` - DGAC/PDI/Police
- `pilot` - Flight crew
- `supervisor` - Manager/lead
- `unknown` - Unclassified

## Common Queries

```python
# Find all passenger utterances
{"filter": {"speaker_role": "passenger"}}

# Find security interactions
{"filter": {"speaker_role": "security"}}

# Time range search (0-100 seconds)
{"filter": {"start_time": {"gte": 0, "lte": 100}}}

# Multiple speakers in chunk
{"filter": {"speaker_roles": {"contains": ["passenger", "staff"]}}}

# Location filter
{"filter": {"location": "GUARULHOS_AIRPORT"}}

# Combined
{"filter": {
  "location": "GUARULHOS_AIRPORT",
  "speaker_role": "security",
  "recording_date": "2025-12-15"
}}
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| 422 Unprocessable Entity | Use `-F file=@` not `-d` |
| No utterances found | Verify JSON has `content` array |
| Empty results on search | Try different query text |
| Collection not found | Check name, list with `GET /v1/qdrant/collections` |
| Slow ingestion | Reduce chunk_size (try 500) |
| Missing metadata | Pass `metadata_json` parameter |

## Batch Processing Template

```bash
#!/bin/bash

for transcript in data/transcripts/*.json; do
  echo "Processing: $transcript"
  
  # Analyze
  python scripts/transcript_analyzer.py "$transcript"
  
  # Ingest
  curl -X POST "http://localhost:8066/v2/transcripts/ingest-enhanced" \
       -F "file=@$transcript" \
       -F "collection_name=transcripts_batch_2026_01" \
       -F "chunk_size=800" \
       -F "preserve_speaker_turns=true"
  
  sleep 1  # Rate limiting
done
```

## Performance Benchmarks

| Operation | Time | Resource |
|-----------|------|----------|
| Analyze 20 utterances | <100ms | CLI |
| Ingest 20 chunks | ~2 sec | API |
| Generate embeddings | 200ms | CPU/GPU |
| Store in Qdrant | 500ms | I/O |
| Search query | <100ms | DB indexed |

## Integration Checklist

- [x] Analyzer CLI working
- [x] API endpoints live
- [x] Qdrant collection created
- [x] Embeddings generated
- [x] Search functional
- [x] Metadata indexed
- [ ] UI integration (optional)
- [ ] Batch automation (optional)
- [ ] Custom reports (optional)
- [ ] Alert system (optional)

## Key Files to Know

```
Main Pipeline:
  core/ingestion/ingestion_pipeline.py
    → .process_transcript_data()
    → .ingest_documents()

Transcript Processing:
  core/ingestion/transcript_processor.py
    → TranscriptProcessor
    → TranscriptChunker
    → TranscriptExtractor

Vector Store:
  core/ingestion/vector_store.py
    → .create_optimized_transcript_collection()
    → .ingest_documents()

API Routes:
  routes/transcript_ingestion.py
    → @router.post("/analyze")
    → @router.post("/ingest-enhanced")
    → @router.post("/ingest-json")
```

## Success Indicators

✅ CLI analyzer runs without errors  
✅ API endpoints return 200/201  
✅ Chunks appear in Qdrant collection  
✅ Search returns relevant results  
✅ Metadata fields are indexed  
✅ Speaker info preserved in chunks  
✅ Timestamps accurate  
✅ Embeddings generated (384-dim)  

---

**Quick Start:** See `TRANSCRIPT_SYSTEM_README.md`  
**Full Guide:** See `TRANSCRIPT_INGESTION_GUIDE.md`  
**Tech Details:** See `IMPLEMENTATION_SUMMARY.md`
