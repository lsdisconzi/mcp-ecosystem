# Transcript Ingestion & Analysis Guide

## Quick Start

### 1. Analyze a Transcript Structure (CLI)

```bash
cd garage
python scripts/transcript_analyzer.py aeropuerto_STG_22.json
```

**Output includes:**
- Utterance count & speaker distribution
- Duration and time coverage
- Language detection (Spanish/Portuguese)
- Recommended chunk size, collection name, embedding model
- Saved detailed report: `aeropuerto_STG_22_analysis.json`

### 2. Analyze a Transcript (API Endpoint)

```bash
curl -X POST "http://localhost:8066/v2/transcripts/analyze" \
     -F "file=@aeropuerto_STG_22.json" | jq '.'
```

**Response includes:**
```json
{
  "filename": "aeropuerto_STG_22.json",
  "total_utterances": 156,
  "speakers": ["PASSENGER_1", "DGAC_OFFICIAL", "GROUND_STAFF"],
  "speaker_roles": {
    "PASSENGER_1": "passenger",
    "DGAC_OFFICIAL": "security",
    "GROUND_STAFF": "staff"
  },
  "duration_seconds": 1245.5,
  "time_range": {
    "start": 0.0,
    "end": 1245.5,
    "duration": 1245.5
  },
  "recommended_config": {
    "chunk_size": 800,
    "chunk_overlap": 150,
    "preserve_speaker_turns": true,
    "strategy": "speaker_turn_preserving",
    "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2",
    "collection_name": "transcripts_guarulhos_airport"
  }
}
```

### 3. Ingest Transcript (File Upload)

```bash
curl -X POST "http://localhost:8066/v2/transcripts/ingest-enhanced" \
     -F "file=@aeropuerto_STG_22.json" \
     -F "collection_name=transcripts_airport_incidents" \
     -F "chunk_size=800" \
     -F "chunk_overlap=150" \
     -F "preserve_speaker_turns=true" \
     -F "force_recreate=false" \
     -F "model_name=paraphrase-multilingual-MiniLM-L12-v2" \
     -F "metadata_json={\"incident_type\":\"passenger_behavior\",\"severity\":\"medium\"}" | jq '.'
```

**Response:**
```json
{
  "status": "success",
  "transcript_id": "abc123def456",
  "filename": "aeropuerto_STG_22.json",
  "collection_name": "transcripts_airport_incidents",
  "chunks_created": 45,
  "utterances_processed": 156,
  "speakers_identified": 3,
  "duration_seconds": 1245.5,
  "transcript_hash": "a1b2c3d4e5f6g7h8",
  "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2",
  "ingestion_timestamp": "2026-01-04T14:30:00.000000"
}
```

### 4. Ingest Transcript (JSON Body - No File Upload)

```bash
curl -X POST "http://localhost:8066/v2/transcripts/ingest-json" \
     -H "Content-Type: application/json" \
     -F "collection_name=transcripts_airport_incidents" \
     -F "chunk_size=800" \
     -F "chunk_overlap=150" \
     -F "preserve_speaker_turns=true" \
     -F "force_recreate=false" \
     -F "model_name=paraphrase-multilingual-MiniLM-L12-v2" \
     -d @aeropuerto_STG_22.json
```

## Key Features

### Smart Chunking Strategy

The transcript chunker preserves conversation context by:

1. **Speaker Turn Preservation**: Avoids splitting mid-conversation between different speakers
2. **Pause Detection**: Treats significant gaps (>2 seconds) as natural break points
3. **Variable Chunk Size**: Adjusts between 200-1500 characters based on content
4. **Context Overlap**: Maintains 150-character overlap between chunks for semantic continuity

### Payload Schema

Each chunk stored in Qdrant includes:
```python
{
    "text": "speaker text content...",
    "transcript_id": "unique_transcript_identifier",
    "speaker": "SPEAKER_LABEL",
    "speaker_role": "passenger|staff|security|pilot|supervisor|unknown",
    "speakers": ["list", "of", "speakers", "in", "chunk"],
    "speaker_roles": ["normalized_roles"],
    "recording_date": "2025-12-15",
    "location": "GUARULHOS_AIRPORT",
    "start_time": 0.0,
    "end_time": 125.5,
    "duration": 125.5,
    "utterance_count": 12,
    "utterance_indices": [0, 1, 2, ...],
    "utterance_range": "0-12",
    "chunk_index": 0,
    "total_chunks": 45,
    "chunk_size": 850,
    "transcript_hash": "a1b2c3d4e5f6g7h8",
    "original_filename": "aeropuerto_STG_22.json",
    "source": "transcript_enhanced",
    "ingestion_timestamp": "2026-01-04T14:30:00"
}
```

### Supported Query Patterns

With the indexed payload fields, you can perform:

**1. Speaker-based search:**
```python
results = qdrant_client.search(
    collection_name="transcripts_airport_incidents",
    query_text="passenger complaint about service",
    filter={
        "speaker_role": {"in": ["passenger"]}
    },
    limit=10
)
```

**2. Timeline reconstruction:**
```python
results = qdrant_client.search(
    collection_name="transcripts_airport_incidents",
    query_text="security incident",
    filter={
        "speaker_role": {"in": ["security", "staff"]},
        "start_time": {"gte": 100, "lte": 500}
    },
    limit=20
)
```

**3. Location-based search:**
```python
results = qdrant_client.search(
    collection_name="transcripts_airport_incidents",
    query_text="altercation disagreement",
    filter={
        "location": "GUARULHOS_AIRPORT",
        "recording_date": "2025-12-15"
    },
    limit=10
)
```

**4. Multi-speaker interaction analysis:**
```python
results = qdrant_client.search(
    collection_name="transcripts_airport_incidents",
    query_text="compromise resolution agreement",
    filter={
        "speaker_roles": {"contains": ["passenger", "staff"]},
        "utterance_count": {"gte": 5}
    },
    limit=15
)
```

## Configuration

### Embedding Models Available

- `all-MiniLM-L6-v2` (384 dims) - General purpose, fast
- `paraphrase-multilingual-MiniLM-L12-v2` (384 dims) - **Recommended for transcripts**, supports Spanish/Portuguese
- `all-mpnet-base-v2` (768 dims) - Higher quality, slower
- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` - Explicit multilingual model

### Chunking Strategies

**Speaker Turn Preserving** (>50 utterances):
- Chunk size: 800 characters
- Overlap: 150 characters
- Respects speaker boundaries
- Detects pauses >2 seconds

**Semantic Topic Based** (<50 utterances):
- Chunk size: 1500 characters
- Overlap: 200 characters
- Emphasizes semantic cohesion
- Preserves context windows

## Batch Processing

### Process Multiple Transcripts

```bash
#!/bin/bash

for transcript in data/transcripts/*.json; do
  echo "Processing: $transcript"
  
  python scripts/transcript_analyzer.py "$transcript"
  
  curl -X POST "http://localhost:8066/v2/transcripts/ingest-enhanced" \
       -F "file=@$transcript" \
       -F "collection_name=transcripts_batch_2025_12" \
       -F "chunk_size=800" \
       -F "preserve_speaker_turns=true" \
       -F "model_name=paraphrase-multilingual-MiniLM-L12-v2" \
       -F "metadata_json={\"batch\":\"2025_december\",\"source\":\"automated_ingest\"}"
  
  sleep 2  # Rate limiting
done
```

### Monitor Ingestion Progress

```bash
# Check collection stats
curl -X GET "http://localhost:8066/v1/qdrant/collections/transcripts_batch_2025_12" | jq '.'

# Verify points uploaded
curl -X GET "http://localhost:8066/v1/ingestion/collections/transcripts_batch_2025_12/info" | jq '.points_count'
```

## Troubleshooting

### Issue: 422 Unprocessable Entity with File Upload

**Cause**: File not sent as multipart/form-data

**Solution**: Use `-F` flag in curl (not `-d`):
```bash
# ✅ Correct
curl -X POST "http://localhost:8066/v2/transcripts/ingest-enhanced" \
     -F "file=@aeropuerto_STG_22.json"

# ❌ Wrong
curl -X POST "http://localhost:8066/v2/transcripts/ingest-enhanced" \
     -d @aeropuerto_STG_22.json
```

### Issue: "No utterances found in transcript"

**Cause**: JSON structure doesn't have `content` array or it's empty

**Solution**: Verify transcript structure:
```bash
python scripts/transcript_analyzer.py your_file.json
```

Expected structure:
```json
{
  "recordingdatetime": "2025-12-15",
  "location": "GUARULHOS_AIRPORT",
  "content": [
    {
      "speaker": "PASSENGER_1",
      "text": "Hello, I need help...",
      "start": 0.0,
      "end": 5.5
    },
    ...
  ]
}
```

### Issue: Slow Ingestion

**Solution**: Reduce chunk size and/or use batch processing with rate limiting:
```bash
curl -X POST "http://localhost:8066/v2/transcripts/ingest-enhanced" \
     -F "file=@large_transcript.json" \
     -F "collection_name=transcripts" \
     -F "chunk_size=500" \  # Smaller chunks = faster processing
     -F "chunk_overlap=100"
```

## API Reference

### POST `/v2/transcripts/analyze`
Analyze transcript structure without ingestion.

**Parameters:**
- `file` (UploadFile, required): Transcript JSON file

**Response:** Analysis object with speaker info, duration, and recommendations

---

### POST `/v2/transcripts/ingest-enhanced`
Ingest transcript with smart chunking.

**Parameters:**
- `file` (UploadFile, required): Transcript JSON file
- `collection_name` (str, required): Qdrant collection name
- `chunk_size` (int, default=1000): Max chunk size in characters
- `chunk_overlap` (int, default=150): Overlap between chunks
- `preserve_speaker_turns` (bool, default=True): Preserve speaker boundaries
- `force_recreate` (bool, default=False): Delete and recreate collection
- `model_name` (str, optional): Embedding model
- `metadata_json` (str, optional): Custom metadata as JSON string

**Response:** Ingestion result with transcript_id, chunks_created, speakers identified

---

### POST `/v2/transcripts/ingest-json`
Ingest transcript from JSON body (alternative to file upload).

**Parameters:** Same as `/ingest-enhanced`, except:
- `transcript` (Dict, required): Transcript data as JSON body instead of file

**Response:** Same as `/ingest-enhanced`

---

## Examples

### Spanish/Portuguese Transcript from Airport Incident

```bash
curl -X POST "http://localhost:8066/v2/transcripts/ingest-enhanced" \
     -F "file=@incidente_aeroporto_stg_22_diciembre.json" \
     -F "collection_name=incidents_latam_december" \
     -F "chunk_size=800" \
     -F "model_name=paraphrase-multilingual-MiniLM-L12-v2" \
     -F "metadata_json={
           \"incident_type\": \"passenger_altercation\",
           \"severity\": \"high\",
           \"security_involved\": true,
           \"location\": \"gate_22\",
           \"date\": \"2025-12-15\"
         }"
```

### Multi-Language Transcript with Custom Metadata

```bash
curl -X POST "http://localhost:8066/v2/transcripts/ingest-json" \
     -H "Content-Type: multipart/form-data" \
     -F "collection_name=transcripts_multilingual" \
     -F "chunk_size=900" \
     -F "preserve_speaker_turns=true" \
     -F "model_name=paraphrase-multilingual-MiniLM-L12-v2" \
     -F "force_recreate=false" \
     -F "metadata_json={
           \"language_mix\": \"spanish_portuguese\",
           \"recording_device\": \"fixed_mic_array\",
           \"audio_quality\": \"good\",
           \"transcript_source\": \"automated_asr\"
         }" \
     -F "transcript=@transcript_data.json"
```

### Search Transcript Collection

```bash
curl -X POST "http://localhost:8066/v1/qdrant/search" \
     -H "Content-Type: application/json" \
     -d '{
       "collection_name": "incidents_latam_december",
       "query_text": "pasajero insiste regla política",
       "limit": 10
     }' | jq '.results[] | {score, text: .payload.text, speaker: .payload.speaker, time: .payload.start_time}'
```

## Next Steps

1. ✅ Analyze 2-3 transcripts with the CLI analyzer
2. ✅ Test `/v2/transcripts/analyze` API endpoint
3. ✅ Ingest one transcript to test the pipeline
4. ✅ Verify chunks in Qdrant via collection info
5. ✅ Test search queries on the indexed collection
6. ✅ Batch process all transcripts for production
7. ✅ Create custom dashboards/reports using transcript data

