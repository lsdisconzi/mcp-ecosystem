from typing import Dict, List, Optional, Union, Any
from pydantic import BaseModel, Field
from config.settings import settings

# ============================================================================
# SYSTEM & HEALTH
# ============================================================================

class HealthResponse(BaseModel):
    """System health check response"""
    status: str
    service: str
    timestamp: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "healthy",
                "service": "garage",
                "timestamp": "2024-01-15T10:30:00Z"
            }
        }

# ============================================================================
# FILE OPERATIONS
# ============================================================================

class FileMetadata(BaseModel):
    """File metadata object"""
    id: str
    filename: str
    content_type: Optional[str] = None
    purpose: str
    bytes: int
    created_at: int
    physical_path: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "file-abc123",
                "filename": "example.pdf",
                "content_type": "application/pdf",
                "purpose": "assistants",
                "bytes": 1024,
                "created_at": 1672531200,
                "physical_path": "/uploads/example.pdf"
            }
        }

class FileObject(BaseModel):
    """OpenAI-compatible file object"""
    id: str
    object: str = "file"
    bytes: int
    created_at: int
    filename: str
    purpose: str
    content_type: Optional[str] = None
    status: str = "processed"
    sha256: Optional[str] = None
    physical_path: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "file-abc123",
                "object": "file",
                "bytes": 1024,
                "created_at": 1672531200,
                "filename": "regulation.pdf",
                "purpose": "assistants",
                "content_type": "application/pdf",
                "status": "processed",
                "sha256": "abc123..."
            }
        }

class FileListResponse(BaseModel):
    """List of files response"""
    object: str = "list"
    data: List[FileObject]
    
    class Config:
        json_schema_extra = {
            "example": {
                "object": "list",
                "data": [
                    {
                        "id": "file-abc123",
                        "object": "file",
                        "bytes": 1024,
                        "created_at": 1672531200,
                        "filename": "regulation.pdf",
                        "purpose": "assistants",
                        "content_type": "application/pdf",
                        "status": "processed",
                        "sha256": "abc123..."
                    }
                ]
            }
        }

class FileReadResponse(BaseModel):
    """Response for reading file content"""
    path: str
    content: str
    size: int
    
    class Config:
        json_schema_extra = {
            "example": {
                "path": "/data/evidence/transcript_001.json",
                "content": "{\"speakers\": [\"John\", \"Jane\"], \"conversation\": [...]}",
                "size": 2048
            }
        }

class FileListItem(BaseModel):
    """Individual file in a directory listing"""
    name: str
    size: int
    modified: str
    is_directory: Optional[bool] = False

class DirectoryListResponse(BaseModel):
    """Response for directory listing"""
    path: str
    files: List[FileListItem]
    count: int
    
    class Config:
        json_schema_extra = {
            "example": {
                "path": "/data/evidence",
                "files": [
                    {
                        "name": "transcript_001.json",
                        "size": 2048,
                        "modified": "2023-12-01T10:00:00Z",
                        "is_directory": False
                    }
                ],
                "count": 1
            }
        }

class SummarizeFilesRequest(BaseModel):
    """Request to summarize transcripts and laws"""
    transcripts: List[str] = Field(..., description="List of transcript file paths")
    laws: List[str] = Field(..., description="List of law file paths")
    
    class Config:
        json_schema_extra = {
            "example": {
                "transcripts": ["transcript_001.json", "transcript_002.json"],
                "laws": ["regulation_001.pdf"]
            }
        }

class SummarizeFilesResponse(BaseModel):
    """Response from file summarization"""
    summary: str
    key_points: List[str]
    files_processed: int
    
    class Config:
        json_schema_extra = {
            "example": {
                "summary": "The documents contain information about aviation security regulations and related incident transcripts...",
                "key_points": [
                    "Regulation XYZ requires proper security screening",
                    "Transcript shows compliance issues",
                    "Recommended actions for improvement"
                ],
                "files_processed": 3
            }
        }

class SummarizeRequest(BaseModel):
    file_ids: List[str]
    model: Optional[str] = None
    temperature: Optional[float] = 0.7

# ============================================================================
# ASSISTANTS
# ============================================================================

class ToolParameter(BaseModel):
    """Tool parameter definition"""
    type: str
    description: Optional[str] = None

class ToolParameters(BaseModel):
    """Tool parameters schema"""
    type: str = "object"
    properties: Dict[str, ToolParameter]
    required: List[str] = []

class ToolFunction(BaseModel):
    """Tool function definition"""
    name: str
    description: Optional[str] = None
    parameters: Optional[ToolParameters] = None

class ToolObject(BaseModel):
    """Tool object with type and function"""
    type: str
    function: Optional[ToolFunction] = None

class AssistantCreateRequest(BaseModel):
    """Request to create a new assistant"""
    name: str = Field(..., description="Assistant name")
    description: Optional[str] = Field(None, description="Assistant description")
    model: str = Field(..., description="Model to use (e.g., llama3.1:8b)")
    instructions: Optional[str] = Field(None, description="System instructions")
    tools: Optional[List[ToolObject]] = Field(default_factory=list, description="Available tools")
    file_ids: Optional[List[str]] = Field(default_factory=list, description="Attached file IDs")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Custom metadata")
    language: Optional[str] = Field(default="en", description="Preferred language (en, pt, es, it, de)")
    collections: Optional[List[str]] = Field(default_factory=list, description="Qdrant collections to search")
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    top_p: Optional[float] = Field(default=1.0, ge=0.0, le=1.0, description="Nucleus sampling")
    max_tokens: Optional[int] = Field(default=2000, gt=0, le=4000, description="Maximum tokens")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Security Analyst",
                "description": "Analyzes aviation security violations",
                "model": "llama3.1:8b",
                "instructions": "You are an expert in aviation security regulations and incident analysis.",
                "tools": [],
                "file_ids": [],
                "metadata": {
                    "specialization": "aviation_security"
                },
                "language": "en",
                "collections": ["laws", "transcripts"],
                "temperature": 0.7,
                "top_p": 1.0,
                "max_tokens": 2000
            }
        }

class AssistantUpdateRequest(BaseModel):
    """Request to update an existing assistant (partial)"""
    name: Optional[str] = None
    description: Optional[str] = None
    model: Optional[str] = None
    instructions: Optional[str] = None
    tools: Optional[List[ToolObject]] = None
    file_ids: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None
    language: Optional[str] = Field(default=None, description="Preferred language")
    collections: Optional[List[str]] = Field(default=None, description="Qdrant collections")
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    max_tokens: Optional[int] = Field(default=None, gt=0, le=4000)
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Updated Security Analyst",
                "description": "Updated description",
                "temperature": 0.5
            }
        }

class AssistantObject(BaseModel):
    """Complete assistant object"""
    id: str
    object: str = "assistant"
    created_at: int
    name: str
    description: Optional[str] = None
    model: str
    instructions: str = ""
    tools: List[ToolObject] = Field(default_factory=list)
    file_ids: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    language: str = "en"
    collections: List[str] = Field(default_factory=list)
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 1.0
    max_tokens: Optional[int] = 2000
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "asst_123",
                "object": "assistant",
                "created_at": 1672531200,
                "name": "Security Analyst",
                "description": "Analyzes aviation security violations",
                "model": "llama3.1:8b",
                "instructions": "You are an expert in aviation security...",
                "tools": [],
                "file_ids": ["file-abc123"],
                "metadata": {
                    "specialization": "aviation_security"
                },
                "language": "en",
                "collections": ["laws", "transcripts"],
                "temperature": 0.7,
                "top_p": 1.0,
                "max_tokens": 2000
            }
        }

class AssistantListResponse(BaseModel):
    """List of assistants"""
    object: str = "list"
    data: List[AssistantObject]
    
    class Config:
        json_schema_extra = {
            "example": {
                "object": "list",
                "data": [
                    {
                        "id": "asst_123",
                        "object": "assistant",
                        "created_at": 1672531200,
                        "name": "Security Analyst",
                        "description": "Analyzes aviation security violations",
                        "model": "llama3.1:8b",
                        "instructions": "You are an expert...",
                        "tools": [],
                        "file_ids": ["file-abc123"],
                        "metadata": {},
                        "language": "en",
                        "collections": ["laws", "transcripts"],
                        "temperature": 0.7,
                        "top_p": 1.0,
                        "max_tokens": 2000
                    }
                ]
            }
        }

class AttachFileRequest(BaseModel):
    """Request to attach file to assistant"""
    file_id: str = Field(..., description="File ID to attach")
    
    class Config:
        json_schema_extra = {
            "example": {
                "file_id": "file-abc123"
            }
        }

# ============================================================================
# CHAT COMPLETIONS
# ============================================================================

class Message(BaseModel):
    """Chat message"""
    role: str = Field(..., description="Message role (system, user, assistant)")
    content: Union[str, List[Dict[str, Any]]] = Field(..., description="Message content")
    name: Optional[str] = Field(None, description="Name of the message sender")

class ChatRequest(BaseModel):
    """Chat completion request"""
    model: str = Field(default="llama3-groq-tool-use:8b", description="Model to use")
    messages: List[Message] = Field(..., description="Conversation messages")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    top_p: float = Field(default=1.0, ge=0.0, le=1.0, description="Nucleus sampling")
    max_tokens: Optional[int] = Field(default=1000, gt=0, description="Maximum tokens")
    stream: bool = Field(default=False, description="Stream response")
    tools: Optional[List[ToolObject]] = Field(None, description="Available tools")
    tool_choice: Optional[Union[str, Dict[str, Any]]] = Field(None, description="Tool choice strategy")
    assistant_id: Optional[str] = Field(None, description="Assistant ID for context")
    thread_id: Optional[str] = Field(None, description="Thread ID for context")
    # External provider routing (optional — omit for local Ollama)
    provider: Optional[str] = Field(None, description="Provider: ollama | openai | anthropic | groq | xai")
    api_key: Optional[str] = Field(None, description="API key for external provider")
    base_url: Optional[str] = Field(None, description="Override base URL for provider")
    
    class Config:
        json_schema_extra = {
            "example": {
                "model": "llama3.1:8b",
                "messages": [
                    {
                        "role": "user",
                        "content": "What are the security requirements for airport screening?"
                    }
                ],
                "temperature": 0.7,
                "top_p": 1.0,
                "max_tokens": 1000,
                "stream": False,
                "tools": None,
                "tool_choice": None,
                "assistant_id": "asst_123"
            }
        }

class Choice(BaseModel):
    """Chat completion choice"""
    index: int = 0
    message: Message
    finish_reason: str = "stop"

class Usage(BaseModel):
    """Token usage statistics"""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class ChatResponse(BaseModel):
    """Chat completion response"""
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Choice]
    usage: Usage
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "chat_123",
                "object": "chat.completion",
                "created": 1672531200,
                "model": "llama3.1:8b",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "According to aviation security regulations, airport screening must include..."
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    "prompt_tokens": 25,
                    "completion_tokens": 150,
                    "total_tokens": 175
                }
            }
        }

# ============================================================================
# THREADS
# ============================================================================

class ThreadCreateRequest(BaseModel):
    """Request to create a new thread"""
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Custom metadata")
    
    class Config:
        json_schema_extra = {
            "example": {
                "metadata": {"test": True}
            }
        }

class ThreadObject(BaseModel):
    """Thread object"""
    id: str
    object: str = "thread"
    created_at: int
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "thread_123",
                "object": "thread",
                "created_at": 1672531200,
                "metadata": {"test": True}
            }
        }

class ThreadListResponse(BaseModel):
    """List of threads"""
    object: str = "list"
    data: List[ThreadObject]

# ============================================================================
# MESSAGES
# ============================================================================

class MessageContentText(BaseModel):
    """Text content"""
    value: str

class MessageContent(BaseModel):
    """Message content object"""
    type: str
    text: Optional[MessageContentText] = None

class MessageCreateRequest(BaseModel):
    """Request to create a message in a thread"""
    role: str = Field(default="user", description="Message role")
    content: Union[str, List[Dict[str, Any]]] = Field(..., description="Message content")
    file_ids: Optional[List[str]] = Field(default_factory=list, description="File IDs")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Metadata")

class MessageObject(BaseModel):
    """Thread message object"""
    id: str
    object: str = "thread.message"
    created_at: int
    thread_id: str
    role: str
    content: List[MessageContent]
    file_ids: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class MessageListResponse(BaseModel):
    """List of messages"""
    object: str = "list"
    data: List[MessageObject]

# ============================================================================
# RUNS
# ============================================================================

class RunCreateRequest(BaseModel):
    """Request to create a run"""
    assistant_id: Optional[str] = Field(None, description="Assistant ID")
    model: Optional[str] = Field(default="llama3.1:8b", description="Model to use")
    instructions: Optional[str] = Field(None, description="Override instructions")
    tools: Optional[List[ToolObject]] = Field(None, description="Available tools")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Metadata")

class RunObject(BaseModel):
    """Run object"""
    id: str
    object: str = "thread.run"
    created_at: int
    thread_id: str
    assistant_id: str
    status: str
    model: str
    instructions: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

# ============================================================================
# QDRANT / VECTOR DATABASE
# ============================================================================

class QdrantConnectionResponse(BaseModel):
    """Qdrant connection status"""
    status: str
    message: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "message": "Successfully connected to Qdrant"
            }
        }

class QdrantCollectionInfo(BaseModel):
    """Information about a Qdrant collection"""
    name: str
    vectors_count: int
    points_count: Optional[int] = None
    status: Optional[str] = None

class QdrantCollectionsResponse(BaseModel):
    """Response for listing Qdrant collections"""
    collections: List[str]
    
    class Config:
        json_schema_extra = {
            "example": {
                "collections": ["laws", "transcripts", "violations"]
            }
        }

class CreateCollectionRequest(BaseModel):
    """Request to create a new Qdrant collection"""
    name: str = Field(..., description="Collection name")
    vector_size: int = Field(default=768, description="Vector dimensions")
    distance_metric: str = Field(default="cosine", description="Distance metric (cosine, euclid, dot)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "aviation_regulations",
                "vector_size": 768,
                "distance_metric": "cosine"
            }
        }

class QdrantSearchResult(BaseModel):
    """Individual search result from Qdrant"""
    id: Union[str, int]
    score: float
    payload: Dict[str, Any]

class QdrantSearchResponse(BaseModel):
    """Response for Qdrant search queries"""
    results: List[QdrantSearchResult]
    count: int
    query: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "results": [
                    {
                        "id": "point_123",
                        "score": 0.95,
                        "payload": {
                            "source": "anac_regulation_001.pdf",
                            "text": "Aviation security regulation requires proper screening of all passengers...",
                            "doc_type": "Resolution"
                        }
                    }
                ],
                "count": 1,
                "query": "aviation security regulations"
            }
        }

class KnowledgeQueryRequest(BaseModel):
    """Request to query knowledge base"""
    query: str = Field(..., description="Search query")
    collection_name: Optional[str] = Field(None, description="Specific collection to search")
    limit: Optional[int] = Field(default=5, description="Maximum results")
    
    class Config:
        json_schema_extra = {
            "example": {
                "query": "aviation security regulations",
                "collection_name": "laws",
                "limit": 5
            }
        }

class KnowledgeIngestTextRequest(BaseModel):
    collection_name: str
    text: str
    chunk_size: int = 500
    chunk_overlap: int = 50
    metadata: Optional[Dict[str, Any]] = None

# ============================================================================
# MODELS
# ============================================================================

class ModelData(BaseModel):
    """Model information"""
    id: str
    object: str = "model"
    created: int
    owned_by: str = "ollama"

class ModelList(BaseModel):
    """List of available models"""
    object: str = "list"
    data: List[ModelData]
    
    class Config:
        json_schema_extra = {
            "example": {
                "object": "list",
                "data": [
                    {
                        "id": "llama3.1:8b",
                        "object": "model",
                        "created": 1672531200,
                        "owned_by": "ollama"
                    }
                ]
            }
        }

# ============================================================================
# GENERIC RESPONSES
# ============================================================================

class GenericSuccessResponse(BaseModel):
    """Generic success response"""
    success: bool = True
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Operation completed successfully",
                "data": {"id": "item_123"}
            }
        }

class DeleteResponse(BaseModel):
    """Delete operation response"""
    id: str
    object: str
    deleted: bool
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "asst_123",
                "object": "assistant",
                "deleted": True
            }
        }

# ============================================================================
# VALIDATION & ERRORS
# ============================================================================

class ValidationError(BaseModel):
    """Validation error detail"""
    loc: List[Union[str, int]]
    msg: str
    type: str

class HTTPValidationError(BaseModel):
    """HTTP validation error response"""
    detail: List[ValidationError]

# ============================================================================
# TOOLS
# ============================================================================

class ToolListResponse(BaseModel):
    """List of tools"""
    object: str = "list"
    data: List[ToolObject]

class AssignToolRequest(BaseModel):
    """Request to assign tool to assistant"""
    tool_id: str = Field(..., description="Tool identifier")
    
    class Config:
        json_schema_extra = {
            "example": {
                "tool_id": "search_regulations"
            }
        }

class ToolCreateRequest(BaseModel):
    function: Dict[str, Any]

class ToolExecuteRequest(BaseModel):
    tool_name: str
    parameters: Dict[str, Any] = {}

# ============================================================================
# DEEPSEEK (if needed)
# ============================================================================

class DeepSeekMessage(BaseModel):
    """DeepSeek message"""
    role: str
    content: str

class DeepSeekRequest(BaseModel):
    """DeepSeek API request"""
    messages: List[DeepSeekMessage]
    api_key: Optional[str] = None

class DeepSeekResponse(BaseModel):
    """DeepSeek API response"""
    response: str
    reasoning: Optional[str] = None

class DeepReasoningRequest(BaseModel):
    question: str

class PromptGenerateRequest(BaseModel):
    model: str
    user_input: str
    system_prompt: Optional[str] = None



class ModelsListResponse(BaseModel):
    """Response model for listing available models"""
    object: str = "list"
    data: List[Dict[str, Any]]
    
    class Config:
        json_schema_extra = {
            "example": {
                "object": "list",
                "data": [
                    {
                        "id": "llama3.1:8b",
                        "object": "model",
                        "created": 1672531200,
                        "owned_by": "ollama"
                    },
                    {
                        "id": "deepseek-v4-flash",
                        "object": "model",
                        "created": 1672531200,
                        "owned_by": "deepseek"
                    }
                ]
            }
        }