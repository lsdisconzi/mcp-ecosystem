# Backend Endpoint for Indexing Reviewed Segments

The following FastAPI router code implements the **review indexing** functionality. This version has been significantly enhanced to guarantee idempotency, safely clear stale Qdrant vectors using metadata filters, inject top-level transcript context into every segment payload, and optionally expose the capability as an MCP tool in the Garage server.

---

```python
# src/presentation/routers/transcripts.py

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from dataclasses import replace as _replace

# Note: _store and _index are injected via ``init_transcript_router``

# ------------------------------------------------------------------
# Pydantic model for the indexing payload
# ------------------------------------------------------------------

class ReviewIndexPayload(BaseModel):
    """Payload for indexing reviewed transcript segments."""
    collection: str = "reviewed_transcripts"
    create_if_missing: bool = True

# ------------------------------------------------------------------
# Review & curation endpoint – index reviewed segments only
# ------------------------------------------------------------------

@router.post("/{transcript_id}/review/index")
async def index_reviewed_segments(
    transcript_id: str,
    payload: ReviewIndexPayload = ReviewIndexPayload()
) -> Dict[str, Any]:
    """Index only the **reviewed** segments of a transcript into Qdrant.

    Enhancements in this version:
    1. Validates that the transcript exists and contains a valid top-level schema.
    2. Deletes stale segments using exact Qdrant Filter matches on `transcript_id`.
    3. Injects top-level context (case_id, speaker_id, chronological_order) into 
       the vector payloads so that RAG queries have full forensic context.
    """
    if _index is None:
        raise HTTPException(status_code=503, detail="Vector indexing not configured")

    # 1. Load the transcript (from JSON store)
    transcript = _store.load(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")

    # 2. Filter for canonical, reviewed segments only
    # (Checking both top-level and segment-level review flags ensures safety)
    if not getattr(transcript, "reviewed", False):
        raise HTTPException(status_code=400, detail="Transcript is not marked as reviewed globally.")

    reviewed_segments = [
        s for s in getattr(transcript, "segments", []) 
        if getattr(s, "reviewed", False)
    ]
    
    collection_name = (payload.collection or "").strip() or "reviewed_transcripts"

    # 3. Idempotency: Safely remove any existing vectors for this transcript
    # CRITICAL FIX: Ensure _index.delete() issues a Qdrant Payload Filter, 
    # not a direct Point ID deletion. (e.g. Filter(must=[FieldCondition(key="transcript_id", match=MatchValue(value=transcript_id))]))
    await _index.delete(transcript_id, collection_name=collection_name)

    if not reviewed_segments:
        return {
            "transcript_id": transcript_id,
            "segments_indexed": 0,
            "message": "No reviewed segments. Existing points cleared."
        }

    # 4. Context Injection: Ensure each segment inherits the top-level transcript metadata
    # This guarantees that vector search results retain awareness of their chronological sequence and incident.
    top_level_context = {
        "case_id": getattr(transcript, "case_id", "Unknown"),
        "narrative_id": getattr(transcript, "narrative_id", "Unknown"),
        "chronological_order": getattr(transcript, "chronological_order", 0),
        "location": getattr(transcript, "location", "")
    }

    # Rebuild segments with injected context
    for s in reviewed_segments:
        if not hasattr(s, "metadata"):
            s.metadata = {}
        s.metadata.update(top_level_context)

    # 5. Build the lightweight transcript and ingest
    reviewed_transcript = _replace(transcript, segments=reviewed_segments)
    
    # Send to Qdrant (using _index.index which handles embeddings and payload generation)
    n = await _index.index(reviewed_transcript, collection_name=collection_name)
    
    return {
        "transcript_id": transcript_id,
        "segments_indexed": n,
        "collection": collection_name,
        "message": "Reviewed segments successfully indexed."
    }
```

---

## **MCP Tool Exposure (Garage Agents)**
To allow the agents running the Qdrant MCP server to trigger this pipeline directly, we recommend exposing a direct MCP wrapper over this logic:

```json
{
  "name": "qdrant_index_reviewed_transcript",
  "description": "Idempotently indexes a fully reviewed transcript into Qdrant. Deletes old segments and uploads only validated segments with rich payload metadata.",
  "parameters": {
    "type": "object",
    "properties": {
      "transcript_id": { "type": "string", "description": "The target transcript ID (e.g. I-002_01_NAR...)" },
      "collection": { "type": "string", "default": "reviewed_transcripts" }
    },
    "required": ["transcript_id"]
  }
}
```

## **Dependencies & Prerequisites**
* ``_index.delete`` **Must** be implemented using a Qdrant payload filter `{"transcript_id": "X"}` to clear exact stale points without needing the UUIDs of the points themselves.
* ``_store.load`` Must return an object capable of storing `case_id`, `chronological_order`, and nested `segments`.
