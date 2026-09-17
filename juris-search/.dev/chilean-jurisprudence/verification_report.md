# chile_scraper.py — Verification Report

Date: 2026-09-17
Operator / session: fresh headful Chrome 152 (Selenium Manager), macOS; one fresh profile per probe, no reused session
Pinned artifact: chile_scraper.py @ sha1:`a595bf7c4c46fd61de1bd0fe87e35a66fe4173c9`
Pinned artifact observed: `a595bf7c4c46fd61de1bd0fe87e35a66fe4173c9` (`git hash-object juris-search/chile_scraper.py` — the working-tree blob, which is what step 0.1's freshness gate tests; `git rev-parse HEAD:…` reports the committed blob and will drift on any commit made after the run)
Playbook: `.dev/chilean-jurisprudence/02-chile_scraper-playbook.md` @ sha256:`63a4f0e7758f3b11d1f9770aeff594d6c22a85a8965514852f216e5021c4b477`

> The pin was **refreshed twice in this pass**: `d46f896dadaacb2b5479420229f547938d688640` → `53a163d543ecb4de425988d2f92d0233e5e4bef7` → `a595bf7c4c46fd61de1bd0fe87e35a66fe4173c9`. The first move was step 6's `_click_next_page` selector fix (blob delta exactly one hunk, `+16/-1`, verified with `git diff d46f896d… 53a163d5…`). The second is **Phase B**, the readiness change described under *Changes made* — it is the first edit to `chile_scraper.py` since that pin. The `playbook-hash` was recomputed for both, because both `02` and `03` were amended; see the amendment table (`D4c`, `D7b`, `D8`).

```
verdict: red — 1 blocking defect (pagination) fixed, awaiting live verification; 10 secondary issues
```

> **Blocking:** open issue 9 (pagination). **Phase A resolved the disambiguation: issue 11 is not the mechanism for this symptom, the selector-scoping fix B-1 is a measured no-op, and the defect is a race between the click's DOM clear (~22 ms) and the readiness predicate's first evaluation (immediate).** Phase B has since been **applied** (change-predicate + a separate content-gated detail wait, see *Changes made*), so the outstanding work is **Phase C: re-run step 6 against the new code path**. The verdict stays red until that run passes — a fix that has never executed live is not a green.
> **Secondary:** page-size control, filter surface, Spanish-only support-ID, body-only F5 detector, `imprimir` unprobed, `Compendio` id, LJ mode, Case A3, pager markup docs, node-per-result efficiency, **page-1 stale-listing path (issue 12, new — code-reading only, two paths: timeout and false-success)**.
> **Blocked by the blocking defect:** step 7 (`_open_detail` untested), step 8 search half (`penales` search untested).
>
> **Issue 12 was found after Phase B was committed** (by tracing the retry logic in review) and is deliberately **not** fixed in `2f4a2cd`: it changes page-1 control flow, which is outside the approved hunks, and its correct remedy depends on a measurement Phase C has not taken yet. See *Open issue 12*.
>
> **Issue 12 has two paths, and the second needs no timeout.** The predicate can be satisfied by the *landing listing itself*, because `pre_search_ids` is frequently empty and an empty baseline degenerates the change predicate to existence mode. That path returns `wait_ok is True`, so a check on `wait_ok` alone cannot see it. Phase C therefore also compares `#span_cantidad_resultados` before and after the search wait. See *Open issue 12*.

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
| **D4c / D7b** | §5, §6 (6a) | **corrections to D4b/D7 after Phase A measurement**: the 7× node replication is one *visible* card containing its own visible descendants (no hidden stubs; scoping is a no-op), and the pagination timeline is clear-at-~22 ms / empty-~2.0 s / repopulated-2.425 s — not "~1.8 s" — with the "satisfied by pre-click rows" mechanism removed. The **fix** each amendment pointed at is unchanged; the stated *reason* was wrong |
| **D8** | 03 Phase A.2 / Phase B | rewrote **§A.2's decision table** (its B-1 row was built on reconstructed markup that does not exist) and marked **B-1 not applicable**. Recorded the applied Phase B shape: `offsetParent`-based id snapshot, bool-returning change predicate, content-gated `_wait_for_detail`, terminal `new_on_page == 0` **except** after a timed-out wait |
| re-pin | header | **`d46f896d…` → `53a163d5…`**: step 6 forced the pager selector fix; the pinned blob moved by design |
| **re-pin 2** | header | **`53a163d5…` → the Phase B blob**: the readiness change is the first edit to `chile_scraper.py` since that pin. The two `.dev` playbooks were also committed, which is what makes the declared `playbook-hash` checkable from `HEAD` |
| minor | §0.5, §4, §10, §11 | `mkdir -p workspace/CL_jurisprudencia`; in-loop assertion; §11.N → §11 item N |

## Summary

| Step | Result | Notes |
|------|--------|-------|
| 0.1 Freshness gate | **PASS** | `freshness OK` on the blob under test, `53a163d5…` at the time of the live run. **The pin has since moved twice** — see the header; the frozen row is retained as the record of that run, not of the current tree. |
| 0.3 Driver smoke | **PASS** | `Example Domain` on a throwaway profile |
| 0.5 Workspace | **PASS** | `workspace/CL_jurisprudencia` created; 0 pre-existing entries |
| 1 Static | **PASS** | 1a–1e (13/13 offline assertions green) |
| 2 F5 unit | **PASS** | incl. 2e (TSPD image → detected, `support_id=None`) and 2f (body-less → `False`) |
| 3 F5 live | **Case B (through)** | `_is_f5_block=False`, `support_id=None`, `title="Buscador Unificado de Fallos del Poder Judicial"`, `window.id_buscador_activo=328`. **Case A3 did not reproduce in the fresh session** — see *Evidence* |
| 4 Section map | **PASS** | `civiles 328/328`, `penales 268/268`, `corte_suprema 528/528`; all `live == expected`, no F5 |
| 5 Search | **PASS** | **P1/P2 first**: landing `n=0`, `cantidad=""` → after `n=70` DOM nodes (**10 unique ids**), `Se ha(n) encontrado 14.733 resultados.`, first id `200791923`, omnibox holds the query. Then `n=10`, `id_buscador=328` on every row, `instancia="civil"`, `categoria="civiles"`, `page=1`, `empty_rols=0`, ROLs well-formed (`C-5810-2025`, `C-12950-2025`, `C-953-2026`, …) |
| 5.5 Filter surface | **OBSERVED** | **Filter NOT sent** — omnibox only, no `tribunal` key. **XHR verdict: `through`** (1 real XHR `multipart/form-data` POST + 3 F5 TSPD `Document` re-injections, all HTTP 200, no F5 *body* — corrected from the original "4 search POSTs / real JSON", see *Evidence*) |
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
- `chile_scraper.py` **Phase B** (work-order Phase B, applied after this report's Phase A and doc 04's verdict). Four edits, one commit:
  1. **`_current_result_ids()`** (new) — one `execute_script` round trip returning a `frozenset` of the visible `[data-idsentencia]` values, `frozenset()` on any driver failure.
  2. **`_wait_for_results()`** — readiness is now a **change** predicate: the live set must be non-empty **and** different from `previous_ids` when one is supplied; `previous_ids=None` keeps the legacy existence behaviour for callers that have no baseline. It now **returns a bool** so a timeout is distinguishable from success.
  3. **`_wait_for_detail()`** (new) — a separate wait for `_open_detail`, gated on **content**, not visibility (see the *Detail-swap* evidence).
  4. **Call sites** — `get_inteiro_links` snapshots the landing ids before `_run_search_ui` and the consumed page's ids before each pager click; `_open_detail` does the same and waits on `_wait_for_detail` after the click. The unpaced `time.sleep(0.5)` and `time.sleep(0.3)` are **removed** — the change predicate is what paces the loops.

  `new_on_page == 0` remains **terminal**, but a zero-yield page now triggers a **single click retry when the preceding wait timed out**, and logs `readiness_reached=` / `ids_on_page=`, so a truncated result set cannot be silent. Work-order **B-1 was not applied** (scoping is a measured no-op).

  Offline coverage: **`test_chile_readiness.py`**, 18 assertions / 18 passing, `.venv/bin/python test_chile_readiness.py`, no network and no Chrome.

  **What those 18 assertions actually target, since it was asked and it matters:** sections 1, 2, 4 and 5 call the **real shipped methods** (`_current_result_ids`, `_wait_for_results`, `_wait_for_detail`) on an instance built with `__new__` + a hand-set `wait_time` — no `__init__`, no browser. The only stub is at the **WebDriver boundary** (`execute_script` returns a scripted value per poll, `page_source` is a fixed string), so the JS text, the F5 short-circuit, the `previous_ids` comparison, the `WebDriverWait` retry cadence and the `bool` return are all the shipped code under test. Section 3 **does** re-implement a predicate, deliberately and unavoidably — the old existence predicate no longer exists in the source to call — and its value is *negative*: it shows that predicate accepts an unchanged 10-node page, so section 2's assertion is not vacuous. Section 6 is source-**text** inspection, not behaviour.

  **Known coverage gaps, stated plainly.** (a) Nothing drives `get_inteiro_links` as a whole, so the **B-2b retry path has zero coverage** — it is only load-bearing in the failure mode it was written for, and will not fire in Phase C if pagination simply works. (b) Section 6's `count("_wait_for_results(") == count("previous_ids=")` is a **structural proxy**: it can show that every call passes *some* baseline, but not that each passes the *right* one. (c) The page-1 path is not covered at all — which is how issue 12 survived the pass.

  **Not yet visited live.** Everything above is offline-verified only; Phase C is what establishes the pin.

## Open issues / follow-ups

1. Page-size control is **not wired up** — `resultados_por_pagina` is arithmetic-only; the portal default (10) applies.
2. Advanced-search filters (`tribunal`, `juez`, `materia`, `rol`, dates) **never reach the portal** — `_run_search_ui` only fills the omnibox. Confirmed live in step 5.5.
3. `_extract_support_id` is **Spanish-only**; an English/marker-only rejection yields `None`. Observed live in step 8: `_is_f5_block` was `True` while `support_id` was `n/a`.
4. `_is_f5_block` is **body-only**; header-only rejections (`x-security-action`) are undetected.
5. `/busqueda/imprimir` is unprobed as an alternative artefact source.
6. `Compendio_Extranjería` `id_buscador` is **still unverified**.
7. `Lineas_Jurisprudenciales` special mode is **not implemented** — `window.es_lj` is confirmed `true` live, but `get_inteiro_links` never branches on `es_lj`. A `NotImplementedError` guard is still recommended.
8. **F5 rejections delivered inside an XHR body are undetectable** (Case A3). **Observed once, not reproduced, body not captured.** The route is documented as the most aggressively filtered one (`docs/pjud-source.md` §5.3), and when it triggers, `_assert_not_blocked` cannot see it and `get_inteiro_links` returns stale landing data as results. But this pass produced **no** capture of an F5 body on that route: the fresh sessions saw the search render result cards, which an F5-rejected body cannot do. Treat A3 as an **environment-dependent** route condition, not a permanent one, and do not report it as reproduced.
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
> **Required next step.** Re-run step 6 against the **new** code path, recording `max_results` explicitly and logging `max_pages` / `len(entries)` / `new_on_page` / `readiness_reached` per iteration — the applied code logs the last two. Pass criteria are in playbook 03 §Phase C. Work-order **B-1 remains not applicable.**
>
> **Phase B applied (2026-09-17).** The readiness predicate is now a *change* predicate (`_wait_for_results(previous_ids=…)`) returning a bool, with `_current_result_ids()` supplying the visible id set in one round trip, and a separate content-gated `_wait_for_detail()` for `_open_detail`. The unpaced `time.sleep(0.5)` / `0.3` calls are gone. See *Changes made* for the four edits and `test_chile_readiness.py` for the offline evidence.
>
> **`_open_detail` inherits the same defect, and is fixed in the same pass.** Doc 04 raised it and the *Detail-swap* probe confirmed the shape: clicking `Ver sentencia` **hides** `#capa_resultados_busqueda_sentencias` without removing its 70 nodes, so `_open_detail`'s post-click `_wait_for_results(timeout=self.wait_time)` was satisfied by **invisible** result nodes and returned immediately — the identical "existence is not readiness" error, one layer down. Its pre-click page-advance loop had the same problem via a bare `_wait_for_results()`. Both now pass explicit `previous_ids`, and the post-click wait is `_wait_for_detail`.
>
> **Applied (2026-09-17, commit `2f4a2cd`).** `_wait_for_results` is now a *change* predicate returning a bool, with the non-terminal `new_on_page == 0` handler this issue asked for. The original "not fixed in this pass" reasoning is retained below because it explains *why* the gate was later skipped rather than met.
>
> **Original "not fixed in this pass" record — reason was verification exhaustion, not scope.** `_wait_for_results` is **not** on the do-not-refactor list (`_parse_chile_text_result`, `_navigate_to_category`, `_click_next_page`, `_open_detail`), and step 6 produced a concrete reproducible failure — so the escape clause applied and a fix was in scope. It was not attempted at the time for two reasons: (a) the session became F5-blocked immediately after step 6 (`RuntimeError: F5 block detected while loading penales`), so any fix would have been **unverifiable** in that pass; and (b) Phase A narrowed the mechanism to a sub-25 ms race between the click's DOM clear and the predicate's first poll. Doc 04 then argued the gate was over-cautious — a change predicate is correct under *both* orderings — and Phase B proceeded without it. **The per-iteration instrumentation is still owed, now against the new code path (Phase C).**
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

12. **The page-1 stale-listing path is unguarded, and `new_on_page == 0` cannot detect it.** Found by tracing the Phase B retry logic (review of `2f4a2cd`), **not observed live — it is a code-reading finding and is honestly labelled as such.**

    On page 1 the sequence is: `pre_search_ids = _current_result_ids()` → `_run_search_ui(query)` → `wait_ok = _wait_for_results(previous_ids=pre_search_ids)` → **parse unconditionally.** `wait_ok` is consulted in exactly one place, the `new_on_page == 0` branch. So when the search's readiness wait **times out** (`wait_ok is False`), the loop parses whatever the DOM holds at that moment.

    On **page 1 that is not the search result**, and it is not empty either. The two candidate DOM states are (a) the landing page's **default listing** — the whole-section set, whose count text reads `Se ha(n) encontrado 855.792 resultados.` on unfiltered Civiles (D4b) and which renders ~1.1 s after `_navigate_to_category` returns — or (b) the **previous query's** rows if the driver is reused. Either way `_parse_search_results` returns a full page of real-looking rows.

    *(Correction to an earlier draft of this entry: it said the landing listing "holds ~15.8k unrelated rows". That conflated the **post-search pagination** count `15.803` with the landing default `855.792`, and neither is a row count — the listing renders **10 unique ids** across 70 nodes.)*

    **Path 2 — no timeout required, and `wait_ok` is `True`.** `_navigate_to_category` returns as soon as `window.id_buscador_activo` is defined (it is set inline, before the landing listing renders), so the `pre_search_ids` snapshot at L325 frequently captures `frozenset()`. `_wait_for_results(previous_ids=frozenset())` then **degenerates to existence mode**: `previous_ids is not None`, so the predicate evaluates `current != previous_ids`, which is `True` for *any* non-empty set — and the landing listing is a non-empty set. If landing renders during the polling window, the wait returns `True` **on landing data**, `wait_ok` is `True`, and there is no timeout to consult. This is a **false success, not a timeout**, and it is the shape that fires when the search XHR is F5-rejected (Case A3): the landing listing renders, the predicate is satisfied, and the scraper returns landing rows as the answer to the query. The baseline models **one** change; landing-then-search is **two**. `wait_ok is True` is therefore **not** sufficient evidence that the search took effect, and a check that only reads `wait_ok` cannot detect this path.

    The guard does not fire, because on page 1 **`seen_ids` is empty**: every freshly parsed row is a *first* sighting, so `new_on_page == 10`, not `0`. The loop therefore appends the wrong rows, `len(entries)` reaches `max_results`, and it returns **explicitly wrong results under the queried term** — with `page: 1` and no warning. This is strictly worse than the truncation the retry was written to prevent: a truncated set is visibly short, whereas this is silently incorrect and indistinguishable downstream from a genuine match.

    This is the same D4b trap the change predicate was built to close, surviving through a **different door**: the predicate correctly refuses to report ready, and the caller ignores the refusal rather than acting on it.

    **Not fixed here on purpose.** The change is outside the approved Phase B hunks (it touches the page-1 control flow, and `_run_search_ui` sits adjacent to the do-not-refactor list), and more importantly it must not be fixed *before* Phase C measures whether page 1's wait ever times out in practice. The two candidate fixes, to be decided with that measurement in hand: on `wait_ok is False` for page 1, either (i) `raise` — an unreached search is not a result set — or (ii) retry `_run_search_ui` once and re-wait, mirroring B-2b's pagination retry. Option (i) is safe and cheap; option (ii) is symmetric with the pager and is preferable only if the timeout is observed to be transient rather than terminal.

    **Phase C must therefore record two things for the search itself**, not only for the paginations: page 1's `wait_ok` **and** `#span_cantidad_resultados` before vs after that wait. The current code logs **neither**, so the pass criteria in playbook 03 §Phase C are insufficient for this issue as written. The count comparison is not optional — it is the only signal that separates Path 2 above from a genuine search, because `wait_ok` is `True` on both. Both are now wired into §Phase C's instrumentation (criteria 6 and 7).

    **The eventual fix is two independent changes, not one.** An earlier draft of this entry proposed adding "a third parameter" to `_wait_for_results`; that is a workaround for a *baseline that is empty by construction*, and the cleaner root cause is that `_navigate_to_category` returns before the landing listing exists. But **land-ready alone does not close this issue**, which is the trap worth pinning while it is fresh:

    1. **Land-ready in `_navigate_to_category`** — return only once the landing listing has settled (bounded, with "landing genuinely empty" as a distinct outcome). This closes **Path 2**: `pre_search_ids` becomes the landing's own 10 ids, the change predicate stops degenerating to existence mode, and the landing listing can no longer satisfy the search wait.
    2. **Consult `wait_ok` in `get_inteiro_links`** — raise or retry once when it is `False`. This closes **Path 1**.

    **(1) alone converts Path 2 from a silent false success into Path 1's loud timeout — it does not remove the failure.** With land-ready in place and the search XHR F5-rejected (Case A3), or the query legitimately returning nothing: `previous_ids` = the landing's 10 ids (non-empty), the predicate correctly waits for a *different* set, no different set arrives, the predicate times out, `wait_ok is False` — **and the caller still ignores it, parsing landing rows as results.** The predicate is then correct and the caller is still wrong. So shipping (1) and declaring issue 12 resolved would leave Case A3 silently ingesting landing data again, via a path that now merely logs a timeout nobody reads. Both changes ship together, or neither closes the issue.

## Evidence

- **blocked page excerpt** (step 8, navigation GET): raw body was not captured — the challenge cleared before a snapshot could be taken (probe 9 read `blocked: false`). What is on record is the detector firing inside `_navigate_to_category`: `RuntimeError: Chile: F5 block detected while loading penales. support_id=n/a. Manual CAPTCHA solve in a real browser may be required.` `support_id=n/a` with a positive body match is the live confirmation of open issue 3.
- **search XHR verdict**: `through` — with one correction and one explicit gap. The autocomplete body stands as recorded: `POST https://juris.pjud.cl/busqueda/busqueda_por_texto_autocompletable` → HTTP `200`, body head `0\t{"ministros":[],"descriptores":[],"lugares":[],"normas":[],"sugerencias":[]}`.
  - **The primary search endpoint POSTs a real multipart body.** Captured live via CDP `Network.requestWillBeSent` (Phase A): `POST https://juris.pjud.cl/busqueda/buscar_sentencias`, `type=XHR`, `postData` head `------WebKitFormBoundaryCqwDieLbFhpKVZBY\r\nContent-Disposition: form-data; name="_token"\r\n\r\nQBf5octe7u9gmYmhK3RwnbusLU8eSH5BF1bzWxyH…`. So the primary search is **not** a JSON POST — it is `multipart/form-data` carrying a Laravel `_token`. This supersedes playbook 03 §4b's illustrative JSON body, which is a reconstruction.
  - **The response body was NOT captured, and the report will not pretend otherwise.** `Network.getResponseBody` for that `requestId` returned:
    ```
    getResponseBody FAILED: unhandled inspector error {"code":-32000,"message":"No data found for resource with given identifier"}
    ```
    i.e. the body had already been evicted by the time it was requested, and a document-level `XMLHttpRequest.prototype.send` hook that *did* capture the autocomplete XHR never saw the `buscar_sentencias` XHR — consistent with it being issued outside the hooked document. Playbook 03 §4b's `0\t{"resultados":[…],"total":14733}` head is therefore **not reproducible and has not been substituted**.
  - **The workaround to use next time, so that this failure is not repeated:** do not read the body from a `Network.responseReceived` event. Enable the `Fetch` domain with `responseStage: Response` (`Fetch.enable` / `Fetch.requestPaused`) and capture `params.responsePayload` (base64) from the paused event itself, then `Fetch.continueRequest`. `responseReceived` carries metadata only, and by the time a later `getResponseBody` call arrives the identifier is often gone — which is exactly the `-32000` above. This has **not** been executed yet; it is the next session's first tooling task, and the report should record the body only once it is actually in hand.
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

**Phase A verdict on the work order:** A.1/A.2 are conclusive on the selector question, so the **B-1 branch does not apply** (scoping is a measured no-op) and **B-2's stated rationale — hidden/cached nodes satisfying the predicate — is refuted by measurement**. B-2 is nonetheless the right change, because requiring a *changed*, non-empty set also defeats the sub-25 ms race and the ~2.0 s empty window.

**Phase B was started without the "re-run step 6 first" gate, deliberately.** Doc 04 argued the point and it holds up: a change predicate is correct under *both* orderings of the race, so the gate could not have changed the fix — only its justification. The instrumentation that would have ordered the race is still owed, and it is now owed against the **new** code path (playbook 03 §Phase C).

### Detail-swap probe — `_open_detail` and `_wait_for_detail`

Read-only probe (`/tmp/cl_detail_probe.py`, raw capture `/tmp/cl_detail_out.json`), run 2026-09-17 on the same pinned blob `53a163d5…`: one navigation to `?Civiles`, one `daño moral` search, **one** `Ver sentencia` click, then 40 samples at 0.25 s. No CAPTCHA served. This probe existed to answer a question doc 04 raised and doc 05 had *guessed* at: does the detail open in a new tab, and is `#capa_contenedor_detalle_sentencia` real?

**Both answers settle the shape of the fix.**

- **No new tab.** `window` handles were `1` before the click and `1` after, sampled every 0.25 s for 10 s. The control `_open_detail` clicks is `<button type="button" class="btn btn-primary font-weight-bold" data-idsentencia="200791920" onclick="…; guardarPosicionPrincipal(); ver_detalle_sentencia(this)">` — note `type="button"`, not a submit, and **not** inside the form.
- **There is a second, unrelated mechanism that *would* open a tab**, and it is important not to confuse them. The card also contains `<form data-idsentencia="200791920" onsubmit="ver_detalle_sentencia_nueva_pestanna(this)" enctype="multipart/form-data" target="_blank" method="post" action="https://juris.pjud.cl/busqueda/pagina_detalle_sentencia">` carrying hidden `_token`, `id_sentencia`, `id_buscador_activo`, `json_lista_palabras_a_destacar_en_highlight`, `json_lista_ids_sentencias_de_la_pagina`. `target="_blank"` is real — but it belongs to the **form submit** path, which a `type="button"` `execute_script` click never triggers. `download_inteiro_teor_url`'s read of `self.driver.page_source` is therefore correct for the path `_open_detail` actually takes. The form is a **sibling** of the button (`inForm=False`), so the button is not wired by form association.
- **`ver_detalle_sentencia` is an in-page AJAX swap** (function body read from the live page): `… cargar_detalle_sentencia(boton.dataset["idsentencia"]); $('#capa_contenedor_detalle_sentencia').show(); $('#capa_contenedor_controles_busqueda').hide(); $('#contenedor_estadisticas_visitas_y_busquedas').hide(); …`. That explains the `guardarPosicionPrincipal()` / `guardarPosicionDestino()` pair in the click handler: they exist because the page is **not** being navigated away from.
- **`#capa_contenedor_detalle_sentencia` is real** — doc 05 flagged it as a guess from a container dump, and it does exist, in the DOM **before** the click, with `display: none`. Its siblings (`detalle_sentencia_ir_anterior`, `panel_contenedor_central_detalle_sentencia`, `contenedor_app_vue_detalle_sentencia`, …) are all present and hidden too.
- **Visibility flips essentially instantly: `display: block`, `vis=True` at the first sample (t≈0.007 s).** A `_wait_for_detail` that only checked `is_displayed()` — which is what the work order originally specified — **would have returned immediately on an empty panel.**
- **The content arrives later, and that is the readiness signal.** Text lengths, pre-click → post-click: `#capa_contenedor_detalle_sentencia` 9,376 → **99,365**; `#panel_contenedor_central_detalle_sentencia` 94 → **78,904**; `#contenedor_app_vue_detalle_sentencia` 1,032 → 91,003. The central panel is the clean signal (94 is static chrome; 78,904 is the document), so `_wait_for_detail` requires container visible **and** central-panel text `>= 1000` — a floor with two orders of magnitude of clearance on both sides. `_DETAIL_MIN_CHARS` is documented against these numbers in the source.
- **The results are hidden, not removed.** `#capa_resultados_busqueda_sentencias` still reports `nIdsent=70` after the swap, with `vis=False`, and `document.querySelectorAll('[data-idsentencia]').length` stays **70** for the whole 10 s. This is the measurement that makes the *old* post-click wait a bug rather than a style issue: `_wait_for_results` asks only whether such nodes exist, and they do — invisible ones. It is also why `_current_result_ids()` filters on `offsetParent`, and why the filter is load-bearing rather than cosmetic.
- `body_len` grew across three steps (833,210 → 912,192 at t≈0.81 s → 923,199 at t≈3.55 s), consistent with the AJAX fill and with `page_source` remaining a valid way to read the document **once the content gate has passed**.

**What this probe does not establish.** (a) It does not time the content growth finely — the `>= 1000` floor is bracketed by the pre/post values, not by a curve, so if a future revision fills the panel slowly the wait may return on a partially-rendered document; that is what the floor is for and it is a heuristic, not a proof. (b) It exercises **one** category (`civiles`) and one result. (c) `download_inteiro_teor_url`'s own behaviour after `_open_detail` returns — including its best-effort "Volver a la página de búsqueda" click and whether `page_source` yields a clean document or the whole 923 KB page with hidden panels included — remains **unverified**, because step 7 is still NOT RUN.
