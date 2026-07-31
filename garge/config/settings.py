from pydantic_settings import BaseSettings
from typing import List, Optional
from pathlib import Path
import os

class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    # Server Configuration
    app_name: str = "Ollama Assistant Engine"
    app_version: str = "1.0.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8066
    
    # Ollama Configuration
    ollama_base_url: str = "http://localhost:11436"
    default_model: str = "llama3.1:8b"
    
    # Storage Paths
    base_dir: Path = Path(__file__).parent.parent
    data_dir: str = "data"
    assistant_storage_path: str = "data/assistants"
    threads_dir: str = "data/threads"
    threads_storage_path: str = "data/threads"  # Alias for compatibility
    files_dir: str = "data/files"
    file_storage_path: str = "data/files"  # Alias for file uploads
    tools_dir: str = "data/tools"
    audio_storage_path: str = "data/audio"
    
    # File Upload Configuration
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    allowed_extensions: List[str] = [".txt", ".md", ".pdf", ".docx", ".doc", ".json"]
    
    # Qdrant Configuration
    qdrant_url: Optional[str] = None
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_api_key: Optional[str] = None

    # Qdrant chunking and ingestion tuning
    # - qdrant_chunk_size_max: hard maximum chunk size (characters)
    # - qdrant_chunk_size_optimal: preferred chunk size during splitting
    # - qdrant_chunk_overlap: overlap window (characters) between consecutive chunks
    # - qdrant_min_chunk_size: smallest allowed chunk size (characters)
    # - qdrant_legal_chunk_size_max: override max for legal documents
    # - qdrant_code_chunk_size_max: override max for code files
    # - qdrant_preserve_headers: preserve markdown headers as chunk boundaries when possible
    # - qdrant_extract_citations: attempt to extract legal citations (experimental)
    qdrant_chunk_size_max: int = 4000
    qdrant_chunk_size_optimal: int = 1500
    qdrant_chunk_overlap: int = 200
    qdrant_min_chunk_size: int = 200
    qdrant_legal_chunk_size_max: int = 7000
    qdrant_code_chunk_size_max: int = 2000
    qdrant_preserve_headers: bool = True
    qdrant_extract_citations: bool = False
    
    # External API Keys
    deepseek_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    google_drive_api_key: Optional[str] = None
    
    # Model Configuration
    default_temperature: float = 0.2
    default_top_p: float = 1.0
    default_max_tokens: int = 2000
    
    # Feature Flags
    enable_tools: bool = True
    enable_vision: bool = True
    enable_embeddings: bool = True
    
    # Logging
    log_level: str = "INFO"
    log_file: Optional[str] = None

    # Session/Auth
    jwt_secret: str = "dev-secret-change-me"
    persist_memory: bool = False
    
    # Additional fields from .env
    js_contained_modules_dir: Optional[str] = None
    argus_api: Optional[str] = None
    runpod_api_key: Optional[str] = None
    datajud_api_key: Optional[str] = None
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        env_prefix = ""
        extra = "allow"
    
    @property
    def assistant_storage_dir(self) -> Path:
        """Get assistant storage directory as Path object."""
        return self.base_dir / self.assistant_storage_path
    
    @property
    def threads_path(self) -> Path:
        """Get threads directory as Path object."""
        return self.base_dir / self.threads_dir
    
    @property
    def files_path(self) -> Path:
        """Get files directory as Path object."""
        return self.base_dir / self.files_dir
    
    @property
    def tools_path(self) -> Path:
        """Get tools directory as Path object."""
        return self.base_dir / self.tools_dir

    @property
    def audio_path(self) -> Path:
        """Get audio directory as Path object."""
        return self.base_dir / self.audio_storage_path


# Initialize settings instance
settings = Settings()

# Ensure all required directories exist
def init_directories():
    """Create all required directories if they don't exist."""
    directories = [
        settings.data_dir,
        settings.assistant_storage_path,
        settings.threads_dir,
        settings.files_dir,
        settings.tools_dir,
        settings.base_dir,
        settings.file_storage_path
    ]
    
    for directory in directories:
        dir_path = settings.base_dir / directory
        os.makedirs(dir_path, exist_ok=True)

# Initialize directories on import
init_directories()
