from typing import List, Dict, Any, Optional
from fastapi import HTTPException
import logging
import json
import os

logger = logging.getLogger(__name__)

async def get_file_content(file_id: str) -> str:
    """
    Retrieve file content by ID
    
    Args:
        file_id: File identifier
        
    Returns:
        File content as string
    """
    from config.settings import settings
    
    try:
        file_path = os.path.join(settings.file_storage_path, "uploads", file_id)
        
        if not os.path.exists(file_path):
            # Try with metadata
            metadata_path = f"{file_path}.json"
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                    file_path = metadata.get('path', file_path)
        
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"File {file_id} not found")
        
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
            
    except Exception as e:
        logger.error(f"Failed to read file {file_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")


async def generate_summary(
    content: str, 
    model: str, 
    temperature: float,
    max_tokens: int = 1000
) -> str:
    """
    Generate summary using AI model
    
    Args:
        content: Text content to summarize
        model: AI model to use
        temperature: Sampling temperature
        max_tokens: Maximum tokens for summary
        
    Returns:
        Generated summary
    """
    from core.local_llm import LocalLLMClient
    
    try:
        llm_client = LocalLLMClient()
        
        prompt = f"""Please provide a concise summary of the following content:

{content[:4000]}  # Limit content to prevent token overflow

Summary:"""
        
        response = await llm_client.generate(
            model=model,
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        return response.get('response', 'Summary generation failed')
        
    except Exception as e:
        logger.error(f"Summary generation failed: {e}")
        return f"Error generating summary: {str(e)}"


def summarize_files(
    file_ids: List[str],
    model: str = "hermes3:8b",
    temperature: float = 0.1,
    max_tokens: int = 1000
) -> Dict[str, Any]:
    """
    Summarize multiple files using AI model
    
    Args:
        file_ids: List of file IDs to summarize
        model: AI model to use for summarization
        temperature: Sampling temperature
        max_tokens: Maximum tokens for summary
        
    Returns:
        Dictionary containing summary and metadata
    """
    import asyncio
    
    try:
        # Get file contents
        file_contents = []
        for file_id in file_ids:
            try:
                content = asyncio.run(get_file_content(file_id))
                file_contents.append(f"File {file_id}:\n{content}")
            except Exception as e:
                logger.warning(f"Failed to read file {file_id}: {e}")
                file_contents.append(f"File {file_id}: [Error reading file]")
        
        # Combine content
        combined_content = "\n\n---\n\n".join(file_contents)
        
        # Generate summary
        summary = asyncio.run(generate_summary(
            combined_content, 
            model, 
            temperature,
            max_tokens
        ))
        
        return {
            "summary": summary,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "file_count": len(file_ids),
            "status": "success"
        }
        
    except Exception as e:
        logger.error(f"Summarization failed: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"File summarization failed: {str(e)}"
        )


def get_available_tools() -> List[Dict[str, Any]]:
    """
    Get list of available tools with proper schema
    """
    tools = [
        {
            "id": "analyze_document",
            "object": "tool",
            "created_at": 1700000000,
            "name": "analyze_document",
            "description": "Analyze document content and extract insights",
            "type": "function",
            "function": {
                "name": "analyze_document",
                "description": "Analyze document content",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Document identifier"
                        },
                        "analysis_type": {
                            "type": "string",
                            "enum": ["summary", "extraction", "classification"],
                            "description": "Type of analysis to perform"
                        }
                    },
                    "required": ["document_id", "analysis_type"]
                }
            }
        },
        {
            "id": "search_knowledge",
            "object": "tool",
            "created_at": 1700000000,
            "name": "search_knowledge",
            "description": "Search knowledge base using semantic search",
            "type": "function",
            "function": {
                "name": "search_knowledge",
                "description": "Search knowledge base",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query"
                        },
                        "collection": {
                            "type": "string",
                            "description": "Collection name"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum results",
                            "default": 10
                        }
                    },
                    "required": ["query"]
                }
            }
        }
    ]
    
    return tools