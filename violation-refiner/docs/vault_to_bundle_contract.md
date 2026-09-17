# `examples/vault_to_bundle.py` — paths, definitions, expected structure, dependents

**Subject:** `examples/vault_to_bundle.py` — **1815 lines** (verified with `wc -l`; the file has no
trailing newline, so it holds 1816 content lines). Re-verified after the `DEFAULT_SOURCE` change.
**Role:** the *only* producer of a bundle. It converts a LA8159 vault violation document
(schema 4.0) into the **final** `build/<VID>/` layout that `refine_batch` consumes. There is no
staging hop: `refine_batch_core._load_violation` returns the file it writes *verbatim* as soon as
it validates.

> **Drift warning.** `project_actual_report_and_proposal_improvements.md:318` records this file as
> **1605 lines**. The real count is **1815**. Treat that table row as stale; re-derive counts from
> the tree, not from the report.

---

## 1. Paths

### 1.1 CLI defaults (module constants, lines 76–103)

| Constant | Line | Value | Notes |
| --- | --- | --- | --- |
| `_REPO_ROOT` | 76 | `Path(__file__).resolve().parents[1]` | inserted into `sys.path` so `python examples/vault_to_bundle.py` works from the repo root |
| `DEFAULT_SOURCE` | 93 | `data/violations` | repo-local as of 2026-09-17: one flat `<VID>.json` per bundle (**81** files), seeded from the `build/<VID>/<VID>.json` set. Replaced an **absolute path into a different repo** (`olivia/…/_json/EN`, whose `_json/{BR,ES,IT}` siblings held partial translations) |
| `DEFAULT_TRANSCRIPT_DIR` | 96 | `data/transcripts/json` | a symlink tree — see `docs/data_source_of_truth.md` §3.2 |
| `DEFAULT_LAW_ROOT` | 97 | `data/law` | a symlink to `../../transcription/data/law` |
| `DEFAULT_OUTPUT` | 100 | `build` | the bundle root *is* this directory; `build/<VID>/` is one bundle |
| `DEFAULT_SPEAKER_INDEX` | 103 | `data/speaker_index.json` | file symlink to `../../transcription/data/speaker_index.json` |

Two vault roots exist in practice: `DEFAULT_SOURCE` above, and `$VAULT_SOURCE`
(`examples/run_one.sh:153` defaults it to `/awareness/shared/violations`). `run_one.sh` always
passes `--source`, so the module default is only reached when the script is called by hand.
`examples/run_one_local.sh:157` used to hardcode the same `olivia` path and now defaults to
`data/violations` as well.

> **`data/violations` as seeded cannot be converted.** The 81 files copied from `build/` are
> *bundle* documents (schema `3.0`): `segments` present, `full_segments` **absent**,
> `element_grids` a **list**, and no `legal_basis` / `case` / `allegation_summary` /
> `incident_timestamp`. `load_violation` (1565) requires the *vault* shape documented in §3.1.
> Every seeded file is therefore rejected — see §5 finding 6.

### 1.2 Paths read

| Path | Read by | Line |
| --- | --- | --- |
| `<source>/<VID>.json` | `find_violation_path` | 1624 |
| `<source>/<jurisdiction>-*.json` (`--all`; `*.json` when `--jurisdiction ''`) | `_resolve_inputs` | 1713 |
| any `.json` given positionally (bypasses `<source>`) | `_resolve_inputs` | 1713 |
| `<transcript_dir>/*.json` | `build_transcript_index` | 321 |
| `<law_root>/_mapping/law_registry.json` | `FrameworkResolver._load` | 259 |
| `<law_root>/<rel>` — each framework Markdown named by the registry | `stage_bundle` (symlink target) | 1441 |
| `<speaker_index>` | `stage_bundle` (symlink target) | 1441 |
| an already-written `<VID>.json` (validation gate) | `_reconcile_contract_confidence` | 1529 |

### 1.3 Paths written

`convert_one` (1578) writes the first two unconditionally; `stage_bundle` (1441) writes the rest
**only when `stage=True`** (`--inputs-only` skips them).

| Path | When | Line |
| --- | --- | --- |
| `<output>/<VID>/` (the directory itself) | always | 1583 |
| `<output>/<VID>/contract.json` | always | 1594 |
| `<output>/<VID>/segments_manifest.json` | always | 1601 |
| `<output>/<VID>/<VID>.json` | `stage` | 1517 |
| `<output>/<VID>/conversion_warnings.json` | `stage` | 1616 |
| `<output>/<VID>/Transcripts/<file>.json` | `stage`, symlink | 1465 |
| `<output>/<VID>/Legal framework/<CODE>.md` | `stage`, symlink | 1478 |
| `<output>/<VID>/speaker_index.json` | `stage`, symlink, only if it exists | 1487 |
| `<output>/<VID>/<VID>.json.invalid` | **only** on a validation failure (1499 → 1505–1511) — then `ValueError` is raised at 1512 | 1505 |
| `<output>/<VID>/contract.json` (rewritten) | `stage`, only when `_reconcile_contract_confidence` moved the snapshot | 1522 |

**No path outside `<output>/<VID>/` is ever written.** The one risk in the codebase is that the
`Transcripts/` and `Legal framework/` entries are symlinks into the shared corpus, so a write
*through* one of them rewrites the corpus for every bundle at once. `stage_bundle` never writes
through them (it only creates/replaces links); `segment_sync` explicitly unlinks before writing
for exactly this reason.

---

## 2. Definitions

### 2.1 Constants

| Name | Line | Purpose |
| --- | --- | --- |
| `_AUDIO_ID_RULES` | 108 | 4 **anchored** `(regex, template)` pairs → `STG-{0}`, `LATAM-{0}`, `CARABINEROS-{0}`, `BDM`. Anchored on purpose: unanchored, `STG_2` also matches inside `latam_STG_2` |
| `_VALID_SEVERITIES` | 117 | `LOW, MEDIUM, HIGH, CRITICAL` |
| `_VALID_APPLICABILITY` | 118 | `direct, indirect_predicate, supporting` |
| `_VALID_NORM_TYPES` | 119 | `prohibition, penalty, right, liability, definition, exemption` |
| `_VALID_PRIORITY` | 127 | `low, medium, high, critical` |
| `_VALID_PROOF_STATUS` | 131 | `established, strong, contested, weak, missing, not_applicable, not_developed` |
| `_VALID_AUTHORITY_TYPES` | 140 | `jurisprudence, doctrine, comparative, statute` |
| `_VALID_CANDIDATE_CACHE_STATUS` | 141 | `not_in_bundle, pending_fetch` |
| `_VALID_CLOCK_CONFIDENCE` | 142 | `verified, estimated_from_audio_offset, unknown` |
| `_APPLICABILITY_ALIASES` | 145 | `primary→direct`; `primary_criminal, primary_civil, criminal_reporting, supporting_analogical, analogical → supporting` |
| `_LEGACY_CODE_ALIASES` | 236 | `(CL,CP)→CPCL`; `(BR,CP)→CPB`; `(CL,CPR)→CONST`; `(BR,ABEAR)→ABEAR_COC`; `(CL,LEY16752)→L16752`; `(CL,LEY20285)→L20285`; `(CL,LEY19880)→None` (not in corpus); `(BR,CF)→CONST`; `(BR,LEI9784)→L9784`; `(INT,BR-CL)→BRCL` |
| `_MIN_TEXT_MATCH_LEN` | 354 | `12` — a needle shorter than this can never *choose* an anchor |
| `_TEXT_DECISIVE` | 404 | `0.90` |
| `_DELTA_MIN_SAMPLES` / `_DELTA_MIN_MAGNITUDE` / `_DELTA_TOLERANCE` / `_DELTA_MIN_AGREEMENT` | 407–410 | `3` / `30.0` / `3.0` / `0.6` |
| `_INFORMATIONAL_MARKERS` | 866 | warnings `main` prints but does not count as problems |
| `_REPEATED_WARNING_MARKERS` | 870 | 4 `(marker, label)` pairs used to collapse repeated warnings per bundle |

### 2.2 Classes

- **`FrameworkResolver(law_root, preferred_language="EN")`** — 259. Reads
  `<law_root>/_mapping/law_registry.json`; builds `_by_code[code] → [rel files]` from each entry's
  `in_qdrant_eli + alias_eli` (ELI split on `.`, `parts[1]` is the code). `resolve(code, jurisdiction)`
  applies `_LEGACY_CODE_ALIASES` then `_pick`, ranking candidates by `(jurisdiction match, preferred
  language in path parts, rel path)`. **The code→file map is derived from the registry and never
  mirrored in code** — there is nothing to keep in sync when the corpus changes.

### 2.3 Functions

| Function | Line | What it does / why the guard exists |
| --- | --- | --- |
| `_norm_text` | 155 | NFKD → ASCII → lower → punctuation to spaces → collapse whitespace. The comparison basis for re-anchoring, so accents and dashes do not defeat a match |
| `parse_args` | 167 | positional `violation*` (ids or `<VID>.json` paths); `--source`, `--all`, `--jurisdiction` (`CL`), `--transcript-dir`, `--law-root`, `--output`, `--allow-weak-anchors`, `--speaker-index`, `--inputs-only` |
| `build_transcript_index` | 321 | globs `*.json`; each doc must be a `dict` with a `segments` list; matches `audio_id` against `_AUDIO_ID_RULES` → `{token: {"doc", "path"}}` |
| `_nearest_by_offset` | 342 | nearest segment to an audio offset |
| `_best_by_text` | 357 | SequenceMatcher over every segment; sorts by `(-score, index)` so ties resolve to the **earlier** index |
| `_best_in_window` | 384 | same, restricted to `center ± window` (used to *snap* a delta guess to nearby text) |
| `estimate_clip_offset_delta` | 413 | per-source median of `segment.start − audio_offset_start` over decisive text matches; needs ≥3 samples, \|median\| ≥ 30 s, ≥60 % agreement within 3 s |
| `reanchor_segment` | 450 | the core. Returns `{transcript_id, index, offset_start, offset_end, method, confidence, ratio, note}`. Ladder: `text` (≥0.90 → high) → `text-weak` (≥0.65 and ≥0.10 ahead of runner-up → medium) → `clip-delta±X.Xs` (→ medium) → `offset` (→ low) → `text-only` (→ low). Upgrades to `high` when the text index agrees with the delta/offset index; records `offset would pick seg-N (drift X.XXs)` when they disagree |
| `flatten_wikilinks` | 527 | recursive; dicts probe `name, ref, id, source, value`; strips `[[…]]` |
| `_as_float` / `_coerce_enum` | 547 / 558 | tolerant coercion; unknown enum values fall back with a warning rather than poisoning the document |
| `build_contract` | 568 | builds `contract.json`; returns `(contract, warnings)` |
| `build_segments_manifest` | 759 | re-anchors every `full_segments` entry; returns `(manifest, warnings)` |
| `_summarise_warnings` | 847 | collapses repeated warnings for the CLI output |
| `_candidate_record` | 880 | normalizes a vault candidate article |
| `_rewrite_prefix` | 899 | element-id prefix canonicalization. **Only fires when `old_prefix` is followed by a literal `.`**, so `Art.193` does not rewrite `Art.1930…` |
| `build_violation_document` | 912 | translates vault layers 1–5 into the model shapes; sets `"confidence": None` at 1331 |
| `_provenance_entries` | 1339 | normalizes the vault audit trail into `models.ProvenanceEntry`. `layer` must be `int` 1–5 or it becomes `None` with the original kept as a `[vault layer=N]` note prefix (51 corpus entries use `layer: 0` = whole-document rebuild). Timestamps are **validated** with `datetime.fromisoformat` but **stored as the original string**; a bad entry is skipped rather than poisoning the document (which would force the lossy legacy path) |
| `_validate_document` | 1394 | runs `Violation.model_validate`; returns a message instead of hiding the error |
| `_framework_bundle_name` | 1410 | returns `f"{code}.md"`. **Reason:** `refine_batch_core._discover_frameworks` keys readers by `md.stem.split("_")[0].upper()`, so keeping the corpus filename (`CodigoPenal.md`) would make V03/V04 miss the reader; naming the link after the code makes the derived key *equal* the looked-up key. A code containing `_` cannot round-trip (first token wins) and `stage_bundle` warns |
| `_ensure_symlink` | 1427 | replaces a stale link, refuses to overwrite a non-symlink, creates the parent, links relatively |
| `stage_bundle` | 1441 | symlinks `Transcripts/`, `speaker_index.json`, `Legal framework/`; calls `build_violation_document`; validates (1499); on failure writes `<VID>.json.invalid` (1505), **unlinks any stale `<VID>.json`** (1509–1511), and raises `ValueError` (1512); on success writes `<VID>.json` (1517), then rewrites `contract.json` (1522) if `_reconcile_contract_confidence` changed it |
| `_reconcile_contract_confidence` | 1529 | if the vault's **dict-shaped** confidence snapshot is not reproduced by `derive_confidence` on the new document, move it to `contract["_vault_confidence"]` and **drop** `confidence` — otherwise V08 fails on a value no faithful translation can clear |
| `load_violation` | 1565 | reads JSON, rejects any non-vault document, tags `doc["__source_path__"]`. A doc with `segments` but no `full_segments` is rejected **by name**: with a `violation_id` it is reported as a schema-3.0 *bundle* document, without one as a *transcript* |
| `convert_one` | 1578 | one vault file → one bundle dir; writes contract + manifest; stages when asked; writes `conversion_warnings.json` |
| `find_violation_path` | 1624 | `<source>/<VID>.json` |
| `_vault_confidence_value` | 1630 | `-1.0` when absent/unreadable |
| `_revision_sort_key` | 1642 | `(-confidence, len(name), name)` |
| `_prefer_authoritative_revisions` | 1647 | one authoritative revision per declared `violation_id`. `convert_one` keys the bundle dir off the **declared** id, so two files declaring the same id write the same `build/<VID>`. Byte-identical copies are dropped by sha256, highest vault confidence wins, and every discarded file is named on **stderr** (the real case: `BR-001` is declared by three files) |
| `_resolve_inputs` | 1713 | positional ids via `find_violation_path`, `.json` paths used directly, `--all` globs, dedupe by `path.resolve()`, then `_prefer_authoritative_revisions` |
| `main` | 1744 | exits 1 if no violations, if `--source` is not a directory, or if the transcript index is empty (**segment ids cannot be re-anchored**); warns on stderr when the registry is missing; prints `{"converted", "warnings", "results"}` with per-result `{violation_id, ok, bundle, segments, sources, warnings}`; returns 0 iff something converted |
| `if __name__ == "__main__"` | 1815 | present — the module is importable and **is** imported by tests |

---

## 3. Structure expected

### 3.1 Input — the vault document (`<source>/<VID>.json`, schema 4.0)

> With `DEFAULT_SOURCE = data/violations` (§1.1) the files at that path are currently schema-3.0
> *bundle* documents, **not** this shape. Everything below is what `load_violation` (1565)
> accepts; see §1.1 and §5 finding 6.

```jsonc
{
  "violation_id": "CL-005", "title": "...", "severity": "CRITICAL",
  "schema_version": "4.0", "jurisdiction": "CL", "category": "...",
  "case": {"id": "I-002", "name": "I-002-Chile-Santiago"},
  "incident": {"date","location","flight","operator","clock_time_estimate","clock_time_confidence"},
  "incident_timestamp": "2024-07-05T11:00:00-04:00", "incident_timestamp_display": "...",
  "allegation_summary": "...",
  "legal_basis": [ { "article_id","article_name","verbatim_text","applicability",
                     "applicability_rationale"|"nexus","duty_bearer","norm_type",
                     "subsections","status","framework_code", <candidate fields> } ],
  "candidate_articles": [...], "cross_references": [...], "open_questions": [...],
  "related_violations": [...], "tags": [...],
  "full_segments": [ { "segment_id",            // legacy *render* numbering — STALE
                       "role_in_argument","audio_offset_start","verbatim_es",
                       "translation_en","transcription_notes" } ],
  "element_grids": { "<article_id>": {...} },   // dict in 4.0; list of {article_id, elements} in 3.0
  "nexus_matrix": [ {"fact_id","norm_id","element_id","nexus_type","strength","rationale_oneline"} ],
  "authorities": [ {"authority_id"|"id","type","supports"|"supports_elements",
                    "research_query","proposition_to_verify"} ],
  "provenance": [ {"timestamp","actor","operation","layer","note"} ],
  "confidence": { "value": 0.53, "components": {...}, ... }
}
```

`full_segments[].segment_id` is the load-bearing trap: `transcription` re-rendered every transcript
(header repair + speaker consolidation), so the legacy indices **now point at the wrong utterance**.
Every segment is re-anchored and the *current* index is emitted as `<transcript_id>.seg-<index>` —
the exact string `JsonTranscriptSource.source_id()` composes.

### 3.2 Output — `build/<VID>/`

#### `contract.json` — 23 keys, plus `_vault_confidence` when divergent

Verified across all 82 bundles: `schema_version` is always `"4.0"` (the *vault's* version,
copied through) while the violation beside it is always `"3.0"` — **the two are not meant to agree**.

| Key group | Keys |
| --- | --- |
| identity | `violation_id`, `violation_number`, `title`, `case{id,name}`, `jurisdiction`, `category`, `severity` |
| versioning | `schema_version` (vault's, `"4.0"`) |
| frameworks | `framework{codes[], files{code → rel path}}` |
| confidence | `confidence` (dict snapshot with `value`, `components`, `derivation_formula`, `history`) — **or absent** |
| incident | `incident{date,location,flight,operator,clock_time_estimate[,clock_time_confidence]}`, `incident_timestamp`, `incident_timestamp_display` |
| prose | `allegation_summary` |
| norms | `legal_basis{frameworks[{framework_code, framework_name, framework_file, articles[{article_id, article_name, article_text, applicability_rationale, duty_bearer, norm_type, applicability, subsections_invoked, status}]}]}`, `established_article_ids[]` |
| other layers | `candidate_articles[]`, `cross_references[]`, `open_questions[]`, `related_violations[]`, `tags[]` |
| audit | `_provenance{source, vault_operations, converted_by: "examples/vault_to_bundle.py"}` |
| conditional | `_vault_confidence` — present in the corpus union but **not** in every file; written only by `_reconcile_contract_confidence` |

#### `segments_manifest.json` — 7 keys

```jsonc
{ "schema_version": "4.0",           // copied from the *vault*, not the bundle
  "violation_id": "CL-005",
  "matched_audio_sources": ["I-002_05_NAR-07_STG_7_post_removal_investigation"],
  "total_segments_matched": 10,
  "segments": [ { "segment_id": "<transcript_id>.seg-<index>",  // canonical
                  "legacy_segment_id": "STG-7.seg-22",          // vault id — recorded NOWHERE else
                  "role_in_argument", "audio_offset_start", "audio_offset_end",
                  "verbatim_es", "translation_en", "transcription_notes" } ],
  "clip_offset_deltas": { "<source>": <float> },
  "transcript_files": { "<transcript_id>": "<filename>.json" } }
```

`transcription_notes` is appended with `reanchored from <legacy> (method=…, confidence=…, text_ratio=…)`
so the *anchor provenance* survives in the artifact.

#### `<VID>.json` — the `violation_pack.models.Violation`

16 top-level keys, verified on disk:

`violation_id`, `title`, `severity`, `schema_version: "3.0"`, `incident`,
`segments[]` (`segment_id`, `role_in_argument`, `audio_offset_start/end`, `speaker`,
`verbatim_es`, `verbatim_sha256`, `translation_en`, `transcription_notes`, `source_uri`,
`source_sha256`, `audio_uri: null`), `framework_caches[]` (`framework_code`, `framework_name`,
`cache_file`, `cache_file_sha256`, `cache_self_reported_sha256`, `articles_cached`),
`established_articles[]`, `candidate_articles[]`, `element_grids[]`, `nexus_matrix[]`,
`authorities[]`, `confidence`, `open_questions[]`, `cross_references[]`, `provenance[]`.

**`confidence` is written as `null` (line 1331) — deliberately.** The vault's snapshot is a
*pre-conversion* number; `refine_batch_core.attach_confidence` recomputes it from `element_grids`
and `validation.v08_contract_consistency` treats a dict-shaped confidence as a *live assertion*.
All 82 live bundles now carry a non-null `confidence` because the pipeline has since run; the
converter's own output is `null`.

Element ids are rewritten at write time (`_rewrite_prefix`) so the bundle carries **one**
spelling — `CL.CHIPENCOD.Art.193…`, not `CL.CHIPENCOD.T4.C3.Art.193…` — in both `element_grids[]`
and the `element_id`/`norm_id` fields of `nexus_matrix[]` (a nexus row left on the old prefix
would dangle after the grid was rewritten).

#### `conversion_warnings.json` — `list[str]`

Plain array of warning strings, e.g.

```
"STG-22.seg-0 -> I-002_12_NAR-15_STG_22_DGAC_office.seg-0: low-confidence anchor (offset+offset); rerun with --allow-weak-anchors to accept"
```

Empty (`[]`) for a clean bundle. Corpus sizes: `BR-013` 108, `BR-001` 101, `INT-019` 85, … and
`CL-005` `[]`. **This is the audit trail** for everything the translation dropped or could not
anchor faithfully.

#### Symlinks and the failure artifact

| Entry | Shape |
| --- | --- |
| `Transcripts/<file>.json` | relative symlink into `data/transcripts/json/` |
| `Legal framework/<CODE>.md` | relative symlink into `data/law/…`, **named after the code**, not the corpus filename |
| `speaker_index.json` | relative symlink, only when one was found |
| `<VID>.json.invalid` | written *instead of* `<VID>.json` when validation fails; the run then raises and the stale `<VID>.json` is unlinked |

---

## 4. Who and what depends on them

### `contract.json`

| Dependent | What it reads | Location |
| --- | --- | --- |
| `violation_pack/refine_batch_core._process_one` | whole file → `project_contract` before `run_pipeline`, so V08/V17 judge the reconciled state | 531, 614 |
| `violation_pack/pack.project_contract` | splits keys into `CONTRACT_PROJECTED_KEYS` (12, overwritten from the violation) and `CONTRACT_VAULT_ONLY_KEYS` (11, left alone) — **a key in neither set fails `tests/test_contract_projection.py`** | 113, 143, 186 |
| `violation_pack/pack.reconcile_contract` | rewrites it from the violation; called by `_process_one` and by `write_violation_json_tool` | 312 |
| `examples/reconcile_contracts.py` | bulk re-projection; its docstring records that the file "is written once by `examples/vault_to_bundle.py`" | 4 |
| `violation_pack/ui_server.BUNDLE_ARTIFACTS` | serves it as the `contract` artifact | 302–308 |
| `examples/validate_preflight.check_source_data` | asserts it exists | 74–81 |
| `validation.v08_contract_consistency` | compares `confidence` against the bundle; **only a bare scalar is downgraded** to legacy — which is why the converter moves a divergent snapshot to `_vault_confidence` | — |
| `validation.v17_cross_view_consistency` | `open_questions` / `cross_references` must agree with the contract | — |
| `tests/test_contract_projection.py` | reads *every* `build/*/contract.json` for the classification completeness test | 776, 794 |
| all 82 corpus files | carry `_provenance.converted_by = "examples/vault_to_bundle.py"` — the provenance marker of this producer | — |

### `segments_manifest.json`

| Dependent | What it reads | Location |
| --- | --- | --- |
| `violation_pack/segment_sync.sync_segment_artifacts` | **the writer.** Rebuilds rows strictly from `violation["segments"]`; **carries `legacy_segment_id` across from the manifest on disk, never re-derives it**; preserves `clip_offset_deltas` and `transcript_files` | 67, 154–155, 228–237 |
| `segment_sync` safety valve | `_legacy_id_collision` **refuses to write** when the violation holds the vault's legacy ids and none of the converter's — the fingerprint of a bundle that never came from this converter. `tests/test_segment_sync.py:481` asserts the warning names `vault_to_bundle` | 200 |
| `violation_pack/mcp_server.write_violation_json_tool` | the S11 write gate; rebuilds the manifest and each `Transcripts/<id>.json` subset | 384–409 |
| `violation_pack/mcp_server` docs | "the composed segment id convention both `segments_manifest.json` and the bundle's violation JSON use" | 87 |
| `violation_pack/ui_server.BUNDLE_ARTIFACTS` | serves it as the `manifest` artifact (`artifacts_present.manifest`) | 305 |
| `examples/validate_preflight.check_source_data` | asserts it exists | 74–81 |
| `examples/validate_preflight.check_bundle_segments` | **wants the canonical id sets to be *equal***; also reads `legacy_segment_id` to name the drift | 87–140 |
| `examples/validate_preflight.check_transcripts` | reads `transcript_files` and checks every `seg-N` is present in the named file; its failure text tells the user to re-run `examples/vault_to_bundle.py` | 147–192 |
| `ui_structural_skeleton` S2 | parses it into a dedicated block; `verbatim_es` **drops accents** the violation keeps, so joins must be on `segment_id` only; a bundle with no manifest is not an error — fall back to the violation's own segments | §S2, line 420 ff. |
| `python violation_pack/segment_sync.py` docstring | records that **nothing rewrote the manifest until this module existed**, and that every segment added in S2 landed in the violation alone | 1–20 |
| `tests/test_segment_sync.py` | the converter is **deliberately out of scope**: "the converter is what *establishes* `segments_manifest.json`" | 567 |
| `tests/test_ui_server.py` | joins on `segment_id` against the manifest; asserts the S2 panel names the artifact | 2302, 2362, 2459, 2690 |

### `<VID>.json`

| Dependent | What it reads | Location |
| --- | --- | --- |
| `refine_batch_core._load_violation` | `Violation.model_validate_json` first; **on any exception silently falls back to `_normalize`**, which reads only `segments` + `legal_basis` and drops `element_grids`, `nexus_matrix`, `authorities`, `confidence`. This is exactly the loss the converter's `_validate_document` + `.invalid` + `raise` path prevents | 462 |
| `refine_batch_core._find_violation_json` | `<dirname>.json` first; else the single `*.json` that is not `contract.json` and not `*.bak` | 91 |
| `refine_batch_core.attach_confidence` | recomputes and installs `confidence` | 531 region |
| `pack.write_violation_json` / `mcp_server.write_violation_json_tool` | the write gate; serializes with `exclude_none=False` | 98 / 385 |
| `ui_server.BUNDLE_ARTIFACTS` | serves it as the `violation` artifact | 302 |
| `_find_violation_json` ↔ `.bak` | `_load_violation` reads `.bak` **only** when the live file is unreadable or not JSON — a recovery snapshot, never a second source of truth | 462 |

### `conversion_warnings.json`

| Dependent | What it reads | Location |
| --- | --- | --- |
| `ui_server.BUNDLE_ARTIFACTS` | serves it as the `warnings` artifact; a malformed or missing artifact degrades to an empty panel, never a 500 | 306 |
| `pack.build_manifest` | hashes and lists it in `MANIFEST.txt` (every bundle's `MANIFEST.txt` names it) | 349 |
| `examples/run_one.sh` / `run_one_local.sh` | print its path in the run summary | 259 / 258 |

`conversion_warnings.json` is **written by this module and by nothing else** — no downstream
consumer regenerates it, so it is a frozen record of the conversion run.

### The symlinked source trees

| Entry | Dependent | Constraint |
| --- | --- | --- |
| `Transcripts/*.json` | `refine_batch_core._discover_transcripts` (133) → `sources_json.JsonTranscriptSource`, keyed by `transcript_id`, line up with `reviewed_transcripts` | a doc without a top-level `segments` list raises `JsonTranscriptSchemaError` and is skipped |
| `speaker_index.json` | `refine_batch_core._speaker_index_path` (181) → `JsonTranscriptSource._load_speaker_index` (217): exact `(transcript_id, segment_index)` lookup | file symlink to the corpus |
| `Legal framework/<CODE>.md` | `refine_batch_core._discover_frameworks` (189) keyed by `md.stem.split("_")[0].upper()`, then `_framework_for` (204) | **this is why `_framework_bundle_name` names the link after the code** — a code containing `_` cannot round-trip and is warned about |
| `Legal framework/` containment | `ui_server` `GET /api/framework-article` accepts exactly `build/<VID>/Legal framework/<name>.md` | containment is checked on **raw path parts**, never on a resolved path, because every one of these is a symlink |

### Shell / CLI drivers

| File | Line | Role |
| --- | --- | --- |
| `examples/run_one.sh` | 158–178 | step 1/3; then asserts `contract.json`, `segments_manifest.json`, `<VID>.json` exist before refining |
| `examples/run_one_local.sh` | 158–258 | same, local variant |
| `examples/remediate_v01.sh` | 18 | `"$VENV_PY" examples/vault_to_bundle.py "$v" --jurisdiction CL` — the documented V01 remedy |
| `examples/triage_buckets.py` | 277 | prints the same command as the suggested fix |
| `examples/validate_preflight.py` | 14, 192 | tells the user to run this module first / to regenerate the manifest |
| `examples/refine_batch.py` | — | `run(root)` — `root` is **the `build/` directory itself**, not the project root |

---

## 5. Findings worth acting on

1. **Line-count drift.** `project_actual_report_and_proposal_improvements.md:318` says 1605 lines;
   the file is 1815. Any estimate built on that table is ~13 % low.

2. **Stale comment in the drivers.** `examples/run_one.sh:185-187` and
   `examples/run_one_local.sh:184-186` say
   *"`refine_batch._load_violation` prefers `<id>.json.bak` over the live JSON when present"* and
   therefore `rm -f "${BUNDLE_DIR}/${VID}.json.bak"`. That preference was **reversed**:
   `_load_violation` (462) now reads the live JSON first and consults `.bak` only when the live
   file cannot be read. The `rm -f` is harmless but the stated reason is now wrong, and the comment
   will mislead the next reader into thinking the old bug is still live.

3. **Three version numbers in one bundle, on purpose.** `contract.json` and
   `segments_manifest.json` carry `"4.0"` (the *vault document's* version, copied through);
   `<VID>.json` carries `"3.0"` (the bundle schema). `pack.CONTRACT_VAULT_ONLY_KEYS` documents
   this for the contract; the manifest is not covered by that note, so the manifest's `"4.0"`
   reads like a bug and is not.

4. **`legacy_segment_id` exists in exactly one artifact.** Nothing in the vault, the violation JSON
   or the transcript carries the pre-re-anchor id. It is written here and thereafter only *carried*
   by `segment_sync`. Losing the manifest loses the only mapping back to the vault's numbering.

5. **The converter's `confidence: None` is not what you will observe.** All 82 live bundles have a
   non-null derived confidence, because `attach_confidence` has since rewritten the file. Do not
   read the corpus to learn what the converter writes; use line 1331.

6. **`DEFAULT_SOURCE` (93) was seeded with files the converter could not read — now fixed.**
   `data/violations` was first populated with 81 schema-3.0 *bundle* copies from `build/`, while
   `load_violation` (1565) demands a schema-4.0 *vault* document; **every** file was rejected, so
   the module default was unusable. **Re-seeded 2026-09-17 from the vault set**
   (`olivia/…/_json/EN`) by the second option below; `data/violations` now holds **80 canonical
   schema-4.0 vault documents**. The vault directory holds **84** files declaring **81** distinct
   `violation_id`s — exactly the 81 bundles. Those files are the schema-4.0 shape §3.1 documents
   (verified: `CL-013.json` is `4.0`, has `full_segments`, a **dict** `element_grids`,
   `legal_basis`, 38 top-level keys). The re-seed filters to `full_segments`-bearing documents and
   arbitrates duplicates among those only, so it lands **80**, not 81 (two exclusions, below).
   Verified after writing: 80 files, **0** byte-mismatches against the vault, no name/stem
   mismatches. Two measured caveats, both narrower than they first look:
   - **Four filenames do not match their declared id** — `1-CL-005.json`, `BR-030.json`,
     `BR-030-updated.json` and `CL-042.json` each declare an id other than their own stem
     (`CL-005`, `CL-030`, `BR-001`, `CL-f7dd941e`). Three ids are therefore declared twice
     (`CL-005`, `BR-001`, `CL-030`); `_prefer_authoritative_revisions` (1647) resolves those and
     names the discarded file on stderr, so a straight copy is **safe**. But because
     `find_violation_path` (1624) matches on the **filename**, it is also *deceivable*: measured,
     `find_violation_path('BR-030', <vault>)` returns `BR-030.json` — a file declaring `CL-030`.
     No vault file declares `BR-030` at all, so a by-id request for it silently converts
     `CL-030` instead of failing. **Do not "fix" `1-CL-005.json` by renaming it to `CL-005.json`**
     — that name already exists and the rename would clobber it. (An earlier revision of this
     finding said the vault names CL files `1-CL-005.json` so a straight copy left `CL-005`
     unresolvable. **That was wrong in both directions** and is retracted: `CL-005.json` exists
     alongside it, and `CL-005` resolves fine.)
   - **Two vault files are not vault documents at all, and both are excluded by the re-seed:**
     - `BR-030.json` is a **schema-3.0 bundle document leaked into the vault** (16 keys,
       `segments`, no `full_segments`). It declares `CL-030` at vault confidence **0.48**, so the
       confidence-only arbitration of `_prefer_authoritative_revisions` (1647) picks it **over the
       real 4.0 `CL-030.json` (0.38)** — and `load_violation` (1565) then rejects it outright
       (`looks like a bundle document (schema 3.0)`, converted 0). This is a live demonstration
       that the arbitration is **confidence-only and schema-blind**; the re-seed works around it by
       pre-filtering to `full_segments`-bearing files. By-id `CL-030` now yields the correct 4.0
       document (5 segments).
     - `CL-042.json` declares `CL-f7dd941e` and has **no `schema_version`** (36 keys, a third
       shape). It converts "successfully" to **0 segments** — a silently degenerate evidence
       layer. Excluded, so **`CL-f7dd941e` has no vault-shaped source**: `find_violation_path`
       (1624) cannot resolve it by id, and the default-source acceptance test fails loudly for it
       (`CL-f7dd941e -> NO JSON`). Its tracked bundle `build/CL-f7dd941e/CL-f7dd941e.json` is
       byte-identical (sha256 `4979ffe6…`) to the copy that was removed from `data/violations`, so
       nothing in `build/` was lost. `--all` still reaches the other 80.
     Conversely `build/CL-0301` exists in **no** vault file, so a re-seed leaves it behind; or
   - **give the converter an explicit bundle-input path.** This is a new mapping, not a relaxed
     guard: a bundle's `legal_basis` / `verbatim_text` / `applicability` live in `contract.json`,
     not in `<VID>.json`, and the full-segment corpus is absent entirely.

   Two *vault* roots still coexist — `$VAULT_SOURCE` (`run_one.sh:153` →
   `/awareness/shared/violations`, **absent on this machine**) and `data/violations` — and
   `run_one.sh` always passes `--source`, so the module default is reached only when the script is
   called by hand. `run_one_local.sh:157` already defaults to `data/violations`, so the local
   wrapper needs no change.

   **Before the re-seed**, measured on `CL-013`: the bare command failed —
   `vault_to_bundle.py CL-013 --output /tmp/x` → `"converted": 0`, exit 1, error
   `data/violations/CL-013.json: looks like a bundle document (schema 3.0)`. With the vault named
   explicitly it succeeded. **After the re-seed the bare command works** — acceptance test over
   five ids: `CL-013` 5 segments, `CL-030` 5, `BR-001` 45, `CL-005` 10, `CL-f7dd941e` fails
   (no source, above). Caveat: `DEFAULT_SOURCE` is **relative**, so the default resolves only with
   cwd = repo root. **This unbreaks the documented repair cycle**
   (`rm -rf build/<VID>` → `vault_to_bundle.py <VID>` → `refine_batch.py --input build --only <VID>`,
   the V01 remedy in `remediate_v01.sh:18` and `triage_buckets.py:277`) — but see finding 7: doing
   that to `CL-013` **fails validation**.

   > **Interpreter trap.** The cycle must run under `.venv/bin/python`. Bare `python3` is Homebrew's
   > 3.14 and has **no `pydantic`** (`ModuleNotFoundError: No module named 'pydantic'`), and
   > `python3 examples/refine_batch.py` additionally fails with `No module named 'violation_pack'`
   > because a script run by path puts `examples/` — not the cwd — on `sys.path[0]`;
   > `vault_to_bundle.py` survives that only because it inserts `_REPO_ROOT` itself.

7. **Rebuilding a bundle from the vault can REGRESS it: the element-grid prefix rewrite emits
   duplicate `article_id`s.** Re-running the now-working repair cycle on `CL-013`
   (`vault_to_bundle.py CL-013` → `scripts/refresh_bundle_artifacts.py CL-013`) produces a bundle
   that **fails validation**, so the tracked `build/CL-013` was reverted to HEAD and the
   regeneration is **not** committed.

   **Mechanism (`examples/vault_to_bundle.py`, ~1137).** The vault document for `CL-013` holds
   **two** element-grid keys for the same article: `CL.CPCL.C1.Art.412` (8 elements, *including*
   `modalidad_tipica`) and `CL.CPCL.T2.P6.Art.412` (7 elements, *without* it — `T2.P6` is an
   unrelated, mis-prefixed key). The converter canonicalizes the prefix and then **appends**:

   ```python
   prefix_rewrites[article_id_in] = canonical
   article_id = canonical
   ```

   Two grids therefore land in `element_grids` (a **list** in the bundle) carrying the **same**
   `article_id`, `CL.CPCL.C1.Art.412` — 6 entries, two of them the same article. The nexus row
   `…seg-11 -> CL.CPCL.C1.Art.412/…elem.modalidad_tipica` resolves against whichever entry comes
   first (the 7-element one), which lacks that element. The HEAD bundle escaped this only because
   it keeps the two prefixes **distinct** (unambiguous, non-canonical) — so **the tracked bundle is
   not reproducible from the current vault + converter.**

   **Measured verdict** (`checks.json` before → after; 18 checks, `refresh_bundle_artifacts.py`):

   | | before (stored, HEAD) | after (regenerated) |
   |---|---|---|
   | checks run | **11** | **18** |
   | pass / warn / fail | 8 / 3 / **0** | 12 / 4 / **2** |
   | notable | — | V03 warn→**pass**; **V10** pass→warn; **V11** pass→**FAIL**; V13/V21 new |

   Two things must be said plainly before calling 8/3/0 better than 12/4/2:
   - The stored report is a **stale snapshot (`ran_at` 2026-09-13) over 11 of 18 checks** — V12–V17
     and V21 did not exist then, so its "0 fail" never measured the current criterion set.
   - **V10's warn is not a defect**: `refresh_bundle_artifacts.py` deliberately never calls
     `attach_confidence`, and the converter *moves* the vault snapshot (0.67) to
     `contract._vault_confidence` and *drops* it precisely "so V08 does not assert a value the
     bundle contradicts" — hence "No confidence value attached".

   **But V11 and V21 are real FAILs**, both traceable to the duplicate grid above:
   - **V11 `enrichment_integrity`**: `E_NEXUS_UNKNOWN_ELEMENT` —
     `CL.CPCL.C1.Art.412.elem.modalidad_tipica` *is not in* the `CL.CPCL.C1.Art.412` grid.
   - **V21 `element_id_closure`**: 4 issues, two of them the **same** article —
     `CL.CPCL.C1.Art.412: template requires element(s) ['delito_perseguible_de_oficio',
     'falsedad_imputacion', 'imputacion_delito_determinado'] not present in the grid`, **listed
     twice**. (V21 also flags `CL.CHIPENCOD.T4.C6.Art.211` and `CL.LPDC.Art.23` — those are a
     template-vs-grid **naming** divergence, present in the vault too, and were merely *unmeasured*
     before.)

   **It is systemic, not a `CL-013` one-off.** Converting all 80 seeded documents gives 289
   warnings and **7 bundles with duplicate `article_id`s**:

   ```
   BR-001 {'BR.CDC.T3.Art.6.IV': 2, 'BR.CDC.T5.C4.Art.39.II': 2}
   BR-005 {'BR.CDC.T5.C4.Art.39': 5}
   BR-006 {'BR.CDC.T2.Art.4': 3, 'BR.CDC.T5.C5.Art.42': 2}
   BR-010 {'BR.CDC.T5.C4.Art.39': 3}
   CL-013 {'CL.CPCL.C1.Art.412': 2}
   CL-017 {'CL.CPCL.T2.P6.Art.412': 2}
   CL-023 {'CL.CPCL.C1.Art.412': 2}
   ```

   **Two candidate fixes; pick one deliberately:**
   - **In the converter (preferred).** When two grids canonicalize to the *same* `article_id`,
     **merge** their elements (by `element_id`, keeping the non-`not_developed` status) instead of
     appending a second grid. This is a converter change and would make all 7 documents coherent;
     it needs its own tests (a vault doc with two colliding grid keys is the fixture).
   - **In the vault (narrow).** Delete the mis-prefixed duplicate key
     (`CL.CPCL.T2.P6.Art.412`) from the source document. Fixes only where the duplicate is an
     unrelated key — it does **not** help `BR-005`/`BR-010`, where the same article legitimately
     appears 3–5 times and merging is the correct semantics.

   Until one is applied, **do not "repair" an affected bundle via the documented cycle** — it will
   replace a coherent bundle with a failing one. Revert with
   `git -C <repo-root> checkout -- violation-refiner/build/<VID>`.

   ### 7a. Resolved — the converter merges colliding grids (2026-09-17)

   **Converter option applied.** `examples/vault_to_bundle.py` gained:

   - **`_merge_grid_elements(target, incoming) -> (added, upgraded)`** (next to `_rewrite_prefix`).
     Folds a second grid's elements into the first **in place**: a new `element_id` is appended; an
     existing one is upgraded **only** when its `proof_status` is `not_developed` (two genuine
     differing statuses keep the first-seen — the canonical grid's — opinion);
     `proof_evidence_segments` is **unioned** (a duplicated row is what V06 flags); blank
     `label`/`doctrinal_basis`/`argument_es` are filled from the other copy and real ones kept;
     `weaknesses`/`open_questions` are unioned.
   - **`grid_by_article: dict[str, dict]`**, keyed by `article_id`, so the emit step can tell
     "first grid for this article" from "second grid for this article".
   - An emit-site **merge branch** that calls the helper instead of appending, and records
     `element grid <old>: merged into the existing <new> grid (+N element(s), M status upgrade(s))
     — two grids canonicalized to the same article_id`.

   **Same defect class at a second site — `open_questions[].blocks_element`.** The grid pass and the
   nexus pass both rewrite a canonicalized article prefix; the `blocks_element` reference did not,
   so it kept naming an `element_id` no grid carries. V11 reported it as
   `W_OQ_BLOCKS_UNKNOWN@OQ-CL013-CREW-NAME: blocks_element 'CL.CPCL.T2.P6.Art.412.elem.sujeto_activo'
   is not a known element_id`. Fixed: the `open_questions` projection now applies `_rewrite_prefix`
   through `prefix_rewrites`, the same loop the nexus pass uses.

   **Verified verdict** (`scripts/refresh_bundle_artifacts.py CL-013`, 18 checks):

   | report | pass / warn / fail | V11 | V21 |
   |---|---|---|---|
   | HEAD `Validation/checks.json` (stamped 2026-09-13) | 8 / 3 / **0** over **11** | pass (never ran V21) | not run |
   | regenerated **before** the fix | 12 / 4 / **2** | **FAIL** `E_NEXUS_UNKNOWN_ELEMENT` | **FAIL**, 4 issues (one article listed **twice**) |
   | regenerated **after** the fix | **13 / 4 / 1** | **pass** | FAIL, **3** issues (duplicate gone) |

   `V11`'s `E_NEXUS_UNKNOWN_ELEMENT` is gone and its two `W_OQ_BLOCKS_UNKNOWN` warnings cleared with
   the `blocks_element` fix. `V21`'s duplicate listing is gone; its 3 remaining issues are the
   **template-vs-vault naming divergence** below, which is older than this defect.

   **The remaining V21 FAIL is a different, pre-existing problem** — the element *template* and the
   vault *grid* spell the same element differently:

   | article | template requires | grid carries |
   |---|---|---|
   | `CL.CPCL.C1.Art.412` | `delito_perseguible_de_oficio`, `falsedad_imputacion`, `imputacion_delito_determinado` | `perseguibilidad_de_oficio`, `falsedad_de_la_imputacion`, `imputacion_de_delito_determinado` |
   | `CL.CHIPENCOD.T4.C6.Art.211` | `elemento_subjetivo_falsedad`, `hecha_ante_autoridad`, `imputacion_falsa_crimen` | — |
   | `CL.LPDC.Art.23` | `falla_calidad…` | — |

   This is present in the vault, and was merely **unmeasured** before (V21 did not exist in the
   2026-09-13 run). Closing it means reconciling an alias table, the template, or the vault — a
   content decision, not a converter bug. `V13`'s 2 warnings and `V06`'s 4 are likewise pre-existing
   and unchanged by the fix.

   **Tests.** `tests/test_vault_grid_merge.py` — 4 unit tests on `_merge_grid_elements` (union
   without duplicating ids / placeholder-only status upgrade / evidence union without duplicate rows
   / blank text filled, real text kept) and 3 corpus tests. Proven to fail first: with the converter
   at HEAD the whole file reports **6 failed**, and
   `test_no_seeded_document_converts_to_a_duplicate_article_id` names **exactly the 7 documents
   measured above, with the same counts** — so the test reproduces the measurement rather than
   asserting a guess.

   **⚠️ The repair cycle is one-shot per bundle, and changes the corpus layout.** After
   `refresh_bundle_artifacts.py`, `Transcripts/*.json` are **no longer symlinks**: the refresh step
   runs `sync_segment_artifacts` → `segment_sync._write_json`, which unlinks a symlink *before*
   writing ("`Path.write_bytes` writes *through* a symlink, so a filtered transcript written over the
   bundle's link into the shared corpus would rewrite `data/transcripts/json/<name>.json` — for every
   bundle at once"). Two consequences:

   1. **Step 1 then fails on a re-run:** `vault_to_bundle._ensure_symlink` raises
      `… exists and is not a symlink`. Re-run requires `git checkout -- build/<VID>` first.
   2. **All 81 committed bundles track their `Transcripts/*.json` as symlinks** (430 symlink entries
      under `build/`), while `refine_batch_core._process_one` also calls `sync_segment_artifacts` —
      so the committed corpus is **converter output only**, never post-`refine_batch`. Refreshing a
      bundle therefore shows 3 `T` (type-change) entries against HEAD. The source transcripts are
      unharmed (`_write_json` replaces the link, never writes through it).

