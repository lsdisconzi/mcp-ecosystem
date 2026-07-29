import logging
import hashlib
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json

from .document_processor import DocumentChunk

logger = logging.getLogger(__name__)


@dataclass
class Utterance:
    """Represents a single utterance in a transcript"""
    speaker: str
    text: str
    start_time: float
    end_time: float
    index: int
    metadata: Dict[str, Any] = None


class TranscriptExtractor:
    """Extracts structured data from transcript JSON files"""

    SPEAKER_ROLE_PATTERNS = {
        'passenger': ['passenger', 'pasajero', 'cliente', 'user', 'customer'],
        'staff': ['staff', 'empleado', 'funcionario', 'counter', 'agent', 'representative'],
        'supervisor': ['supervisor', 'jefe', 'chief', 'manager', 'boss', 'lead'],
        'security': ['security', 'seguridad', 'DGAC', 'PDI', 'policía', 'police'],
        'pilot': ['pilot', 'piloto', 'capitán', 'captain', 'crew'],
        'unknown': []
    }

    @staticmethod
    def extract_utterances(transcript_data: Dict) -> List[Utterance]:
        """Extract utterances from transcript JSON."""
        utterances = []
        
        if "content" not in transcript_data or not isinstance(transcript_data["content"], list):
            logger.warning("No 'content' array found in transcript")
            return utterances

        for idx, item in enumerate(transcript_data["content"]):
            try:
                utterance = Utterance(
                    speaker=item.get('speaker', 'unknown'),
                    text=item.get('text', ''),
                    start_time=item.get('start', 0.0),
                    end_time=item.get('end', 0.0),
                    index=idx,
                    metadata=item.get('metadata', {})
                )
                utterances.append(utterance)
            except Exception as e:
                logger.warning(f"Failed to parse utterance {idx}: {e}")

        return utterances

    @staticmethod
    def normalize_speaker_role(speaker_label: str) -> str:
        """Normalize speaker role based on label patterns."""
        speaker_lower = speaker_label.lower()
        
        for role, patterns in TranscriptExtractor.SPEAKER_ROLE_PATTERNS.items():
            if role == 'unknown':
                continue
            if any(pattern.lower() in speaker_lower for pattern in patterns):
                return role
        
        return 'unknown'

    @staticmethod
    def extract_transcript_metadata(transcript_data: Dict) -> Dict[str, Any]:
        """Extract metadata from transcript."""
        metadata = {
            "transcript_id": None,
            "recording_date": None,
            "location": None,
            "audio_duration": None,
            "segment_count": None,
            "language": None,
            "custom_metadata": {}
        }

        # Extract standard fields
        if "recordingdatetime" in transcript_data:
            metadata["recording_date"] = transcript_data["recordingdatetime"]
        
        if "location" in transcript_data:
            metadata["location"] = transcript_data["location"]
        
        if "audio_duration" in transcript_data:
            metadata["audio_duration"] = transcript_data["audio_duration"]
        
        if "filename" in transcript_data:
            metadata["transcript_id"] = hashlib.md5(
                transcript_data["filename"].encode()
            ).hexdigest()[:16]
        
        # Extract any custom metadata
        for key in transcript_data:
            if key not in ["content", "recordingdatetime", "location", "audio_duration", "filename"]:
                if isinstance(transcript_data[key], (str, int, float, bool)):
                    metadata["custom_metadata"][key] = transcript_data[key]

        return metadata


class TranscriptChunker:
    """Smart chunking for transcript utterances preserving conversation flow"""

    def __init__(
        self,
        min_chunk_size: int = 200,
        max_chunk_size: int = 1000,
        overlap: int = 150,
        preserve_speaker_turns: bool = True,
        pause_threshold: float = 2.0
    ):
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap
        self.preserve_speaker_turns = preserve_speaker_turns
        self.pause_threshold = pause_threshold

    def chunk_utterances(
        self,
        utterances: List[Utterance],
        transcript_metadata: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Intelligently chunk utterances based on conversation flow."""
        chunks = []
        
        if not utterances:
            return chunks

        current_chunk = []
        current_size = 0
        chunk_index = 0

        for i, utterance in enumerate(utterances):
            utterance_size = len(utterance.text)
            
            # Check conditions for chunk completion
            should_finalize = False
            
            # 1. Size threshold exceeded
            if current_size + utterance_size > self.max_chunk_size and current_chunk:
                should_finalize = True
            
            # 2. Speaker turn change (if preserving turns)
            if self.preserve_speaker_turns and current_chunk:
                if utterance.speaker != current_chunk[-1].speaker:
                    should_finalize = True
            
            # 3. Significant pause detected
            if current_chunk and i > 0:
                pause = utterance.start_time - utterances[i-1].end_time
                if pause > self.pause_threshold:
                    should_finalize = True

            # Finalize current chunk if threshold met
            if should_finalize:
                chunk_data = self._create_chunk(
                    current_chunk,
                    chunk_index,
                    transcript_metadata
                )
                chunks.append(chunk_data)

                # Start new chunk with overlap
                overlap_utterances = self._get_overlap(current_chunk)
                current_chunk = overlap_utterances + [utterance]
                current_size = sum(len(u.text) for u in current_chunk)
                chunk_index += 1
            else:
                # Add to current chunk
                current_chunk.append(utterance)
                current_size += utterance_size

        # Add final chunk
        if current_chunk:
            chunk_data = self._create_chunk(
                current_chunk,
                chunk_index,
                transcript_metadata
            )
            chunks.append(chunk_data)

        return chunks

    def _create_chunk(
        self,
        utterances: List[Utterance],
        chunk_index: int,
        transcript_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a chunk from utterances."""
        
        # Build chunk text
        chunk_text = " ".join([u.text for u in utterances])
        
        # Extract speakers in chunk
        speakers = list(set([u.speaker for u in utterances]))
        speaker_roles = [
            TranscriptExtractor.normalize_speaker_role(s) for s in speakers
        ]

        # Time coverage
        start_time = min(u.start_time for u in utterances)
        end_time = max(u.end_time for u in utterances)

        # Build metadata
        metadata = {
            **transcript_metadata,
            "chunk_index": chunk_index,
            "speaker": speakers[0] if speakers else "unknown",
            "speakers": speakers,
            "speaker_roles": speaker_roles,
            "start_time": start_time,
            "end_time": end_time,
            "duration": end_time - start_time,
            "utterance_count": len(utterances),
            "utterance_indices": [u.index for u in utterances],
            "utterance_range": f"{utterances[0].index}-{utterances[-1].index}",
            "chunk_size": len(chunk_text),
            "ingestion_timestamp": datetime.now().isoformat(),
            "source": "transcript_enhanced"
        }

        return {
            "text": chunk_text,
            "metadata": metadata,
            "utterance_indices": [u.index for u in utterances]
        }

    def _get_overlap(self, utterances: List[Utterance], max_count: int = 2) -> List[Utterance]:
        """Get last N utterances for overlap."""
        return utterances[-max_count:] if len(utterances) > max_count else utterances


class TranscriptProcessor:
    """Complete transcript processing pipeline"""

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 150,
        preserve_speaker_turns: bool = True
    ):
        self.extractor = TranscriptExtractor()
        self.chunker = TranscriptChunker(
            max_chunk_size=chunk_size,
            overlap=chunk_overlap,
            preserve_speaker_turns=preserve_speaker_turns
        )

    def process_transcript_file(self, file_path: str) -> Dict[str, Any]:
        """Process transcript file and return structured data."""
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"Transcript file not found: {file_path}")

        with open(file_path, 'r', encoding='utf-8') as f:
            transcript_data = json.load(f)

        return self.process_transcript_data(transcript_data)

    def process_transcript_data(self, transcript_data: Dict) -> Dict[str, Any]:
        """Process transcript data and return structured output."""
        
        # Extract utterances
        utterances = self.extractor.extract_utterances(transcript_data)
        if not utterances:
            raise ValueError("No utterances found in transcript")

        # Extract metadata
        metadata = self.extractor.extract_transcript_metadata(transcript_data)

        # Generate chunks
        chunks = self.chunker.chunk_utterances(utterances, metadata)

        return {
            "transcript_id": metadata.get("transcript_id"),
            "metadata": metadata,
            "utterance_count": len(utterances),
            "chunk_count": len(chunks),
            "chunks": chunks,
            "speakers": list(set([u.speaker for u in utterances])),
            "duration": max([u.end_time for u in utterances], default=0) - min([u.start_time for u in utterances], default=0)
        }

    def convert_chunks_to_document_chunks(
        self,
        chunks: List[Dict[str, Any]],
        doc_hash: str
    ) -> List[DocumentChunk]:
        """Convert processed chunks to DocumentChunk format for ingestion."""
        
        document_chunks = []
        
        for chunk_data in chunks:
            doc_chunk = DocumentChunk(
                text=chunk_data["text"],
                metadata=chunk_data["metadata"],
                chunk_id=f"{doc_hash}_{chunk_data['metadata']['chunk_index']}",
                chunk_index=chunk_data['metadata']['chunk_index'],
                total_chunks=len(chunks)
            )
            document_chunks.append(doc_chunk)

        return document_chunks
