# Task Plan: Merge Two Transcript Versions into Final Canonical Set

## Goal
Merge two independent transcription runs (first_latam_case_version, 64 files + main_latam_case_version, 54 files) of the LATAM LA8159 airport incident into a single canonical transcript set with named speakers, proper metadata, and standardized schema.

## Current Phase
Complete

## Phases

### Phase 1: Cross-version file mapping
- [x] Load all 118 JSON files from both directories
- [x] Compute Jaccard similarity on normalized text + timestamp overlap
- [x] Produce mapping table (42 matched pairs, 12 main-only, 29 first-only)
- **Status:** complete

### Phase 2: Within-version deduplication
- [x] Load dedup_report.json (main version: 3 near-duplicates, 2 clusters)
- [x] Load dedup_report_2.json (first version: 5 near-duplicates, 4 clusters)
- [x] Exclude non-canonical files from merge
- **Status:** complete

### Phase 3: Merge logic
- [x] Matched pairs: use main version as base (named speakers, metadata), cross-check text against first version
- [x] Main-only files: include as-is
- [x] First-only files: upgrade to main schema (add audio_id, location, etc.)
- [x] Generate cross-check flags where main text < 50% of first version text
- **Status:** complete

### Phase 4: Schema standardization
- [x] All output follows: {title, audio_id, filename, recordingdatetime, location, content: [{speaker, start, end, text, id}]}
- [x] Strip internal _cross_check_flags before writing (bug found, fixed)
- **Status:** complete

### Phase 5: Output and reports
- [x] Write 75 canonical files to workspace/final_transcripts/
- [x] Generate merge_report.json with full mapping log
- [x] 5,063 total segments, ~334K characters
- **Status:** complete

### Phase 6: Verification
- [x] All 75 files valid JSON, correct schema
- [x] 50 files with named speakers, 25 with generic (first-only)
- [x] 0 leftover _cross_check_flags
- [x] Cross-version mapping independently validated by Explore agent
- **Status:** complete

## Key Outputs
- `workspace/final_transcripts/*.json` — 75 canonical transcript files
- `workspace/_intelligence/merge_report.json` — full merge log
- `workspace/merge_transcripts.py` — re-runnable merge script

## Errors Encountered
| Error | Resolution |
|-------|------------|
| `_cross_check_flags` written to output files (pop after json.dump) | Moved pop before write, stripped from existing files |
