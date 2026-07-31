import logging
import time
import hashlib
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime

from .document_processor import DocumentProcessor, DocumentChunk
from .embedding_generator import EmbeddingGenerator
from .vector_store import VectorStore
from .transcript_processor import TranscriptProcessor
from .legal_document_processor import (
    LegalDocumentExtractor, 
    LegalDocumentChunker, 
    LegalSectionType
)

logger = logging.getLogger(__name__)

class IngestionPipeline:
    """Main pipeline for document ingestion into vector database."""
    
    def __init__(
        self,
        qdrant_url: Optional[str] = None,
        qdrant_host: str = "localhost",
        qdrant_port: int = 6333,
        qdrant_api_key: Optional[str] = None,
        embedding_model: str = "all-MiniLM-L6-v2",
        chunk_size: int = 1000,
        chunk_overlap: int = 200
    ):
        """Initialize the ingestion pipeline."""
        self.processor = DocumentProcessor(chunk_size, chunk_overlap)
        self.embedding_generator = EmbeddingGenerator(embedding_model)
        # Pass explicit qdrant_url (if present) so VectorStore uses it instead of host/port
        self.vector_store = VectorStore(qdrant_host, qdrant_port, qdrant_api_key, qdrant_url)
        
        # Legal-specific components
        self.extractor = LegalDocumentExtractor()
        self.chunker = LegalDocumentChunker(max_chunk_size=1500, overlap=150)
        
        # Transcript-specific components
        self.transcript_processor = TranscriptProcessor(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            preserve_speaker_turns=True
        )
    
    def _embedding_generator_for(self, collection_name: str) -> EmbeddingGenerator:
        """Return an EmbeddingGenerator matching the target collection's vector dimension."""
        target_size = self.vector_store.get_collection_vector_size(collection_name)
        if target_size is None:
            return self.embedding_generator
        if target_size == self.embedding_generator.get_embedding_dimension():
            return self.embedding_generator
        try:
            return EmbeddingGenerator.for_dimension(target_size)
        except ValueError:
            logger.warning(f"No embedding model for dimension {target_size}; using default")
            return self.embedding_generator

    def ingest_directory(
        self,
        directory_path: str,
        collection_name: str,
        force_recreate: bool = False,
        exclude_dirs: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Complete ingestion pipeline for a directory."""
        start_time = time.time()

        logger.info(f"Starting ingestion pipeline for: {directory_path}")

        # Step 1: Create collection (match the target collection's dimension if it exists)
        generator = self._embedding_generator_for(collection_name)
        vector_size = generator.get_embedding_dimension()
        if not self.vector_store.create_collection(collection_name, vector_size, force_recreate):
            return {"success": False, "error": "Failed to create collection"}

        # Step 2: Process documents
        chunks = self.processor.process_directory(directory_path, exclude_dirs)

        if not chunks:
            logger.warning("No chunks created from directory")
            return {"success": False, "error": "No documents processed"}

        # Step 3: Generate embeddings
        embeddings = generator.generate_embeddings(chunks)
        
        # Step 4: Ingest to vector store
        success = self.vector_store.ingest_documents(collection_name, chunks, embeddings)
        
        # Compile statistics
        execution_time = time.time() - start_time
        
        stats = {
            "success": success,
            "total_chunks": len(chunks),
            "total_embeddings": len(embeddings),
            "execution_time_seconds": round(execution_time, 2),
            "chunks_per_second": round(len(chunks) / execution_time, 2) if execution_time > 0 else 0,
            "collection_name": collection_name,
            "directory_path": directory_path
        }
        
        logger.info(f"Ingestion completed. Stats: {stats}")
        return stats
    
    def ingest_file(
        self,
        file_path: str,
        collection_name: str,
        force_recreate: bool = False
    ) -> Dict[str, Any]:
        """Ingest a single file."""
        start_time = time.time()

        logger.info(f"Starting file ingestion for: {file_path}")

        # Step 1: Create collection (match the target collection's dimension if it exists)
        generator = self._embedding_generator_for(collection_name)
        vector_size = generator.get_embedding_dimension()
        if not self.vector_store.create_collection(collection_name, vector_size, force_recreate):
            return {"success": False, "error": "Failed to create collection"}

        # Step 2: Process file
        chunks = self.processor.process_file(file_path)

        if not chunks:
            return {"success": False, "error": "No content extracted from file"}

        # Step 3: Generate embeddings
        embeddings = generator.generate_embeddings(chunks)
        
        # Step 4: Ingest to vector store
        success = self.vector_store.ingest_documents(collection_name, chunks, embeddings)
        
        execution_time = time.time() - start_time
        
        stats = {
            "success": success,
            "total_chunks": len(chunks),
            "execution_time_seconds": round(execution_time, 2),
            "collection_name": collection_name,
            "file_path": file_path
        }
        
        return stats

    def ingest_legal_file(
        self,
        file_path: str,
        collection_name: str,
        force_recreate: bool = False,
        model_name: Optional[str] = None,
        provided_metadata: Optional[Dict[str, Any]] = None,
        enhanced: bool = True
    ) -> Dict[str, Any]:
        """Ingest a legal DOC/DOCX file with legal-aware defaults.
        
        If enhanced=True, uses section-aware extraction and chunking.
        """
        if not enhanced:
            # Fallback to basic legal ingestion if requested
            return self._ingest_legal_file_basic(file_path, collection_name, force_recreate, model_name, provided_metadata)
            
        start_time = time.time()
        logger.info(f"Starting enhanced legal file ingestion for: {file_path}")

        # 1. Extract raw text using DocumentProcessor's robust methods
        text = self.processor.read_file_content(file_path)
        if not text:
            return {"success": False, "error": "No content extracted from file"}

        # 2. Extract metadata and sections
        extracted_metadata = self.extractor.extract_metadata_from_text(text)
        sections = self.extractor.extract_sections(text)
        logger.info(f"Extracted {len(sections)} sections from {file_path}")

        # 3. Prepare document metadata
        doc_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        doc_metadata = {
            **(provided_metadata or {}),
            **extracted_metadata,
            "document_hash": doc_hash,
            "total_sections": len(sections),
            "ingestion_timestamp": datetime.now().isoformat(),
            "file_name": Path(file_path).name,
            "source": "garage_legal_enhanced"
        }

        # 4. Chunk document with section preservation
        chunks_data = self.chunker.chunk_document(sections, doc_metadata)
        
        # Convert to DocumentChunk objects for compatibility with existing pipeline
        chunks = []
        for i, cdata in enumerate(chunks_data):
            chunks.append(DocumentChunk(
                text=cdata["text"],
                metadata=cdata["metadata"],
                chunk_id=f"{doc_hash}_{i}",
                chunk_index=i,
                total_chunks=len(chunks_data)
            ))

        # 5. Generate embeddings
        if model_name:
            from .embedding_generator import EmbeddingGenerator
            generator = EmbeddingGenerator(model_name)
        else:
            generator = self.embedding_generator

        vector_size = generator.get_embedding_dimension()
        
        # 6. Create optimized collection
        if not self.vector_store.create_optimized_legal_collection(collection_name, vector_size, force_recreate):
            return {"success": False, "error": "Failed to create optimized collection"}

        # 7. Generate embeddings and ingest
        embeddings = generator.generate_embeddings(chunks)
        success = self.vector_store.ingest_documents(collection_name, chunks, embeddings)

        execution_time = time.time() - start_time
        stats = {
            "success": success,
            "status": "success" if success else "failed",
            "document_info": {
                "filename": Path(file_path).name,
                "document_hash": doc_hash,
                "total_sections": len(sections),
                "total_chunks": len(chunks),
                "metadata_extracted": {
                    k: v for k, v in doc_metadata.items() 
                    if k in ["document_type", "processo_numero", "tribunal", "comarca", "relator"]
                }
            },
            "ingestion_stats": {
                "points_uploaded": len(chunks),
                "execution_time_seconds": round(execution_time, 2),
                "collection": collection_name,
                "embedding_model": model_name or generator.model_name,
                "timestamp": datetime.now().isoformat()
            }
        }
        logger.info(f"Enhanced legal ingestion finished: {stats}")
        return stats

    def _ingest_legal_file_basic(
        self,
        file_path: str,
        collection_name: str,
        force_recreate: bool = False,
        model_name: Optional[str] = None,
        provided_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Basic legal ingestion (original implementation)."""
        start_time = time.time()
        logger.info(f"Starting basic legal file ingestion for: {file_path}")

        # Use specialized embedding model if provided
        if model_name:
            from .embedding_generator import EmbeddingGenerator
            generator = EmbeddingGenerator(model_name)
        else:
            generator = self.embedding_generator

        vector_size = generator.get_embedding_dimension()
        if not self.vector_store.create_collection(collection_name, vector_size, force_recreate):
            return {"success": False, "error": "Failed to create collection"}

        # Process file
        chunks = self.processor.process_file(file_path)
        if not chunks:
            return {"success": False, "error": "No content extracted from file"}

        # Attach provided metadata to all chunks
        if provided_metadata:
            for chunk in chunks:
                chunk.metadata.update(provided_metadata)

        # Attempt to extract light metadata (case number, year) from filename or first lines
        try:
            first_text = (chunks[0].text[:1000] if chunks else '')
            import re
            case_match = re.search(r'\bN[\u00baº]?\s*(\d{6,20})\b', first_text)
            year_match = re.search(r'\b(19|20)\d{2}\b', first_text)
            if case_match:
                for chunk in chunks:
                    chunk.metadata.setdefault('case_number', case_match.group(1))
            if year_match:
                for chunk in chunks:
                    chunk.metadata.setdefault('year', int(year_match.group(0)))
        except Exception:
            pass

        # Generate embeddings using the chosen generator
        embeddings = generator.generate_embeddings(chunks)

        # Ingest to vector store
        success = self.vector_store.ingest_documents(collection_name, chunks, embeddings)

        execution_time = time.time() - start_time
        stats = {
            "success": success,
            "total_chunks": len(chunks),
            "execution_time_seconds": round(execution_time, 2),
            "collection_name": collection_name,
            "file_path": file_path
        }
        logger.info(f"Basic legal ingestion finished: {stats}")
        return stats

    def analyze_document_structure(self, file_path: str) -> Dict[str, Any]:
        """Analyze document structure without ingestion."""
        text = self.processor.read_file_content(file_path)
        if not text:
            return {"error": "No content extracted from file"}
            
        sections = self.extractor.extract_sections(text)
        metadata = self.extractor.extract_metadata_from_text(text)
        
        return {
            "filename": Path(file_path).name,
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
                "recommended_chunk_size": self.chunker.max_chunk_size,
                "sections_to_keep_intact": [
                    s.section_type.value for s in sections 
                    if len(s.content) <= self.chunker.max_chunk_size * 1.5
                ],
                "estimated_chunks": sum(
                    1 if len(s.content) <= self.chunker.max_chunk_size else max(1, len(s.content) // self.chunker.max_chunk_size)
                    for s in sections
                )
            }
        }
    
    def search_collection(
        self, 
        collection_name: str, 
        query_text: str, 
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Search for documents similar to query."""
        # Generate embedding for query
        query_embedding = self.embedding_generator.model.encode([query_text])[0]
        
        # Search vector store
        results = self.vector_store.search(
            collection_name=collection_name,
            query_vector=query_embedding,
            limit=limit
        )
        
        return results