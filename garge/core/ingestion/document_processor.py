import os
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging
from dataclasses import dataclass

# Document processing libraries
from pypdf import PdfReader
from docx import Document
import markdown
from bs4 import BeautifulSoup
import pandas as pd
from email import policy
from email.parser import BytesParser

logger = logging.getLogger(__name__)

@dataclass
class DocumentChunk:
    """Represents a chunk of text from a document with metadata."""
    text: str
    metadata: Dict[str, Any]
    chunk_id: str
    chunk_index: int
    total_chunks: int

class DocumentProcessor:
    """Handles extraction and processing of various document types."""
    
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        
        # Supported file extensions
        self.supported_extensions = {
            '.txt', '.md', '.markdown', '.json', '.csv', '.xml', '.html', 
            '.tex', '.log', '.yaml', '.yml', '.pdf', '.docx', '.doc', 
            '.eml', '.py', '.js', '.ts', '.java', '.cpp', '.c', '.h',
            '.sql', '.toml', '.env'
        }
        
        # File handlers registry
        self.file_handlers = {
            '.pdf': self._read_pdf,
            '.docx': self._read_docx,
            '.doc': self._read_doc,
            '.eml': self._read_eml,
            '.json': self._read_json,
            '.csv': self._read_csv,
            '.xml': self._read_xml,
            '.html': self._read_html,
            '.md': self._read_markdown,
            '.py': self._read_code,
            '.js': self._read_code,
            '.ts': self._read_code,
            '.sql': self._read_sql,
        }

        # Detect available DOC extractors and report for easier diagnostics
        try:
            self.available_doc_extractors = self._detect_doc_extractors()
            logger.info(f"DOC extractors available: {', '.join(self.available_doc_extractors) if self.available_doc_extractors else 'none'}")
        except Exception as e:
            logger.debug(f"Error detecting DOC extractors: {e}")
    
    def process_file(self, file_path: str) -> List[DocumentChunk]:
        """Process a single file and return text chunks."""
        file_path = Path(file_path)
        
        if not file_path.exists():
            logger.error(f"File does not exist: {file_path}")
            return []
        
        ext = file_path.suffix.lower()
        if ext not in self.supported_extensions:
            logger.warning(f"Unsupported file extension: {ext}")
            return []
        
        # Get file metadata
        stats = file_path.stat()
        metadata = {
            'doc_id': self._generate_doc_id(str(file_path)),
            'file_path': str(file_path),
            'file_name': file_path.name,
            'file_extension': ext,
            'file_size': stats.st_size,
            'last_modified': stats.st_mtime,
            'directory': str(file_path.parent),
            'source': 'garage_aware'
        }
        
        # Read file content
        logger.info(f"Processing file: {file_path}")
        
        if ext in self.file_handlers:
            text = self.file_handlers[ext](str(file_path))
        else:
            # Default text file handler
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
                    text = file.read()
            except Exception as e:
                logger.error(f"Error reading file {file_path}: {e}")
                text = ""
        
        # Create chunks
        chunks = self._chunk_text(text, metadata)
        logger.info(f"Created {len(chunks)} chunks from {file_path}")
        
        return chunks
    
    def read_file_content(self, file_path: str) -> str:
        """Read raw text content from a file without chunking."""
        file_path = Path(file_path)
        if not file_path.exists():
            return ""
        
        ext = file_path.suffix.lower()
        if ext in self.file_handlers:
            return self.file_handlers[ext](str(file_path))
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
                return file.read()
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return ""

    def process_directory(self, directory_path: str, exclude_dirs: List[str] = None) -> List[DocumentChunk]:
        """Recursively process all supported files in a directory."""
        if exclude_dirs is None:
            exclude_dirs = ['.git', '__pycache__', 'node_modules', '.venv', 'venv']
        
        all_chunks = []
        directory_path = Path(directory_path)
        
        if not directory_path.exists():
            logger.error(f"Directory does not exist: {directory_path}")
            return all_chunks
        
        logger.info(f"Processing directory: {directory_path}")
        
        for root, dirs, files in os.walk(directory_path):
            # Filter out excluded directories
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for file in files:
                file_path = Path(root) / file
                ext = file_path.suffix.lower()
                
                if ext not in self.supported_extensions:
                    continue
                
                chunks = self.process_file(str(file_path))
                all_chunks.extend(chunks)
        
        logger.info(f"Total chunks from directory: {len(all_chunks)}")
        return all_chunks
    
    def _read_pdf(self, file_path: str) -> str:
        """Extract text from PDF files."""
        try:
            text = ""
            with open(file_path, 'rb') as file:
                pdf_reader = PdfReader(file)
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
            return text.strip()
        except Exception as e:
            logger.error(f"Error reading PDF {file_path}: {e}")
            return ""
    
    def _read_docx(self, file_path: str) -> str:
        """Extract text from DOCX files."""
        try:
            doc = Document(file_path)
            text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            return text.strip()
        except Exception as e:
            logger.error(f"Error reading DOCX {file_path}: {e}")
            return ""

    def _read_doc(self, file_path: str) -> str:
        """Extract text from legacy DOC files.

        Strategy (in order):
        1. Use the `textract` package if available.
        2. Use CLI tools: `antiword`, `catdoc`, `wvText` in that order if available.
        3. Convert DOC -> DOCX using LibreOffice (`soffice`/`libreoffice`) if available, then read docx.
        4. If none available, return empty string and log actionable instructions.
        """
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        tried = []

        # 1) Try textract (optional dependency)
        try:
            import textract
            tried.append('textract')
            try:
                data = textract.process(file_path)
                return data.decode("utf-8", errors="replace").strip()
            except Exception as e:
                logger.debug(f"textract failed for {file_path}: {e}")
        except Exception:
            logger.debug("textract not available; skipping textract fallback")

        # 2) CLI tools (antiword, catdoc, wvText)
        for binary, label in [('antiword', 'antiword'), ('catdoc', 'catdoc'), ('wvText', 'wvText')]:
            found = shutil.which(binary)
            if not found:
                continue

            tried.append(label)
            # If the found executable is a venv wrapper or a python script that tries to call
            # other tools (e.g., the venv 'antiword' wrapper that calls libreoffice), prefer
            # to try system locations first if available.
            actual_path = found
            try:
                # Inspect the first KB of the file to detect wrapper scripts
                with open(found, 'rb') as fh:
                    head = fh.read(2048).decode('utf-8', errors='ignore')
                    if ('libreoffice' in head) or ('soffice' in head) or (found.endswith('/bin/antiword') and 'python' in head):
                        for sys_candidate in ['/opt/homebrew/bin/'+binary, '/usr/local/bin/'+binary, '/usr/bin/'+binary, '/bin/'+binary]:
                            if os.path.exists(sys_candidate) and os.access(sys_candidate, os.X_OK):
                                actual_path = sys_candidate
                                logger.debug(f"Using system binary {actual_path} for {binary} instead of wrapper {found}")
                                break
            except Exception:
                # If inspection fails, continue and attempt to run the found path
                pass

            try:
                result = subprocess.run([actual_path, file_path], capture_output=True, check=True)
                return result.stdout.decode("utf-8", errors="replace").strip()
            except Exception as e:
                logger.debug(f"{label} failed for {file_path} with {actual_path}: {e}")

        # 3) Try LibreOffice conversion to docx
        soffice_path = shutil.which("soffice") or shutil.which("libreoffice")
        if soffice_path:
            tried.append('libreoffice')
            try:
                tmp_dir = tempfile.mkdtemp(prefix="doc_convert_")
                cmd = [soffice_path, "--headless", "--convert-to", "docx", "--outdir", tmp_dir, file_path]
                subprocess.run(cmd, capture_output=True, check=True)
                converted = Path(tmp_dir) / (Path(file_path).stem + ".docx")
                if converted.exists():
                    text = self._read_docx(str(converted))
                    try:
                        converted.unlink()
                    except Exception:
                        pass
                    return text
            except Exception as e:
                logger.debug(f"LibreOffice conversion failed for {file_path}: {e}")

        # 4) Last-resort: try 'strings' to salvage readable text
        strings_path = shutil.which('strings') or shutil.which('/usr/bin/strings') or shutil.which('/opt/homebrew/bin/strings')
        if strings_path:
            try:
                result = subprocess.run([strings_path, file_path], capture_output=True, check=True)
                raw = result.stdout.decode('utf-8', errors='replace')
                # Heuristic: keep lines with reasonable length to reduce noise
                lines = [line for line in raw.splitlines() if len(line.strip()) >= 30]
                text = '\n'.join(lines).strip()
                if text:
                    logger.warning("strings fallback produced text for DOC file; output may be noisy")
                    return text
            except Exception as e:
                logger.debug(f"strings failed for {file_path}: {e}")

        # If we reached here, nothing worked
        available = getattr(self, 'available_doc_extractors', None)
        if available is not None and len(available) == 0:
            logger.error(
                "Unable to extract text from DOC file: no supported tools were detected. "
                "Install one of: 'textract' (pip), 'antiword' (brew/apt), 'catdoc' (brew/apt), or LibreOffice ('soffice' CLI)."
            )
        else:
            logger.error(
                "Unable to extract text from DOC file despite available tools. Attempted: %s. "
                "See logs for details."
                % (', '.join(tried) if tried else 'none')
            )

        return ""
    
    def _read_eml(self, file_path: str) -> str:
        """Extract text from EML email files."""
        try:
            with open(file_path, 'rb') as file:
                msg = BytesParser(policy=policy.default).parse(file)
            
            text_parts = []
            if msg.is_multipart():
                for part in msg.iter_parts():
                    if part.get_content_type() == 'text/plain':
                        text_parts.append(part.get_content())
            else:
                text_parts.append(msg.get_content())
            
            headers = f"From: {msg.get('From')}\nTo: {msg.get('To')}\nSubject: {msg.get('Subject')}\n"
            return headers + "\n".join(text_parts)
        except Exception as e:
            logger.error(f"Error reading EML {file_path}: {e}")
            return ""
    
    def _read_json(self, file_path: str) -> str:
        """Extract text from JSON files."""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                data = json.load(file)
            return self._flatten_json(data)
        except Exception as e:
            logger.error(f"Error reading JSON {file_path}: {e}")
            return ""
    
    def _read_csv(self, file_path: str) -> str:
        """Extract text from CSV files."""
        try:
            df = pd.read_csv(file_path)
            return df.to_string(index=False).strip()
        except Exception as e:
            logger.error(f"Error reading CSV {file_path}: {e}")
            return ""
    
    def _read_xml(self, file_path: str) -> str:
        """Extract text from XML files."""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                soup = BeautifulSoup(file, 'xml')
            return soup.get_text().strip()
        except Exception as e:
            logger.error(f"Error reading XML {file_path}: {e}")
            return ""
    
    def _read_html(self, file_path: str) -> str:
        """Extract text from HTML files."""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                soup = BeautifulSoup(file, 'html.parser')
            return soup.get_text().strip()
        except Exception as e:
            logger.error(f"Error reading HTML {file_path}: {e}")
            return ""
    
    def _read_markdown(self, file_path: str) -> str:
        """Extract text from Markdown files."""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()
            
            html = markdown.markdown(content)
            soup = BeautifulSoup(html, 'html.parser')
            return soup.get_text().strip()
        except Exception as e:
            logger.error(f"Error reading Markdown {file_path}: {e}")
            return ""
    
    def _read_code(self, file_path: str) -> str:
        """Extract text from code files."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
                return file.read().strip()
        except Exception as e:
            logger.error(f"Error reading code file {file_path}: {e}")
            return ""
    
    def _read_sql(self, file_path: str) -> str:
        """Extract text from SQL files."""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read().strip()
        except Exception as e:
            logger.error(f"Error reading SQL {file_path}: {e}")
            return ""
    
    def _flatten_json(self, data: Any, prefix: str = "") -> str:
        """Flatten JSON structure into readable text."""
        items = []
        
        if isinstance(data, dict):
            for key, value in data.items():
                new_prefix = f"{prefix}.{key}" if prefix else key
                items.append(self._flatten_json(value, new_prefix))
        elif isinstance(data, list):
            for i, item in enumerate(data):
                items.append(self._flatten_json(item, f"{prefix}[{i}]"))
        else:
            items.append(f"{prefix}: {str(data)}")
        
        return "\n".join(items)
    
    def _chunk_text(self, text: str, metadata: Dict[str, Any]) -> List[DocumentChunk]:
        """Split text into overlapping chunks."""
        if not text:
            return []
        
        chunks = []
        start = 0
        chunk_index = 0
        
        while start < len(text):
            end = start + self.chunk_size
            
            if end >= len(text):
                chunk_text = text[start:]
            else:
                chunk_text = text[start:end]
                
                # Find good breaking point
                last_break = max(
                    chunk_text.rfind('\n\n'),
                    chunk_text.rfind('\n'),
                    chunk_text.rfind('. '),
                    chunk_text.rfind('? '),
                    chunk_text.rfind('! ')
                )
                
                if last_break > self.chunk_size // 4:
                    chunk_text = chunk_text[:last_break + 1]
                    end = start + len(chunk_text)
            
            chunk_metadata = metadata.copy()
            chunk_metadata.update({
                'chunk_index': chunk_index,
                'char_start': start,
                'char_end': end
            })
            
            chunk = DocumentChunk(
                text=chunk_text.strip(),
                metadata=chunk_metadata,
                chunk_id=f"{metadata.get('doc_id', '')}_chunk_{chunk_index}",
                chunk_index=chunk_index,
                total_chunks=0
            )
            chunks.append(chunk)
            
            start = end - self.chunk_overlap
            chunk_index += 1
        
        # Update total chunks
        total_chunks = len(chunks)
        for chunk in chunks:
            chunk.total_chunks = total_chunks
            chunk.metadata['total_chunks'] = total_chunks
        
        return chunks
    
    def _generate_doc_id(self, file_path: str) -> str:
        """Generate unique document ID based on file path."""
        abs_path = os.path.abspath(file_path)
        return hashlib.md5(abs_path.encode()).hexdigest()[:16]

    def _detect_doc_extractors(self) -> list:
        """Return a list of available tools that can extract DOC/.doc files.

        Checks for:
          - python package 'textract' importable
          - 'antiword' binary
          - 'catdoc' binary
          - 'wvText' binary
          - 'soffice' or 'libreoffice' binary
        """
        import shutil
        extractors = []

        # textract python package
        try:
            import textract  # type: ignore
            extractors.append('textract')
        except Exception:
            pass

        # CLI tools
        for binary, name in [('antiword', 'antiword'), ('catdoc', 'catdoc'), ('wvText', 'wvText'), ('soffice', 'libreoffice')]:
            if shutil.which(binary):
                extractors.append(name)

        return extractors