# TC Chile — Tribunal Constitucional de Chile (Buscador de Jurisprudencia)

Reverse-engineering / integration notes for adding a scraper for the **Chilean
Constitutional Court** jurisprudence search to juris-search.

> **Status: ✅ IMPLEMENTED.** The scraper lives in `tc_chile_scraper.py`
> (`TCChileJurisprudenciaScraper`), registered as court key **`CLTC`** in
> `modules/courts.py`. Search + PDF download are verified working end-to-end.
>
> **Read §0 first.** The original recon below (§3–§4) contained several
> incorrect claims that were only caught when the API was probed directly
> during implementation. §0 lists every correction; where §0 and a later
> section disagree, **§0 wins**.

---

## 0. Verified Correction Log

Everything in this section was confirmed by direct HTTP probes and by
decompiling the SPA bundle (`/assets/index-DX71WdAE.js`), not by reading the
UI. These corrections **supersede** the corresponding statements in §3–§5.

| Original claim (wrong) | Verified reality |
|---|---|
| Download via ficha `id`: `GET /extended/{ficha_id}/download` | The download key is the **`folio`**. The SPA calls `rs(card.folio \|\| card.rol)` and `rs(this.ficha.folio)`. Using a ficha `id` or a `sentence_id` returns **HTTP 200 with a completely different document** — see "The id-namespace trap" below. |
| `fecha_sentencia` accepts a range `[start, end]` | **Exact date only** (`YYYY-MM-DD`). Every range form tried (`[a,b]`, `"a,b"`, `{"desde":..}`, `fecha_desde`/`fecha_hasta`) silently returned `total: 0`. Date ranges are implemented scraper-side by iterating day by day. |
| `/extended/sentencias` accepts the full filter set | It **ignores every filter except `search`** (and `literal`). Any given search term always returns the same total; adding `competencia`, `ministro`, `fecha_sentencia`, etc. changes nothing. |
| Catalog filters take **catalog item IDs** | They take **exact catalog NAMES** (strings) for `competencia`, `cuerpo_legal`, `ministro`, `palabra_clave`, `tipo_resolucion`, `resultado`. Only `articulo_constitucion` appears to accept IDs — and it is ignored anyway. |
| `per_page` / `rowsPerPage` is overridable | **Hard-fixed at 5** on `/buscadorexterno/ficha`. `per_page`, `rowsPerPage` and `rows` are all ignored. |
| Catalog 27 "Decisión" has 5 items, incl. "Empate" | Actual values: **Acoge, Rechaza, Empate de Votos, Acoge parcial, Rechaza parcial**. |
| API sets no `Content-Disposition` | It **does**: `attachment; filename="2012-04-30 16622.pdf"`, and the backend exposes it via `access-control-expose-headers: Content-Disposition`. The date in that filename is a portal-internal date, **not** the sentencia date — do not use it as `fecha`. |
| Single `fecha_sentencia` date returned 0 results | Worked (`"2026-03-19"` → 1). The earlier "0" was from a bad combination, not from single dates being unsupported. |

### The id-namespace trap (why `folio` matters)

`GET /extended/{X}/download` returns **HTTP 200 for any `X` that exists in *any*
id namespace**, and each namespace resolves to a *different real document*. This
was proven by downloading several ids, running `pdftotext` and comparing md5s —
four ids referring to "the same" case returned four distinct, genuine PDFs.

Only a truly nonexistent id 404s:

```json
{"message":"No se encontró un documento con el título: 99999999"}
```

Consequence: **HTTP 200 proves nothing**. Always download by **`folio`**. In
`/extended/sentencias` results `id == folio == rol`, so that path is safe too.

### Other verified facts

- `sortBy=id` → ascending; **omitting `sortBy` → newest-first descending**.
- `sortBy=id&descending=true` → non-JSON error response.
- `competencia` values are exact strings and fragile — the real value is
  `"Inaplicabilidad de Precepto Legal (Art. 93 N° 6 - INA) "` (note the
  trailing space). The SPA's own truncated `"(Art. 93 N° 6)"` returns **0**.
  `tc_chile_scraper` therefore resolves catalog values fuzzily
  (exact → id → accent-normalized → substring → token-overlap ≥ 0.45).
- Filters verified live: `resultado:"Acoge"` → 417, `resultado:"Rechaza"` → 339,
  `tipo_resolucion:"Sentencia"` → 951, `cuerpo_legal:"Código Civil"` → 27,
  `ministro:"María Pia Silva Gallinato"` → 62, `palabra_clave:"Aborto"` → 3,
  `competencia:"Inaplicabilidad de Precepto Legal (Art. 93 N° 6 - INA) "` → 31.
- Records flagged `es_reservada` are still downloadable, but are skipped by
  default; `incluir_reservadas=True` opts back in. `exist_file` must be truthy
  for a document to be downloadable at all.

---

## 1. Source Overview

| Item | Value |
|------|-------|
| Public name | Buscador de Jurisprudencia del Tribunal Constitucional |
| SPA (frontend) | https://buscador.tcchile.cl/#/ |
| Backend API | `https://buscador-backend.tcchile.cl/api` |
| Country | Chile 🇨🇱 |
| Court | Tribunal Constitucional de Chile (TC) |
| Frontend stack | Vue 3 + Vuetify 3 (Vite build, `materialdesignicons`) |
| Backend stack | Laravel (Laravel pagination envelope, Sanctum-free public API) |
| Auth | **None** — public, unauthenticated JSON API |
| Anti-bot | **None observed** — no CSRF token, no reCAPTCHA, no cookies required |
| Document format | PDF (signed digital documents), served directly by the API |

### Why this is a *different* source than the existing `CL` court

The project already has `chile_scraper.py` for `CL`, which targets
**`juris.pjud.cl`** — the *Poder Judicial* unified rulings portal
(Corte Suprema, Cortes de Apelaciones, Civiles, Penales, Laborales, …).

This source is the **Tribunal Constitucional** (a separate constitutional
body) at `buscador.tcchile.cl`. It must therefore be registered as an
**independent court entry** (suggested code `CLTC`), not merged into `CL`.

> Existing `CL`: Poder Judicial de Chile — Buscador Unificado de Fallos
> New source: Tribunal Constitucional de Chile — Buscador de Jurisprudencia

---

## 2. Architecture

```
┌──────────────────────────────┐        ┌─────────────────────────────────────┐
│ buscador.tcchile.cl (SPA)    │        │ buscador-backend.tcchile.cl (API)   │
│  Vue 3 + Vuetify, hash router│  GET   │  Laravel JSON API                   │
│  GET /api/... (axios)        ├───────►│  filter={json} query param          │
│  /#/  dashboard & results    │  JSON  │  meta: {total,page,per_page,...}    │
└──────────────────────────────┘        └─────────────────────────────────────┘
                                                     │
                                    ┌────────────────┴────────────────┐
                                    ▼                                 ▼
                          /api/buscadorexterno/ficha/*       /api/extended/*
                          (metadata "fichas")                (full sentence text + PDF)
```

- The SPA calls the backend **cross-origin** with `axios.get` and a plain
  `filter=<url-encoded JSON>` query parameter.
- No request signing, no CSRF, no session cookie is required for reads — which
  means a scraper can use **plain HTTP (`requests`)** and does **not** need Selenium.
- CORS on the backend is restricted to `Origin: https://buscador.tcchile.cl`;
  send that header to be safe (works from server-side too).

---

## 3. API Reference (verified live)

Base URL: `https://buscador-backend.tcchile.cl/api`

Recommended headers:

```http
Accept: application/json
Content-Type: application/json
Origin: https://buscador.tcchile.cl
```

### 3.1 Search fichas (metadata / keyword search)

```http
GET /buscadorexterno/ficha?page={n}&filter={json}
```

- `page` — 1-indexed.
- `filter` — URL-encoded JSON object of search criteria (see §4).
- **Page size is fixed at 5** (`per_page: 5`); `rowsPerPage`/`per_page` are ignored.
  Iterate pages until `current_page >= last_page`.

Verified example:

```bash
curl -s -G 'https://buscador-backend.tcchile.cl/api/buscadorexterno/ficha' \
  --data-urlencode 'page=1' \
  --data-urlencode 'filter={"search":"vida"}' \
  -H 'Origin: https://buscador.tcchile.cl'
```

Response envelope:

```json
{
  "data": [ { /* Ficha record — see §5.1 */ } ],
  "meta": { "total": 952, "current_page": 1, "per_page": 5, "last_page": 191 }
}
```

### 3.2 Full-text search in sentence text

```http
GET /extended/sentencias?filter={json}
```

- Powers the UI's **"Búsqueda de palabra en sentencia"** box and the
  exact-phrase (`literal`) mode.
- Performs server-side spelling correction (`corrected_query` in the response).
- Response shape differs from `/ficha`: results are nested under
  `data.results` with a `data.count`.
- ⚠️ **This endpoint ignores every filter except `search`/`literal`** (§0). Any
  other key — `competencia`, `ministro`, `fecha_sentencia`, … — has no effect on
  the result set. Verified: `{"search":"vida"}` always → `total: 486`.
  `tc_chile_scraper` therefore strips the payload down to `{search, literal}`
  before calling it.

Verified example:

```bash
curl -s -G 'https://buscador-backend.tcchile.cl/api/extended/sentencias' \
  --data-urlencode 'filter={"search":"vida","literal":false}' \
  -H 'Origin: https://buscador.tcchile.cl'
```

Response envelope:

```json
{
  "data": {
    "count": 486,
    "next": null,
    "previous": null,
    "all": [],
    "results": [ { /* Sentence record — see §5.2 */ } ],
    "corrected_query": null
  },
  "meta": { "total": 486, "current_page": 1, "per_page": 5, "last_page": 98 }
}
```

> `literal: true` toggles exact-phrase matching (used by the UI's
> *"frase exacta"* checkbox). A multi-word `search` without `literal` is treated
> as terms, and the response may include `corrected_query`.

### 3.3 Fetch a single sentence by id

```http
GET /extended/sentenciaByID?filter={"id":<sentence_id>,"search":"<keywords>"}
```

- `id` is the **sentence id** (the `id` field of a §5.2 result, i.e. the
  `sentence_id`/ROL-derived id), not the ficha id.
- Returns the same envelope as §3.2.

### 3.4 Download the full document (PDF)

```http
GET /extended/{folio}/download
```

- Returns the signed PDF (`Content-Type: application/pdf`, magic `%PDF-1.7`).
- `{folio}` is the **`folio`** from §5.1 (`data[].folio`) — **not** the ficha
  `id`. See §0 "The id-namespace trap": any existing id returns 200 with a
  *different real document*, so using `id` silently yields the wrong PDF.
- The server **does** set `Content-Disposition`. Verified:
  `GET /extended/16622/download` → HTTP 200, 697,944 B,
  `content-disposition: attachment; filename="2012-04-30 16622.pdf"`.
  The date in that filename is a portal-internal value, not the sentencia date.
- The frontend only renders a download button when `exist_file` is truthy.

Verified: `GET /extended/16622/download` → HTTP 200,
`application/pdf`, 697,944 B.

### 3.5 Catalogs (`tipodato`)

```http
GET /buscadorexterno/tipodato?sortBy=id&descending=true&page=1&rowsPerPage=100
```

Returns the master data used to populate the advanced-search dropdowns.
Standard Laravel pagination envelope (`current_page`, `data`, `per_page`, `total`, …).

| Catalog id | Nombre | Items |
|-----------:|--------|------:|
| 1 | Ministros | 70 |
| 2 | Palabras clave | 1036 |
| 25 | Causal de inadmisibilidad | 10 |
| 26 | Sala | 2 |
| 27 | Decisión | 5 |
| 28 | Precepto Legal | 6 |
| 29 | Artículo de la Constitución | 765 |
| 30 | Cuerpo Legal | 792 |
| 31 | Tipo de resolución | 2 |
| 32 | Iniciativa del proceso | 2 |
| 33 | Competencias | 17 |
| 36 | Prueba tipo dato | 2 |

Each catalog entry has nested `tipo_dato_contenido[]` items:

```json
{
  "id": 1,
  "nombre": "Ministros",
  "estado": 1,
  "tipo_dato_contenido": [
    { "id": 1, "nombre": "María Pia Silva Gallinato", "tipodato_id": 1 }
  ]
}
```

> ⚠️ **Corrected in §0:** advanced filter values are **catalog item NAMES**
> (exact strings), *not* IDs — except `articulo_constitucion`, which accepts IDs
> and is ignored by the backend anyway. Resolve names via `tipodato`; see
> `resolve_catalog_value()` in `tc_chile_scraper.py` for fuzzy matching.

---

## 4. Filter Parameters (UI field → API key)

Derived from the SPA source (`sendDataSearch` / `onSubmit`) and verified live.
**All catalog-backed values are exact catalog NAMES, not IDs** (see §0).

| UI field (Spanish) | API `filter` key | Type | Notes |
|--------------------|------------------|------|-------|
| Búsqueda por palabra clave | `search` | string | Keyword search. |
| Búsqueda de palabra en sentencia | `search` + `literal` | string + bool | Routed to `/extended/sentencias`. |
| Buscar por exclusión | `exclusion` | bool | Exclude `search` terms. |
| Número de rol / folio | `folio` | string | **The download key**, e.g. `"16622"`. |
| Fecha de sentencia | `fecha_sentencia` | string | **Exact date only**, `YYYY-MM-DD`. Ranges are NOT supported (§0). |
| Competencia | `competencia` | string (catalog 33 **name**) | Fragile: exact string incl. trailing space; fuzzy-resolved by the scraper. |
| Tipo de resolución | `tipo_resolucion` | string (catalog 31 **name**) | e.g. `"Sentencia"`, `"Inadmisibilidad"`. |
| Ministra/o (redactor) | `ministro` | string (catalog 1 **name**) | |
| Resultado | `resultado` | string (catalog 27 **name**) | `Acoge`, `Rechaza`, `Empate de Votos`, `Acoge parcial`, `Rechaza parcial`. |
| Artículo de la Constitución | `articulo_constitucion` | int (catalog 29 id) | Accepted but **ignored** by the backend. |
| Cuerpo legal | `cuerpo_legal` | string (catalog 30 **name**) | |
| Palabras clave | `palabra_clave` | string (catalog 2 **name**) | |

Empty/`null` fields are omitted by the SPA; the scraper should omit them too.
`literal`, `search`, `folio` and the catalog filters are only honoured by
`/buscadorexterno/ficha`; `/extended/sentencias` honours **only** `search`/`literal`.

**Endpoint routing rule (as implemented in `tc_chile_scraper.py`):**

```
if filter.literal is truthy            -> GET /extended/sentencias
elif search_index in {texto libre, texto_libre, fulltext, sentencias}
                                       -> GET /extended/sentencias
else                                   -> GET /buscadorexterno/ficha
```

Observed behavior details:

- `fecha_sentencia: "2026-03-19"` (single exact date) → **1** result. Range forms
  are silently rejected → `total: 0`, so the scraper implements ranges itself by
  querying one day at a time (`fecha_inicio`/`fecha_fin`, capped at
  `MAX_DATE_SCAN_DAYS`).
- `folio` filter returns the single ficha matching that folio.
- `exclusion: true` combined with `search` still returns matches (semantics of
  exclusion were not fully characterized — treat as pass-through).

---

## 5. Record Schemas

### 5.1 Ficha record (`/buscadorexterno/ficha` → `data[]`)

```json
{
  "id": 13526,
  "codigo": "06a-INA",
  "folio": "16622",
  "nombre": "INA-STC",
  "fecha_sentencia": "2026-03-19 03:00:00",
  "template_id": 27,
  "estado_id": 1,
  "exist_file": 1,
  "es_reservada": null,
  "template": {
    "id": 27,
    "nombre": "INA-STC",
    "codigo": "06a-INA",
    "tipo": "1",
    "complete_name": "Inaplicabilidad de Precepto Legal (Art. 93 N° 6 - STC)"
  },
  "estado": { "id": 1, "nombre": "Ingresado" },
  "detalle": [
    {
      "id": 235799,
      "ficha_id": 13526,
      "parametro_id": 3,
      "tipo": 1,
      "valor": "Proceso Rol N° 9947-2025 (Civil), ...",
      "parametro": { "id": 3, "nombre": "Gestión pendiente", "codigo": "c003" }
    }
  ]
}
```

`detalle[]` is the metadata payload — a list of `{parametro.nombre → valor}`
key/value pairs. Observed parameter names:

| `parametro_id` | Nombre | Significance |
|---------------:|--------|--------------|
| 2 | Precepto legal impugnado | impugned legal provision |
| 3 | Gestión pendiente | procedural status / underlying case ROL |
| 5 | Resultado | outcome (decided / inadmissible / …) |
| 6 | Voto mayoría | majority vote ministers |
| 7 | Redactor voto mayoría | majority-opinion rapporteur |
| 39 | Voto disidencia | dissenting vote ministers |
| 42 | Redactor disidencia | dissenting-opinion rapporteur |
| 50 | Doctrina | doctrinal summary (⚠️ often holds the **ementa-like summary**) |
| 63 | Artículo de la Constitución | constitutional articles invoked |
| 64 | Palabras clave | keywords |
| 68 | Sentencias relacionadas | related sentences |
| 71 | Tipo de resolución | resolution type |

> The values are frequently `null` for newer fichas; the full text is only
> available via `/extended/*` and the PDF download. `parametro_id` → label
> mapping should be resolved at runtime from `parametro.nombre` (do **not**
> hardcode ids — they are stable-but-opaque).

### 5.2 Sentence record (`/extended/sentencias` → `data.results[]`)

```json
{
  "id": "7001",
  "content": "Santiago, diez de septiembre de dos mil diecinueve.\n...",
  "sentence_id": 16564,
  "es_reservada": 0,
  "rol": "7001",
  "competencia": "Inaplicabilidad de Precepto Legal (Art. 93 N° 6 - INA)",
  "competenciaShortName": "INA-Inadmisibilidad",
  "highlightParagraphs": [
    { "full": "...matched paragraph text...", "summary": "..." }
  ],
  "highlightParagraphsAmount": 2,
  "custom_fields": { }
}
```

Key points:

- `content` is the **full sentence text** (OCR/plain-text export, with the
  court's own line-break artifacts like `Ciento olos`, `N*`, `poor`).
- `id` == `rol` for the sample; `sentence_id` is the numeric DB id used by
  `sentenciaByID`.
- `highlightParagraphs[]` contains the paragraphs matching the query — useful
  for `texto_preview` / relevance snippets.
- `competenciaShortName` mirrors `template.codigo`.

---

## 6. Download & Ingestion Flow

```
search (ficha or sentencias)
      │  collect folios (exist_file truthy, and not es_reservada)
      ▼
GET /extended/{folio}/download            →  PDF bytes
      │
      ▼
jurisprudence_downloads/{agent_id}/{folder}/{timestamp}/
   CLTC_[fecha_]folio.pdf
   CLTC_[fecha_]folio.pdf.metadata.json     (sidecar)
      │
      ▼
court_extractor → extracted_documents/CLTC_*.json → master_index → Qdrant
```

- Skip fichas where `exist_file` is falsy (no document) or `es_reservada` is
  truthy (reserved / restricted), unless `incluir_reservadas=True`.
- The download key is the **`folio`** — see §0.
- The local filename is built from verified data (`CLTC_{fecha}_{folio}.pdf`);
  the server's `Content-Disposition` name is stored only in the sidecar as
  `server_filename`, because its embedded date is misleading.
- ⚠️ **`court_extractor` has no `CLTC` extractor yet**, so the last arrow is
  currently broken: downloads succeed but `process_file` logs
  `SKIP …: no extractor for CLTC` and nothing is indexed. See §9 item 5.
- Because documents are PDFs, the downstream pipeline already handles them
  (`parser: "pdf"`, see `docs/ingestion_schema.md`).

---

## 7. Proposed Scraper Design

> **Status: ✅ IMPLEMENTED** — see `tc_chile_scraper.py`. This section is kept
> as the original design sketch; the notes below describe what actually shipped.

**What shipped (`tc_chile_scraper.py`, ~1,100 lines):**

- **Plain `requests`, no Selenium.** No auth, no CSRF, no CAPTCHA → no browser needed.
  (`_shared/chrome_driver.py` is imported only for `write_sidecar_metadata`.)
- Module constants: `TC_COURT_KEY = "CLTC"`, `TC_API_BASE`, `TC_PUBLIC_BASE`,
  `PER_PAGE = 5`, catalog ids (`CAT_MINISTROS = 1` … `CAT_COMPETENCIAS = 33`),
  `DEFAULT_REQUEST_DELAY = 0.35`, `MAX_PAGES_PER_DAY = 40`,
  `MAX_DATE_SCAN_DAYS = 400`.
- `SearchCriteria` dataclass carries both the **TC-native** filters and the
  **route-facing aliases** the generic search helper injects (`juez`, `materia`,
  `orgao_julgador`, `relator`, `tipo_norma`, …); `_build_filter` merges the alias
  groups into the native keys.
- `load_catalogs()` caches `tipodato` to `master_index/tc_chile_catalogs.json`;
  `resolve_catalog_value()` fuzzy-matches user text to catalog **names**.
- Two search paths: `_search_ficha` (`/buscadorexterno/ficha`, full filters) and
  `_search_sentencias` (`/extended/sentencias`, `{search, literal}` only).
- `search_with_criteria()` handles exact dates directly and date ranges via
  `_search_date_range()` (one request per day, newest first, deduped on folio).
- Filenames are built from verified data as **`CLTC_[fecha_]folio.pdf`**; the
  server's `Content-Disposition` name is stored only in the sidecar.
- Implements the full project download contract
  (`download_inteiro_teor_url(..., agent_id=, folder_name=, search_params=, _skip_org=)`
  and `download_all_inteiro_teor(..., overwrite=, delay=)`) with the
  `[agent_id, folder_name, timestamp]` folder convention.

**Integration surface (all done):**

| Touchpoint | Change |
|---|---|
| `modules/courts.py` | `SUPPORTED_COURTS["CLTC"]`, `COURT_NAMES["CLTC"]`, plus `COURT_ALIASES` and a rewritten `_resolve_court()` so names like `"TC Chile"` / `"Tribunal Constitucional de Chile"` resolve. |
| `modules/routes_search.py` | `_CLTC_FIELD_MAP` + extended `_USER_FIELD_KEYS`; mapping branch selects the map per court. |
| `modules/models.py` | 14 TC-native fields added to `SearchFields` (Pydantic silently drops unknown keys). |
| `modules/system_prompt.py` | `_build_tc_chile_system_prompt()` — Spanish prompt with TC competences, field list and critical rules. |
| `tjrs-frontend/src/App.jsx` | `CLTC` in `COURTS`, court resolver, display normalization, sidebar jurisdiction, `chile` scraper label. |
| `test_integration.py` | §13 exercises resolution, criteria round-trip, live search, folio/URL shape, and a real PDF download. |

### Original scraper sketch (superseded — see §7 above)

Follow the project's **common scraper interface** (see `PIPELINE.md` §3.3) so
the existing dispatch in `modules/routes_search.py` works unchanged:

```
__init__(headless=True)
search_with_criteria(SearchCriteria)      -> List[Dict]
download_inteiro_teor_url(url, save_dir, metadata) -> str
download_all_inteiro_teor(results, save_dir, ...)  -> List[str]
close()
```

But this source needs **no Selenium** — implement with `requests` (much faster,
no Chrome dependency). Keep `headless` accepted and ignored for interface parity.

Suggested file: `tc_chile_scraper.py`

```python
class TCChileJurisprudenciaScraper:
    BASE = "https://buscador-backend.tcchile.cl/api"
    HEADERS = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://buscador.tcchile.cl",
    }

    def search_with_criteria(self, criteria):
        # 1. build filter dict from criteria (map §4)
        # 2. choose endpoint (fichas vs sentencias) per routing rule
        # 3. page through results (fixed per_page=5) up to max_results
        # 4. normalize -> common result dict (see §8)
        ...

    def download_inteiro_teor_url(self, folio, save_dir, metadata):
        # GET f"{BASE}/extended/{folio}/download" -> write PDF + sidecar
        ...
```

> ⚠️ The sketch above is kept for historical context only. The shipped
> signature is `download_inteiro_teor_url(self, url, filename=None, save_dir=None,
> metadata=None, agent_id=None, folder_name=None, search_params=None, _skip_org=False)`
> and the download key is **`folio`**, not `ficha_id` (§0).

### Recommended catalog caching

Resolve advanced-filter labels to **names** with a one-time `tipodato` fetch,
cached to disk (e.g. `master_index/tc_chile_catalogs.json`) — the catalog is
~1000+ items and rarely changes.

---

## 8. Field Mapping → Project Result Schema

Normalize each TC-Chile result to the shape the frontend / master index expects
(see `docs/ingestion_schema.md`):

| Project field | TC-Chile source |
|---------------|-----------------|
| `tribunal` | `"CLTC"` (new) |
| `tribunal_pais` | `"CHILE"` |
| `numero_processo` / `rol` | ficha `folio` (ROL, e.g. `16622`) |
| `id` | not set — the pipeline keys off `numero_processo` (the folio). `metadata.ficha_id` carries the raw ficha id. |
| `data_julgamento` | ficha `fecha_sentencia` (`YYYY-MM-DD`) |
| `classe` / `tipo` | `template.complete_name` or `competencia` |
| `relator` | ficha `detalle[parametro="Redactor voto mayoría"].valor` |
| `ementa` / `texto_preview` | `content` (first N chars) or `highlightParagraphs[0].summary` |
| `assunto` / palavras-chave | `detalle[parametro="Palabras clave"].valor` |
| `legislacao_citada` | `detalle[parametro="Precepto legal impugnado"/"Artículo de la Constitución"]` |
| `outcome` | `detalle[parametro="Resultado"].valor` → map to project enum |
| `inteiro_url` | ``f"{BASE}/extended/{folio}/download"`` — **use `folio`, never `id`** (§0) |
| `url_detalle` | ``f"{TC_PUBLIC_BASE}/#/ficha/{folio}"`` |
| `exist_file` | ficha `exist_file` — gate for downloadable results |

**Outcome enum mapping (proposed):**

| TC-Chile `Resultado` | Project outcome |
|----------------------|-----------------|
| Acoge / Requerimiento acogido | `dado_provimento` / `procedente` |
| Rechaza / No acoge | `negado_provimento` / `improcedente` |
| Inadmisible | `improcedente` *(new value `inadmissible` recommended)* |
| Sin pronunciamiento | *(store raw, no enum)* |

> Verify actual `Resultado` catalog values from `tipodato` id 27 (Decisión,
> 5 items) before finalizing the mapping.

---

## 9. Integration Checklist

> **Status: items 1–4 and 6 are ✅ done.** Item 5 is the only remaining work.

1. ✅ **Create** `tc_chile_scraper.py` implementing the common interface (§7).
2. ✅ **Register** the court in `modules/courts.py`:
   ```python
   "CLTC": {
       "name": "CLTC",
       "scraper_module": "tc_chile_scraper",
       "scraper_class": "TCChileJurisprudenciaScraper",
   },
   ```
   and add to `COURT_NAMES`:
   `"CLTC": "Tribunal Constitucional de Chile (TCChile)"`.
   Additional fix required: `_resolve_court()` could not resolve friendly names
   (`"TC Chile"`, `"TCChile"`, `"Tribunal Constitucional de Chile"` all fell
   through to `TJRS`), so a `COURT_ALIASES` map + auto-derived aliases from
   `COURT_NAMES` were added.
3. ✅ **Frontend**: `CLTC` added to `COURTS` in `tjrs-frontend/src/App.jsx`,
   plus the court resolver, display normalization, sidebar jurisdiction and
   `chile` scraper label. The existing `CL` entry was renamed to **"Chile PJud"**.
4. ✅ **System prompt**: `_build_tc_chile_system_prompt()` added to
   `modules/system_prompt.py` (Spanish; dispatched before the `CL` branch).
5. ⬜ **Extractor** *(only remaining item)*: `court_extractor.py` has no `CLTC`
   entry, so `process_file` logs `SKIP {file}: no extractor for CLTC` and
   downloaded TC PDFs are **not** indexed into Qdrant/Neo4j. `BaseExtractor` is
   Brazil/Portuguese-specific (`EMENTA` markers, CNJ keywords), so this needs a
   Spanish-Chilean `CLTCExtractor` subclass — not a quick patch. Note the API
   already returns structured metadata, so much of this can be a pass-through.
6. ✅ **Tests**: `test_integration.py` §13 does a live search + a real PDF
   download and asserts the `%PDF-` magic.

---

## 10. Open Questions / Risks

> **Resolutions are in §0.** Outstanding items are marked ⬜.

1. ✅ **Detail page deep link** — SPA is hash-routed; implemented as
   `{TC_PUBLIC_BASE}/#/ficha/{folio}`.
2. ✅ **Rate limits** — undocumented; `tc_chile_scraper` uses a polite
   `DEFAULT_REQUEST_DELAY = 0.35 s` and a bounded page cap.
3. ✅ **Fixed page size** — 5/page confirmed hard-coded; the scraper stops at
   `max_results` and caches catalogs to disk.
4. ✅ **`/ficha/{id}` returned 404** — confirmed; the list endpoint embeds the
   full `detalle`, so no per-ficha detail endpoint is used.
5. ✅ **Data quality** — `content` OCR artifacts are noted; the PDF is treated as
   authoritative.
6. ✅ **Reserved documents** — `es_reservada` is filtered out unless
   `incluir_reservadas=True`; `exist_file` gates downloadability.
7. ✅ **`fecha_sentencia` time-of-day** — truncated to date when normalizing.
8. ✅ **CORS / Origin** — `Origin: https://buscador.tcchile.cl` is always sent.
9. ⬜ **Downstream indexing** — see checklist item 5; requires `CLTCExtractor`.
10. ⬜ **MCP catalog staleness** — `mcp/juris_api.json` and
    `mcp/catalog/*` are generated snapshots that predate the `SearchFields`
    addition; regenerate with `mcp/generate_tool_catalog.py` while the API is up.

---

## 11. Verification Log

All facts above were verified live against the production API on **2026-09-13**
(full re-verification during implementation, which invalidated several of the
original recon claims — see §0).

**Endpoint totals**

| Check | Result |
|-------|--------|
| `/buscadorexterno/ficha` (no filter) | 200, `total: 12329` |
| `/buscadorexterno/ficha?filter={"search":"vida"}` | 200, `total: 952`, `per_page: 5`, `last_page: 191` |
| `/extended/sentencias?filter={"search":"vida"}` | 200, `count: 486`, `per_page: 5`, `last_page: 98` |
| `/buscadorexterno/tipodato?sortBy=id&descending=true&page=1&rowsPerPage=100` | 200, 12 catalogs |
| `/buscadorexterno/ficha/13526` | 404 (no per-ficha detail endpoint) |

**Filter behaviour (names, not ids)**

| Filter | Result |
|--------|--------|
| `{"folio":"16622"}` | `total: 1` |
| `{"resultado":"Acoge"}` | `total: 417` |
| `{"resultado":"Rechaza"}` | `total: 339` |
| `{"tipo_resolucion":"Sentencia"}` | `total: 951` |
| `{"cuerpo_legal":"Código Civil"}` | `total: 27` |
| `{"ministro":"María Pia Silva Gallinato"}` | `total: 62` |
| `{"palabra_clave":"Aborto"}` | `total: 3` |
| `{"competencia":"Inaplicabilidad de Precepto Legal (Art. 93 N° 6 - INA) "}` | `total: 31` |
| `{"fecha_sentencia":"2026-03-19"}` | `total: 1` |
| `{"fecha_sentencia":["2025-01-01","2025-12-31"]}` | `total: 0` — ranges unsupported |
| `{"articulo_constitucion":3}` | ignored (`total: 12329`) |

**Sorting**

| Check | Result |
|-------|--------|
| `sortBy=id` | ascending |
| *(no `sortBy`)* | newest-first (descending) |
| `sortBy=id&descending=true` | non-JSON error response |

**Download (the id-namespace trap)**

| Check | Result |
|-------|--------|
| `/extended/16622/download` | 200, `application/pdf`, 697,944 B, `content-disposition: attachment; filename="2012-04-30 16622.pdf"` |
| `/extended/99999999/download` | 404, `{"message":"No se encontró un documento con el título: 99999999"}` |
| Four ids that all "reference" one case | 200 ×4, **four different PDFs** (confirmed via `pdftotext` + md5) |

**End-to-end (this project)**

| Check | Result |
|-------|--------|
| `POST /api/search {"court":"CLTC","search_text":"vida","max_results":3,"tipo_resolucion":"Sentencia"}` | `completed`, 3 results, `court: "CLTC"`, `inteiro_url: …/extended/{folio}/download` |
| `POST /api/download {"tribunal":"CLTC", …}` | `success: true`, `…/jurisprudence_downloads/juris-search/20260913_035916/CLTC_16622.pdf`, magic `%PDF-`, 697,944 B |
| `test_integration.py` | 295 checks, 290 passed — the 5 failures are pre-existing and require `DEEPSEEK_API_KEY`; **zero CLTC failures** |

---

## 12. Reference — SPA Source Snippets

Extracted from `https://buscador.tcchile.cl/assets/index-DX71WdAE.js` (Vite bundle):

```js
// keyword / advanced search
axios.get("https://buscador-backend.tcchile.cl/api/buscadorexterno/ficha", {
  params: { page, filter: JSON.stringify({...}) },
  headers: { "Content-Type": "application/json" },
});

// full-text / exact-phrase search
axios.get("https://buscador-backend.tcchile.cl/api/extended/sentencias", {
  params: { filter: JSON.stringify({...}) },
  headers: { "Content-Type": "application/json" },
});

// sentence by id
`https://buscador-backend.tcchile.cl/api/extended/sentenciaByID?filter={"id":${id},"search":"${q}"}`

// document download — key is the FOLIO (card.folio || card.rol), not the ficha id
`https://buscador-backend.tcchile.cl/api/extended/${folio}/download`
```

> The minified bundle resolves the download identifier via helpers rendered as
> `rs(card.folio || card.rol)` and `rs(this.ficha.folio)` — i.e. the `folio`.
> The `id` used by `/sentenciaByID` is a *different* namespace (§0).
```
