# -*- coding: utf-8 -*-
"""
domain/entities/canonical_entities.py

Pure domain entities — zero infrastructure imports.
All canonical entity types used throughout the Argus system.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class CanonicalEntity:
    schema_version: str = "2.0"
    schema_type: str = ""
    category: str = ""
    provenance: Dict[str, Any] = None

    def __post_init__(self):
        if self.provenance is None:
            self.provenance = {
                "source": "",
                "generated_at": datetime.now().isoformat(),
                "analyst": "Argus Legal Framework",
            }


@dataclass
class CanonicalViolation(CanonicalEntity):
    schema_type: str = "violation"
    violation_id: str = ""
    case_id: str = ""
    jurisdiction: str = ""
    framework_code: str = ""
    violation_type: str = ""
    severity: str = "UNKNOWN"
    confidence: float = 0.85
    status: str = "OPEN"
    actor_ids: List[str] = field(default_factory=list)
    action_ids: List[str] = field(default_factory=list)
    legal_article_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    checksum: str = ""


@dataclass
class CanonicalEvidence(CanonicalEntity):
    schema_type: str = "evidence"
    evidence_id: str = ""
    case_id: str = ""
    type: str = "transcript"
    source: str = ""
    excerpt: str = ""
    start_time: str = ""
    end_time: str = ""
    transcript_segment_ids: List[str] = field(default_factory=list)
    checksum: str = ""


@dataclass
class CanonicalSegment(CanonicalEntity):
    schema_type: str = "segment"
    segment_id: str = ""
    case_id: str = ""
    speaker: str = ""
    start_time: str = ""
    end_time: str = ""
    text: str = ""
    checksum: str = ""


@dataclass
class CanonicalArticle(CanonicalEntity):
    schema_type: str = "article"
    # ELI identifier — e.g. "BR.CBA.T3.C1.Art.74" — primary key across systems
    eli_id: str = ""
    article_id: str = ""          # legacy alias, kept for backward compat
    framework_code: str = ""
    framework_name: str = ""
    article_number: str = ""      # "74", "0", "1" etc.
    jurisdiction: str = ""
    reference: str = ""
    text: str = ""                # full article text from the law corpus
    full_text: Optional[str] = None  # legacy alias
    theme: str = ""               # high-level theme from the law corpus
    hierarchy: Dict[str, Any] = field(default_factory=dict)  # title/chapter/section/paragraph
    checksum: str = ""


@dataclass
class CanonicalActor(CanonicalEntity):
    schema_type: str = "actor"
    actor_id: str = ""
    name: str = ""
    normalized_name: str = ""
    actor_type: str = ""  # organization | individual | government | system
    role: str = ""        # suspect | victim | witness | responsible
    checksum: str = ""


@dataclass
class CanonicalAction(CanonicalEntity):
    schema_type: str = "action"
    action_id: str = ""
    description: str = ""
    sequence_index: int = 1
    actor_id: str = ""
    checksum: str = ""
