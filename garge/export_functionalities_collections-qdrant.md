The error `"Connection refused"` indicates your application cannot connect to the Qdrant server. Let's fix this issue and enhance the code with better error handling and configuration.

## 1. First, Let's Debug the Connection Issue

```python
import os
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_qdrant_client():
    """Create Qdrant client with multiple connection strategies"""
    qdrant_host = os.getenv("QDRANT_HOST", "localhost")
    qdrant_port = int(os.getenv("QDRANT_PORT", 6333))
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    qdrant_url = os.getenv("QDRANT_URL")
    
    logger.info(f"Attempting to connect to Qdrant at {qdrant_host}:{qdrant_port}")
    
    try:
        # Try multiple connection strategies
        if qdrant_url:
            # Use URL if provided
            logger.info(f"Connecting via URL: {qdrant_url}")
            client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
        elif qdrant_api_key:
            # Use cloud connection with API key
            logger.info("Connecting to Qdrant Cloud")
            client = QdrantClient(
                url=f"https://{qdrant_host}:{qdrant_port}",
                api_key=qdrant_api_key
            )
        else:
            # Local connection
            logger.info(f"Connecting to local Qdrant at {qdrant_host}:{qdrant_port}")
            client = QdrantClient(host=qdrant_host, port=qdrant_port)
        
        # Test connection
        collections = client.get_collections()
        logger.info(f"Successfully connected to Qdrant. Found {len(collections.collections)} collections")
        
        return client
        
    except Exception as e:
        logger.error(f"Failed to connect to Qdrant: {str(e)}")
        raise
```

## 2. Updated FastAPI App with Better Error Handling

```python
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional, List
import json
import csv
import io
from datetime import datetime
from pydantic import BaseModel
import traceback
import logging

# Configure logging
logger = logging.getLogger(__name__)

# Define models
class ExportRequest(BaseModel):
    collection_name: str
    format: str = "json"  # "json" or "csv"
    limit: Optional[int] = None
    include_vectors: bool = False
    include_payload: bool = True

class ErrorResponse(BaseModel):
    error: dict

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan manager for startup/shutdown events"""
    # Startup
    logger.info("Starting up FastAPI application...")
    try:
        # Initialize Qdrant client
        app.state.qdrant_client = create_qdrant_client()
        logger.info("Qdrant client initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Qdrant client: {str(e)}")
        app.state.qdrant_client = None
    yield
    # Shutdown
    logger.info("Shutting down FastAPI application...")
    if app.state.qdrant_client:
        app.state.qdrant_client.close()

app = FastAPI(
    title="Qdrant Collection Exporter API",
    description="API for exporting Qdrant collections to CSV or JSON",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency to get Qdrant client
def get_qdrant_client():
    client = app.state.qdrant_client
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Qdrant service is unavailable. Please check the connection."
        )
    return client

# Custom exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": 500,
                "type": type(exc).__name__,
                "message": str(exc),
                "path": request.url.path,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        }
    )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        client = get_qdrant_client()
        # Test connection by getting collections
        collections = client.get_collections()
        return {
            "status": "healthy",
            "qdrant_connected": True,
            "collections_count": len(collections.collections),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "qdrant_connected": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

@app.post("/api/v1/qdrant/export/collection", response_model=None)
async def export_collection(
    request: ExportRequest,
    client = Depends(get_qdrant_client)
):
    """
    Export a Qdrant collection in JSON or CSV format.
    
    - **collection_name**: Name of the collection to export (required)
    - **format**: Export format - "json" or "csv" (default: "json")
    - **limit**: Maximum number of records to export (optional, 0 for all)
    - **include_vectors**: Whether to include vector embeddings (default: False)
    - **include_payload**: Whether to include payload data (default: True)
    """
    try:
        logger.info(f"Exporting collection '{request.collection_name}' in {request.format} format")
        
        # Check if collection exists
        collections = client.get_collections().collections
        collection_names = [col.name for col in collections]
        
        if request.collection_name not in collection_names:
            raise HTTPException(
                status_code=404,
                detail=f"Collection '{request.collection_name}' not found. Available collections: {', '.join(collection_names)}"
            )
        
        # Get collection info
        collection_info = client.get_collection(request.collection_name)
        total_points = collection_info.points_count
        
        logger.info(f"Collection '{request.collection_name}' has {total_points} points")
        
        # Handle limit parameter
        scroll_limit = request.limit if request.limit and request.limit > 0 else None
        if request.limit == 0:
            scroll_limit = None  # 0 means no limit
        
        # Get all points using scroll API with pagination
        all_points = []
        next_offset = None
        
        while True:
            # Calculate batch size
            batch_size = 1000
            if scroll_limit:
                remaining = scroll_limit - len(all_points)
                if remaining <= 0:
                    break
                batch_size = min(batch_size, remaining)
            
            scroll_result = client.scroll(
                collection_name=request.collection_name,
                limit=batch_size,
                offset=next_offset,
                with_vectors=request.include_vectors,
                with_payload=request.include_payload
            )
            
            points, next_offset = scroll_result
            
            if points:
                all_points.extend(points)
                logger.info(f"Retrieved {len(points)} points, total: {len(all_points)}")
            
            # Break conditions
            if not points or next_offset is None:
                break
            if scroll_limit and len(all_points) >= scroll_limit:
                break
        
        if not all_points:
            raise HTTPException(
                status_code=404,
                detail=f"No points found in collection '{request.collection_name}'"
            )
        
        # Export based on format
        if request.format.lower() == "json":
            return await export_as_json(all_points, request.collection_name, request.include_vectors)
        elif request.format.lower() == "csv":
            return await export_as_csv(all_points, request.collection_name, request.include_vectors)
        else:
            raise HTTPException(
                status_code=400,
                detail="Format must be 'json' or 'csv'"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting collection: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error exporting collection: {str(e)}"
        )

async def export_as_json(points, collection_name, include_vectors):
    """Export points as JSON"""
    try:
        # Convert points to JSON-serializable format
        data = []
        for point in points:
            point_data = {
                "id": str(point.id),
                "payload": point.payload or {}
            }
            if include_vectors and hasattr(point, 'vector') and point.vector is not None:
                point_data["vector"] = point.vector
            data.append(point_data)
        
        # Create JSON string
        json_data = json.dumps(data, indent=2, default=str, ensure_ascii=False)
        
        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{collection_name}_export_{timestamp}.json"
        
        # Return as downloadable file
        return StreamingResponse(
            iter([json_data]),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "application/json; charset=utf-8"
            }
        )
    except Exception as e:
        logger.error(f"Error creating JSON export: {str(e)}")
        raise

async def export_as_csv(points, collection_name, include_vectors):
    """Export points as CSV"""
    try:
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Prepare headers
        headers = ["id"]
        
        # Get all unique payload keys from points
        payload_keys = set()
        for point in points:
            if point.payload:
                payload_keys.update(point.payload.keys())
        
        headers.extend(sorted(payload_keys))
        
        if include_vectors:
            headers.append("vector")
        
        writer.writerow(headers)
        
        # Write data rows
        for point in points:
            row = [str(point.id)]
            
            # Add payload values in same order as headers
            for key in sorted(payload_keys):
                if point.payload and key in point.payload:
                    # Convert value to string
                    value = point.payload[key]
                    if isinstance(value, (list, dict)):
                        value = json.dumps(value, ensure_ascii=False)
                    row.append(str(value))
                else:
                    row.append("")
            
            if include_vectors and hasattr(point, 'vector') and point.vector is not None:
                # Convert vector to string representation
                if isinstance(point.vector, list):
                    vector_str = ",".join(map(str, point.vector))
                else:
                    vector_str = str(point.vector)
                row.append(vector_str)
            
            writer.writerow(row)
        
        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{collection_name}_export_{timestamp}.csv"
        
        # Reset buffer position
        output.seek(0)
        
        return StreamingResponse(
            output,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "text/csv; charset=utf-8"
            }
        )
    except Exception as e:
        logger.error(f"Error creating CSV export: {str(e)}")
        raise

@app.get("/api/v1/qdrant/collections")
async def list_collections(client = Depends(get_qdrant_client)):
    """List all available collections"""
    try:
        collections = client.get_collections()
        return {
            "collections": [col.name for col in collections.collections],
            "total": len(collections.collections),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    except Exception as e:
        logger.error(f"Error listing collections: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error listing collections: {str(e)}"
        )

@app.get("/api/v1/qdrant/collections/{collection_name}/info")
async def get_collection_info(collection_name: str, client = Depends(get_qdrant_client)):
    """Get information about a specific collection"""
    try:
        info = client.get_collection(collection_name)
        return {
            "name": info.name,
            "status": info.status,
            "vectors_count": info.vectors_count,
            "points_count": info.points_count,
            "config": info.config.dict() if hasattr(info.config, 'dict') else str(info.config),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    except Exception as e:
        logger.error(f"Error getting collection info: {str(e)}")
        raise HTTPException(
            status_code=404,
            detail=f"Collection '{collection_name}' not found: {str(e)}"
        )
```

## 3. Environment Configuration (.env file)

```bash
# Qdrant Connection
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_API_KEY=
QDRANT_URL=

# FastAPI Configuration
HOST=0.0.0.0
PORT=8079
LOG_LEVEL=INFO
```

## 4. Updated requirements.txt

```txt
fastapi==0.104.1
uvicorn[standard]==0.24.0
qdrant-client==1.6.3
pydantic==2.5.0
python-multipart==0.0.6
python-dotenv==1.0.0
```

## 5. Docker Compose Setup (if using Docker)

```yaml
version: '3.8'

services:
  qdrant:
    image: qdrant/qdrant:latest
    container_name: qdrant
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - ./qdrant_storage:/qdrant/storage
    restart: unless-stopped

  exporter-api:
    build: .
    container_name: qdrant-exporter-api
    ports:
      - "8079:8079"
    environment:
      - QDRANT_HOST=qdrant
      - QDRANT_PORT=6333
      - HOST=0.0.0.0
      - PORT=8079
    depends_on:
      - qdrant
    restart: unless-stopped
```

## 6. Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8079"]
```

## 7. Debug Commands

First, check if Qdrant is running:

```bash
# Check Qdrant status
curl http://localhost:6333/collections

# Check your API health
curl http://0.0.0.0:8079/health

# List collections through your API
curl http://0.0.0.0:8079/api/v1/qdrant/collections
```

## 8. Start the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Run with environment variables
export QDRANT_HOST=localhost
export QDRANT_PORT=6333
uvicorn main:app --host 0.0.0.0 --port 8079 --reload

# Or using python-dotenv
python -c "from dotenv import load_dotenv; load_dotenv()" && uvicorn main:app --host 0.0.0.0 --port 8079 --reload
```

## 9. Test the Export Again

```bash
curl -X 'POST' \
  'http://0.0.0.0:8079/api/v1/qdrant/export/collection' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "collection_name": "evidence_vault_all_transcripts",
  "format": "csv",
  "limit": 10,  # Start with small limit for testing
  "include_vectors": false,
  "include_payload": true
}' --output test_export.csv
```

## Key Improvements:

1. **Better error handling** with detailed logging
2. **Connection testing** at startup
3. **Health check endpoint** to verify connectivity
4. **Graceful pagination** for large collections
5. **UTF-8 support** for non-ASCII characters
6. **Collection existence check** before attempting export
7. **Comprehensive logging** for debugging
8. **Docker support** for easy deployment
9. **Environment variable configuration** for different environments

If you're still getting connection errors, check:
1. Qdrant service is running: `docker ps` or `systemctl status qdrant`
2. Firewall/network policies
3. Correct host/port configuration
4. If using Docker, ensure containers are on the same network