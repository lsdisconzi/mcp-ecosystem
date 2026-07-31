import logging
import time
import numpy as np
import os
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.models import PointStruct, VectorParams, Distance
from .document_processor import DocumentChunk

# Import Qdrant connection error from wrapper to unify error handling
try:
    from core.qdrant_client import QdrantConnectionError
except Exception:
    # Fallback if wrapper is not available in some contexts
    QdrantConnectionError = RuntimeError

logger = logging.getLogger(__name__)

class VectorStore:
    """Handles Qdrant vector store operations."""

    def __init__(self, host: str = "localhost", port: int = 6333, api_key: Optional[str] = None, qdrant_url: Optional[str] = None):
        self.host = host
        self.port = port
        self.api_key = api_key

        # Prefer explicit qdrant_url argument, then environment variable
        qdrant_url_effective = qdrant_url or os.getenv("QDRANT_URL")
        qdrant_api_key_env = os.getenv("QDRANT_API_KEY")

        try:
            if qdrant_url_effective:
                logger.info(f"Initializing Qdrant client with URL: {qdrant_url_effective}")
                self.client = QdrantClient(url=qdrant_url_effective, api_key=qdrant_api_key_env or api_key, timeout=30)
                self._conn_desc = f"url={qdrant_url_effective}"
            else:
                logger.info(f"Initializing Qdrant client at {host}:{port}")
                self.client = QdrantClient(host=host, port=port, api_key=api_key)
                self._conn_desc = f"host={host},port={port}"

            # Validate connection
            try:
                self.client.get_collections()
            except Exception as e:
                logger.error(f"Failed to validate Qdrant connection ({self._conn_desc}): {e}")
                raise QdrantConnectionError(f"Failed to connect to Qdrant ({self._conn_desc}): {e}")

        except QdrantConnectionError:
            raise
        except Exception as e:
            logger.error(f"Error initializing Qdrant client ({getattr(self, '_conn_desc', 'unknown')}): {e}")
            raise QdrantConnectionError(str(e))
    
    def get_collection_vector_size(self, collection_name: str) -> Optional[int]:
        """Return the vector size of an existing collection, or None if it does not exist."""
        try:
            info = self.client.get_collection(collection_name)
            vectors = info.config.params.vectors
            return getattr(vectors, "size", None)
        except Exception:
            return None

    def create_collection(self, collection_name: str, vector_size: int, force_recreate: bool = False) -> bool:
        """Create or recreate collection in Qdrant."""
        try:
            collections = self.client.get_collections().collections
            collection_exists = any(c.name == collection_name for c in collections)
            
            if collection_exists:
                if force_recreate:
                    logger.info(f"Deleting existing collection: {collection_name}")
                    self.client.delete_collection(collection_name)
                else:
                    logger.info(f"Collection {collection_name} already exists")
                    return True
            
            logger.info(f"Creating collection: {collection_name}")
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=Distance.COSINE
                )
            )
            
            time.sleep(1)  # Wait for collection to be ready
            return True
            
        except Exception as e:
            logger.error(f"Failed to create collection: {e}")
            return False

    def create_optimized_legal_collection(self, collection_name: str, vector_size: int, force_recreate: bool = False) -> bool:
        """Create collection with optimized settings for legal docs."""
        try:
            collections = self.client.get_collections().collections
            collection_exists = any(c.name == collection_name for c in collections)
            
            if collection_exists:
                if force_recreate:
                    logger.info(f"Deleting existing collection: {collection_name}")
                    self.client.delete_collection(collection_name)
                else:
                    logger.info(f"Collection {collection_name} already exists")
                    return True
            
            logger.info(f"Creating optimized legal collection: {collection_name}")
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                    on_disk=True
                ),
                optimizers_config=models.OptimizersConfigDiff(
                    indexing_threshold=10000,
                    memmap_threshold=20000,
                    default_segment_number=4,
                    max_segment_size=50000
                ),
                hnsw_config=models.HnswConfigDiff(
                    m=16,
                    ef_construct=100,
                    full_scan_threshold=10000
                ),
                quantization_config=models.ScalarQuantization(
                    scalar=models.ScalarQuantizationConfig(
                        type=models.ScalarType.INT8,
                        quantile=0.99,
                        always_ram=True
                    )
                )
            )
            
            # Create payload indexes for common queries
            payload_indexes = [
                ("section_type", models.PayloadSchemaType.KEYWORD),
                ("document_type", models.PayloadSchemaType.KEYWORD),
                ("tribunal", models.PayloadSchemaType.KEYWORD),
                ("comarca", models.PayloadSchemaType.KEYWORD),
                ("processo_numero", models.PayloadSchemaType.KEYWORD),
                ("cnj_number", models.PayloadSchemaType.KEYWORD),
                ("data", models.PayloadSchemaType.DATETIME),
                ("relator", models.PayloadSchemaType.KEYWORD),
                ("has_acordao", models.PayloadSchemaType.BOOL),
                ("chunk_sequence", models.PayloadSchemaType.INTEGER),
                ("is_complete_section", models.PayloadSchemaType.BOOL)
            ]
            
            for field_name, schema_type in payload_indexes:
                try:
                    self.client.create_payload_index(
                        collection_name=collection_name,
                        field_name=field_name,
                        field_schema=schema_type
                    )
                except Exception as e:
                    logger.warning(f"Failed to create index for {field_name}: {e}")
            
            # Create text index for full-text search within chunks
            try:
                self.client.create_payload_index(
                    collection_name=collection_name,
                    field_name="text",
                    field_schema=models.TextIndexParams(
                        type=models.TextIndexType.TEXT,
                        tokenizer=models.TokenizerType.WORD,
                        min_token_len=2,
                        max_token_len=20,
                        lowercase=True
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to create text index: {e}")

            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"Failed to create optimized collection: {e}")
            return False

    def create_optimized_transcript_collection(self, collection_name: str, vector_size: int, force_recreate: bool = False) -> bool:
        """Create collection with optimized settings for transcript data."""
        try:
            collections = self.client.get_collections().collections
            collection_exists = any(c.name == collection_name for c in collections)
            
            if collection_exists:
                if force_recreate:
                    logger.info(f"Deleting existing collection: {collection_name}")
                    self.client.delete_collection(collection_name)
                else:
                    logger.info(f"Collection {collection_name} already exists")
                    return True
            
            logger.info(f"Creating optimized transcript collection: {collection_name}")
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                    on_disk=True
                ),
                optimizers_config=models.OptimizersConfigDiff(
                    indexing_threshold=10000,
                    memmap_threshold=20000,
                    default_segment_number=4,
                    max_segment_size=50000
                ),
                hnsw_config=models.HnswConfigDiff(
                    m=16,
                    ef_construct=100,
                    full_scan_threshold=10000
                )
            )
            
            # Create payload indexes for transcript queries
            payload_indexes = [
                ("speaker", models.PayloadSchemaType.KEYWORD),
                ("speaker_role", models.PayloadSchemaType.KEYWORD),
                ("speaker_roles", models.PayloadSchemaType.KEYWORD),
                ("recording_date", models.PayloadSchemaType.DATETIME),
                ("location", models.PayloadSchemaType.KEYWORD),
                ("start_time", models.PayloadSchemaType.FLOAT),
                ("end_time", models.PayloadSchemaType.FLOAT),
                ("duration", models.PayloadSchemaType.FLOAT),
                ("utterance_count", models.PayloadSchemaType.INTEGER),
                ("chunk_index", models.PayloadSchemaType.INTEGER),
                ("total_chunks", models.PayloadSchemaType.INTEGER),
                ("transcript_id", models.PayloadSchemaType.KEYWORD),
                ("transcript_hash", models.PayloadSchemaType.KEYWORD),
                ("source", models.PayloadSchemaType.KEYWORD)
            ]
            
            for field_name, schema_type in payload_indexes:
                try:
                    self.client.create_payload_index(
                        collection_name=collection_name,
                        field_name=field_name,
                        field_schema=schema_type
                    )
                except Exception as e:
                    logger.warning(f"Failed to create index for {field_name}: {e}")
            
            # Create text index for content search
            try:
                self.client.create_payload_index(
                    collection_name=collection_name,
                    field_name="text",
                    field_schema=models.TextIndexParams(
                        type=models.TextIndexType.TEXT,
                        tokenizer=models.TokenizerType.WORD,
                        min_token_len=2,
                        max_token_len=20,
                        lowercase=True
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to create text index: {e}")

            time.sleep(1)
            logger.info(f"Transcript collection '{collection_name}' created successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to create transcript collection: {e}")
            return False
    
    def ingest_documents(
        self, 
        collection_name: str, 
        chunks: List[DocumentChunk], 
        embeddings: List[np.ndarray],
        batch_size: int = 100
    ) -> bool:
        """Ingest document chunks and embeddings into Qdrant."""
        if len(chunks) != len(embeddings):
            logger.error(f"Mismatch between chunks ({len(chunks)}) and embeddings ({len(embeddings)})")
            return False
        
        try:
            points = []
            
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                point = PointStruct(
                    id=i,
                    vector=embedding.tolist(),
                    payload={
                        'text': chunk.text,
                        'chunk_id': chunk.chunk_id,
                        'chunk_index': chunk.chunk_index,
                        'total_chunks': chunk.total_chunks,
                        **chunk.metadata
                    }
                )
                points.append(point)
            
            # Upload in batches
            for i in range(0, len(points), batch_size):
                batch = points[i:i+batch_size]
                self.client.upsert(
                    collection_name=collection_name,
                    points=batch
                )
                logger.info(f"Uploaded batch {i//batch_size + 1}/{(len(points) + batch_size - 1)//batch_size}")
            
            logger.info(f"Successfully ingested {len(points)} points into Qdrant")
            return True
            
        except Exception as e:
            logger.error(f"Failed to ingest to Qdrant: {e}")
            return False
    
    def search(
        self, 
        collection_name: str, 
        query_vector: np.ndarray, 
        limit: int = 10,
        score_threshold: float = 0.5
    ) -> List[Dict[str, Any]]:
        """Search for similar documents."""
        try:
            resp = self.client.query_points(
                collection_name=collection_name,
                query=query_vector.tolist(),
                limit=limit,
                score_threshold=score_threshold,
                with_payload=True,
            )

            return [
                {
                    "id": result.id,
                    "score": result.score,
                    "text": (result.payload or {}).get("text", ""),
                    "metadata": {k: v for k, v in (result.payload or {}).items() if k != "text"}
                }
                for result in resp.points
            ]
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
    
    def get_collection_info(self, collection_name: str) -> Dict[str, Any]:
        """Get information about the collection."""
        try:
            info = self.client.get_collection(collection_name)

            return {
                "name": collection_name,
                "points_count": getattr(info, "points_count", None),
                "vector_size": getattr(getattr(getattr(info, "config", None), "params", None), "vectors", None) and getattr(getattr(getattr(info, "config", None), "params", None).vectors, "size", None),
                "distance_metric": (str(getattr(getattr(getattr(info, "config", None), "params", None).vectors, "distance", "")).split('.')[-1].lower() if getattr(getattr(getattr(info, "config", None), "params", None), "vectors", None) else None),
                "config": info.config.dict() if hasattr(info, "config") and hasattr(info.config, "dict") else str(getattr(info, "config", None))
            }
        except Exception as e:
            # If it's a connection problem, raise a specific error so callers
            # can return a 503 Service Unavailable instead of a generic 500.
            if isinstance(e, QdrantConnectionError) or 'Connection refused' in str(e):
                logger.error(f"Failed to get collection info due to connection error: {e}")
                raise QdrantConnectionError(str(e))

            logger.error(f"Failed to get collection info: {e}")
            return {}