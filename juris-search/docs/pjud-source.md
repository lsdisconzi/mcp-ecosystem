# Poder Judicial de Chile — Buscador Unificado de Fallos (`juris.pjud.cl`)

Reverse-engineering / integration notes for the scraper that backs the existing
**`CL`** court entry in juris-search.

> **Status:** source recon + request contract documented live against production.
> A scraper already exists (`chile_scraper.py`) and works today, but this
> document corrects several gaps in it — most importantly the
> **`id_buscador` → section mapping** and the **F5 WAF layer** which the current
> code mislabels as "reCAPTCHA".
>
> Companion document: `docs/tc-chile-source.md` (Tribunal Constitucional, a
> *different* Chilean source — proposed court code `CLTC`).

---

## 1. Source Overview

| Item | Value |
|------|-------|
| Public name | Buscador Unificado de Fallos del Poder Judicial |
| Portal (SPA) | https://juris.pjud.cl/busqueda |
| Section index | https://juris.pjud.cl/lista_buscadores |
| Country | Chile 🇨🇱 |
| Operator | Poder Judicial de Chile |
| Frontend stack | Laravel Blade + jQuery + Bootstrap 4 + DataTables + select2 + jsTree + Highmaps |
| Backend stack | Laravel (CSRF meta token, `PHPSESSID` + `XSRF-TOKEN` cookies) |
| Auth | **None required for search**; optional account at `/busqueda/bienvenida` |
| Anti-bot | ⚠️ **F5 BIG-IP ASM (TSPD)** *and* **Google reCAPTCHA v3** |
| Document format | HTML detail view (`page_source`) + PDF/XML panels |
| Help | https://ayudamcs.pjud.cl/jurisunificado/ · https://juris.pjud.cl/material_ayuda |

### Why this source is hard

This is the most heavily defended source in the project. Two independent layers
stand between a scraper and the data:

1. **F5 BIG-IP ASM / TSPD** — a JavaScript challenge with an image-CAPTCHA
   fallback. It guards the whole `pjud.cl` domain family.
2. **Google reCAPTCHA v3** — site key `6Lf5adcZAAAAAGCJfAo8YQ2jb6uYZ2VE-AwHnUmk`,
   validated server-side (Laravel) on search POSTs.

The practical consequence: **plain HTTP scraping (`requests`) is impossible.**
Even a real browser is rejected for direct `fetch()`/`XHR` POSTs unless the
session has passed F5 *and* the reCAPTCHA v3 score is acceptable. This is
exactly why the existing `chile_scraper.py` drives a real Chrome instance via
`_shared/chrome_driver.py` and clicks the UI button rather than calling the API.

### F5 protection scope (verified)

| Host | F5 protected? | Notes |
|------|---------------|-------|
| `juris.pjud.cl` | ✅ Yes | TSPD challenge on GET; POST search blocked |
| `www.pjud.cl` | ✅ Yes | Same F5 family |
| `busddhh.pjud.cl` | ✅ Yes | Derechos Humanos buscador |
| `baremo.pjud.cl` | ❌ No | Serves real XHTML (`/BAREMOWEB/`) |
| `api.pjud.cl` | ❌ No | Returns literal `API.PJUD.CL` |

**Observed F5 artifacts**

- Inline `<script>` injecting `window["bobcmn"]` and the `TSPD_101` cookie.
- Image challenge at `/TSPD/<hash>?type=5` (`What code is in the image?`,
  `Your support ID is: <n>`).
- **Blocked-POST signature** (this is what a scraper must detect):
  - HTTP status is **200** (not a 4xx/5xx — easy to misread as success).
  - Body: `<html><head><title>La URL solicitada ha sido rechazada</title></head>…`
    with `Su numero de soporte es : <…>`.
  - Response header **`x-security-action: 0800000200`**.
  - Related request header `x-security-request: required`.
- **Escalation pattern:** ordinary GET navigations succeed for a few requests,
  then F5 re-challenges. Rapid section iteration (as a scraper naturally does)
  trips this quickly — observed blocking after ~6 consecutive `page.goto` calls.
  A single manual CAPTCHA solve clears it again.

> **Detector to implement:** treat a response as an F5 block if the body
> contains `rechazada` / `human visitor` / `Su numero de soporte`, **or** if the
> `x-security-action` header is present. Never treat HTTP 200 as success here.

---

## 2. Architecture

```
┌──────────────────────────────────────────┐
│ juris.pjud.cl/busqueda?<Section>         │
│  Laravel Blade shell                     │
│  • inline config: id_buscador_activo,    │
│    parametros_buscador                   │
│  • meta[name=csrf-token]                 │
│  • jQuery components (panel_busqueda.js, │
│    omnibox.js, busqueda_avanzada.js, …)  │
└───────────────┬──────────────────────────┘
                │  POST multipart/form-data
                │  X-Requested-With: XMLHttpRequest
                ▼
┌──────────────────────────────────────────┐
│ POST /busqueda/buscar_sentencias         │
│  _token, id_buscador, filtros (JSON),    │
│  numero_filas_paginacion,                │
│  offset_paginacion, orden, personalizacion│
└───────────────┬──────────────────────────┘
                │  tab-delimited envelope
                │  "<code>\t<json payload>"
                ▼
┌──────────────────────────────────────────┐
│ Results rendered into DOM rows carrying  │
│   [data-idsentencia="<id>"]              │
│   + "Ver sentencia" button               │
└──────────────────────────────────────────┘
```

Each **section** of the portal is the *same* page with a different
`?<Section>` query parameter. The section determines a numeric
**`id_buscador`**, which is the single required key for every request.

---

## 3. Endpoint Reference (verified live)

All URLs were extracted from the inline configuration on
`https://juris.pjud.cl/busqueda?Civiles`:

```js
var url_estadisticas_visitas_y_busquedas = "https://juris.pjud.cl/busqueda/estadisticas_visitas_y_busquedas";
var url_arbol_indice_tematico_json        = "https://juris.pjud.cl/busqueda/arbol_json";
var url_cargar_detalle_sentencia          = "https://juris.pjud.cl/busqueda/buscar_sentencias";
var url_webservices                       = "https://juris.pjud.cl/busqueda/webservices";
var url_arbol_indice_tematico_json_detalle_sentencia = "https://juris.pjud.cl/busqueda/arbol_json";
var url_imprimir_sentencia                = "https://juris.pjud.cl/busqueda/imprimir";
var url_sentencias_guardadas              = "https://juris.pjud.cl/busqueda/sentencias_guardadas";
var url_ids_sentencias_relacionadas       = "https://juris.pjud.cl/busqueda/listar_ids_relacionados";
var url_enviar_mail_compartir_sentencia   = "https://juris.pjud.cl/busqueda/mail_compartir_sentencia";
var url_documentos                        = "https://juris.pjud.cl/busqueda/documentos";
var url_terminos_juridicos                = "https://juris.pjud.cl/detalle_sentencia/terminos_juridicos";
var url_buscador_terminos_juridicos       = "https://juris.pjud.cl/detalle_sentencia/buscador_terminos_juridicos";
```

| # | Endpoint | Method | Purpose | Relevance to scraper |
|---|----------|--------|---------|----------------------|
| 3.1 | `/busqueda?<Section>` | GET | Search shell for a section | **Required** — establishes session + config |
| 3.2 | `/busqueda/buscar_sentencias` | POST | Execute a search / load a detail | **Primary** |
| 3.3 | `/busqueda/documentos` | GET/POST | Document/assets for a sentence | **Download path** |
| 3.4 | `/busqueda/imprimir` | GET | Printable (clean) sentence view | **Alt. full-text** |
| 3.5 | `/busqueda/estadisticas_visitas_y_busquedas` | GET | `?id_buscador=<n>` → counts | Nice-to-have |
| 3.6 | `/busqueda/arbol_json` | GET | Thematic index tree (JSON) | Optional (facets) |
| 3.7 | `/busqueda/listar_ids_relacionados` | POST | Related sentences | Optional |
| 3.8 | `/busqueda/sentencias_guardadas` | POST | Saved sentences (account) | Needs login — skip |
| 3.9 | `/busqueda/mail_compartir_sentencia` | POST | Share by email | Not for scraping |
| 3.10 | `/busqueda/webservices` | mixed | Generic service hub | Undocumented — probe later |
| 3.11 | `/detalle_sentencia/terminos_juridicos` | GET | Legal-term glossary | Optional enrichment |
| 3.12 | `/detalle_sentencia/buscador_terminos_juridicos` | GET | Glossary search | Optional enrichment |

> `/lista_buscadores` (the section index) was **not** reachable during recon —
> blocked by F5 on every attempt. See §11 Open Questions.

### 3.5 Response envelope — tab-delimited

AJAX responses from this portal use a **tab-delimited envelope**, not raw JSON:

```js
data = response.split("\t");
if (data[0] === "0") {            // "0" = success
    payload = JSON.parse(data[1]); // JSON lives after the first tab
}
```

Confirmed on `/busqueda/estadisticas_visitas_y_busquedas`, which returns
`{"busquedas": <int>, "visitas_totales": <int>}` in `data[1]`.

> **Scraper rule:** always split on `\t` first; a bare `JSON.parse(response)`
> will fail.

---

## 4. Section → `id_buscador` Map

Each section URL sets `window.id_buscador_activo` and
`window.parametros_buscador` in an inline script. **The current
`chile_scraper.py` does not send `id_buscador` at all** — it is the missing key
that makes the API contract usable.

| Section URL | `id_buscador` | `nombre_buscador` | `tipo_instancia_principal` | Notes |
|-------------|---------------|-------------------|----------------------------|-------|
| `/busqueda` | *(null)* | — | — | Landing page; config not exposed |
| `?Corte_Suprema` | **528** | Corte Suprema | `corte_suprema` | |
| `?Corte_de_Apelaciones` | **168** | Corte de Apelaciones | `corte_apelaciones` | |
| `?Civiles` | **328** | Civiles | `civil` | Reference section for all captures |
| `?Penales` | **268** | Penales | `penal` | |
| `?Laborales` | **271** | Laborales | `laboral` | |
| `?Familia` | **270** | Familia | `familia` | |
| `?Cobranza` | **269** | Cobranza | `cobranza` | |
| `?Salud_CS` | **127** | Salud CS | `corte_suprema` | Health-law subset of CS |
| `?Lineas_Jurisprudenciales` | **628** | Lineas Jurisprudenciales | `corte_suprema` | ⚠️ Special mode — `es_lj: true` |
| `?Compendio_Extranjer%C3%ADa` | ❓ *(unverified)* | Compendio Extranjería | — | F5-blocked during recon |

Sections rendered as navigation buttons in the UI (7):
`Corte Suprema · Corte de Apelaciones · Laborales · Cobranza · Penales · Familia · Civiles`

The remaining four (`Salud_CS`, `Lineas_Jurisprudenciales`,
`Compendio_Extranjería`, plus the base landing) are reachable **only by direct
URL** — they are not in the visible button row.

### `Lineas_Jurisprudenciales` is structurally different

```js
window.es_lj = true;
// parametros_buscador:
//   tipo_instancia_principal: "corte_suprema"
//   buscador_lineas_jurisprudenciales: true
//   campos_facetas: ["Tema", "Línea jurisprudencial", "Sala"]
```

It carries its own faceting model (`Tema` / `Línea jurisprudencial` / `Sala`)
rather than the generic `materia`/`juez` facets, and sets a global
`es_lj` flag that other components read. **Treat it as a separate scraper
mode**, not just another `id_buscador`.

---

## 5. Request Contract — Search

Fully captured from a live search on `/busqueda?Civiles`.

### 5.1 Request

```
POST https://juris.pjud.cl/busqueda/buscar_sentencias
Content-Type: multipart/form-data; boundary=----WebKitFormBoundary…
X-Requested-With: XMLHttpRequest
X-Security-Request: required
Referer: https://juris.pjud.cl/busqueda?Civiles
```

**Multipart fields**

| Field | Value | Notes |
|-------|-------|-------|
| `_token` | CSRF token | Read from `meta[name="csrf-token"]` |
| `id_buscador` | e.g. `328` | From §4 |
| `filtros` | JSON **string** | See §5.2 |
| `numero_filas_paginacion` | `10` | Page size (`10-20-50` per config) |
| `offset_paginacion` | `0` | Zero-based offset (not page number) |
| `orden` | `recientes` | Default sort |
| `personalizacion` | `false` | Account personalisation |

### 5.2 `filtros` JSON payload

Exact shape observed (empty search, `Civiles`):

```json
{
  "rol": "",
  "era": "",
  "fec_desde": "",
  "fec_hasta": "",
  "tipo_norma": "",
  "num_norma": "",
  "num_art": "",
  "num_inciso": "",
  "todas": "",
  "algunas": "",
  "excluir": "",
  "literal": "",
  "proximidad": "",
  "distancia": "",
  "analisis_s": "11",
  "submaterias": "",
  "facetas_seleccionadas": [],
  "filtros_omnibox": [
    { "categoria": "TEXTO", "valores": [""] }
  ],
  "ids_comunas_seleccionadas_mapa": []
}
```

**Field semantics**

| Key | Meaning | UI origin |
|-----|---------|-----------|
| `rol` | ROL / RIT case number | Advanced search "Rol" |
| `era` | `era` component of the ROL | Advanced search |
| `fec_desde` / `fec_hasta` | Date range | Facet: date tree |
| `tipo_norma` / `num_norma` / `num_art` / `num_inciso` | Cited-law filters | Facet: normas tree |
| `todas` / `algunas` / `excluir` | Boolean full-text operators | Advanced search |
| `literal` | Exact phrase | Advanced search |
| `proximidad` + `distancia` | Proximity search | Advanced search |
| `analisis_s` | Analysis mode flag (`"11"` observed default) | Internal |
| `submaterias` | Sub-topic filter | Thematic index |
| `facetas_seleccionadas` | Array of applied facet values | Facet panels |
| `filtros_omnibox` | **Primary free-text entry** — `[{categoria, valores[]}]` | Omnibox |
| `ids_comunas_seleccionadas_mapa` | Territorial map filter | Highmaps panel |

> ⚠️ **Observed quirk:** setting `#tb_input_omnibox` programmatically and
> dispatching `input`/`change` updated the visible textbox but the request still
> carried `"valores": [""]`. The omnibox component keeps its own state and only
> commits on genuine keystrokes. A scraper must **type into the field** (Selenium
> `send_keys`) rather than assign `.value`, or post the JSON itself if the
> reCAPTCHA score allows.

### 5.3 F5 behaviour on this endpoint

Every direct POST attempted during recon — via the page's own button **and** via
`fetch()` — returned the F5 rejection (`x-security-action: 0800000200`, HTTP
200, "La URL solicitada ha sido rechazada"), even immediately after a successful
manual CAPTCHA solve. The POST path appears to be the most aggressively
filtered route on the host.

**Implication:** the request contract in §5.1–5.2 is documented for reference and
for a *real-browser* implementation, but the working strategy remains
**UI-driven search inside Chrome** (§7).

---

## 6. `parametros_buscador` — Per-Section Configuration

Every section ships a JSON config object describing which fields to display,
facet, and expose. This is authoritative for building the field→column mapping.

Example (`Civiles`, `id_buscador` 328):

```json
{
  "id_buscador": "328",
  "nombre_buscador": "Civiles",
  "tipo_ordenamiento_defecto": "recientes",
  "numero_resultados_pagina": "10-20-50",
  "campos_listado_resultados": [
    "rol_era_sup_s", "caratulado_s", "fec_sentencia_sup_dt",
    "gls_juz_s", "gls_materia_s", "gls_juez_ss"
  ],
  "campos_facetas": [
    "fec_sentencia_sup_dt", "gls_materia_s", "gls_juz_s", "gls_juez_ss"
  ],
  "campos_detalles_sentencia": [
    "rol_era_sup_s", "caratulado_s", "fec_sentencia_sup_dt",
    "gls_juz_s", "gls_materia_s"
  ],
  "mostrar_estructura_en_detalle_sentencia": false,
  "mostrar_entidades_en_detalle_sentencia": false,
  "mostrar_resumen_votos_en_detalle_sentencia": false,
  "mostrar_panel_normas_relevantes": false,
  "mostrar_panel_normas_mencionadas": false,
  "mostrar_panel_buscador_externo_normas": false,
  "mostrar_contenido_corte_suprema": true,
  "mostrar_contenido_corte_apelaciones": true,
  "mostrar_contenido_tribunales": true,
  "mostrar_indice_tematico": false,
  "mostrar_controles_analisis_jurisprudencial": false,
  "mostrar_grupo_componentes_normas_busqueda_avanzada": false,
  "mostrar_cuadro_sugerencias_omnibox": true,
  "texto_placeholder_omnibox": "Ingrese texto libre de búsqueda",
  "tipo_instancia_principal": "civil",
  "ws_2_visible": false,
  "ws_3_visible": false,
  "ws_1_etiqueta_pestanna": "Primera Instancia",
  "ws_2_etiqueta_pestanna": "Corte de Apelaciones",
  "ws_3_etiqueta_pestanna": "Corte Suprema",
  "busqueda_hibrida": false,
  "buscador_lineas_jurisprudenciales": false
}
```

### Field-name catalogue

The `campos_*` arrays use opaque Solr-style suffixed names. Decoded:

| Field name | Meaning | Suffix |
|------------|---------|--------|
| `rol_era_sup_s` | ROL (with era) | `_s` = string |
| `caratulado_s` | Case caption ("caratulado") | `_s` |
| `fec_sentencia_sup_dt` | Sentence date | `_dt` = date |
| `gls_juz_s` | Court ("juzgado") | `_s` |
| `gls_materia_s` | Subject matter | `_s` |
| `gls_juez_ss` | Judge(s) | `_ss` = string, multi-valued |

### Section behaviour flags of interest

| Flag | Effect |
|------|--------|
| `tipo_instancia_principal` | Drives which instance tab is active — **a second axis** beyond `id_buscador` (e.g. `Salud_CS` = `corte_suprema`, `Cobranza` = `cobranza`) |
| `numero_resultados_pagina` | Allowed page sizes, dash-joined |
| `mostrar_*` | Gates which detail panels render — must be honoured when parsing the detail DOM |
| `ws_N_visible` / `ws_N_etiqueta_pestanna` | Workflow-stage tabs (Primera Instancia / Corte de Apelaciones / Corte Suprema) |
| `busqueda_hibrida` | Hybrid (keyword + vector) search toggle |
| `buscador_lineas_jurisprudenciales` | Line-jurisprudence mode (= `es_lj`) |

---

## 7. Results & Document Retrieval

### 7.1 Result rows in the DOM

Results are **not** consumed as JSON by the current scraper — they are read
from the rendered DOM:

```html
<element data-idsentencia="<id>">
  ROL: C-1944-2025
  Caratulado: MONSALVE/…
  Fecha: 15-05-2026
  Tribunal: 1º Juzgado de Letras de Osorno
  Materia: PERJUICIOS, INDEMNIZACIÓN DE
  Juez(a): Raul Fredy Ramírez López
  …
  <button>Ver sentencia</button>
</element>
```

- **Stable hook:** the `data-idsentencia` attribute — this is the sentence ID.
- **Detail trigger:** the `Ver sentencia` button inside the row.
- Text is parsed with regex in `chile_scraper.py::_parse_chile_text_result`.

### 7.2 Download flow (as implemented)

`chile_scraper.py::download_inteiro_teor_url` does **not** fetch a document URL.
It re-drives the browser:

1. Navigate back to the section page (`/busqueda?<slug>`).
2. Re-run the search with the original `search_terms` to repopulate the results.
3. Locate the row whose `data-idsentencia` matches, click **`Ver sentencia`**.
4. Wait, then persist `driver.page_source` as **`.html`** (no PDF download).
5. Click **`Volver a la página de búsqueda`** to reset.
6. Write a `.metadata.json` sidecar via `_shared.chrome_driver.write_sidecar_metadata`.

> **This is O(n) re-search per document** — very slow and F5-risky. See §10 for
> the recommended improvement (capture the detail endpoint response instead).

### 7.3 Statistics endpoint (working reference)

```
GET /busqueda/estadisticas_visitas_y_busquedas?id_buscador=328
→ "<code>\t{\"busquedas\": <int>, \"visitas_totales\": <int>}"
```

Client helper (`panel_busqueda.js`):

```js
llamada_ajax(url_estadisticas_visitas_y_busquedas + "?id_buscador=" + id_buscador_activo,
             null, function_success, null, "get");
```

---

## 8. Field Mapping → Project Result Schema

Matches the shape produced today by `_parse_chile_text_result`
(see `docs/ingestion_schema.md`):

| Project field | Pjud source | Status |
|---------------|-------------|--------|
| `tribunal` | `"CL"` | ✅ present |
| `tribunal_pais` | `"CHILE"` | ✅ present |
| `rol` | `ROL: …` from row text | ✅ present |
| `id_sentencia` | `data-idsentencia` attribute | ✅ present |
| `caratulado` | `Caratulado: …` | ✅ present |
| `fecha` | `Fecha: dd-mm-yyyy` | ✅ present |
| `tribunal` (court name) | `Tribunal: …` | ✅ present |
| `materia` | `Materia: …` | ✅ present |
| `juez` | `Juez(a): …` | ✅ present |
| `texto_preview` | First 500 chars of row text | ✅ present |
| `url_detalle` | — | ⚠️ Currently hardcoded to `buscar_sentencias` (not a real deep link) |
| `categoria` | Set post-hoc in `get_inteiro_links` | ✅ present |
| `tribunal_pais` note | `"CHILE"` | ✅ present |
| `id_buscador` | §4 map | ❌ **missing — add it** |
| `instancia` | `parametros_buscador.tipo_instancia_principal` | ❌ **missing — add it** |
| `inteiro_url` | `/busqueda/documentos` or `/busqueda/imprimir` | ❌ **missing** |

---

## 9. Gap Analysis — `chile_scraper.py` vs. verified portal

Findings from reading the current implementation against the live contract.

| # | Finding | Severity | Fix |
|---|---------|----------|-----|
| 1 | `CHILE_CATEGORIES` entries have `slug`/`name`/`description` but **no `id_buscador`** | 🔴 High | Add the `id_buscador` field from §4 to every entry |
| 2 | Comment says "blocked by CSRF + **reCAPTCHA** server-side validation" | 🟡 Med | It is **F5 TAS**, not reCAPTCHA, that rejects the POST. Correct the comment so future work isn't misdirected |
| 3 | No F5-block detection | 🔴 High | A blocked response is **HTTP 200**; the scraper will silently parse the error page as "no results". Detect `rechazada` / `x-security-action` and raise/retry |
| 4 | `_navigate_to_category` uses `time.sleep(4)` and skips re-navigation when the category is unchanged | 🟡 Med | Sleep is a guess; the section change may need a fresh F5 clearance. Prefer explicit "config loaded" wait (`window.id_buscador_activo` matches expected id) |
| 5 | `_search_via_form_fallback` returns results only when `page == 0`; other pages fall through with no action | 🔴 High | Pagination is effectively broken — see #6 |
| 6 | `get_inteiro_links` loops `page` but `_search_page` never advances the offset; dedupe-by-`rol` prevents growth, so the loop spins to `max_pages` | 🔴 High | Implement real paging via `offset_paginacion` (or the DOM pager) and break when a page returns no *new* ids |
| 7 | `_categoria_actual` guard means switching category in one session may not reload the page | 🟡 Med | Verify `?<slug>` navigation actually re-fires; reset the guard after F5 recovery |
| 8 | `time.sleep(15)` after the search click | 🟡 Med | Long and fragile; poll for `[data-idsentencia]` count / loading overlay `.capa_carga` to disappear |
| 9 | Detail retrieval re-searches per document (§7.2) | 🟡 Med | Capture the `buscar_sentencias` detail response once and parse it — avoids N re-searches |
| 10 | `url_detalle` is set to the search endpoint, not a per-sentence URL | 🟡 Med | Populate from the `id_sentencia` + section so links are shareable |
| 11 | Documents saved as `.html` (page source) | 🟢 Low | Acceptable, but `/busqueda/imprimir` likely yields much cleaner text |
| 12 | `per_page` docstring says "10, 20, 50, 100, 250" | 🟢 Low | Config exposes `"10-20-50"`; 100/250 unverified |
| 13 | No handling of `Lineas_Jurisprudenciales` special mode (`es_lj`) | 🟡 Med | Add a distinct code path for `id_buscador=628` |
| 14 | `Salud_CS` maps to `tipo_instancia_principal = corte_suprema` | 🟢 Low | Correct — but means section ≠ instance; don't conflate them |

### Additional UI note

The portal shows a full-page overlay `#capa_carga`. If any background XHR is
blocked by F5, the overlay **never clears** and intercepts all clicks, making the
Buscar button unclickable. The current `execute_script("arguments[0].click()")`
approach sidesteps this — keep it, but detect the stuck overlay explicitly.

---

## 10. Recommended Scraper Improvements

Ordered by value:

1. **Add `id_buscador` to `CHILE_CATEGORIES`** (§4) and send it in the payload.
2. **Implement F5 detection + recovery.** On a blocked response:
   - log the support ID,
   - back off (exponential, starting ~30 s),
   - optionally surface a "manual CAPTCHA needed" state to the operator.
3. **Fix pagination** using `offset_paginacion` and `numero_filas_paginacion`,
   breaking on the first page that yields no new `data-idsentencia` values.
4. **Replace fixed sleeps** with polling predicates:
   - after navigation: `window.id_buscador_activo === expected`
   - after search: `#capa_carga` hidden **and** `[data-idsentencia]` count > 0
5. **Fetch the detail once** and cache the response, instead of re-searching per
   document in `download_inteiro_teor_url`.
6. **Prefer `/busqueda/imprimir`** for the stored artefact (cleaner than raw
   `page_source`), falling back to `page_source`.
7. **Populate `url_detalle`** from `id_sentencia` + section.
8. **Rate-limit section hopping.** F5 re-challenges after roughly 6 rapid
   navigations; insert meaningful spacing between section switches.
9. **Split out `Lineas_Jurisprudenciales`** into its own mode/facets.

---

## 11. Open Questions / Risks

1. 🔴 **`Compendio_Extranjería` (`?Compendio_Extranjer%C3%ADa`) `id_buscador`
   is unverified** — F5 blocked every attempt during recon. Recover it by
   loading the section in a clean browser session and reading
   `window.id_buscador_activo`.
2. 🔴 **No successful `buscar_sentencias` response body was ever captured.**
   All POSTs (UI-driven and `fetch()`) were F5-rejected with
   `x-security-action: 0800000200`, including immediately after a manual CAPTCHA
   solve. The response shape in §5 is therefore **inferred** from the request
   contract, the tab-delimited envelope (§3.5), and the DOM result structure
   (§7.1) — it must be confirmed from a working Chrome session.
3. 🟡 **`/lista_buscadores`** never loaded (F5). It may enumerate all sections and
   their ids in one request — high value if reachable.
4. 🟡 **reCAPTCHA v3 score is invisible.** A scraper can't know its score; low
   scores may be the reason POSTs are rejected. There is no way to "solve" v3 —
   the browser profile must look sufficiently human (real Chrome, persistent
   profile, plausible timing).
5. 🟡 **`/busqueda/webservices` is undocumented** — the name suggests a broader
   JSON API surface. Worth probing from a cleared session.
6. 🟡 **`analisis_s: "11"`** appears in every payload with no explanation; it may
   encode the analysis/facet mode. Do not change it blindly.
7. 🟢 **Account-gated endpoints** (`sentencias_guardadas`,
   `mail_compartir_sentencia`) are out of scope for scraping.
8. 🟢 **Detail-panel gating** — `mostrar_*` flags vary per section, so detail
   parsing must be tolerant of missing panels.
9. 🟢 **Date format** — rows show `dd-mm-yyyy`; normalize to ISO before indexing.

---

## 12. Verification Log

Facts verified **live against production on 2026-09-13**.

| Item | Method | Result |
|------|--------|--------|
| Portal reachable | Browser navigation after manual F5 CAPTCHA solve | ✅ Loaded, title "Buscador Unificado de Fallos del Poder Judicial" |
| F5 protection present | `bobcmn` inline script, `TSPD_101`, `/TSPD/<hash>?type=5` image challenge | ✅ Confirmed |
| F5 on POST | `POST /busqueda/buscar_sentencias` → `x-security-action: 0800000200`, body "La URL solicitada ha sido rechazada" | ✅ Reproduced 3× |
| Endpoint map | Inline `var url_*` block on `/busqueda?Civiles` | ✅ Extracted (§3) |
| `parametros_buscador` | `window.parametros_buscador` on `/busqueda?Civiles` | ✅ Captured (§6) |
| Section → id map | `window.id_buscador_activo` per section, navigated with delays | ✅ 10 of 11 (§4) |
| `Lineas_Jurisprudenciales` mode | `window.es_lj === true`, `buscador_lineas_jurisprudenciales: true` | ✅ Confirmed |
| Search payload | Playwright network capture of the UI-triggered XHR | ✅ Full multipart body (§5.1, §5.2) |
| Search response | — | ❌ Never obtained (F5) |
| `estadisticas_visitas_y_busquedas` | `/busqueda/estadisticas_visitas_y_busquedas?id_buscador=328` | ✅ Tab-delimited envelope confirmed |
| `baremo.pjud.cl`, `api.pjud.cl` | Direct HTTP request | ✅ Not F5-protected |
| OmniBox programmatic set | `input`/`change` dispatch → request still sent `valores: [""]` | ⚠️ Must use real keystrokes |

### Reverse-engineering obstacles encountered

| Attempt | Outcome |
|---------|---------|
| Plain `curl` + browser UA | F5 JS challenge |
| Playwright + `navigator.webdriver` override + stealth init script | F5 JS challenge |
| `r.jina.ai` reader proxy | Connection reset / F5 rejection page with support ID |
| Playwright `page.request.get` / `ctx.clearCookies` | `Protocol error (Storage.getCookies): Method not found` — unusable |
| Same-origin `fetch()` from page context | GET returns F5 challenge page; POST returns rejection |
| Rapid iteration over 12 section URLs | F5 re-challenged after ~6 navigations |
| Manual CAPTCHA solve, then navigate | ✅ 3 more sections resolved before re-challenge |

**Working techniques (keep):**

- Solve the F5 image CAPTCHA manually in the browser, then use the session
  immediately with **spaced-out** navigations.
- Read portal config from `window.id_buscador_activo` / `window.parametros_buscador`
  via `page.evaluate()`.
- Use `page.evaluate(async () => { return await (await fetch(url)).text() })`
  for same-origin assets (regular `page.request` is broken in this environment).

---

## 13. Reference — SPA Source Snippets

### 13.1 Section config (inline script, `/busqueda?Civiles`)

```js
var flg_version_movil = 0;
var id_buscador_activo = 328;
var parametros_buscador = JSON.parse('{"id_buscador":"328","nombre_buscador":"Civiles",…}');
var es_lj = false;
```

### 13.2 Statistics helper (`panel_busqueda.js`)

```js
llamada_ajax(url_estadisticas_visitas_y_busquedas + "?id_buscador=" + id_buscador_activo,
             null, function_success, null, "get");
// success: data = response.split("\t"); data[0] === "0" → JSON.parse(data[1])
```

### 13.3 Omnibox input (rendered HTML)

```html
<input placeholder="Ingrese texto libre de búsqueda"
       type="text" id="tb_input_omnibox"
       oninput="debounced_cargar_opciones_omnibox()"
       onclick="mostrar_capa_opciones_disponibles_omnibox()"
       onkeydown="if(event.key === 'Enter') btn_buscar_componente_busqueda_avanzada_click()"
       autocomplete="off">
```

### 13.4 Search button (rendered HTML)

```html
<button type="button" title="Buscar"
        class="btn pull-right btn-primary btn_buscar"
        onclick="btn_buscar_componente_busqueda_avanzada_click()">…</button>
```

### 13.5 JS components loaded on the search page

| File | Size |
|------|------|
| `/general/js/app.js` | — |
| `/buscador/js/funciones_generales.js?v202210051334` | 11,715 B |
| `/buscador/js/componentes/busqueda/panel_busqueda.js?v=202010081433` | 3,847 B |
| `/buscador/js/componentes/busqueda/busqueda_avanzada.js?v=202010081436` | 6,217 B |
| `/buscador/js/componentes/busqueda/omnibox.js?v=202011190936` | 7,928 B |
| `/buscador/js/componentes/busqueda/suggester.js?v=202010081432` | 2,122 B |
| `/buscador/js/componentes/busqueda/arbol_indice_tematico.js` | 12,469 B |
| `/buscador/js/componentes/busqueda/busqueda_avanzada_panel_faceta__arbol_fechas.js` | — |
| `/buscador/js/componentes/busqueda/busqueda_avanzada_panel_faceta__arbol_normas.js` | — |
| `/buscador/js/componentes/busqueda/busqueda_avanzada_panel_faceta__componente_facetas_seleccionadas.js` | — |
| `/buscador/js/lib/mapas/highmaps.js` | — |

### 13.6 Related (protected) Chilean sources

| Source | URL | Status |
|--------|-----|--------|
| Derechos Humanos | `busddhh.pjud.cl` | F5-protected — **not documented yet** |
| Baremo Jurisprudencial | `baremo.pjud.cl/BAREMOWEB/` | ✅ Reachable, real content |
| API root | `api.pjud.cl` | ✅ Reachable (placeholder text only) |
| Tribunal Constitucional | `buscador.tcchile.cl` | ✅ Documented — see `docs/tc-chile-source.md` |
