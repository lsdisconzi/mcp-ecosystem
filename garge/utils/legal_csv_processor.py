"""
Legal CSV Document Processor
Handles text cleaning, chunking, and metadata extraction for legal documents.
"""
import re
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import pandas as pd

logger = logging.getLogger(__name__)


class LegalTextCleaner:
    """Cleans and normalizes legal text."""
    
    @staticmethod
    def clean_text(text: str) -> str:
        """
        Clean legal text by removing HTML entities and normalizing whitespace.
        
        Args:
            text: Raw text to clean
            
        Returns:
            Cleaned text
        """
        if not isinstance(text, str):
            return ""
        
        # Remove HTML entities
        text = re.sub(r'&nbsp;', ' ', text)
        text = re.sub(r'&quot;', '"', text)
        text = re.sub(r'&apos;', "'", text)
        text = re.sub(r'&amp;', '&', text)
        text = re.sub(r'&lt;', '<', text)
        text = re.sub(r'&gt;', '>', text)
        
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\n\s*\n', '\n\n', text)
        
        return text.strip()
    
    @staticmethod
    def split_by_legal_sections(text: str) -> List[Dict[str, str]]:
        """
        Split legal document by common sections.
        
        Args:
            text: Legal document text
            
        Returns:
            List of sections with type and content
        """
        sections = []
        
        # Common legal section markers
        section_patterns = [
            (r'EMENTA:?\s*', 'ementa'),
            (r'RELATÓRIO:?\s*', 'relatorio'),
            (r'VOTO:?\s*', 'voto'),
            (r'ACÓRDÃO:?\s*', 'acordao'),
            (r'DESPACHO:?\s*', 'despacho'),
            (r'DECISÃO:?\s*', 'decisao'),
            (r'FUNDAMENTAÇÃO:?\s*', 'fundamentacao'),
            (r'DISPOSITIVO:?\s*', 'dispositivo')
        ]
        
        # Find all section markers
        markers = []
        for pattern, section_type in section_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                markers.append((match.start(), section_type))
        
        # Sort by position
        markers.sort(key=lambda x: x[0])
        
        # Extract sections
        for i, (start, section_type) in enumerate(markers):
            end = markers[i + 1][0] if i + 1 < len(markers) else len(text)
            content = text[start:end].strip()
            
            if content:
                sections.append({
                    'type': section_type,
                    'content': content
                })
        
        # If no sections found, return entire text as single section
        if not sections:
            sections.append({
                'type': 'documento_completo',
                'content': text
            })
        
        return sections


class LegalMetadataExtractor:
    """Extracts structured metadata from legal documents."""
    
    @staticmethod
    def extract_parties(text: str) -> Dict[str, str]:
        """
        Extract parties involved in the legal case.
        
        Args:
            text: Legal document text
            
        Returns:
            Dictionary with party information
        """
        parties = {}
        
        # Common patterns for parties
        patterns = {
            'autor': r'(?:AUTOR|REQUERENTE|RECORRENTE):\s*([^\n]+)',
            'reu': r'(?:RÉU|REQUERIDO|RECORRIDO):\s*([^\n]+)',
            'apelante': r'APELANTE:\s*([^\n]+)',
            'apelado': r'APELADO:\s*([^\n]+)'
        }
        
        for party_type, pattern in patterns.items():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                parties[party_type] = match.group(1).strip()
        
        return parties
    
    @staticmethod
    def extract_decision(text: str) -> Optional[str]:
        """
        Extract the main decision from the document.
        
        Args:
            text: Legal document text
            
        Returns:
            Decision text or None
        """
        # Look for decision patterns
        decision_patterns = [
            r'(?:DECISÃO|ACORDAM):\s*([^\.]+\.)',
            r'(?:negaram|deram|conheceram)\s+(?:provimento|recursos?)[^\.]+\.',
            r'(?:mantiveram|reformaram)\s+(?:a\s+)?(?:sentença|decisão)[^\.]+\.'
        ]
        
        for pattern in decision_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0).strip()
        
        return None
    
    @staticmethod
    def extract_legal_basis(text: str) -> List[str]:
        """
        Extract legal foundations (laws, articles, etc.).
        
        Args:
            text: Legal document text
            
        Returns:
            List of legal references
        """
        legal_refs = []
        
        # Patterns for legal references
        patterns = [
            r'(?:Lei|Decreto|Portaria)\s+(?:nº|n\.?)?\s*[\d\.]+/[\d]+',
            r'(?:art(?:igo)?|Art)\.\s*[\d]+(?:º|°)?(?:,\s*[\d]+(?:º|°)?)*',
            r'(?:inciso|§)\s*[\d]+(?:º|°)?',
            r'Código\s+[\w\s]+',
            r'Constituição\s+Federal'
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            legal_refs.extend(matches)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_refs = []
        for ref in legal_refs:
            ref_clean = ref.strip()
            if ref_clean and ref_clean not in seen:
                seen.add(ref_clean)
                unique_refs.append(ref_clean)
        
        return unique_refs
    
    @staticmethod
    def extract_precedents(text: str) -> List[str]:
        """
        Extract legal precedents cited in the document.
        
        Args:
            text: Legal document text
            
        Returns:
            List of precedent references
        """
        precedents = []
        
        # Patterns for precedents
        patterns = [
            r'(?:REsp|AgRg|AREsp|HC|RHC|MS)\s+[\d\.]+',
            r'(?:Súmula|Súm\.)\s+(?:nº|n\.?)?\s*[\d]+',
            r'(?:Recurso\s+Especial|Habeas\s+Corpus)\s+[\d\.]+',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            precedents.extend(matches)
        
        return list(set(precedents))  # Remove duplicates


class LegalCSVProcessor:
    """Main processor for legal CSV files."""
    
    def __init__(self):
        self.cleaner = LegalTextCleaner()
        self.metadata_extractor = LegalMetadataExtractor()
    
    def load_csv(self, csv_path: str, encoding: str = 'utf-8') -> pd.DataFrame:
        """
        Load CSV file with error handling.
        
        Args:
            csv_path: Path to CSV file
            encoding: File encoding (default: utf-8)
            
        Returns:
            Pandas DataFrame
        """
        try:
            df = pd.read_csv(csv_path, encoding=encoding)
            logger.info(f"Loaded CSV with {len(df)} rows")
            return df
        except UnicodeDecodeError:
            # Try different encodings
            for enc in ['latin-1', 'iso-8859-1', 'cp1252']:
                try:
                    df = pd.read_csv(csv_path, encoding=enc)
                    logger.info(f"Loaded CSV with encoding {enc}, {len(df)} rows")
                    return df
                except:
                    continue
            raise
    
    def process_dataframe(self, df: pd.DataFrame, text_column: str = 'texto') -> pd.DataFrame:
        """
        Process DataFrame by cleaning text and extracting metadata.
        
        Args:
            df: Input DataFrame
            text_column: Name of column containing legal text
            
        Returns:
            Processed DataFrame with additional columns
        """
        if text_column not in df.columns:
            raise ValueError(f"Column '{text_column}' not found in DataFrame")
        
        # Clean text
        logger.info("Cleaning text...")
        df['texto_clean'] = df[text_column].apply(self.cleaner.clean_text)
        
        # Extract metadata
        logger.info("Extracting metadata...")
        df['parties'] = df['texto_clean'].apply(self.metadata_extractor.extract_parties)
        df['decision'] = df['texto_clean'].apply(self.metadata_extractor.extract_decision)
        df['legal_basis'] = df['texto_clean'].apply(self.metadata_extractor.extract_legal_basis)
        df['precedents'] = df['texto_clean'].apply(self.metadata_extractor.extract_precedents)
        
        # Add processing timestamp
        df['processed_at'] = datetime.now().isoformat()
        
        logger.info("Processing complete")
        return df
    
    def validate_required_columns(
        self,
        df: pd.DataFrame,
        required_columns: Optional[List[str]] = None
    ) -> bool:
        """
        Validate that DataFrame has required columns.
        
        Args:
            df: DataFrame to validate
            required_columns: List of required column names
            
        Returns:
            True if valid
            
        Raises:
            ValueError: If required columns are missing
        """
        if required_columns is None:
            required_columns = ['id', 'texto']
        
        missing = [col for col in required_columns if col not in df.columns]
        
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(missing)}")
        
        return True
    
    def get_statistics(self, df: pd.DataFrame, text_column: str = 'texto_clean') -> Dict[str, Any]:
        """
        Get statistics about the processed documents.
        
        Args:
            df: Processed DataFrame
            text_column: Column containing text
            
        Returns:
            Dictionary with statistics
        """
        stats = {
            'total_documents': len(df),
            'avg_text_length': df[text_column].str.len().mean(),
            'max_text_length': df[text_column].str.len().max(),
            'min_text_length': df[text_column].str.len().min(),
            'total_characters': df[text_column].str.len().sum()
        }
        
        # Count non-null metadata
        if 'parties' in df.columns:
            stats['documents_with_parties'] = df['parties'].apply(lambda x: bool(x)).sum()
        if 'decision' in df.columns:
            stats['documents_with_decision'] = df['decision'].notna().sum()
        if 'legal_basis' in df.columns:
            stats['documents_with_legal_basis'] = df['legal_basis'].apply(lambda x: bool(x)).sum()
        
        return stats
