"""
Legal Document Ingestor for Qdrant Vector Database
Handles complete ingestion pipeline from CSV to Qdrant with chunking and embeddings.
"""
import os
import re
import logging
import hashlib
from typing import List, Dict, Any, Optional
from datetime import datetime
import pandas as pd
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, FieldCondition, Filter, MatchValue
from sentence_transformers import SentenceTransformer


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
            # Prefer paragraph splits, fallback to greedy character chunks
            parts = [p.strip() for p in text.split('\n\n') if p.strip()]
            if not parts:
                parts = [text]
            chunks = []
            for part in parts:
                start = 0
                while start < len(part):
                    end = start + self.chunk_size
                    chunks.append(part[start:end])
                    # advance preserving overlap but avoid infinite loop
                    advance = self.chunk_size - self.chunk_overlap
                    if advance <= 0:
                        break
                    start += advance
            return chunks

    class RecursiveCharacterTextSplitter(CharacterTextSplitter):
        # Behavior compatible with LangChain's splitter for our use-case
        pass

# CSV processor / cleaner used elsewhere in this module
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


class LegalDocumentIngestor:
    """
    Main ingestion pipeline for legal documents into Qdrant.
    Handles CSV loading, text processing, chunking, embedding, and vector storage.
    """
    
    def __init__(
        self,
        qdrant_url: str = "localhost",
        qdrant_port: int = 6333,
        qdrant_api_key: Optional[str] = None,
        model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        chunk_size: int = 800,
        chunk_overlap: int = 100
    ):
        """
        Initialize the legal document ingestor.
        
        Args:
            qdrant_url: Qdrant server URL
            qdrant_port: Qdrant server port
            qdrant_api_key: API key for Qdrant Cloud (optional)
            model_name: Sentence transformer model name (Portuguese-optimized recommended)
            chunk_size: Size of text chunks
            chunk_overlap: Overlap between chunks
        """
        # Initialize Qdrant client
        if qdrant_api_key:
            self.client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
        else:
            self.client = QdrantClient(host=qdrant_url, port=qdrant_port)
        
        logger.info("Qdrant client initialized")
        
        # Initialize embedding model
        logger.info(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        self.embedding_dimension = self.model.get_sentence_embedding_dimension()
        logger.info(f"Model loaded. Embedding dimension: {self.embedding_dimension}")
        
        # Initialize processors
        self.csv_processor = LegalCSVProcessor()
        self.chunker = LegalDocumentChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )
    
    def create_collection(
        self,
        collection_name: str,
        recreate: bool = False,
        distance_metric: Distance = Distance.COSINE
    ):
        """
        Create or recreate a Qdrant collection.
        
        Args:
            collection_name: Name of the collection
            recreate: If True, delete existing collection and create new one
            distance_metric: Vector distance metric to use
        """
        try:
            if recreate:
                logger.info(f"Deleting existing collection: {collection_name}")
                try:
                    self.client.delete_collection(collection_name=collection_name)
                except Exception as e:
                    logger.debug(f"Collection didn't exist or couldn't be deleted: {e}")
            
            logger.info(f"Creating collection: {collection_name}")
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=self.embedding_dimension,
                    distance=distance_metric
                )
            )
            
            # Create payload indexes for common filters
            self.create_payload_indexes(collection_name)
            
            logger.info(f"Collection '{collection_name}' created successfully")
            
        except Exception as e:
            logger.error(f"Error creating collection: {e}")
            raise
    
    def create_payload_indexes(self, collection_name: str):
        """
        Create indexes on payload fields for faster filtering.
        
        Args:
            collection_name: Name of the collection
        """
        index_fields = [
            'processo',
            'classe',
            'relator',
            'origem',
            'ano',
            'document_id'
        ]
        
        for field in index_fields:
            try:
                self.client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field,
                    field_schema="keyword"
                )
                logger.debug(f"Created index on field: {field}")
            except Exception as e:
                logger.debug(f"Could not create index on {field}: {e}")
    
    def generate_embeddings(
        self,
        texts: List[str],
        batch_size: int = 32,
        show_progress: bool = True
    ) -> np.ndarray:
        """
        Generate embeddings for a list of texts.
        
        Args:
            texts: List of text strings
            batch_size: Batch size for encoding
            show_progress: Show progress bar
            
        Returns:
            Numpy array of embeddings
        """
        logger.info(f"Generating embeddings for {len(texts)} texts...")
        
        embeddings = []
        try:
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                batch_embeddings = self.model.encode(
                    batch,
                    show_progress_bar=show_progress and i == 0,
                    convert_to_numpy=True
                )
                # Ensure batch_embeddings is iterable of vectors
                if isinstance(batch_embeddings, np.ndarray) and batch_embeddings.ndim == 1 and len(batch_embeddings) > 0:
                    # Single vector returned for one input - wrap it
                    batch_embeddings = np.expand_dims(batch_embeddings, 0)
                embeddings.extend(batch_embeddings)
                
                if show_progress and (i + batch_size) % (batch_size * 10) == 0:
                    logger.info(f"Processed {min(i + batch_size, len(texts))}/{len(texts)} texts")
        except Exception as e:
            logger.error(f"Error generating embeddings: {e}")
            raise
        
        emb_arr = np.array(embeddings)
        logger.info(f"Embeddings generated. shape={getattr(emb_arr, 'shape', None)}, dtype={getattr(emb_arr, 'dtype', None)}")
        # Validate counts
        if emb_arr.ndim == 1:
            # If embeddings collapsed to 1D, reshape to (n, 1)
            emb_arr = emb_arr.reshape(-1, 1)
        if emb_arr.shape[0] != len(texts):
            raise ValueError(f"Embeddings count {emb_arr.shape[0]} does not match texts count {len(texts)}")
        
        return emb_arr
    
    def process_csv_to_chunks(
        self,
        csv_path: str,
        text_column: str = 'texto',
        metadata_columns: Optional[List[str]] = None
    ) -> tuple[List[Dict[str, Any]], pd.DataFrame]:
        """
        Process CSV file into chunks ready for embedding.
        
        Args:
            csv_path: Path to CSV file
            text_column: Column containing document text
            metadata_columns: Columns to include as metadata (None = all columns)
            
        Returns:
            Tuple of (chunks list, processed DataFrame)
        """
        # Load CSV
        df = self.csv_processor.load_csv(csv_path)
        logger.info(f"Loaded {len(df)} documents from CSV")
        
        # Validate required columns
        self.csv_processor.validate_required_columns(df, ['id', text_column])
        
        # Process DataFrame
        df = self.csv_processor.process_dataframe(df, text_column)
        
        # Get statistics
        stats = self.csv_processor.get_statistics(df)
        logger.info(f"Statistics: {stats}")
        
        # Determine metadata columns
        if metadata_columns is None:
            # Exclude the cleaned text column from metadata
            metadata_columns = [col for col in df.columns if col not in ['texto_clean']]
        
        # Chunk documents
        all_chunks = []
        for idx, row in df.iterrows():
            # Prepare metadata
            metadata = {
                'document_id': str(row['id']),
                'source_row': int(idx)
            }
            
            # Add specified metadata columns
            for col in metadata_columns:
                if col not in row:
                    continue
                value = row[col]
                # Skip obvious missing scalars (NaN/None)
                if value is None:
                    continue
                if not isinstance(value, (list, dict, tuple, np.ndarray)) and pd.isna(value):
                    # scalar NaN or NaT
                    continue
                # Convert non-serializable types
                if isinstance(value, (dict, list)):
                    metadata[col] = str(value)
                elif isinstance(value, pd.Timestamp):
                    metadata[col] = value.isoformat()
                else:
                    metadata[col] = value

            # Extract year from date if available
            if 'julgado_em' in row:
                try:
                    value = row['julgado_em']
                    if value is not None and not (not isinstance(value, (list, dict, tuple, np.ndarray)) and pd.isna(value)):
                        date_str = str(value)
                        year_match = re.search(r'(\d{4})', date_str)
                        if year_match:
                            metadata['ano'] = int(year_match.group(1))
                except Exception:
                    pass
            
            # Chunk the document
            doc_chunks = self.chunker.chunk_document(
                text=row['texto_clean'],
                metadata=metadata
            )
            
            all_chunks.extend(doc_chunks)
            
            if (idx + 1) % 100 == 0:
                logger.info(f"Processed {idx + 1}/{len(df)} documents, {len(all_chunks)} chunks so far")
        
        logger.info(f"Total chunks created: {len(all_chunks)}")
        return all_chunks, df
    
    def _to_serializable(self, value: Any) -> Any:
        """Convert numpy types and other non-serializable values to Python primitives."""
        import numpy as _np
        if value is None:
            return None
        if isinstance(value, (_np.integer, )):
            return int(value)
        if isinstance(value, (_np.floating, )):
            return float(value)
        if isinstance(value, _np.ndarray):
            return value.tolist()
        if isinstance(value, (list, tuple)):
            return [self._to_serializable(v) for v in value]
        if isinstance(value, dict):
            return {k: self._to_serializable(v) for k, v in value.items()}
        return value

    def chunks_to_points(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: np.ndarray
    ) -> List[PointStruct]:
        """
        Convert chunks and embeddings to Qdrant points.
        
        Args:
            chunks: List of chunk dictionaries
            embeddings: Array of embeddings
            
        Returns:
            List of PointStruct objects
        """
        points = []
        
        # Validate embeddings shape
        if not hasattr(embeddings, 'shape'):
            raise ValueError("Embeddings must be an array-like with shape (n, dim)")
        if embeddings.shape[0] != len(chunks):
            raise ValueError(f"Number of embeddings ({embeddings.shape[0]}) does not match number of chunks ({len(chunks)})")
        
        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            # Generate unique ID
            unique_string = f"{chunk.get('document_id', '')}_{chunk.get('chunk_index', idx)}_{chunk['text'][:50]}"
            point_id = hashlib.md5(unique_string.encode()).hexdigest()
            
            # Prepare payload
            payload = {
                'text': chunk['text'],
                'chunk_index': int(self._to_serializable(chunk['chunk_index'])),
                'total_chunks': int(self._to_serializable(chunk['total_chunks'])),
                'chunk_size': int(self._to_serializable(chunk['chunk_size'])),
                'tokens': int(self._to_serializable(chunk['tokens'])),
            }
            
            # Add all other metadata
            for key, value in chunk.items():
                if key not in ['text', 'chunk_index', 'total_chunks', 'chunk_size', 'tokens']:
                    payload[key] = self._to_serializable(value)
            
            # Add ingestion timestamp
            payload['ingested_at'] = datetime.now().isoformat()
            
            points.append(
                PointStruct(
                    id=point_id,
                    vector=self._to_serializable(embedding),
                    payload=payload
                )
            )
        
        return points
    
    def ingest_points(
        self,
        collection_name: str,
        points: List[PointStruct],
        batch_size: int = 100
    ):
        """
        Upload points to Qdrant collection in batches.
        
        Args:
            collection_name: Name of the collection
            points: List of PointStruct objects
            batch_size: Number of points per batch
        """
        logger.info(f"Uploading {len(points)} points to collection '{collection_name}'...")
        
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            
            try:
                self.client.upsert(
                    collection_name=collection_name,
                    points=batch
                )
                
                if (i + batch_size) % (batch_size * 10) == 0:
                    logger.info(f"Uploaded {min(i + batch_size, len(points))}/{len(points)} points")
            
            except Exception as e:
                logger.error(f"Error uploading batch {i}-{i + batch_size}: {e}")
                raise
        
        logger.info(f"Successfully uploaded all {len(points)} points")
    
    def ingest_csv(
        self,
        csv_path: str,
        collection_name: str,
        text_column: str = 'texto',
        recreate_collection: bool = False,
        metadata_columns: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Complete ingestion pipeline from CSV to Qdrant.
        
        Args:
            csv_path: Path to CSV file
            collection_name: Name of Qdrant collection
            text_column: Column containing document text
            recreate_collection: Whether to recreate the collection
            metadata_columns: Columns to include as metadata
            
        Returns:
            Dictionary with ingestion statistics
        """
        start_time = datetime.now()
        
        try:
            # Create collection
            self.create_collection(collection_name, recreate=recreate_collection)
            
            # Process CSV to chunks
            chunks, df = self.process_csv_to_chunks(
                csv_path=csv_path,
                text_column=text_column,
                metadata_columns=metadata_columns
            )
            
            # Generate embeddings
            texts = [chunk['text'] for chunk in chunks]
            logger.info(f"Preparing to generate embeddings for {len(texts)} chunks")
            embeddings = self.generate_embeddings(texts)
            logger.info(f"Embeddings shape after generation: {getattr(embeddings, 'shape', None)}")
            
            # Sanity check
            if len(chunks) != embeddings.shape[0]:
                raise ValueError(f"Chunks ({len(chunks)}) and embeddings ({embeddings.shape[0]}) length mismatch")
            
            # Convert to points
            points = self.chunks_to_points(chunks, embeddings)
            logger.info(f"Converted to {len(points)} points")
            
            # Ingest points
            self.ingest_points(collection_name, points)
            
            # Calculate statistics
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            stats = {
                'success': True,
                'collection_name': collection_name,
                'total_documents': len(df),
                'total_chunks': len(chunks),
                'total_points': len(points),
                'embedding_dimension': self.embedding_dimension,
                'duration_seconds': duration,
                'chunks_per_document': len(chunks) / len(df),
                'timestamp': end_time.isoformat()
            }
            
            logger.info(f"Ingestion complete: {stats}")
            return stats
            
        except Exception as e:
            # Log full traceback for easier debugging
            import traceback
            tb = traceback.format_exc()
            logger.exception("Ingestion failed with exception")
            return {
                'success': False,
                'error': str(e),
                'traceback': tb,
                'timestamp': datetime.now().isoformat()
            }
    
    def search(
        self,
        collection_name: str,
        query: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search the collection with a query.
        
        Args:
            collection_name: Name of the collection
            query: Search query text
            limit: Maximum number of results
            filters: Optional filters (e.g., {'classe': 'APELACAO'})
            
        Returns:
            List of search results
        """
        # Generate query embedding
        query_embedding = self.model.encode([query])[0]
        
        # Prepare filter
        qdrant_filter = None
        if filters:
            conditions = []
            for key, value in filters.items():
                conditions.append(
                    FieldCondition(
                        key=key,
                        match=MatchValue(value=value)
                    )
                )
            if conditions:
                qdrant_filter = Filter(must=conditions)
        
        # Search
        results = self.client.search(
            collection_name=collection_name,
            query_vector=query_embedding.tolist(),
            query_filter=qdrant_filter,
            limit=limit
        )
        
        # Format results
        formatted_results = []
        for result in results:
            formatted_results.append({
                'id': result.id,
                'score': result.score,
                'text': result.payload.get('text', ''),
                'metadata': {k: v for k, v in result.payload.items() if k != 'text'}
            })
        
        return formatted_results
