"""
qdrant_service.py — compatibility shim.
All symbols are now canonical in services/qdrant_client.py.
Import from there directly; this module exists only for backward compatibility.
"""
from services.qdrant_client import (  # noqa: F401
    QdrantConnectionError,
    QdrantClient,
    get_qdrant_client,
    get_connected_client,
    close_qdrant_client,
    health_check,
    QDRANT_URL,
    QDRANT_API_KEY,
)
