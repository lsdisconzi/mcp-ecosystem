import os
import logging
import tempfile
import json
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Body
from pydantic import BaseModel
from datetime import datetime

from config.settings import settings
from core.ingestion.transcript_processor import TranscriptProcessor, TranscriptExtractor
from core.ingestion.ingestion_pipeline import IngestionPipeline

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v2/transcripts",
    tags=["Transcript Ingestion"]
)


class TranscriptAnalysisResponse(BaseModel):
    filename: str
    total_utterances: int
    speakers: List[str]
    duration_seconds: float
    time_range: Optional[Dict[str, float]] = None
    recommended_config: Dict[str, Any]


@router.post("/analyze")
async def analyze_transcript_structure(
    file: UploadFile = File(...)
) -> Dict[str, Any]:
    """Analyze transcript structure and suggest optimal ingestion parameters."""
    try:
        # Read file
        contents = await file.read()
        
        # Parse JSON
        try:
            transcript_data = json.loads(contents)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON file")

        # Extract basic information
        processor = TranscriptProcessor()
        utterances = processor.extractor.extract_utterances(transcript_data)
        metadata = processor.extractor.extract_transcript_metadata(transcript_data)

        if not utterances:
            raise HTTPException(status_code=400, detail="No utterances found in transcript")

        # Extract speakers and roles
        speakers = list(set([u.speaker for u in utterances]))
        speaker_roles = {
            s: TranscriptExtractor.normalize_speaker_role(s) for s in speakers
        }

        # Calculate time range
        start_time = min(u.start_time for u in utterances)
        end_time = max(u.end_time for u in utterances)
        duration = end_time - start_time

        # Generate recommendations
        utterance_count = len(utterances)
        recommended_config = {
            "chunk_size": 800 if utterance_count > 50 else 1500,
            "chunk_overlap": 150,
            "preserve_speaker_turns": True,
            "strategy": "speaker_turn_preserving" if utterance_count > 50 else "semantic_topic_based",
            "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2",
            "payload_indexes": ["speaker", "speaker_role", "location", "recording_date"],
            "collection_name": f"transcripts_{metadata.get('location', 'default').lower().replace(' ', '_')}"
        }

        return {
            "filename": file.filename,
            "total_utterances": len(utterances),
            "speakers": speakers,
            "speaker_roles": speaker_roles,
            "duration_seconds": duration,
            "time_range": {
                "start": start_time,
                "end": end_time,
                "duration": duration
            },
            "metadata_present": metadata,
            "recommended_config": recommended_config
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error analyzing transcript: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest-enhanced")
async def ingest_transcript_enhanced(
    file: UploadFile = File(...),
    collection_name: str = Form(...),
    chunk_size: int = Form(1000),
    chunk_overlap: int = Form(150),
    preserve_speaker_turns: bool = Form(True),
    force_recreate: bool = Form(False),
    model_name: Optional[str] = Form(None),
    metadata_json: Optional[str] = Form(None)
) -> Dict[str, Any]:
    """Enhanced transcript ingestion with speaker-aware chunking."""
    
    try:
        # Read and parse transcript
        contents = await file.read()
        try:
            transcript_data = json.loads(contents)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON file")

        # Initialize pipeline
        qdrant_url = getattr(settings, 'qdrant_url', None)
        qdrant_host = getattr(settings, 'qdrant_host', 'localhost')
        qdrant_port = getattr(settings, 'qdrant_port', 6333)
        qdrant_api_key = getattr(settings, 'qdrant_api_key', None)

        pipeline = IngestionPipeline(
            qdrant_url=qdrant_url,
            qdrant_host=qdrant_host,
            qdrant_port=qdrant_port,
            qdrant_api_key=qdrant_api_key,
            embedding_model=model_name or "paraphrase-multilingual-MiniLM-L12-v2",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )

        # Process transcript
        processor = TranscriptProcessor(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            preserve_speaker_turns=preserve_speaker_turns
        )

        result = processor.process_transcript_data(transcript_data)

        # Parse optional metadata
        additional_metadata = {}
        if metadata_json:
            try:
                additional_metadata = json.loads(metadata_json)
            except json.JSONDecodeError:
                logger.warning("Failed to parse metadata_json")

        # Create transcript ID
        transcript_hash = hashlib.sha256(
            json.dumps(transcript_data, sort_keys=True).encode()
        ).hexdigest()[:16]

        # Prepare chunks for ingestion
        chunks = processor.convert_chunks_to_document_chunks(
            result["chunks"],
            transcript_hash
        )

        # Update chunk metadata with additional fields
        for chunk in chunks:
            chunk.metadata.update(additional_metadata)
            chunk.metadata["transcript_hash"] = transcript_hash
            chunk.metadata["original_filename"] = file.filename

        # Create transcript-optimized collection
        vector_size = pipeline.embedding_generator.get_embedding_dimension()
        if not pipeline.vector_store.create_optimized_transcript_collection(
            collection_name,
            vector_size,
            force_recreate
        ):
            raise HTTPException(status_code=500, detail="Failed to create collection")

        # Generate embeddings
        embeddings = pipeline.embedding_generator.generate_embeddings(chunks)

        # Ingest to Qdrant
        success = pipeline.vector_store.ingest_documents(collection_name, chunks, embeddings)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to ingest documents")

        logger.info(f"Transcript ingestion completed: {len(chunks)} chunks created")

        return {
            "status": "success",
            "transcript_id": result["transcript_id"],
            "filename": file.filename,
            "collection_name": collection_name,
            "chunks_created": len(chunks),
            "utterances_processed": result["utterance_count"],
            "speakers_identified": len(result["speakers"]),
            "duration_seconds": result["duration"],
            "transcript_hash": transcript_hash,
            "embedding_model": model_name or "paraphrase-multilingual-MiniLM-L12-v2",
            "ingestion_timestamp": datetime.now().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error ingesting transcript: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest-json")
async def ingest_transcript_json(
    transcript: Dict[str, Any] = Body(...),
    collection_name: str = Form(...),
    chunk_size: int = Form(1000),
    chunk_overlap: int = Form(150),
    preserve_speaker_turns: bool = Form(True),
    force_recreate: bool = Form(False),
    model_name: Optional[str] = Form(None),
    metadata_json: Optional[str] = Form(None)
) -> Dict[str, Any]:
    """Ingest transcript provided as JSON body (alternative to file upload)."""
    
    try:
        # Initialize pipeline
        qdrant_url = getattr(settings, 'qdrant_url', None)
        qdrant_host = getattr(settings, 'qdrant_host', 'localhost')
        qdrant_port = getattr(settings, 'qdrant_port', 6333)
        qdrant_api_key = getattr(settings, 'qdrant_api_key', None)

        pipeline = IngestionPipeline(
            qdrant_url=qdrant_url,
            qdrant_host=qdrant_host,
            qdrant_port=qdrant_port,
            qdrant_api_key=qdrant_api_key,
            embedding_model=model_name or "paraphrase-multilingual-MiniLM-L12-v2",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )

        # Process transcript
        processor = TranscriptProcessor(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            preserve_speaker_turns=preserve_speaker_turns
        )

        result = processor.process_transcript_data(transcript)

        # Parse optional metadata
        additional_metadata = {}
        if metadata_json:
            try:
                additional_metadata = json.loads(metadata_json)
            except json.JSONDecodeError:
                logger.warning("Failed to parse metadata_json")

        # Create transcript ID
        transcript_hash = hashlib.sha256(
            json.dumps(transcript, sort_keys=True).encode()
        ).hexdigest()[:16]

        # Prepare chunks for ingestion
        chunks = processor.convert_chunks_to_document_chunks(
            result["chunks"],
            transcript_hash
        )

        # Update chunk metadata
        for chunk in chunks:
            chunk.metadata.update(additional_metadata)
            chunk.metadata["transcript_hash"] = transcript_hash

        # Create transcript-optimized collection
        vector_size = pipeline.embedding_generator.get_embedding_dimension()
        if not pipeline.vector_store.create_optimized_transcript_collection(
            collection_name,
            vector_size,
            force_recreate
        ):
            raise HTTPException(status_code=500, detail="Failed to create collection")

        # Generate embeddings
        embeddings = pipeline.embedding_generator.generate_embeddings(chunks)

        # Ingest to Qdrant
        success = pipeline.vector_store.ingest_documents(collection_name, chunks, embeddings)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to ingest documents")

        logger.info(f"Transcript (JSON) ingestion completed: {len(chunks)} chunks created")

        return {
            "status": "success",
            "transcript_id": result["transcript_id"],
            "collection_name": collection_name,
            "chunks_created": len(chunks),
            "utterances_processed": result["utterance_count"],
            "speakers_identified": len(result["speakers"]),
            "duration_seconds": result["duration"],
            "transcript_hash": transcript_hash,
            "embedding_model": model_name or "paraphrase-multilingual-MiniLM-L12-v2",
            "ingestion_timestamp": datetime.now().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error ingesting transcript (JSON): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
