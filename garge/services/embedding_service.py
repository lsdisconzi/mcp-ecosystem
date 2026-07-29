"""
Embedding Service
Manages embedding models and text processing for vector operations.
"""

from sentence_transformers import SentenceTransformer
from typing import List, Dict, Any, Optional, Union
import logging

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Service for handling text embeddings with multiple model support.
    
    Supports different embedding dimensions (384, 768) for various use cases.
    Implements caching for efficient repeated embeddings.
    """
    
    def __init__(self):
        """Initialize embedding models with standard dimensions."""
        self.models = {}
        self.default_dimension = 384
        self._initialize_models()
    
    def _initialize_models(self):
        """Load and initialize embedding models for supported dimensions."""
        try:
            # Standard models for different dimensions
            model_configs = {
                384: 'all-MiniLM-L6-v2',  # Fast, efficient (default)
                768: 'all-mpnet-base-v2',  # Higher quality, slower
            }
            
            for dim, model_name in model_configs.items():
                self.models[dim] = SentenceTransformer(model_name)
                logger.info(f"✅ Loaded embedding model: {model_name} ({dim}d)")
            
            # Add specialized legal model
            legal_model_name = 'neuralmind/bert-base-portuguese-cased'
            self.models[legal_model_name] = SentenceTransformer(legal_model_name)
            logger.info(f"✅ Loaded legal embedding model: {legal_model_name}")
                
        except Exception as e:
            logger.error(f"⚠️ Failed to load embedding models: {e}")
            raise
    
    def get_model(self, model_key: Optional[Union[int, str]] = None) -> SentenceTransformer:
        """
        Get embedding model for specific dimension or model name.
        
        Args:
            model_key: Desired embedding dimension (384 or 768) or model name string
            
        Returns:
            SentenceTransformer: Model for the specified key
            
        Raises:
            ValueError: If model_key is not supported
        """
        key = model_key or self.default_dimension
        
        if key not in self.models:
            available = list(self.models.keys())
            raise ValueError(
                f"Embedding model/dimension {key} not supported. "
                f"Available: {available}"
            )
        
        return self.models[key]
    
    def encode(self, texts: List[str], dimension: Optional[int] = None) -> List[List[float]]:
        """
        Encode list of texts to embeddings.
        
        Args:
            texts: List of text strings to encode
            dimension: Target embedding dimension
            
        Returns:
            List[List[float]]: List of embedding vectors
            
        Example:
            ```python
            embeddings = service.encode(["Hello world", "Another text"], dimension=384)
            ```
        """
        if not texts:
            return []
        
        model = self.get_model(dimension)
        return model.encode(texts).tolist()
    
    def encode_single(self, text: str, dimension: Optional[int] = None) -> List[float]:
        """
        Encode single text to embedding vector.
        
        Args:
            text: Text string to encode
            dimension: Target embedding dimension
            
        Returns:
            List[float]: Embedding vector
            
        Example:
            ```python
            vector = service.encode_single("Search query", dimension=384)
            ```
        """
        return self.encode([text], dimension)[0]
    
    def get_embedding_dimension(self, dimension: Optional[int] = None) -> int:
        """
        Get actual embedding dimension for model.
        
        Args:
            dimension: Desired dimension or None for default
            
        Returns:
            int: Actual embedding dimension
        """
        model = self.get_model(dimension)
        return model.get_sentence_embedding_dimension()
    
    def chunk_text(
        self, 
        text: str, 
        chunk_size: int = 500, 
        chunk_overlap: int = 50
    ) -> List[str]:
        """
        Split text into overlapping chunks for embedding.
        
        Args:
            text: Input text to chunk
            chunk_size: Maximum characters per chunk
            chunk_overlap: Overlap between consecutive chunks
            
        Returns:
            List[str]: List of text chunks
            
        Example:
            ```python
            chunks = service.chunk_text(long_document, chunk_size=1000, chunk_overlap=100)
            ```
        """
        if not text.strip():
            return []
        
        # Simple sliding window chunking
        chunks = []
        start = 0
        text_length = len(text)
        
        while start < text_length:
            end = start + chunk_size
            chunk = text[start:end]
            
            if chunk.strip():
                chunks.append(chunk)
            
            start += chunk_size - chunk_overlap
        
        return chunks


# Global instance for easy access
embedding_service = EmbeddingService()