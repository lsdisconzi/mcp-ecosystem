"""
Embedding service for generating vector representations of text.
Uses sentence-transformers for local embedding generation.
"""
import logging
from typing import List, Optional
import numpy as np

logger = logging.getLogger(__name__)

class EmbeddingService:
    """Service for generating text embeddings."""
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize embedding service.
        
        Args:
            model_name: Name of the sentence-transformer model to use
        """
        self.model_name = model_name
        self._model = None
        self._dimension = None
    
    @property
    def model(self):
        """Lazy load the embedding model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info(f"Loading embedding model: {self.model_name}")
                self._model = SentenceTransformer(self.model_name)
                logger.info("Embedding model loaded successfully")
            except ImportError:
                logger.error("sentence-transformers not installed. Install with: pip install sentence-transformers")
                raise
            except Exception as e:
                logger.error(f"Error loading embedding model: {e}")
                raise
        return self._model
    
    @property
    def dimension(self) -> int:
        """Get the dimension of embeddings produced by this model."""
        if self._dimension is None:
            # Get dimension by encoding a test string
            test_embedding = self.embed_text("test")
            self._dimension = len(test_embedding)
        return self._dimension
    
    def embed_text(self, text: str) -> List[float]:
        """
        Generate embedding for a single text string.
        
        Args:
            text: Text to embed
            
        Returns:
            List of floats representing the embedding vector
        """
        try:
            if not text or not text.strip():
                logger.warning("Empty text provided for embedding")
                return [0.0] * self.dimension
            
            embedding = self.model.encode(text, convert_to_numpy=True)
            return embedding.tolist()
            
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            raise
    
    def embed_texts(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """
        Generate embeddings for multiple texts.
        
        Args:
            texts: List of texts to embed
            batch_size: Batch size for processing
            
        Returns:
            List of embedding vectors
        """
        try:
            if not texts:
                return []
            
            embeddings = self.model.encode(
                texts,
                batch_size=batch_size,
                convert_to_numpy=True,
                show_progress_bar=len(texts) > 100
            )
            return embeddings.tolist()
            
        except Exception as e:
            logger.error(f"Error generating batch embeddings: {e}")
            raise
    
    def similarity(self, text1: str, text2: str) -> float:
        """
        Calculate cosine similarity between two texts.
        
        Args:
            text1: First text
            text2: Second text
            
        Returns:
            Similarity score between 0 and 1
        """
        try:
            emb1 = np.array(self.embed_text(text1))
            emb2 = np.array(self.embed_text(text2))
            
            # Cosine similarity
            similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
            return float(similarity)
            
        except Exception as e:
            logger.error(f"Error calculating similarity: {e}")
            raise


# Global instances (per-model cache so 384- and 768-dim paths can coexist)
_embedding_services: Dict[str, "EmbeddingService"] = {}

# Model registry keyed by embedding dimension (must match routes/qdrant_router.py)
EMBEDDING_MODELS_BY_DIM: Dict[int, str] = {
    384: "all-MiniLM-L6-v2",
    768: "all-mpnet-base-v2",
}


def get_embedding_service(model_name: str = "all-MiniLM-L6-v2") -> EmbeddingService:
    """
    Get or create the global embedding service instance (one per model_name).

    Args:
        model_name: Name of the embedding model to use

    Returns:
        EmbeddingService instance
    """
    global _embedding_services

    if model_name not in _embedding_services:
        _embedding_services[model_name] = EmbeddingService(model_name)

    return _embedding_services[model_name]


def get_embedding_service_for_dim(dimension: int) -> EmbeddingService:
    """Return the embedding service whose output dimension matches ``dimension``."""
    model_name = EMBEDDING_MODELS_BY_DIM.get(dimension)
    if model_name is None:
        raise ValueError(
            f"No embedding model registered for dimension {dimension}; "
            f"known dimensions: {sorted(EMBEDDING_MODELS_BY_DIM)}"
        )
    return get_embedding_service(model_name)


def reset_embedding_service():
    """Reset the global embedding services (useful for testing)."""
    global _embedding_services
    _embedding_services = {}