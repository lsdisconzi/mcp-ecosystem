import re
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

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
        processo_match = re.search(r'N[º°]\s*(\d[\d\.\-/]+)\s*\([Nn][º°]\s*CNJ:\s*([\d\.\-]+)\)', text)
        if processo_match:
            metadata["processo_numero"] = processo_match.group(1)
            metadata["cnj_number"] = processo_match.group(2)
        
        # Extract court/tribunal
        tribunal_patterns = [
            r'PRIMEIRA TURMA RECURSAL DA FAZENDA PÚBLICA',
            r'D[ÉE]CIMA [A-Z]+ C[ÂA]MARA C[ÍI]VEL',
            r'TRIBUNAL DE JUSTI[ÇC]A DO ESTADO',
            r'JUIZADO ESPECIAL [A-Z\s]+'
        ]
        
        for pattern in tribunal_patterns:
            match = re.search(pattern, text)
            if match:
                metadata["tribunal"] = match.group(0)
                break
        
        # Extract comarca
        comarca_match = re.search(r'Comarca de ([A-ZÀ-Ú\s]+)', text)
        if comarca_match:
            metadata["comarca"] = comarca_match.group(1)
        
        # Extract parties
        partes_section = re.search(r'([A-ZÀ-Ú\s]+)\s+RECORRENTE[E]?\s*\n([A-ZÀ-Ú\s]+)\s+RECORRIDO[O]?', text, re.MULTILINE)
        if partes_section:
            metadata["partes"]["recorrente"] = partes_section.group(1).strip()
            metadata["partes"]["recorrido"] = partes_section.group(2).strip()
        
        # Extract date
        date_match = re.search(r'(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})', text, re.IGNORECASE)
        if date_match:
            metadata["data"] = f"{date_match.group(1)}/{date_match.group(2)}/{date_match.group(3)}"
        
        # Extract relator and judges
        relator_match = re.search(r'(?:RELATOR[A]?|Relator[a]?):?\s*([A-ZÀ-Ú\s]+(?:\([A-Z]+\))?)', text)
        if relator_match:
            metadata["relator"] = relator_match.group(1).strip()
        
        # Extract cited legislation
        leg_citada = re.findall(r'(?:art\.|Lei|Código|Constituição)[\s\dº§\.\-/]+', text)
        metadata["legislacao_citada"] = list(set(leg_citada))
        
        # Extract cited jurisprudence
        jur_citada = re.findall(r'(?:REsp|RE|AI|AC|AP|ADI)\s+[\d\-\./]+', text)
        metadata["jurisprudencia_citada"] = list(set(jur_citada))
        
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
