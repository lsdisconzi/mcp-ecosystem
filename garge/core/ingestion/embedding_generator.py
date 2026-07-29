import logging
import numpy as np
from typing import List
from sentence_transformers import SentenceTransformer
from .document_processor import DocumentChunk

logger = logging.getLogger(__name__)

class EmbeddingGenerator:
    """Generates embeddings for document chunks."""
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        logger.info(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        self.embedding_dim = self.model.get_sentence_embedding_dimension()
    
    def generate_embeddings(self, chunks: List[DocumentChunk], batch_size: int = 32) -> List[np.ndarray]:
        """Generate embeddings for text chunks."""
        if not chunks:
            return []
        
        texts = [chunk.text for chunk in chunks]
        logger.info(f"Generating embeddings for {len(texts)} chunks")
        
        all_embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i+batch_size]
            batch_embeddings = self.model.encode(
                batch_texts,
                show_progress_bar=True,
                normalize_embeddings=True
            )
            all_embeddings.extend(batch_embeddings)
        
        return all_embeddings
    
    def get_embedding_dimension(self) -> int:
        """Get the dimension of the embedding vectors."""
        return self.embedding_dim