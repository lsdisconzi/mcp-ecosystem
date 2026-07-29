import os
import json
import logging
import pydantic
from fastapi import APIRouter, HTTPException, Body, UploadFile, File, Form, Request
from typing import List, Optional, Dict, Any 
from datetime import datetime
from pathlib import Path

from api.schemas import (
    AssistantObject,
    AssistantCreateRequest,
    AssistantListResponse,
    AssistantUpdateRequest,
    ChatRequest,
    GenericSuccessResponse
)
from core.assistant import AssistantCore
from config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/assistants", tags=["Assistants"])

# Ensure assistants directory exists
os.makedirs(settings.assistant_storage_path, exist_ok=True)

def get_assistant_path(assistant_id: str) -> str:
    """Get the file path for an assistant."""
    return os.path.join(settings.assistant_storage_path, f"{assistant_id}.json")

def get_assistant_from_file(assistant_id: str) -> Optional[Dict[str, Any]]:
    """Load assistant data from file storage."""
    file_path = get_assistant_path(assistant_id)
    
    if not os.path.exists(file_path):
        return None
    
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading assistant {assistant_id}: {e}")
        return None

def to_serializable(obj):
    """Convert Pydantic models and nested structures to JSON-serializable format."""
    if isinstance(obj, pydantic.BaseModel):
        return obj.model_dump()
    if isinstance(obj, list):
        return [to_serializable(i) for i in obj]
    if isinstance(obj, dict):
        return {k: to_serializable(v) for k, v in obj.items()}
    return obj

def save_assistant_to_file(assistant_data):
    """Save assistant to file storage"""
    logger.info(f"save_assistant_to_file called with data: {assistant_data}")
    
    assistant_id = assistant_data.get("id")
    if not assistant_id:
        raise ValueError("Assistant ID is required")
    
    logger.info(f"Assistant ID: {assistant_id}")
    logger.info(f"Storage path: {settings.assistant_storage_path}")
    
    file_path = get_assistant_path(assistant_id)
    
    try:
        with open(file_path, 'w') as f:
            json.dump(to_serializable(assistant_data), f, indent=2)
        logger.info(f"✅ Assistant saved to {file_path}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to save assistant: {e}")
        raise

@router.post("/", response_model=AssistantObject)
async def create_assistant(request: AssistantCreateRequest):
    """Create a new assistant"""
    try:
        assistant_id = f"asst_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        assistant_data = {
            "id": assistant_id,
            "object": "assistant",
            "created_at": int(datetime.now().timestamp()),
            "name": request.name,
            "description": request.description,
            "model": request.model,
            "instructions": request.instructions or "You are a helpful assistant.",
            "tools": request.tools or [],
            "file_ids": request.file_ids or [],
            "metadata": request.metadata or {},
            "language": request.language or "en",
            "collections": request.collections or [],
            "temperature": request.temperature if request.temperature is not None else 0.7,
            "top_p": request.top_p if request.top_p is not None else 1.0,
            "max_tokens": request.max_tokens or 500
        }
        
        save_assistant_to_file(assistant_data)
        
        return AssistantObject(**assistant_data)
        
    except Exception as e:
        logger.error(f"Error creating assistant: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/", response_model=AssistantListResponse)
async def list_assistants():
    """List all assistants"""
    try:
        assistants_dir = Path(settings.assistant_storage_path)
        if not assistants_dir.exists():
            return {"object": "list", "data": []}
            
        assistants = []
        for file_path in assistants_dir.glob("*.json"):
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)
                    
                # Fix malformed tools before validation
                if "tools" in data:
                    fixed_tools = []
                    for tool in data["tools"]:
                        try:
                            # Ensure tool has proper structure
                            if isinstance(tool, dict):
                                if "function" in tool:
                                    func = tool["function"]
                                    # Ensure parameters has properties
                                    if "parameters" in func:
                                        params = func["parameters"]
                                        if isinstance(params, dict):
                                            if "properties" not in params:
                                                params["properties"] = {}
                                            if "required" not in params:
                                                params["required"] = []
                                            if "type" not in params:
                                                params["type"] = "object"
                                fixed_tools.append(tool)
                            elif isinstance(tool, str):
                                # Simple string tool reference
                                fixed_tools.append({"type": "function", "function": {"name": tool}})
                        except Exception as e:
                            logger.warning(f"Skipping malformed tool in {file_path.name}: {e}")
                            continue
                    data["tools"] = fixed_tools
                
                assistants.append(data)
                    
            except Exception as e:
                logger.error(f"Error loading assistant from {file_path.name}: {e}")
                continue
                
        return {"object": "list", "data": assistants}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{assistant_id}", response_model=AssistantObject)
async def get_assistant(assistant_id: str):
    """Get a specific assistant"""
    try:
        file_path = get_assistant_path(assistant_id)
        
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"Assistant {assistant_id} not found")
        
        with open(file_path, 'r') as f:
            assistant_data = json.load(f)
        
        # Ensure new fields have defaults
        assistant_data.setdefault("language", "en")
        assistant_data.setdefault("collections", [])
        assistant_data.setdefault("temperature", 0.7)
        assistant_data.setdefault("top_p", 1.0)
        assistant_data.setdefault("max_tokens", 500)
        
        return AssistantObject(**assistant_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting assistant: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/{assistant_id}", response_model=AssistantObject)
async def update_assistant(assistant_id: str, request: AssistantUpdateRequest):
    """Update an assistant (partial update)"""
    try:
        # Get existing assistant
        file_path = get_assistant_path(assistant_id)
        
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"Assistant {assistant_id} not found")
        
        with open(file_path, 'r') as f:
            assistant_data = json.load(f)
        
        # Update only provided fields
        update_data = request.model_dump(exclude_unset=True)
        assistant_data.update(update_data)
        
        # Save updated assistant
        save_assistant_to_file(assistant_data)
        
        return AssistantObject(**assistant_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating assistant: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{assistant_id}", response_model=AssistantObject)
async def replace_assistant(assistant_id: str, request: AssistantUpdateRequest):
    """Update an assistant (full replacement)"""
    try:
        # Get existing assistant to preserve ID and created_at
        file_path = get_assistant_path(assistant_id)
        
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"Assistant {assistant_id} not found")
        
        with open(file_path, 'r') as f:
            existing_data = json.load(f)
        
        # Preserve immutable fields
        preserved_id = existing_data["id"]
        preserved_created_at = existing_data["created_at"]
        
        # Build new assistant data from request
        update_data = request.model_dump(exclude_unset=True)
        assistant_data = existing_data.copy()
        assistant_data.update(update_data)
        
        # Ensure preserved fields aren't changed
        assistant_data["id"] = preserved_id
        assistant_data["created_at"] = preserved_created_at
        
        # Save updated assistant
        save_assistant_to_file(assistant_data)
        
        return AssistantObject(**assistant_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error replacing assistant: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{assistant_id}", response_model=Dict[str, Any])
async def delete_assistant(assistant_id: str):
    """Delete an assistant"""
    try:
        file_path = get_assistant_path(assistant_id)
        
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"Assistant {assistant_id} not found")
        
        os.remove(file_path)
        
        return {"id": assistant_id, "object": "assistant.deleted", "deleted": True}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting assistant: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{assistant_id}/chat", response_model=Dict[str, Any])
async def chat_with_assistant(assistant_id: str, request: ChatRequest):
    """Chat with an assistant"""
    try:
        # Get assistant
        assistant = await get_assistant(assistant_id)

        # Normalize tool objects to plain dicts for AssistantCore/tool registry usage.
        assistant_tools = []
        for tool in (assistant.tools or []):
            if isinstance(tool, dict):
                assistant_tools.append(tool)
            elif hasattr(tool, "model_dump"):
                assistant_tools.append(tool.model_dump())
            else:
                logger.warning(f"Skipping unsupported tool object type: {type(tool)}")

        model_name = request.model or assistant.model
        temperature = request.temperature if request.temperature is not None else assistant.temperature
        max_tokens = request.max_tokens if request.max_tokens is not None else assistant.max_tokens
        top_p = request.top_p if request.top_p is not None else assistant.top_p
        
        # Use AssistantCore for chat
        core = AssistantCore()
        response = await core.generate_response(
            messages=request.messages,
            model=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            stream=request.stream,
            tools=assistant_tools,
            assistant_id=assistant_id,
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error chatting with assistant: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{assistant_id}/files", response_model=GenericSuccessResponse)
async def attach_file_to_assistant(assistant_id: str, request: Request):
    """Attach an existing file to an assistant"""
    try:
        # Parse request body
        body = await request.json()
        file_id = body.get("file_id")
        
        if not file_id:
            raise HTTPException(status_code=400, detail="file_id is required")
        
        # Get assistant
        assistant = get_assistant_from_file(assistant_id)
        if not assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")
        
        # Verify file exists - check multiple possible locations
        file_found = False
        possible_paths = [
            Path("data/files") / file_id,
            Path("data/files") / f"{file_id}.json",
            Path(settings.assistant_storage_path).parent / "files" / file_id,
            Path(settings.assistant_storage_path).parent / "files" / f"{file_id}.json",
        ]
        
        # If settings has files_dir, use it
        if hasattr(settings, 'files_dir'):
            possible_paths.insert(0, Path(settings.files_dir) / file_id)
            possible_paths.insert(1, Path(settings.files_dir) / f"{file_id}.json")
        elif hasattr(settings, 'file_storage_dir'):
            possible_paths.insert(0, Path(settings.file_storage_dir) / file_id)
            possible_paths.insert(1, Path(settings.file_storage_dir) / f"{file_id}.json")
        
        for file_path in possible_paths:
            if file_path.exists():
                file_found = True
                break
        
        if not file_found:
            # File might exist in the system, just not found - log warning but proceed
            logger.warning(f"File {file_id} not found in filesystem, but proceeding with attachment")
        
        # Add file_id to assistant if not already present
        if "file_ids" not in assistant:
            assistant["file_ids"] = []
        
        if file_id not in assistant["file_ids"]:
            assistant["file_ids"].append(file_id)
            save_assistant_to_file(assistant)
        
        return GenericSuccessResponse(
            success=True,
            message=f"File {file_id} attached to assistant {assistant_id}",
            data={
                "assistant_id": assistant_id,
                "file_id": file_id,
                "total_files": len(assistant["file_ids"])
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error attaching file to assistant: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{assistant_id}/files", response_model=Dict[str, Any])
async def list_assistant_files(assistant_id: str):
    """List all files attached to an assistant"""
    try:
        assistant = get_assistant_from_file(assistant_id)
        if not assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")
        
        file_ids = assistant.get("file_ids", [])
        
        return {
            "object": "list",
            "data": file_ids
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing assistant files: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{assistant_id}/files/{file_id}", response_model=Dict[str, Any])
async def detach_file_from_assistant(assistant_id: str, file_id: str):
    """Detach a file from an assistant"""
    try:
        assistant = get_assistant_from_file(assistant_id)
        if not assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")
        
        if "file_ids" not in assistant:
            assistant["file_ids"] = []
        
        if file_id in assistant["file_ids"]:
            assistant["file_ids"].remove(file_id)
            save_assistant_to_file(assistant)
        
        return {
            "id": file_id,
            "object": "assistant.file.deleted",
            "deleted": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error detaching file from assistant: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{assistant_id}/query-knowledge", response_model=Dict[str, Any])
async def query_assistant_knowledge(
    assistant_id: str,
    request: Request
):
    """Query the knowledge base of an assistant"""
    try:
        # Parse request
        body = await request.json()
        query = body.get("query", "")
        limit = body.get("limit", 5)
        
        if not query:
            raise HTTPException(status_code=400, detail="query is required")
        
        # Get assistant
        assistant = get_assistant_from_file(assistant_id)
        if not assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")
        
        # Get collections from assistant
        collections = assistant.get("collections", [])
        
        if not collections:
            return {
                "results": [],
                "count": 0,
                "query": query,
                "message": "No collections configured for this assistant"
            }
        
        # Search in configured collections
        all_results = []
        
        for collection_name in collections:
            try:
                # Use Qdrant client to search
                from routes.qdrant_router import client as qdrant_client
                
                if not qdrant_client:
                    continue
                
                # Perform semantic search
                search_results = qdrant_client.search(
                    collection_name=collection_name,
                    query_text=query,
                    limit=limit
                )
                
                # Add collection name to results
                for result in search_results:
                    result["collection"] = collection_name
                    all_results.append(result)
                    
            except Exception as e:
                logger.warning(f"Error searching collection {collection_name}: {str(e)}")
                continue
        
        # Sort by score and limit
        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        all_results = all_results[:limit]
        
        return {
            "results": all_results,
            "count": len(all_results),
            "query": query
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying knowledge base: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

def _validate_and_normalize_tools(tools: List[dict]) -> List[dict]:
    """Validate and normalize tool schemas."""
    normalized = []
    
    for tool in tools:
        if tool.get("type") != "function":
            continue
        
        function = tool.get("function", {})
        if not function:
            continue
        
        # Ensure parameters structure
        params = function.get("parameters", {})
        if isinstance(params, dict):
            if "type" not in params:
                params["type"] = "object"
            if "properties" not in params:
                params["properties"] = {}
            if "required" not in params:
                params["required"] = []
            function["parameters"] = params
        
        normalized.append({
            "type": "function",
            "function": function
        })
    
    return normalized