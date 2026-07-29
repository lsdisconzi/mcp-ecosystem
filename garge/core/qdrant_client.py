"""
core/qdrant_client.py — compatibility shim.
All connection logic is now canonical in services/qdrant_client.py.
This module re-exports the symbols used by core/ingestion and api/knowledge_router.
"""
from services.qdrant_client import (  # noqa: F401
    QdrantConnectionError,
    QdrantClient,
    get_qdrant_client,
    close_qdrant_client,
    health_check,
    QDRANT_URL,
    QDRANT_API_KEY,
)

# QdrantClientWrapper kept as a thin alias for any code that instantiates it directly.
# Prefer get_qdrant_client() for all new code.
from qdrant_client import QdrantClient as QdrantClientWrapper  # noqa: F401
