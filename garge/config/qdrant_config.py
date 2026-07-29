"""
config/qdrant_config.py — compatibility shim.
LegalDocumentVectorStore is now canonical in services/legal_qdrant_config.py.
"""
from services.legal_qdrant_config import LegalDocumentVectorStore  # noqa: F401
