# chile_scraper.py — Verification Report

Date: 2026-09-17
Operator / session: fresh headful Chrome 152 (Selenium Manager), macOS; one fresh profile per probe, no reused session
Pinned artifact: chile_scraper.py @ sha1:`a595bf7c4c46fd61de1bd0fe87e35a66fe4173c9`
Pinned artifact observed: `a595bf7c4c46fd61de1bd0fe87e35a66fe4173c9` (`git hash-object juris-search/chile_scraper.py` — the working-tree blob, which is what step 0.1's freshness gate tests; `git rev-parse HEAD:…` reports the committed blob and will drift on any commit made after the run)
Playbook: `.dev/chilean-jurisprudence/02-chile_scraper-playbook.md` @ sha256:`6bd071acf1a710248f30542a839750557031d548b5258072e5fe0a458c58d092`

> The pin was **refreshed twice in this pass**: `d46f896dadaacb2b5479420229f547938d688640` → `53a163d543ecb4de425988d2f92d0233e5e4bef7` → `a595bf7c4c46fd61de1bd0fe87e35a66fe4173c9`. The first move was step 6's `_click_next_page` selector fix (blob delta exactly one hunk, `+16/-1`, verified with `git diff d46f896d… 53a163d5…`). The second is **Phase B**, the readiness change described under *Changes made* — it is the first edit to `chile_scraper.py` since that pin. The `playbook-hash` was recomputed for both, because both `02` and `03` were amended; see the amendment table (`D4c`, `D7b`, `D8`). It was recomputed **once more** after this report was reviewed: the review moved the instrumentation rule into `02` §13 and the count-lag finding into `docs/pjud-source.md` §7.1, so the report no longer matches the hash it was produced against — those rows are `D9`, `D4d`, `D10` and `R1` in the amendment table. **The report's measurements are unchanged by that re-pin**; only its own text moved. `chile_scraper.py` is still at `a595bf7c…`, so the pinned-artifact half of the header is untouched.

```
verdict: red — issue 9 (pagination) fixed and **verified live**; issue 12 Path 1 confirmed live **as a code path, and now with a production-shaped trigger observed** — a portal-side search stall that truncates a ~15,800-match query to 10 rows silently: unfixed; 11 secondary issues
```

> **Blocking:** open issue 12 Path 1. **Issue 9 is now closed by live measurement** — Phase C re-ran the step against the Phase B code path and pagination works (`pages == [1,2,3,4]`, `total == 40`, `unique == 40`), as does the same code path through the **deployed API** (a 30-result job returned `pages == [1,2,3]`, 30/30 unique). **Phase A resolved the issue-9 disambiguation: issue 11 is not the mechanism, the selector-scoping fix B-1 is a measured no-op, and the defect is a race between the click's DOM clear (~22 ms) and the readiness predicate's first evaluation (immediate).** Phase B has been **applied** (change-predicate + a separate content-gated detail wait, see *Changes made*).
>
> **The verdict is red for a different reason than it was.** Phase C also produced a live reproduction of issue 12's **Path 1**: on page 1 the search readiness wait returned `False` and `get_inteiro_links` **consumed the DOM anyway**, because L327's `wait_ok` is read only inside the `new_on_page == 0` branch — which on page 1 cannot fire (`seen_ids` is empty, so `new_on_page == 10`). The same discard exists in `_open_detail` (L738). See *Phase C* under Evidence and *Open issue 12*.
>
> **Qualification — what "confirmed live" does and does not mean for Path 1.** What is observed is that the *code path executes and mishandles a `False` wait*, reproduced end-to-end by direct observation rather than by code reading — and, since the post-review step-7 run, also that a **production-shaped trigger reaches it**: a portal-side stall of the search response makes the wait time out, the caller reads **0 rows**, and `get_inteiro_links` returns normally with a **truncated** result set (`total: 10` for a `855.792`-match query, `readiness_reached=False, ids_on_page=0`). That is the *silent-truncation* variant, and it is measured. What remains **unobserved** is the *wrong-rows* variant: Case A3 (an F5 or challenge rejection delivered inside the search `POST` body, issue 8) and a query that legitimately returns nothing. The first trigger ever observed here was an unsolved challenge (issue 13), i.e. a harness condition; the step-7 stall was not — no challenge popup was on the page at all. So the defect is real, page-1-specific, and now has a measured production cost; only its *wrong-rows* trigger remains unvalidated.
>
> **Issue 12's Path 2 was NOT confirmed — and the "evidence leans against it" recorded by the previous revision of this report has been WITHDRAWN. The evidence is uninformative, not merely thin.** Its *precondition* (`pre_search_ids == frozenset()`) was reproduced live twice, including on the UI's own path (**routine, not exceptional**). What could not be shown is the predicate ever *accepting* landing data — and a post-report re-audit of the raw captures shows the value that was used to argue it had *not* accepted it (the "settled landing first id", `200705571`) is the **lowest** id of run 1's page-1 set and therefore the **last** row of a listing paginated by descending id. The comparison was not a comparison of like states. Reasons, raw-capture citations and the instrument artefact that produced the value are under *Phase C* and *Capture re-audit*.
> **Secondary:** page-size control, filter surface, Spanish-only support-ID, body-only F5 detector, `imprimir` unprobed, `Compendio` id, LJ mode, Case A3, pager markup docs, node-per-result efficiency, **CL reliability under the F5/reCAPTCHA challenge (issue 13, new — the top operational risk)**.
> **Blocked by the blocking defect:** none of the remaining steps is blocked by the defect any more. **Step 7 has now been run and it FAILED** — three post-review live attempts on the pinned blob reached `_open_detail → False` after a **61.9 s** wait because the search *re-run* inside `download_inteiro_teor_url` produced **no rows at all** (`_current_result_ids()` returned `frozenset()` on every one of 31 polls), so the row loop never ran and the click — hence **`_wait_for_detail`** — was never exercised. The portal stopped serving **search** results to this client part-way through the session while the **landing** page of the same session kept rendering normally (`6752` chars, `70` visible nodes, `10` unique ids, count `855.792`), which pins the failure to the search `POST` — the precondition this step's own warning names. Criteria 1 and 2 pass; 3 and 4 are not applicable. See *Step 7 live run* under Evidence. **`_wait_for_detail` was unmeasured at the end of that run and has since been measured**, by a fourth attempt (R3) that reaches the click and invokes the gate — see *Fourth attempt (R3)* under Evidence, which also identifies why the call returns `False`: the portal's F5/Imperva layer **rejects the site's own `buscar_sentencias` POST** with an HTTP `200` block body. Step 8's search half (`penales`) remains unmeasured because step 8 is blocked at **navigation**.
>
> **Issue 12 was found after Phase B was committed** (by tracing the retry logic in review) and is deliberately **not** fixed in `2f4a2cd`: it changes page-1 control flow, which is outside the approved hunks. Phase C has since supplied the measurement that was owed: **Path 1 is confirmed live** and **Path 2 is not**, so the remedy is now decidable (see *Open issue 12*).
>
> **Issue 12 has two paths, and the second needs no timeout.** The predicate can be satisfied by the *landing listing itself*, because `pre_search_ids` is frequently empty and an empty baseline degenerates the change predicate to existence mode. That path returns `wait_ok is True`, so a check on `wait_ok` alone cannot see it. Phase C therefore also compares `#span_cantidad_resultados` before and after the search wait. See *Open issue 12*.
>
> **Correction to that plan, from the Phase C measurement.** The count comparison was designed as the Path-2 discriminator and it **cannot serve as one**: `#span_cantidad_resultados` **lags the row set**. That is a portal fact, not a report finding, and it now lives in **`docs/pjud-source.md` §7.1** with the measured values (`''` beside `0` nodes after nav; `15.803` beside `70` nodes after search; run 1's fresh ids beside the stale landing default). What stays here is the consequence: a stale count beside a fresh row set is an **expected** state, so criteria 6/7 decide nothing about Path 2 — and criterion 7 in fact passed for the wrong reason (`855.792 != ''`). **The search XHR response body is the only reliable discriminator**; see issue 12 and issue 8.

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
| **D9** | **§13 (new)**, §5 | added a top-level **§13 Instrumentation rules** (5 mandatory rules): validate that a baseline is **non-degenerate** before evaluating a discriminator; a **subset read can never exceed its superset**; **name the statistic** and compare set-to-set (`first` here is the page's *maximum* id); read **after the render** (~1.1 s landing / ~2.0 s post-click windows); and **re-derive recorded values from the raw capture**. This was the report's own "instrumentation rule" paragraph; it now lives in the playbook, and the report keeps only a pointer |
| **D4d** | report issue 12 / §5 | **correction to D4b's landing figure.** D4b's landing first id `200917190` is not distinguishable from the post-search page-1 first id, and probe 2 recorded `200705571` for the same state — two records sitting at **opposite ends of the same page-1 id set**. A landing baseline must be a **settled (≥2.5 s) id set**, and P1/P2 must compare **set-to-set**, not first-id-to-first-id |
| **D10** | `docs/pjud-source.md` §7.1 | moved three measured **portal** facts into the source notes: `#span_cantidad_resultados` **lags the row set** (4 readings, 3 captures); ordering is **descending `id_sentencia`** (so "first row" = the page's maximum id); `[data-idsentencia]` is **~7 nodes per result** with `div.card` as the per-result root |
| **R1** | verdict fence, summary, issue 12, issue 13, Evidence | post-review corrections to this report: secondary count **10 → 11**; Path 1 qualified as an observed **code path** (production triggers **not** observed); Path 2's **negative leaning withdrawn** and replaced by *Capture re-audit*; issue 13 step (ii) specified; the pre-existing literal `\"` escapes on the issue-13 paragraph removed |
| **R2** | Summary (row 7, count, arithmetic note), verdict fence, issue 12, issue 13, Evidence (**new** *Step 7 live run*) | post-review **step-7 live attempt** recorded. Row 7 `NOT RUN` → `FAIL`; standing count now **10 PASS / 1 FAIL / 2 BLOCKED**. Three conclusions written up: `_wait_for_detail` is **still unmeasured** (the click is never reached — the search re-run inside `download_inteiro_teor_url` returns no rows and `_open_detail` returns `False` correctly); a **portal-side search stall** is a **production-shaped Path-1 trigger** with a measured cost (silent truncation to `total: 10`, `readiness_reached=False, ids_on_page=0`); and issue 13 element (ii)-3's **reCAPTCHA-anchor signal is withdrawn** — the anchor is present at 256×60 in *healthy* sessions and the challenge popup `api2/bframe` was **0** in both states. Report text only: **`chile_scraper.py` remains at `a595bf7c…`** and `02` was **not** touched, so the `playbook-hash` is unchanged. |
| **R3** | verdict fence, Summary (row 7), issue 3, issue 8, Evidence (**new** *Fourth attempt (R3)*) | the **fourth step-7 attempt**, run for its own sake (a 15-result search-and-download) rather than as a probe. **It reaches the click and calls `_wait_for_detail` for the first time**: `ok=false` after ≈**31 s**, container `display:block`, central-panel text at its at-rest value (**94** headless / **55** headed) — while **one headed session's identical click succeeded**: 40,102 chars in **5 s**, `page_source` 5,182,638 bytes. Root cause of the refusal identified: replaying the SPA's own captured `buscar_sentencias` POST returns HTTP **200** with a **207-byte** body (`La URL solicitada ha sido rechazada … Su numero de soporte es : <12975407294843877253>`, ≈**89 ms**). Detector behaviour then measured **offline** on that body: `_is_f5_block → True`, `_extract_support_id → None` — a **third variant of issue 3** (Spanish, but the support id is wrapped in angle brackets). Also records that `_open_detail` re-runs the search **per document**, so 15 documents cost **15 searches**. **Report text only: `chile_scraper.py` remains at `a595bf7c…`** and `02` was **not** touched, so the `playbook-hash` is unchanged. |

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
| 7 Detail + download | **FAIL** *(run post-review; was NOT RUN)* | **Post-review run: `_open_detail` reached, click never reached, `_wait_for_detail` never called.** In the original pass step 6 failed, so no result had `page >= 2`; the recipe's `results[-1]` fallback was a page-1 row, which cannot distinguish a correct `_open_detail` from one that always lands on page 1 — reported NOT RUN rather than a vacuous green. The post-review run found a `page >= 2` target and still failed, for a measured reason: the search **re-run inside `download_inteiro_teor_url` produced no rows at all** (`_current_result_ids() == frozenset()` on all 31 polls over **61.9 s**), so `_open_detail` returned `False` before the row loop. Criteria 1 and 2 **PASS** (`path is None`, no new `sentencia_*.html`); 3 and 4 not applicable. **Not evidence about `_open_detail`'s page-targeting or about `_wait_for_detail`** — see *Step 7 live run* under Evidence. **R3, later the same day: the click IS reached and `_wait_for_detail` IS measured.** The gate returns `ok=false` after ≈**31 s** with the container `display:block` and the central-panel text still at its at-rest value (**94** headless / **55** headed), while **one headed session's identical click succeeded** (40,102 chars in **5 s**). The refusal that produces the `False` is identified — the F5/Imperva layer rejects the SPA's own `buscar_sentencias` POST with an HTTP `200` block body. Row stays **FAIL** as a step (search 15/15, **0/15 documents saved**); it is no longer an unmeasured fix. See *Fourth attempt (R3)*. |
| 8 Second section | **BLOCKED** | `RuntimeError: F5 block detected while loading penales` / `… salud_cs` — F5 on **navigation** (Case A2), caught correctly by `_is_f5_block` |
| 8b `salud_cs` | **BLOCKED** | Same F5 navigation block |
| 9 LJ mode | **PASS** | `_navigate_to_category` returned `628`; `window.es_lj === true` (literal `true`); `window.id_buscador_activo=628`; no F5. `es_lj` is still **not** branched on in `get_inteiro_links` (open issue 7) |
| 10 Compendio negative | **PASS** | Live: `ValueError: Categoría 'compendio_extranjeria' has no verified id_buscador. See docs/pjud-source.md §11 item 1.` — both required doc references present |

**Count: 9 PASS, 1 FAIL, 1 NOT RUN, 2 BLOCKED** — the classification of the frozen run. **Two rows have since moved:** step 6's `FAIL` is superseded by Phase C (now PASS), and step 7's `NOT RUN` became a `FAIL` when it was run post-review. So the current standing is **10 PASS, 1 FAIL (step 7), 2 BLOCKED**.

> **Arithmetic note (added with patch 1).** 15 rows total. `3 F5 live` = Case B and `5.5` = OBSERVED are not pass/fail categories, leaving 13 classified. PASS rows are 0.1, 0.3, 0.5, 1, 2, 4, 5, 9, 10 — **nine**, not eight; the pre-patch `8 PASS` undercounted. Step 7 moved `BLOCKED` → `NOT RUN` per patch 1, so `BLOCKED` drops to 2 (steps 8, 8b); the post-review run then moved it `NOT RUN` → `FAIL`, which is the row above.

> **Phase C note — the table above is the record of the *original* run and is left frozen.** Phase C re-ran step 6 on 2026-09-17 against the Phase B code path, in a separate session, and **step 6 now PASSES**: `pages == [1,2,3,4]`, `total == 40`, `unique == 40` (`max_results=40`, `categoria=civiles`, `resultados_por_pagina=10`). The same fixed code path was independently verified through the **deployed API** on the same day (30-result job → `pages == [1,2,3]`, 30/30 unique, `court_errors == []`). Step 6's `FAIL` row above is retained as the pre-fix measurement; the issue-9 `FAIL` is **superseded**. See *Phase C* and *Headless / deployed-API probe* under Evidence.

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

    **Update (R3, same day): the rejection body on that route is now on record — but not from the SPA's own XHR.** Replaying the SPA's own captured request (same URL, same cookie jar, `credentials:'include'`, with and without `X-Requested-With`) returned HTTP **200** with the **207-byte** block body quoted under *Fourth attempt (R3)*, in ≈89 ms. So the block is proven to be servable **for this exact endpoint and request shape**, which is the missing half of the `"search accepted, results never arrived"` reading above. What is still **not** captured is the SPA's own failed response — the `Fetch`-domain workaround in the *search XHR verdict* bullet remains unexecuted, and the replay ran after the session had already begun stalling, so it timestamps no first refusal. **Measured consequence, offline and new:** on that body `_is_f5_block → True` but `_extract_support_id → None`, because the id arrives as `<12975407294843877253>` and `soporte es\s*:?\s*(\d+)` cannot cross the `<`. A cheap fix now exists for one sub-case (allow an optional bracketed form), but it does **not** close this issue: `_assert_not_blocked` reads `driver.page_source`, so **any** block body delivered as an XHR payload is invisible to it regardless of language or bracket style.
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

    ### Phase C outcome for issue 12 (2026-09-17)

    **Path 1: CONFIRMED LIVE — as a code path.** In the same session's second probe the search never took effect — 10 landing ids were visible, `_run_search_ui` cleared the container, and **no result node repopulated it for the full 180 s existence wait or the following 60 s change wait** (`count` stayed `Se ha(n) encontrado 855.792 resultados.` throughout). Both waits returned **`ok=False`**, correctly and within their bounds (no hang). `get_inteiro_links` L327 then **parsed the empty DOM** because its `wait_ok` reader is the page-1-impossible `new_on_page == 0` branch. That is Path 1 reproduced end-to-end by direct observation, not by code reading. `_open_detail` L738 discards its wait result in the same way.

    **Scope of that evidence, stated explicitly.** What is observed is the *code path*: a `False` wait is produced, and the caller consumes the DOM anyway. The *trigger* observed here was an unsolved challenge — a **harness condition**, not a production one (a live `recaptcha/api2/anchor` and webworker sat in the DOM and the URL never left `/busqueda?Civiles`; a later baseline measured that same anchor present, 256×60, in *healthy* sessions too, so it was not diagnostic of the challenge either — see *Step 7 live run*). A second, **production-shaped** trigger has since been observed: a **portal-side stall of the search response**, in which the wait times out and the DOM never repopulates — the caller then reads **0 rows** and `get_inteiro_links` returns normally, truncating a ~15,800-match query to `total: 10` (`readiness_reached=False, ids_on_page=0`). That is Path 1 executed with production-shaped consequences (measured 2026-09-17; see *Step 7 live run*). What remains unobserved is the trigger that consumes **landing rows as results** — Case A3 (issue 8) and a query that legitimately returns nothing. So Path 1 is confirmed as a defect that executes, and its consequence is now measured as a **silent truncation**; whether production reaches the *wrong-rows* variant is still unmeasured.

    **Path 2: NOT CONFIRMED — and the leaning previously recorded against it is WITHDRAWN.** Its precondition *is* routine: `pre_search_ids` was empty (`baseline_n == 0`) in Phase C run 1, and in the headless UI-path check `_navigate_to_category` returned `id_buscador_activo=328` with **`n_result_nodes == 0` and `count_text == ''`**. So the guard does run in existence mode as a matter of course. What could not be shown is the predicate *accepting* landing data — and the comparison offered as evidence **against** acceptance does not bear the weight:

    - **The id used to separate landing from search is not attributable to the landing listing.** A post-report re-audit of the raw captures (`/tmp/cl_phase_a_out.json`, `/tmp/cl_probe10.json`, `/tmp/cl_live2.json` — see *Capture re-audit* under Evidence) establishes three facts about the two values in the withdrawn comparison:
      - Run 1's page-1 first id **`200917190`** is confirmed as the **first visible card**: `a13_first_three[0].outerHTML` begins `<div data-idsentencia="200917190" class="card border-info capa_elemento_lista_resultado_busqueda">`.
      - In the *same* capture the id array `a12_counts.ids_all` runs `200705571 → … → 200917190` **ascending**, and its **last** element is that first visible card. The array is therefore a *sorted* set, and its **first** element is the page's **lowest** id.
      - The listing paginates by **descending** `id_sentencia` (page 1 `200705571…200917190`; page 2 `199729629…200134126`). So `200705571` is the **tenth** row of run 1's page-1 set, not a first row — and it is the same value probe 2 recorded as the *settled landing listing's first id*.
    - **Both possible readings of `200705571` destroy the inference, so no leaning survives.**
      - If the landing `first` was read the way the Phase A array was (`sorted(ids)[0]`), the comparison sets a **maximum** against a **minimum** — guaranteed to differ for any two non-empty sets, hence **vacuous by construction**.
      - If it was read DOM-first, then the landing listing's first row is a value that **also** occurs in run 1's page-1 set (at the opposite end), so "they differ" compares a row of one state with a row of a state it overlaps. It is equally consistent with a landing read that caught a **partial render of the search page**.
      Either way the observation is **uninformative** about Path 2. What was established independently, and survives, is that the click **clears the container** — so landing rows on page 1 would require a landing render after ~2.7 s, which was never observed.
    - **No non-empty landing state was ever captured through the scraper's own instrument.** Both landing reads taken on the code's path are **empty**: `cl_live2.5_landing_snapshot {n: 0, count_text: "", first: null}` (step 5 — the P1 criterion was satisfied by an *absence*, via its `n == 0` branch, and D4b's ~1.1 s late render is why) and `cl_probe10.landing {n: 0, first: null}` (Phase C run 1). Probe 2's `n=10` landing read is the **only non-empty landing observation in the workspace**, and it came from a **standalone probe whose read timing is not the code's** — which is exactly why its statistic is unverified.
    - **Instrument artefact to fix, not portal behaviour to explain — the "scoped" selector is not stable.** In the Phase A capture the scoped read (`a2_pre.ids_scoped`) returned **11** unique ids sharing exactly **one** value with the unscoped read (`a12_counts.ids_all`, 10 ids), and on the next samples it returned **0 nodes** (`a2_samples[*].n_scoped == 0`, `delta_scoped = 11`). A selector whose match set changes composition between samples cannot serve as a baseline. This is the resolution of what was earlier flagged as an internal inconsistency between two blocks of the same capture file.
    - Probe 2's forced-empty-baseline wait returned `ok=False, n=0` — it did **not** return the settled landing set. The landing set had already been cleared by the search click and never came back.
    - **Run 1's landing-vs-page-1 discriminator was VACUOUS and proved nothing.** It compared page-1 ids against `landing_ids`, but that snapshot was taken before the ~1.1 s render (D4b), so it was **empty**; `overlap 0/10` and `at1 == settled → False` are the guaranteed answers for an empty set regardless of the truth. **This is the fourth appearance of the degenerate-baseline failure** (run 1's check, the check proposed in review, probe 2, and the re-audit above — which showed the probe-2 value was read against the wrong end of a sorted array rather than against a live landing listing).
    - **`#span_cantidad_resultados` is not a usable Path-2 discriminator either.** It lags the row set: the headless run read `count_text == ''` with `n_result_nodes == 0` after nav and `15.803` with `70` nodes after search, while run 1 showed ids present with the count still on the landing default. A stale count string with a fresh row set is therefore an expected state, and run 1's `855.792`-with-search-ids is explained by lag rather than by landing rows.

    **What the next pass must do differently — the rule now lives in the playbook.** The four failures above produced a rule, and it has been moved out of this report into a standing section: **`02-chile_scraper-playbook.md` §13 "Instrumentation rules"** (with a pointer from §5, beside D4b). The rule is that *a probe must validate that its baseline is non-degenerate before evaluating any discriminator*, and must **refuse to evaluate** rather than report a confident negative when the baseline is an absence. Two additions specific to Path 2, both derived from the re-audit above:

    - **A landing baseline must be a *settled, non-empty* id set, read after the ~1.1 s render (D4b) — not a first id.** No reading of the code's own path in this workspace produced one.
    - **The Path-2 comparison must be set-to-set (landing ids vs page-1 ids), not first-id-to-first-id.** A single-row comparison cannot distinguish "the wait was satisfied by the landing listing" from "the search produced a page-1 with a different first row", and the statistic behind a recorded `first` was not verified in probe 2. On the ranking key itself the evidence is now clear: results are ordered by **descending `id_sentencia`** (see *Capture re-audit*), so "first" is the page's **maximum** id — a definition worth stating in any future probe.

    Until a set-to-set comparison is made against a settled non-empty landing baseline, Path 2 stays **NOT CONFIRMED**: one unverified non-empty landing observation, no inference either way, and — as the packet shows — no instrument yet built that could decide it. Settling it also still depends on the **search XHR response body** (issue 8's Fetch-domain workaround), which remains the only signal that separates Path 2 from an ordinary slow search.

13. **The F5/reCAPTCHA challenge has no automated recovery, so CL's reliability is gated on luck — and the UI cannot surface why a run failed.** This is the **top operational risk** for the deployed path and is separate from issues 3, 4 and 8 (which are all about *detecting* F5). Measured across five navigations on 2026-09-17: two were served the challenge (one *before* the report's Phase A runs, one in probe 2, where the search never took effect for 180 s + 60 s while a live `recaptcha/api2/anchor` and webworker sat in the DOM) and three were not (Phase C run 1, the headless UI check, the two API jobs). The challenge is **intermittent per fresh profile**, and a fresh profile is created on every run because `_shared/chrome_driver.py` sets no `--user-data-dir` — so the cleared-F5 cookie is **never** reused.
>
> **The solver exists but is not wired to Chile.** `modules/captcha_solver.py` implements `solve_and_submit` / `click_checkbox_captcha` / `extract_recaptcha_sitekey` for 2captcha and anticaptcha, and it is imported by exactly **one** module: `_shared/esaj_scraper.py` (the Brazilian e-SAJ courts). `chile_scraper.py` never imports it, and no `JURIS_CAPTCHA_SOLVER` / `JURIS_CAPTCHA_API_KEY` is configured in `.env`. So a challenged CL run has **no recovery path at all**: `_navigate_to_category`'s poll `except Exception: pass` (L257–L264) swallows the timeout, the run continues, and the failure surfaces — if at all — as zero results or a timeout warning. In probe 2 it surfaced only as `ok=False` on a value nobody reads (issue 12 Path 1).
>
> **What "get CL working reliably" therefore requires**, in dependency order: (i) issue 12's two changes, so a failed or unstarted search **fails loudly** instead of returning landing/empty rows; (ii) a challenge-aware outcome, specified below, surfaced on the job's `per_court` entry so the UI can say "blocked" rather than "0 results"; and only then (iii) a solver or a persisted profile, either of which turns a loud failure back into a success. **(i) and (ii) are cheap and are what make the scraper trustworthy; (iii) is the convenience layer.** Doing (iii) first would make the remaining silent-failure paths harder to find, not easier.
>
> **Specification for (ii), so it can be implemented without another round of design.** Three elements:
> 1. **A closed per-court status vocabulary**, carried on every `per_court` entry: **`completed`** (the search ran and was parsed), **`blocked`** (a challenge or F5 layer was detected), **`empty`** (the search ran and the portal reported a genuinely empty result set), **`error`** (anything else, with the exception text). The UI switches on this field and **never** infers state from `len(results) == 0`. Today `blocked`, `empty` and `error` are indistinguishable at the API boundary — that is the defect.
> 2. **A bounded challenge-wait — 30–60 s, not 180 s + 60 s.** Exceeding it reports `blocked`; it never degrades to a silent zero. The observed unbounded waits (180 s existence + 60 s change) are why a challenged run costs minutes and still returns a normal-looking result.
> 3. **A detection signal, named concretely — and the first candidate is withdrawn.** The reCAPTCHA **anchor** iframe is **not** a signal. A post-review baseline measured it present at **256×60, `display:inline`** in the healthy landing state of a working session — i.e. in *every* session — with `window.grecaptcha` defined in both the healthy and the failing state, and the challenge **popup** (`api2/bframe`) count **0 in both**. So the report's own earlier description of it ("the invisible reCAPTCHA anchor", *Phase A probe*) was right and the "measured signal" framing in the previous revision of this item was wrong. What **is** measured to differ is the **stall** signature: `#capa_carga` at `display:block` with a **1452×963** box (idle: `display:none`, 0×0) **plus four empty 1016×674 `src=""` iframes** **plus** `#span_cantidad_resultados` unchanged from its pre-search value **plus** zero visible `[data-idsentencia]` nodes — measured 2026-09-17 in the step-7 run (see *Step 7 live run*). The implementable signal for (ii) is therefore **"overlay visible AND the visible result set unchanged for the whole bounded window"**, with the challenge popup as a second, independent signal — and **neither is a proven challenge detector**: the run that produced the stall signature had **no** challenge on the page at all. (ii) must therefore report `blocked`/`error` on that signature without claiming a captcha was seen.

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

  **Definition of `first` (measured, not assumed — and needed by the Path-2 re-audit below).** `first` is the id of the **first visible card**, and the portal orders results by **descending `id_sentencia`**, so `first` is the page's **maximum** id. Confirmed twice independently: Phase A's page 1 `200705571…200917190` against page 2 `199729629…200134126` (page 2 lies entirely below page 1), and this step's `first_before=200791923` → `first_after=199931811`. Now recorded in `docs/pjud-source.md` §7.1.
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
- **one downloaded file's first 500 chars**: none — **step 7 was NOT RUN in this pass** (see Summary). *(Superseded: step 7 was run after the review and failed without reaching the click — no file was written again, and the reason is measured rather than procedural. See *Step 7 live run*.)* The recipe's `results[-1]` fallback would have produced a page-1 row, which does not exercise the page-targeting logic under test. `/tmp/cl_test` received no new `sentencia_*.html`; this is **not** evidence about `_open_detail`'s correctness. *(R3: **still no file.** `workspace/CL_jurisprudencia/e2e_15/20260917_091541/` holds **0** files after a 15-document attempt whose search half succeeded 15/15 — see *Fourth attempt (R3)*.)*
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

**What this probe does not establish.** (a) It does not time the content growth finely — the `>= 1000` floor is bracketed by the pre/post values, not by a curve, so if a future revision fills the panel slowly the wait may return on a partially-rendered document; that is what the floor is for and it is a heuristic, not a proof. (b) It exercises **one** category (`civiles`) and one result. (c) `download_inteiro_teor_url`'s own behaviour after `_open_detail` returns — including its best-effort "Volver a la página de búsqueda" click and whether `page_source` yields a clean document or the whole 923 KB page with hidden panels included — remains **unverified**. Step 7 has since been run and still could not verify it, because the click is never reached: `_open_detail` returns `False` after its own `_wait_for_results` times out (see *Step 7 live run*).

### Phase C — live re-run of step 6 against the Phase B path

Run 2026-09-17, headful Chrome 152 (Selenium Manager), fresh profile; `chile_scraper.py` at the pinned blob `a595bf7c…`. Instrumentation patches `_run_search_ui` (recording the landing count, ids and `id_buscador_activo`) and `_wait_for_results` (recording `ok`, `reused`, `baseline_n`, `count`, `elapsed`), then calls
`get_inteiro_links("daño moral", max_results=40, filters={"categoria": "civiles", "resultados_por_pagina": 10})` → `max_pages == 6`.

**Result — issue 9 PASSES.**

```
[PROBE] landing BEFORE search: n=0 count='' id_buscador_activo=328 (expected 328)
[PROBE] wait[0]: {"ok": true, "reused": true, "baseline_n": 0, "count": "Se ha(n) encontrado 855.792 resultados.", "elapsed": 1.766}
Chile: page 1 — 10 new (10/40 total)
[PROBE] wait[1]: {"ok": true, "reused": true, "baseline_n": 10, "count": "Se ha(n) encontrado 15.803 resultados.", "elapsed": 3.684}
Chile: page 2 — 10 new (20/40 total)
[PROBE] wait[2]: {"ok": true, "reused": true, "baseline_n": 10, "count": "… 15.803 …", "elapsed": 2.048}
Chile: page 3 — 10 new (30/40 total)
[PROBE] wait[3]: {"ok": true, "reused": true, "baseline_n": 10, "count": "… 15.803 …", "elapsed": 1.338}
Chile: page 4 — 10 new (40/40 total)
Chile: total results: 40
pages: [1, 2, 3, 4]   total: 40   unique: 40
sample: {"page": 1, "id_sentencia": "200917190", "rol": "C-3662-2026", "fecha": "16-09-2026"}
1. pages superset of [1,2,3] : True
2. len(results) >= 30        : True   40
3. no duplicate id_sentencia : True   40/40
```

- **The pagination defect is closed by measurement.** Four pages, 40 results, 40 unique — against a pre-fix `pages == [1]`, `total == 10`. The pager waits took **3.684 / 2.048 / 1.338 s**, i.e. the change predicate paced the loop across the ~2.0 s empty window without a sleep, and `wait[1..3]` each report `baseline_n == 10` (the consumed page's ids), so the predicate was comparing against a real baseline.
- **B-2b did NOT fire.** No `no new results on page N — stopping. readiness_reached=…` line appears, so the retry path added in Phase B was **not exercised** by this run. Per the work order it is recorded as **unexercised**, not as coverage — pagination simply worked. Its offline coverage is also zero (see *Known coverage gaps*).
- **Criterion 5 (wall-clock ≤ 5 s per page) was never printed by the runner, so it is unrecorded.** The per-wait `elapsed` values above are ≤ 3.684 s, which is consistent with it passing, but the criterion as written was not evaluated and is not reported as green.
- **Criterion 7 passed for the wrong reason, and this is recorded rather than papered over.** It asserted the post-search count differs from the landing snapshot; the landing snapshot was `''`, so it passed for *any* non-empty count. Its own `seen[0]` count was `855.792` — the **landing default**, not the search's `15.803`. The criterion's intent ("nor the landing default") is right; its implementation could not distinguish the two without knowing the landing constant, and it did not. **Criteria 6 and 7 passing must not be read as evidence about Path 2.**
- **Path 2's precondition is live and routine.** `baseline_n == 0` on the page-1 wait means the L327 guard ran in **existence mode**. Per the reasoning in issue 12 this is expected whenever `_navigate_to_category` wins the race with the ~1.1 s landing render, and the run confirms that is common rather than rare.

### Probe 2 — settled landing vs forced-empty baseline (Path 2)

One navigation, `/tmp/chile_phase_c2_20260917.py`. It polls the landing listing until it settles, then reproduces the run-1 predicate state by calling `_wait_for_results(previous_ids=frozenset())` directly, then a proper change-mode wait.

```
[PROBE] SETTLED landing: n=10 count='Se ha(n) encontrado 855.792 resultados.' first=200705571 after 2.20s
WARNING - Chile: timed out waiting for results            (t+3m25s, the 180 s existence wait)
[PROBE] existence-mode wait -> ok=False n=0 count='Se ha(n) encontrado 855.792 resultados.' first=None
[PROBE] at1 == SETTLED LANDING ? False
[PROBE] overlap at1 vs landing : 0/0
WARNING - Chile: timed out waiting for results            (t+4m26s, the 60 s change wait)
[PROBE] change-mode wait -> ok=False n=0 count='Se ha(n) encontrado 855.792 resultados.' first=None
[PROBE] at2 == SETTLED LANDING ? False
[PROBE] at2 == at1 ? True
```

**Reading, stated carefully.**

- `at1` is the **empty set**, so `at1 == settled → False` and `overlap 0/0` are **vacuous** — the fourth appearance of the degenerate-baseline failure. The probe did not decide Path 2; it only failed to refute it via an instrument that could not have refuted it.
- What it *does* establish, as direct observation: the landing listing **does exist and settles** (`n=10`, landing count `855.792`, first id `200705571` at 2.20 s), and in this session the search **never took effect** — the container was emptied by the click and stayed empty for 180 s + 60 s, while `count` never left the landing default. **Annotation, post-report re-audit:** the `n=10` and the count `855.792` stand as direct observations; the *first id* `200705571` does **not** support the inference it was used for — see *Capture re-audit* below.
- A **live reCAPTCHA anchor and webworker** were present in this session (confirmed via the DevTools target list), and the URL never left `/busqueda?Civiles`. So the failure mode here is plausibly an unsolved challenge — a **harness artifact** — and must not be reported as a production-shaped stall. The *mechanism* it exercised (`wait_ok=False` with a caller that ignores it) is production-shaped regardless of the cause.
- **No F5 was detected** (`_assert_not_blocked` did not raise) and the URL stayed on the portal. "No F5" therefore does **not** imply "the search worked" — a direct input to issue 8's framing, and the first observation of a *non-F5* "search never took effect" mode.
- The landed id `200705571` **differs** from run 1's page-1 first id `200917190` — the comparison this report previously treated as evidence *against* Path 2 having fired. **That reading is withdrawn: the comparison is uninformative, not merely weak. See *Capture re-audit* immediately below.**

### Capture re-audit — where the Path-2 leaning came from, and why it is withdrawn

Run 2026-09-17, post-report, against the raw captures still on disk (`/tmp/cl_phase_a_out.json`, `/tmp/cl_phase_a_out2.json`, `/tmp/cl_probe10.json`, `/tmp/cl_live2.json`). Read-only, no browser session. Its purpose is narrow: the Path-2 leaning was the only part of this report arguing a **negative**, so its two ids were re-derived from the raw captures instead of restated from the report's own prose.

**What the captures actually contain.**

| Fact | Source | Value |
|---|---|---|
| First visible result card on the `daño moral` page 1 | `cl_phase_a_out.json` → `evidence.a13_first_three[0].outerHTML` | `<div data-idsentencia="200917190" class="card border-info capa_elemento_lista_resultado_busqueda">` |
| The id array for that same page | `cl_phase_a_out.json` → `evidence.a12_counts.ids_all` (70 nodes, 10 unique) | `200705571, 200775922, 200789966, 200812286, 200827634, 200828293, 200839965, 200842042, 200851256, 200917190` — **ascending**, and the first card is its **last** element, so the array is a *sorted* set and its first element is the page's **lowest** id |
| The state after the pager click | `cl_phase_a_out.json` → `evidence.final_snapshot` (`cursor: 1`) | `199729629 … 200134126` — entirely **below** page 1's range ⇒ descending `id_sentencia` ordering |
| Run 1's settled page-1 read | `cl_probe10.json` → `p1_stable.snap.first` | `200917190` — agrees with the DOM read above |
| The landing read on the code's own path | `cl_live2.json` → `5_landing_snapshot` | `{n: 0, count_text: "", first: null}` |
| The Phase C landing read | `cl_probe10.json` → `landing` | `{n: 0, first: null}` |
| The pre-click read, both selectors, same instant | `cl_phase_a_out.json` → steps `[A.2] pre` and `evidence.a2_pre` | `n_all=70 u_all=10` but `n_scoped=70 u_scoped=11` |

**What follows.**

1. **The leaning's two values are not two states.** `200917190` is provably the first card of the **post-search** page 1. `200705571` is provably the **lowest** id of that same page's set — the tenth row of a descending listing — and it is *also* the value probe 2 recorded as the landing listing's first id. Either the landing `first` was read as `sorted(ids)[0]` (then the comparison is max-vs-min and **vacuous by construction**), or it was read DOM-first (then it compares a row against a set that row is an element of). **Neither separates landing from search, so "they differ" carries no information.**
2. **The code has never read a non-empty landing state.** Both landing reads taken on the scraper's path are `n=0`, and step 5's P1 criterion was *satisfied by that absence* (its `n == 0` branch). Probe 2's `n=10` landing read is the only non-empty landing observation anywhere in the workspace, and it came from a standalone probe whose read timing is not the code's. So the landing baseline that issue 12's fix (1) depends on **has never been observed at all**.
3. **The instrument is at fault, twice, and the second fault is a hard contradiction.** (a) The landing read happens before D4b's ~1.1 s render, which yields an empty baseline — the degenerate-baseline failure. (b) At the same instant, over the same node count (70/70), the scoped read returns **11** unique ids against the unscoped read's **10**. That is *impossible* if the scoped set is a subset of the unscoped one — so the two reads are not measuring the same population, and `a2_pre.ids_scoped` (whose 11 values share exactly one id with `ids_all`) has **no established provenance**. It is recorded as an **instrument defect** and must not be cited as evidence about the portal.
4. **Nothing here rehabilitates Path 2 — it removes the argument that Path 2 had not fired.** The verdict is unchanged in kind and stronger in form: **NOT CONFIRMED**, leaning withdrawn, on the ground that the evidence is *uninformative* rather than thin, and with the constructive requirement now stated (a **settled, non-empty** landing id set compared **set-to-set** against page 1 — see *Open issue 12*).

### Headless / deployed-API probe — the path the UI actually uses

The UI never calls `chile_scraper` directly. `modules/routes_search.py` does `_get_scraper_class("CL")` → `importlib.import_module("chile_scraper")` → `scraper_cls(headless=True)` → `search_with_criteria(criteria)`. This probe reproduces that construction exactly, then exercises the **running server** on `:8000`.

**(a) Direct, `headless=True`:**

```
nav:    ok=True id_buscador=328 elapsed=18.61
search: ok=True n=10 elapsed=4.46  sample.rol='C-5810-2025'  sample.id_sentencia='200791920'
after_nav:     n_result_nodes=0   visible_ids=0   count_text=''        id_buscador_activo=328
               f5_title=False     recaptcha_anchor=True  recaptcha_grecaptcha=True
after_search:  n_result_nodes=70  visible_ids=70  count_text='Se ha(n) encontrado 15.803 resultados.'
               f5_title=False
```

**(b) Deployed API — `POST /api/search`, asynchronous job, results read from `/api/results/{job}`:**

| Job | Request | Outcome |
|---|---|---|
| `ab55c743` | `max_results=10` | `{'court': 'CL', 'status': 'completed', 'total': 10}`, `/api/results` returned **10 rows, 10/10 unique**, all with `texto_preview` — e.g. `200791920 \| C-5810-2025 \| 12-09-2026`, `200748938 \| C-12950-2025`, `200535350 \| C-953-2026` |
| `e92ce75e` | `max_results=30` | `{'court': 'CL', 'status': 'completed', 'total': 30}`, **`pages == [1, 2, 3]`, 30/30 unique, `court_errors == []`**, all rows carry `texto_preview` |

- **This is the strongest single piece of evidence in the report for the fix being live.** The pre-fix code could not return three pages — issue 9 truncated at `pages == [1]`, `total == 10`. A 30-result job over `pages [1,2,3]` can only come from the change-predicate path.
- **The running server is not stale.** It started `Tue Sep 15 03:56:33`; `chile_scraper.py` was last modified by commit `2f4a2cd` at `08:18:05` on 2026-09-17. The fix is live anyway because `_get_scraper_class` imports the module **lazily** (inside the function, per `importlib.import_module`), so a module edit is picked up without a restart. Worth knowing operationally — it cuts both ways.
- **It establishes that `headless=True` works**, which corrects an earlier claim in this pass that it could not. The earlier claim confused "no CAPTCHA solver is wired in" (true) with "headless cannot pass the gate" (false — these runs were never challenged). **The accurate statement is: CL works through the UI when F5 does not challenge it, and hangs or fails when it does, with no automated recovery.**
- **The empty landing baseline reproduced on the UI's own path.** `after_nav` reports `n_result_nodes == 0` and `count_text == ''` at `t=18.61 s`, i.e. `pre_search_ids == frozenset()` — Path 2's precondition, on the deployed path, headless. It was harmless here only because the landing listing never rendered at all, so the search rows were the first non-empty set. This is what raises issue 12's stakes: existence mode is the **normal** state, not an edge case.
- **The count text lags the row set** (see issue 12), which is why it cannot serve as the Path-2 discriminator.
- **No F5 on any of these five navigations**, one of which was a 30-result three-page run.

### Step 7 live run — `_open_detail` reached, no click, and a reproducible portal stall

Playbook `02` §7 was run **after the report review** (2026-09-17, 09:00–09:10, fresh headful Chrome per session, pinned blob `a595bf7c…`, **no code change in between**). The purpose was to stop `_wait_for_detail` being the one Phase B fix that is reasoned rather than measured. **Outcome: it is still unmeasured — but the reason is now measured, and it is not `_open_detail`.**

| # | Search | Outcome | Verdict on the attempt |
|---|---|---|---|
| A1 | `daño moral`, civiles, `max_results=30` → `pages [1,2,3]`, 30 rows in **34.7 s** | target `page=2 id=200134126` found; `download_inteiro_teor_url` aborted in **0.004 s** | **void — harness bug, not an artifact defect.** My own probe wrapper did `ids[0]` on the `frozenset` returned by `_current_result_ids()` (`'frozenset' object is not subscriptable`). The artifact was never entered. |
| A2 | same → `pages [1]`, **10 rows** | no `page >= 2` target → step not run | the pager had begun stalling: `page 2 — 0 new`, `page 3 — 0 new`, both waits timing out at 30 s |
| A3 | same → `pages [1,2]`, 20 rows | target `page=2 id=200791920`; `download_inteiro_teor_url → None` after **61.9 s** | `_open_detail` **reached**: `_navigate_to_category → 328` (0.002 s, cached section), `_click_next_page → True`, then `_wait_for_results` **timed out twice (30.6 s + 30.6 s)** with `_current_result_ids() == frozenset()` on all **31** polls → `_open_detail → False`. **`_wait_for_detail` was never called.** A3's search-phase row counts are additionally unreliable: the same `ids[0]` bug fires on a **non-empty** set, so any `_ready` evaluation with rows present raised and was counted as `ok=False`. The *stall* evidence is unaffected (an empty set never takes the buggy branch). |
| B | landing + `_run_search_ui` only | landing **healthy**, search **stalled 31.3 s** | `landing_settled_2.5`: `body_len=6752`, `70` visible nodes, `10` unique ids, count `855.792`; `after_search`: `body_len=929`, **`0` visible nodes**, count still `855.792`, `#capa_carga` `display:block` 1452×963. `ids after search: n=0` |
| C | same, with body-text capture | landing **healthy**, search **stalled 35 s** | identical stall; table below |

**Criteria, per playbook §7:** 1 (`path is None` **or** the file exists) **PASS**. 2 (on `None`, no new `sentencia_*.html`) **PASS** — `/tmp/cl_test` gained nothing. 3 and 4 (`size > 5 KB`, body contains `ROL`/`Caratulado`, sidecar present) **not applicable**, because the download never returned a path. Step 7 is therefore **FAIL by criterion 3 being unreachable, not by a failed assertion**.

**The stall, captured (probe C).** Healthy landing vs 0.5 s / 10 s / 35 s after `_run_search_ui`:

| Reading | Healthy landing | +0.5 s | +10 s | +35 s |
|---|---|---|---|---|
| `document.body.innerText` length | 6752 | **929** | 929 | 929 |
| visible `[data-idsentencia]` nodes (unique ids) | 70 (10) | **0 (0)** | **0** | **0** |
| `#span_cantidad_resultados` | `855.792` | `855.792` (**unchanged**) | unchanged | unchanged |
| iframes | `TS_Injection` + anchor 256×60 + 1 empty | + **4 × 1016×674, `src=""`, `display:block`** + 2 × `buscar_sentencias?onComplete=…` | 4 overlay frames | 4 overlay frames |
| `#capa_carga` | `display:none`, 0×0 | `display:block`, 1452×963 | block | block |
| `api2/bframe` (challenge popup) | 0 | **0** | 0 | 0 |
| F5 body markers | false | false | false | false |

The body text is the **same 929 characters** at +0.5 s and at +35 s — header, nav, "Avisos", the search form, the stale count, the ordering control — with the results region **empty** and a full-viewport overlay (`#capa_carga`, 1452×963) on top of it. Nothing on the page says anything is wrong: no challenge popup, no error text, no F5 body, no support id. The two zero-size `buscar_sentencias?onComplete=…` frames appear with the search and are gone by +10 s, corroborating the `Document`-type `buscar_sentencias?onComplete=…` requests already recorded in the *search XHR verdict* bullet above.

**Four conclusions.**

1. **`_wait_for_detail` is still unmeasured *by this run*, and now for a measured reason.** The click is never reached because `_open_detail`'s own `_wait_for_results` times out and it then returns `False` **correctly**. This run is therefore **neither evidence for nor against** Phase B's detail fix, and must not be quoted as either. *(Superseded as a statement about the gate — not about this run: the R3 attempt below does reach the click and invokes `_wait_for_detail`, which returns `ok=false` after ~31 s with the container open and the panel text at its at-rest value. See *Fourth attempt (R3)*.)*
2. **The failure is specific to the search `POST`, not to the session.** In both B and C the *landing* page of the same session rendered normally (`6752` chars, 70 nodes, 10 ids, count `855.792`) while the search never repopulated the results region. `_navigate_to_category` works; the search does not. That is precisely the precondition playbook §7's own warning names — “`download_inteiro_teor_url` re-runs the search … it re-fires the very `POST` that Case A3 rejects. Under Case A3 this step cannot pass, and its `path is None` outcome is **not** evidence about `_open_detail`” — arriving **on its own**, with no challenge posed.
3. **The stall produces a silent truncation, and that is the load-bearing finding.** In A2 the same stall turned a ~15,800-match query into `total results: 10`, logged as `no new results on page 3 — stopping. readiness_reached=False, ids_on_page=0`, and returned normally. `get_inteiro_links` **reports success with 10 rows**, and nothing at the API boundary distinguishes that from “the query has 10 matches”. This is issue 12 **Path 1**'s mechanism with a **production-shaped trigger** and a measured cost — see the Path-1 scope note in issue 12.
4. **The reCAPTCHA anchor iframe is not a challenge signal; the earlier naming of it as one is corrected.** In the healthy landing state the anchor is present at **256×60, `display:inline`** — the same box it had during probe 2's failure — and `window.grecaptcha` is defined in both states. The challenge **popup** (`api2/bframe`) was **0 in both**, so no challenge was posed in this run at all. Issue 13 element (ii)-3 is amended accordingly.

**Not claimed.** (a) The **cause** of the stall is not established. It began mid-session (A1's search was clean, 30 rows / 34.7 s; by A2 the pager was stalling; by B and C the search itself stalled) and it persisted across **three fresh Chrome profiles**, so it is not cookie/profile state — but it correlates with *this client's* access pattern (≈6 automated searches in 10 minutes) and no search response was captured, so “the portal rate-limited us” is a **plausible hypothesis, not a finding**. (b) The signature above is a **stall** signature; it is **not** established as a *challenge* signature, because no challenge was observed. (c) The `buscar_sentencias` response body was **not** captured, so issue 8's Fetch-domain workaround remains unexercised here. *(Partially superseded by R3, which captured the rejection body on that route **by replay** — the SPA's own response body still was not captured. See the next section.)*

### Fourth attempt (R3) — the click is reached, `_wait_for_detail` is measured, and the refusal is identified

Run 2026-09-17 later the same day, headful **and** headless, pinned blob `a595bf7c…`, **no code change**. Unlike the R2 attempt this was not a probe: it is the 15-result search-and-download the pipeline exists to perform, run because the previous attempt had left `_wait_for_detail` as the one Phase B fix with no live call.

**Result: the search half works and is repeatable; the download half saved 0 of 15 documents, and the reason is now measured.** `workspace/CL_jurisprudencia/e2e_15/` contains **0 files**.

| Phase | Measured |
|---|---|
| Search, `max_results=15`, `civiles` | **15/15**, pages `[1,2]`, 15 unique ids — **25.1 s** and **25.6 s** on the two runs whose timings were recorded |
| Download, 15 documents | **0/15 saved.** `_open_detail` **reached**; `_wait_for_detail` **invoked**; every `download_inteiro_teor_url` returned `None` |

**`_wait_for_detail` is no longer unmeasured — this is its first live call, and it fails for a measured reason.**

| Reading | Headless (`/tmp/cl_dl15.py`) | Headed (`/tmp/cl_run15.py`) |
|---|---|---|
| `_wait_for_detail(...)` return | `ok=false` | `ok=false` |
| elapsed | ≈ **31.0 s** | ≈ 31 s |
| `#capa_contenedor_detalle_sentencia` `display` | **`block`** | `block` |
| `#panel_contenedor_central_detalle_sentencia` text length | **94** | **55** |

The container **does** open on click, so the click is delivered and the handler runs; the panel text stays at its **at-rest** value (the *Detail-swap* probe measured **94** chars **before** any click). **Conclusion 1 of the R2 run is therefore superseded: the click is reachable and the gate is correct — the document never arrives.**

**Control: the same click succeeds when the request is served.** In one headed session the identical click on the identical page filled the panel to **40,102 chars in 5 s**, with `page_source` at **5,182,638 bytes** (saved `/tmp/cl_headed_ok.html`). `_DETAIL_MIN_CHARS = 1000` therefore has the clearance the *Detail-swap* probe predicted, and the click path is **not** the defect. This is the only successful detail load observed in the session.

**The refusal, captured and then reproduced.** The SPA's own search payload was captured by wrapping the page's global `window.llamada_ajax` **before** running the search (the CDP `getResponseBody` route recorded above returns `-32000`, and a `XMLHttpRequest.prototype.send` hook never saw this request):

```
POST https://juris.pjud.cl/busqueda/buscar_sentencias
  _token=<laravel>, filtros=<JSON string>, id_buscador=328,
  numero_filas_paginacion=10, offset_paginacion=0, orden=recientes, personalizacion=false
```

Replaying that request from the page context — `fetch`, `credentials:'include'`, with and without `X-Requested-With: XMLHttpRequest` / `Accept` — returned, in ≈ **89 ms**:

```
HTTP 200, 207-byte body
<html><head><title>La URL solicitada ha sido rechazada</title></head><body> . (2) .
<br><br>Su numero de soporte es : <12975407294843877253><br><br>
<a href='javascript:history.back();'>[Go Back]</body>
```

That is the rejection body `docs/pjud-source.md` §1 records, **served for the site's own request shape**. So the stall is the F5/Imperva layer refusing the POST — not a parser, selector or predicate defect, and not a parse artefact of an empty result set. **This does not substitute for capturing the SPA's own failed response** (the `Fetch`-domain workaround is still unexecuted), and the replay ran after the session had already begun stalling, so it reproduces the refusal without timestamping the first one.

**Detector behaviour on that body, measured offline and new** (`/tmp/cl_detect_check.py`, calling the shipped `staticmethod`s directly — no browser, no re-implementation): `_is_f5_block → True` (markers `La URL solicitada ha sido rechazada`, `Su numero de soporte`), `_extract_support_id → None`. The support id **is** present but wrapped in angle brackets, and `re.search(r"soporte es\s*:?\s*(\d+)")` cannot cross the `<`; the bare-digit control `Su numero de soporte es : 1234567890` returns `'1234567890'`. **This is a third variant of issue 3** — Spanish, like the form the regex was written for, so it is *not* the English-only gap already recorded. It matters less than the delivery channel: `_assert_not_blocked` reads `driver.page_source`, so a block body arriving as an **XHR payload is invisible to it** whatever its language (issue 8).

**Why 15 documents cost 15 searches.** `_open_detail` re-runs `_navigate_to_category` + `_run_search_ui` + the pager loop for **every** document, so `download_all_inteiro_teor(15)` issues **15 searches** where 1 would do. Measured: documents 1–2 returned `None` in ~**3 s** with no timeout logged; documents 3–15 each logged `Chile: timed out waiting for results` once or twice and then `could not open detail`. The search phase, run once, succeeded 15/15 — the **15×** amplification is the difference between a session that is served and one that is refused.

**One of the failures was the harness's, not the artifact's.** The e2e wrapper read page 1 after the search phase had left the DOM on the **last** page fetched, so page-1 targets were reported `no_visible_node` / `row_absent`; a corrected wrapper (`dom_page()` / `go_to_page()`) accounts for the current page. That does not explain the failures above — those are timeouts, not misses — but it is why one early headed run scored 0 against a healthy portal, and it is recorded so the number is not mistaken for a portal condition.

**Not claimed.** (a) The refusal is **not** shown to be caused by request *rate*: it correlated with this client's own session and no other client was observed, so “the portal throttled us” remains a **hypothesis, not a finding**. (b) **No WAF bypass was attempted or is proposed**, and the ~45 minutes of repeated attempts in this session plausibly worsened the condition; the operational reading is the opposite of automation. (c) Clicking rows already on screen instead of re-running the search per document is the right shape of a fix, but it was **not proven end to end** — only the first click was reached, and it was refused.
