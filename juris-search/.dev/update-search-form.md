# Search Date Range — TJSP (Phases 1–3)

> **Scope of this document:** TJSP only. Every other court is listed under
> [Out of scope](#out-of-scope--follow-ups) and is **not touched** by phases 1–3.
>
> **Definition of done:** the user can type *Data de Julgamento — Início / Fim*
> in the search form, the values reach `TJSPJurisprudenciaScraper`, and TJSP's
> CJSG search returns only decisions inside that window.

---

## 0. Key finding — the TJSP scraper needs **zero** changes

`tjsp_scraper.py` is already wired end-to-end for date filtering. The dates simply
never arrive, because they are dropped in two earlier layers.

| Piece | Location | Status |
| --- | --- | --- |
| `SearchCriteria.data_julgamento_inicio/fim` | `tjsp_scraper.py:62-63` | ✅ exists |
| `SearchCriteria.data_publicacao_inicio/fim` | `tjsp_scraper.py:64-65` | ✅ exists |
| `search_with_criteria()` → `filters` dict | `tjsp_scraper.py:493-499` | ✅ forwards dates |
| `filters` → POST body | `tjsp_scraper.py:334` — `_build_search_form_data(query, filters)` | ✅ |
| ISO → `DD/MM/AAAA` conversion | `_format_date_for_tjsp()` at `tjsp_scraper.py:117` | ✅ |
| Actual form inputs | `dados.dtJulgamentoInicio` / `dados.dtJulgamentoFim`, `dados.dtPublicacaoInicio` / `dados.dtPublicacaoFim` | ✅ |
| `SearchFields` (Pydantic) declares dates | `modules/models.py` | ❌ **missing** |
| `_USER_FIELD_KEYS` collects dates | `modules/routes_search.py:47` | ❌ **missing** |
| `FIELDS` / `DEFAULT_FIELDS` render dates | `tjrs-frontend/src/App.jsx:149,162` | ❌ **missing** |

**Where the values die today:** `modules/models.py::SearchFields` has no date
fields, so Pydantic silently discards them on `POST /api/search`; even if they
survived, `_USER_FIELD_KEYS` never collects them, so `_build_criteria_args()`
passes the dataclass defaults (`None`).

### Two corrections to the earlier draft

1. **Do not introduce `data_inicio` / `data_fim`.** Reuse the field names the
   dataclasses already declare: `data_julgamento_inicio` / `data_julgamento_fim`.
   Using the existing names is what makes phases 1–3 a pure plumbing change.
2. **The e-SAJ form keys are not `dtJulgIni` / `dtJulgFim`.** They are
   `dados.dtJulgamentoInicio` / `dados.dtJulgamentoFim` (+ the `dtPublicacao*`
   pair) — and that mapping is already implemented, so there is nothing to build.

### v1 decision

Expose **Data de Julgamento** only. Data de Publicação is already supported
inside the scraper; we just don't surface it yet (see follow-ups).

---

## Phase 1 — Backend plumbing

- [x] **1.1** `modules/models.py` — declare the fields
- [x] **1.2** `modules/routes_search.py` — collect the fields
- [x] **1.3** `modules/system_prompt.py` — let the chat assistant populate them

### 1.1 `modules/models.py`

In `SearchFields`, immediately after `tipo_decisao`:

```python
    tipo_decisao: Optional[str] = None
    data_julgamento_inicio: Optional[str] = None  # ISO "YYYY-MM-DD"
    data_julgamento_fim: Optional[str] = None     # ISO "YYYY-MM-DD"
    tribunal: Optional[str] = None
```

### 1.2 `modules/routes_search.py`

Add to `_USER_FIELD_KEYS`:

```python
    "data_julgamento_inicio",
    "data_julgamento_fim",
```

Add to `_BRAZIL_FIELD_MAP`:

```python
    "data_julgamento_inicio": "data_julgamento_inicio",
    "data_julgamento_fim": "data_julgamento_fim",
```

**Why this cannot break other courts:** `_build_criteria_args()` intersects the
mapped names with `dc_fields(SearchCriteria)`, so a court whose dataclass does not
declare these fields silently ignores them. No court needs to be touched to keep
working.

### 1.3 `modules/system_prompt.py`

In the Brazil `<search_fields>` example block (`_build_brazil_system_prompt`), add
after `tipo_decisao` so the assistant can suggest dates:

```
  "data_julgamento_inicio": "AAAA-MM-DD (ou null)",
  "data_julgamento_fim": "AAAA-MM-DD (ou null)",
```

---

## Phase 2 — Frontend

All edits in one file: `tjrs-frontend/src/App.jsx`.

- [x] **2a** add two entries to `FIELDS`
- [x] **2b** add the two keys to `DEFAULT_FIELDS`
- [x] **2c** guard against an inverted range in `runSearch`
- [x] **2d** `npm run build`

### 2a. `FIELDS` — insert after the `tipo_decisao` entry

```js
  { key: "tipo_decisao", label: "Tipo de Decisão", placeholder: "Acórdão, Monocrática..." },
  { key: "data_julgamento_inicio", label: "Data de Julgamento — Início", type: "date" },
  { key: "data_julgamento_fim", label: "Data de Julgamento — Fim", type: "date" },
  { key: "search_index", label: "Buscar em", placeholder: "acórdão / inteiro_teor" },
```

No renderer change is needed: the input at `App.jsx:966` already forwards `f.type`,
and its `onChange` falls back to `e.target.value` for non-`number` types.

### 2b. `DEFAULT_FIELDS`

```js
const DEFAULT_FIELDS = {
  search_text: "", tipo_processo: "", classe_cnj: "", assunto_cnj: "",
  comarca_origem: "", relator: "", orgao_julgador: "", tipo_decisao: "",
  data_julgamento_inicio: "", data_julgamento_fim: "",
  tribunal: "", search_index: "acórdão", max_results: 20,
};
```

This is **required** for 1.3: `parseSearchFields` only accepts suggested keys that
already exist in `DEFAULT_FIELDS` (`if (... && k in DEFAULT_FIELDS)`), so without
this the assistant's dates would be discarded.

### 2c. `runSearch` — normalize an inverted range

`<input type="date">` yields `YYYY-MM-DD`, so a string compare is valid:

```js
  const runSearch = async () => {
    if (!fields.search_text && !Object.values(fields).some((v) => v)) return;

    let di = fields.data_julgamento_inicio;
    let df = fields.data_julgamento_fim;
    if (di && df && di > df) { [di, df] = [df, di]; }
    const searchPayload = { ...fields, data_julgamento_inicio: di, data_julgamento_fim: df };
    // ...send searchPayload instead of ...fields in the /api/search body
```

Swapping silently is the least surprising behaviour; if we prefer, reject with an
inline message instead.

### 2d. Rebuild

```bash
cd tjrs-frontend && npm run build
```

---

## Phase 3 — Validate against live TJSP

- [x] **3.1** *Baseline* — search `dano moral`, no dates, note total.
- [x] **3.2** *Narrow window* — same term, `2024-01-01` → `2024-03-31`.
- [x] **3.3** *Old window* — `2001-01-01` → `2001-01-31`.
- [x] **3.4** *Payload trace* — a gated `logger.info` in `_build_search_form_data()`
      logs the `DD/MM/AAAA` values **only when a window is applied**, so it is silent
      on normal searches. Kept as a cheap debugging aid:
      `TJSP form dates: julgamento 01/01/2024 .. 31/03/2024`
- [x] **3.5** *Production path* — ran `search_with_criteria()` exactly as
      `_run_scraper` does, via `.dev/validate_tjsp_e2e.py`.
- [ ] **3.6** *Persistence* — confirm the saved file in `searches_history/` includes
      both date keys under `fields`. **Requires the backend to be restarted** (see below).
- [ ] **3.7** *Inverted range* — covered by the 2c guard; confirm interactively.
- [ ] **3.8** *Regression* — a date-less search still behaves as before 2a.
- [ ] **3.9** *Cross-court sanity* — run the 3.2 window against TJRS and confirm it
      still returns results (dates ignored, no crash).

### Results

Reported totals from the live TJSP site (`.fundocinza1` pages), query `dano moral`:

| Scenario | Reported total | Page-1 judgement dates | In window? |
| --- | --- | --- | --- |
| no window | **2,657,027** | Aug–Sep 2026 | n/a |
| `2024-01-01 → 2024-03-31` | **50,268** | Feb–Mar 2024 | ✅ all inside |
| `2001-01-01 → 2001-01-31` | **240** | Jan 2001 | ✅ all inside |

End-to-end via the production path (`.dev/validate_tjsp_e2e.py`, `max_results=20`):

```
3.1 no window      -> n=20  span 05/09/2026 .. 29/08/2026   (outside 2024 window)
3.2 2024-01-01..   -> n=20  span 01/02/2024 .. 27/03/2024   all inside window: True
3.3 2001-01-01..   -> n=20  span 04/01/2001 .. 31/01/2001   all inside window: True
```

**Verdict: PASS.** A 4-order-of-magnitude total drop (2.65M → 50k → 240), and every
returned decision's `data_julgamento` falls inside the requested window.

---

## Phase 3b — Blocker found and fixed: the TJSP form never submitted

Phase 3 initially returned **0 results for every scenario, including the no-date
baseline** — so the scraper was broken independently of this feature.

**Root cause.** `get_inteiro_links()` clicked the `Pesquisar` button and treated a
non-throwing click as success:

```python
btn.click()
submitted = True          # ← click "succeeded"…
if not submitted: …       # ← …so this JS fallback never ran
```

But TJSP's form declares:

```html
onsubmit="return applySubmit(this, … spwSubmit(this, event);))"
```

`spwSubmit` → `BENV_isCamposValidos(t)` can return `false`, which **cancels the POST
without raising an exception**. The page silently stayed on the search form, so the
results wait timed out and the scraper returned `[]`. `document.forms[0].submit()`
bypasses `onsubmit` and always posts — which is why it worked.

**Fix (in `tjsp_scraper.py`).** New `_submit_search_form()` clicks, then verifies the
results area actually rendered (`_search_results_rendered()`), and only falls back to
`document.forms[0].submit()` if it did not. This keeps the click path for the normal
case while making the JS submit a *verified* fallback rather than dead code.

This bug blocked **all** TJSP searching, not just dates — worth confirming it explains
any previously-reported "TJSP returns nothing" behaviour.

---

## Blocker for API-level verification

The running backend (`localhost:8000`, PID from `lsof -iTCP:8000`) was started
**before** these edits; `/openapi.json` still lacks the date properties, so
`POST /api/search` drops them. **Restart the API** to validate 3.6–3.9 through HTTP:

```bash
./stop.sh && ./start.sh     # or kill the PID and re-run python api.py
```

Then confirm:

```bash
curl -s localhost:8000/openapi.json | grep -c data_julgamento_inicio   # expect: 1
```


---

## Risks

- **Silent no-ops elsewhere.** Courts that declare the fields but ignore them
  (TJRS, TJMG, TJRJ, CL) will return unfiltered results with no error. Multi-court
  searches mixing TJSP + TJRS therefore become inconsistent. Mitigation: phase 4
  adds a `supports_dates` capability flag so the UI can disable/annotate
  unsupported courts. Not in scope for 1–3.
- **`data_julgamento` vs `data_publicacao`.** TJSP's CJSG also has
  `dados.dtRegistroInicio/Fim`, which we leave empty. Two date pairs shown at once
  would be confusing, hence the v1 "julgamento only" decision.
- **Selenium clicks are not proof of submission.** See phase 3b. The same
  "click-doesn't-throw ⇒ assume success" assumption may exist in other scrapers'
  submit paths; worth auditing the others when they are next touched.
- **A stale API process silently discards new fields.** Pydantic ignores unknown
  keys, so an un-restarted server looks like a working no-op. Always restart after
  changing `SearchFields`.

---

## Out of scope — follow-ups

Wiring is **not** uniform across courts, so each needs its own work:

| Court | State of date filtering | Work needed |
| --- | --- | --- |
| **TJSP** | ✅ fully wired + validated (phase 3) | none — done |
| e-SAJ courts (TJCE, TJMS, TJAC, …23 total) | ✅ fully wired in `_shared/esaj_scraper.py` | none — they inherit phase 1 for free |
| STF | ✅ wired in `stf_scraper.py` | none — inherits phase 1 |
| TJRS | ⚠️ declares fields, never uses them; `_semantic_filters_to_terms()` folds filters into free-text `q` | find the portal's real date params (e.g. `_build_search_url`) |
| TJMG | ⚠️ declares + forwards, but `get_inteiro_links()` is a skeleton that never reads `filters` | portal inspection + implement |
| TJRJ | ⚠️ same as TJMG | portal inspection + implement |
| CL (Chile) | ⚠️ `fecha_inicio/fecha_fin` forwarded, but `_search_via_form_fallback()` ignores `filters` | wire the date widgets in the SPA form |
| **Phase 5 — interval crawler** | — | build only after 3 passes |

The crawler design from the earlier draft is still sound, but it must consume the
**existing** names (`data_julgamento_inicio/fim`), not the draft's `data_inicio/fim`:

```jsonc
{
  "job_id": "…",
  "fields": { /* saved search, minus dates */ },
  "data_fim_initial": "2026-09-13",  // "today" at creation
  "data_floor":       "2015-01-01",  // hard stop walking back
  "window_days":      30,
  "cursor":           "2026-09-13",  // newest edge not yet processed
  "status":           "idle"         // idle | running | paused | exhausted
}
```

Each tick runs the saved `fields` with `data_julgamento_inicio = cursor − window_days`
and `data_julgamento_fim = cursor`, downloads/ingests, then sets `cursor = data_julgamento_inicio`.
When `cursor <= data_floor` it flips to `exhausted`; pause/resume is just a status flag.

---

## Order of execution

1. ~~Phase 1 (1.1 → 1.3) — backend accepts and forwards dates.~~ ✅ done
2. ~~Phase 2 (2a → 2d) — dates appear in the form; rebuild.~~ ✅ done
3. ~~Phase 3 — validate on live TJSP, fill in the results table.~~ ✅ done
   (plus 3b: the pre-existing submit bug found and fixed)
4. **Remaining:** restart the API, then 3.6–3.9 over HTTP.
5. Only then: decide between per-court wiring (phase 4) and the interval crawler (phase 5).

---

## Files touched

| File | Change |
| --- | --- |
| `modules/models.py` | `SearchFields` gains the three date/`search_index` fields |
| `modules/routes_search.py` | field map + `_USER_FIELD_KEYS` collect them |
| `modules/system_prompt.py` | assistant prompt documents the date fields |
| `tjrs-frontend/src/App.jsx` | two date inputs, `DEFAULT_FIELDS`, inverted-range guard |
| `tjsp_scraper.py` | **bug fix only** — `_submit_search_form()` + `_search_results_rendered()`; no date wiring was needed |
| `.dev/validate_tjsp_e2e.py` | reusable live regression harness (production path) |

No changes were made to any other court's scraper.