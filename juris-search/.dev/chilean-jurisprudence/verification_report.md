# chile_scraper.py — Verification Report

Date: 2026-09-17
Operator / session: fresh headful Chrome 152 (Selenium Manager), macOS; one fresh profile per probe, no reused session
Pinned artifact: chile_scraper.py @ sha1:`53a163d543ecb4de425988d2f92d0233e5e4bef7`
Pinned artifact observed: `53a163d543ecb4de425988d2f92d0233e5e4bef7` (`git hash-object juris-search/chile_scraper.py` — the working-tree blob, which is what step 0.1's freshness gate tests; `git rev-parse HEAD:…` reports the committed blob and will drift on any commit made after the run)
Playbook: `.dev/chilean-jurisprudence/02-chile_scraper-playbook.md` @ sha256:`f8784bcc6e95cde6db18504587e73b637ba712bd2829015d159314dfe1e31c60`

> The pin was **refreshed during this pass**, from `d46f896dadaacb2b5479420229f547938d688640` to `53a163d5…`. The blob moved because step 6 produced a concrete reproducible failure that forced the `_click_next_page` selector fix (see *Changes made*). The blob delta between the two pins is exactly one hunk, `+16/-1`, and contains only that fix — verified with `git diff d46f896d… 53a163d5…`.

```
verdict: red — 1 blocking defect (pagination), 10 secondary issues
```

> **Blocking:** open issue 9 (pagination). **Phase A resolved the disambiguation: issue 11 is a red herring for this symptom (mechanism `B-2`), the selector-scoping fix B-1 is a no-op, and the freshness predicate is probably *not* the defect. Step 6 must be re-run with `max_results` recorded before any fix is designed** — see *Phase A probe* under Evidence.
> **Secondary:** page-size control, filter surface, Spanish-only support-ID, body-only F5 detector, `imprimir` unprobed, `Compendio` id, LJ mode, Case A3, pager markup docs, node-per-result scoping.
> **Blocked by the blocking defect:** step 7 (`_open_detail` untested), step 8 search half (`penales` search untested).

## Amendments applied (this playbook revision)

| ID | Section | Change |
|----|---------|--------|
| D1 | §0.1 | freshness gate: `grep -q` (>=1 match) instead of "one hit each" — the old form caused a false STOP |
| D2 | §4 | replaced the false `quote(slug, safe="")` diagnosis with the three real causes; added the URL-encoding note |
| D3 | §5, §5.5, §6 | recalibrated to the portal's 10-row default; split page/len criteria; added step 5.5 (inert filter surface) |
| H1 | §2, §3 | added tests 2e/2f (TSPD image, body-less F5); split Case A into A1/A2 |
| H2 | §7 | replaced unreachable size/body criteria with a no-file-on-failure check |
| D4 | §5, §8 | added **P1/P2 provenance criteria** — `_navigate_to_category` can land on a page that already contains a default listing, so a green "10 rows" result can be landing data. Added the landing-vs-after snapshot script |
| D5 | §3, §5.5 | added **Case A3** — F5 rejection delivered inside the search `POST` XHR body (HTTP 200, `page_source` clean). Detection recipe + the observation that it invalidates steps 5–8 |
| D6 | §6, §7, §8 | recorded the **real pager markup** (Bootstrap 4, `#btnPaginador_pagina_adelante`) replacing the wrong DataTables guidance; corrected step 6's failure table; added Case-A3 preconditions to §7/§8 |
| **D4b** | §5 | recorded the **measured** landing behaviour: the default listing renders **~1.1 s late** (so an empty snapshot is a false negative, and a non-empty `#span_cantidad_resultados` is *not* proof of freshness); `[data-idsentencia]` matches **~70 nodes for 10 unique ids** |
| **D7** | §6 (sub-step 6a) | recorded the **measured post-fix pager state**: `_click_next_page() -> True` and cursor `0 -> 1`, but rows are cleared on click and the true count lands at **~1.8 s** while the loop sleeps only `0.5 s` — turning step 6's "Known gap" row into a confirmed finding |
| re-pin | header | **`d46f896d…` → `53a163d5…`**: step 6 forced the pager selector fix; the pinned blob moved by design |
| minor | §0.5, §4, §10, §11 | `mkdir -p workspace/CL_jurisprudencia`; in-loop assertion; §11.N → §11 item N |

## Summary

| Step | Result | Notes |
|------|--------|-------|
| 0.1 Freshness gate | **PASS** | `freshness OK`; observed == declared == `53a163d5…` |
| 0.3 Driver smoke | **PASS** | `Example Domain` on a throwaway profile |
| 0.5 Workspace | **PASS** | `workspace/CL_jurisprudencia` created; 0 pre-existing entries |
| 1 Static | **PASS** | 1a–1e (13/13 offline assertions green) |
| 2 F5 unit | **PASS** | incl. 2e (TSPD image → detected, `support_id=None`) and 2f (body-less → `False`) |
| 3 F5 live | **Case B (through)** | `_is_f5_block=False`, `support_id=None`, `title="Buscador Unificado de Fallos del Poder Judicial"`, `window.id_buscador_activo=328`. **Case A3 did not reproduce in the fresh session** — see *Evidence* |
| 4 Section map | **PASS** | `civiles 328/328`, `penales 268/268`, `corte_suprema 528/528`; all `live == expected`, no F5 |
| 5 Search | **PASS** | **P1/P2 first**: landing `n=0`, `cantidad=""` → after `n=70` DOM nodes (**10 unique ids**), `Se ha(n) encontrado 14.733 resultados.`, first id `200791923`, omnibox holds the query. Then `n=10`, `id_buscador=328` on every row, `instancia="civil"`, `categoria="civiles"`, `page=1`, `empty_rols=0`, ROLs well-formed (`C-5810-2025`, `C-12950-2025`, `C-953-2026`, …) |
| 5.5 Filter surface | **OBSERVED** | **Filter NOT sent** — omnibox only, no `tribunal` key. **XHR verdict: `through`** (4 search POSTs, all HTTP 200 with real JSON, no F5 body) |
| 6 Pagination | **FAIL** | `pages == [1]`, `total == 10` against ~15,800 matches. The **selector fix itself is confirmed working** (`_click_next_page() -> True`, cursor `0 -> 1`, first row changed); the loop still stops after page 1 — see *Open issue 9* |
| 7 Detail + download | **NOT RUN** | Step 6 failed, so no result had `page >= 2`. The step's recipe falls back to `results[-1]`, which was a page-1 row; running against it would exercise `download_inteiro_teor_url` but **not** the page-targeting fix that was the point of this step — a page-1 target cannot distinguish a correct `_open_detail` from one that always lands on page 1. Reported NOT RUN rather than PASS/FAIL to avoid recording a vacuous green. `_open_detail`'s page-targeting behaviour remains untested. No file was written to `/tmp/cl_test`, which is consistent with `download_inteiro_teor_url` not being called, not with a download failure. |
| 8 Second section | **BLOCKED** | `RuntimeError: F5 block detected while loading penales` / `… salud_cs` — F5 on **navigation** (Case A2), caught correctly by `_is_f5_block` |
| 8b `salud_cs` | **BLOCKED** | Same F5 navigation block |
| 9 LJ mode | **PASS** | `_navigate_to_category` returned `628`; `window.es_lj === true` (literal `true`); `window.id_buscador_activo=628`; no F5. `es_lj` is still **not** branched on in `get_inteiro_links` (open issue 7) |
| 10 Compendio negative | **PASS** | Live: `ValueError: Categoría 'compendio_extranjeria' has no verified id_buscador. See docs/pjud-source.md §11 item 1.` — both required doc references present |

**Count: 9 PASS, 1 FAIL, 1 NOT RUN, 2 BLOCKED.**

> **Arithmetic note (added with patch 1).** 15 rows total. `3 F5 live` = Case B and `5.5` = OBSERVED are not pass/fail categories, leaving 13 classified. PASS rows are 0.1, 0.3, 0.5, 1, 2, 4, 5, 9, 10 — **nine**, not eight; the pre-patch `8 PASS` undercounted. Step 7 moved `BLOCKED` → `NOT RUN` per patch 1, so `BLOCKED` drops to 2 (steps 8, 8b).

> **Note on step 5 across sessions.** In the *first* re-run (before the pager fix, task-relevant background only) step 5 reported 8/8 criteria green on rows that were later shown to be the landing page's default listing — an **invalidated false pass**, which is what motivated amendment D4. In *this* run step 5 passed legitimately: the landing snapshot was empty (`n=0`) and the row set materially changed (`null → 200791923`) with the count text going from `""` to `14.733 resultados`.

## Changes made

- `chile_scraper.py` L406–L425 (`_click_next_page`): the verified Bootstrap 4 control `#btnPaginador_pagina_adelante` (plus its anchored form) was added **first** in the selector tuple, and the docstring now records the verified markup, the JS page cursor it moves, and that the markup is absent from `docs/pjud-source.md §7.1`. The pre-existing DataTables selectors were kept as fallbacks for `/busqueda/imprimir`, which is unprobed. **Justified by step 6 (and sub-step 6a)**, per the work order's escape clause: step 6 produced `pages == [1]`, `total == 10`, and `_click_next_page() -> False` while `#btnPaginador_pagina_adelante` was present (`displayed=True`, `enabled=True`) and clicking it moved `pagina_resultados_busqueda_sentencias` from `0` to `1`. No other hunk in the file.

## Open issues / follow-ups

1. Page-size control is **not wired up** — `resultados_por_pagina` is arithmetic-only; the portal default (10) applies.
2. Advanced-search filters (`tribunal`, `juez`, `materia`, `rol`, dates) **never reach the portal** — `_run_search_ui` only fills the omnibox. Confirmed live in step 5.5.
3. `_extract_support_id` is **Spanish-only**; an English/marker-only rejection yields `None`. Observed live in step 8: `_is_f5_block` was `True` while `support_id` was `n/a`.
4. `_is_f5_block` is **body-only**; header-only rejections (`x-security-action`) are undetected.
5. `/busqueda/imprimir` is unprobed as an alternative artefact source.
6. `Compendio_Extranjería` `id_buscador` is **still unverified**.
7. `Lineas_Jurisprudenciales` special mode is **not implemented** — `window.es_lj` is confirmed `true` live, but `get_inteiro_links` never branches on `es_lj`. A `NotImplementedError` guard is still recommended.
8. **F5 rejections delivered inside an XHR body are undetectable** (Case A3). *Not observed in this pass* — the search POSTs returned real JSON — but the route is documented as the most aggressively filtered one (`docs/pjud-source.md` §5.3), and when it triggers, `_assert_not_blocked` cannot see it and `get_inteiro_links` returns stale landing data as results.
9. **The search loop has no freshness check — and work-order Phase A narrows the failure to a sub-25 ms race. Issue 11 is not involved.** *This supersedes the "CONFIRMED LIVE as the cause" framing introduced by patch 2, which the report's own step-6 evidence already contradicted.*
>
> **Outcome (unchanged):** `pages == [1]`, `total == 10`.
>
> **What the probes measured** (work-order Phase A, 2026-09-17, two independent fresh sessions, 0.1 s sampling; see *Phase A probe* under Evidence):
>
> | Reading | Measured |
> |---|---|
> | First sample after `_click_next_page()` | `n_all=0`, all 70 nodes gone — **t=0.022 s** (probe 2) / **t=0.027 s** (probe 1) |
> | Empty window | ≈ **[0.02 s, 2.09 s]** — 20 consecutive empty samples at 0.1 s |
> | Repopulated with the **next** page | **t=2.425 s**: 70 nodes, 10 unique, **all 10 ids replaced** (`delta=20`) |
> | Scoped vs unscoped selector | **70 vs 70 nodes** — scoping removes nothing |
>
> **Conclusion — a sub-25 ms *race*; issue 11 is not involved.** The clear lands within ~22 ms, which is *faster* than the ~2.0 s repopulation but **not** necessarily faster than `_wait_for_results`'s first predicate evaluation: `WebDriverWait` evaluates the predicate **immediately** and uses its 0.5 s interval only *between retries*. So the first evaluation can still see the pre-click rows, the predicate returns `True` at t≈0, and `_parse_search_results` then runs against either the old rows (all of which dedupe) or the ~2.0 s empty window (returning nothing). Either way `new_on_page == 0` and the loop takes its terminal branch. **The probes bound the *clear*; they do not order the predicate's first poll — so the race reading is supported, not refuted.**
>
> **What is definitively refuted is the *issue-11* mechanism.** All **70** nodes — the entire `[data-idsentencia]` population — disappear on click and stay gone for ~2.0 s, so **no node carrying the attribute survives the click** to satisfy the predicate. Issue 11 is therefore not the cause of the symptom, and the fix is not "scope the selector": scoping is a measured no-op. Per the work order's A.2 decision table this is branch **B-2**; the operative sub-case is the race, not the "stale rows" wording the work order supplies for it.
>
> **Two independent defects — work-order B-2 fixes only the first.**
>
> 1. **Readiness must be a row-*change* predicate, not existence** (work-order B-2). Requiring the live set to be non-empty **and** different from `previous_ids` makes the t≈0 evaluation fail, which closes the ~2.0 s empty window and the race at the same time. **This is the fix — for a different reason than B-2 states.**
> 2. **`new_on_page == 0` must not be terminal.** It conflates "the parse landed in the ~2.0 s empty window" with "the pager is exhausted". Even with B-2 applied, any transient empty parse permanently truncates the result set. This is a defect in `get_inteiro_links`, and no selector or predicate change addresses it.
>
> **The `max_results`-cap alternative is excluded.** The recorded step-6 call used `max_results=30, per_page=10`, so `max_pages == 5` and page 1's 10 entries do **not** satisfy the request — the loop must have reached its terminal `new_on_page == 0` branch. That removes the "step 6 was a mis-specified test" reading and leaves the race + terminal-break pair as the mechanism.
>
> **Required next step.** Re-run step 6 unchanged, recording `max_results` explicitly and logging `max_pages` / `len(entries)` / `new_on_page` per iteration, to confirm the terminal branch is what fires. Then apply work-order **B-2 and** relax the break in the same change, and re-run steps 5–8. Work-order **B-1 remains not applicable.**
>
> **Not fixed in this pass — reason is verification exhaustion, not scope.** `_wait_for_results` is **not** on the do-not-refactor list (`_parse_chile_text_result`, `_navigate_to_category`, `_click_next_page`, `_open_detail`), and step 6 produced a concrete reproducible failure — so the escape clause applies and a fix would have been in scope. It was not attempted for two reasons: (a) the session became F5-blocked immediately after step 6 (`RuntimeError: F5 block detected while loading penales`), so any fix would have been **unverifiable** in this pass; and (b) Phase A narrowed the mechanism to a sub-25 ms race between the click's DOM clear and the predicate's first poll, which is only observable with the instrumentation described above — so the fix, while clearly in scope, cannot be *shown* to close the observed failure until step 6 is re-run. **This remains the top follow-up: while the loop's page-1 exit stands, `max_results > 10` is unreachable in practice and a query silently returns one page.** The next pass should re-run step 6 with that instrumentation, then apply B-2 together with the non-terminal break, then re-run steps 5–8 in a fresh session.
10. **The pager markup is undocumented** in `docs/pjud-source.md` §7.1, which covers result rows only. The verified markup is recorded in playbook §6 sub-step 6a; it should be folded into the source notes.
11. **`[data-idsentencia]` is not one-node-per-result — but the composition is not what playbook 03 §4a reconstructs.** Measured live (work-order Phase A, 2026-09-17, fresh headful Chrome 152; see *Phase A probe* under Evidence): **70 nodes = 10 results × 7 nodes, all visible.** The ratio is exactly 7 and it is structural — measured anatomy of a single result:
>
> ```html
> <!-- one result's 7 nodes, in DOM order; all seven carry the SAME data-idsentencia -->
> <div    class="card border-info capa_elemento_lista_resultado_busqueda" data-idsentencia="200917190">
> <span   class="estilo_resultado_titulo" data-idsentencia="200917190">ROL: C-3662-2026</span>
> <span   class="estilo_resultado_titulo" data-idsentencia="200917190">Caratulado: BANCO DE CHILE/ORELLANA</span>
> <span   class="estilo_resultado_titulo" data-idsentencia="200917190">Fecha: 16-09-2026</span>
> <span   class="estilo_resultado_titulo" data-idsentencia="200917190">Tribunal: 1º Juzgado Civil de Puente Alto</span>
> <button class="btn btn-primary font-weight-bold" data-idsentencia="200917190">Ver sentencia</button>
> <form   class="" data-idsentencia="200917190"></form>
> ```
>
> The `div.card` **wraps** the other six (`childIds=['SPAN','SPAN','SPAN','SPAN','BUTTON','FORM']`), so the count is `1 + 6` per result. Measured histogram over all 70 nodes: `40× span.estilo_resultado_titulo`, `10× div.card.border-info.capa_elemento_lista_resultado_busqueda`, `10× button.btn.btn-primary.font-weight-bold`, `10× form`. **`is_displayed()` was `True` for all 70 — there are no hidden stubs.** (Classes are from the probe's anatomy dump; the `data-idsentencia` value shown, `200917190`, is the step-6 pre-click first id, which probe 1 independently reproduced as its first match.)
>
> **Correction to playbook 03 §4a.** The classes it supplies — `fila_resultado_busqueda_sentencias`, `contenedor_carga_resultado`, `celda_detalle_sentencia` — **do not exist in the live DOM**, and its claim that the attribute sits on "a visible row container, a hidden load stub, and per-cell wrappers" is not supported: the live set is one visible card plus its own visible descendants. The `hidden` stub is a reconstruction and must not be folded into the source notes.
>
> **Scoping is a no-op for this symptom — do not apply work-order B-1 as a pagination fix.** `#capa_resultados_busqueda_sentencias [data-idsentencia]` returned **70 nodes / 10 unique — identical to the unscoped selector.** The container holds all the cards and nothing else carrying the attribute, so scoping removes zero nodes.
>
> What survives is the original **efficiency** point: `_parse_search_results` runs its full regex set **7× per result** and `_open_detail`'s row loop iterates nested duplicates. That is a tidy-up (collapse to the `div.card` nodes, or dedupe on element identity), not a correctness fix — correct today only because of `seen_ids` dedupe and `_open_detail`'s early `id` mismatch `continue`. Fold the measured markup into `docs/pjud-source.md` §7.1.

## Evidence

- **blocked page excerpt** (step 8, navigation GET): raw body was not captured — the challenge cleared before a snapshot could be taken (probe 9 read `blocked: false`). What is on record is the detector firing inside `_navigate_to_category`: `RuntimeError: Chile: F5 block detected while loading penales. support_id=n/a. Manual CAPTCHA solve in a real browser may be required.` `support_id=n/a` with a positive body match is the live confirmation of open issue 3.
- **search XHR verdict**: `through` — with one correction and one explicit gap. The autocomplete body stands as recorded: `POST https://juris.pjud.cl/busqueda/busqueda_por_texto_autocompletable` → HTTP `200`, body head `0\t{"ministros":[],"descriptores":[],"lugares":[],"normas":[],"sugerencias":[]}`.
  - **The primary search endpoint POSTs a real multipart body.** Captured live via CDP `Network.requestWillBeSent` (Phase A): `POST https://juris.pjud.cl/busqueda/buscar_sentencias`, `type=XHR`, `postData` head `------WebKitFormBoundaryCqwDieLbFhpKVZBY\r\nContent-Disposition: form-data; name="_token"\r\n\r\nQBf5octe7u9gmYmhK3RwnbusLU8eSH5BF1bzWxyH…`. So the primary search is **not** a JSON POST — it is `multipart/form-data` carrying a Laravel `_token`. This supersedes playbook 03 §4b's illustrative JSON body, which is a reconstruction.
  - **The response body was NOT captured, and the report will not pretend otherwise.** `Network.getResponseBody` for that `requestId` failed with `No data found for resource with given identifier` (body already evicted), and a document-level `XMLHttpRequest.prototype.send` hook that *did* capture the autocomplete XHR never saw the `buscar_sentencias` XHR — consistent with it being issued outside the hooked document. Playbook 03 §4b's `0\t{"resultados":[…],"total":14733}` head is therefore **not reproducible and has not been substituted**.
  - **Stronger evidence than a body head, and first-hand:** the search then **rendered 70 result nodes / 10 unique ids**, and `_is_f5_block(page_source)` was `False`. An F5-rejected body cannot produce result cards, so **Case A3 did not reproduce in this session either** — and that argument does not depend on reading the response body.
  - **The F5 layer is separately visible on this exact path.** CDP logged three further `buscar_sentencias` requests of `type=Document` shaped `buscar_sentencias?onComplete=<nonce>&ajaxAction=0501010200&time=…`, all HTTP `200`, whose retrieved bodies are `<meta http-equiv="Pragma" content="no-cache"/><meta http-equiv="Expires" content="-1"/>…` — TSPD script re-injection, not portal payload. This is the concrete form `x-security-action: 0800000200` takes here: **the "4 search POSTs" recorded earlier are 1 real XHR POST + 3 F5 challenge/injection Documents, not 4 portal calls.** Worth folding into `docs/pjud-source.md`.
- **landing vs after snapshot** (step 5, D4): landing `first=null` (`n=0`, `cantidad=""`) → after `first=200791923` (`n=70`, `cantidad="Se ha(n) encontrado 14.733 resultados."`). P1 satisfied via the `landing["n"] == 0` branch; the measured late render is why the `time.sleep(15)` settle is load-bearing (D4b).
- **pagination timing** (step 6): pre-click `first=200917190`, `cursor=0`; immediately after the click `first=null`, `n=0`, `cursor=1` (rows cleared, count still stale); at **1.8 s** `first=200791920`, `n=70`, `cantidad="Se ha(n) encontrado 15.803 resultados."`. `_click_next_page()` returned `True` on every attempt.
- **one sample result dict** (step 5):
  ```json
  {"rol": "C-5810-2025",
   "caratulado": "CASTRO/CORPORACIÓN MUNICIPAL DE SERVICIOS PUBLICOS TRASPASADOS DE RANCAGUA",
   "fecha": "12-09-2026",
   "tribunal": "2º Juzgado Civil de Rancagua",
   "materia": "ACTO ADMINISTRATIVO, NULIDAD DE",
   "juez": "Cristián Eduardo Fernández González",
   "id_sentencia": "200791920",
   "id_buscador": 328,
   "instancia": "civil",
   "categoria": "civiles",
   "page": 1}
  ```
- **one downloaded file's first 500 chars**: none — step 7 was NOT RUN (see Summary). The recipe's `results[-1]` fallback would have produced a page-1 row, which does not exercise the page-targeting logic under test. `/tmp/cl_test` received no new `sentencia_*.html`; this is expected given the step did not execute, and is **not** evidence about `_open_detail`'s correctness.
- **section map** (step 4): `civiles {expected: 328, live: 328, f5: false}`, `penales {268, 268, false}`, `corte_suprema {528, 528, false}`.
- **step 9 live**: `navigate_returned=628`, `window.es_lj=true`, `window.id_buscador_activo=628`, `is_f5_block=false`.

### Phase A probe — issues 9 and 11 disambiguated

Work-order Phase A, run 2026-09-17 after the report patches. Read-only: one navigation to `?Civiles`, one `daño moral` search, one pager click; no downloads. `.venv/bin/python` (selenium 4.48.0) + Chrome 152 via Selenium Manager, headful, fresh profile per run; `chile_scraper.py` at the pinned blob `53a163d5…`. Two runs, same conclusions; raw captures in `/tmp/cl_phase_a_out.json` and `/tmp/cl_phase_a_out2.json`. No CAPTCHA was served on either run (`id_buscador_activo=328` on landing).

**A.1.1 — container.** `#capa_resultados_busqueda_sentencias` → 1 match, `#panel_resultados_busqueda_sentencias` → 1 match, `[id*='resultados']` → 5. A result card's ancestor chain is `div.card` → `div` → `div#capa_resultados_busqueda_sentencias` → `div#panel_resultados_busqueda_sentencias` → `div.col-md-12` → `div.row`. `document.querySelectorAll("#capa_resultados_busqueda_sentencias").length == 1` in the top document — the results are **not** inside an iframe (the only iframes are `TS_Injection`, the invisible reCAPTCHA anchor `k=6Lf5adcZ…`, and one empty frame), which is why `driver.find_elements` sees all 70.

**A.1.2 — node count vs unique.** `nodes=70 unique=10` on every observed page, **unscoped and scoped identically**. Node-per-result is exactly 7 and structural — see open issue 11 for the real markup. All 70 `is_displayed() == True`.

**A.2 — timing table** (probe 2, 0.1 s sampling; `n_all` = `[data-idsentencia]` count):

| t (s) | `n_all` | unique | cursor |
|---|---|---|---|
| pre-click | 70 | 10 | 0 |
| **0.022** | **0** | 0 | 1 |
| 0.133 … **2.087** | **0** | 0 | 1 |
| **2.425** | 70 | 10 | 1 |
| 2.528 … 4.940 | 70 | 10 | 1 |

20 consecutive empty samples; first sample whose id set differs from the pre-click set is at 2.425 s with `delta = 20` (all 10 ids replaced). Probe 1, sampling with a slower per-sample snapshot, bracketed the same window independently: first empty `t=0.027 s`, still empty at `t=2.011 s`, repopulated by `t=2.964 s`.

**Mechanism line — `issue 9 mechanism: B-2`.** Established by all 70 nodes reaching `n_all=0` within 22 ms of the click and staying empty for ~2.0 s: **no node carrying `data-idsentencia` survives the click**, so the "hidden stubs / cached rows satisfy the predicate" mechanism is refuted. What the probes **cannot** order is whether the predicate's *first* evaluation (which happens immediately — `WebDriverWait`'s 0.5 s is only the retry interval) precedes the ~22 ms clear; the sub-25 ms race is therefore **bounded but unresolved**, and it is the mechanism consistent with the recorded step-6 failure. Issue 11 is not involved, and work-order **B-1 is a no-op**.

**Transport, from the same run.** The search POST is `multipart/form-data` carrying a Laravel `_token` (see the *search XHR verdict* bullet above). The page also carries `form#form_busqueda_avanzada` with no `action` and no `method`. Three `buscar_sentencias?onComplete=…&ajaxAction=0501010200&time=…` **Document** requests (all 200, TSPD re-injection bodies) accompany the single real XHR POST.

**Phase A verdict on the work order:** A.1/A.2 are conclusive on the selector question, so the **B-1 branch does not apply** (scoping is a measured no-op) and **B-2's stated rationale — hidden/cached nodes satisfying the predicate — is refuted by measurement**. B-2 is nonetheless the right change, because requiring a *changed*, non-empty set also defeats the sub-25 ms race and the ~2.0 s empty window. Do not start work-order Phase B blind: Phase C must first re-run step 6 with the per-iteration instrumentation described in open issue 9.
