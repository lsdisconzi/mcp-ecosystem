# Vendored transcript HTML render

**This directory is a derived snapshot, not a source of truth.**

The authoritative transcripts are the canonical JSON under
`transcription/data/transcripts/`, which this project reads through
`data/transcripts/json/`. These `.html` files are a *render* of the same
transcripts, produced by `transcription/`.

## Why it is vendored

Until 2026-09-13 this path was a symlink:

```
data/transcripts/html -> ../../../../olivia/_shared/cases/la8159/02-transcripts/transcripts_rendered/I-002
```

That target lives in a **different git repository** (`olivia`), whose
`.gitignore` excludes `_shared/`. The render was therefore **versioned
nowhere**, and any worktree, clone, or CI checkout outside the local tree
failed to run the test suite:

```
tests/test_layers.py::test_layer1_is_idempotent
    FileNotFoundError: .../data/transcripts/html/I-002_05_..._investigation.html
```

Copying the files in makes the checkout self-contained. `data/law` and
`data/transcripts/json` deliberately remain symlinks — both resolve to tracked
paths inside this repository (`transcription/data/...`), so they are portable
already; duplicating ~4.2MB of the corpus here would instead fork data that
`transcription/` owns by contract.

## Provenance

| | |
|---|---|
| Source | `olivia/_shared/cases/la8159/02-transcripts/transcripts_rendered/I-002` |
| Vendored | 2026-09-13 |
| Files | 29 `.html` |
| Rendered by | `transcription/` |

## Keeping it honest

`tests/test_sources.py::test_rendered_transcripts_match_json_segment_counts`
compares every render against its canonical JSON segment-by-segment, and
`tests/test_sources_json.py` pins the corpus magnitude. If `transcription/`
re-renders, re-copy this directory and re-run the suite — a stale render is
detected by those tests rather than silently trusted.

Note that `HtmlTranscriptSource` derives its `source_id` from the **filename**,
while `JsonTranscriptSource` uses the document's `transcript_id`. These agree
only while the two corpora stay in sync, which is the other thing those tests
protect.
