from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File
from typing import Dict, Any, List, Optional
import logging
import tempfile
import os
import threading
from pathlib import Path
import json

from core.ingestion import IngestionPipeline, document_processor
from config.settings import settings

# Import the specific Qdrant connection error to map it to HTTP 503
try:
    from core.qdrant_client import QdrantConnectionError
except Exception:
    QdrantConnectionError = Exception

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/ingestion", tags=["Ingestion"])

# Global pipeline instance
_pipeline: IngestionPipeline | None = None
_pipeline_lock = threading.Lock()

def get_pipeline() -> IngestionPipeline:
    """Get or create ingestion pipeline instance (thread-safe)."""
    global _pipeline
    with _pipeline_lock:
        if _pipeline is None:
            _pipeline = IngestionPipeline(
                qdrant_url=getattr(settings, 'qdrant_url', None),
                qdrant_host=getattr(settings, 'qdrant_host', 'localhost'),
                qdrant_port=getattr(settings, 'qdrant_port', 6333),
                qdrant_api_key=getattr(settings, 'qdrant_api_key', None)
            )
    return _pipeline

@router.post("/ingest-directory")
async def ingest_directory(
    background_tasks: BackgroundTasks,
    directory_path: str,
    collection_name: str,
    force_recreate: bool = False,
    exclude_dirs: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Ingest all documents from a directory into vector database."""
    try:
        if not os.path.exists(directory_path):
            raise HTTPException(status_code=400, detail="Directory does not exist")
        
        pipeline = get_pipeline()
        
        # Run ingestion in background
        def run_ingestion():
            try:
                result = pipeline.ingest_directory(
                    directory_path=directory_path,
                    collection_name=collection_name,
                    force_recreate=force_recreate,
                    exclude_dirs=exclude_dirs
                )
                logger.info(f"Ingestion completed: {result}")
            except Exception as e:
                logger.error(f"Ingestion failed: {e}")
        
        background_tasks.add_task(run_ingestion)
        
        return {
            "message": "Ingestion started in background",
            "directory_path": directory_path,
            "collection_name": collection_name
        }
        
    except Exception as e:
        logger.error(f"Error starting ingestion: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/ingest-file")
async def ingest_file(
    file: UploadFile = File(...),
    collection_name: str = "default_collection",
    force_recreate: bool = False
) -> Dict[str, Any]:
    """Ingest a single uploaded file."""
    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_file_path = tmp_file.name
        
        try:
            pipeline = get_pipeline()
            result = pipeline.ingest_file(
                file_path=tmp_file_path,
                collection_name=collection_name,
                force_recreate=force_recreate
            )
            
            return {
                **result,
                "original_filename": file.filename
            }
            
        finally:
            # Clean up temporary file
            os.unlink(tmp_file_path)
            
    except Exception as e:
        logger.error(f"Error ingesting file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest-legal-file")
async def ingest_legal_file(
    file: UploadFile = File(...),
    collection_name: str = "legal_documents",
    force_recreate: bool = False,
    model_name: Optional[str] = None,
    metadata_json: Optional[str] = None,
    enhanced: bool = True,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None
) -> Dict[str, Any]:
    """Ingest a single legal DOC/DOCX file with legal-aware defaults."""
    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_file_path = tmp_file.name

        try:
            pipeline = get_pipeline()
            
            # Override chunker settings if provided
            if chunk_size:
                pipeline.chunker.max_chunk_size = chunk_size
            if chunk_overlap:
                pipeline.chunker.overlap = chunk_overlap

            # Parse provided metadata if any
            provided_metadata = None
            if metadata_json:
                try:
                    provided_metadata = json.loads(metadata_json)
                except Exception as e:
                    logger.warning(f"Failed to parse metadata_json: {e}")

            result = pipeline.ingest_legal_file(
                file_path=tmp_file_path,
                collection_name=collection_name,
                force_recreate=force_recreate,
                model_name=model_name,
                provided_metadata=provided_metadata,
                enhanced=enhanced
            )

            return {
                **result,
                "original_filename": file.filename
            }

        finally:
            # Clean up temporary file
            os.unlink(tmp_file_path)

    except Exception as e:
        logger.error(f"Error ingesting legal file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/analyze-document-structure")
async def analyze_document_structure(
    file: UploadFile = File(...)
) -> Dict[str, Any]:
    """Analyze document structure without ingestion."""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_file_path = tmp_file.name

        try:
            pipeline = get_pipeline()
            result = pipeline.analyze_document_structure(tmp_file_path)
            return result
        finally:
            os.unlink(tmp_file_path)
    except Exception as e:
        logger.error(f"Error analyzing document: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/search")
async def search_documents(
    collection_name: str,
    query: str,
    limit: int = 10
) -> Dict[str, Any]:
    """Search for documents similar to query."""
    try:
        pipeline = get_pipeline()
        results = pipeline.search_collection(
            collection_name=collection_name,
            query_text=query,
            limit=limit
        )
        
        return {
            "query": query,
            "collection": collection_name,
            "results": results,
            "count": len(results)
        }
        
    except Exception as e:
        logger.error(f"Error searching documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/collections/{collection_name}/info")
async def get_collection_info(collection_name: str) -> Dict[str, Any]:
    """Get information about a collection."""
    try:
        pipeline = get_pipeline()
        info = pipeline.vector_store.get_collection_info(collection_name)
        
        if not info:
            raise HTTPException(status_code=404, detail="Collection not found")

        # Try to attach ingestion meta if available
        meta_path = Path("data/collections") / f"{collection_name}.meta.json"
        if meta_path.exists():
            try:
                with open(meta_path, 'r') as mf:
                    info['ingestion_meta'] = json.load(mf)
                    info['meta_file'] = str(meta_path)
                logger.info(f"Attached ingestion meta for collection {collection_name} from {meta_path}")
            except Exception as e:
                logger.warning(f"Failed to load collection meta file {meta_path}: {e}")

        return info
        
    except HTTPException:
        raise
    except QdrantConnectionError as e:
        logger.error(f"Error getting collection info: {e}")
        raise HTTPException(status_code=503, detail=f"Qdrant unavailable: {str(e)}")
    except Exception as e:
        logger.error(f"Error getting collection info: {e}")
        raise HTTPException(status_code=500, detail=str(e))