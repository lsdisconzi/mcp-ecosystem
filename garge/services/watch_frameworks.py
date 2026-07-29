#!/usr/bin/env python3
"""
Legal Frameworks Directory Watcher with Jurisdiction Enrichment
---------------------------------------------------------------
This script watches the legal_frameworks directory for changes and 
automatically generates/updates the framework_list.json file with
enriched jurisdiction data inferred from responsible entities.

Usage:
    python watch_frameworks.py
"""

import os
import json
import time
import logging
import re
from typing import Dict, Any

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    Observer = None

    class FileSystemEventHandler:  # type: ignore
        pass

    HAS_WATCHDOG = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Paths configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAMEWORKS_DIR = os.path.join(BASE_DIR, 'static', 'js', 'legal_frameworks')
OUTPUT_FILE = os.path.join(FRAMEWORKS_DIR, 'framework_list.json')
JURISDICTION_INDEX_FILE = os.path.join(
    BASE_DIR, 'static', 'js', 'legalframeworks-repository', 'jurisdiction_index.json'
)


class JurisdictionEnricher:
    """
    Enriches frameworks with jurisdiction information inferred from
    responsible entities, framework names, and framework types.
    """
    
    def __init__(self):
        # Jurisdiction mapping based on responsible entity patterns
        self.entity_jurisdiction_mapping = {
            # Brazilian entities
            "brazil": {"jurisdiction": "Brazil", "flag": "🇧🇷"},
            "governo do brasil": {"jurisdiction": "Brazil", "flag": "🇧🇷"},
            "government of brazil": {"jurisdiction": "Brazil", "flag": "🇧🇷"},
            "anac": {"jurisdiction": "Brazil", "flag": "🇧🇷"},
            "agência nacional de aviação civil": {"jurisdiction": "Brazil", "flag": "🇧🇷"},
            "national civil aviation agency": {"jurisdiction": "Brazil", "flag": "🇧🇷"},
            "agência nacional": {"jurisdiction": "Brazil", "flag": "🇧🇷"},
            "senacon": {"jurisdiction": "Brazil", "flag": "🇧🇷"},
            "procon": {"jurisdiction": "Brazil", "flag": "🇧🇷"},
            "anpd": {"jurisdiction": "Brazil", "flag": "🇧🇷"},
            "secretaria nacional": {"jurisdiction": "Brazil", "flag": "🇧🇷"},
            "abear": {"jurisdiction": "Brazil", "flag": "🇧🇷"},
            
            # Chilean entities
            "chile": {"jurisdiction": "Chile", "flag": "🇨🇱"},
            "gobierno de chile": {"jurisdiction": "Chile", "flag": "🇨🇱"},
            "government of chile": {"jurisdiction": "Chile", "flag": "🇨🇱"},
            "dgac": {"jurisdiction": "Chile", "flag": "🇨🇱"},
            "junta de aeronáutica civil": {"jurisdiction": "Chile", "flag": "🇨🇱"},
            "ley": {"jurisdiction": "Chile", "flag": "🇨🇱"},
            
            # Argentine entities
            "argentina": {"jurisdiction": "Argentina", "flag": "🇦🇷"},
            "gobierno de argentina": {"jurisdiction": "Argentina", "flag": "🇦🇷"},
            "government of argentina": {"jurisdiction": "Argentina", "flag": "🇦🇷"},
            "anac argentina": {"jurisdiction": "Argentina", "flag": "🇦🇷"},
            
            # Colombian entities
            "colombia": {"jurisdiction": "Colombia", "flag": "🇨🇴"},
            "aerocivil": {"jurisdiction": "Colombia", "flag": "🇨🇴"},
            
            # Peruvian entities
            "peru": {"jurisdiction": "Peru", "flag": "🇵🇪"},
            "perú": {"jurisdiction": "Peru", "flag": "🇵🇪"},
            "dgac perú": {"jurisdiction": "Peru", "flag": "🇵🇪"},
            
            # Corporate entities
            "conduct": {"jurisdiction": "Code of Conduct", "flag": "📜"},
            "latam - contrato de transporte aéreo": {"jurisdiction": "Brazil", "flag": "🇧🇷"},
            
            # International entities
            "icao": {"jurisdiction": "International", "flag": "🇺🇳"},
            "american": {"jurisdiction": "International", "flag": "🇺🇳"},
            "international civil aviation organization": {"jurisdiction": "International", "flag": "🇺🇳"},
            "organización de aviación civil internacional": {"jurisdiction": "International", "flag": "🇺🇳"},
            "iata": {"jurisdiction": "International", "flag": "🇺🇳"},
            "international air transport association": {"jurisdiction": "International", "flag": "🇺🇳"},
            "united nations": {"jurisdiction": "International", "flag": "🇺🇳"},
            "naciones unidas": {"jurisdiction": "International", "flag": "🇺🇳"},
            "onu": {"jurisdiction": "International", "flag": "🇺🇳"},
            "international": {"jurisdiction": "International", "flag": "🇺🇳"},
            "tokyo": {"jurisdiction": "International", "flag": "🇺🇳"},
            "ukbriberyact2010": {"jurisdiction": "International", "flag": "🇬🇧"},
            "Bribery Act": {"jurisdiction": "United Kingdom", "flag": "🇬🇧"},
            "UKBriberyAct2010": {"jurisdiction": "United Kingdom", "flag": "🇬🇧"}

        }
        
        # Resolution/Regulatory patterns for Brazilian frameworks
        self.resolution_patterns = [
            r'resolu[çc][ãa]o\s+(?:anac\s+)?n[oº°]?\.\s*\d+',
            r'resolution\s+n[oº°]?\.\s*\d+',
            r'resolu[çc][ãa]o\s+\d+',
            r'resolution\s+\d+',
        ]
        
        # Framework type hints
        self.framework_type_mapping = {
            "regulatory resolution": {"hint": "check_entity"},
            "national law": {"hint": "check_entity"},
            "international treaty": {"jurisdiction": "International", "flag": "🌐"},
            "industry standard": {"jurisdiction": "International", "flag": "🌐"},
        }
    
    def infer_jurisdiction_from_entity(self, text: str) -> Dict[str, str]:
        """
        Infer jurisdiction from entity name, framework name, or any text.
        Uses longest-match-first approach for accurate detection.
        """
        if not text:
            return {"jurisdiction": "Unknown", "flag": "🏳️"}
        
        text_lower = text.lower().strip()
        
        # Sort mapping keys by length (longest first) for better matching
        sorted_keys = sorted(self.entity_jurisdiction_mapping.keys(), key=len, reverse=True)
        
        for key in sorted_keys:
            if key in text_lower:
                return self.entity_jurisdiction_mapping[key].copy()
        
        # Check for Brazilian Resolution patterns
        for pattern in self.resolution_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                logging.debug(f"Matched Brazilian resolution pattern in: {text}")
                return {"jurisdiction": "Brazil", "flag": "🇧🇷"}
        
        # Pattern-based detection for country names
        country_patterns = [
            (r'\b(brazil|brasil)\b', "Brazil", "🇧🇷"),
            (r'\b(chile)\b', "Chile", "🇨🇱"),
            (r'\b(argentina)\b', "Argentina", "🇦🇷"),
            (r'\b(colombia)\b', "Colombia", "🇨🇴"),
            (r'\b(per[uú])\b', "Peru", "🇵🇪"),
            (r'\b(m[eé]xico|mexico)\b', "Mexico", "🇲🇽"),
        ]
        
        for pattern, country, flag in country_patterns:
            if re.search(pattern, text_lower):
                return {"jurisdiction": country, "flag": flag}
        
        return {"jurisdiction": "Unknown", "flag": "🏳️"}
    
    def infer_jurisdiction_from_framework_type(self, framework_type: str) -> Dict[str, str]:
        """Infer jurisdiction hints from framework type."""
        if not framework_type:
            return {}
        
        framework_type_lower = framework_type.lower().strip()
        
        for key, value in self.framework_type_mapping.items():
            if key in framework_type_lower:
                if "jurisdiction" in value:
                    return value
                # Otherwise it's just a hint to check entity
                return {}
        
        return {}
    
    def enrich_framework(self, framework_key: str, framework_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enrich a single framework with inferred jurisdiction and flag data.
        Priority: responsible_entity > framework_name > framework_type > jurisdiction_index
        """
        config = framework_data.get("config", {})
        responsible_entity = config.get("responsible_entity", "")
        framework_type = config.get("framework_type", "")
        framework_name = config.get("framework_name", framework_data.get("name", ""))
        
        # Track inference source
        inference_source = "none"
        confidence = "low"
        
        # Priority 1: Infer from responsible entity
        jurisdiction_info = self.infer_jurisdiction_from_entity(responsible_entity)
        if jurisdiction_info.get("jurisdiction") != "Unknown":
            inference_source = "responsible_entity"
            confidence = "high"
            logging.debug(f"✓ {framework_key}: Inferred from responsible entity '{responsible_entity}' → {jurisdiction_info['jurisdiction']} {jurisdiction_info['flag']}")
        
        # Priority 2: Infer from framework name
        if jurisdiction_info.get("jurisdiction") == "Unknown":
            name_info = self.infer_jurisdiction_from_entity(framework_name)
            if name_info.get("jurisdiction") != "Unknown":
                jurisdiction_info = name_info
                inference_source = "framework_name"
                confidence = "medium"
                logging.debug(f"✓ {framework_key}: Inferred from framework name '{framework_name}' → {jurisdiction_info['jurisdiction']} {jurisdiction_info['flag']}")
        
        # Priority 3: Infer from framework type
        if jurisdiction_info.get("jurisdiction") == "Unknown":
            type_info = self.infer_jurisdiction_from_framework_type(framework_type)
            if type_info.get("jurisdiction"):
                jurisdiction_info = type_info
                inference_source = "framework_type"
                confidence = "medium"
                logging.debug(f"✓ {framework_key}: Inferred from framework type '{framework_type}' → {jurisdiction_info['jurisdiction']} {jurisdiction_info['flag']}")
        
        # Priority 4: Keep existing jurisdiction from jurisdiction_index.json if available
        existing_jurisdiction = framework_data.get("primary_jurisdiction", "Unknown")
        existing_flag = framework_data.get("flag", "🏳️")
        
        if jurisdiction_info.get("jurisdiction") == "Unknown" and existing_jurisdiction != "Unknown":
            jurisdiction_info = {"jurisdiction": existing_jurisdiction, "flag": existing_flag}
            inference_source = "jurisdiction_index"
            confidence = "high"
            logging.debug(f"✓ {framework_key}: Using existing jurisdiction from index → {existing_jurisdiction} {existing_flag}")
        
        # Update framework data
        final_jurisdiction = jurisdiction_info.get("jurisdiction", "Unknown")
        final_flag = jurisdiction_info.get("flag", "🏳️")
        
        # Only update if we found something better than what exists
        should_update = (
            framework_data.get("primary_jurisdiction", "Unknown") == "Unknown" or
            inference_source in ["responsible_entity", "framework_name"] or
            (inference_source == "framework_type" and framework_data.get("primary_jurisdiction") == "Unknown")
        )
        
        if should_update:
            framework_data["primary_jurisdiction"] = final_jurisdiction
            framework_data["flag"] = final_flag
            framework_data["enrichment_metadata"] = {
                "inferred_from": inference_source,
                "confidence": confidence,
                "responsible_entity": responsible_entity,
                "framework_type": framework_type
            }
        
        return framework_data


class FrameworkHandler(FileSystemEventHandler):
    """Handles filesystem events and updates the framework list JSON with enrichment."""
    
    def __init__(self):
        self.last_updated = 0
        self.debounce_seconds = 2  # Debounce time to avoid multiple updates
        self.enricher = JurisdictionEnricher()
    
    def on_any_event(self, event):
        # Skip the framework_list.json file itself and any temporary files
        if (event.src_path.endswith('framework_list.json') or 
            '.git' in event.src_path or 
            '~' in event.src_path or
            '.DS_Store' in event.src_path):
            return
        
        # Debounce - only update if it's been more than N seconds since last update
        current_time = time.time()
        if current_time - self.last_updated < self.debounce_seconds:
            return
        
        self.last_updated = current_time
        logging.info(f"Change detected: {event.src_path}")
        self.update_framework_list()
    
    def update_framework_list(self):
        """Scan the directory and update the framework list JSON file with enrichment."""
        frameworks = {}
        enrichment_stats = {
            "total": 0,
            "enriched": 0,
            "from_entity": 0,
            "from_name": 0,
            "from_type": 0,
            "from_index": 0,
            "unknown": 0
        }

        # --- Load jurisdiction index (fallback source) ---
        try:
            with open(JURISDICTION_INDEX_FILE, 'r') as f:
                jurisdiction_index = json.load(f)
            logging.info(f"Loaded jurisdiction index with {len(jurisdiction_index)} jurisdictions")
        except Exception as e:
            logging.warning(f"Could not load jurisdiction_index.json: {e}")
            jurisdiction_index = {}

        # Build a key->(jurisdiction, flag) lookup from index
        key_to_jurisdiction = {}
        for jurisdiction, items in jurisdiction_index.items():
            for item in items:
                key_to_jurisdiction[item['key'].lower()] = {
                    'primary_jurisdiction': jurisdiction,
                    'flag': item.get('flag', '🌐')
                }

        try:
            for item in os.listdir(FRAMEWORKS_DIR):
                item_path = os.path.join(FRAMEWORKS_DIR, item)
                if not os.path.isdir(item_path):
                    continue
                if not (item.endswith('Analyzer') or 'Convention' in item or 'Rights' in item):
                    continue

                config_path = os.path.join(item_path, 'config.json')
                if not os.path.exists(config_path):
                    logging.warning(f"Directory {item} has no config.json, skipping")
                    continue

                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    
                    key = item.replace('Analyzer', '').lower()
                    framework_name = config.get('framework_name', self.format_framework_name(item))

                    # Start with jurisdiction from index if available
                    index_jurisdiction_info = key_to_jurisdiction.get(key, {
                        'primary_jurisdiction': 'Unknown',
                        'flag': '🏳️'
                    })

                    # Create initial framework data
                    framework_data = {
                        'name': framework_name,
                        'description': config.get('framework_description',
                            f"{config.get('framework_type', 'Legal')} - {config.get('responsible_entity', '')}"),
                        'defaultPrompt': config.get('default_prompt',
                            f"Analyze the transcript for compliance with {framework_name}..."),
                        'path': f"/static/js/legal_frameworks/{item}",
                        'directory': item,
                        'config': config,
                        'primary_jurisdiction': index_jurisdiction_info['primary_jurisdiction'],
                        'flag': index_jurisdiction_info['flag']
                    }

                    # Load generated prompt if exists
                    prompt_path = os.path.join(item_path, 'generated_prompt.txt')
                    if os.path.exists(prompt_path):
                        with open(prompt_path, 'r', encoding='utf-8') as f:
                            prompt_text = f.read()
                        framework_data['generatedPrompt'] = prompt_text
                        framework_data['generatedPromptLoaded'] = True

                    # --- ENRICH WITH INFERRED JURISDICTION ---
                    enriched_framework = self.enricher.enrich_framework(key, framework_data)
                    
                    # Track statistics
                    enrichment_stats["total"] += 1
                    
                    inference_source = enriched_framework.get("enrichment_metadata", {}).get("inferred_from", "none")
                    final_jurisdiction = enriched_framework.get("primary_jurisdiction", "Unknown")
                    
                    if final_jurisdiction != "Unknown":
                        enrichment_stats["enriched"] += 1
                        
                        if inference_source == "responsible_entity":
                            enrichment_stats["from_entity"] += 1
                            logging.info(f"✓ Enriched {key} from entity → {final_jurisdiction} {enriched_framework['flag']}")
                        elif inference_source == "framework_name":
                            enrichment_stats["from_name"] += 1
                            logging.info(f"✓ Enriched {key} from name → {final_jurisdiction} {enriched_framework['flag']}")
                        elif inference_source == "framework_type":
                            enrichment_stats["from_type"] += 1
                            logging.info(f"✓ Enriched {key} from type → {final_jurisdiction} {enriched_framework['flag']}")
                        elif inference_source == "jurisdiction_index":
                            enrichment_stats["from_index"] += 1
                    else:
                        enrichment_stats["unknown"] += 1
                        logging.warning(f"⚠ Could not determine jurisdiction for {key}")
                    
                    frameworks[key] = enriched_framework

                except json.JSONDecodeError:
                    logging.error(f"Error parsing config.json in {item}")
                except Exception as e:
                    logging.error(f"Error processing {item}: {e}")

            # Write enriched frameworks to file
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(frameworks, f, indent=2, ensure_ascii=False)

            # Log enrichment statistics
            logging.info(f"=" * 60)
            logging.info(f"Updated {OUTPUT_FILE} with {len(frameworks)} frameworks")
            logging.info(f"Enrichment Statistics:")
            logging.info(f"  Total Frameworks: {enrichment_stats['total']}")
            logging.info(f"  Enriched: {enrichment_stats['enriched']}")
            logging.info(f"    - From Entity: {enrichment_stats['from_entity']}")
            logging.info(f"    - From Name: {enrichment_stats['from_name']}")
            logging.info(f"    - From Type: {enrichment_stats['from_type']}")
            logging.info(f"    - From Index: {enrichment_stats['from_index']}")
            logging.info(f"  Unknown: {enrichment_stats['unknown']}")
            logging.info(f"=" * 60)

        except Exception as e:
            logging.error(f"Error updating framework list: {e}")
    
    @staticmethod
    def format_framework_name(dir_name: str) -> str:
        """Format a directory name into a readable framework name."""
        name = dir_name.replace('Analyzer', '')
        
        # Add spaces before capital letters
        formatted = ""
        for i, char in enumerate(name):
            if char.isupper() and i > 0 and name[i-1] != ' ':
                formatted += ' ' + char
            else:
                formatted += char
        
        # Replace underscores with spaces
        formatted = formatted.replace('_', ' ').strip()
        return formatted


def main():
    """Main function to start the directory watcher with enrichment."""
    logging.info(f"Starting Legal Frameworks Directory Watcher with Jurisdiction Enrichment")
    logging.info(f"Watching: {FRAMEWORKS_DIR}")
    logging.info(f"Output: {OUTPUT_FILE}")
    
    # Create the initial framework list with enrichment
    handler = FrameworkHandler()
    handler.update_framework_list()

    if not HAS_WATCHDOG:
        logging.warning("watchdog is not installed; generated framework_list.json once and exiting.")
        logging.warning("Install watchdog to enable continuous directory watching.")
        return
    
    # Set up the observer
    observer = Observer()
    observer.schedule(handler, FRAMEWORKS_DIR, recursive=True)
    observer.start()
    
    logging.info("Watching for changes... (Press Ctrl+C to stop)")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Stopping watcher...")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()