from fastapi import APIRouter, Depends, HTTPException, status, Body, UploadFile, File, Form, Request
from fastapi.responses import JSONResponse, FileResponse
from qdrant_client import QdrantClient, models
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Union
import os
import io
import uuid
import re
import json
import ollama
import logging
import asyncio
from datetime import datetime
from pathlib import Path
import hashlib
from pydantic import Field




# Add these imports to your base router
import fitz  # PyMuPDF
import email
from email import policy
from email.parser import BytesParser
import re  # Add this import for regex patterns

# --- New Imports for Ingestion ---
from sentence_transformers import SentenceTransformer
import pypdf

from services.qdrant_service import get_qdrant_client, get_connected_client, health_check
from utils.document_ingestor import process_file_for_ingestion


logger = logging.getLogger(__name__)

# Project base path configuration
BASE_PATH = Path(__file__).parent.parent.resolve()  # /Users/leandrodisconzi/Documents/sa_server/garage
WORKSPACE_PATH = BASE_PATH.parent / "garage"  # Adjust based on your structure
DATA_PATH = BASE_PATH / "data"
ASSISTANTS_PATH = DATA_PATH / "assistants"
PROMPTS_PATH = DATA_PATH / "prompts"

# Ensure directories exist
DATA_PATH.mkdir(exist_ok=True)
ASSISTANTS_PATH.mkdir(exist_ok=True)
PROMPTS_PATH.mkdir(exist_ok=True)

# --- Add Testing Samples ---
TEST_SAMPLES = {
    "create_collection": {
        "name": "test_collection",
        "vector_size": 768,
        "distance_metric": "cosine"
    },
    "upsert_points": {
        "collection_name": "test_collection",
        "points": [
            {
                "id": "point_1",
                "vector": [0.1] * 768,
                "payload": {
                    "text": "Sample document text",
                    "doc_type": "test",
                    "source": "test_data"
                }
            }
        ]
    },
    "transcript_ingest": {
        "collection_name": "transcripts",
        "data_type": "transcript",
        "items": [
            {
                "id": "STG_7_seg8_001",
                "speaker": "Latam Mgr",
                "text": "Seria por falta de segurancia...",
                "timestamp": "00:09-00:12",
                "transcript_id": "STG_7",
                "segment_id": "8",
                "location": "SCL Airport Gate 7"
            }
        ]
    },
    "violation_ingest": {
        "collection_name": "violations",
        "data_type": "violation",
        "items": [
            {
                "id": "STG_7_seg8_v1",
                "transcript_ref": "aeropuerto_STG_7_segment_8",
                "speaker": "Latam Mgr",
                "violation_type": "False security allegation without evidence",
                "framework": ["Chilean Aviation Law", "Brazilian Aviation Law"],
                "reasoning": "Manager suggests filing security report without substantiated grounds...",
                "linked_law_hint": ["Ley 19.983", "CBA Art. 259"],
                "timestamp": "00:09-00:12"
            }
        ]
    },
    "law_ingest": {
        "collection_name": "laws",
        "data_type": "law",
        "items": [
            {
                "id": "law_001",
                "title": "Chilean Aviation Law Article 15",
                "text": "All aviation security reports must be substantiated with evidence...",
                "jurisdiction": "Chile",
                "framework": "Chilean Aviation Law",
                "article": "15"
            }
        ]
    },
    "search": {
        "collection_name": "test_collection",
        "query_text": "aviation security regulations",
        "limit": 5
    }
}

def sanitize_qdrant_filter(qdrant_filter: Any) -> Any:
    """Sanitizes a filter dictionary to remove junk keys and handle empty filters."""
    if not qdrant_filter or not isinstance(qdrant_filter, dict):
        return None
    
    # Remove common Swagger UI junk keys
    for junk in ["additionalProp1", "additionalProp2", "additionalProp3"]:
        qdrant_filter.pop(junk, None)
        
    # If empty or has no valid Qdrant filter keys, return None
    # Note: Qdrant filters usually have at least one of these keys
    valid_keys = {"must", "should", "must_not", "any", "nested", "min_score"}
    if not qdrant_filter or not any(k in qdrant_filter for k in valid_keys):
        return None
        
    return qdrant_filter

router = APIRouter(
    prefix="/v1/qdrant",
    tags=["Qdrant"]
) 

# --- Load Embedding Models ---
# We load multiple models to support different embedding dimensions.
try:
    embedding_models = {
        384: SentenceTransformer('all-MiniLM-L6-v2'),
        768: SentenceTransformer('all-mpnet-base-v2'), # A model that produces 768-dim vectors
        'neuralmind/bert-base-portuguese-cased': SentenceTransformer('neuralmind/bert-base-portuguese-cased')
    }
    print("✅ Embedding models loaded successfully: all-MiniLM-L6-v2 (384), all-mpnet-base-v2 (768), Portuguese BERT.")
    # Keep a default for older functions that don't specify a dimension.
    embedding_model = embedding_models[768] 
except Exception as e:
    print(f"⚠️ Failed to load one or more embedding models: {e}")
    # Fallback if Portuguese model fails
    try:
        embedding_models = {
            384: SentenceTransformer('all-MiniLM-L6-v2'),
            768: SentenceTransformer('all-mpnet-base-v2')
        }
        embedding_model = embedding_models[768]
    except:
        embedding_models = {}
        embedding_model = None


# --- Add Docstrings to Pydantic Models ---
class CreateCollectionRequest(BaseModel):
    """Request model for creating a new Qdrant collection."""
    name: str = Field(..., description="Name of the collection to create")
    vector_size: int = Field(..., description="Dimension of the vectors (384 or 768)")
    distance_metric: str = Field("cosine", description="Distance metric: cosine, euclid, or dot")

class Point(BaseModel):
    """Represents a single point with vector and payload."""
    id: Union[int, str] = Field(..., description="Unique identifier for the point")
    vector: List[float] = Field(..., description="Vector embedding")
    payload: Optional[Dict[str, Any]] = Field(None, description="Metadata payload")

class UpsertPointsRequest(BaseModel):
    """Request model for upserting points into a collection."""
    collection_name: str = Field(..., description="Target collection name")
    points: List[Point] = Field(..., description="List of points to upsert")

class DeletePointsRequest(BaseModel):
    """Request model for deleting points from a collection."""
    collection_name: str = Field(..., description="Target collection name")
    point_ids: List[Union[int, str]] = Field(..., description="List of point IDs to delete")

class QueryRequest(BaseModel):
    """Request model for vector similarity search."""
    collection_name: str = Field(..., description="Target collection name")
    query_vector: List[float] = Field(..., description="Query vector for search")
    limit: int = Field(10, description="Maximum number of results to return")

class StructuredIngestRequest(BaseModel):
    """Request model for structured data ingestion."""
    collection_name: str = Field(..., description="Target collection name")
    data_type: str = Field(..., description="Type of data: transcript, violation, law, or generic")
    items: List[dict] = Field(..., description="List of data items to ingest")

class ScrollRequest(BaseModel):
    """Request model for scrolling through collection points."""
    limit: int = Field(10, description="Number of points to return per page")
    offset: Optional[Union[int, str]] = Field(None, description="Pagination offset")
    with_payload: bool = Field(True, description="Include payload in response")
    with_vectors: bool = Field(False, description="Include vectors in response")

class EmbedCaseDirectoryRequest(BaseModel):
    """Request model for embedding entire case directories."""
    case_directory: str = Field(..., description="Path to case directory")
    collection_name: str = Field(..., description="Target collection name")
    embedding_dim: int = Field(384, description="Embedding dimension: 384 or 768")

class EmbedProjectCodeRequest(BaseModel):
    """Request model for embedding source code into a dev-code collection."""
    project_root: str = Field(default="/home/garge", description="Root directory of the project to index")
    collection_name: str = Field(default="olivia-dev-code", description="Target Qdrant collection name")
    force_recreate: bool = Field(default=True, description="Recreate the collection before ingestion")
    embedding_dim: int = Field(default=384, description="Embedding dimension: 384 or 768")

class SearchRequest(BaseModel):
    """Request model for text-based search.

    `query_text` accepts either a single string or a list of strings (for multi-query search).
    It may also accept a JSON object from which `text` or `query` will be extracted.
    """
    collection_name: str = Field(..., description="Target collection name")
    query_text: Union[str, List[str], Dict[str, Any]] = Field(..., description="Text query to search for (string or list of strings)")
    limit: int = Field(10, description="Maximum number of results")
    filters: Optional[Dict[str, Any]] = Field(None, description="Optional filters to apply")
    filter: Optional[Dict[str, Any]] = Field(None, description="Alias for filters")
    min_score: float = Field(0.0, description="Minimum similarity score threshold")

class SearchResponse(BaseModel):
    """Response model for search results."""
    status: str = Field(..., description="Status of the search operation")
    count: int = Field(..., description="Number of results returned")
    results: List[Dict[str, Any]] = Field(..., description="List of search results")

class QueryVectorRequest(BaseModel):
    """Request model for vector-based query, supporting both raw vectors and text."""
    query_vector: Union[str, List[Any]] = Field(..., description="Vector (list of floats) or text query to search for")
    limit: int = Field(10, description="Maximum number of results")
    filter: Optional[Dict[str, Any]] = Field(None, description="Optional Qdrant filters")
    score_threshold: Optional[float] = Field(None, description="Minimum similarity score threshold")
    with_payload: Union[bool, List[str]] = Field(True, description="Whether to include payload in results")

# --- Testing Samples ---

# Sample data for testing various endpoints
TEST_SAMPLES = {
    "create_collection": {
        "name": "test_collection",
        "vector_size": 384,
        "distance_metric": "cosine"
    },
    "upsert_points": {
        "collection_name": "test_collection",
        "points": [
            {
                "id": "point_1",
                "vector": [0.1] * 384,  # 384-dimensional vector
                "payload": {
                    "text": "Sample document text",
                    "doc_type": "test",
                    "source": "test_data"
                }
            }
        ]
    },
    "transcript_ingest": {
        "collection_name": "transcripts",
        "data_type": "transcript",
        "items": [
            {
                "id": "STG_7_seg8_001",
                "speaker": "Latam Mgr",
                "text": "Seria por falta de segurancia...",
                "timestamp": "00:09-00:12",
                "transcript_id": "STG_7",
                "segment_id": "8",
                "location": "SCL Airport Gate 7"
            }
        ]
    },
    "violation_ingest": {
        "collection_name": "violations",
        "data_type": "violation",
        "items": [
            {
                "id": "STG_7_seg8_v1",
                "transcript_ref": "aeropuerto_STG_7_segment_8",
                "speaker": "Latam Mgr",
                "violation_type": "False security allegation without evidence",
                "framework": ["Chilean Aviation Law", "Brazilian Aviation Law"],
                "reasoning": "Manager suggests filing security report without substantiated grounds...",
                "linked_law_hint": ["Ley 19.983", "CBA Art. 259"],
                "timestamp": "00:09-00:12"
            }
        ]
    },
    "law_ingest": {
        "collection_name": "laws",
        "data_type": "law",
        "items": [
            {
                "id": "law_001",
                "title": "Chilean Aviation Law Article 15",
                "text": "All aviation security reports must be substantiated with evidence...",
                "jurisdiction": "Chile",
                "framework": "Chilean Aviation Law",
                "article": "15"
            }
        ]
    },
    "search": {
        "collection_name": "test_collection",
        "query_text": "aviation security regulations",
        "limit": 5
    }
}

# --- Helper Functions for Ingestion ---

def ingest_document(
    file_path: str,
    text_content: str,
    doc_type: str,
    doc_number: Optional[str] = None,
    date: Optional[str] = None,
    chunk_size: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
    embedding_dim: int = 384
) -> List[Dict[str, Any]]:
    """
    Ingests a document into a structured format for vector search.
    
    Args:
        file_path: Path to the source file
        text_content: Extracted text content
        doc_type: Type of document (transcript, violation, law, etc.)
        doc_number: Optional document identifier
        date: Optional document date
        chunk_size: Size for text chunking (None for full document)
        metadata: Additional metadata
        embedding_dim: Vector dimension (384 or 768)
    
    Returns:
        List of structured items ready for vectorization
    
    Example:
        >>> items = ingest_document(
        ...     "documents/report.pdf",
        ...     "This is the document content...",
        ...     "report",
        ...     chunk_size=500
        ... )
    """
    ingest_items = []
    
    # Default metadata
    base_metadata = {
        "file_path": file_path,
        "doc_type": doc_type,
        "doc_number": doc_number,
        "date": date,
        "embedding_dim": embedding_dim,
        "ingested_at": datetime.utcnow().isoformat(),
    }
    if metadata:
        base_metadata.update(metadata)
    
    # Full-document ingestion
    if not chunk_size:
        ingest_items.append({
            "id": str(uuid.uuid4()),
            "text": text_content,
            "metadata": base_metadata,
            "chunk_index": 0,
            "full_document": True
        })
    else:
        # Chunked ingestion
        for idx in range(0, len(text_content), chunk_size):
            ingest_items.append({
                "id": str(uuid.uuid4()),
                "text": text_content[idx:idx + chunk_size],
                "metadata": base_metadata,
                "chunk_index": idx // chunk_size,
                "full_document": False
            })
    
    return ingest_items

def extract_text_from_pdf(file_stream: io.BytesIO) -> str:
    """Extracts text from a PDF file stream."""
    try:
        reader = pypdf.PdfReader(file_stream)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {e}")
        raise

def chunk_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[str]:
    """Splits text into overlapping chunks."""
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - chunk_overlap
    return chunks

# --- Core Ingestion Functions ---

async def upsert_transcript_points(client, collection_name: str, transcripts: List[dict], embedding_model):
    """
    Ingests transcript segments into Qdrant.
    
    Payload Structure:
        - id: Unique segment identifier
        - speaker: Speaker name/role
        - text: Transcript text content
        - timestamp: Time segment (e.g., "00:09-00:12")
        - transcript_id: Parent transcript identifier
        - segment_id: Segment number/identifier
        - location: Physical location
    
    Example Payload:
        {
            "id": "STG_7_seg8_001",
            "speaker": "Latam Mgr", 
            "text": "Seria por falta de segurancia...",
            "timestamp": "00:09-00:12",
            "transcript_id": "STG_7",
            "segment_id": "8",
            "location": "SCL Airport Gate 7"
        }
    """
    try:
        vectors = embedding_model.encode([t.get("text", t.get("transcript", "")) for t in transcripts]).tolist()

        points = []
        for i, t in enumerate(transcripts):
            point_id = str(t.get("id", uuid.uuid4()))
            points.append(models.PointStruct(
                id=point_id,
                vector=vectors[i],
                payload=t
            ))

        client.upsert(collection_name=collection_name, points=points, wait=True)
        return {"status": "ok", "count": len(points)}
    except Exception as e:
        logger.error(f"Error upserting transcript points: {e}")
        raise

async def upsert_violation_points(client, collection_name: str, violations: List[dict], embedding_model):
    """
    Ingests violation analyses into Qdrant.
    
    Payload Structure:
        - id: Unique violation identifier
        - transcript_ref: Reference to source transcript
        - speaker: Speaker who committed violation
        - violation_type: Type of violation
        - framework: Applicable legal frameworks
        - reasoning: Detailed violation analysis
        - linked_law_hint: Relevant laws/regulations
        - timestamp: Time segment of violation
    
    Example Payload:
        {
            "id": "STG_7_seg8_v1",
            "transcript_ref": "aeropuerto_STG_7_segment_8",
            "speaker": "Latam Mgr",
            "violation_type": "False security allegation without evidence",
            "framework": ["Chilean Aviation Law", "Brazilian Aviation Law"],
            "reasoning": "Manager suggests filing security report without substantiated grounds...",
            "linked_law_hint": ["Ley 19.983", "CBA Art. 259"],
            "timestamp": "00:09-00:12"
        }
    """
    try:
        texts = []
        for v in violations:
            if "violation_type" in v and "reasoning" in v:
                texts.append(f"{v['violation_type']} {v['reasoning']}")
            elif "description" in v:
                texts.append(v["description"])
            else:
                texts.append(json.dumps(v))
                
        vectors = embedding_model.encode(texts).tolist()

        points = []
        for i, v in enumerate(violations):
            point_id = str(v.get("id", uuid.uuid4()))
            points.append(models.PointStruct(
                id=point_id,
                vector=vectors[i],
                payload=v
            ))

        client.upsert(collection_name=collection_name, points=points, wait=True)
        return {"status": "ok", "count": len(points)}
    except Exception as e:
        logger.error(f"Error upserting violation points: {e}")
        raise

async def upsert_law_points(client, collection_name, laws, embedding_model):
    """
    Upsert law points into Qdrant collection with flexible schema support.
    
    Payload Structure:
        - id: Unique law identifier
        - title: Law/regulation title
        - text: Full text content
        - jurisdiction: Applicable jurisdiction
        - framework: Legal framework
        - article/section: Specific article/section reference
    
    Example Payload:
        {
            "id": "law_001",
            "title": "Chilean Aviation Law Article 15",
            "text": "All aviation security reports must be substantiated with evidence...",
            "jurisdiction": "Chile", 
            "framework": "Chilean Aviation Law",
            "article": "15"
        }
    """
    try:
        # More flexible text extraction
        texts = []
        for l in laws:
            if 'text' in l:
                # Build text with title if available
                if 'title' in l:
                    texts.append(f"{l['title']} {l['text']}")
                else:
                    texts.append(l['text'])
            # Fallback if no text field is found
            elif 'content' in l:
                texts.append(l['content'])
            else:
                # Last resort - stringify the whole object
                texts.append(json.dumps(l))
        
        # Generate embeddings directly using the model (no asyncio needed)
        embeddings = embedding_model.encode(texts).tolist()
        
        # Prepare points for Qdrant
        points = []
        for i, (law, embedding) in enumerate(zip(laws, embeddings)):
            # Generate point ID
            if 'id' in law:
                point_id = str(law['id'])
            else:
                point_id = str(uuid.uuid4())
            
            # Determine document type if not provided
            if 'doc_type' not in law:
                doc_type = determine_doc_type(
                    metadata=law.get('metadata', {}),
                    filename=law.get('title', ''),
                    content=texts[i][:1000]
                )
            else:
                doc_type = law['doc_type']
            
            # Create payload with all original data
            payload = {
                "original_data": law,
                "text": texts[i],
                "doc_type": doc_type,  # Add at root level for easier filtering
                "metadata": {
                    "data_type": "law",
                    "doc_type": doc_type,
                    "ingestion_time": datetime.now().isoformat()
                }
            }
            
            # Add individual fields from the law to the payload for easier filtering
            for key, value in law.items():
                if key not in ["id"] and not key.startswith("_"):
                    payload[key] = value
            
            points.append({
                "id": point_id,
                "vector": embedding,
                "payload": payload
            })
        
        # Batch upsert to Qdrant
        client.upsert(
            collection_name=collection_name,
            points=points
        )
        
        return {
            "status": "success",
            "count": len(points),
            "collection": collection_name
        }
    except Exception as e:
        logging.error(f"Error in upsert_law_points: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to upsert law points: {str(e)}")

async def upsert_generic_points(client, collection_name: str, items: List[dict], data_type: str, embedding_model):
    """
    Ingests generic JSON objects into Qdrant.
    
    The entire JSON object is stored in the payload, and its string representation is embedded.
    
    Payload Structure:
        - data_type: Type of data (provided parameter)
        - All original item fields
        - text: String representation for embedding
    
    Example Payload:
        {
            "data_type": "custom_data",
            "id": "item_001",
            "name": "Sample Item",
            "description": "This is a sample item",
            "text": "{\"id\": \"item_001\", \"name\": \"Sample Item\", \"description\": \"This is a sample item\"}"
        }
    """
    try:
        # Embed the string representation of each JSON object
        texts_to_embed = [json.dumps(item) for item in items]
        vectors = embedding_model.encode(texts_to_embed).tolist()

        points = []
        for i, item in enumerate(items):
            point_id = str(item.get("id", uuid.uuid4()))
            
            # Create a payload that includes the original data and the data type
            payload = {
                "data_type": data_type,
                **item  # Unpack the original item's fields into the payload
            }
            
            points.append(models.PointStruct(
                id=point_id,
                vector=vectors[i],
                payload=payload
            ))

        client.upsert(collection_name=collection_name, points=points, wait=True)
        return {"status": "ok", "count": len(points)}
    except Exception as e:
        logger.error(f"Error upserting generic points: {e}")
        raise

# --- API Endpoints ---

@router.post("/connect", summary="Check Qdrant Connection")
async def connect_to_qdrant(client: QdrantClient = Depends(get_qdrant_client)):
    """Verifies the connection to the Qdrant instance."""
    return {"status": "connected", "url": os.getenv("QDRANT_URL")}

@router.get("/collections", summary="List All Collections")
async def list_collections(client: QdrantClient = Depends(get_qdrant_client)):
    """Retrieves a list of all collections in the Qdrant database."""
    try:
        collections_response = client.get_collections()
        collections_list = []
        for collection in collections_response.collections:
            collection_info = client.get_collection(collection_name=collection.name)
            collections_list.append({
                "name": collection.name,
                "vectors_count": collection_info.points_count,  # Changed from vectors_count to points_count
                "vector_size": collection_info.config.params.vectors.size,
            })
        return {"collections": collections_list}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/collections/{collection_name}/summary", summary="Get Collection Statistics")
async def get_collection_summary(
    collection_name: str,
    client: QdrantClient = Depends(get_connected_client)
):
    """
    Calculates and returns detailed statistics for a given collection.
    
    Returns:
        - points_count: Total number of vectors
        - frameworks_count: Number of distinct frameworks
        - doc_type_counts: Distribution of document types
    
    Example Response:
        {
            "points_count": 1500,
            "frameworks_count": 5,
            "doc_type_counts": {
                "transcripts": 800,
                "violations": 400,
                "laws": 300
            }
        }
    """
    try:
        collection_info = client.get_collection(collection_name=collection_name)
        points_count = collection_info.points_count  # Changed from vectors_count to points_count
        # Use scroll to efficiently gather payload data without vectors
        next_offset = None
        frameworks = set()
        doc_types = {}
        
        while True:
            scroll_result, next_offset = client.scroll(
                collection_name=collection_name,
                limit=250,
                offset=next_offset,
                with_payload=True,
                with_vectors=False
            )
            
            for point in scroll_result:
                payload = point.payload
                if not payload:
                    continue
                
                # Count frameworks
                fw = payload.get("framework")
                if isinstance(fw, str):
                    frameworks.add(fw)
                elif isinstance(fw, list):
                    frameworks.update(fw)

                # Count document types from file paths
                file_path = payload.get("file_path", "")
                if "results/" in file_path:
                    doc_types["results"] = doc_types.get("results", 0) + 1
                elif "transcripts/" in file_path:
                    doc_types["transcripts"] = doc_types.get("transcripts", 0) + 1
                elif "frameworks/" in file_path:
                    doc_types["frameworks"] = doc_types.get("frameworks", 0) + 1
                else:
                    # Fallback for other types
                    suffix = Path(file_path).suffix.replace('.', '') if file_path else "unknown"
                    if suffix:
                        doc_types[suffix] = doc_types.get(suffix, 0) + 1

            if next_offset is None:
                break

        return {
            "points_count": points_count,
            "frameworks_count": len(frameworks),
            "doc_type_counts": doc_types
        }

    except Exception as e:
        logger.error(f"Error getting summary for collection '{collection_name}': {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/collections/structured_ingest", summary="Ingest structured data")
async def structured_ingest(
    request: StructuredIngestRequest,
    client: QdrantClient = Depends(get_connected_client)
):
    """
    Ingest structured data with automatic embedding and type-specific processing.
    
    Supported data_types:
        - transcript: Speaker segments with timestamps
        - violation: Legal violation analyses  
        - law: Regulations and legal frameworks
        - generic: Any JSON data with string representation
    
    Example Request:
        {
            "collection_name": "violations",
            "data_type": "violation",
            "items": [...violation objects...]
        }
    """
    if not embedding_model:
        raise HTTPException(status_code=500, detail="Embedding model not available")

    if request.data_type == "transcript":
        return await upsert_transcript_points(client, request.collection_name, request.items, embedding_model)
    elif request.data_type == "violation":
        return await upsert_violation_points(client, request.collection_name, request.items, embedding_model)
    elif request.data_type == "law":
        return await upsert_law_points(client, request.collection_name, request.items, embedding_model)
    else:
        # Fallback to generic ingestion
        return await upsert_generic_points(client, request.collection_name, request.items, request.data_type, embedding_model)

@router.post("/collections", summary="Create a New Collection")
async def create_collection(
    request: CreateCollectionRequest,
    client: QdrantClient = Depends(get_connected_client)
):
    """Creates a new vector collection."""
    try:
        distance_map = {
            "cosine": models.Distance.COSINE,
            "euclid": models.Distance.EUCLID,
            "dot": models.Distance.DOT
        }
        client.recreate_collection(
            collection_name=request.name,
            vectors_config=models.VectorParams(
                size=request.vector_size,
                distance=distance_map.get(request.distance_metric.lower(), models.Distance.COSINE)
            ),
        )
        
        # Create default legal indexes for better filtering
        legal_fields = [
            "legislacao_citada", "jurisprudencia_citada", "tribunal", 
            "relator", "processo_numero", "cnj_number", "document_type",
            "section_type", "has_acordao"
        ]
        for field in legal_fields:
            try:
                client.create_payload_index(
                    collection_name=request.name,
                    field_name=field,
                    field_schema=models.PayloadSchemaType.KEYWORD
                )
            except Exception as e:
                logger.warning(f"Could not create index for {field}: {e}")

        return {"status": "success", "message": f"Collection '{request.name}' created with legal indexes."}
    except Exception as e:
        if "already exists" in str(e):
            raise HTTPException(status_code=409, detail=f"Collection '{request.name}' already exists.")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/collections/{collection_name}/ensure-indexes", summary="Ensure Legal Indexes")
async def ensure_legal_indexes(
    collection_name: str,
    client: QdrantClient = Depends(get_connected_client)
):
    """Ensures all required legal metadata indexes exist for a collection."""
    legal_fields = [
        "legislacao_citada", "jurisprudencia_citada", "tribunal", 
        "relator", "processo_numero", "cnj_number", "document_type",
        "section_type", "has_acordao"
    ]
    created = []
    errors = []
    
    for field in legal_fields:
        try:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD
            )
            created.append(field)
        except Exception as e:
            if "already exists" in str(e).lower():
                continue
            errors.append(f"{field}: {str(e)}")
            
    return {
        "status": "completed",
        "collection": collection_name,
        "indexes_ensured": created,
        "errors": errors
    }

@router.delete("/collections/{collection_name}", summary="Delete a Collection")
async def delete_collection(
    collection_name: str,
    client: QdrantClient = Depends(get_connected_client)
):
    """Deletes a specified vector collection."""
    try:
        result = client.delete_collection(collection_name=collection_name)
        if not result:
             raise HTTPException(status_code=500, detail=f"Failed to delete collection '{collection_name}'.")
        return {"status": "success", "message": f"Collection '{collection_name}' deleted."}
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' not found or could not be deleted: {e}")

# --- UPDATED ENDPOINT FOR BATCH FILE INGESTION ---
# ...existing code...

@router.post("/collections/{collection_name}/ingest", summary="Ingest Files into a Collection")
async def ingest_files(
    collection_name: str, 
    files: List[UploadFile] = File(...),
    use_auto_chunking: bool = Form(True),
    chunk_size: Optional[int] = Form(None),
    doc_type: Optional[str] = Form(None)
):
    """
    Enhanced endpoint to ingest files with automatic document type detection
    and smart chunking strategy. Embedding model is selected based on the
    collection's vector dimension.
    """
    client = get_connected_client()
    results = []
    errors = []

    # Get the collection's vector size
    try:
        collection_info = client.get_collection(collection_name=collection_name)
        vector_size = collection_info.config.params.vectors.size
    except Exception as e:
        logger.error(f"Failed to get collection info for '{collection_name}': {e}")
        raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' not found: {str(e)}")

    # Select the correct embedding model
    model = embedding_models.get(vector_size)
    if not model:
        logger.error(f"No embedding model for dimension {vector_size}")
        raise HTTPException(status_code=400, detail=f"Embedding dimension {vector_size} not supported.")

    # Process each file
    for file in files:
        try:
            content_bytes = await file.read()

            # Handle JSON files separately
            if file.filename.lower().endswith('.json'):
                json_data = json.loads(content_bytes.decode('utf-8'))
                total_points = 0

                if isinstance(json_data, list):
                    detected_type = doc_type or detect_json_type(json_data)
                    if detected_type == "transcript":
                        result = await upsert_transcript_points(client, collection_name, json_data, model)
                        total_points = result["count"]
                    elif detected_type == "violation":
                        result = await upsert_violation_points(client, collection_name, json_data, model)
                        total_points = result["count"]
                    elif detected_type == "law":
                        result = await upsert_law_points(client, collection_name, json_data, model)
                        total_points = result["count"]
                    else:
                        result = await upsert_generic_points(client, collection_name, json_data, detected_type, model)
                        total_points = result["count"]

                elif isinstance(json_data, dict):
                    if "chunks" in json_data and isinstance(json_data["chunks"], list):
                        items_to_process = []
                        if "full_text" in json_data:
                            items_to_process.append({
                                "id": f"{json_data.get('id', str(uuid.uuid4()))}_full",
                                "text": json_data["full_text"],
                                "metadata": json_data.get("metadata", {}),
                                "full_document": True
                            })
                        for i, chunk in enumerate(json_data["chunks"]):
                            items_to_process.append({
                                "id": f"{json_data.get('id', str(uuid.uuid4()))}_chunk_{i}",
                                "text": chunk["text"],
                                "metadata": {
                                    **json_data.get("metadata", {}),
                                    "page": chunk.get("page", i+1),
                                    "chunk_index": i,
                                    "embedding_dim": vector_size
                                },
                                "full_document": False
                            })
                        total_points = await ingest_items_to_qdrant(client, collection_name, items_to_process, model)
                    else:
                        detected_type = doc_type or detect_json_type([json_data])
                        result = await upsert_generic_points(client, collection_name, [json_data], detected_type, model)
                        total_points = result["count"]

                results.append({
                    "filename": file.filename,
                    "status": "success",
                    "points_added": total_points,
                    "format": "json"
                })

            # Handle all text-based files (PDF, TXT, etc.)
            else:
                text_content = ""
                if file.filename.lower().endswith('.pdf'):
                    text_content = extract_text_from_pdf(io.BytesIO(content_bytes))
                else:
                    text_content = content_bytes.decode('utf-8')

                ingest_items = []
                if use_auto_chunking:
                    ingest_items = process_file_for_ingestion(
                        file_path=file.filename,
                        content=text_content,
                        override_doc_type=doc_type,
                        override_chunk_size=chunk_size,
                        embedding_dim=vector_size
                    )
                else:
                    ingest_items = ingest_document(
                        file_path=file.filename,
                        text_content=text_content,
                        doc_type=doc_type or "Document",
                        chunk_size=chunk_size or 2000,
                        embedding_dim=vector_size
                    )

                # Pass the model to the ingestion function
                total_points = await ingest_items_to_qdrant(client, collection_name, ingest_items, model)

                results.append({
                    "filename": file.filename,
                    "status": "success",
                    "points_added": total_points,
                    "doc_type": ingest_items[0]["metadata"]["doc_type"] if ingest_items else "unknown"
                })

        except Exception as e:
            logger.exception(f"Error processing file {file.filename}: {str(e)}")
            errors.append({"file": file.filename, "error": str(e)})

    return {
        "message": f"Processed {len(results)} files with {len(errors)} errors",
        "results": results,
        "errors": errors
    }

# ...existing code...

# Helper function to ingest items to Qdrant - UPDATED to accept model parameter
async def ingest_items_to_qdrant(client, collection_name, ingest_items, model):
    """Helper function to ingest items to Qdrant using the provided embedding model"""
    if not ingest_items:
        return 0

    points_to_upsert = []
    
    # Extract all texts for a single batch encoding call
    texts_to_encode = [item["text"] for item in ingest_items]
    embeddings = model.encode(texts_to_encode).tolist()

    for i, item in enumerate(ingest_items):
        # Ensure metadata exists
        if "metadata" not in item:
            item["metadata"] = {}
        if "doc_type" not in item["metadata"]:
            item["metadata"]["doc_type"] = determine_doc_type(
                metadata=item["metadata"],
                filename=item.get("filename", ""),
                content=item["text"][:1000] if item.get("text") else ""
            )
        
        payload = {
            "text": item["text"],
            "metadata": item.get("metadata", {}),
            "doc_type": item["metadata"].get("doc_type", "unknown"),
            "full_document": item.get("full_document", False),
            "chunk_index": item.get("chunk_index", 0)
        }
        # Add individual metadata fields to payload for easier filtering
        for key, value in item.get("metadata", {}).items():
            payload[key] = value
        points_to_upsert.append(models.PointStruct(
            id=item["id"],
            vector=embeddings[i],
            payload=payload
        ))
    
    # Upsert all points in a single batch
    client.upsert(
        collection_name=collection_name,
        points=points_to_upsert,
        wait=True
    )
    
    return len(points_to_upsert)


@router.post("/embed-case-directory", summary="Scan, create, and embed a full case directory")
async def embed_case_directory(
    request: EmbedCaseDirectoryRequest,
    client: QdrantClient = Depends(get_connected_client)
):
    """
    Creates a new collection and ingests all files from a specified case directory.

    Example Request:
        {
            "case_directory": "case_001",
            "collection_name": "case_001_collection", 
            "embedding_dim": 384
        }
    """
    base_path = Path("./static/latam/violations_data/Case/latam_fiasco/transcript_analyses")
    target_dir = base_path / request.case_directory

    if not target_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Case directory not found: {target_dir}")

    # 1. Create or recreate the collection
    try:
        client.recreate_collection(
            collection_name=request.collection_name,
            vectors_config=models.VectorParams(size=request.embedding_dim, distance=models.Distance.COSINE)
        )
        logger.info(f"Successfully created collection '{request.collection_name}'")
    except Exception as e:
        # If recreate fails because it already exists, proceed; otherwise raise
        if "already exists" in str(e).lower():
            logger.warning(f"Collection '{request.collection_name}' already exists. Proceeding with ingestion.")
        else:
            logger.error(f"Failed to create collection '{request.collection_name}': {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create Qdrant collection: {e}")

    # 2. Scan and ingest files
    files_processed = 0
    points_added = 0
    errors = []
    files_summary = []

    # Resolve embedding model
    model = embedding_models.get(request.embedding_dim)
    if model is None:
        raise HTTPException(status_code=400, detail=f"Unsupported embedding_dim: {request.embedding_dim}")

    for file_path in target_dir.rglob("*"):
        if not file_path.is_file():
            continue

        try:
            with open(file_path, "rb") as f:
                content_bytes = f.read()

            text_content = ""
            if file_path.suffix.lower() == '.pdf':
                text_content = extract_text_from_pdf(io.BytesIO(content_bytes))
            elif file_path.suffix.lower() == '.json':
                text_content = json.dumps(json.loads(content_bytes.decode('utf-8')))
            else:  # Treat as text
                try:
                    text_content = content_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    # fallback: skip binary/unreadable files
                    logger.warning(f"Skipping unreadable file (encoding issue): {file_path}")
                    continue

            if not text_content.strip():
                logger.warning(f"Skipping empty file: {file_path}")
                continue

            ingest_items = process_file_for_ingestion(
                file_path=str(file_path),
                content=text_content,
                embedding_dim=request.embedding_dim
            )

            # Compute file-level metadata
            file_sha256 = hashlib.sha256(content_bytes).hexdigest()
            file_size = len(content_bytes)

            # Assign deterministic IDs and enrich payload metadata
            for item in ingest_items:
                # Deterministic id: use UUID5 derived from stable name to ensure valid UUID format
                content_hash = hashlib.sha256(item['text'].encode('utf-8')).hexdigest()
                name = f"{request.collection_name}|{file_path}|{item.get('chunk_index',0)}|{content_hash}"
                item['id'] = str(uuid.uuid5(uuid.NAMESPACE_URL, name))

                # Ensure metadata exists and add provenance fields
                item.setdefault('metadata', {})
                item['metadata'].update({
                    'filename': file_path.name,
                    'file_path': str(file_path),
                    'file_size': file_size,
                    'file_sha256': file_sha256,
                    'dataset': request.case_directory,
                    'collection': request.collection_name
                })

            # Ingest to Qdrant using existing helper (will encode using model)
            count = await ingest_items_to_qdrant(client, request.collection_name, ingest_items, model)
            points_added += count
            files_processed += 1
            files_summary.append({
                'file': str(file_path),
                'points_added': count,
                'sha256': file_sha256,
                'file_size': file_size
            })

            logger.info(f"Ingested {file_path} ({count} points)")

        except Exception as e:
            logger.exception(f"Error processing file {file_path} for case embedding: {e}")
            errors.append({"file": str(file_path), "error": str(e)})

    # Write collection meta to disk for easier retrieval and display
    meta = {
        'collection': request.collection_name,
        'ingested_at': datetime.utcnow().isoformat(),
        'source': str(target_dir),
        'files_processed': files_processed,
        'total_points': points_added,
        'embedding_dim': request.embedding_dim,
        'files': files_summary
    }

    meta_dir = Path('data/collections')
    meta_dir.mkdir(parents=True, exist_ok=True)
    meta_path = meta_dir / f"{request.collection_name}.meta.json"
    try:
        with open(meta_path, 'w') as mf:
            json.dump(meta, mf, indent=2)
    except Exception as e:
        logger.warning(f"Failed to write collection meta file: {e}")

    return {
        "message": f"Embedding complete for collection '{request.collection_name}'.",
        "files_processed": files_processed,
        "total_points_added": points_added,
        "errors": errors,
        "meta_file": str(meta_path)
    }


@router.post("/embed-project-code", summary="Generate code summaries and index into dev-code collection")
async def embed_project_code(request: EmbedProjectCodeRequest):
    """
    Scans a project root directory, generates markdown summaries for source code
    files, and ingests them into a Qdrant collection (default: 'olivia-dev-code').
    """
    project_root = Path(request.project_root).resolve()
    if not project_root.is_dir():
        raise HTTPException(status_code=400, detail=f"Project root not found: {request.project_root}")

    # Create/recreate the collection
    client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port, api_key=settings.qdrant_api_key)
    try:
        client.recreate_collection(
            collection_name=request.collection_name,
            vectors_config=models.VectorParams(size=request.embedding_dim, distance=models.Distance.COSINE)
        )
        logger.info(f"Created/recreated collection '{request.collection_name}' with dim {request.embedding_dim}")
    except Exception as e:
        logger.warning(f"Collection setup warning: {e}")

    model = embedding_models.get(request.embedding_dim)
    if model is None:
        raise HTTPException(status_code=400, detail=f"Unsupported embedding_dim: {request.embedding_dim}")

    SOURCE_EXTENSIONS = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.go', '.java', '.rs',
        '.cpp', '.hpp', '.h', '.c', '.rb', '.php', '.swift', '.kt', '.scala',
        '.sql', '.yaml', '.yml', '.json', '.md', '.html', '.css', '.scss', '.less',
        '.sh', '.bash', '.zsh', '.dockerfile', '.tf', '.proto',
    }
    SKIP_DIRS = {
        'node_modules', '__pycache__', '.git', '.venv', '.eggs', '.mypy_cache',
        '.pytest_cache', '.cache', '.tox', 'dist', 'build', '.next', '.terraform',
        '__pycache__', '.svn', '.hg', 'venv', 'env', '.godot', 'target',
    }
    SKIP_FILES = {'package-lock.json', 'yarn.lock', 'poetry.lock', 'Pipfile.lock'}

    files_processed = 0
    points_added = 0
    errors = []
    files_summary = []
    all_items = []

    for file_path in project_root.rglob("*"):
        if not file_path.is_file():
            continue
        if any(part.startswith('.') for part in file_path.relative_to(project_root).parts):
            continue
        if any(part in SKIP_DIRS for part in file_path.parts):
            continue
        ext = file_path.suffix.lower()
        if ext not in SOURCE_EXTENSIONS and file_path.name not in ('Dockerfile', 'Makefile', 'Justfile', 'CMakeLists.txt'):
            continue
        if file_path.name in SKIP_FILES:
            continue

        try:
            content_bytes = file_path.read_bytes()
            if not content_bytes.strip():
                continue
            try:
                text_content = content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                continue

            rel_path = file_path.relative_to(project_root)
            lang = ext.lstrip('.').upper() if ext else 'TEXT'
            lines = text_content.split('\n')
            line_count = len(lines)
            if line_count > 2000:
                display_text = '\n'.join(lines[:2000])
                display_text += f"\n\n<!-- FILE TRUNCATED: {line_count} total lines, showing first 2000 -->"
            else:
                display_text = text_content

            summary_md = [
                f"# File: `{rel_path}`",
                f"- **Language**: {lang}",
                f"- **Lines**: {line_count}",
                f"- **Size**: {file_path.stat().st_size} bytes",
                "",
                "```" + (ext.lstrip('.') if ext else 'text'),
                display_text,
                "```",
            ]
            summary_text = '\n'.join(summary_md)

            ingest_items = process_file_for_ingestion(
                file_path=str(file_path),
                content=summary_text,
                embedding_dim=request.embedding_dim
            )

            file_sha256 = hashlib.sha256(content_bytes).hexdigest()
            file_size = len(content_bytes)

            import uuid
            for item in ingest_items:
                content_hash = hashlib.sha256(item['text'].encode('utf-8')).hexdigest()
                name = f"{request.collection_name}|{rel_path}|{item.get('chunk_index', 0)}|{content_hash}"
                item['id'] = str(uuid.uuid5(uuid.NAMESPACE_URL, name))
                item.setdefault('metadata', {})
                item['metadata'].update({
                    'filename': file_path.name,
                    'file_path': str(rel_path),
                    'file_size': file_size,
                    'file_sha256': file_sha256,
                    'language': lang,
                    'line_count': line_count,
                    'collection': request.collection_name,
                    'doc_type': 'source_code',
                })

            all_items.extend(ingest_items)
            files_processed += 1
            files_summary.append({
                'file': str(rel_path),
                'language': lang,
                'chunks': len(ingest_items),
                'file_size': file_size,
            })
        except Exception as e:
            logger.exception(f"Error processing {file_path}: {e}")
            errors.append({"file": str(file_path), "error": str(e)})

    if all_items:
        points_added = await ingest_items_to_qdrant(client, request.collection_name, all_items, model)

    meta_dir = Path('data/collections')
    meta_dir.mkdir(parents=True, exist_ok=True)
    meta_path = meta_dir / f"{request.collection_name}.meta.json"
    meta = {
        'collection': request.collection_name,
        'ingested_at': datetime.utcnow().isoformat(),
        'source': str(project_root),
        'files_processed': files_processed,
        'total_points': points_added,
        'embedding_dim': request.embedding_dim,
        'files': files_summary,
    }
    try:
        with open(meta_path, 'w') as mf:
            json.dump(meta, mf, indent=2)
    except Exception as e:
        logger.warning(f"Failed to write collection meta file: {e}")

    return {
        "message": f"Project code indexing complete for collection '{request.collection_name}'.",
        "files_processed": files_processed,
        "total_points_added": points_added,
        "errors": errors,
        "meta_file": str(meta_path),
    }


# Function to detect JSON data type based on field patterns
def detect_json_type(items):
    """Detect the type of JSON data based on field patterns"""
    if not items:
        return "unknown"
    
    sample = items[0]
    
    # Check for transcript pattern
    if "speaker" in sample and ("text" in sample or "transcript" in sample):
        return "transcript"
    
    # Check for violation pattern
    if "violation_type" in sample or "reasoning" in sample:
        return "violation"
    
    # Check for law pattern
    if ("title" in sample and "text" in sample) or "article" in sample or "section" in sample:
        return "law"
    
    # Check for PDF conversion format
    if "full_text" in sample and "chunks" in sample:
        return "document"
    
    # Default
    return "document"

def determine_doc_type(metadata: dict, filename: str = "", content: str = "") -> str:
    """
    Determines the document type based on metadata, filename, or content.
    Returns one of: "Resolution", "RBAC", "CDC", "ICAO", "IN", "Internal", "unknown"
    """
    # First check if doc_type is already provided in metadata
    if "doc_type" in metadata:
        return metadata["doc_type"]
    
    # Try to determine from filename
    if filename:
        filename_lower = filename.lower()
        if "resolução" in filename_lower or "resolucao" in filename_lower or "resolution" in filename_lower:
            return "Resolution"
        elif "rbac" in filename_lower:
            return "RBAC"
        elif "cdc" in filename_lower or "consumidor" in filename_lower:
            return "CDC"
        elif "icao" in filename_lower or "annex" in filename_lower:
            return "ICAO"
        elif "instrução" in filename_lower or "instrucao" in filename_lower or "in_anac" in filename_lower:
            return "IN"
        elif "internal" in filename_lower or "hr" in filename_lower or "probation" in filename_lower:
            return "Internal"
    
    # Try to determine from content
    if content:
        content_sample = content[:1000].lower()  # Look at first 1000 chars
        if "resolução" in content_sample or "resolucao" in content_sample:
            return "Resolution"
        elif "rbac" in content_sample:
            return "RBAC"
        elif "código de defesa do consumidor" in content_sample or "cdc" in content_sample:
            return "CDC"
        elif "icao" in content_sample or "annex" in content_sample:
            return "ICAO"
        elif "instrução normativa" in content_sample:
            return "IN"
    
    # Default
    return "unknown"

# 3. Fix query_points endpoint (around line 1951)
@router.post("/query", summary="Query a Collection with Vector")
async def query_points(
    request: QueryRequest,
    client: QdrantClient = Depends(get_connected_client)
):
    """Performs a vector search on a collection."""
    try:
        # FIXED: Replace client.search() with client.query_points()
        search_results = client.query_points(
            collection_name=request.collection_name,
            query=request.query_vector,
            limit=request.limit,
            with_payload=True
        ).points
        
        return {"results": search_results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 4. Fix search_qdrant endpoint (around line 2034)
@router.post("/qdrant/search")
async def search_qdrant(
    collection_name: str,
    query_text: str,
    limit: int = 5,
    score_threshold: float = 0.5,
    client: QdrantClient = Depends(get_connected_client)
):
    """Direct search endpoint for Qdrant."""
    try:
        # Validate collection exists
        collection_info = client.get_collection(collection_name=collection_name)
        vector_size = collection_info.config.params.vectors.size
        
        # Get correct embedding model
        model = embedding_models.get(vector_size)
        if not model:
            raise HTTPException(status_code=500, detail=f"No embedding model available for dimension {vector_size}")
        
        # Generate embedding
        query_embedding = model.encode(query_text).tolist()
        
        # Search using the client parameter, not undefined qdrant_client
        results = client.query_points(
            collection_name=collection_name,
            query=query_embedding,
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True
        ).points
        
        return {
            "query": query_text,
            "collection": collection_name,
            "results": [
                {
                    "id": str(r.id),
                    "score": float(r.score),
                    "payload": r.payload
                }
                for r in results
            ]
        }
    except Exception as e:
        logger.error(f"Search error in collection '{collection_name}': {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



# ============================================================================
# Search & Query Endpoints
# ============================================================================

@router.post("/search", summary="Search a Collection with Text")
async def search_with_text(
    request: SearchRequest,
    client: QdrantClient = Depends(get_connected_client)
):
    """
    Supports multiple query input formats:
      - single string: "text"
      - list of strings: ["text1", "text2"] (will run each query and aggregate results)
      - object: {"text": "..."} or {"query": "..."}

    Aggregation strategy: when multiple queries are provided we take the maximum score per result id
    (i.e., OR semantics with best-match ranking). You can extend this to average or weighted aggregation.
    """
    try:
        # Validate collection exists
        try:
            collection_info = client.get_collection(collection_name=request.collection_name)
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"Collection '{request.collection_name}' not found: {str(e)}")
        
        # Determine vector size and get embedding model
        vector_size = collection_info.config.params.vectors.size
        model = embedding_models.get(vector_size)
        if not model:
            logger.error(f"No embedding model for dimension {vector_size}")
            raise HTTPException(status_code=500, detail=f"No embedding model available for dimension {vector_size}.")

        # Normalize query_text into list of strings
        qtext = request.query_text
        if isinstance(qtext, dict):
            # Accept {"text": ...} or {"query": ...} or {"query_text": ...}
            for key in ("text", "query", "query_text", "q"):
                if key in qtext:
                    qtext = qtext[key]
                    break
        # Now qtext should be str or list
        if isinstance(qtext, str):
            texts = [qtext]
        elif isinstance(qtext, list):
            # filter to strings only
            texts = [t for t in qtext if isinstance(t, str) and t.strip()]
            if not texts:
                raise HTTPException(status_code=400, detail="`query_text` list contains no valid strings")
        else:
            raise HTTPException(status_code=400, detail="Unsupported `query_text` type. Provide a string, list of strings or an object with a 'text' field.")

        # Encode all texts at once
        embeddings = model.encode(texts, convert_to_numpy=True)
        logger.debug(f"Generated {embeddings.shape[0]} embeddings for {len(texts)} query texts")

        # Aggregate results across embeddings
        results_by_id: Dict[Any, Dict[str, Any]] = {}
        
        # Use filters or filter alias
        qdrant_filter = sanitize_qdrant_filter(request.filters or request.filter)

        for emb in embeddings:
            query_vec = emb.tolist()
            search_results = client.query_points(
                collection_name=request.collection_name,
                query=query_vec,
                limit=request.limit,
                query_filter=qdrant_filter,
                with_payload=True
            ).points

            for r in search_results:
                rid = r.id
                score = float(r.score)
                payload = dict(r.payload) if r.payload else {}
                existing = results_by_id.get(rid)
                if existing is None or score > existing['score']:
                    results_by_id[rid] = {
                        'id': rid,
                        'score': score,
                        'payload': payload,
                        'version': getattr(r, 'version', None)
                    }

        # Convert aggregated results to list sorted by score
        aggregated = sorted(results_by_id.values(), key=lambda x: x['score'], reverse=True)

        # Apply min_score filter if provided
        if request.min_score and request.min_score > 0.0:
            aggregated = [r for r in aggregated if r['score'] >= request.min_score]

        # Respect the result limit
        aggregated = aggregated[: request.limit]

        return {
            'status': 'success',
            'count': len(aggregated),
            'results': aggregated
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Search error in collection '{request.collection_name}': {str(e)}")
        raise HTTPException(status_code=500, detail=f"An error occurred during search: {str(e)}")
@router.post("/collections/{collection_name}/query/vector", summary="Query with Vector")
async def query_with_vector(
    collection_name: str,
    request: QueryVectorRequest,
    client: QdrantClient = Depends(get_connected_client)
):
    """Direct vector similarity search or text-to-vector search.

    Accepts:
      - A numeric vector (list of floats)
      - A single query string (will be encoded)
      - A list of query strings (will be encoded and results aggregated)
    """
    try:
        query_input = request.query_vector
        limit = request.limit
        qdrant_filter = sanitize_qdrant_filter(request.filter)
        score_threshold = request.score_threshold
        with_payload = request.with_payload

        # Normalize filter values for legal fields (case-insensitive search support)
        if qdrant_filter and isinstance(qdrant_filter, dict):
            legal_fields_to_lower = [
                "legislacao_citada", "jurisprudencia_citada", "tribunal", 
                "relator", "document_type", "section_type"
            ]
            # Handle 'must' filters
            if "must" in qdrant_filter and isinstance(qdrant_filter["must"], list):
                for condition in qdrant_filter["must"]:
                    if isinstance(condition, dict) and condition.get("key") in legal_fields_to_lower:
                        match_data = condition.get("match")
                        if isinstance(match_data, dict) and "value" in match_data:
                            val = match_data["value"]
                            if isinstance(val, str):
                                match_data["value"] = val.lower()
                            elif isinstance(val, list):
                                match_data["value"] = [v.lower() if isinstance(v, str) else v for v in val]

        # Case 1: Single string or list of strings
        if isinstance(query_input, str) or (isinstance(query_input, list) and query_input and isinstance(query_input[0], str)):
            # Determine collection vector size
            try:
                collection_info = client.get_collection(collection_name=collection_name)
            except Exception as e:
                raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' not found: {e}")
            
            vector_size = collection_info.config.params.vectors.size
            
            # Select model: prefer Portuguese BERT for 768 if available, else fallback
            model = None
            if vector_size == 768:
                model = embedding_models.get('neuralmind/bert-base-portuguese-cased') or embedding_models.get(768)
            else:
                model = embedding_models.get(vector_size)
                
            if not model:
                raise HTTPException(status_code=500, detail=f"No embedding model for dimension {vector_size}")

            texts = [query_input] if isinstance(query_input, str) else [t for t in query_input if isinstance(t, str) and t.strip()]
            if not texts:
                raise HTTPException(status_code=400, detail="Provided query_vector as text but found no valid strings")
            
            embeddings = model.encode(texts, convert_to_numpy=True)

            # Aggregate results across embeddings (max score wins)
            results_by_id = {}
            for emb in embeddings:
                try:
                    search_results = client.query_points(
                        collection_name=collection_name,
                        query=emb.tolist(),
                        limit=limit,
                        query_filter=qdrant_filter,
                        score_threshold=score_threshold,
                        with_payload=with_payload
                    ).points
                except Exception as e:
                    if "Index required but not found" in str(e):
                        # Extract field name from error message if possible
                        match = re.search(r'for \\"([^\\"]+)\\"', str(e))
                        field_name = match.group(1) if match else None
                        if field_name:
                            logger.info(f"Auto-creating missing index for field: {field_name}")
                            client.create_payload_index(
                                collection_name=collection_name,
                                field_name=field_name,
                                field_schema=models.PayloadSchemaType.KEYWORD
                            )
                            # Retry once
                            search_results = client.query_points(
                                collection_name=collection_name,
                                query=emb.tolist(),
                                limit=limit,
                                query_filter=qdrant_filter,
                                score_threshold=score_threshold,
                                with_payload=with_payload
                            ).points
                        else:
                            raise e
                    else:
                        raise e

                for r in search_results:
                    rid = r.id
                    score = float(r.score)
                    payload = dict(r.payload) if r.payload else {}
                    existing = results_by_id.get(rid)
                    if existing is None or score > existing['score']:
                        results_by_id[rid] = {'id': rid, 'score': score, 'payload': payload}

            aggregated = sorted(results_by_id.values(), key=lambda x: x['score'], reverse=True)[:limit]
            return {
                'status': 'success',
                'count': len(aggregated),
                'results': aggregated
            }

        # Case 2: Numeric vector
        if not isinstance(query_input, list) or not all(isinstance(x, (int, float)) for x in query_input):
            raise HTTPException(status_code=422, detail="`query_vector` must be a list of numbers, a string, or a list of strings")

        search_results = client.query_points(
            collection_name=collection_name,
            query=query_input,
            limit=limit,
            query_filter=qdrant_filter,
            score_threshold=score_threshold,
            with_payload=with_payload
        ).points
            
        return {
            "status": "success",
            "count": len(search_results),
            "results": [
                {
                    "id": r.id,
                    "score": r.score,
                    "payload": r.payload
                }
                for r in search_results
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Query error in collection '{collection_name}': {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Vector query failed: {str(e)}"
        )
