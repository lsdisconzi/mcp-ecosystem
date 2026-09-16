# Shared Data: Source of Truth & Vendoring Contract

**Status:** authoritative for this project · **Established:** 2026-09-13
**Scope:** the law corpus and the transcript corpus, which are consumed by more than one
project in `mcp-ecosystem`.

---

## 1. The rule

> **`transcription/` is the single writer and owner of the shared corpora.
> Every other project is a read-only consumer and accesses the data through a
> relative symlink. Nothing outside `transcription/` may edit, rename, generate,
> or re-ingest these files.**

| Artifact | Owner (writer) | Consumers | Access mechanism |
|---|---|---|---|
| `transcription/data/law/` — legal framework Markdown | `transcription` | violation-refiner, others | directory symlink |
| `transcription/data/transcripts/*.json` — 27 transcripts | `transcription` | violation-refiner, others | per-file symlinks |
| `transcription/data/speaker_index.json` — segment→`SPK-…` map | `transcription` | violation-refiner | file symlink |
| `transcription/data/audio/`, `speakers/` | `transcription` | violation-refiner (not currently) | not linked |
| Qdrant `transcription_law`, `reviewed_transcripts` | `transcription` | violation-refiner — **read-only** via `violation_pack/shared_corpora.py` | API, not files (see §4) |
| Qdrant `la8159_law`, `la8159_law_bm25` | `transcription` | *(none — see §4)* | not read |
| Qdrant `transcription_transcripts` | `transcription` | *(none)* | not read — raw-audio working index, disjoint from the case corpus (§4.3) |

The canonical location therefore is, and must remain:

```
transcription/data/law/**/*.md
transcription/data/transcripts/*.json
transcription/data/speaker_index.json
```

There is a second, **non-canonical** edge, added 2026-09-13 and documented in §8:

| Artifact | Owner (writer) | Consumers | Access mechanism |
|---|---|---|---|
| `olivia/_shared/cases/la8159/02-transcripts/transcripts_rendered/I-002/*.html` — the transcript **render** | `olivia` (a sibling repo, outside `mcp-ecosystem`) | violation-refiner | directory symlink |

A render is presentation, not data. It carries role labels but no `SPK-…` ids, so it
cannot join to `reviewed_transcripts`; it exists so the S2 HTML parser has an input and
the Browse control has something to show. It was 27 committed copies until they were
found to be rewritten in place by a sibling process (§8).

---

## 2. Why single-writer

These corpora are produced by a pipeline that lives in `transcription/` (audio →
transcription → reconciliation → header repair → speaker consolidation → law/article
parsing). A **second writer is not detectable by any test** — it silently produces a
divergent copy, and the divergence only surfaces later as an unreproducible result.

This is not hypothetical. The two failure modes below both actually happened here:

- `transcription/data/transcripts-named/` was a **stale second transcript corpus**
  (an older ASR vintage with truncated utterances). It is now **removed** — see §7.
- Two legacy scripts in `transcription/scripts/` that consumed it were retired,
  because one of them (`generate_speaker_index.py`) would have **regenerated
  `speaker_index.json` from the stale vintage** and silently destroyed the
  consolidated speaker index.

**The rule is cheap to follow and expensive to break.** If you need different data,
change the input in `transcription/` and re-run the pipeline.

---

## 3. The symlink contract

Downstream projects link into `transcription/data/`, never copy.

### 3.1 Law corpus — directory symlink

From `violation-refiner/data/`:

```
law -> ../../transcription/data/law
```

### 3.2 Transcripts — one symlink per file

From `violation-refiner/data/transcripts/json/`, for each of the 27 files:

```
<name>.json -> ../../../../transcription/data/transcripts/<name>.json
```

Targets are resolved relative to the **link's own directory**, so the four `..`
levels are exactly `json → transcripts → data → violation-refiner → mcp-ecosystem`.

### 3.3 `speaker_index.json` — file symlink

From `violation-refiner/data/`:

```
speaker_index.json -> ../../transcription/data/speaker_index.json
```

This file is **not optional**. It is priority 1 of `transcription`'s own speaker
resolution: `QdrantTranscriptIndex` builds its `_spk_by_seg` map from it, so it is what
determines the `speaker_id` actually stored in `reviewed_transcripts`. Resolving
speakers any other way here produces payloads that disagree with the collection.

`JsonTranscriptSource` mirrors that precedence exactly:

1. exact `(transcript_id, segment_index)` lookup in `speaker_index.json`;
2. `segment_labels` / `role` / `speaker_label` on the document's `participants`;
3. `None`.

### 3.4 Two hard requirements

1. **Symlink targets MUST be relative.** An absolute target embeds the developer's
   checkout path, so the repository only works on one machine and at one location.
2. **The basename on both sides MUST be identical.** Consumers resolve by filename;
   a rename on one side silently produces a dangling link.

> **Fixed 2026-09-13:** five links (`I-002_{01,02,03,04,05}_*`) had been **committed
> with absolute targets** pointing at `/Users/leandrodisconzi/repos/...`. They were
> rewritten to the relative form. All 27 are now relative.

---

## 4. Qdrant collection ownership

Two different law stores exist. Do not confuse them.

| Collection | Owner | Vector | Contents | Read by violation-refiner? |
|---|---|---|---|---|
| `la8159_law` | `transcription` | 768-d (opaque, read-only) | canonical law article payloads, 1119 articles | **No** |
| `la8159_law_bm25` | `transcription` | sparse `text` (`qdrant/bm25`) | lexical BM25 over the same articles | **No** |
| `transcription_law` | `transcription` | 384-d (`all-MiniLM-L6-v2`) | repo-owned semantic law index; safe to drop/rebuild | **Yes — read-only** (§4.2) |
| `transcription_transcripts` | `transcription` | 384-d | `transcription`'s own working index over **raw audio** — 481 ad-hoc job ids, `SPEAKER_00` labels, empty `case_id`; **0** id overlap with the case corpus | **No** — out of contract, and *not* a superset (§4.3) |
| `reviewed_transcripts` | `transcription` | 384-d | curated/reviewed segments | **Yes — read-only** (§4.2) |
| `violationrefiner_v1_*` | **violation-refiner** | per embedder | `_segments`, `_articles`, `_authorities`, `_jurisprudence` | Yes (own namespace) |

**violation-refiner does not query `la8159_law`.** It reads the law corpus as
**Markdown files** through the `data/law` symlink, and writes only into its own
`QDRANT_COLLECTION_PREFIX` namespace (default `violationrefiner_v1`).

`data/law/_mapping/law_registry.json` **is generated by `transcription`**, not by this
project. Its title (`Law Corpus Registry — data/law/ ↔ Qdrant la8159_law`) describes
`transcription`'s pairing; it is a read-only reconciliation artifact here. Regenerate
it with `transcription/scripts/ingest_law_corpus.py validate --write-registry`, never
by hand.

### 4.1 Ingestion commands (run in `transcription/`, not here)

```bash
# law corpus -> la8159_law, la8159_law_bm25, transcription_law
.venv-py312/bin/python scripts/ingest_law_corpus.py ingest --target local
.venv-py312/bin/python scripts/ingest_law_corpus.py validate --write-registry

# transcripts -> transcription_transcripts / reviewed_transcripts  (no CLI; HTTP/MCP)
curl -X POST 'http://localhost:8000/api/transcripts/index-all'
```

There is **no law-ingestion and no transcript-ingestion script in violation-refiner.**
Its `FrameworkIngester` parses a *single* Markdown framework file into its own
`_articles` collection; it does not walk `data/law/` and does not touch `la8159_law`.

`TranscriptIngester` can read a canonical `segments[]` document
(`JsonTranscriptSource`) as well as a legacy OliviaLegal `content[]` export, but it
writes only to `<prefix>_segments` — a private working collection. It never writes a
shared collection.

### 4.2 Reading the shared collections — `violation_pack/shared_corpora.py`

The executable form of the §4 table. It is **read-only by construction**: there is no
`upsert` method, and the module exposes no collection-creation call.

```python
from violation_pack.shared_corpora import SharedCorpusReader, MiniLmEmbedder

reader = SharedCorpusReader()                      # QDRANT_URL / QDRANT_API_KEY from env

# --- exact reads: no embedder required, no cross-embedder risk ----------------
reader.law_article("CL.CHIPENCOD.T4.C3.Art.193")
reader.iter_law_articles(framework_code="CHIPENCOD", language="en")
reader.reviewed_segment("I-002_01_NAR-01_STG_1_pre_boarding", 0)
reader.reviewed_segments("I-002_01_NAR-01_STG_1_pre_boarding")

# --- contract / drift check -------------------------------------------------
reader.verify_contract()                           # {"ok": bool, "collections": [...]}

# --- semantic search: needs a matching 384-d embedder ------------------------
reader = SharedCorpusReader(embedder=MiniLmEmbedder())
reader.search_law("detención arbitraria", top_k=10)
reader.search_reviewed_segments("boarding gate confrontation", top_k=10,
                                case_id="I-002")   # payload filters are keyword args
```

The result-count argument is **``top_k``, not ``limit``**. Any keyword argument
other than ``top_k`` is treated as a payload filter, so a misspelled one used to build a
filter on a non-existent key and quietly return zero rows. Unknown filter keys now
raise ``SharedCorpusError`` and list the valid ones.

**Point ids are derivable, so exact reads never need a vector search** — which is what
makes read-only access cheap and deterministic:

| Collection | Point id |
|---|---|
| `transcription_law` | `uuid5(NAMESPACE_DNS, original_id)` — `law_point_id()` |
| `reviewed_transcripts` | `uuid.UUID(md5(f"{transcript_id}:{segment_index}"))` — `transcript_point_id()` |

Both live in the payload too (`original_id`, and `transcript_id` + `segment_index`), so
a payload filter reaches the same point without knowing a uuid.

> **The dashed-uuid trap.** `transcript_point_id()` returns the **dashed** form
> (`uuid.UUID(...)`), matching `str(point.id)`. Comparing it against the bare
> `hashlib.md5(...).hexdigest()` matches **nothing, silently**. This false negative
> was hit once during verification; it is now covered by a test.

> **The embedder trap.** Both collections are **384-d** (`all-MiniLM-L6-v2`).
> violation-refiner's own default embedder is **Voyage `voyage-3-large`, 1024-d**.
> Querying a 384-d collection with a 1024-d query vector returns meaningless
> neighbours and raises no error. The reader therefore guards every semantic-search
> path and raises `EmbedderMismatch` when the embedder is `None` or has a different
> `dim`. Use `MiniLmEmbedder` (which lazily imports `sentence_transformers`).

### 4.3 Known collection gaps

**Resolved** (re-indexed, re-verified 2026-09-13):

- ~~`I-002_07_NAR-06_STG_13_post_PDI_corridor` is entirely absent from
  `reviewed_transcripts`~~ — it was missing (195 canonical reviewed segments, 0
  indexed points; the whole 2968 point count). After re-ingesting in
  `transcription/`, it holds **195** points and the collection is **3163** across
  27 transcripts. `2968 + 195 = 3163`, and all 27 transcripts now match their JSON
  segment counts exactly. The gap is closed.

**Open — a corrected claim:**

- **`transcription_transcripts` (2272 points) is *not* a superset of
  `reviewed_transcripts`.** This document previously said it was, and that was
  wrong. The two collections are **disjoint**: `transcription_transcripts` holds
  2272 points across **481** ad-hoc raw-audio job ids (`denoise (25)_1788032405.wav`,
  `segment_331_1787922197.wav`, `stg_7_p2_1787952500`) with `SPEAKER_00` labels and
  empty `case_id`, while the case corpus holds the 27 `I-002_*` transcripts. Their
  transcript-id sets intersect in **zero** places, so nothing here is "superseded".
  - It remains true that it **lacks `speaker_id` and `segment_id`**, and that there
    is therefore no reason for violation-refiner to read it — `reviewed_transcripts`
    is the correct and only transcript read target.
  - It should **not** be deleted: it is `transcription`'s live working index
    (`src/infrastructure/qdrant_index.py`, wired in `src/composition.py`;
    `TranscriptIndexPort` for transcript search), `_ensure_collection()` would
    recreate it empty on the next startup anyway, and its 2272 points have no
    second copy. Dropping it would destroy data and break that app's search.

---

## 5. How to add or change a shared file

1. **Add/modify the file in `transcription/data/...`.** That is the only write.
2. **Re-run the owning pipeline** in `transcription/` so derived artifacts
   (`speaker_index.json`, `_mapping/law_registry.json`) stay consistent.
3. **Re-ingest** the affected Qdrant collection(s) in `transcription/` (§4.1).
4. **Relink downstream**, if the file set changed (new basename):

   ```bash
   cd violation-refiner/data/transcripts/json
   ln -sfn ../../../../transcription/data/transcripts/<name>.json <name>.json
   ```

5. **Verify** with the checks in §6.

Steps 3–5 are mandatory on any content change: the symlink makes the *file* current
instantly, but any Qdrant index built from it remains stale until re-ingested.

---

## 6. Verification

Run these after any change to the shared data or its links.

```bash
# 1. No absolute symlink targets (must print nothing)
cd violation-refiner/data/transcripts/json
for f in *; do t=$(readlink "$f"); case "$t" in /*) echo "ABSOLUTE: $f -> $t";; esac; done

# 2. No dangling links anywhere under data/ (must print nothing)
find -L violation-refiner/data -type l

# 3. Every shared transcript resolves to the canonical file, byte for byte
cd violation-refiner/data/transcripts/json
python3 - <<'PY'
import hashlib, pathlib
here  = pathlib.Path('.')
canon = pathlib.Path('../../../../transcription/data/transcripts').resolve()
bad = [p.name for p in sorted(here.glob('*.json'))
       if hashlib.sha256(p.read_bytes()).digest()
       != hashlib.sha256((canon / p.name).read_bytes()).digest()]
print(f"checked {len(list(here.glob('*.json')))}; mismatches: {len(bad)}", bad or '')
PY
```

Expected: 27 links checked, `mismatches: 0`.

```bash
# 4. Shared-collection contract drift (owner / dim / payload keys / point ids)
#    Exit 0 = clean, 1 = drift, 2 = QDRANT_URL unset.  Needs only QDRANT_URL.
cd violation-refiner
.venv/bin/python -m violation_pack.shared_corpora

# 5. Segment ids line up with the reviewed corpus
#    (the JSON corpus is the only form whose ids join — see §8)
.venv/bin/python - <<'PY'
from violation_pack.sources_json import discover_json_transcripts
srcs = discover_json_transcripts("data/transcripts/json",
                                 speaker_index_path="data/speaker_index.json")
print("transcripts:", len(srcs))
print("segments   :", sum(s.segment_count() for s in srcs.values()))
print("reviewed   :", sum(len(s.reviewed_segments()) for s in srcs.values()))
s = srcs["I-002_01_NAR-01_STG_1_pre_boarding"]
print("example id :", s.get_segment("seg-0")["segment_id"])
print("speaker_id :", s.get_segment("seg-0")["speaker_id"])
PY
```

Expected for step 5: `transcripts: 27`, `segments: 3207`, `reviewed: 3163`, and
`example id: I-002_01_NAR-01_STG_1_pre_boarding.seg-0` — the same string that is stored
as `reviewed_transcripts.segment_id`.

---

## 7. Known traps

- **Absolute symlinks.** Fixed 2026-09-13 (§3.4). Re-introduced easily by `ln -s`
  with an absolute path — always pass the relative target.
- **A symlink is not a copy, but a snapshot directory can look like one.**
  `data/transcripts/html/` is *real vendored content*, not a symlink, and can drift
  from the canonical JSON while appearing to be the same data. See §8.
- **Editing "inside" `data/law/` while working here edits `transcription`'s corpus.**
  The path looks local; the write is not. The directory listing gives no hint.
- **`data/transcripts/bak/` in `transcription`** is a pre-`segment_labels` draft, *not*
  a pre-backfill snapshot. It is not the restore point you may be looking for; use
  `git show <commit>:<path>` instead.
- **Removed corpus:** `transcription/data/transcripts-named/` (24 files, an older ASR
  vintage) was deleted 2026-09-13 along with its two consumer scripts. Recoverable via
  `git show a2caeff:transcription/data/transcripts-named/<file>`. Do not recreate it.
- **A law file's `**Sha256:**` header is not the hash of that file.** 58 of the 101
  files under `data/law/` carry one, and **none** of the 58 matches
  `sha256(that file's bytes)` — measured, `declared == actual` is 0/58, which rules out
  "mostly right, occasionally stale". The field records the **upstream document** the
  text was fetched from (`Source:` names it), so it can never be satisfied by rewriting
  the file: any edit changes the bytes, and a self-referential hash would be wrong the
  instant it was written. The verifier therefore treats a mismatch as **INFO**, not a
  failure — `V03 article_text_hash` passes when the framework cache matches the bytes on
  disk and reports the declared/actual pair alongside. What this means in practice:
  quote the cache hash when you need to prove which bytes a bundle was validated against,
  and **do not** "fix" a header to make V03's INFO go away. Changing 58 files in a corpus
  owned by `transcription` to remove one informational line is a bad trade, and it would
  churn every consumer's framework-cache hash. (CL-030 is unaffected either way: it cites
  no CONST article as established.)

---

## 8. Corpus form and `data/transcripts/html/`

`violation-refiner/data/transcripts/html/` is a **symlink** to
`../../../../olivia/_shared/cases/la8159/02-transcripts/transcripts_rendered/I-002`
(27 `*.html`, byte-identical at the time of linking).

**Observed drift, then observed repair (2026-09-13).** It used to be 27 committed
real files that a sibling project overwrote in place. Mid-session,
`test_rendered_transcripts_match_json_segment_counts` failed on `I-002_05B` (6
rendered segments against 4 canonical). Ten minutes later, with **no change to this
repo**, it passed: every file had been regenerated at 07:29, dirtying ~5k lines of
`git diff`. Two conclusions, both load-bearing:

1. A vendored copy of a render **cannot stay in sync**. Committing it means every
   sibling render dirties this repo; there is no "snapshot" that survives contact.
2. That stale-segment failure was **not** a reliable signal. It appeared and vanished
   on someone else's schedule, so it could not gate this repo's correctness.

Linking it removes the copy, so the question of sync stops existing. The render is
still a *render*: it carries only bare role labels (`passenger`, `background_audio`)
and never `SPK-…`, so it can never join to `reviewed_transcripts` (§8.1).

> **This link leaves the `mcp-ecosystem` repo.** Unlike `data/law` and
> `data/transcripts/json/`, it depends on `olivia` being checked out as a sibling
> directory. It is a relative link (never commit an absolute one), but the layout is
> still an external assumption.

### 8.1 JSON is now the wired, authoritative transcript source

`violation_pack/sources_json.py::JsonTranscriptSource` reads a canonical document and
implements the same `TranscriptSource` protocol as `HtmlTranscriptSource`, so the two
are interchangeable everywhere `layers.py` consumes a source. It is wired into:

- `ui_server.discover_sources()` → new `transcripts_json` list (keyed by
  `transcript_id`, with `segment_id_example`), plus a `precedence` block;
- `ui_server.discover_transcript()` → accepts `data/transcripts/json/*.json`;
- `refine_batch_core._discover_transcripts()` → reads `Transcripts/*.json`;
- `ingesters.TranscriptIngester` → accepts canonical `segments[]` documents.

**This is the technical point of the wiring.** `layers.py` composes
`EvidenceSegment.segment_id = f"{source_id()}.{local_id}"`. For an HTML source,
`source_id()` is a *display* label (`STG-1`) that joins to nothing. For a canonical JSON
source, `source_id()` returns the `transcript_id`, so the composed id is **byte-identical
to `reviewed_transcripts.segment_id`**. That join is what lets a refiner finding be
traced back to an indexed, speaker-resolved, human-reviewed segment.

### 8.2 Decision taken — `html/` is a symlink to the render tree

**Resolved 2026-09-13.** No role below is load-bearing anymore:

| Role | Status |
|---|---|
| Rendered evidence source for the S2 HTML parser | **Superseded** by `JsonTranscriptSource` |
| Input to `len(transcripts) == 27` in `tests/test_ui_server.py` | Still reads `html/`, and still passes — through the symlink |
| Data-root marker for `find_data_root()` | **Relaxed**: accepts `transcripts/json/` **or** `transcripts/html/` |
| `tests/test_sources.py` segment-count parity check | Passes against the linked render; it is a smoke test, not a guarantee |

**`browse_workspace()` needed a fix to make this possible — and it was already
broken.** It resolved a path *before* checking containment, so any symlink leaving the
`violation-refiner` root was refused:

```
data/law                -> REFUSED (None)   # pre-existing, no test covered it
data/transcripts/html   -> REFUSED (None)   # the new symlink
data/transcripts/json   -> OK   (27 entries)
```

`data/law` points at `../transcription/data/law` — outside this workspace — and had
been silently unreachable for as long as it has existed. Containment is now checked
**lexically, on the unresolved path**, and the path is resolved only for
existence/type. That preserves traversal protection (`../../` is normalised and
rejected before any filesystem access) while permitting repo-owned symlinks; a person
who can plant a symlink in the repo can already read those files directly. Covered by
three tests, including one asserting `../transcription/...` and
`data/transcripts/html/../../../../olivia` are still refused.
