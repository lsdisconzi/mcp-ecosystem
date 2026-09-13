#!/usr/bin/env python3
"""
generate_speaker_index.py — Scan all transcripts and build a dynamic speaker mapping index.

Iterates over all `.json` files in `data/transcripts/`.
Extracts all participants and unique segment speakers.
Uses case-insensitive resolution against `role` and `speaker_label` to match segment speakers to participants.
Categorizes speakers into `mapped_speakers` (those with a `speaker_id`) and `unmapped_speakers`.
Outputs the global index to `data/speaker_index.json` and a summary to stdout.
"""

import json
import os
import sys
from pathlib import Path
from collections import defaultdict


def resolve_speaker_id(seg_speaker: str, participants: list) -> str | None:
    """Resolve the segment speaker label to a participant's speaker_id."""
    if not seg_speaker:
        return None
    
    seg_speaker_lower = seg_speaker.strip().lower()
    for p in participants:
        p_role = (p.get("role") or "").strip().lower()
        p_label = (p.get("speaker_label") or "").strip().lower()
        
        if seg_speaker_lower == p_role or seg_speaker_lower == p_label:
            return p.get("speaker_id")
    return None


def main():
    repo_root = Path(__file__).resolve().parent.parent
    transcripts_dir = repo_root / "data" / "transcripts-named"
    output_file = repo_root / "data" / "speaker_index.json"

    if not transcripts_dir.exists():
        print(f"Error: {transcripts_dir} does not exist.", file=sys.stderr)
        sys.exit(1)

    mapped_speakers = defaultdict(list)
    unmapped_speakers = []

    total_transcripts = 0
    total_segments_scanned = 0

    for path in transcripts_dir.glob("*.json"):
        total_transcripts += 1
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"Warning: failed to parse {path.name}: {e}", file=sys.stderr)
            continue
            
        transcript_id = data.get("transcript_id", path.stem)
        participants = data.get("participants", [])
        
        # 1. Process participants explicitly defined in the metadata
        for p in participants:
            speaker_id = p.get("speaker_id")
            entry = {
                "transcript_id": transcript_id,
                "type": "participant",
                "canonical_name": p.get("canonical_name"),
                "role": p.get("role"),
                "speaker_label": p.get("speaker_label")
            }
            
            if speaker_id:
                mapped_speakers[speaker_id].append(entry)
            else:
                unmapped_speakers.append(entry)
                
        # 2. Process unique segment speakers
        segments = data.get("segments", [])
        unique_seg_speakers = set()
        
        for seg in segments:
            total_segments_scanned += 1
            if isinstance(seg, dict):
                # Handle old vs new segment schema if necessary
                speaker = seg.get("speaker")
                if isinstance(speaker, dict):
                    spk_label = speaker.get("label", "")
                else:
                    spk_label = str(speaker or "")
                    
                if spk_label:
                    unique_seg_speakers.add(spk_label)
                    
        for spk_label in unique_seg_speakers:
            speaker_id = resolve_speaker_id(spk_label, participants)
            if speaker_id:
                mapped_speakers[speaker_id].append({
                    "transcript_id": transcript_id,
                    "type": "segment",
                    "speaker": spk_label
                })
            else:
                # If it didn't resolve to a participant, or resolved to one without a speaker_id,
                # we flag this segment speaker as unmapped as well.
                # Avoid duplicate unmapped entries if the participant was already captured.
                unmapped_speakers.append({
                    "transcript_id": transcript_id,
                    "type": "segment",
                    "speaker": spk_label
                })

    unique_unmapped = []
    seen = set()
    for item in unmapped_speakers:
        key = tuple(sorted((k, str(v)) for k, v in item.items()))
        if key not in seen:
            seen.add(key)
            unique_unmapped.append(item)

    mapped_dict = {k: v for k, v in sorted(mapped_speakers.items())}
    
    index_data = {
        "summary": {
            "total_transcripts_scanned": total_transcripts,
            "total_segments_scanned": total_segments_scanned,
            "total_mapped_speaker_ids": len(mapped_dict),
            "total_unmapped_instances": len(unique_unmapped)
        },
        "mapped_speakers": mapped_dict,
        "unmapped_speakers": unique_unmapped
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2, ensure_ascii=False)

    print("=" * 60)
    print("SPEAKER INDEX GENERATION COMPLETE")
    print("=" * 60)
    print(f"Transcripts scanned    : {total_transcripts}")
    print(f"Segments scanned       : {total_segments_scanned}")
    print(f"Unique Mapped IDs      : {len(mapped_dict)}")
    print(f"Unmapped Instances     : {len(unique_unmapped)} (HUMAN CONFIRMATION NEEDED)")
    print("-" * 60)
    print(f"Output saved to        : {output_file.relative_to(repo_root)}")
    print("=" * 60)
    
    if unique_unmapped:
        print("\nTop 5 Unmapped Instances:")
        for item in unique_unmapped[:5]:
            print(f"  - {item}")
        if len(unique_unmapped) > 5:
            print(f"  ... and {len(unique_unmapped) - 5} more.")

if __name__ == "__main__":
    main()
