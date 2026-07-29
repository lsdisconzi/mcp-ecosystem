from fastapi import APIRouter, UploadFile, File, Form, Query, HTTPException, Request
from pydantic import BaseModel, Field
import os
import uuid
import json
import shutil
import time
from pathlib import Path
from config.settings import settings
# from data.tools.detailed_documentation.file_reader import summarize_files  # Adjust import if needed
from fastapi.responses import FileResponse
from typing import List, Dict, Any
import email
from email import policy
from email.parser import BytesParser
from core.file_utils import summarize_files
import asyncio
from api.schemas import SummarizeRequest


router = APIRouter(tags=["files"])

# --- Path safety (S1 — path traversal fix) ---
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()

def _safe_path(raw: str) -> Path:
    """Resolve raw path against the project root; reject traversal outside it."""
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = _PROJECT_ROOT / candidate
    resolved = candidate.resolve()
    if not str(resolved).startswith(str(_PROJECT_ROOT)):
        raise HTTPException(status_code=403, detail="Access denied: path is outside the allowed directory")
    return resolved

# --- Configurable data directories (S4 — no more hardcoded dev paths) ---
_TRANSCRIPTS_PATH = Path(os.getenv("TRANSCRIPTS_DIR", "data/documents/transcripts"))
if not _TRANSCRIPTS_PATH.is_absolute():
    _TRANSCRIPTS_PATH = (_PROJECT_ROOT / _TRANSCRIPTS_PATH).resolve()

_AUDIO_PATH = Path(os.getenv("AUDIO_DIR", str(settings.audio_storage_path)))
if not _AUDIO_PATH.is_absolute():
    _AUDIO_PATH = (_PROJECT_ROOT / _AUDIO_PATH).resolve()

_EVIDENCE_PATH = Path(os.getenv("EVIDENCE_DIR", "data/documents/evidence"))
if not _EVIDENCE_PATH.is_absolute():
    _EVIDENCE_PATH = (_PROJECT_ROOT / _EVIDENCE_PATH).resolve()

_LAWS_PATH = Path(os.getenv("LAWS_DIR", "data/documents/laws"))
if not _LAWS_PATH.is_absolute():
    _LAWS_PATH = (_PROJECT_ROOT / _LAWS_PATH).resolve()

class FileSummarizeRequest(BaseModel):
    """Request schema for file summarization"""
    file_ids: List[str] = Field(..., min_items=1, description="List of file IDs to summarize")
    model: str = Field(default="llama3.1:8b", description="AI model to use")
    temperature: float = Field(default=0.1, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: int = Field(default=1000, ge=1, le=4000, description="Maximum tokens for summary")


@router.post("/v1/files/summarize")
async def summarize_files_endpoint(request: FileSummarizeRequest):
    """
    Summarize multiple files using AI model
    """
    try:
        result = summarize_files(
            file_ids=request.file_ids,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File summarization failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@router.post("/v1/files")
async def upload_file(file: UploadFile = File(...), purpose: str = Form("assistants")):
    """Upload a file and return file ID"""
    file_id = f"file-{uuid.uuid4().hex}"
    
    # Save to data/files directory
    os.makedirs(settings.file_storage_path, exist_ok=True)
    file_path = os.path.join(settings.file_storage_path, f"{file_id}.{file.filename.split('.')[-1]}")
    
    # Save the actual file
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    
    # Save metadata
    metadata = {
        "id": file_id,
        "object": "file",
        "filename": file.filename,
        "purpose": purpose,
        "bytes": len(content),
        "created_at": int(time.time()),
        "physical_path": file_path,
    }
    
    metadata_path = os.path.join(settings.file_storage_path, f"{file_id}.json")
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    
    return metadata

@router.get("/v1/files/list")
async def list_files_in_directory(path: str = Query(..., description="Directory path to list (relative to project root)")):
    """List files in a directory — restricted to the project directory."""
    try:
        resolved = _safe_path(path)  # raises 403 on traversal

        if not resolved.exists():
            raise HTTPException(status_code=404, detail="Path not found")

        files = []
        try:
            for item in os.listdir(resolved):
                item_path = resolved / item
                if item_path.is_file():
                    stat = item_path.stat()
                    files.append({
                        "name": item,
                        "path": str(item_path),
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                        "type": "file"
                    })
                elif item_path.is_dir():
                    files.append({
                        "name": item,
                        "path": str(item_path),
                        "type": "directory"
                    })

            return files

        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing files: {str(e)}")

@router.get("/v1/files/read")
async def read_file(path: str = Query(..., description="File path to read (relative to project root)")):
    """Read file contents — restricted to the project directory (S1)."""
    import mimetypes
    try:
        resolved = _safe_path(path)  # raises 403 on traversal

        if not resolved.exists():
            raise HTTPException(status_code=404, detail="File not found")

        if not resolved.is_file():
            raise HTTPException(status_code=400, detail="Path is not a file")

        mime, _ = mimetypes.guess_type(str(resolved))
        ext = resolved.suffix.lower()

        # Try to read as text first
        try:
            with open(resolved, 'r', encoding='utf-8') as f:
                content = f.read()
            # If it's a JSON file, parse it
            if resolved.suffix == '.json':
                try:
                    parsed_content = json.loads(content)
                    return {"content": json.dumps(parsed_content, indent=2), "type": "json"}
                except json.JSONDecodeError:
                    return {"content": content, "type": "text"}
            # If it's an EML file, extract email body
            elif ext == ".eml" or (mime and "message/rfc822" in mime):
                try:
                    with open(resolved, 'rb') as f:
                        msg = BytesParser(policy=policy.default).parse(f)
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == 'text/plain':
                                body += part.get_content()
                    else:
                        body = msg.get_content()
                    return {"content": body, "type": "eml"}
                except Exception as e:
                    return {"content": content, "type": "text"}
            else:
                return {"content": content, "type": "text"}
        except UnicodeDecodeError:
            # Not a text file, try PDF extraction if PDF
            if ext == ".pdf" or (mime and "pdf" in mime):
                try:
                    from pypdf import PdfReader
                    with open(resolved, "rb") as f:
                        reader = PdfReader(f)
                        text = ""
                        for page in reader.pages:
                            text += page.extract_text() or ""
                    return {"content": text, "type": "pdf"}
                except Exception:
                    pass
            # Fallback: read as binary hex
            with open(resolved, 'rb') as f:
                content = f.read()
            return {"content": content.hex(), "type": "binary"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")

@router.get("/v1/files/transcripts")
async def list_transcript_files():
    """List all transcript files in the evidence directory."""
    try:
        if not _EVIDENCE_PATH.exists():
            return []

        files = []
        for item in _EVIDENCE_PATH.iterdir():
            if item.is_file():
                stat = item.stat()
                files.append({
                    "name": item.name,
                    "path": str(item),
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                    "type": "transcript",
                    "category": "evidence"
                })

        return files

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing transcript files: {str(e)}")

@router.get("/v1/files/laws")
async def list_law_files():
    """List all law/regulation files in the laws directory."""
    try:
        if not _LAWS_PATH.exists():
            return []

        files = []
        for item in _LAWS_PATH.iterdir():
            if item.is_file():
                stat = item.stat()
                files.append({
                    "name": item.name,
                    "path": str(item),
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                    "type": "law",
                    "category": "admin_regulatory"
                })

        return files

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing law files: {str(e)}")

@router.post("/v1/files/upload/transcript")
async def upload_transcript_file(file: UploadFile = File(...)):
    """Upload a transcript file to the evidence directory."""
    try:
        _EVIDENCE_PATH.mkdir(parents=True, exist_ok=True)
        file_path = _EVIDENCE_PATH / file.filename
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        return {
            "message": "Transcript file uploaded successfully",
            "filename": file.filename,
            "path": str(file_path),
            "size": len(content),
            "type": "transcript"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading transcript: {str(e)}")

@router.post("/v1/files/upload/law")
async def upload_law_file(file: UploadFile = File(...)):
    """Upload a law/regulation file to the laws directory."""
    try:
        _LAWS_PATH.mkdir(parents=True, exist_ok=True)
        file_path = _LAWS_PATH / file.filename
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        return {
            "message": "Law file uploaded successfully",
            "filename": file.filename,
            "path": str(file_path),
            "size": len(content),
            "type": "law"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading law file: {str(e)}")

@router.post("/v1/files/summarize")
async def summarize_files(req: SummarizeRequest):
    if not req.file_ids:
        raise HTTPException(status_code=400, detail="file_ids must contain at least one id")
    # Use async operations here
    file_contents = []
    for file_id in req.file_ids:
        content = await get_file_content_async(file_id)  # Async function
        file_contents.append(content)
    
    summary = await generate_summary_async("\n\n".join(file_contents), req.model, req.temperature)
    
    return {
        "summary": summary,
        "model": req.model,
        "temperature": req.temperature,
        "max_tokens": req.max_tokens,
        "file_count": len(req.file_ids),
        "status": "success"
    }

@router.get("/api/transcripts")
async def get_transcripts() -> List[Dict[str, Any]]:
    """Get all transcript JSON files and return as array"""
    try:
        transcripts = []
        
        print(f"Looking for transcripts in: {_TRANSCRIPTS_PATH}")
        
        if not os.path.exists(_TRANSCRIPTS_PATH):
            print(f"Transcripts path doesn't exist: {_TRANSCRIPTS_PATH}")
            return []
        
        files = os.listdir(_TRANSCRIPTS_PATH)
        json_files = [f for f in files if f.endswith('.json')]
        print(f"Found {len(json_files)} JSON files: {json_files}")
        
        for filename in json_files:
            file_path = os.path.join(_TRANSCRIPTS_PATH, filename)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Ensure the data has the expected structure
                transcript = {
                    "filename": filename.replace('.json', ''),
                    "date": data.get("date", ""),
                    "audio": f"/api/audio/{filename.replace('.json', '.mp3')}",
                    "content": []
                }
                
                # Handle different transcript formats
                content_data = data.get("content", []) or data.get("segments", []) or data.get("transcript", [])
                
                if isinstance(content_data, list):
                    for segment in content_data:
                        processed_segment = {
                            "start": float(segment.get("start", 0)),
                            "end": float(segment.get("end", 0)),
                            "speaker": segment.get("speaker", "Unknown"),
                            "text": segment.get("text", ""),
                            "timestamp": format_time(float(segment.get("start", 0)))
                        }
                        transcript["content"].append(processed_segment)
                
                transcripts.append(transcript)
                print(f"Processed transcript: {filename} with {len(transcript['content'])} segments")
                
            except Exception as e:
                print(f"Error reading {filename}: {e}")
                continue
        
        print(f"Returning {len(transcripts)} transcripts")
        return transcripts
        
    except Exception as e:
        print(f"Error loading transcripts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/audio/{filename}")
async def get_audio_file(filename: str):
    try:
        # Validate file extension
        if not filename.lower().endswith(('.mp3', '.wav', '.ogg')):
            raise HTTPException(status_code=400, detail="Invalid audio file format")
        
        # Construct file path
        audio_path = os.path.join(settings.audio_storage_path, filename)
        
        # Check if file exists
        if not os.path.exists(audio_path):
            raise HTTPException(status_code=404, detail="Audio file not found")
        
        # Return file
        return FileResponse(audio_path, media_type="audio/mpeg", filename=filename)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve audio: {str(e)}")

def format_time(seconds: float) -> str:
    """Format seconds to MM:SS format"""
    if not isinstance(seconds, (int, float)) or seconds < 0:
        return "0:00"
    
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"

def extract_eml_info(path):
    with open(path, 'rb') as f:
        msg = BytesParser(policy=policy.default).parse(f)
    headers = {k: v for k, v in msg.items()}
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                body += part.get_content()
    else:
        body = msg.get_content()
    # Optionally, extract attachment info
    attachments = []
    for part in msg.iter_attachments():
        attachments.append({
            "filename": part.get_filename(),
            "content_type": part.get_content_type(),
            "size": len(part.get_content())
        })
    return {
        "headers": headers,
        "body": body,
        "attachments": attachments
    }

