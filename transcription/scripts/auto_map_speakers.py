#!/usr/bin/env python3
"""
auto_map_speakers.py — Automatically map descriptive speakers to canonical speaker IDs.

Iterates over transcript JSON files in a given directory.
Finds participants without a `speaker_id` whose `speaker_label` is descriptive 
(i.e., not a generic SPEAKER_XX).
Updates `canonical_name` and `speaker_id` in-place using the `narrative_id`.
"""

import json
import os
import re
import sys
from pathlib import Path


def slugify(text: str) -> str:
    """Convert text to a lowercase, hyphen-separated slug."""
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text.strip('-')


def process_directory(directory: Path):
    if not directory.exists():
        print(f"Error: {directory} does not exist.", file=sys.stderr)
        return

    updated_files_count = 0
    total_participants_updated = 0

    for path in directory.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"Warning: failed to parse {path.name}: {e}", file=sys.stderr)
            continue
            
        participants = data.get("participants", [])
        narrative_id = data.get("narrative_id") or data.get("transcript_id") or path.stem
        
        file_updated = False
        
        for p in participants:
            speaker_id = p.get("speaker_id")
            speaker_label = p.get("speaker_label", "").strip()
            
            # If missing speaker_id and it's a descriptive label (not generic SPEAKER_...)
            if not speaker_id and speaker_label and not re.match(r'^SPEAKER_\d+$', speaker_label, re.IGNORECASE):
                # We need to map it!
                new_canonical = f"{speaker_label} ({narrative_id})"
                new_speaker_id = f"SPK-{slugify(speaker_label)}-{slugify(narrative_id)}"
                
                p["canonical_name"] = new_canonical
                p["speaker_id"] = new_speaker_id
                
                file_updated = True
                total_participants_updated += 1
                
        if file_updated:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            updated_files_count += 1
            print(f"Updated {path.name}")

    print(f"Directory {directory.name}: Updated {total_participants_updated} participants across {updated_files_count} files.")


def main():
    repo_root = Path(__file__).resolve().parent.parent
    
    dirs_to_process = [
        repo_root / "data" / "transcripts",
        repo_root / "data" / "transcripts-named"
    ]
    
    for d in dirs_to_process:
        print(f"Processing directory: {d.relative_to(repo_root)} ...")
        process_directory(d)
        print("-" * 40)

if __name__ == "__main__":
    main()
