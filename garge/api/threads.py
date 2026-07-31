from fastapi import APIRouter, HTTPException, Body
from typing import List, Optional, Dict, Any
from datetime import datetime
import sqlite3  # Add this import at the top
import os
import json
import uuid
import logging

from api.schemas import (
    ThreadObject, 
    ThreadCreateRequest, 
    ThreadListResponse,
    MessageObject,
    MessageCreateRequest,
    MessageListResponse,
    RunObject,
    RunCreateRequest
)
from config.settings import settings

# Initialize router before potential error code
router = APIRouter(prefix="/v1/threads", tags=["Threads"])

# Try to import and initialize assistant_core, with fallback if database is corrupted
try:
    from core.assistant import AssistantCore
    assistant_core = AssistantCore()
except sqlite3.DatabaseError as e:
    # sqlite3 is now imported at the top of the file
    logging.error(f"Database error: {e}")
    from core.assistant import AssistantCore
    
    # Create a simplified version of AssistantCore for emergency use
    class EmergencyAssistantCore:
        async def generate_response(self, messages, model=None):
            # Simple implementation that echoes back the last message
            # This is just a fallback to allow the API to start
            last_message = messages[-1]["content"] if messages else ""
            return {
                "choices": [
                    {
                        "message": {
                            "content": f"[DATABASE ERROR] Unable to process your request normally. Please contact support. Your message: {last_message}"
                        }
                    }
                ]
            }
    
    assistant_core = EmergencyAssistantCore()
    
# Ensure threads directory exists
os.makedirs(settings.threads_storage_path, exist_ok=True)

def get_thread_path(thread_id: str) -> str:
    """Get the file path for a thread."""
    return os.path.join(settings.threads_storage_path, f"{thread_id}.json")

def get_messages_path(thread_id: str) -> str:
    """Get the file path for thread messages."""
    return os.path.join(settings.threads_storage_path, f"{thread_id}_messages.json")

@router.post("/", response_model=ThreadObject)
async def create_thread(
    request: ThreadCreateRequest = Body(default=ThreadCreateRequest())
):
    """Create a new thread."""
    thread_id = f"thread_{uuid.uuid4().hex}"
    now = int(datetime.now().timestamp())
    
    thread_data = {
        "id": thread_id,
        "object": "thread",
        "created_at": now,
        "metadata": request.metadata or {}
    }
    
    # Save thread data
    with open(get_thread_path(thread_id), "w") as f:
        json.dump(thread_data, f)
    
    # Initialize empty messages list
    with open(get_messages_path(thread_id), "w") as f:
        json.dump({"messages": []}, f)
    
    return ThreadObject(**thread_data)

@router.get("/", response_model=ThreadListResponse)
async def list_threads():
    """List all threads."""
    threads = []
    
    for filename in os.listdir(settings.threads_storage_path):
        if filename.endswith(".json") and not filename.endswith("_messages.json"):
            filepath = os.path.join(settings.threads_storage_path, filename)
            
            with open(filepath, "r") as f:
                thread_data = json.load(f)
                threads.append(ThreadObject(**thread_data))
    
    return {"object": "list", "data": threads}

@router.get("/{thread_id}", response_model=ThreadObject)
async def get_thread(thread_id: str):
    """Get information about a specific thread."""
    thread_path = get_thread_path(thread_id)
    
    if not os.path.exists(thread_path):
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
    
    with open(thread_path, "r") as f:
        thread_data = json.load(f)
    
    return ThreadObject(**thread_data)

@router.delete("/{thread_id}", response_model=Dict[str, Any])
async def delete_thread(thread_id: str):
    """Delete a thread."""
    thread_path = get_thread_path(thread_id)
    messages_path = get_messages_path(thread_id)
    
    if not os.path.exists(thread_path):
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
    
    # Delete thread data
    os.remove(thread_path)
    
    # Delete messages if they exist
    if os.path.exists(messages_path):
        os.remove(messages_path)
    
    return {
        "id": thread_id,
        "object": "thread",
        "deleted": True
    }

# --- Thread Messages ---

@router.post("/{thread_id}/messages", response_model=MessageObject)
async def add_message(
    thread_id: str,
    request: MessageCreateRequest
):
    """Add a message to a thread."""
    thread_path = get_thread_path(thread_id)
    messages_path = get_messages_path(thread_id)
    
    if not os.path.exists(thread_path):
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
    
    message_id = f"msg_{uuid.uuid4().hex}"
    now = int(datetime.now().timestamp())
    
    # Handle both string and list content
    if isinstance(request.content, str):
        content_list = [{"type": "text", "text": {"value": request.content}}]
    elif isinstance(request.content, list):
        # Assuming the list is already in the correct format for multi-modal content
        content_list = request.content
    else:
        raise HTTPException(status_code=422, detail="Invalid content format")

    message_data = {
        "id": message_id,
        "object": "thread.message",
        "created_at": now,
        "thread_id": thread_id,
        "role": request.role,
        "content": content_list,
        "file_ids": request.file_ids or [],
        "metadata": request.metadata or {}
    }
    
    # Load existing messages
    if os.path.exists(messages_path):
        with open(messages_path, "r") as f:
            messages_data = json.load(f)
    else:
        messages_data = {"messages": []}
    
    # Add the new message
    messages_data["messages"].append(message_data)
    
    # Save updated messages
    with open(messages_path, "w") as f:
        json.dump(messages_data, f)
    
    return MessageObject(**message_data)

@router.get("/{thread_id}/messages", response_model=MessageListResponse)
async def list_messages(thread_id: str, limit: int = 20):
    """List all messages in a thread."""
    thread_path = get_thread_path(thread_id)
    messages_path = get_messages_path(thread_id)
    
    if not os.path.exists(thread_path):
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
    
    if not os.path.exists(messages_path):
        return {"object": "list", "data": []}
    
    with open(messages_path, "r") as f:
        messages_data = json.load(f)
    
    # Get the most recent messages
    messages = messages_data["messages"][-limit:]
    
    return {
        "object": "list",
        "data": [MessageObject(**msg) for msg in messages]
    }

# --- Thread Runs ---

@router.post("/{thread_id}/runs", response_model=RunObject)
async def create_run(
    thread_id: str,
    request: RunCreateRequest
):
    """Run an assistant on a thread."""
    thread_path = get_thread_path(thread_id)
    messages_path = get_messages_path(thread_id)
    
    if not os.path.exists(thread_path):
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
    
    if not os.path.exists(messages_path):
        raise HTTPException(status_code=400, detail="Thread has no messages")
    
    # Load messages
    with open(messages_path, "r") as f:
        messages_data = json.load(f)
    
    if not messages_data["messages"]:
        raise HTTPException(status_code=400, detail="Thread has no messages")
    
    # Convert thread messages to the format expected by assistant
    formatted_messages = []
    for msg in messages_data["messages"]:
        content = ""
        if msg["content"]:
            for content_item in msg["content"]:
                if content_item["type"] == "text":
                    content += content_item["text"]["value"] + "\n"
        
        formatted_messages.append({
            "role": msg["role"],
            "content": content.strip()
        })
    
    # Generate response
    run_id = f"run_{uuid.uuid4().hex}"
    now = int(datetime.now().timestamp())
    
    try:
        # Use the assistant to generate a response
        response = await assistant_core.generate_response(
            messages=formatted_messages,
            model=request.model or "lfm2.5:8b:8b"
        )
        
        # Extract the response content
        assistant_message = response["choices"][0]["message"]["content"]
        
        # Add the response as a new message to the thread
        assistant_msg = {
            "id": f"msg_{uuid.uuid4().hex}",
            "object": "thread.message",
            "created_at": now,
            "thread_id": thread_id,
            "role": "assistant",
            "content": [{"type": "text", "text": {"value": assistant_message}}],
            "file_ids": [],
            "metadata": {}
        }
        
        messages_data["messages"].append(assistant_msg)
        
        # Save updated messages
        with open(messages_path, "w") as f:
            json.dump(messages_data, f)
        
        # Create the run object
        run_data = {
            "id": run_id,
            "object": "thread.run",
            "created_at": now,
            "thread_id": thread_id,
            "assistant_id": request.assistant_id or "default",
            "status": "completed",
            "model": request.model,
            "instructions": request.instructions or "",
            "metadata": request.metadata or {}
        }
        
        return RunObject(**run_data)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{thread_id}/files")
async def attach_file_to_thread(thread_id: str, body: Dict):
    file_id = body.get("file_id")
    if not file_id:
        raise HTTPException(status_code=400, detail="file_id is required")
    # TODO: Implement logic to associate file_id with thread_id in your DB
    # Example:
    # thread = db.get_thread(thread_id)
    # thread.file_ids.append(file_id)
    # db.save(thread)
    return {"thread_id": thread_id, "file_id": file_id, "status": "attached"}