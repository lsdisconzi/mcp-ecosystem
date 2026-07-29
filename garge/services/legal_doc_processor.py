import re
import json
import logging
import uuid
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import docx
from pathlib import Path
import hashlib
from datetime import datetime

logger = logging.getLogger(__name__)

class LegalSectionType(Enum):
    HEADER = "header"
    ACORDAO = "acórdão"
    RELATORIO = "relatório"
    VOTOS = "votos"
    INTELECTO_TEOR = "inteiro_teor"
    SENTENCA = "sentença"
    PARECER = "parecer"
    RESUMO = "resumo"
    CONTENT = "conteúdo"

@dataclass
class LegalDocumentSection:
    """Represents a section of a legal document with metadata"""
    section_type: LegalSectionType
    title: str
    content: str
    page_reference: Optional[str] = None
    line_start: int = 0
    line_end: int = 0
    metadata: Dict[str, Any] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "section_type": self.section_type.value,
            "title": self.title,
            "content": self.content,
            "page_reference": self.page_reference,
            "line_range": f"{self.line_start}-{self.line_end}",
            **(self.metadata or {})
        }

class LegalDocumentExtractor:
    """Extracts and structures legal documents with section preservation"""
    
    # Brazilian legal document section patterns
    SECTION_PATTERNS = {
        LegalSectionType.HEADER: [
            r'^\s*(?:RECURSO|APELAÇÃO|EMBARGOS|AGRAVO|HABEAS|MANDADO|AÇÃO)\s+[A-ZÀ-Ú\s]+\.?\s*$',
            r'^[A-Z\s]+\s*-\s*[A-Z\s]+$',
            r'^\s*(?:Nº|Processo):?\s*\d+[-\.\d\w]+\s*\(.*\)\s*$'
        ],
        LegalSectionType.ACORDAO: [
            r'^\s*#?\s*AC[ÓO]RD[ÃA]O\s*$',
            r'^\s*AC[ÓO]RD[ÃA]O\s*{',
            r'^Vistos,\s+relatados\s+e\s+discutidos\s+os\s+autos\.$'
        ],
        LegalSectionType.RELATORIO: [
            r'^\s*#?\s*RELAT[ÓO]RIO\s*$',
            r'^\s*Relat[óo]rio\s*{',
            r'^Des\.\s+[A-Z\s]+\(?RELATOR\)?\s*'
        ],
        LegalSectionType.VOTOS: [
            r'^\s*#?\s*VOTOS\s*$',
            r'^\s*Voto[s]?\s*{',
            r'^[Dd]r[as]?\.\s+[A-Z\s]+\(?[A-Z\s]*\)?\s*$'
        ],
        LegalSectionType.INTELECTO_TEOR: [
            r'^\s*inteiro\s+teor\s*$',
            r'^\s*INTEIRO\s+TEOR\s*$'
        ],
        LegalSectionType.SENTENCA: [
            r'^\s*SENTEN[ÇC]A\s*$',
            r'^[Jj]ulgo\s+(?:procedente|improcedente|parcialmente)\s*',
            r'^\s*ANTE\s+O\s+EXPOSTO,\s+JULGO'
        ]
    }
    
    @staticmethod
    def extract_metadata_from_text(text: str) -> Dict[str, Any]:
        """Extract metadata from legal document text"""
        metadata = {
            "document_type": "unknown",
            "partes": {},
            "tribunal": None,
            "comarca": None,
            "processo_numero": None,
            "cnj_number": None,
            "data": None,
            "relator": None,
            "magistrados": [],
            "legislacao_citada": [],
            "jurisprudencia_citada": []
        }
        
        # Extract document type
        doc_type_patterns = {
            "recurso_inominado": r'RECURSO INOMINADO',
            "apelacao_civel": r'APELA[ÇC][ÃA]O C[ÍI]VEL',
            "acao_indentizatoria": r'A[ÇC][ÃA]O INDENIZAT[ÓO]RIA',
            "embargos": r'EMBARGOS',
            "agravo": r'AGRAVO',
            "resolucao": r'RESOLU[ÇC][ÃA]O',
            "portaria": r'PORTARIA',
            "decreto": r'DECRETO',
            "sumula": r'S[ÚU]MULA'
        }
        
        for doc_type, pattern in doc_type_patterns.items():
            if re.search(pattern, text, re.IGNORECASE):
                metadata["document_type"] = doc_type
                break
        
        # Extract process number and CNJ
        # Improved to handle newlines and table formats
        processo_match = re.search(r'N[º°]\s*(\d[\d\.\-/]+)', text)
        if processo_match:
            metadata["processo_numero"] = processo_match.group(1).strip()
            
        cnj_match = re.search(r'(?:CNJ|cnj):?\s*([\d\.\-]+)', text, re.IGNORECASE)
        if cnj_match:
            metadata["cnj_number"] = cnj_match.group(1).strip()
        
        # Extract court/tribunal
        tribunal_patterns = [
            r'PRIMEIRA TURMA RECURSAL DA FAZENDA PÚBLICA',
            r'D[ÉE]CIMA [A-ZÀ-Ú\s]+ C[ÂA]MARA C[ÍI]VEL',
            r'TRIBUNAL DE JUSTI[ÇC]A DO ESTADO',
            r'JUIZADO ESPECIAL [A-ZÀ-Ú\s]+'
        ]
        
        for pattern in tribunal_patterns:
            match = re.search(pattern, text)
            if match:
                metadata["tribunal"] = match.group(0).strip()
                break
        
        # Extract comarca
        comarca_match = re.search(r'(?:Comarca de|COMARCA DE)\s+([A-ZÀ-Ú\s]+)', text)
        if comarca_match:
            metadata["comarca"] = comarca_match.group(1).strip('| ').strip()
        
        # Extract parties
        # Improved to handle APELANTE/APELADO and RECORRENTE/RECORRIDO
        partes_patterns = [
            (r'([A-ZÀ-Ú\s]+)\s+(?:RECORRENTE|APELANTE)', "recorrente"),
            (r'([A-ZÀ-Ú\s]+)\s+(?:RECORRIDO|APELADO)', "recorrido")
        ]
        
        for pattern, role in partes_patterns:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                metadata["partes"][role] = match.group(1).strip('| ').strip()
        
        # Extract date
        date_match = re.search(r'(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})', text, re.IGNORECASE)
        if date_match:
            metadata["data"] = f"{date_match.group(1)}/{date_match.group(2)}/{date_match.group(3)}"
        
        # Extract relator and judges
        relator_match = re.search(r'(?:RELATOR[A]?|Relator[a]?):?\s*([A-ZÀ-Ú\s]+(?:\([A-Z]+\))?)', text)
        if relator_match:
            metadata["relator"] = relator_match.group(1).strip()
        
        # Extract cited legislation
        # Clean up whitespace and newlines in citations
        # Added Resolução, Portaria, Decreto and Súmula patterns for better legal coverage
        # Improved character class to handle 'nº', 'n.' and other common abbreviations
        leg_citada = re.findall(r'(?:art\.|Lei|Código|Constituição|Resolução|Res\.|Portaria|Port\.|Decreto|Súmula)[\s\dº§\.\-/nº°]+', text, re.IGNORECASE)
        metadata["legislacao_citada"] = sorted(list(set([re.sub(r'\s+', ' ', l).strip() for l in leg_citada])))
        
        # Extract cited jurisprudence
        jur_citada = re.findall(r'(?:REsp|RE|AI|AC|AP|ADI)\s+[\d\-\./]+', text)
        metadata["jurisprudencia_citada"] = sorted(list(set([re.sub(r'\s+', ' ', j).strip() for j in jur_citada])))
        
        return metadata
    
    @staticmethod
    def detect_section_type(line: str, context: List[str] = None) -> Optional[LegalSectionType]:
        """Detect the type of legal section from text"""
        line_stripped = line.strip()
        
        # Check each section type pattern
        for section_type, patterns in LegalDocumentExtractor.SECTION_PATTERNS.items():
            for pattern in patterns:
                if re.match(pattern, line_stripped, re.IGNORECASE):
                    return section_type
        
        # Context-based detection
        if context:
            context_text = " ".join(context[-3:])  # Last 3 lines
            if "Vistos, relatados e discutidos os autos" in context_text:
                return LegalSectionType.ACORDAO
            if any(word in line_stripped for word in ["voto", "vota", "votação"]):
                return LegalSectionType.VOTOS
            if "relatório" in line_stripped.lower():
                return LegalSectionType.RELATORIO
        
        return None
    
    def extract_sections(self, text: str) -> List[LegalDocumentSection]:
        """Extract structured sections from legal document text"""
        lines = text.split('\n')
        sections = []
        current_section = None
        current_content = []
        line_number = 0
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            
            # Check if this line starts a new section
            section_type = self.detect_section_type(line, lines[max(0, i-2):i])
            
            if section_type:
                # Save previous section if exists
                if current_section and current_content:
                    section = LegalDocumentSection(
                        section_type=current_section,
                        title=current_section.value.title(),
                        content='\n'.join(current_content).strip(),
                        line_start=line_number - len(current_content),
                        line_end=line_number - 1,
                        metadata={"section_depth": 1}
                    )
                    sections.append(section)
                
                # Start new section
                current_section = section_type
                current_content = [line_stripped]
                line_number = i
            elif current_section:
                # Continue current section
                if line_stripped or current_content:  # Keep empty lines within sections?
                    current_content.append(line_stripped)
            
            line_number = i
        
        # Don't forget the last section
        if current_section and current_content:
            section = LegalDocumentSection(
                section_type=current_section,
                title=current_section.value.title(),
                content='\n'.join(current_content).strip(),
                line_start=line_number - len(current_content) + 1,
                line_end=line_number,
                metadata={"section_depth": 1}
            )
            sections.append(section)
        
        return sections

class LegalDocumentChunker:
    """Chunks legal documents while preserving section structure"""
    
    def __init__(self, max_chunk_size: int = 1000, overlap: int = 100):
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap
    
    def chunk_section(self, section: LegalDocumentSection, 
                     section_id: int, doc_metadata: Dict) -> List[Dict[str, Any]]:
        """Chunk a single section, preserving its integrity"""
        chunks = []
        content = section.content
        
        # If section is small enough, keep it whole
        if len(content) <= self.max_chunk_size:
            chunk = {
                "text": content,
                "metadata": {
                    **doc_metadata,
                    "section_id": section_id,
                    "section_type": section.section_type.value,
                    "section_title": section.title,
                    "line_range": f"{section.line_start}-{section.line_end}",
                    "chunk_sequence": 0,
                    "is_complete_section": True,
                    "total_chunks_in_section": 1,
                    **(section.metadata or {})
                }
            }
            chunks.append(chunk)
            return chunks
        
        # If section is large, split by paragraphs while trying to preserve section
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        current_chunk = []
        current_size = 0
        chunk_index = 0
        
        for i, para in enumerate(paragraphs):
            para_size = len(para)
            
            # If adding this paragraph would exceed chunk size and we have content
            if current_size + para_size > self.max_chunk_size and current_chunk:
                # Create chunk
                chunk_text = '\n\n'.join(current_chunk)
                chunk = {
                    "text": chunk_text,
                    "metadata": {
                        **doc_metadata,
                        "section_id": section_id,
                        "section_type": section.section_type.value,
                        "section_title": section.title,
                        "paragraph_range": f"{i - len(current_chunk)}-{i-1}",
                        "chunk_sequence": chunk_index,
                        "is_complete_section": False,
                        "total_chunks_in_section": -1,  # Will be updated later
                        **(section.metadata or {})
                    }
                }
                chunks.append(chunk)
                chunk_index += 1
                
                # Start new chunk with overlap
                overlap_paras = current_chunk[-2:] if len(current_chunk) >= 2 else current_chunk[-1:]
                current_chunk = overlap_paras + [para]
                current_size = sum(len(p) for p in current_chunk)
            else:
                current_chunk.append(para)
                current_size += para_size
        
        # Don't forget the last chunk
        if current_chunk:
            chunk_text = '\n\n'.join(current_chunk)
            chunk = {
                "text": chunk_text,
                "metadata": {
                    **doc_metadata,
                    "section_id": section_id,
                    "section_type": section.section_type.value,
                    "section_title": section.title,
                    "paragraph_range": f"{len(paragraphs) - len(current_chunk)}-{len(paragraphs)-1}",
                    "chunk_sequence": chunk_index,
                    "is_complete_section": False,
                    "total_chunks_in_section": -1,  # Will be updated later
                    **(section.metadata or {})
                }
            }
            chunks.append(chunk)
        
        # Update total chunks in section for all chunks
        total_chunks = len(chunks)
        for chunk in chunks:
            chunk["metadata"]["total_chunks_in_section"] = total_chunks
        
        return chunks
    
    def chunk_document(self, sections: List[LegalDocumentSection], 
                      doc_metadata: Dict) -> List[Dict[str, Any]]:
        """Chunk entire document with section preservation"""
        all_chunks = []
        
        for section_id, section in enumerate(sections):
            section_chunks = self.chunk_section(section, section_id, doc_metadata)
            all_chunks.extend(section_chunks)
        
        return all_chunks

class LegalDocumentPipeline:
    """Main pipeline for legal document ingestion"""
    
    def __init__(self, qdrant_client, embedding_model=None):
        self.qdrant = qdrant_client
        self.embedding_model = embedding_model
        self.extractor = LegalDocumentExtractor()
        self.chunker = LegalDocumentChunker(max_chunk_size=1500, overlap=150)
    
    def extract_text_from_doc(self, file_path: str) -> str:
        """Extract text from DOC/DOCX file"""
        if file_path.endswith('.docx'):
            doc = docx.Document(file_path)
            return '\n'.join([para.text for para in doc.paragraphs])
        else:
            # For .doc files, we use the robust DocumentProcessor if available, 
            # but for this standalone version we'll try a simple approach or raise error
            try:
                from core.ingestion.document_processor import DocumentProcessor
                dp = DocumentProcessor()
                return dp.read_file_content(file_path)
            except ImportError:
                raise ValueError("DOC format requires core.ingestion.DocumentProcessor. Convert to DOCX first.")
    
    def generate_document_hash(self, text: str) -> str:
        """Generate unique hash for document"""
        return hashlib.sha256(text.encode()).hexdigest()[:16]
    
    def enrich_metadata(self, base_metadata: Dict, 
                       extracted_metadata: Dict,
                       sections: List[LegalDocumentSection]) -> Dict:
        """Enrich metadata with document structure"""
        # Calculate document statistics
        total_text_length = sum(len(section.content) for section in sections)
        section_types = [s.section_type.value for s in sections]
        
        enriched = {
            **base_metadata,
            **extracted_metadata,
            "document_hash": self.generate_document_hash(
                '\n'.join([s.content for s in sections])
            ),
            "total_sections": len(sections),
            "section_types_present": list(set(section_types)),
            "total_text_length": total_text_length,
            "ingestion_timestamp": datetime.now().isoformat(),
            "has_acordao": LegalSectionType.ACORDAO.value in section_types,
            "has_relatorio": LegalSectionType.RELATORIO.value in section_types,
            "has_votos": LegalSectionType.VOTOS.value in section_types
        }
        
        return enriched
    
    def ingest_legal_file(self, file_path: str, 
                         collection_name: str,
                         force_recreate: bool = False,
                         model_name: Optional[str] = None,
                         provided_metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """Main ingestion method with section-aware processing"""
        
        logger.info(f"Starting ingestion of {file_path}")
        
        # 1. Extract text
        text = self.extract_text_from_doc(file_path)
        
        # 2. Extract metadata
        extracted_metadata = self.extractor.extract_metadata_from_text(text)
        
        # 3. Extract sections
        sections = self.extractor.extract_sections(text)
        logger.info(f"Extracted {len(sections)} sections: {[s.section_type.value for s in sections]}")
        
        # 4. Prepare document metadata
        doc_metadata = self.enrich_metadata(
            provided_metadata or {},
            extracted_metadata,
            sections
        )
        
        # 5. Chunk document with section preservation
        chunks = self.chunker.chunk_document(sections, doc_metadata)
        logger.info(f"Created {len(chunks)} chunks from {len(sections)} sections")
        
        # 6. Generate embeddings
        if self.embedding_model:
            texts = [chunk["text"] for chunk in chunks]
            embeddings = self.embedding_model.encode(
                texts,
                show_progress_bar=True,
                normalize_embeddings=True
            )
        else:
            # Fallback to default embedding generator if available
            try:
                from core.ingestion.embedding_generator import EmbeddingGenerator
                eg = EmbeddingGenerator(model_name or "all-MiniLM-L6-v2")
                embeddings = eg.generate_embeddings([type('obj', (object,), {'text': t}) for t in texts])
            except ImportError:
                embeddings = None
        
        # 7. Prepare points for Qdrant
        from qdrant_client.models import PointStruct
        points = []
        for i, chunk in enumerate(chunks):
            # Qdrant requires UUID or integer IDs. Generate a deterministic UUID from the hash and index.
            string_id = f"{doc_metadata['document_hash']}_{i}"
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, string_id))
            
            point = PointStruct(
                id=point_id,
                vector=embeddings[i].tolist() if embeddings is not None else None,
                payload={
                    "text": chunk["text"],
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    **chunk["metadata"]
                }
            )
            points.append(point)
        
        # 8. Upload to Qdrant
        from qdrant_client.models import VectorParams, Distance
        
        # Ensure collection exists
        collections = self.qdrant.get_collections().collections
        collection_names = [c.name for c in collections]
        
        if force_recreate or collection_name not in collection_names:
            self.qdrant.recreate_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=len(embeddings[0]) if embeddings is not None else 384,
                    distance=Distance.COSINE
                )
            )
        
        # Create indexes for efficient filtering
        from qdrant_client.http import models
        index_fields = [
            "section_type",
            "document_type", 
            "tribunal",
            "comarca",
            "processo_numero",
            "cnj_number",
            "relator",
            "legislacao_citada",
            "jurisprudencia_citada"
        ]
        
        for field in index_fields:
            try:
                self.qdrant.create_payload_index(
                    collection_name=collection_name,
                    field_name=field,
                    field_schema=models.PayloadSchemaType.KEYWORD
                )
            except Exception:
                pass
        
        # Upload in batches
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i:i+batch_size]
            self.qdrant.upsert(
                collection_name=collection_name,
                points=batch
            )
        
        # 9. Return ingestion report
        return {
            "status": "success",
            "document_info": {
                "filename": Path(file_path).name,
                "document_hash": doc_metadata["document_hash"],
                "total_sections": len(sections),
                "section_breakdown": {
                    stype.value: len([s for s in sections if s.section_type == stype])
                    for stype in LegalSectionType
                },
                "total_chunks": len(chunks),
                "chunks_per_section": sum(1 for chunk in chunks 
                                        if chunk["metadata"].get("is_complete_section")) / len(chunks) * 100 if chunks else 0,
                "metadata_extracted": {
                    k: v for k, v in doc_metadata.items() 
                    if k in ["document_type", "processo_numero", "tribunal", "comarca", "relator"]
                }
            },
            "ingestion_stats": {
                "points_uploaded": len(points),
                "collection": collection_name,
                "embedding_model": model_name or "default",
                "timestamp": datetime.now().isoformat()
            }
        }
