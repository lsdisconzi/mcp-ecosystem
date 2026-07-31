import os
import warnings

# Suppress HuggingFace Hub unauthenticated warnings
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
warnings.filterwarnings("ignore", message=".*unauthenticated requests.*")
warnings.filterwarnings("ignore", message=".*HF_TOKEN.*")

import json
import time
import uuid
import shutil
import logging
import httpx
from pathlib import Path
from typing import List, Optional, Dict, Any, Union
from datetime import datetime
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse, HTMLResponse, RedirectResponse, Response
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
from pathlib import Path

# Load shared env first (secrets — override=True so file values always win),
# then local overrides for non-secret service settings.
_shared_env = Path(__file__).resolve().parent.parent / "_shared" / ".env"
load_dotenv(_shared_env, override=True)
load_dotenv(override=True)  # local .env overrides
from pydantic import BaseModel

# Import Core Services and Schemas
from core.assistant import AssistantCore
from config.settings import settings
from data.tools import registry  # Use the singleton registry
from api.tools import router as tools_router

from api.schemas import (
    FileListResponse,
    FileMetadata,
    DeleteResponse,
    AssistantListResponse,
    AssistantObject,
    ToolListResponse,
    HealthResponse,
    GenericSuccessResponse,
    FileReadResponse,
    DirectoryListResponse,
    QdrantConnectionResponse,
    QdrantCollectionsResponse,
    QdrantSearchResponse,
    CreateCollectionRequest,
#     ToolExecutionRequest,
#    ToolExecutionResponse,
    KnowledgeQueryRequest,
    AttachFileRequest,
    AssignToolRequest,
    DeepSeekRequest,
    DeepSeekResponse,
)

# Import Routers
from api.files import router as files_router
from api.assistants import router as assistants_router, get_assistant_from_file, save_assistant_to_file
from api.chat import router as chat_router
from routes.qdrant_router import router as qdrant_router
from api.knowledge_router import router as knowledge_router
from api.prompt_engineer import router as prompt_engineer_router
from routes import ingestion
from routes.legal_ingestion import router as legal_ingestion_router
from routes.legal_doc_ingestion_v2 import router as legal_doc_ingestion_v2_router
from routes.transcript_ingestion import router as transcript_ingestion_router
from routes.neo4j_router import router as neo4j_router
from api.openclaude_router import router as openclaude_router
from services.watch_frameworks import FrameworkHandler



logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Initialize global HTTP client for reuse
global_client = httpx.AsyncClient(timeout=httpx.Timeout(360.0, connect=10.0))

# Restrict file-read endpoints to the project directory (S1 — path traversal fix)
_ALLOWED_FILES_BASE = Path(os.path.dirname(os.path.abspath(__file__))).resolve()
_PINOCCHIO_TRANSCRIPTS_PATH = Path(os.getenv("TRANSCRIPTS_DIR", "data/documents/transcripts"))
if not _PINOCCHIO_TRANSCRIPTS_PATH.is_absolute():
    _PINOCCHIO_TRANSCRIPTS_PATH = (_ALLOWED_FILES_BASE / _PINOCCHIO_TRANSCRIPTS_PATH).resolve()


def _dedupe_urls(urls: List[str]) -> List[str]:
    ordered: List[str] = []
    for url in urls:
        candidate = str(url or "").strip()
        if candidate and candidate not in ordered:
            ordered.append(candidate)
    return ordered


def _localhost_variants(url: str) -> List[str]:
    variants = [url]
    if "localhost" in url:
        variants.append(url.replace("localhost", "127.0.0.1"))
    elif "127.0.0.1" in url:
        variants.append(url.replace("127.0.0.1", "localhost"))
    return _dedupe_urls(variants)


def _pinocchio_transcribe_candidates(suffix: str = "") -> List[str]:
    base = os.getenv(
        "PINOCCHIO_TRANSCRIBE_UPSTREAM_URL",
        "http://127.0.0.1:8039/api/diarization/transcribe",
    ).strip()
    if not base:
        base = "http://127.0.0.1:8039/api/diarization/transcribe"
    candidate = f"{base.rstrip('/')}{suffix}" if suffix else base
    return _localhost_variants(candidate)


def _pinocchio_pyannote_candidates() -> List[str]:
    env_value = os.getenv("PINOCCHIO_PYANNOTE_UPSTREAM_URL", "").strip()
    if env_value:
        return _localhost_variants(env_value)

    base = _pinocchio_transcribe_candidates()[0].rstrip("/")
    if base.endswith("/transcribe"):
        base = f"{base}/pyannote"
    else:
        base = f"{base}/transcribe/pyannote"
    return _localhost_variants(base)


def _pinocchio_voiceprint_candidates() -> List[str]:
    env_value = os.getenv("PINOCCHIO_VOICEPRINT_UPSTREAM_URL", "").strip()
    if env_value:
        return _localhost_variants(env_value)

    return _dedupe_urls(
        _localhost_variants("http://127.0.0.1:8039/api/pinocchio/voiceprint_from_file")
        + _localhost_variants("http://127.0.0.1:8039/api/diarization/voiceprint_from_file")
    )


async def _proxy_pinocchio_form_post(
    request: Request,
    upstream_urls: List[str],
    endpoint_name: str,
) -> Response:
    raw_body = await request.body()
    content_type = request.headers.get("content-type", "")
    if not content_type:
        raise HTTPException(status_code=400, detail="Missing Content-Type header")

    forward_headers = {
        "content-type": content_type,
    }

    last_error: Optional[Exception] = None
    for url in _dedupe_urls(upstream_urls):
        try:
            response = await global_client.post(
                url,
                content=raw_body,
                headers=forward_headers,
                timeout=httpx.Timeout(900.0, connect=10.0),
            )
            content_type = response.headers.get("content-type", "application/json")
            return Response(
                content=response.content,
                status_code=response.status_code,
                media_type=content_type,
            )
        except Exception as exc:
            last_error = exc

    raise HTTPException(
        status_code=502,
        detail=f"Failed to reach upstream for {endpoint_name}: {last_error}",
    )


def _normalize_transcript_payload(raw: Dict[str, Any], transcript_id: str) -> Dict[str, Any]:
    segments = raw.get("segments")
    if not isinstance(segments, list):
        content_segments = raw.get("content") if isinstance(raw.get("content"), list) else []
        segments = []
        for i, seg in enumerate(content_segments):
            if not isinstance(seg, dict):
                continue
            start = seg.get("start", 0)
            end = seg.get("end", start)
            try:
                start = float(start)
            except Exception:
                start = 0.0
            try:
                end = float(end)
            except Exception:
                end = start
            segments.append(
                {
                    "index": i,
                    "speaker": seg.get("speaker", "SPEAKER_00"),
                    "start": start,
                    "end": end,
                    "duration": max(0.0, end - start),
                    "text": seg.get("text", ""),
                }
            )

    payload = dict(raw)
    payload["transcript_id"] = str(raw.get("transcript_id") or transcript_id)
    payload["filename"] = raw.get("filename") or raw.get("source_file") or transcript_id
    payload["segments"] = segments or []
    payload.setdefault("provider", "local")
    payload.setdefault("timestamp", datetime.now().isoformat())
    return payload

def _safe_file_path(raw: str) -> Path:
    """Resolve raw path; raise 403 if it escapes the project directory."""
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = _ALLOWED_FILES_BASE / candidate
    resolved = candidate.resolve()
    if not str(resolved).startswith(str(_ALLOWED_FILES_BASE)):
        raise HTTPException(status_code=403, detail="Access denied: path is outside the allowed directory")
    return resolved

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle."""
    logger.info("Starting up Ollama Assistants API...")
    yield
    await global_client.aclose()
    logger.info("Global HTTP client closed")


# Initialize FastAPI app
app = FastAPI(
    title="Ollama-Compatible Assistants API",
    version="1.0.0",
    description="""A comprehensive API for AI assistants with file management, 
    tool integration, and knowledge base capabilities.""",
    docs_url=None,
    redoc_url=None,
    openapi_url="/openapi.json",
    servers=[
        {"url": "http://localhost:8066", "description": "Development server"},
    ],
    contact={
        "name": "API Support",
        "url": "http://localhost:8066/docs",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
    lifespan=lifespan,
)

# Add CORS middleware — use ALLOWED_ORIGINS env var instead of wildcard (S3)
_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:8066")
# Handle case where it might be in the ['url1', 'url2'] format from .env
_origins_env = _origins_env.replace('[', '').replace(']', '').replace('"', '').replace('\n', '').replace(' ', '')
_allowed_origins_list = [o for o in _origins_env.split(",") if o]

_origin_patterns = []
for o in _allowed_origins_list:
    if '*' in o:
        pattern = o.replace('.', '\\.').replace('*', '.*')
        _origin_patterns.append(f"^{pattern}$")
    else:
        pattern = o.replace('.', '\\.')
        _origin_patterns.append(f"^{pattern}$")

_allow_origin_regex = "|".join(_origin_patterns) if _origin_patterns else None

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SessionMiddleware, secret_key=settings.jwt_secret)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- Core Services Initialization ---

# Initialize Assistant Core
try:
    assistant = AssistantCore()
    logger.info("✅ AssistantCore loaded successfully")
except Exception as e:
    logger.error(f"❌ Failed to load AssistantCore: {e}")
    assistant = None

# Expose assistant via app.state so routers (e.g. api/chat.py) can access it
app.state.assistant = assistant

# Tool Registry is already initialized via import
# logger.info(f"🔧 Tool registry initialized with {len(registry.list_tools())} tools")

# --- Router Inclusion ---

# Include core routers
app.include_router(chat_router)
app.include_router(files_router)
app.include_router(assistants_router)
app.include_router(qdrant_router)
app.include_router(knowledge_router, prefix="/v1/knowledge", tags=["knowledge"])
app.include_router(tools_router, prefix="/v1")
app.include_router(prompt_engineer_router)
app.include_router(ingestion.router)
app.include_router(legal_ingestion_router)
app.include_router(legal_doc_ingestion_v2_router)
app.include_router(transcript_ingestion_router)
app.include_router(neo4j_router)
app.include_router(openclaude_router)

# --- Ecosystem report endpoint ---
# Serves the latest ecosystem orchestration report so the Olivia workspace
# can fetch it at startup to discover available MCP tools and endpoints.
_ECOSYSTEM_REPORT_PATH = os.getenv(
    "ECOSYSTEM_REPORT_PATH",
    str(Path("/Users/dev/_sell/mcp-ecosystem/_ecosystem-reports/ecosystem_report_latest.md"))
)

@app.get("/v1/ecosystem/report", tags=["Ecosystem"], summary="Get latest ecosystem MCP report")
async def get_ecosystem_report():
    """Return the latest ecosystem orchestration report as markdown.

    The report lists all 7 ecosystem projects, their MCP servers (with ports),
    available tools, human interfaces, and configuration parameters.
    """
    report_path = Path(_ECOSYSTEM_REPORT_PATH).resolve()
    if not report_path.is_file():
        return JSONResponse(
            status_code=404,
            content={"error": "Ecosystem report not found"}
        )
    try:
        content = report_path.read_text(encoding="utf-8")
        return Response(content=content, media_type="text/markdown")
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to read report: {exc}"}
        )

@app.get("/v1/ecosystem/metadata", tags=["Ecosystem"], summary="Get ecosystem metadata JSON")
async def get_ecosystem_metadata():
    """Return the raw ecosystem metadata JSON with the host substituted.

    The 'host' field is resolved from ECOSYSTEM_HOST env var (or defaults
    to localhost) so consumers always get reachable URLs.
    """
    meta_path = Path("/Users/dev/_sell/olivia/config/ecosystem_metadata.json")
    if not meta_path.is_file():
        return JSONResponse(status_code=404, content={"error": "Metadata not found"})
    try:
        content = meta_path.read_text(encoding="utf-8")
        host = os.getenv("ECOSYSTEM_HOST", "[IP_ADDRESS]")
        content = content.replace("{{ECOSYSTEM_HOST}}", host)
        # Return as JSON with the right content-type
        data = json.loads(content)
        return JSONResponse(content=data)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


# --- Manus proxy ---
# Forwards /manus/{path} → http://localhost:8078/{path} to avoid browser CORS
# restrictions when the Manus service runs on a different port.

_MANUS_ORIGIN = os.getenv("MANUS_SERVICE_URL", "http://localhost:8078")

@app.api_route(
    "/manus/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    tags=["Manus Proxy"],
    include_in_schema=False,
)
async def manus_proxy(path: str, request: Request) -> Response:
    url = f"{_MANUS_ORIGIN}/{path}"
    params = dict(request.query_params)
    body = await request.body()
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length")
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        upstream = await client.request(
            method=request.method,
            url=url,
            params=params,
            content=body,
            headers=headers,
        )
    # Stream-friendly: return bytes as-is
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=dict(upstream.headers),
        media_type=upstream.headers.get("content-type"),
    )


# Conditional Threads Router
try:
    from api.threads import router as threads_router
    app.include_router(threads_router)
    logger.info("✅ Threads router included")
except ImportError as e:
    logger.warning(f"⚠️ Threads router not available: {e}")

# --- Helper Functions ---

async def attach_file_to_assistant_logic(assistant_id: str, file_id: str):
    """Logic to attach a file to an assistant"""
    assistant_data = get_assistant_from_file(assistant_id)
    if not assistant_data:
        raise HTTPException(status_code=404, detail="Assistant not found")
    
    if "file_ids" not in assistant_data:
        assistant_data["file_ids"] = []
    
    if file_id not in assistant_data["file_ids"]:
        assistant_data["file_ids"].append(file_id)
        save_assistant_to_file(assistant_data)

def truncate_text(text: str, max_length: int = 32000) -> str:
    if isinstance(text, str) and len(text) > max_length:
        return text[:max_length]
    return text
 
# --- Debug Endpoints ---

@app.get("/debug-schema", tags=["Debug"])
async def debug_schema():
    """Check if OpenAPI schema is generated correctly"""
    schema = app.openapi()
    return {
        "schema_available": bool(schema),
        "endpoints_count": len(app.routes),
        "openapi_version": schema.get("openapi") if schema else None,
        "paths_count": len(schema.get("paths", {})) if schema else 0
    }

@app.get("/debug-routes", tags=["Debug"])
async def debug_routes():
    """List all registered routes"""
    routes = []
    for route in app.routes:
        routes.append({
            "path": getattr(route, "path", None),
            "name": getattr(route, "name", None),
            "methods": list(getattr(route, "methods", [])) if hasattr(route, "methods") else None
        })
    return {"routes": routes, "count": len(routes)}

# --- API Endpoints ---

@app.get("/health", tags=["System"], response_model=HealthResponse)
async def health_check():
    """System health check endpoint"""
    return {
        "status": "healthy",
        "service": "garage",
        "timestamp": datetime.now().isoformat()
    }

@app.post("/api/frameworks/regenerate-list", tags=["System"])
async def regenerate_framework_list():
    """Regenerate static/js/legal_frameworks/framework_list.json on demand."""
    try:
        handler = FrameworkHandler()
        await asyncio.to_thread(handler.update_framework_list)

        output_path = Path("static/js/legal_frameworks/framework_list.json")
        framework_count = 0
        if output_path.exists():
            with open(output_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                framework_count = len(data) if isinstance(data, dict) else 0

        return {
            "success": True,
            "message": "framework_list.json regenerated",
            "path": str(output_path),
            "framework_count": framework_count,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Failed to regenerate framework list: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to regenerate framework list: {e}")

@app.get("/", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
async def serve_root(request: Request):
    """Serve the root UI"""
    return templates.TemplateResponse("garage.html", {"request": request})


@app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
async def serve_favicon():
    """Redirect legacy favicon requests to the static SVG icon."""
    return RedirectResponse(url="/static/favicon.svg", status_code=307)

@app.get("/qdrant", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
async def serve_qdrant(request: Request):
    """Serve the Qdrant UI"""
    return templates.TemplateResponse("qdrant.html", {"request": request})

@app.get("/garage", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
async def serve_garage(request: Request):
    """Serve the Garage UI"""
    return templates.TemplateResponse("garage.html", {"request": request})

@app.get("/pinocchio", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
async def serve_pinocchio(request: Request):
    """Serve the Pinocchio UI"""
    return templates.TemplateResponse("pinocchio.html", {"request": request})


@app.post("/api/pinocchio/transcribe", tags=["Pinocchio"], include_in_schema=False)
async def proxy_pinocchio_transcribe(request: Request):
    """Proxy same-origin Pinocchio transcribe requests to the diarization backend."""
    return await _proxy_pinocchio_form_post(
        request,
        _pinocchio_transcribe_candidates(),
        "pinocchio transcribe",
    )


@app.post("/api/pinocchio/transcribe/async", tags=["Pinocchio"], include_in_schema=False)
async def proxy_pinocchio_transcribe_async(request: Request):
    """Proxy async transcribe calls when the frontend points to /api/pinocchio/transcribe/async."""
    return await _proxy_pinocchio_form_post(
        request,
        _pinocchio_transcribe_candidates("/async"),
        "pinocchio transcribe async",
    )


@app.post("/api/pinocchio/transcribe/pyannote", tags=["Pinocchio"], include_in_schema=False)
async def proxy_pinocchio_transcribe_pyannote(request: Request):
    """Proxy pyannote transcribe requests to an upstream service."""
    return await _proxy_pinocchio_form_post(
        request,
        _pinocchio_pyannote_candidates(),
        "pinocchio pyannote transcribe",
    )


@app.post("/api/pinocchio/voiceprint_from_file", tags=["Pinocchio"], include_in_schema=False)
async def proxy_pinocchio_voiceprint(request: Request):
    """Proxy voiceprint extraction requests to an upstream service."""
    return await _proxy_pinocchio_form_post(
        request,
        _pinocchio_voiceprint_candidates(),
        "pinocchio voiceprint",
    )


@app.get("/api/pinocchio/transcripts", tags=["Pinocchio"], include_in_schema=False)
async def list_pinocchio_transcript_ids():
    """Return transcript ids expected by the Pinocchio frontend sync flow."""
    if not _PINOCCHIO_TRANSCRIPTS_PATH.exists():
        return []

    json_files = [p for p in _PINOCCHIO_TRANSCRIPTS_PATH.glob("*.json") if p.is_file()]
    json_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.stem for p in json_files]


@app.get("/api/pinocchio/transcripts/{transcript_id}", tags=["Pinocchio"], include_in_schema=False)
async def get_pinocchio_transcript(transcript_id: str):
    """Return one transcript payload in a Pinocchio-friendly shape."""
    tid = str(transcript_id or "").strip()
    if not tid or "/" in tid or "\\" in tid:
        raise HTTPException(status_code=400, detail="Invalid transcript id")

    candidates = [
        _PINOCCHIO_TRANSCRIPTS_PATH / f"{tid}.json",
        _PINOCCHIO_TRANSCRIPTS_PATH / tid,
    ]
    transcript_path = next((p for p in candidates if p.exists() and p.is_file()), None)
    if not transcript_path:
        raise HTTPException(status_code=404, detail="Transcript not found")

    try:
        with open(transcript_path, "r", encoding="utf-8") as fp:
            payload = json.load(fp)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read transcript: {exc}")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Transcript payload must be a JSON object")

    return _normalize_transcript_payload(payload, tid)


# --- File Management Endpoints ---

@app.get("/v1/files", tags=["Files"], response_model=FileListResponse)
async def list_files():
    """List all uploaded files"""
    try:
        files_dir = Path(settings.file_storage_path)
        if not files_dir.exists():
            return {"object": "list", "data": []}

        files_data = []
        for meta_file in files_dir.glob("*.json"):
            try:
                with open(meta_file, "r") as f:
                    meta = json.load(f)
                    if "id" in meta and "filename" in meta:
                        # Back-fill physical_path for files uploaded before it was stored
                        if not meta.get("physical_path"):
                            fid = meta["id"]
                            candidates = [
                                p for p in files_dir.glob(f"{fid}*")
                                if not p.suffix == ".json"
                            ]
                            if candidates:
                                meta["physical_path"] = str(candidates[0])
                                with open(meta_file, "w") as wf:
                                    json.dump(meta, wf, indent=2)
                        files_data.append(meta)
            except Exception:
                continue

        return {"object": "list", "data": files_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/files/{file_id}/content", tags=["Files"], response_class=FileResponse)
async def get_file_content(file_id: str):
    """Download file content"""
    try:
        files_dir = Path(settings.file_storage_path)
        metadata_path = files_dir / f"{file_id}.json"
        
        if not metadata_path.exists():
            metadata_path = files_dir / f"{file_id}_metadata.json"
            if not metadata_path.exists():
                raise HTTPException(status_code=404, detail="File metadata not found")
        
        with open(metadata_path, "r") as f:
            metadata = json.load(f)
            
        physical_path = metadata.get("physical_path")
        if not physical_path or not os.path.exists(physical_path):
            # Try extensionless match first, then glob for any extension
            candidate = files_dir / file_id
            if candidate.exists():
                physical_path = str(candidate)
            else:
                matches = [p for p in files_dir.glob(f"{file_id}*") if p.suffix != ".json"]
                if not matches:
                    raise HTTPException(status_code=404, detail="Physical file not found")
                physical_path = str(matches[0])

        return FileResponse(
            path=physical_path,
            filename=metadata.get("filename", file_id),
            media_type=metadata.get("content_type", "application/octet-stream")
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving file: {str(e)}")

@app.delete("/v1/files/{file_id}", tags=["Files"], response_model=DeleteResponse)
async def delete_file(file_id: str):
    """Delete a file"""
    try:
        files_dir = Path(settings.file_storage_path)
        
        metadata_path = files_dir / f"{file_id}.json"
        if not metadata_path.exists():
            metadata_path = files_dir / f"{file_id}_metadata.json"
        
        physical_path = None
        if metadata_path.exists():
            with open(metadata_path, "r") as f:
                data = json.load(f)
                physical_path = data.get("physical_path")
            os.remove(metadata_path)
        
        if not physical_path:
            physical_path = files_dir / file_id
            
        if physical_path and os.path.exists(physical_path):
            os.remove(physical_path)
            
        return {"id": file_id, "object": "file", "deleted": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")

@app.post("/v1/assistants/{assistant_id}/tools", tags=["Assistants"], response_model=GenericSuccessResponse)
async def assign_tool_to_assistant(assistant_id: str, payload: AssignToolRequest):
    """Assign a tool to an assistant"""
    tool_id = payload.tool_id
    if not tool_id:
        raise HTTPException(status_code=400, detail="tool_id required")
        
    assistant_data = get_assistant_from_file(assistant_id)
    if not assistant_data:
        raise HTTPException(status_code=404, detail="Assistant not found")
        
    if "tools" not in assistant_data:
        assistant_data["tools"] = []
        
    def get_tool_name(t):
        if isinstance(t, str):
            return t
        if isinstance(t, dict):
            if "function" in t:
                return t["function"].get("name")
            return t.get("name")
        return None

    if any(get_tool_name(t) == tool_id for t in assistant_data["tools"]):
        return {"success": True, "assistant": assistant_data}
        
    # Get tool from the singleton registry
    tool = registry.get(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
        
    # Build tool definition from the tool object
    tool_def = tool.to_schema()
    
    assistant_data["tools"].append(tool_def)
    save_assistant_to_file(assistant_data)
    
    return {"success": True, "assistant": assistant_data}


# --- DeepSeek Integration ---

@app.post("/v1/assistants/{assistant_id}/deepseek", tags=["DeepSeek"])
async def deepseek_proxy(assistant_id: str, request: Request):
    """Proxy requests to DeepSeek API"""
    try:
        payload = await request.json()
        
        if "messages" in payload:
            for message in payload["messages"]:
                if "content" in message:
                    message["content"] = truncate_text(message["content"])

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=360) as client:
            resp = await client.post(
                "http://localhost:11436/v1/chat/completions",
                headers=headers,
                json=payload
            )
            
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
                
            return resp.json()
            
    except Exception as e:
        logger.error(f"DeepSeek proxy error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/deepseek-engineer/chat", tags=["DeepSeek"], response_model=DeepSeekResponse)
async def deepseek_engineer_chat(request: DeepSeekRequest):
    """DeepSeek Engineer Chat Endpoint"""
    try:
        messages = request.messages

        payload = {
            "model": "llama3.2:1b",
            "messages": [msg.model_dump() if hasattr(msg, 'model_dump') else msg for msg in messages],
            "max_tokens": 8000,
            "stream": False
        }

        headers = {
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=800.0) as client:
            resp = await client.post(
                "http://localhost:11436/v1/chat/completions",
                headers=headers,
                json=payload
            )

        if resp.status_code != 200:
            return JSONResponse(content={'error': f"Ollama API error: {resp.text}"}, status_code=resp.status_code)

        result = resp.json()
        assistant_response = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        reasoning_content = result.get("choices", [{}])[0].get("message", {}).get("reasoning_content", None)

        return JSONResponse(content={
            'response': assistant_response,
            'reasoning': reasoning_content,
        }, status_code=200)

    except Exception as e:
        logger.error(f"DeepSeek Engineer error: {e}")
        return JSONResponse(content={'error': str(e)}, status_code=500)
    



# --- Exception Handlers ---

from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error(f"Validation error: {exc}")
    return PlainTextResponse(str(exc), status_code=422)

@app.exception_handler(Exception)
async def universal_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(status_code=500, content={"error": "Internal server error", "detail": str(exc)})

@app.get("/redoc", include_in_schema=False)
async def custom_redoc_html():
    """Custom ReDoc documentation"""
    return get_redoc_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - ReDoc",
        redoc_js_url="https://cdn.jsdelivr.net/npm/redoc@latest/bundles/redoc.standalone.js",
    )

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    """Custom Swagger UI documentation"""
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - Swagger UI",
        swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
    )

########## DEEPSEEK ENDPOINTS ##############
############################################
@app.post("/v1/assistants/deepseek-stream-proxy")
async def deepseek_streaming_proxy(request: Request):
    payload = await request.json()
    is_streaming = bool(payload.get("stream", False))
    requested_model = str(payload.get("model", "")).strip().lower()

    external_deepseek_models = {
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "deepseek-v3",
        "deepseek-v4",
        # Legacy aliases — accepted by DeepSeek API until 2026-07-24
        "deepseek-chat",
        "deepseek-reasoner",
    }
    use_external_deepseek = requested_model in external_deepseek_models

    if use_external_deepseek and not DEEPSEEK_API_KEY:
        raise HTTPException(
            status_code=400,
            detail=(
                "DeepSeek assistant requires DEEPSEEK_API_KEY for external routing. "
                "Set DEEPSEEK_API_KEY or switch the assistant to a local Ollama model."
            ),
        )

    if use_external_deepseek:
        deepseek_base_url = (os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
        upstream_url = f"{deepseek_base_url}/chat/completions"
        upstream_name = "DeepSeek"
    else:
        upstream_url = "http://localhost:11436/v1/chat/completions"
        upstream_name = "Ollama"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if use_external_deepseek:
        headers["Authorization"] = f"Bearer {DEEPSEEK_API_KEY}"

    # Truncate long inputs
    if "messages" in payload and isinstance(payload["messages"], list):
        for message in payload["messages"]:
            if isinstance(message.get("content"), str):
                message["content"] = truncate_text(message["content"])

    async def stream_generator():
        try:
            async with global_client.stream(
                "POST",
                upstream_url,
                headers=headers,
                json=payload
            ) as response:

                if response.status_code != 200:
                    err_body = await response.aread()
                    err_text = err_body.decode("utf-8", errors="ignore")
                    err_json = None
                    try:
                        err_json = json.loads(err_text)
                    except Exception:
                        pass

                    detail = err_json if err_json is not None else err_text[:1000]
                    yield (json.dumps({"error": {"message": f"{upstream_name} API error {response.status_code}", "details": detail}}) + "\n").encode("utf-8")
                    return

                async for text_chunk in response.aiter_text():
                    yield text_chunk if text_chunk.endswith("\n") else text_chunk + "\n"

        except httpx.TimeoutException:
            yield (json.dumps({"error": {"message": "Request to Ollama timed out"}}) + "\n").encode("utf-8")
        except httpx.RequestError as e:
            yield (json.dumps({"error": {"message": f"Ollama connection error: {str(e)}"}}) + "\n").encode("utf-8")
        except Exception as e:
            logger.exception("DeepSeek streaming proxy error")
            yield (json.dumps({"error": {"message": "Internal server error during streaming"}}) + "\n").encode("utf-8")

    if is_streaming:
        return StreamingResponse(stream_generator(), media_type="application/x-ndjson")
    else:
        try:
            response = await global_client.post(
                upstream_url,
                headers=headers,
                json=payload
            )

            if response.status_code != 200:
                try:
                    err = response.json()
                    detail = err.get("message") or json.dumps(err)
                except Exception:
                    detail = response.text[:1000]
                raise HTTPException(status_code=response.status_code, detail=f"{upstream_name} API error {response.status_code}: {detail}")

            return response.json()

        except HTTPException:
            # Re-raise HTTP exceptions we intentionally raised (e.g., 4xx from DeepSeek)
            raise
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Request to Ollama timed out")
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Ollama connection error: {str(e)}")
        except Exception as e:
            logger.exception("DeepSeek proxy error (non-streaming)")
            raise HTTPException(status_code=500, detail="Internal server error")


########## FRONTEND GATEWAY — /api/deepseek/* ##############
# Routes frontend AI calls to the local Ollama instance.
############################################################
@app.get("/api/deepseek/{path:path}", tags=["Gateway"], operation_id="deepseek_gateway_get")
@app.post("/api/deepseek/{path:path}", tags=["Gateway"], operation_id="deepseek_gateway_post")
@app.put("/api/deepseek/{path:path}", tags=["Gateway"], operation_id="deepseek_gateway_put")
@app.delete("/api/deepseek/{path:path}", tags=["Gateway"], operation_id="deepseek_gateway_delete")
@app.options(
    "/api/deepseek/{path:path}",
    tags=["Gateway"],
    operation_id="deepseek_gateway_options",
    include_in_schema=False,
)
async def deepseek_gateway(path: str, request: Request):
    """Transparent proxy: /api/deepseek/{path} → http://localhost:11436/{path}

    Routes all frontend AI requests to the local Ollama instance.
    """
    forwarded_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length")
    }

    target_url = f"http://localhost:11436/{path}"
    query = request.url.query
    if query:
        target_url = f"{target_url}?{query}"

    body = await request.body()

    try:
        # Detect streaming intent from body JSON before forwarding
        is_streaming = False
        if body:
            try:
                parsed = json.loads(body)
                is_streaming = bool(parsed.get("stream", False))
            except Exception:
                pass

        if is_streaming:
            async def _stream_gen():
                async with global_client.stream(
                    request.method,
                    target_url,
                    headers=forwarded_headers,
                    content=body,
                ) as resp:
                    if resp.status_code != 200:
                        err = await resp.aread()
                        yield (json.dumps({"error": {"message": f"Ollama error {resp.status_code}", "details": err.decode("utf-8", errors="ignore")[:500]}}) + "\n").encode()
                        return
                    async for chunk in resp.aiter_bytes():
                        yield chunk
            return StreamingResponse(_stream_gen(), media_type="application/x-ndjson")

        resp = await global_client.request(
            request.method,
            target_url,
            headers=forwarded_headers,
            content=body,
        )

        if resp.status_code not in (200, 201):
            raise HTTPException(status_code=resp.status_code, detail=resp.text[:1000])

        return JSONResponse(content=resp.json(), status_code=resp.status_code)

    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="DeepSeek gateway: request timed out")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"DeepSeek gateway: connection error: {str(e)}")
    except Exception as e:
        logger.exception("DeepSeek gateway error")
        raise HTTPException(status_code=500, detail="DeepSeek gateway: internal server error")
