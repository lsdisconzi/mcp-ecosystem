"""
Document Processing Utilities
Text extraction and processing functions for various document formats.
"""

import io
import json
from typing import Optional, Dict, Any
import logging
import pypdf
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """
    Extract text from PDF file bytes.
    
    Args:
        pdf_bytes: Raw PDF file bytes
        
    Returns:
        str: Extracted text content
        
    Raises:
        ValueError: If PDF cannot be processed
    """
    try:
        # Try PyMuPDF first (better for complex PDFs)
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text = ""
            for page in doc:
                text += page.get_text()
            return text
        except Exception as e:
            logger.debug(f"PyMuPDF extraction failed, trying PyPDF: {e}")
        
        # Fallback to PyPDF
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        
        if not text.strip():
            logger.warning("PDF text extraction returned empty content")
        
        return text
        
    except Exception as e:
        logger.error(f"Failed to extract text from PDF: {e}")
        raise ValueError(f"Failed to extract text from PDF: {str(e)}")


def extract_text_from_file(file_bytes: bytes, filename: str) -> str:
    """
    Extract text from various file formats.
    
    Args:
        file_bytes: Raw file bytes
        filename: Original filename for format detection
        
    Returns:
        str: Extracted text content
        
    Raises:
        ValueError: If file format is unsupported or extraction fails
    """
    filename_lower = filename.lower()
    
    # PDF files
    if filename_lower.endswith('.pdf'):
        return extract_text_from_pdf(file_bytes)
    
    # JSON files
    elif filename_lower.endswith('.json'):
        try:
            data = json.loads(file_bytes.decode('utf-8'))
            return json.dumps(data, ensure_ascii=False, indent=2)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {str(e)}")
    
    # Text files (txt, md, csv, etc.)
    elif any(filename_lower.endswith(ext) for ext in ['.txt', '.md', '.csv', '.html', '.htm', '.xml']):
        try:
            return file_bytes.decode('utf-8')
        except UnicodeDecodeError:
            # Try other encodings
            for encoding in ['latin-1', 'iso-8859-1', 'cp1252']:
                try:
                    return file_bytes.decode(encoding)
                except UnicodeDecodeError:
                    continue
            raise ValueError("Could not decode text file with any supported encoding")
    
    else:
        raise ValueError(f"Unsupported file format: {filename}")


def determine_document_type(filename: str, content: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Determine document type based on filename, content, and metadata.
    
    Args:
        filename: Original filename
        content: Text content (optional)
        metadata: Additional metadata (optional)
        
    Returns:
        str: Document type string
    """
    # Check metadata first
    if metadata and metadata.get("doc_type"):
        return metadata["doc_type"]
    
    filename_lower = filename.lower()
    
    # Check filename patterns
    if "transcript" in filename_lower:
        return "transcript"
    elif "violation" in filename_lower or "finding" in filename_lower:
        return "violation"
    elif any(keyword in filename_lower for keyword in ["law", "regulation", "statute", "code", "rbac", "anac", "icao"]):
        return "law"
    elif "resolution" in filename_lower:
        return "resolution"
    elif "report" in filename_lower:
        return "report"
    elif "contract" in filename_lower or "agreement" in filename_lower:
        return "contract"
    
    # Check content patterns if available
    if content:
        content_lower = content[:1000].lower()  # Check first 1000 chars
        if any(keyword in content_lower for keyword in ["article", "section", "law", "regulation", "statute"]):
            return "law"
        elif any(keyword in content_lower for keyword in ["speaker", "transcript", "timestamp", "00:"]):
            return "transcript"
    
    # Default
    return "document"


def chunk_text_by_paragraphs(text: str, max_chunk_size: int = 1000) -> list:
    """
    Chunk text by paragraphs while respecting maximum chunk size.
    
    Args:
        text: Input text
        max_chunk_size: Maximum characters per chunk
        
    Returns:
        list: List of text chunks
    """
    if not text.strip():
        return []
    
    paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
    
    chunks = []
    current_chunk = []
    current_size = 0
    
    for paragraph in paragraphs:
        para_size = len(paragraph)
        
        # If a single paragraph is too large, split it
        if para_size > max_chunk_size:
            # If we have accumulated content, add it first
            if current_chunk:
                chunks.append('\n'.join(current_chunk))
                current_chunk = []
                current_size = 0
            
            # Split the large paragraph
            words = paragraph.split()
            temp_chunk = []
            temp_size = 0
            
            for word in words:
                word_size = len(word) + 1  # +1 for space
                
                if temp_size + word_size > max_chunk_size:
                    if temp_chunk:
                        chunks.append(' '.join(temp_chunk))
                    temp_chunk = [word]
                    temp_size = word_size
                else:
                    temp_chunk.append(word)
                    temp_size += word_size
            
            if temp_chunk:
                chunks.append(' '.join(temp_chunk))
        
        # Normal paragraph
        elif current_size + para_size + 1 > max_chunk_size:
            # Current chunk is full, save it
            if current_chunk:
                chunks.append('\n'.join(current_chunk))
            current_chunk = [paragraph]
            current_size = para_size
        else:
            # Add paragraph to current chunk
            current_chunk.append(paragraph)
            current_size += para_size + 1  # +1 for newline
    
    # Add the last chunk
    if current_chunk:
        chunks.append('\n'.join(current_chunk))
    
    return chunks


def sanitize_text(text: str) -> str:
    """
    Clean and sanitize text for embedding.
    
    Args:
        text: Input text
        
    Returns:
        str: Sanitized text
    """
    if not text:
        return ""
    
    # Replace multiple whitespace with single space
    import re
    text = re.sub(r'\s+', ' ', text)
    
    # Remove control characters except newline and tab
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
    
    # Normalize unicode (if needed)
    try:
        import unicodedata
        text = unicodedata.normalize('NFKC', text)
    except ImportError:
        pass
    
    return text.strip()