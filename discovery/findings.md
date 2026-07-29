# Findings: Transcript Merge

## Structure Differences Between Versions

| Property | first_latam_case_version | main_latam_case_version |
|---|---|---|
| Segments key | `segments` | `content` |
| Speaker labels | Generic (SPEAKER_00, SPEAKER_01) or mixed | Named (Leandro Disconzi, DGAC, Latam Staff) |
| Date format | `recordingDateTime` (camelCase) | `recordingdatetime` (lowercase) |
| Dates used | Mostly transcription dates (2025-06-03) | Actual recording dates (2024-07-05/06) |
| Location metadata | Absent | Present |
| File count | 64 | 54 |

## Cross-Version File Mapping

- **42 matched pairs** — same audio, different transcription runs
- **12 main-only files** — many are `_segment_*` files that split larger recordings; some have no first-version counterpart (e.g., guarulhos_airport_BD_Marinho.json)
- **29 first-only files** — includes duplicate/near-duplicate files (_copy variants, alternate transcriptions); 5 excluded as non-canonical

### Key Matches (High Confidence)
- `aeropuerto_STG_12.json` <-> `audio_12_full.json` (sim=1.000)
- `aeropuerto_STG_7.json` <-> `PDI_outside_where_the_magic_happens.json` (sim=0.913)
- `aeropuerto_STG_15.json` <-> `Aeropuerto_Arturo_Merino_Beni_tez_15.1.json` (sim=0.937)
- `Terminal_Internacional_T2.json` <-> `T2_DGAC_sends_to_Latam_counter.json` (sim=0.967)

### Interesting Low-Confidence Matches
- `aeropuerto_STG_23.json` <-> `Aeropuerto_Arturo_Merino_Beni_tez_23.2.json` (sim=0.246) — main has 111 segs vs first's 401 segs; likely different segmentation of same long recording
- `aeropuerto_STG_6.json` <-> `DGAC_contradictions_meet_jose.json` (sim=0.235) — main 343 segs vs first 82 segs; main version has much more content

## Within-Version Near-Duplicates

### Main Version (3 near-duplicates)
- `aeropuerto_STG_22_segment_1.json` and `segment_2` are near-duplicates of `aeropuerto_STG_22.json` (sim=0.904)
- `aeropuerto_STG_7_segment_8.json` is near-duplicate of `aeropuerto_STG_7_8_corruption.json` (sim=0.847)

### First Version (5 near-duplicates)
- `Aeropuerto_Arturo_Merino_Beni_tez_15.3.json` and `_15.json` are near-duplicates of `_15.1.json`
- `_5_copy.json` near-duplicate of `_5.json`
- `Nova_Gravac_a_o_2.json` near-duplicate of `_2.2.json`
- `Terminal_Internacional_-_T2.json` near-duplicate of `transcript_1748818294.json`

## Merge Quality Observations

1. **Main version is clearly superior**: named speakers, actual recording dates, location metadata, better transcription accuracy
2. **First version has coverage gaps filled by main**: many first-version files have generic speakers where main has names
3. **First version has unique content**: 21 files exist only in first version (after dedup), primarily `Aeropuerto_Arturo_Merino_Beni_tez_*` numbered files
4. **Cross-check flags**: 4 files flagged (19 total flagged segments) where main text is significantly shorter than first version — these need human review
5. **Guarulhos file is entirely unique**: `guarulhos_airport_BD_Marinho.json` has no first-version counterpart, transcribing a different airport (São Paulo)

## Naming Pattern Notes
- Main version: `aeropuerto_STG_N.json` pattern with `_segment_*` sub-files
- First version: `Aeropuerto_Arturo_Merino_Beni_tez_N.json` pattern + descriptive names
- `latam_STG_*` files in main correspond to `Nova_Gravac_a_o_*` files in first
- `audio_*_full.json` in first are the "full" versions of recordings that main splits differently
