import os
import logging
import tempfile
import threading
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, UploadFile, File, HTTPException, Body, Form
from pydantic import BaseModel, ConfigDict
from config.settings import settings
from services.legal_doc_processor import LegalDocumentPipeline
from services.legal_qdrant_config import LegalDocumentVectorStore

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v2/legal-ingestion",
    tags=["Legal Document Ingestion V2"]
)

class FolderIngestionRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    folder_path: str
    collection_name: str = "legal_documents"
    force_recreate: bool = False
    model_name: Optional[str] = None
    metadata_json: Optional[str] = None
    preserve_sections: bool = True
    enhanced: bool = True  # Alias for preserve_sections from frontend
    chunk_size: int = 1500
    chunk_overlap: int = 150
    recursive: bool = False

_legal_pipeline: LegalDocumentPipeline | None = None
_legal_pipeline_lock = threading.Lock()

def get_pipeline() -> LegalDocumentPipeline:
    """Get or create the legal document pipeline (thread-safe singleton)."""
    global _legal_pipeline
    with _legal_pipeline_lock:
        if _legal_pipeline is None:
            qdrant_url = getattr(settings, 'qdrant_url', None)
            qdrant_host = getattr(settings, 'qdrant_host', 'localhost')
            qdrant_port = getattr(settings, 'qdrant_port', 6333)
            qdrant_api_key = getattr(settings, 'qdrant_api_key', None)
            
            vector_store = LegalDocumentVectorStore(
                host=qdrant_host, 
                port=qdrant_port, 
                url=qdrant_url, 
                api_key=qdrant_api_key
            )
            
            _legal_pipeline = LegalDocumentPipeline(
                qdrant_client=vector_store.client,
                embedding_model=vector_store.embedding_model
            )
    return _legal_pipeline

@router.post("/ingest-legal-file-enhanced")
async def ingest_legal_file_enhanced(
    files: List[UploadFile] = File(...),
    collection_name: str = Form("legal_documents"),
    force_recreate: bool = Form(False),
    model_name: Optional[str] = Form(None),
    metadata_json: Optional[str] = Form(None),
    preserve_sections: bool = Form(True),
    enhanced: bool = Form(True),
    chunk_size: int = Form(1500),
    chunk_overlap: int = Form(150)
) -> Dict[str, Any]:
    """Enhanced ingestion with section preservation for multiple files"""
    results = []
    total_files = len(files)
    
    # Parse metadata
    base_metadata = {}
    if metadata_json:
        try:
            base_metadata = json.loads(metadata_json)
        except Exception as e:
            logger.warning(f"Failed to parse metadata: {e}")

    # If force_recreate is true, we only want to do it for the first file
    should_recreate = force_recreate
    
    # Use enhanced if preserve_sections is default
    effective_preserve = preserve_sections if preserve_sections is not True else enhanced

    for i, file in enumerate(files):
        try:
            logger.info(f"Processing file {i+1}/{total_files}: {file.filename}")
            
            # Save uploaded file
            with tempfile.NamedTemporaryFile(
                delete=False, 
                suffix=Path(file.filename).suffix
            ) as tmp_file:
                content = await file.read()
                tmp_file.write(content)
                tmp_file_path = tmp_file.name
            
            try:
                pipeline = get_pipeline()
                
                # Override chunker settings
                pipeline.chunker.max_chunk_size = chunk_size
                pipeline.chunker.overlap = chunk_overlap
                
                # Add ingestion parameters to metadata
                file_metadata = base_metadata.copy()
                file_metadata.update({
                    "ingestion_parameters": {
                        "preserve_sections": effective_preserve,
                        "chunk_size": chunk_size,
                        "chunk_overlap": chunk_overlap,
                        "model": model_name
                    },
                    "original_filename": file.filename
                })
                
                # Process document
                result = pipeline.ingest_legal_file(
                    file_path=tmp_file_path,
                    collection_name=collection_name,
                    force_recreate=should_recreate,
                    model_name=model_name,
                    provided_metadata=file_metadata
                )
                
                # Only recreate for the first file if multiple files are uploaded
                should_recreate = False
                
                results.append({
                    "filename": file.filename,
                    "status": "success",
                    "document_info": result.get("document_info", {}),
                    "points_count": result.get("points_count", 0)
                })
                
            finally:
                if os.path.exists(tmp_file_path):
                    os.unlink(tmp_file_path)
                    
        except Exception as e:
            logger.error(f"Error ingesting file {file.filename}: {e}")
            results.append({
                "filename": file.filename,
                "status": "error",
                "error": str(e)
            })

    return {
        "status": "completed",
        "total_files": total_files,
        "successful": len([r for r in results if r["status"] == "success"]),
        "failed": len([r for r in results if r["status"] == "error"]),
        "results": results
    }

@router.post("/ingest-legal-folder")
async def ingest_legal_folder(
    request: FolderIngestionRequest
) -> Dict[str, Any]:
    """Ingest all legal documents from a local folder path"""
    path = Path(request.folder_path)
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=400, detail=f"Invalid folder path: {request.folder_path}")
    
    # Supported extensions
    extensions = ['.doc', '.docx', '.pdf', '.txt']
    files_to_process = []
    
    if request.recursive:
        for ext in extensions:
            files_to_process.extend(list(path.rglob(f"*{ext}")))
    else:
        for ext in extensions:
            files_to_process.extend(list(path.glob(f"*{ext}")))
            
    if not files_to_process:
        return {"status": "no_files_found", "path": request.folder_path}

    results = []
    pipeline = get_pipeline()
    pipeline.chunker.max_chunk_size = request.chunk_size
    pipeline.chunker.overlap = request.chunk_overlap
    
    base_metadata = {}
    if request.metadata_json:
        try:
            base_metadata = json.loads(request.metadata_json)
        except Exception as e:
            logger.warning(f"Failed to parse metadata: {e}")

    should_recreate = request.force_recreate
    # Use enhanced if preserve_sections is default
    effective_preserve = request.preserve_sections if request.preserve_sections is not True else request.enhanced
    
    for i, file_path in enumerate(files_to_process):
        try:
            logger.info(f"Processing folder file {i+1}/{len(files_to_process)}: {file_path.name}")
            
            file_metadata = base_metadata.copy()
            file_metadata.update({
                "ingestion_parameters": {
                    "preserve_sections": effective_preserve,
                    "chunk_size": request.chunk_size,
                    "chunk_overlap": request.chunk_overlap,
                    "model": request.model_name
                },
                "original_filename": file_path.name,
                "source_folder": request.folder_path
            })
            
            result = pipeline.ingest_legal_file(
                file_path=str(file_path),
                collection_name=request.collection_name,
                force_recreate=should_recreate,
                model_name=request.model_name,
                provided_metadata=file_metadata
            )
            
            should_recreate = False
            
            results.append({
                "filename": file_path.name,
                "status": "success",
                "document_info": result.get("document_info", {}),
                "points_count": result.get("points_count", 0)
            })
        except Exception as e:
            logger.error(f"Error ingesting folder file {file_path.name}: {e}")
            results.append({
                "filename": file_path.name,
                "status": "error",
                "error": str(e)
            })

    return {
        "status": "completed",
        "total_processed": len(files_to_process),
        "successful": len([r for r in results if r["status"] == "success"]),
        "failed": len([r for r in results if r["status"] == "error"]),
        "results": results
    }

@router.post("/analyze-document-structure")
async def analyze_document_structure(
    file: UploadFile = File(...)
) -> Dict[str, Any]:
    """Analyze document structure without ingestion"""
    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=Path(file.filename).suffix
        ) as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_file_path = tmp_file.name
        
        try:
            pipeline = get_pipeline()
            text = pipeline.extract_text_from_doc(tmp_file_path)
            sections = pipeline.extractor.extract_sections(text)
            metadata = pipeline.extractor.extract_metadata_from_text(text)
            
            return {
                "filename": file.filename,
                "total_sections": len(sections),
                "sections": [
                    {
                        "type": section.section_type.value,
                        "title": section.title,
                        "line_range": f"{section.line_start}-{section.line_end}",
                        "content_preview": section.content[:200] + "..." if len(section.content) > 200 else section.content
                    }
                    for section in sections
                ],
                "metadata_extracted": metadata,
                "suggested_chunking": {
                    "recommended_chunk_size": 1500,
                    "sections_to_keep_intact": [
                        s.section_type.value for s in sections 
                        if len(s.content) <= 2000
                    ],
                    "estimated_chunks": sum(
                        1 if len(s.content) <= 1500 else max(1, len(s.content) // 1000)
                        for s in sections
                    )
                }
            }
        finally:
            if os.path.exists(tmp_file_path):
                os.unlink(tmp_file_path)
            
    except Exception as e:
        logger.error(f"Error analyzing document: {e}")
        raise HTTPException(status_code=500, detail=str(e))
