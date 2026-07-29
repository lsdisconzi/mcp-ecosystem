#!/usr/bin/env python3
"""
Enhanced Transcript Structure Analyzer
Examines transcript JSON structure and suggests optimal ingestion parameters.
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime
import hashlib


class TranscriptAnalyzer:
    def __init__(self, transcript_path: str):
        self.transcript_path = Path(transcript_path)
        self.data = self.load_transcript()
        self.analysis = {}

    def load_transcript(self) -> Dict:
        """Load and validate transcript JSON."""
        if not self.transcript_path.exists():
            raise FileNotFoundError(f"Transcript not found: {self.transcript_path}")

        with open(self.transcript_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return data

    def analyze_structure(self) -> Dict[str, Any]:
        """Comprehensive transcript structure analysis."""
        analysis = {
            "filename": self.transcript_path.name,
            "file_size_bytes": self.transcript_path.stat().st_size,
            "analysis_timestamp": datetime.now().isoformat(),
            "document_hash": hashlib.md5(json.dumps(self.data, sort_keys=True).encode()).hexdigest()
        }

        # 1. Basic structure
        analysis["keys"] = list(self.data.keys())
        analysis["depth"] = self.calculate_json_depth(self.data)

        # 2. Content analysis
        if "content" in self.data:
            content = self.data["content"]
            analysis["content_type"] = type(content).__name__

            if isinstance(content, list):
                analysis["utterance_count"] = len(content)
                analysis["speaker_distribution"] = self.analyze_speakers(content)
                analysis["time_coverage"] = self.analyze_timing(content)
                analysis["text_stats"] = self.analyze_text(content)

        # 3. Metadata extraction
        analysis["metadata_present"] = self.extract_metadata()

        # 4. Suggested ingestion parameters
        analysis["ingestion_recommendations"] = self.generate_recommendations()

        self.analysis = analysis
        return analysis

    def analyze_speakers(self, content: List[Dict]) -> Dict:
        """Analyze speaker distribution and roles."""
        speakers = {}
        for i, utterance in enumerate(content):
            speaker = utterance.get('speaker', 'unknown')
            if speaker not in speakers:
                speakers[speaker] = {
                    "count": 0,
                    "indices": [],
                    "total_duration": 0.0,
                    "avg_duration": 0.0
                }

            speakers[speaker]["count"] += 1
            speakers[speaker]["indices"].append(i)

            # Calculate duration if available
            if 'start' in utterance and 'end' in utterance:
                duration = utterance['end'] - utterance['start']
                speakers[speaker]["total_duration"] += duration
                speakers[speaker]["avg_duration"] = speakers[speaker]["total_duration"] / speakers[speaker]["count"]

        return speakers

    def analyze_timing(self, content: List[Dict]) -> Dict:
        """Analyze timing and gaps in conversation."""
        if not content or 'start' not in content[0]:
            return {"available": False}

        times = {
            "start_time": content[0]['start'],
            "end_time": content[-1]['end'],
            "total_duration": content[-1]['end'] - content[0]['start'],
            "gaps": [],
            "turn_taking": []
        }

        # Calculate gaps between utterances
        for i in range(1, len(content)):
            gap = content[i]['start'] - content[i-1]['end']
            if gap > 0:
                times["gaps"].append({
                    "index": i,
                    "gap_seconds": gap,
                    "from_speaker": content[i-1].get('speaker'),
                    "to_speaker": content[i].get('speaker')
                })

        # Analyze turn-taking patterns
        speaker_changes = 0
        for i in range(1, len(content)):
            if content[i].get('speaker') != content[i-1].get('speaker'):
                speaker_changes += 1

        times["speaker_changes"] = speaker_changes
        times["avg_utterance_duration"] = times["total_duration"] / len(content) if content else 0

        return times

    def analyze_text(self, content: List[Dict]) -> Dict:
        """Analyze text content and statistics."""
        stats = {
            "total_characters": 0,
            "total_words": 0,
            "avg_words_per_utterance": 0,
            "max_utterance_length": 0,
            "min_utterance_length": float('inf'),
            "language_indicators": self.detect_language_indicators(content)
        }

        word_counts = []
        for utterance in content:
            text = utterance.get('text', '')
            char_count = len(text)
            word_count = len(text.split())

            stats["total_characters"] += char_count
            stats["total_words"] += word_count
            word_counts.append(word_count)

            stats["max_utterance_length"] = max(stats["max_utterance_length"], word_count)
            stats["min_utterance_length"] = min(stats["min_utterance_length"], word_count)

        if word_counts:
            stats["avg_words_per_utterance"] = sum(word_counts) / len(word_counts)

        return stats

    def detect_language_indicators(self, content: List[Dict]) -> Dict:
        """Detect language patterns in transcript."""
        common_spanish = ['el', 'la', 'los', 'las', 'y', 'de', 'que']
        common_portuguese = ['o', 'a', 'os', 'as', 'e', 'de', 'que']

        sample_text = ' '.join([u.get('text', '')[:100] for u in content[:10]])
        sample_lower = sample_text.lower()

        spanish_count = sum(sample_lower.count(word) for word in common_spanish)
        portuguese_count = sum(sample_lower.count(word) for word in common_portuguese)

        return {
            "likely_spanish": spanish_count > portuguese_count,
            "likely_portuguese": portuguese_count > spanish_count,
            "mixed_language": abs(spanish_count - portuguese_count) < 3
        }

    def extract_metadata(self) -> Dict:
        """Extract available metadata from transcript."""
        metadata = {}

        # Common metadata fields
        metadata_fields = [
            'recordingdatetime', 'location', 'filename',
            'audio_duration', 'segment_count', 'transcript_id'
        ]

        for field in metadata_fields:
            if field in self.data:
                metadata[field] = self.data[field]

        # Look for nested metadata
        if 'metadata' in self.data and isinstance(self.data['metadata'], dict):
            metadata.update(self.data['metadata'])

        return metadata

    def generate_recommendations(self) -> Dict:
        """Generate optimal ingestion recommendations."""
        recs = {
            "chunking_strategy": "variable_smart",
            "vector_embedding": "paraphrase-multilingual-MiniLM-L12-v2",
            "collection_name": f"transcripts_{self.data.get('location', 'unknown').lower().replace(' ', '_')}",
            "payload_indexes": []
        }

        # Based on content analysis
        if "content" in self.data and isinstance(self.data["content"], list):
            utterance_count = len(self.data["content"])

            # Determine chunk size
            if utterance_count > 50:
                recs["chunk_size"] = 800
                recs["chunk_overlap"] = 150
                recs["chunking_strategy"] = "speaker_turn_preserving"
            else:
                recs["chunk_size"] = 1500
                recs["chunk_overlap"] = 200
                recs["chunking_strategy"] = "semantic_topic_based"

            # Determine payload indexes needed
            speakers = self.analyze_speakers(self.data["content"])
            if len(speakers) > 1:
                recs["payload_indexes"].extend(["speaker", "speaker_role"])

            if self.data.get("location"):
                recs["payload_indexes"].append("location")

            if self.data.get("recordingdatetime"):
                recs["payload_indexes"].append("recording_date")

        return recs

    def calculate_json_depth(self, obj, depth=0):
        """Calculate maximum depth of JSON structure."""
        if isinstance(obj, dict):
            return max((self.calculate_json_depth(v, depth+1) for v in obj.values()), default=depth)
        elif isinstance(obj, list):
            return max((self.calculate_json_depth(item, depth+1) for item in obj), default=depth)
        return depth

    def save_analysis_report(self, output_path: str = None):
        """Save analysis report to file."""
        if not output_path:
            output_path = f"{self.transcript_path.stem}_analysis.json"

        report = {
            "transcript": self.transcript_path.name,
            "analysis": self.analysis,
            "ingestion_template": self.generate_ingestion_template()
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"✓ Analysis saved to: {output_path}")
        return output_path

    def generate_ingestion_template(self) -> Dict:
        """Generate a ready-to-use ingestion template."""
        template = {
            "collection_config": {
                "name": f"transcripts_{self.data.get('location', 'airport').lower().replace(' ', '_')}",
                "vector_size": 384,  # For multilingual MiniLM
                "distance_metric": "cosine",
                "optimizers_config": {
                    "indexing_threshold": 10000,
                    "memmap_threshold": 20000
                }
            },
            "payload_schema": {
                "text": {"type": "text", "indexed": True},
                "transcript_id": {"type": "keyword", "indexed": True},
                "speaker": {"type": "keyword", "indexed": True},
                "speaker_role": {"type": "keyword", "indexed": True},
                "recording_date": {"type": "datetime", "indexed": True},
                "location": {"type": "keyword", "indexed": True},
                "utterance_index": {"type": "integer", "indexed": True},
                "start_time": {"type": "float", "indexed": False},
                "end_time": {"type": "float", "indexed": False},
                "chunk_index": {"type": "integer", "indexed": False},
                "total_chunks": {"type": "integer", "indexed": False}
            },
            "chunking_config": {
                "strategy": "smart_speaker_turn",
                "min_chunk_size": 200,
                "max_chunk_size": 1000,
                "overlap": 150,
                "preserve_speaker_turns": True,
                "detect_topic_changes": True
            },
            "ingestion_endpoint": "/v2/transcripts/ingest-enhanced",
            "ingestion_parameters": {
                "preserve_speaker_turns": True,
                "enhanced": True,
                "model_name": "paraphrase-multilingual-MiniLM-L12-v2",
                "speaker_normalization": True,
                "detect_emotions": True,
                "extract_entities": True
            }
        }

        return template


# Command-line interface
if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python transcript_analyzer.py <transcript_file.json>")
        sys.exit(1)

    transcript_file = sys.argv[1]

    try:
        analyzer = TranscriptAnalyzer(transcript_file)
        analysis = analyzer.analyze_structure()

        print("\n" + "="*60)
        print("TRANSCRIPT ANALYSIS REPORT")
        print("="*60)

        print(f"\n📄 File: {analysis['filename']}")
        print(f"📏 Size: {analysis['file_size_bytes']:,} bytes")
        print(f"🗂️  Structure Keys: {', '.join(analysis['keys'])}")

        if "utterance_count" in analysis:
            print(f"🗣️  Utterances: {analysis['utterance_count']}")
            print(f"👥 Speakers: {len(analysis['speaker_distribution'])}")

            for speaker, stats in analysis['speaker_distribution'].items():
                print(f"   • {speaker}: {stats['count']} utterances")

        if "time_coverage" in analysis and analysis["time_coverage"].get("available", True):
            time_info = analysis["time_coverage"]
            if "total_duration" in time_info:
                print(f"⏱️  Duration: {time_info['total_duration']:.1f}s")
                print(f"🔄 Speaker changes: {time_info.get('speaker_changes', 0)}")

        print("\n💡 RECOMMENDATIONS:")
        recs = analysis["ingestion_recommendations"]
        print(f"   • Chunking: {recs['chunking_strategy']}")
        print(f"   • Chunk size: {recs.get('chunk_size', 'auto')}")
        print(f"   • Collection: {recs['collection_name']}")
        print(f"   • Embedding: {recs['vector_embedding']}")
        if recs.get('payload_indexes'):
            print(f"   • Indexes: {', '.join(recs['payload_indexes'])}")

        # Save detailed report
        report_file = analyzer.save_analysis_report()

        print("\n" + "="*60)
        print(f"✅ Detailed report saved to: {report_file}")
        print("="*60)

    except Exception as e:
        print(f"❌ Error analyzing transcript: {e}")
        sys.exit(1)
