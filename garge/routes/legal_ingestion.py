"""
Legal Document Ingestion API Routes
FastAPI endpoints for uploading and processing legal CSV files into Qdrant.
"""
import os
import logging
import tempfile
from typing import Optional, Dict, Any, List
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Query, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import pandas as pd
from qdrant_client import QdrantClient

from services.legal_document_ingestor import LegalDocumentIngestor

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/legal-ingestion",
    tags=["Legal Document Ingestion"]
)

# Initialize ingestor (can be configured via environment variables)
QDRANT_URL = os.getenv("QDRANT_URL", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
DEFAULT_MODEL = os.getenv("LEGAL_EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")


def _build_qdrant_client() -> QdrantClient:
    """Build a lightweight Qdrant client for read-only collection endpoints."""
    if QDRANT_API_KEY:
        return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    return QdrantClient(host=QDRANT_URL, port=QDRANT_PORT)




try:
    # Preferred import for modern LangChain
    from langchain.text_splitter import CharacterTextSplitter, RecursiveCharacterTextSplitter
except Exception:
    # Lightweight fallback splitter (used when langchain is not installed)
    class CharacterTextSplitter:
        def __init__(self, chunk_size=800, chunk_overlap=100, separators=None, length_function=len):
            self.chunk_size = chunk_size
            self.chunk_overlap = chunk_overlap
            self.separators = separators or ["\n\n\n", "\n\n", "\n", ". ", "; ", ", ", " ", ""]
            self.length_function = length_function

        def split_text(self, text: str):
            if not isinstance(text, str) or not text:
                return []
            parts = [p.strip() for p in text.split('\n\n') if p.strip()]
            if not parts:
                parts = [text]
            chunks = []
            for part in parts:
                start = 0
                while start < len(part):
                    end = start + self.chunk_size
                    chunks.append(part[start:end])
                    advance = self.chunk_size - self.chunk_overlap
                    if advance <= 0:
                        break
                    start += advance
            return chunks

    class RecursiveCharacterTextSplitter(CharacterTextSplitter):
        pass

# Ensure CSV processor / cleaner remain available
from utils.legal_csv_processor import LegalCSVProcessor, LegalTextCleaner

logger = logging.getLogger(__name__)


class LegalDocumentChunker:
    """Handles intelligent chunking of legal documents."""
    
    def __init__(
        self,
        chunk_size: int = 800,
        chunk_overlap: int = 100,
        separators: Optional[List[str]] = None
    ):
        """
        Initialize document chunker.
        
        Args:
            chunk_size: Maximum size of each chunk
            chunk_overlap: Number of characters to overlap between chunks
            separators: List of separator strings for splitting
        """
        if separators is None:
            # Legal document-specific separators
            separators = [
                "\n\n\n",  # Multiple line breaks
                "\n\n",    # Paragraph breaks
                "\n",      # Line breaks
                ". ",      # Sentences
                "; ",      # Clauses
                ", ",      # Sub-clauses
                " ",       # Words
                ""         # Characters
            ]
        
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=separators,
            length_function=len
        )
    
    def chunk_document(
        self,
        text: str,
        metadata: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Chunk a document and attach metadata to each chunk.
        
        Args:
            text: Document text to chunk
            metadata: Base metadata to attach to all chunks
            
        Returns:
            List of chunk dictionaries with text and metadata
        """
        chunks = self.text_splitter.split_text(text)
        
        chunk_dicts = []
        for idx, chunk in enumerate(chunks):
            chunk_dict = {
                'text': chunk,
                'chunk_index': idx,
                'total_chunks': len(chunks),
                'chunk_size': len(chunk),
                'tokens': len(chunk.split()),
                **metadata  # Include all original metadata
            }
            chunk_dicts.append(chunk_dict)
        
        return chunk_dicts

# Request/Response Models
class IngestionRequest(BaseModel):
    """Request model for CSV ingestion."""
    collection_name: str = Field(..., description="Name of the Qdrant collection")
    text_column: str = Field(default="texto", description="Column containing legal text")
    recreate_collection: bool = Field(default=False, description="Recreate collection if exists")
    chunk_size: int = Field(default=800, ge=100, le=2000, description="Size of text chunks")
    chunk_overlap: int = Field(default=100, ge=0, le=500, description="Overlap between chunks")
    metadata_columns: Optional[List[str]] = Field(default=None, description="Columns to include as metadata")


class IngestionResponse(BaseModel):
    """Response model for ingestion status."""
    success: bool
    message: str
    collection_name: Optional[str] = None
    total_documents: Optional[int] = None
    total_chunks: Optional[int] = None
    total_points: Optional[int] = None
    duration_seconds: Optional[float] = None
    timestamp: str


class SearchRequest(BaseModel):
    """Request model for searching legal documents."""
    query: str = Field(..., description="Search query")
    limit: int = Field(default=10, ge=1, le=100, description="Maximum results")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Metadata filters")


class SearchResult(BaseModel):
    """Single search result."""
    id: str
    score: float
    text: str
    metadata: Dict[str, Any]


class SearchResponse(BaseModel):
    """Response model for search results."""
    query: str
    results: List[SearchResult]
    total_results: int
    timestamp: str


@router.post("/upload-csv", response_model=IngestionResponse)
async def upload_and_ingest_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="CSV file containing legal documents"),
    collection_name: str = Query(..., description="Name of the Qdrant collection"),
    text_column: str = Query(default="texto", description="Column containing legal text"),
    recreate_collection: bool = Query(default=False, description="Recreate collection if exists"),
    chunk_size: int = Query(default=800, ge=100, le=2000, description="Size of text chunks"),
    chunk_overlap: int = Query(default=100, ge=0, le=500, description="Overlap between chunks"),
    async_mode: bool = Query(default=False, description="Process in background")
):
    """
    Upload a CSV file and ingest legal documents into Qdrant.
    
    The CSV file should contain:
    - `id`: Unique document identifier
    - `texto`: Legal document text (or specify different column name)
    - Optional: processo, relator, origem, classe, julgado_em, etc.
    
    Example usage:
    ```bash
    curl -X POST "http://localhost:8000/legal-ingestion/upload-csv?collection_name=jurisprudencia" \\
         -F "file=@jurisprudencia.csv"
    ```
    """
    # Validate file type
    if not file.filename.endswith('.csv'):
        raise HTTPException(
            status_code=400,
            detail="Only CSV files are supported"
        )
    
    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.csv') as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_path = temp_file.name
        
        logger.info(f"Uploaded CSV saved to {temp_path}")
        
        # Validate CSV can be read
        try:
            df = pd.read_csv(temp_path, nrows=5)
            if text_column not in df.columns:
                raise HTTPException(
                    status_code=400,
                    detail=f"Column '{text_column}' not found in CSV. Available columns: {list(df.columns)}"
                )
        except Exception as e:
            os.unlink(temp_path)
            raise HTTPException(
                status_code=400,
                detail=f"Invalid CSV file: {str(e)}"
            )
        
        if async_mode:
            # Process in background
            background_tasks.add_task(
                process_csv_background,
                temp_path,
                collection_name,
                text_column,
                recreate_collection,
                chunk_size,
                chunk_overlap
            )
            
            return IngestionResponse(
                success=True,
                message="Ingestion started in background. Check status endpoint for progress.",
                collection_name=collection_name,
                timestamp=datetime.now().isoformat()
            )
        else:
            # Process synchronously
            ingestor = LegalDocumentIngestor(
                qdrant_url=QDRANT_URL,
                qdrant_port=QDRANT_PORT,
                qdrant_api_key=QDRANT_API_KEY,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )
            
            result = ingestor.ingest_csv(
                csv_path=temp_path,
                collection_name=collection_name,
                text_column=text_column,
                recreate_collection=recreate_collection
            )
            
            # Clean up temp file
            os.unlink(temp_path)
            
            if result['success']:
                return IngestionResponse(
                    success=True,
                    message="CSV ingestion completed successfully",
                    collection_name=result['collection_name'],
                    total_documents=result['total_documents'],
                    total_chunks=result['total_chunks'],
                    total_points=result['total_points'],
                    duration_seconds=result['duration_seconds'],
                    timestamp=result['timestamp']
                )
            else:
                raise HTTPException(
                    status_code=500,
                    detail=f"Ingestion failed: {result.get('error', 'Unknown error')}"
                )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during CSV ingestion: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.post("/ingest-file", response_model=IngestionResponse)
async def ingest_from_file_path(
    request: IngestionRequest,
    file_path: str = Query(..., description="Path to CSV file on server")
):
    """
    Ingest a CSV file from a server path.
    
    Useful for processing files already on the server without uploading.
    
    Example usage:
    ```bash
    curl -X POST "http://localhost:8000/legal-ingestion/ingest-file?file_path=/data/jurisprudencia.csv" \\
         -H "Content-Type: application/json" \\
         -d '{"collection_name": "jurisprudencia", "recreate_collection": true}'
    ```
    """
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail=f"File not found: {file_path}"
        )
    
    try:
        ingestor = LegalDocumentIngestor(
            qdrant_url=QDRANT_URL,
            qdrant_port=QDRANT_PORT,
            qdrant_api_key=QDRANT_API_KEY,
            chunk_size=request.chunk_size,
            chunk_overlap=request.chunk_overlap
        )
        
        result = ingestor.ingest_csv(
            csv_path=file_path,
            collection_name=request.collection_name,
            text_column=request.text_column,
            recreate_collection=request.recreate_collection,
            metadata_columns=request.metadata_columns
        )
        
        if result['success']:
            return IngestionResponse(
                success=True,
                message="CSV ingestion completed successfully",
                collection_name=result['collection_name'],
                total_documents=result['total_documents'],
                total_chunks=result['total_chunks'],
                total_points=result['total_points'],
                duration_seconds=result['duration_seconds'],
                timestamp=result['timestamp']
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Ingestion failed: {result.get('error', 'Unknown error')}"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during CSV ingestion: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.post("/search/{collection_name}", response_model=SearchResponse)
async def search_legal_documents(
    collection_name: str,
    request: SearchRequest
):
    """
    Search for legal documents in a collection.
    
    Example usage:
    ```bash
    curl -X POST "http://localhost:8000/legal-ingestion/search/jurisprudencia" \\
         -H "Content-Type: application/json" \\
         -d '{
           "query": "recurso de apelação cível",
           "limit": 5,
           "filters": {"classe": "APELACAO"}
         }'
    ```
    """
    try:
        ingestor = LegalDocumentIngestor(
            qdrant_url=QDRANT_URL,
            qdrant_port=QDRANT_PORT,
            qdrant_api_key=QDRANT_API_KEY
        )
        
        results = ingestor.search(
            collection_name=collection_name,
            query=request.query,
            limit=request.limit,
            filters=request.filters
        )
        
        return SearchResponse(
            query=request.query,
            results=[SearchResult(**r) for r in results],
            total_results=len(results),
            timestamp=datetime.now().isoformat()
        )
    
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Search failed: {str(e)}"
        )


@router.get("/collections")
async def list_collections():
    """
    List all available collections in Qdrant.
    
    Example usage:
    ```bash
    curl http://localhost:8000/legal-ingestion/collections
    ```
    """
    try:
        client = _build_qdrant_client()
        collections = client.get_collections()
        collection_rows = []

        for col in collections.collections:
            points_count = None
            vectors_count = None
            try:
                col_info = client.get_collection(col.name)
                points_count = getattr(col_info, 'points_count', None)
                vectors_count = getattr(col_info, 'vectors_count', points_count)
            except Exception:
                # Keep endpoint fast and resilient even if detail lookup fails.
                pass

            collection_rows.append(
                {
                    "name": col.name,
                    "vectors_count": vectors_count,
                    "points_count": points_count,
                }
            )
        
        return {
            "collections": collection_rows,
            "total": len(collections.collections)
        }
    
    except Exception as e:
        logger.error(f"Error listing collections: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list collections: {str(e)}"
        )


@router.get("/collection/{collection_name}/info")
async def get_collection_info(collection_name: str):
    """
    Get information about a specific collection.
    
    Example usage:
    ```bash
    curl http://localhost:8000/legal-ingestion/collection/jurisprudencia/info
    ```
    """
    try:
        client = _build_qdrant_client()
        collection_info = client.get_collection(collection_name)
        
        return {
            "name": collection_name,
            "status": collection_info.status,
            "vectors_count": getattr(collection_info, 'vectors_count', getattr(collection_info, 'points_count', None)),
            "points_count": getattr(collection_info, 'points_count', None),
            "config": {
                "params": {
                    "vectors": {
                        "size": collection_info.config.params.vectors.size,
                        "distance": collection_info.config.params.vectors.distance
                    }
                }
            }
        }
    
    except Exception as e:
        logger.error(f"Error getting collection info: {e}")
        raise HTTPException(
            status_code=404,
            detail=f"Collection not found or error: {str(e)}"
        )


@router.delete("/collection/{collection_name}")
async def delete_collection(collection_name: str):
    """
    Delete a collection from Qdrant.
    
    Example usage:
    ```bash
    curl -X DELETE http://localhost:8000/legal-ingestion/collection/jurisprudencia
    ```
    """
    try:
        client = _build_qdrant_client()
        client.delete_collection(collection_name)
        
        return {
            "success": True,
            "message": f"Collection '{collection_name}' deleted successfully",
            "timestamp": datetime.now().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error deleting collection: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete collection: {str(e)}"
        )


# Background task function
async def process_csv_background(
    csv_path: str,
    collection_name: str,
    text_column: str,
    recreate_collection: bool,
    chunk_size: int,
    chunk_overlap: int
):
    """Process CSV ingestion in the background."""
    try:
        logger.info(f"Starting background ingestion for {csv_path}")
        
        ingestor = LegalDocumentIngestor(
            qdrant_url=QDRANT_URL,
            qdrant_port=QDRANT_PORT,
            qdrant_api_key=QDRANT_API_KEY,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )
        
        result = ingestor.ingest_csv(
            csv_path=csv_path,
            collection_name=collection_name,
            text_column=text_column,
            recreate_collection=recreate_collection
        )
        
        logger.info(f"Background ingestion completed: {result}")
        
    except Exception as e:
        logger.error(f"Background ingestion failed: {e}")
    finally:
        # Clean up temp file
        if os.path.exists(csv_path):
            os.unlink(csv_path)
