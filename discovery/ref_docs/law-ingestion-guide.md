# Law Document Ingestion Guide

How to take a raw law document (PDF, web page, or loose Markdown) and turn it
into a **standardized, article-level corpus file** that is ready to be ingested
into the Discovery legal Knowledge Base (Qdrant `la8159_law` / `la8159_law_bm25`).

This guide encodes the conventions actually used by the existing `data-law/`
corpus (90 files, 837 ingested articles). If you follow it, a new instrument
will parse cleanly, resolve ELI IDs, and index correctly with the registry tool
(`case-server/pipeline/build_law_registry.js`).

---

## 1. Decide the target output

Two equivalent representations; **Markdown is the authoring format** (readable,
diffable, reviewable), **JSON is the ingest format**. Generate the JSON from the
Markdown, never author JSON by hand.

| Format | Purpose | Where it lives |
|---|---|---|
| Markdown `.md` (article-level) | Author / review / source of truth | `data-law/<JUR>/<FILE>.md` |
| JSON (per point) | What actually gets indexed in Qdrant | produced by the ingestion step |

**Rule:** every file you add to `data-law/` should be **one legal instrument**
(the file = the law), containing **one `### Art. …` block per article** you want
indexed. Do **not** dump a whole consolidated code into one file as free text
(see §7 "whole-code reference files").

---

## 2. File placement & naming

Place the file in the folder matching its jurisdiction. Language is derived from
the folder, so naming must follow the folder convention exactly:

| Folder | Language | ELI jurisdiction token | Example filename |
|---|---|---|---|
| `data-law/BR/` | Portuguese | `BR` | `L8078_CDC.md`, `R400_ANAC.md` |
| `data-law/CL/` | Spanish | `CL` | `L18916_CACH.md`, `L20285_Transparencia.md` |
| `data-law/INT/BR/` | Portuguese (INT translation) | `INT` | `MC99_1999.md` |
| `data-law/INT/EN/` | English (INT original) | `INT` | `MC99_1999.md` |
| `data-law/CORP/` | English | `CORP` | `LATAM_CodeOfConduct_2024.md` |

Filename rules:
- `<CODE>_<SHORTNAME>.md`, e.g. `L18916_CACH.md`, `D2181_SNDC.md`, `R400_ANAC.md`.
- For international instruments keep the **same basename** in `INT/BR/` (PT) and
  `INT/EN/` (EN) — the two are translations of one instrument and share ELI IDs.
- **Do not** invent a filename whose subject differs from the file content (see
  the Chicago-1944 mislabeling incident in §8).

---

## 3. ELI ID conventions

An **ELI ID** is the stable article identifier. Format:

```
<JUR>.<FRAMEWORK>.<hierarchy...>.Art.<number>
```

Derived from the document's own structure:

| Piece | Meaning | Source | Example |
|---|---|---|---|
| `JUR` | Jurisdiction | folder | `BR`, `CL`, `INT` |
| `FRAMEWORK` | The instrument code | filename / law | `CACH`, `CDC`, `CBA`, `R400`, `CONST`, `CPCL`, `MC99` |
| `<hierarchy...>` | Title/Chapter/Section/Part as it appears | document headers | `T4.C2.S1.P3`, `C2.S1` |
| `Art.<number>` | the article number | article header | `Art.133`, `Art.3.1` |

### Hierarchy tokens

- **BR statutes** use `T<#>` (Título), `C<#>` (Capítulo), `S<#>` (Seção),
  `P<#>` (Parágrafo). Example: `BR.R400.C1.S1.Art.5`, `BR.CDC.T6.C3.Art.54`,
  `BR.CONST.T2.C1.Art.5.XX`, `BR.CC.PG.L3.T4.C1.S4.Art.206.P3.V`.
- **CL statutes** are flatter — often just `CL.CACH.Art.133`, but some carry
  hierarchy: `CL.L20285.T3.Art.12`, `CL.CHIPENCOD.T4.C6.Art.211`,
  `CL.CONST.T1.C3.P7.Art.19.7`.
- **INT instruments** mirror their chapter/section numbering:
  `INT.AN6I.C11.S3.Art.11.3`, `INT.MC99.C2.Art.5`, `INT.AN9.C3.S33.P1.Art.3.33.1`.

### Rules

- **Don't duplicate an article under two ELI forms.** One article = one ELI ID.
  (Known antipattern: `ABEAR_Code.md` lists each article twice — a canonical
  `BR.ABEAR_POL.§N — …` and an alias `BR.ABEAR_POL.SN`. Pick one canonical form
  and drop the other.)
- Preserve suffixes: `Art.133A` ≠ `Art.133`; `Art.3.1` ≠ `Art.3`.
- Legal article numbers survive verbatim even if unusual (`Art.133 A`,
  `Art.494 N 16`, `Art.269 ter`). Use the document's own numbering.

### Canonical framework codes (reference)

Resolver map lives in `case-server/pipeline/dossier_code_resolver.js`
(`FRAMEWORK_NAMES`). A sample of the codes in use:

- **Chile:** `CACH` (Código Aeronáutico), `CONST` (Constitución), `LPDC` (Ley
  19.496 consumidor), `CHIPENCOD`/`CPCL` (Código Penal), `L16752` (DGAC),
  `CC` (Código Civil), `L20285` (Transparencia), `JAC` (R218).
- **Brazil:** `CDC` (Lei 8.078), `CBA`/`LEI7565` (Código Aeronáutico), `CF88`/
  `CONST`, `R400`/`ANAC400` (Resolução ANAC 400), `CPB`/`CP` (Código Penal),
  `CC` (Código Civil 10.406), `L8906_OAB`, `CED_OAB`, `L12527`/`LAI`, `L8429`
  (Improbidade), `L12846` (Anticorrupção), `D2181`, `D7724`, `L9784`, `L13460`.
- **International:** `MC99` (Montreal 1999), `CHICAGO` (Chicago 1944), `VCLT`,
  `VCCR`, `ACHR`, `AN6I`/`AN9`/`AN11`/`AN13`/`AN14`/`AN17`/`AN18` (ICAO
  Annexes), `DOC4444`/`DOC8168`/`DOC9284`, `IATA_GC`, `UNGCP`, `UNCRC`,
  `HAGUE1980`, `BRCL`, `ILC`.

---

## 4. Source document → clean Markdown (PDF / web / .md)

### 4a. PDF

1. Prefer the **official source** (e.g. bcn.cl/leychile for CL, planalto.gov.br
   for BR, icao.int for ICAO annexes).
2. Extract text with your tool of choice:
   - CLI: `pdftotext -layout file.pdf file.txt` (poppler)
   - Or a PDF library (`pdf-parse` in Node, `pypdf`/`pdfplumber` in Python)
   - For scanned/OCR docs, OCR first (e.g. `ocrmypdf`) then extract.
3. **Watch for OCR corruption:** the CL corpus explicitly notes the BCN PDF OCR
   lost table layout in `L18916_CACH.md` (compensation table). If tables got
   mangled, reconstruct them from a second source or the official text and say
   so in `Notes`.
4. Strip headers/footers/page numbers, reflow line breaks, and drop figure-only
   pages. Keep paragraph and list structure.

### 4b. Web page / existing loose .md

- Convert to clean Markdown (browser "copy as Markdown", `pandoc`, or
  `trafilatura`/readability), then normalize to the template in §5.

### 4c. Manual review is mandatory

Automated extraction is never final. A human must verify against the official
text and set the verification flag (see §5 Metadata `Notes`). Mark the
`Sha256` of the source you used so provenance is auditable.

---

## 5. Standard Markdown template (authoring format)

This is the canonical article-level layout used across the corpus. Copy the
structure verbatim.

````markdown
# <TITLE> — <Human-readable law name>

## Metadata

- **Source:** <official URL>
- **Fetched:** <YYYY-MM-DD>
- **Sha256:** <hex of source used>
- **Articles:** <sorted list, e.g. 1, 5, 12, 133, 133 A>
- **Notes:** ✅ verified — <one-line description>
           (or ⏳ pending — not yet fully verified; NEVER invent text)

---

## Articles

### Art. <N> — <Short topic>

**Theme:** <theme>
**ELI ID:** `<JUR>.<FRAMEWORK>....Art.<N>`
**Hierarchy:** <optional hierarchy string>        <- optional; BR/CL long codes only
**Tags:** norm_type: <type> · scope: <scope> · sanctions: <s1, s2>   <- optional

<verbatim article body — keep original numbering, paragraphs, lists>

---
````

### Field guidance

- `## Metadata` — one per file. `Sha256` = hash of the *source* you converted.
- `### Art. N — Topic` — one per article. The heading is free text; the machine
  reads the `ELI ID` line.
- `**ELI ID:**` — use **exactly** this label. (4 legacy PT files use
  `**ID ELI:**`; the registry accepts both, but new files should use
  `ELI ID:` for consistency.)
- `**Hierarchy:**` — optional. Only needed when the ELI already encodes the
  hierarchy (e.g. `CL.CC.Art.1437`); mostly used to annotate human context.
- `**Theme:**` → Qdrant `theme`.
- `**Tags:**` → Qdrant `tags` (see §6 vocabulary).

### Allowed ELI label spellings (parser-compatible)

Both are parsed by `build_law_registry.js`:
```
**ELI ID:** `CL.CACH.Art.133`
**ID ELI:** `INT.IATA_GC.Art.1`     # legacy PT form — avoid in new files
```

---

## 6. Controlled vocabularies (Theme / Tags)

Keep tags **low-cardinality** so they stay filterable. Observed vocabulary:

- **norm_type:** `duty`, `power`, `right`, `penalty`, `definition`,
  `procedural`, `exemption`, `constitutional_principle`,
  `constitutional_guarantee`, `ethics`, `statute`,
  `administrative_instruction`
- **scope:** `regulatory`, `contractual`, `criminal`, `constitutional`,
  `obligational`, `state`, `administrative`
- **sanctions:** `financial_penalty`, `criminal_liability`,
  `service_remedy`, `suspension`, `license_revocation`,
  `compensacion_monetaria`

Format is a `·`-separated list, comma-separated within a facet:
```
**Tags:** norm_type: penalty · scope: contractual · sanctions: financial_penalty, service_remedy
```

---

## 7. What to index vs. what to keep as reference-only

The corpus distinguishes **article-level instruments** (indexed) from
**whole-code / institutional documents** (kept as reference, NOT article-ingested).

| Kind | Example | Action |
|---|---|---|
| Curated statute excerpts | `CL/CC_CodigoCivil.md` (6 arts) | Index (article blocks + ELI) |
| Curated penal excerpts | `CL/CHIPENCOD_CP.md`, `CL/CodigoPenal.md` | Index |
| Whole-code full text | `CL/ChileanCivilCodeandRelatedLaws.md` (~2.5k arts), `CL/CodigoPenalChile.md` (~577) | **Reference-only** — no ELI article headers; do not bulk ingest |
| Corporate codes of conduct | `CORP/*`, `BR/ABEAR_*` | Reference / contextual, not statutory law |

**Decision rule:** index only the articles that are *relevant and verified* for
the matter at hand. Do not ingest an entire code just because you have it —
~2.5k extra points of English civil-code text degraded corpus signal and were
rejected. If you need more of a code later, curate the additional articles into
the article-level file.

---

## 8. Quality checklist before saving

- [ ] One instrument per file, correct `data-law/<JUR>/` folder.
- [ ] `## Metadata` block with `Source`, `Fetched`, `Sha256`, `Notes` + a
      verification flag (`✅ verified` / `⏳ pending`).
- [ ] One `### Art. N — Topic` per article, each with exactly one
      `**ELI ID:**`.
- [ ] ELI follows `<JUR>.<FRAMEWORK>.<hier>...Art.<N>`; no duplicate alias forms.
- [ ] Article bodies are **verbatim** (never paraphrase or fabricate). If text
      is missing/unverified mark `⏳ pending` — never invent content.
- [ ] `Theme`/`Tags` use the controlled vocabulary (§6).
- [ ] Filename matches the file's actual content.
- [ ] `node --check` not needed (Markdown), but the file must be parseable by:
      `node case-server/pipeline/build_law_registry.js` and show the new ELIs as
      present (see §10).

### Historical pitfall — always check content↔filename

`INT/BR/Chicago_1944.md` was previously mislabeled: its content was actually the
**American Convention on Human Rights in Portuguese** (`INT.ACHR…` IDs), a copy
of `INT/EN/ACHR_1969.md`. It was renamed to `ACHR_1969.md`. **Lesson:** after
converting, grep the first `##` heading and the first ELI prefix and make sure
they match the filename before committing.

---

## 9. From Markdown → JSON (ingest payload)

Each `### Art.` block becomes one Qdrant point. The ingest JSON payload keys are
(verified against live `la8159_law` payloads):

```jsonc
{
  // flat, indexed/searchable copies:
  "original_id":  "CL.CACH.Art.133",            // = ELI ID (filtered exact)
  "title":        "Art. 133 — Denegacion de embarque por sobreventa",  // "Art. N — Topic"
  "text":         "<full article body>",        // searchable text
  "content":      "<full article body>",        // same as text (searchable)
  "theme":        "",                            // from **Theme:**
  "tags":         "norm_type: duty · scope: contractual · sanctions: service_remedy, compensacion_monetaria", // from **Tags:**
  "source_file":  "L18916_CACH.md",             // basename of the .md
  "doc_type":     "unknown",                    // legacy field

  // nested provenance (as ingested by the memory service):
  "original_data": {
    "id":          "<uuid>",                     // UUID assigned at ingest
    "title":       "…",
    "source_file": "L18916_CACH.md",
    "theme":       "…",
    "tags":        "…",
    "content":     "<full article body>",
    "original_id": "CL.CACH.Art.133"
  },

  // metadata envelope:
  "metadata": {
    "data_type":     "law",
    "doc_type":      "unknown",
    "ingestion_time": "<ISO-8601>"
  }
}
```

> Derived search fields (`jurisdiction`, `framework_code`) are added at index
> time on the BM25 collection. You do **not** need to author them.

### JSON↔Markdown derivation rules (implement in the converter)

| JSON key | Source in Markdown |
|---|---|
| `original_id` | `**ELI ID:**` value |
| `title` | `### Art. N — Topic` heading (reformatted `Art. N — Topic`) |
| `text` / `content` | everything under the `###` block after `Tags` (the verbatim body) |
| `theme` | `**Theme:**` value |
| `tags` | `**Tags:**` value (trim trailing ` · `) |
| `source_file` | `path.basename(file)` |

---

## 10. End-to-end workflow

```
1. GET SOURCE        official text (PDF / web). Record URL + Sha256.
2. EXTRACT           pdftotext / OCR -> clean text. Fix tables/layout.
3. NORMALIZE         split into one ### Art. block per article (verbatim).
4. ANNOTATE          add Theme / Tags / ELI ID per §3 & §6; fill Metadata.
5. VERIFY            human check vs official text -> ✅/⏳ flag in Notes.
6. PLACE             save to data-law/<JUR>/<CODE>_<NAME>.md
7. VALIDATE          node case-server/pipeline/build_law_registry.js
                     -> confirm new file: articles_local == articles_in_qdrant
                        is NOT yet true (they're local only), and no parse 0s.
8. INGEST            run the Qdrant ingestion (search/corpus pipeline):
                        - la8159_law        (exact lookup + payload store)
                        - la8159_law_bm25   (server-side BM25 sparse vectors,
                                             model qdrant/bm25)
9. RE-VALIDATE       re-run build_law_registry.js -> the new ELIs now appear in
                     Qdrant (source_basename_present_in_qdrant = true).
```

**Registry check after ingest:**

| Field | Before ingest | After ingest |
|---|---|---|
| `articles_local` | N | N |
| `articles_in_qdrant` | 0 | N |
| `articles_missing` | N | 0 |
| `source_basename_present_in_qdrant` | false | true |

---

## 11. Reference files

- Corpus: `data-law/` — clean examples to imitate:
  - `BR/R400_ANAC.md` (46 articles, `Theme`/`ELI ID`/`Tags`, list-style metadata)
  - `CL/L18916_CACH.md` (table-style metadata + `Hierarchy`, Spanish)
  - `INT/EN/ICAO_Annex6.md` (English INT)
- Registry + validator: `data-law/_mapping/law_registry.json`,
  `data-law/_mapping/LAW_REGISTRY.md`
- Registry generator: `case-server/pipeline/build_law_registry.js`
  (usage: `node case-server/pipeline/build_law_registry.js`)
- Framework names / ELI parsing: `case-server/pipeline/dossier_code_resolver.js`
- KB connector / payload mapping: `case-server/pipeline/legal_kb.js`
