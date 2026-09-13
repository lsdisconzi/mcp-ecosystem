"""JSON transcript source wrapper."""
from .sources import TranscriptSource, ParsedSegment
import json
from pathlib import Path

class JsonTranscriptSource:
    def __init__(self, path: str):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text())
    def source_id(self) -> str: return self.data.get("id", "")
    def source_uri(self) -> str: return str(self.path)
    def source_sha256(self) -> str: return ""
    def get_segment(self, segment_id: str) -> ParsedSegment | None: return None
    def all_segments(self) -> list[ParsedSegment]: return []

def expand_segment_index_spec(spec: str) -> list[str]: return [spec]
