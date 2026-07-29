"""
Pydantic Schemas for Qdrant Operations
Data models for request/response validation and documentation.
"""

from pydantic import BaseModel, Field, validator
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from enum import Enum


class DistanceMetric(str, Enum):
    """Supported distance metrics for vector similarity."""
    COSINE = "cosine"
    EUCLIDEAN = "euclid"
    DOT = "dot"


class DocumentType(str, Enum):
    """Supported document types for ingestion."""
    TRANSCRIPT = "transcript"
    VIOLATION = "violation"
    LAW = "law"
    RESOLUTION = "resolution"
    RBAC = "rbac"
    CDC = "cdc"
    ICAO = "icao"
    INTERNAL = "internal"
    GENERIC = "generic"
    METADATA = "metadata"


class CreateCollectionRequest(BaseModel):
    """Request model for creating a new Qdrant collection."""
    name: str = Field(..., min_length=3, max_length=100, description="Name of the collection")
    vector_size: int = Field(384, description="Vector dimension size (384 or 768)")
    distance_metric: DistanceMetric = Field(DistanceMetric.COSINE, description="Distance metric")
    
    # Optional metadata
    description: Optional[str] = Field(None, description="Collection description")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Custom metadata")
    
    @validator('name')
    def validate_name(cls, v):
        """Validate collection name format."""
        import re
        if not re.match(r'^[a-z0-9_-]+$', v):
            raise ValueError('Collection name must contain only lowercase letters, numbers, underscores, and hyphens')
        return v
    
    @validator('vector_size')
    def validate_vector_size(cls, v):
        """Validate vector size is supported."""
        if v not in [384, 768]:
            raise ValueError('Vector size must be 384 or 768')
        return v


class PointSchema(BaseModel):
    """Schema for a single vector point."""
    id: Union[int, str] = Field(..., description="Unique point identifier")
    vector: List[float] = Field(..., description="Vector embedding")
    payload: Optional[Dict[str, Any]] = Field(None, description="Metadata payload")


class UpsertPointsRequest(BaseModel):
    """Request for upserting points into a collection."""
    collection_name: str = Field(..., description="Target collection name")
    points: List[PointSchema] = Field(..., min_items=1, description="Points to upsert")


class SearchRequest(BaseModel):
    """Request for vector similarity search."""
    collection_name: str = Field(..., description="Target collection name")
    query_text: str = Field(..., min_length=1, description="Text query to search for")
    limit: int = Field(10, ge=1, le=100, description="Maximum results to return")
    filters: Optional[Dict[str, Any]] = Field(None, description="Filter conditions")
    min_score: float = Field(0.0, ge=0.0, le=1.0, description="Minimum similarity score")


class SearchResponse(BaseModel):
    """Response for search operations."""
    status: str = Field("success", description="Operation status")
    count: int = Field(..., description="Number of results")
    results: List[Dict[str, Any]] = Field(..., description="Search results")


class StructuredIngestRequest(BaseModel):
    """Request for structured data ingestion."""
    collection_name: str = Field(..., description="Target collection name")
    data_type: DocumentType = Field(..., description="Type of data being ingested")
    items: List[Dict[str, Any]] = Field(..., min_items=1, description="Data items to ingest")
    
    # Ingestion options
    chunk_size: Optional[int] = Field(None, ge=100, le=5000, description="Chunk size for text")
    chunk_overlap: Optional[int] = Field(None, ge=0, le=500, description="Chunk overlap")


class FileIngestRequest(BaseModel):
    """Request for file ingestion."""
    collection_name: str = Field(..., description="Target collection name")
    chunk_size: int = Field(1000, ge=100, le=5000, description="Chunk size for text")
    chunk_overlap: int = Field(100, ge=0, le=500, description="Chunk overlap")
    doc_type: Optional[DocumentType] = Field(None, description="Override document type detection")


class CollectionInfo(BaseModel):
    """Information about a Qdrant collection."""
    name: str = Field(..., description="Collection name")
    points_count: int = Field(..., description="Number of points/vectors")
    vector_size: int = Field(..., description="Vector dimension")
    distance_metric: str = Field(..., description="Distance metric")
    status: str = Field(..., description="Collection status")
    created_at: Optional[datetime] = Field(None, description="Creation timestamp")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Collection metadata")


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Health status")
    url: str = Field(..., description="Qdrant URL")
    connected: bool = Field(..., description="Connection status")
    collections_count: Optional[int] = Field(None, description="Number of collections")
    error: Optional[str] = Field(None, description="Error details if unhealthy")


class CrossReferenceRequest(BaseModel):
    """Request for cross-referencing findings with regulations."""
    findings: List[Dict[str, Any]] = Field(..., min_items=1, description="Findings to cross-reference")
    priority_weights: Optional[Dict[str, float]] = Field(None, description="Document type priority weights")
    min_score: float = Field(0.25, ge=0.0, le=1.0, description="Minimum score threshold")