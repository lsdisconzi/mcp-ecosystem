"""
Qdrant Client Service  — CANONICAL MODULE
All other qdrant client modules (core/qdrant_client.py, services/qdrant_service.py,
config/qdrant_config.py) re-export from here.  Do not instantiate QdrantClient
anywhere else in the codebase.
"""

import os
import threading
from typing import Optional
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException
from fastapi import HTTPException
import logging

# Configure logging
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


class QdrantConnectionError(Exception):
    """Raised when the Qdrant service is not available or the connection fails."""


# Qdrant configuration from environment.
# Default to local instance; set QDRANT_URL for Qdrant Cloud.
QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY: Optional[str] = os.getenv("QDRANT_API_KEY")

# --- Qdrant Client Singleton ---
_qdrant_client: Optional[QdrantClient] = None
_qdrant_client_lock = threading.Lock()


def get_qdrant_client() -> QdrantClient:
    """
    Get or create Qdrant client with connection validation.
    
    Implements singleton pattern to ensure single connection pool.
    Validates connection before returning client.
    
    Returns:
        QdrantClient: Connected and validated Qdrant client instance
        
    Raises:
        HTTPException: If connection to Qdrant fails (503 Service Unavailable)
        
    Example:
        ```python
        client = get_qdrant_client()
        collections = client.get_collections()
        ```
    """
    global _qdrant_client
    
    with _qdrant_client_lock:
        if _qdrant_client is None:
            try:
                logger.info(f"Connecting to Qdrant at {QDRANT_URL}")
                _qdrant_client = QdrantClient(
                    url=QDRANT_URL,
                    api_key=QDRANT_API_KEY,
                    timeout=10
                )
                
                # Test connection by getting collections
                _qdrant_client.get_collections()
                logger.info("✅ Successfully connected to Qdrant")
                
            except (ResponseHandlingException, ConnectionRefusedError, Exception) as e:
                _qdrant_client = None  # Ensure retrying next call is possible
                logger.error(f"❌ Failed to connect to Qdrant: {e}")
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "Vector database unavailable",
                        "message": "Please ensure Qdrant is running and accessible",
                        "url": QDRANT_URL,
                        "details": str(e)
                    }
                )
    
    return _qdrant_client


def get_connected_client() -> QdrantClient:
    """
    Return the already-established Qdrant client, or raise HTTP 503 instantly
    (no connection attempt, no timeout) if POST /v1/qdrant/connect has not been
    called yet or the connection was lost.
    """
    if _qdrant_client is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Connection not established",
                "message": "Call POST /v1/qdrant/connect first to initialise the database connection",
                "status": 503,
            }
        )
    return _qdrant_client


def close_qdrant_client():
    """
    Close the Qdrant client connection.
    
    Should be called during application shutdown to clean up resources.
    
    Example:
        ```python
        close_qdrant_client()  # During app shutdown
        ```
    """
    global _qdrant_client
    if _qdrant_client:
        try:
            _qdrant_client.close()
            logger.info("Qdrant client connection closed")
        except Exception as e:
            logger.error(f"Error closing Qdrant client: {e}")
        finally:
            _qdrant_client = None


def health_check() -> dict:
    """
    Check Qdrant service health and connection status.
    
    Returns:
        dict: Health status information including:
            - status: "healthy" or "unhealthy"
            - url: Qdrant URL
            - connected: boolean connection status
            - collections_count: number of collections (if connected)
            - error: error details (if unhealthy)
            
    Example:
        ```python
        health = health_check()
        if health["connected"]:
            print("Qdrant is healthy")
        ```
    """
    try:
        client = get_qdrant_client()
        collections = client.get_collections()
        
        return {
            "status": "healthy",
            "url": QDRANT_URL,
            "collections_count": len(collections.collections),
            "connected": True
        }
    except HTTPException as e:
        return {
            "status": "unhealthy",
            "url": QDRANT_URL,
            "connected": False,
            "error": e.detail
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "url": QDRANT_URL,
            "connected": False,
            "error": str(e)
        }