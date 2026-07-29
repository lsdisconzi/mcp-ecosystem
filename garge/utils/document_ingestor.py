from typing import List, Dict, Any, Optional, Union
import uuid
from datetime import datetime
import os
import json
import re

def ingest_document(
    file_path: str,
    text_content: str,
    doc_type: str,
    doc_number: Optional[str] = None,
    date: Optional[str] = None,
    chunk_size: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
    embedding_dim: int = 768  # 👈 ADD THIS
) -> List[Dict[str, Any]]:
    """
    Ingests a document into a structured format for vector search.
    Supports full-document ingestion (default) and optional chunking.
    
    Args:
        file_path: Original file path / source.
        text_content: Full text of the document.
        doc_type: Type of document (e.g., 'Resolution', 'IN', 'RBAC', 'Transcript').
        doc_number: Optional identifier for the document.
        date: Optional document date.
        chunk_size: If provided, splits text into chunks of this many characters.
        metadata: Optional dictionary of extra metadata.
        embedding_dim: Dimensionality of the embedding space (default: 768).

    Returns:
        List of structured dicts, each representing a vector/document chunk.
    """
    ingest_items = []
    
    # Default metadata
    base_metadata = {
        "file_path": file_path,
        "doc_type": doc_type,
        "doc_number": doc_number,
        "date": date,
        "ingested_at": datetime.utcnow().isoformat(),
    }
    
    # Filter out None values
    base_metadata = {k: v for k, v in base_metadata.items() if v is not None}
    
    if metadata:
        base_metadata.update(metadata)
    
    # If chunk_size is not provided, ingest as a full document
    if not chunk_size:
        ingest_items.append({
            "id": str(uuid.uuid4()),
            "text": text_content,
            "metadata": base_metadata,
            "chunk_index": 0,
            "full_document": True
        })
    else:
        # Split text into chunks for large documents (transcripts, reviews)
        for idx in range(0, len(text_content), chunk_size):
            chunk_text = text_content[idx:idx + chunk_size]
            # Skip empty chunks
            if not chunk_text.strip():
                continue
                
            ingest_items.append({
                "id": str(uuid.uuid4()),
                "text": chunk_text,
                "metadata": {
                    **base_metadata,
                    "chunk_index": idx // chunk_size
                },
                "chunk_index": idx // chunk_size,
                "full_document": False
            })
    
    return ingest_items

def detect_document_type(file_path: str, content: str) -> Dict[str, Any]:
    """
    Attempts to automatically detect document type, number, and date
    from filename and content patterns.
    
    Args:
        file_path: Path to the original document
        content: Text content of the document
        
    Returns:
        Dict with detected doc_type, doc_number, and date (if found)
    """
    filename = os.path.basename(file_path).upper()
    result = {
        "doc_type": None,
        "doc_number": None,
        "date": None
    }
    
    # Check for ANAC regulation patterns
    if "RESOLUCAO" in filename or "RESOLUTION" in filename:
        result["doc_type"] = "Resolution"
        # Try to extract resolution number
        number_match = re.search(r'(RESOLUCAO|RESOLUTION)[_\s-]*(\d+)', filename, re.IGNORECASE)
        if number_match:
            result["doc_number"] = number_match.group(2)
    
    elif "RBAC" in filename:
        result["doc_type"] = "RBAC"
        # Try to extract RBAC number
        number_match = re.search(r'RBAC[_\s-]*(\d+)', filename, re.IGNORECASE)
        if number_match:
            result["doc_number"] = number_match.group(1)
    
    elif "INSTRUCAO" in filename or "INSTRUCTION" in filename or "IN" in filename:
        result["doc_type"] = "Instruction"
        # Try to extract instruction number
        number_match = re.search(r'(IN|INSTRUCAO|INSTRUCTION)[_\s-]*(\d+)', filename, re.IGNORECASE)
        if number_match:
            result["doc_number"] = number_match.group(2)
    
    elif "PORTARIA" in filename:
        result["doc_type"] = "Portaria"
        number_match = re.search(r'PORTARIA[_\s-]*(\d+)', filename, re.IGNORECASE)
        if number_match:
            result["doc_number"] = number_match.group(1)
            
    elif "DECRETO" in filename:
        result["doc_type"] = "Decreto"
        number_match = re.search(r'DECRETO[_\s-]*(\d+)', filename, re.IGNORECASE)
        if number_match:
            result["doc_number"] = number_match.group(1)
    
    elif "TRANSCRIPT" in filename or "TRANSCRICAO" in filename:
        result["doc_type"] = "Transcript"
    
    elif "REVIEW" in filename or "AVALIACAO" in filename:
        result["doc_type"] = "Review"
    
    # Look for date patterns in filename
    date_match = re.search(r'(\d{4})[_\s-]*(\d{2})[_\s-]*(\d{2})', filename)
    if date_match:
        year, month, day = date_match.groups()
        result["date"] = f"{year}-{month}-{day}"
    
    # If we couldn't detect from filename, try content
    if not result["doc_type"]:
        # Check first 1000 chars for common patterns
        first_block = content[:1000].upper()
        
        if "RESOLUÇÃO" in first_block or "RESOLUTION" in first_block:
            result["doc_type"] = "Resolution"
        elif "RBAC" in first_block:
            result["doc_type"] = "RBAC"
        elif "PORTARIA" in first_block:
            result["doc_type"] = "Portaria"
        elif "DECRETO" in first_block:
            result["doc_type"] = "Decreto"
        elif "INSTRUÇÃO NORMATIVA" in first_block or "NORMATIVE INSTRUCTION" in first_block:
            result["doc_type"] = "Instruction"
        elif any(term in first_block for term in ["TRANSCRIPT", "TRANSCRIÇÃO", "CONVERSA", "DIÁLOGO"]):
            result["doc_type"] = "Transcript"
        else:
            # Default type if nothing detected
            result["doc_type"] = "Document"
            
    # Filter out None values
    return {k: v for k, v in result.items() if v is not None}

def determine_chunking_strategy(doc_type: str, text_length: int) -> Dict[str, Any]:
    """
    Determines whether a document should be chunked and at what size
    based on document type and length.
    
    Args:
        doc_type: Type of document
        text_length: Length of the document text
        
    Returns:
        Dict with chunk_size and chunk_overlap recommendations
    """
    # Default settings - no chunking
    strategy = {
        "chunk_size": None,
        "chunk_overlap": 0
    }
    
    # For regulations, laws, etc., keep as full documents unless very large
    if doc_type in ["Resolution", "RBAC", "Instruction", "Regulation", "Law"]:
        if text_length > 100000:  # If over 100K chars, chunk even regulations
            strategy["chunk_size"] = 10000
            strategy["chunk_overlap"] = 500
    
    # For transcripts, reviews, etc., always chunk
    elif doc_type in ["Transcript", "Review", "Conversation"]:
        strategy["chunk_size"] = 2000
        strategy["chunk_overlap"] = 200
    
    # For unknown/default document types, use size-based decision
    else:
        if text_length > 5000:
            strategy["chunk_size"] = 2000
            strategy["chunk_overlap"] = 200
    
    return strategy

# Smart chunking helpers
import hashlib
from config.settings import settings


def compute_sha256(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def split_by_headers(content: str) -> list:
    """Split markdown-like content into sections by headers preserving hierarchy."""
    import re
    lines = content.split('\n')
    sections = []
    current_headers = {}
    current_content = []

    header_pattern = re.compile(r'^(#{1,6})\s+(.+)$')

    for line in lines:
        match = header_pattern.match(line)
        if match:
            # Save previous section
            if current_content and any(s.strip() for s in current_content):
                header_path = ' > '.join([h for h in current_headers.values()])
                sections.append({
                    'header_path': header_path,
                    'level': len(current_headers),
                    'content': '\n'.join(current_content)
                })
                current_content = []

            level = len(match.group(1))
            header_text = match.group(2).strip()
            # Remove deeper levels
            current_headers = {k: v for k, v in current_headers.items() if k < level}
            current_headers[level] = header_text

            current_content.append(line)
        else:
            current_content.append(line)

    if current_content and any(s.strip() for s in current_content):
        header_path = ' > '.join([h for h in current_headers.values()])
        sections.append({
            'header_path': header_path,
            'level': len(current_headers),
            'content': '\n'.join(current_content)
        })

    return sections


def split_with_overlap(text: str, chunk_size: int = 3000, overlap: int = 200) -> list:
    """Split text into overlapping chunks based on paragraphs."""
    paragraphs = [p for p in text.split('\n\n') if p.strip()]
    chunks = []
    current_chunk = []
    current_size = 0

    for para in paragraphs:
        para_size = len(para)
        if current_size + para_size > chunk_size and current_chunk:
            chunks.append('\n\n'.join(current_chunk))

            # build overlap
            overlap_paras = []
            overlap_size = 0
            for p in reversed(current_chunk):
                if overlap_size + len(p) <= overlap:
                    overlap_paras.insert(0, p)
                    overlap_size += len(p)
                else:
                    break

            current_chunk = overlap_paras + [para]
            current_size = sum(len(p) for p in current_chunk)
        else:
            current_chunk.append(para)
            current_size += para_size

    if current_chunk:
        chunks.append('\n\n'.join(current_chunk))

    return chunks


def chunk_markdown_document(content: str, max_chunk_size: int = None) -> list:
    """Smart chunking for markdown documents respecting headers and overlaps."""
    if max_chunk_size is None:
        max_chunk_size = settings.qdrant_chunk_size_max

    chunks = []
    sections = split_by_headers(content)

    for section in sections:
        sec_text = section['content'].strip()
        if not sec_text:
            continue

        if len(sec_text) <= max_chunk_size:
            chunks.append({
                'text': sec_text,
                'metadata': {
                    'header_path': section['header_path'],
                    'level': section['level'],
                    'chunk_type': 'full_section'
                }
            })
        else:
            sub_chunks = split_with_overlap(sec_text, chunk_size=max_chunk_size, overlap=settings.qdrant_chunk_overlap)
            for i, chunk in enumerate(sub_chunks):
                chunks.append({
                    'text': chunk,
                    'metadata': {
                        'header_path': section['header_path'],
                        'level': section['level'],
                        'chunk_type': 'paragraph_chunk',
                        'sub_index': i
                    }
                })
    return chunks


def process_file_for_ingestion(
    file_path: str,
    content: str,
    override_doc_type: Optional[str] = None,
    override_chunk_size: Optional[int] = None,
    embedding_dim: int = 768
):
    """
    Processes a document by detecting its type, determining the best chunking
    strategy, and preparing it for ingestion into Qdrant.
    """
    # Detect document properties
    detected = detect_document_type(file_path, content)

    # Allow overrides
    doc_type = override_doc_type or detected.get("doc_type", "Document")
    doc_number = detected.get("doc_number")
    date = detected.get("date")

    # Decide chunking configuration values
    if doc_type == 'Document' and settings.qdrant_preserve_headers and ('\n#' in content or content.strip().startswith('#')):
        # Use header-aware chunking for markdown-like content
        raw_chunks = chunk_markdown_document(content, max_chunk_size=(override_chunk_size or settings.qdrant_chunk_size_optimal))
        texts = [c['text'] for c in raw_chunks]
        metadatas = [c['metadata'] for c in raw_chunks]
    else:
        # Fallback to paragraph-overlap chunking when large
        effective_chunk_size = override_chunk_size or settings.qdrant_chunk_size_optimal
        if len(content) <= effective_chunk_size:
            texts = [content]
            metadatas = [{'header_path': '', 'level': 0, 'chunk_type': 'full_document'}]
        else:
            texts = split_with_overlap(content, chunk_size=effective_chunk_size, overlap=settings.qdrant_chunk_overlap)
            metadatas = [{'header_path': '', 'level': 0, 'chunk_type': 'paragraph_chunk', 'sub_index': i} for i,_ in enumerate(texts)]

    ingest_items = []
    total = len(texts)
    now = datetime.utcnow().isoformat()

    for i, txt in enumerate(texts):
        chunk_metadata = {
            'file_path': file_path,
            'file_size': len(content),
            'chunk_index': i,
            'total_chunks': total,
            'chunk_size': len(txt),
            'header_path': metadatas[i].get('header_path', ''),
            'section_level': metadatas[i].get('level', 0),
            'doc_type': doc_type,
            'created_at': now,
            'sha256': compute_sha256(txt)
        }

        # Optionally add doc-specific metadata (placeholders for extraction hooks)
        if settings.qdrant_extract_citations and doc_type == 'Document':
            # simple placeholder — real extractor would be more sophisticated
            chunk_metadata['article_references'] = []
            chunk_metadata['case_references'] = []

        ingest_items.append({
            'id': str(uuid.uuid4()),
            'text': txt,
            'metadata': chunk_metadata,
            'chunk_index': i,
            'full_document': (total == 1)
        })

    # Use the correct embedding model - keep previous behavior (no embedding generation here)
    from routes.qdrant_router import embedding_models
    model = embedding_models.get(embedding_dim)
    if not model:
        raise ValueError(f"No embedding model for dimension {embedding_dim}")

    return ingest_items