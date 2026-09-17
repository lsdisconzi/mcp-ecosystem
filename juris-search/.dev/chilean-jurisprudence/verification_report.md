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

> **Blocking:** open issue 9 (pagination), pending disambiguation from issue 11.
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
9. **No freshness check anywhere in the search loop — CONFIRMED LIVE as the cause of step 6's failure.** Outcome is solid: `pages == [1]`, `total == 10`, `new_on_page == 0` on the second iteration, loop breaks. **The precise mechanism is not yet established, and two observations are in tension:**
>
> 1. The step-6 timing probe (direct click on `#btnPaginador_pagina_adelante`) shows rows are **cleared immediately** (`first=null`, `n=0`) and the true count arrives at **~1.8 s**.
> 2. If rows are cleared on click, then `_wait_for_results` — an *existence* predicate — cannot be "satisfied by the pre-click row set." Something else keeps the predicate true.
>
> The most likely reconciliation is **open issue 11**: `[data-idsentencia]` matches ~70 nodes for 10 unique ids, so non-result elements carrying the attribute (hidden templates, cached rows, sidebar copies) survive pagination and satisfy `_wait_for_results` while the real result set is empty. **If so, the fix is not "add a sleep" — it is to scope the selector and redefine readiness as a row-set *change*.** If instead issue 11 is a red herring and the row clearing seen in the probe does not occur on `_click_next_page`'s code path (which uses `execute_script` rather than a real click), the fix is a longer wait. **Resolving 9 requires resolving 11 first.** Do not apply a predicate-change fix until the two are disambiguated.
>
> **Third reading, from the code (not in the original patch text).** `get_inteiro_links` calls `_wait_for_results()` *after* `_click_next_page()`, with `wait_time=30` and WebDriverWait's default 0.5 s poll. If the click's row-clear is deferred (the handler clears the DOM only once the XHR callback runs) then the **first poll at t≈0 still sees the old rows**, the existence predicate returns `True` immediately, and `_parse_search_results` re-reads page 1. This reading reconciles both observations without invoking issue 11, and it is a *race*, which explains why the failure is reproducible-but-timing-sensitive. It also means the row-set-*change* predicate is the correct fix in **all three** readings — see the tension with work-order §B-2 noted in `03-chile_scraper-playbook.md`.
>
> **Not fixed in this pass — reason is verification exhaustion, not scope.** `_wait_for_results` is **not** on the do-not-refactor list (`_parse_chile_text_result`, `_navigate_to_category`, `_click_next_page`, `_open_detail`), and step 6 produced a concrete reproducible failure attributable to it — so the escape clause applies and a fix would have been in scope. It was not attempted for two reasons: (a) the session became F5-blocked immediately after step 6 (`RuntimeError: F5 block detected while loading penales`), so any fix would have been **unverifiable** in this pass; and (b) the correct fix is blocked on disambiguating issues 9 and 11 (see above). **This is the top follow-up: the scraper cannot paginate at all, so `max_results > 10` is unreachable and every query silently returns at most one page.** The next pass should resolve 11 first, then fix 9, then re-run steps 5–8 in a fresh session.
10. **The pager markup is undocumented** in `docs/pjud-source.md` §7.1, which covers result rows only. The verified markup is recorded in playbook §6 sub-step 6a; it should be folded into the source notes.
11. **`[data-idsentencia]` is not one-node-per-result** — it matched ~70 nodes for 10 unique ids on every observed page (the first three matches carried the *same* id). `_parse_search_results` therefore runs its full regex set ~7× more often than needed, and `_open_detail`'s row loop iterates nested duplicates. Correct today only because of `seen_ids` dedupe and `_open_detail`'s early `id` mismatch `continue`. Tighten once the markup is confirmed in the source notes.

## Evidence

- **blocked page excerpt** (step 8, navigation GET): raw body was not captured — the challenge cleared before a snapshot could be taken (probe 9 read `blocked: false`). What is on record is the detector firing inside `_navigate_to_category`: `RuntimeError: Chile: F5 block detected while loading penales. support_id=n/a. Manual CAPTCHA solve in a real browser may be required.` `support_id=n/a` with a positive body match is the live confirmation of open issue 3.
- **search XHR verdict**: `through`. `POST https://juris.pjud.cl/busqueda/busqueda_por_texto_autocompletable` → HTTP `200`, body head `0\t{"ministros":[],"descriptores":[],"lugares":[],"normas":[],"sugerencias":[]}`; 4 search POSTs total, **none** with an F5 body. `_is_f5_block(response_body)` was `False` on every one. Case A3 did **not** reproduce in this fresh session, so the earlier session's Case A3 observation stands as an environment-dependent condition, not a permanent one.
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
