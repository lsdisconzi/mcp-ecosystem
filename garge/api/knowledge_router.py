from importlib import metadata
import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from networkx import cut_size
from pydantic import BaseModel, Field
import json
import os
import uuid
from datetime import datetime
from api.schemas import KnowledgeQueryRequest, KnowledgeIngestTextRequest
from qdrant_client.http.models import VectorParams, Distance

logger = logging.getLogger(__name__)
router = APIRouter()

# Try to import optional dependencies
try:
    from core.embeddings import get_embedding_service
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    logger.warning("Embeddings service not available. Install sentence-transformers: pip install sentence-transformers")
    EMBEDDINGS_AVAILABLE = False

try:
    from core.qdrant_client import get_qdrant_client
    QDRANT_AVAILABLE = True
except ImportError:
    logger.warning("Qdrant client not available")
    QDRANT_AVAILABLE = False

try:
    from core.file_processor import FileProcessor
    FILE_PROCESSOR_AVAILABLE = True
except ImportError:
    logger.warning("File processor not available")
    FILE_PROCESSOR_AVAILABLE = False

# Request/Response Models
class KnowledgeQueryRequest(BaseModel):
    """Flexible knowledge query request accepting multiple field names."""
    query: Optional[str] = Field(None, description="Query text (primary field)")
    question: Optional[str] = Field(None, description="Alternative field name for query")
    collection_name: str = Field(..., description="Target collection name")
    assistant_id: Optional[str] = Field(None, description="Optional assistant ID for context")
    limit: int = Field(5, ge=1, le=100, description="Maximum results to return")
    score_threshold: float = Field(0.7, ge=0.0, le=1.0, description="Minimum similarity score")
    filter: Optional[Dict[str, Any]] = Field(None, description="Optional metadata filter")

class KnowledgeIngestRequest(BaseModel):
    """Request for ingesting text into knowledge base."""
    collection_name: str = Field(..., description="Target collection name")
    text: str = Field(..., description="Text content to ingest")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional metadata")
    chunk_size: int = Field(512, ge=100, le=2000, description="Text chunk size")
    chunk_overlap: int = Field(50, ge=0, le=500, description="Overlap between chunks")

class KnowledgeSearchResult(BaseModel):
    """Individual search result."""
    id: str
    score: float
    content: str
    metadata: Optional[Dict[str, Any]] = None

class KnowledgeQueryResponse(BaseModel):
    """Response for knowledge queries."""
    results: List[KnowledgeSearchResult]
    count: int
    query: str
    collection: str
    message: Optional[str] = None

# Helper Functions
def chunk_text(text: str, chunk_size: int = 512, overlap: int = 50) -> List[str]:
    """Split text into overlapping chunks."""
    if not text:
        return []
    
    chunks = []
    start = 0
    text_length = len(text)
    
    while start < text_length:
        end = start + chunk_size
        chunk = text[start:end]
        
        if chunk.strip():
            chunks.append(chunk.strip())
        
        start = end - overlap
        if start >= text_length:
            break
    
    return chunks

def load_assistant_collections(assistant_id: str) -> List[str]:
    """Load collection names associated with an assistant."""
    try:
        assistant_path = f"data/assistants/{assistant_id}.json"
        if not os.path.exists(assistant_path):
            return []
        
        with open(assistant_path, 'r') as f:
            assistant_data = json.load(f)
            return assistant_data.get("collections", [])
    except Exception as e:
        logger.error(f"Error loading assistant collections: {e}")
        return []

def check_dependencies():
    """Check if required dependencies are available and reachable."""
    if not EMBEDDINGS_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Embeddings service not available. Install: pip install sentence-transformers"
        )
    if not QDRANT_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Qdrant client not available"
        )

    # Validate connectivity to Qdrant service.
    # get_qdrant_client() already validates the connection during singleton creation.
    try:
        get_qdrant_client()
    except HTTPException:
        raise

# API Endpoints
@router.post("/query", response_model=KnowledgeQueryResponse)
async def knowledge_query(req: KnowledgeQueryRequest):
    """
    Query knowledge base with flexible field names.
    Accepts either 'query' or 'question' as the search text.
    """
    check_dependencies()
    
    try:
        # Get query text from either field
        query_text = req.query or req.question
        if not query_text:
            raise HTTPException(
                status_code=422,
                detail="Either 'query' or 'question' field is required"
            )
        
        qdrant = get_qdrant_client()
        embedding_service = get_embedding_service()
        
        # Generate query embedding
        query_embedding = embedding_service.embed_text(query_text)
        
        # Search in collection
        search_results = qdrant.search(
            collection_name=req.collection_name,
            query_vector=query_embedding,
            limit=req.limit,
            score_threshold=req.score_threshold,
            query_filter=req.filter
        )
        
        # Format results
        results = []
        for result in search_results:
            results.append(KnowledgeSearchResult(
                id=str(result.id),
                score=result.score,
                content=result.payload.get("content", ""),
                metadata=result.payload.get("metadata")
            ))
        
        return KnowledgeQueryResponse(
            results=results,
            count=len(results),
            query=query_text,
            collection=req.collection_name
        )
        
    except Exception as e:
        logger.error(f"Error querying knowledge: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/assistant/{assistant_id}/query")
async def assistant_query_knowledge(assistant_id: str, req: KnowledgeQueryRequest):
    """
    Query all knowledge collections associated with an assistant.
    """
    try:
        # Ensure dependencies (including Qdrant connectivity)
        check_dependencies()

        # Load assistant's collections
        collections = load_assistant_collections(assistant_id)
        
        if not collections:
            return KnowledgeQueryResponse(
                results=[],
                count=0,
                query=req.query,
                collection="",
                message="No collections configured for this assistant"
            )
        
        qdrant = get_qdrant_client()
        embedding_service = get_embedding_service()
        
        # Generate query embedding
        query_embedding = embedding_service.embed_text(req.query)
        
        # Search across all collections
        all_results = []
        for collection in collections:
            try:
                search_results = qdrant.search(
                    collection_name=collection,
                    query_vector=query_embedding,
                    limit=req.limit
                )
                
                for result in search_results:
                    all_results.append({
                        "collection": collection,
                        "result": result
                    })
            except Exception as e:
                logger.warning(f"Error searching collection {collection}: {e}")
                continue
        
        # Sort by score and limit
        all_results.sort(key=lambda x: x["result"].score, reverse=True)
        all_results = all_results[:req.limit]
        
        # Format results
        results = []
        for item in all_results:
            result = item["result"]
            results.append(KnowledgeSearchResult(
                id=str(result.id),
                score=result.score,
                content=result.payload.get("content", ""),
                metadata={
                    **result.payload.get("metadata", {}),
                    "collection": item["collection"]
                }
            ))
        
        return KnowledgeQueryResponse(
            results=results,
            count=len(results),
            query=req.query,
            collection=",".join(collections)
        )
        
    except Exception as e:
        logger.error(f"Error querying assistant knowledge: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest/file")
async def ingest_file(collection_name: str = Form(...), file: UploadFile = File(...)):
    """
    Ingest a file into a knowledge base collection.
    Supports various file formats (PDF, TXT, MD, etc.).
    """
    check_dependencies()
    
    if not FILE_PROCESSOR_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="File processor not available"
        )
    
    try:
        # Parse metadata if provided
        file_metadata = {}
        if metadata:
            try:
                file_metadata = json.loads(metadata)
            except json.JSONDecodeError:
                logger.warning("Invalid metadata JSON, using empty dict")
        
        # Save file temporarily
        temp_path = f"data/temp/{file.filename}"
        os.makedirs("data/temp", exist_ok=True)
        
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        # Extract text from file
        processor = FileProcessor()
        extracted_text = processor.extract_text(temp_path)
        
        # Clean up temp file
        os.remove(temp_path)
        
        # Ingest extracted text
        ingest_request = KnowledgeIngestRequest(
            collection_name=collection_name,
            text=extracted_text,
            metadata={
                **file_metadata,
                "filename": file.filename,
                "content_type": file.content_type,
                "file_size": len(content)
            },
            chunk_size=cut_size,
            chunk_overlap=cut_size
        )
        
        result = await ingest_text(ingest_request)
        return result
        
    except Exception as e:
        logger.error(f"Error ingesting file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/collection/{collection_name}/clear")
async def clear_collection(collection_name: str):
    """Clear all points from a collection."""
    try:
        qdrant = get_qdrant_client()
        
        # Delete and recreate collection
        qdrant.delete_collection(collection_name)
        
        # Get embedding service to recreate with correct dimensions
        embedding_service = get_embedding_service()
        qdrant.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=embedding_service.dimension,
                distance=Distance.COSINE,
            ),
        )
        
        return {
            "success": True,
            "collection": collection_name,
            "message": "Collection cleared successfully"
        }
        
    except Exception as e:
        logger.error(f"Error clearing collection: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/collection/{collection_name}/stats")
async def get_collection_stats(collection_name: str):
    """Get statistics about a knowledge collection."""
    try:
        qdrant = get_qdrant_client()
        
        collection_info = qdrant.get_collection(collection_name)
        
        return {
            "collection": collection_name,
            "points_count": collection_info.points_count,
            "vector_size": collection_info.config.params.vectors.size,
            "distance": collection_info.config.params.vectors.distance,
            "status": collection_info.status
        }
        
    except Exception as e:
        logger.error(f"Error getting collection stats: {e}", exc_info=True)
        raise HTTPException(status_code=404, detail=f"Collection not found: {collection_name}")