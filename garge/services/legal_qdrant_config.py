# qdrant_config.py
from qdrant_client import QdrantClient
from qdrant_client.http import models
from sentence_transformers import SentenceTransformer
import os
import logging

logger = logging.getLogger(__name__)

class LegalDocumentVectorStore:
    """Optimized Qdrant store for legal documents"""
    
    def __init__(self, host="localhost", port=6333, url=None, api_key=None):
        if url:
            self.client = QdrantClient(url=url, api_key=api_key)
        else:
            self.client = QdrantClient(host=host, port=port, api_key=api_key)
            
        self.embedding_model = SentenceTransformer(
            "neuralmind/bert-base-portuguese-cased"
        )
        
    def create_optimized_collection(self, collection_name: str):
        """Create collection with optimized settings for legal docs"""
        
        # Delete if exists
        try:
            self.client.delete_collection(collection_name)
        except Exception as e:
            logger.debug(f"Collection {collection_name} delete failed (might not exist): {e}")
        
        # Create with optimized configuration
        self.client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=768,  # BERT base size
                distance=models.Distance.COSINE,
                on_disk=True  # For large collections
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
        
        return collection_name
