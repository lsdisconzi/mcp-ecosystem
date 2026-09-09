# file: violation_object_normalizer.py
"""
VIOLATION OBJECT NORMALIZER
Extracts and structures violation data into standardized JSON format
"""

import json
import re
import hashlib
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional, Union
import spacy
from dataclasses import dataclass, asdict
from enum import Enum

class SeverityBucket(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"

class ActorType(str, Enum):
    ORGANIZATION = "organization"
    INDIVIDUAL = "individual"
    GOVERNMENT = "government"
    SYSTEM = "system"

class RoleType(str, Enum):
    SUSPECT = "suspect"
    VICTIM = "victim"
    WITNESS = "witness"
    RESPONSIBLE = "responsible"

@dataclass
class Actor:
    actor_id: str
    name: str
    normalized_name: str
    actor_type: ActorType
    role: RoleType

@dataclass
class Action:
    action_id: str
    description: str
    sequence_index: int
    actor_id: str

@dataclass
class LegalArticle:
    article_id: str
    framework_code: str
    article_code: str
    jurisdiction: str
    reference: str
    full_text: Optional[str] = None

@dataclass
class Evidence:
    evidence_id: str
    type: str
    source: str
    excerpt: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    segment_ids: Optional[List[str]] = None

@dataclass
class TranscriptSegment:
    segment_id: str
    speaker: str
    start_time: str
    end_time: str
    text: str
    confidence: Optional[float] = None

@dataclass
class Provenance:
    provenance_id: str
    source_file: str
    analysis_run: str
    extraction_datetime: str

class ViolationObjectNormalizer:
    """
    Extracts and normalizes violation data into structured objects
    Compatible with IntegratedLegalFrameworkParser outputs
    """
    
    def __init__(self, nlp_model: str = "en_core_web_sm"):
        """
        Initialize with NLP model for entity extraction
        """
        try:
            self.nlp = spacy.load(nlp_model)
        except OSError:
            print(f"Warning: SpaCy model '{nlp_model}' not found. Installing...")
            import subprocess
            subprocess.run(["python", "-m", "spacy", "download", nlp_model])
            self.nlp = spacy.load(nlp_model)
        
        # Entity extraction patterns
        self.entity_patterns = {
            "airlines": r'(LATAM|Avianca|Azul|Gol|American Airlines|Delta|United)\s*(?:Airlines)?',
            "airports": r'\b(SCL|GRU|GIG|EZE|MIA|JFK|LAX|MAD|CDG)\b',
            "dates": r'\b(\d{4}-\d{2}-\d{2})T?(\d{2}:\d{2}:\d{2})?Z?\b',
            "times": r'\b(\d{1,2}:\d{2}(?::\d{2})?)\b',
            "article_refs": r'(Article|Art\.?|§|Artículo)\s*(\d+[a-z]?[\.\d]*)',
        }
        
        # Framework code mappings
        self.framework_codes = {
            "Código de Defesa do Consumidor": "CDC_BR",
            "Lei 8.078/1990": "CDC_BR",
            "Montreal Convention": "ICAO_MC99",
            "Convención de Montreal": "ICAO_MC99",
            "ANAC Resolution": "ANAC_BR",
            "ICAO Annex": "ICAO",
            "DGAC Regulation": "DGAC_CL",
            "EU Regulation": "EU_261",
        }
        
        # Jurisdiction codes
        self.jurisdiction_codes = {
            "Brazil": "BR",
            "Chile": "CL",
            "International": "INTL",
            "European Union": "EU",
            "United States": "US",
            "Argentina": "AR"
        }
    
    def generate_checksum(self, data: Dict) -> str:
        """
        Generate SHA-256 checksum of violation object (excluding checksum field)
        """
        data_copy = data.copy()
        if "checksum" in data_copy:
            del data_copy["checksum"]
        
        # Sort keys for consistent hashing
        sorted_json = json.dumps(data_copy, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(sorted_json.encode()).hexdigest()[:32]
    
    def extract_actors_from_text(self, text: str) -> List[Actor]:
        """
        Extract actors (organizations/individuals) from text using NLP
        """
        actors = []
        doc = self.nlp(text)
        
        # Extract organizations
        for ent in doc.ents:
            if ent.label_ in ["ORG", "PERSON", "GPE"]:
                actor_type = ActorType.ORGANIZATION if ent.label_ == "ORG" else ActorType.INDIVIDUAL
                actor_id = f"ACT_{ent.text.upper().replace(' ', '_')[:10]}_{hashlib.md5(ent.text.encode()).hexdigest()[:6]}"
                
                actors.append(Actor(
                    actor_id=actor_id,
                    name=ent.text,
                    normalized_name=ent.text.lower(),
                    actor_type=actor_type,
                    role=RoleType.SUSPECT if "airline" in ent.text.lower() else RoleType.RESPONSIBLE
                ))
        
        # Fallback: pattern matching for airlines
        if not actors:
            for match in re.finditer(self.entity_patterns["airlines"], text, re.IGNORECASE):
                actor = Actor(
                    actor_id=f"ACT_{match.group(1).upper().replace(' ', '_')}",
                    name=match.group(0),
                    normalized_name=match.group(0).lower(),
                    actor_type=ActorType.ORGANIZATION,
                    role=RoleType.SUSPECT
                )
                actors.append(actor)
        
        return actors
    
    def extract_actions_from_violation(self, violation_text: str, actors: List[Actor]) -> List[Action]:
        """
        Extract actions from violation description
        """
        actions = []
        
        # Common violation action patterns
        action_patterns = [
            (r'refused\s+to\s+provide', "Refusal to provide information"),
            (r'denied\s+boarding', "Denial of boarding"),
            (r'delayed\s+flight', "Flight delay"),
            (r'cancelled\s+flight', "Flight cancellation"),
            (r'failed\s+to\s+inform', "Failure to inform"),
            (r'overbooked', "Overbooking"),
            (r'lost\s+luggage', "Lost luggage"),
            (r'damaged\s+property', "Property damage"),
            (r'harassed', "Harassment"),
            (r'discriminated', "Discrimination"),
        ]
        
        for i, (pattern, description) in enumerate(action_patterns, 1):
            if re.search(pattern, violation_text, re.IGNORECASE):
                # Assign to first actor if available
                actor_id = actors[0].actor_id if actors else "ACT_UNKNOWN"
                
                actions.append(Action(
                    action_id=f"ACTN_{i:03d}",
                    description=description,
                    sequence_index=i,
                    actor_id=actor_id
                ))
        
        # If no patterns matched, create a generic action
        if not actions:
            actions.append(Action(
                action_id="ACTN_001",
                description="Violation of legal provision",
                sequence_index=1,
                actor_id=actors[0].actor_id if actors else "ACT_UNKNOWN"
            ))
        
        return actions
    
    def extract_legal_articles(self, legal_reference: str, framework_name: str) -> List[LegalArticle]:
        """
        Extract legal article references from violation text
        """
        articles = []
        
        # Extract article references
        matches = re.finditer(self.entity_patterns["article_refs"], legal_reference, re.IGNORECASE)
        
        for match in matches:
            article_type = match.group(1)
            article_number = match.group(2)
            
            # Determine framework code
            framework_code = "UNKNOWN"
            for key, code in self.framework_codes.items():
                if key.lower() in framework_name.lower():
                    framework_code = code
                    break
            
            # Determine jurisdiction
            jurisdiction = "INTL"
            if "brazil" in framework_name.lower() or "brasil" in framework_name.lower():
                jurisdiction = "BR"
            elif "chile" in framework_name.lower():
                jurisdiction = "CL"
            
            articles.append(LegalArticle(
                article_id=f"{framework_code}_{article_number.replace('.', '_')}",
                framework_code=framework_code,
                article_code=f"{article_type} {article_number}",
                jurisdiction=jurisdiction,
                reference=f"Violation of {article_type} {article_number}",
                full_text=legal_reference
            ))
        
        return articles
    
    def extract_evidence(self, transcript_evidence: str, timestamp: str = None) -> Evidence:
        """
        Extract evidence from transcript excerpts
        """
        # Parse timestamp if provided
        start_time = None
        end_time = None
        
        if timestamp:
            time_match = re.search(r'\[?(\d{1,2}:\d{2}(?::\d{2})?)\s*[-–]\s*(\d{1,2}:\d{2}(?::\d{2})?)\]?', timestamp)
            if time_match:
                start_time = time_match.group(1)
                end_time = time_match.group(2)
        
        return Evidence(
            evidence_id=f"EVID_{hashlib.md5(transcript_evidence.encode()).hexdigest()[:8].upper()}",
            type="transcript",
            source="Flight communication transcript",
            excerpt=transcript_evidence[:500],  # Truncate if too long
            start_time=start_time,
            end_time=end_time,
            segment_ids=["SEG_01"]  # Will be populated by transcript segments
        )
    
    def extract_transcript_segments(self, transcript_text: str, timestamp: str = None) -> List[TranscriptSegment]:
        """
        Extract structured segments from transcript text
        """
        segments = []
        
        # Simple parsing of transcript lines
        lines = transcript_text.split('\n')
        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
            
            # Try to extract speaker and time
            speaker = "UNKNOWN"
            start_time = None
            end_time = None
            
            # Pattern: [HH:MM:SS] Speaker: Text
            time_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', line)
            speaker_match = re.search(r'(\w+):\s*(.+)', line)
            
            if time_match:
                start_time = time_match.group(1)
            if speaker_match:
                speaker = speaker_match.group(1)
                text = speaker_match.group(2)
            else:
                text = line
            
            segments.append(TranscriptSegment(
                segment_id=f"SEG_{i:02d}",
                speaker=speaker,
                start_time=start_time or "00:00:00",
                end_time=end_time or "00:00:00",
                text=text[:200]  # Truncate
            ))
        
        return segments[:3]  # Return first 3 segments max
    
    def determine_severity(self, severity_text: str) -> Dict[str, str]:
        """
        Parse severity text into structured bucket
        """
        severity_lower = severity_text.lower()
        
        if "critical" in severity_lower:
            return {"bucket": SeverityBucket.CRITICAL}
        elif "high" in severity_lower:
            return {"bucket": SeverityBucket.HIGH}
        elif "moderate" in severity_lower:
            return {"bucket": SeverityBucket.MODERATE}
        elif "low" in severity_lower:
            return {"bucket": SeverityBucket.LOW}
        else:
            return {"bucket": SeverityBucket.MODERATE}  # Default
    
    def extract_location(self, text: str) -> str:
        """
        Extract location code (airport/region) from text
        """
        # Look for airport codes
        for match in re.finditer(self.entity_patterns["airports"], text):
            return match.group(1)
        
        # Look for city/country mentions
        doc = self.nlp(text)
        for ent in doc.ents:
            if ent.label_ == "GPE":
                return ent.text.upper()[:3]
        
        return "UNK"
    
    def parse_violation_from_legal_analysis(self, 
                                          violation_text: str,
                                          case_id: str = None,
                                          framework_name: str = "Unknown",
                                          source_file: str = "unknown.md") -> Dict[str, Any]:
        """
        Main method: Parse legal violation text into structured object
        """
        # Generate unique IDs
        violation_id = f"VIOL_{uuid.uuid4().hex[:8]}"
        if not case_id:
            case_id = f"CASE_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:4]}"
        
        # Extract components from violation text
        # Assuming structure: [Violation Name]\n\nTranscript Evidence: "[...]"\n\nLegal Reference: [...]
        lines = violation_text.split('\n')
        
        # Parse structured parts
        violation_name = lines[0].strip() if lines else "Unknown Violation"
        transcript_evidence = ""
        legal_reference = ""
        timestamp = ""
        
        for i, line in enumerate(lines):
            if "Transcript Evidence:" in line:
                # Extract quoted text
                quote_match = re.search(r'["\'“”]([^"\']+)["\'“”]', line)
                if quote_match:
                    transcript_evidence = quote_match.group(1)
                # Extract timestamp if present
                time_match = re.search(r'\[([^\]]+)\]', line)
                if time_match:
                    timestamp = time_match.group(1)
            elif "Legal Reference:" in line:
                legal_reference = line.replace("Legal Reference:", "").strip()
        
        # Extract data using helper methods
        actors = self.extract_actors_from_text(violation_text)
        actions = self.extract_actions_from_violation(violation_text, actors)
        legal_articles = self.extract_legal_articles(legal_reference, framework_name)
        evidence = self.extract_evidence(transcript_evidence, timestamp)
        transcript_segments = self.extract_transcript_segments(transcript_evidence)
        
        # Determine jurisdiction from framework
        jurisdiction_code = "UNK"
        for country, code in self.jurisdiction_codes.items():
            if country.lower() in framework_name.lower():
                jurisdiction_code = code
                break
        
        # Determine framework code
        framework_code = "UNKNOWN"
        for key, code in self.framework_codes.items():
            if key.lower() in framework_name.lower():
                framework_code = code
                break
        
        # Create violation object
        violation_obj = {
            "violation_id": violation_id,
            "case_id": case_id,
            "jurisdiction": jurisdiction_code,
            "framework_code": framework_code,
            "category": self.categorize_violation(violation_name),
            "violation_type": violation_name,
            "severity": self.determine_severity(violation_text),
            "confidence": 0.85,  # Could be calculated based on evidence quality
            "status": "OPEN",
            "datetime": datetime.now().isoformat() + "Z",
            "location": self.extract_location(violation_text),
            "checksum": "",  # Will be calculated below
            
            "actors": [asdict(actor) for actor in actors],
            "actions": [asdict(action) for action in actions],
            "legal_articles": [asdict(article) for article in legal_articles],
            "evidence": [asdict(evidence)],
            "transcript_segments": [asdict(segment) for segment in transcript_segments],
            
            "provenance": {
                "provenance_id": f"PROV_{uuid.uuid4().hex[:8]}",
                "source_file": source_file,
                "analysis_run": "normalizer_v1",
                "extraction_datetime": datetime.now().isoformat() + "Z"
            }
        }
        
        # Calculate checksum
        violation_obj["checksum"] = self.generate_checksum(violation_obj)
        
        return violation_obj
    
    def categorize_violation(self, violation_name: str) -> str:
        """
        Categorize violation into broader categories
        """
        name_lower = violation_name.lower()
        
        categories = {
            "safety": ["safety", "security", "danger", "risk", "emergency"],
            "consumer": ["consumer", "passenger", "customer", "rights", "information"],
            "procedural": ["procedure", "process", "documentation", "compliance"],
            "discrimination": ["discrimination", "bias", "prejudice", "unequal"],
            "financial": ["compensation", "refund", "payment", "overcharge"],
            "privacy": ["privacy", "data", "personal information", "confidential"],
            "service": ["service", "quality", "delay", "cancellation", "boarding"],
        }
        
        for category, keywords in categories.items():
            if any(keyword in name_lower for keyword in keywords):
                return category.capitalize()
        
        return "General"
    
    def batch_process_legal_analysis(self, 
                                   analysis_text: str,
                                   case_id: str = None,
                                   framework_name: str = "Unknown") -> List[Dict[str, Any]]:
        """
        Process entire legal analysis text, extracting multiple violations
        """
        violations = []
        
        # Split analysis into individual violations
        # Pattern: a) [Violation Name] followed by sections
        violation_pattern = r'([a-h])\)\s+([^\n]+)(?:\n\nTranscript Evidence:[^\n]+\n\nLegal Reference:[^\n]+(?:\n\nAnalysis:[^\n]+)?)'
        
        matches = re.finditer(violation_pattern, analysis_text, re.IGNORECASE | re.DOTALL)
        
        for match in matches:
            letter = match.group(1)
            violation_block = match.group(0)
            
            violation_obj = self.parse_violation_from_legal_analysis(
                violation_text=violation_block,
                case_id=case_id,
                framework_name=framework_name,
                source_file="legal_analysis.md"
            )
            
            violations.append(violation_obj)
        
        return violations
    
    def export_to_json(self, violation_objects: List[Dict], output_path: str):
        """
        Export violation objects to JSON file
        """
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(violation_objects, f, indent=2, ensure_ascii=False)
        
        print(f"Exported {len(violation_objects)} violation objects to {output_path}")
        return output_path
    
    def generate_js_export_function(self, violation_objects: List[Dict]) -> str:
        """
        Generate JavaScript function for web integration
        """
        js_template = f"""
/**
 * VIOLATION OBJECT EXPORT
 * Generated: {datetime.now().isoformat()}
 */

const VIOLATION_DATA = {json.dumps(violation_objects, indent=2, ensure_ascii=False)};

function exportViolationObjects() {{
    const dataStr = JSON.stringify(VIOLATION_DATA, null, 2);
    const dataBlob = new Blob([dataStr], {{type: 'application/json'}});
    
    const exportLink = document.createElement('a');
    exportLink.href = URL.createObjectURL(dataBlob);
    exportLink.download = 'violation_objects_' + new Date().toISOString().split('T')[0] + '.json';
    exportLink.click();
    
    return VIOLATION_DATA.length;
}}

// Attach to global window object
if (typeof window !== 'undefined') {{
    window.exportViolationObjects = exportViolationObjects;
    window.VIOLATION_DATA = VIOLATION_DATA;
    
    console.log(`Loaded ${{VIOLATION_DATA.length}} violation objects`);
}}
"""
        return js_template