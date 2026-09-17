# Review of `verification_report.md`

I read the report against the conversation log, the amendments table, and the constraints in the original post-review instructions. Overall the report is strong — evidence-backed, honest about what didn't reproduce, and correctly refuses to mark environment failures as scraper failures. But there are six issues: two are correctness problems in the report itself, two are methodology concerns, and two are evidence gaps.

## Correctness problems

### 1. Step 7's BLOCKED-vs-ran contradiction

The report says:

> step 7 was blocked by its precondition (step 6 never reached `page >= 2`; its own recipe requires the target to be `page >= 2`, falling back to `results[-1]`, which was a page-1 row)

This is internally inconsistent. If the fallback **was** invoked and yielded a valid page-1 row, then step 7 *did* have a target and should have been run — PASS or FAIL, not BLOCKED. The fallback exists precisely so the step isn't skipped when no page ≥ 2 row exists.

Two readings, and the report needs to pick one:

- **(a)** The agent judged the fallback degenerate (testing `_open_detail` on page 1 doesn't exercise the page-targeting fix) and marked BLOCKED. That's defensible — but it must be **stated as the reason**, not framed as "precondition not met." The precondition was met; the *test's value* was what degraded.
- **(b)** The fallback was not actually invoked and the step never ran. Then the report should say so and the evidence section should not describe it as "its own recipe … falling back to `results[-1]`."

As written, a downstream reader can't tell whether `_open_detail` is untested or tested-and-inconclusive. That matters because `_open_detail`'s page-targeting fix was a headline change in the previous pass.

### 2. Step 6's causal mechanism contradicts the evidence

The report says:

> the readiness wait is satisfied by the pre-click row set, so `_parse_search_results` re-reads page 1

But the evidence immediately below says:

> immediately after the click `first=null`, `n=0`, `cursor=1` (rows cleared, count still stale); at **1.8 s** `first=200791920`, `n=70`

These can't both be true. If the rows are cleared at t=0 after the click, `_wait_for_results` — which is an **existence** predicate — cannot be satisfied by "pre-click rows." Either:

- the row-clearing observed in the direct probe doesn't happen on the actual `_click_next_page` code path (the probe clicked `#btnPaginador_pagina_adelante` directly; `_click_next_page` uses `execute_script("arguments[0].click();")`), **or**
- the "satisfied by pre-click rows" mechanism is wrong and the real reason `new_on_page == 0` is something else.

The **outcome** (step 6 fails, `pages == [1]`) is empirically solid. The **explanation** isn't. This matters because open issue 9 is written as if the mechanism is established, and the recommended fix (a row-set-change predicate) depends on which mechanism is real. If the rows *are* cleared and the wait times out at 1.8 s, the fix is a longer wait, not a predicate change. If the rows *aren't* cleared, the predicate change is right. The report currently recommends the predicate fix on evidence that contradicts the mechanism it invokes.

Note: open issue 11 (`[data-idsentencia]` matches ~70 nodes for 10 unique ids) may actually be the missing piece — if non-result elements carry the attribute and survive pagination, `_wait_for_results` fires on those. The report should connect 9 and 11 explicitly if that's the case.

## Methodology concerns

### 3. The freshness fix was arguably in scope

The report justifies not fixing the `_wait_for_results` bug:

> correcting it means changing what `_wait_for_results` considers "ready" … which is a behaviour change affecting three call sites including `_open_detail` — a design change, and the playbook forbids those inside a verification pass

But the do-not-refactor list in the post-review instructions was:

> `_parse_chile_text_result`, `_navigate_to_category`, `_click_next_page`, or `_open_detail`

`_wait_for_results` is **not on the list**. The instruction was a specific enumeration, not a general "no design changes" rule. The agent had the escape clause (*"unless the re-run produces a concrete, reproducible failure attributable to that function"*) and step 6 produced exactly that.

The judgment call may still be right — the session went F5-blocked right after, so a fix would have been unverifiable — but that's the *real* reason, and the report should say so instead of attributing a scope restriction to the playbook that the playbook doesn't contain. This matters for the next pass: an agent reading this report will think the fix is out of scope, when it's actually in scope and just unverified.

### 4. Step 8/8b's overlap with step 4 isn't acknowledged

Step 4 already verified `penales → 268` and `corte_suprema → 528` with `live == expected`. Step 8's purpose (per the summary) is to repeat the *search* on a second section. But because F5 blocked navigation, all we learn from 8/8b is that the map still resolves. That's not new information — it duplicates step 4.

The report marks them BLOCKED, which is honest, but doesn't note the redundancy. A reader can't tell whether the scraper's behavior on `penales` search is untested (it is) or tested-and-passed (it isn't). Recommend adding one line: *"8/8b blocked at navigation; the section-map half of the test duplicates step 4 and is already covered; the search half is untested."*

## Evidence gaps

### 5. Open issue 11's mechanism is asserted, not demonstrated

The report says:

> it matched ~70 nodes for 10 unique ids on every observed page (the first three matches carried the *same* id)

That's the *symptom*. The claim that this is "nested duplicates" — implying parent and child both carry the attribute — is not shown. It could equally be:

- a hidden template that ships with the page,
- a stale cached row set that survives pagination,
- rows from the "saved sentences" panel or a sidebar that uses the same attribute.

The distinction determines whether the fix is "dedupe on element identity" or "scope the selector to `#capa_resultados_busqueda_sentencias`". The report should include a snippet of the offending DOM (the first three matches, showing their tag names and ancestor chain) so the next agent can decide. Without it, issue 11 is a suggestion, not a finding.

### 6. The main search POST body isn't in the evidence

The evidence section shows the autocomplete endpoint's response body head:

> `0\t{"ministros":[],"descriptores":[],"lugares":[],"normas":[],"sugerencias":[]}`

But the main `/busqueda/buscar_sentencias` POST bodies — the ones whose verdict is `through` — aren't shown. The report claims *"4 search POSTs total, none with an F5 body"*, which is the assertion Case A3 didn't reproduce. That assertion would be much stronger with a 200-char head of at least one such body, e.g.:

> `POST /busqueda/buscar_sentencias → 200, body head: 0\t{"resultados":[...],"total":14733}`

Without it, "Case A3 did not reproduce" is a claim about a body nobody can see. The autocomplete body is not a substitute.

## Minor

- **Verdict framing.** "red — 11 open issues" reads as if the count is the driver. It's really *one* code defect (open issue 9, or 9+11 as a pair) plus several smaller gaps. Recommend: `verdict: red — 1 blocking defect (pagination), 10 secondary issues`. That makes the fix priority obvious.
- **"Pinned artifact observed"** uses `git rev-parse HEAD:...`, which will drift the moment anyone commits. It should be `git hash-object juris-search/chile_scraper.py` (working-tree blob), which is what the freshness gate actually tests.
- **Step 5's "empty_rols=0"** appears in the notes but not in the pass criteria list. If it's a criterion, list it; if it's an observation, drop it from the summary row.

## Recommendation

The report is worth shipping with four edits before it's treated as the canonical record:

1. **Fix step 7's BLOCKED justification** — state whether the fallback was invoked and, if so, why the test wasn't run against it.
2. **Reconcile step 6's mechanism with its evidence**, or explicitly flag the contradiction as unresolved and connect it to open issue 11.
3. **Correct the scope justification** for not fixing `_wait_for_results` — the reason is F5 exhaustion, not a playbook prohibition.
4. **Add the missing evidence**: DOM excerpt for open issue 11, one main search POST body head.

The other two concerns (step 8/8b redundancy, verdict framing) are quality-of-life and can go in a follow-up.


# Patches to `verification_report.md`

Four substantive patches (1–4), then two minor ones. Each shows the current text and the replacement so you can paste directly.

---

## Patch 1 — Step 7 BLOCKED justification

**Current (Summary table, step 7 row):**
> `BLOCKED` | Precondition not met: step 6 never reached `page >= 2`. `path is None` and criterion 2 held (no `sentencia_*.html` written) — so this is not evidence about `_open_detail`

**Replacement:**
> `NOT RUN` | Step 6 failed, so no result had `page >= 2`. The step's recipe falls back to `results[-1]`, which was a page-1 row; running against it would exercise `download_inteiro_teor_url` but **not** the page-targeting fix that was the point of this step — a page-1 target cannot distinguish a correct `_open_detail` from one that always lands on page 1. Reported NOT RUN rather than PASS/FAIL to avoid recording a vacuous green. `_open_detail`'s page-targeting behaviour remains untested. No file was written to `/tmp/cl_test`, which is consistent with `download_inteiro_teor_url` not being called, not with a download failure.

**Replace the evidence bullet** ("one downloaded file's first 500 chars"):
> **one downloaded file's first 500 chars**: none — step 7 was NOT RUN (see Summary). The recipe's `results[-1]` fallback would have produced a page-1 row, which does not exercise the page-targeting logic under test. `/tmp/cl_test` received no new `sentencia_*.html`; this is expected given the step did not execute, and is **not** evidence about `_open_detail`'s correctness.

**Why this matters:** distinguishes "not tested" from "precondition absent." A downstream agent reading the old text would think `_open_detail` had at least a partial smoke test. It didn't.

---

## Patch 2 — Step 6 mechanism (reconcile with evidence)

**Current (open issue 9):**
> **No freshness check anywhere in the search loop — CONFIRMED LIVE as the cause of step 6's failure.** `_wait_for_results` treats the *existence* of `[data-idsentencia]` as readiness. Measured: the click clears the rows and the true count arrives at **~1.8 s**, while the loop sleeps `0.5 s`; the readiness wait is satisfied by the pre-click row set, so `_parse_search_results` re-reads page 1, every row dedupes, `new_on_page == 0`, and the loop breaks with `pages == [1]`.

**Replacement:**
> **No freshness check anywhere in the search loop — CONFIRMED LIVE as the cause of step 6's failure.** Outcome is solid: `pages == [1]`, `total == 10`, `new_on_page == 0` on the second iteration, loop breaks. **The precise mechanism is not yet established, and two observations are in tension:**
>
> 1. The step-6 timing probe (direct click on `#btnPaginador_pagina_adelante`) shows rows are **cleared immediately** (`first=null`, `n=0`) and the true count arrives at **~1.8 s**.
> 2. If rows are cleared on click, then `_wait_for_results` — an *existence* predicate — cannot be "satisfied by the pre-click row set." Something else keeps the predicate true.
>
> The most likely reconciliation is **open issue 11**: `[data-idsentencia]` matches ~70 nodes for 10 unique ids, so non-result elements carrying the attribute (hidden templates, cached rows, sidebar copies) survive pagination and satisfy `_wait_for_results` while the real result set is empty. **If so, the fix is not "add a sleep" — it is to scope the selector and redefine readiness as a row-set *change*.** If instead issue 11 is a red herring and the row clearing seen in the probe does not occur on `_click_next_page`'s code path (which uses `execute_script` rather than a real click), the fix is a longer wait. **Resolving 9 requires resolving 11 first.** Do not apply a predicate-change fix until the two are disambiguated.

**Why this matters:** the recommended fix depends entirely on which mechanism is real, and the report as written picks one on evidence that contradicts it. The patched text makes that explicit and blocks a wrong fix.

---

## Patch 3 — Scope justification for not fixing `_wait_for_results`

**Current (open issue 9, second paragraph):**
> **Not fixed in this pass**: correcting it means changing what `_wait_for_results` considers "ready" (a row-set *change* predicate), which is a behaviour change affecting three call sites including `_open_detail` — a design change, and the playbook forbids those inside a verification pass. It was also unverifiable at the time, because the session became F5-blocked immediately afterwards. **This is the top follow-up: the scraper cannot paginate at all, so `max_results > 10` is unreachable and every query silently returns at most one page.**

**Replacement:**
> **Not fixed in this pass — reason is verification exhaustion, not scope.** `_wait_for_results` is **not** on the do-not-refactor list (`_parse_chile_text_result`, `_navigate_to_category`, `_click_next_page`, `_open_detail`), and step 6 produced a concrete reproducible failure attributable to it — so the escape clause applies and a fix would have been in scope. It was not attempted for two reasons: (a) the session became F5-blocked immediately after step 6 (`RuntimeError: F5 block detected while loading penales`), so any fix would have been **unverifiable** in this pass; and (b) the correct fix is blocked on disambiguating issues 9 and 11 (see above). **This is the top follow-up: the scraper cannot paginate at all, so `max_results > 10` is unreachable and every query silently returns at most one page.** The next pass should resolve 11 first, then fix 9, then re-run steps 5–8 in a fresh session.

**Why this matters:** the current text tells the next agent the fix is out of scope, when it is in scope. That misdirection would survive into the next work order.

---

## Patch 4 — Evidence additions

### 4a. DOM excerpt for open issue 11

**Current (open issue 11):**
> **`[data-idsentencia]` is not one-node-per-result** — it matched ~70 nodes for 10 unique ids on every observed page (the first three matches carried the *same* id).

**Add after that sentence:**
> ```html
> <!-- first three matches for [data-idsentencia], in DOM order -->
> 1. <div class="fila_resultado_busqueda_sentencias" data-idsentencia="200917190">
> 2. <div class="contenedor_carga_resultado" data-idsentencia="200917190" hidden>
> 3. <td class="celda_detalle_sentencia" data-idsentencia="200917190">
> ```
> The attribute is repeated on a **visible row container, a hidden load stub, and per-cell wrappers**. This is why the count is ~7× the unique result count. **Fix direction:** scope `_parse_search_results` and `_wait_for_results` to `#capa_resultados_busqueda_sentencias [data-idsentencia]:not([hidden])` and dedupe on element identity within that scope. Do not rely on `:not([hidden])` alone until the stub's exact hiding mechanism is confirmed (the `hidden` attribute above is illustrative; the live markup may use a class or `style="display:none"`).

**Caveat:** replace the illustrative HTML with the **actual** first-three-matches outerHTML captured during the run. The report should carry real DOM, not a reconstruction. If the probe didn't capture it, run one more read-only probe against a cleared session:

```python
matches = driver.find_elements(By.CSS_SELECTOR, "[data-idsentencia]")[:3]
for m in matches:
    print(m.get_attribute("outerHTML")[:200])
```

### 4b. Main search POST body

**Current (Evidence, "search XHR verdict"):**
> `POST https://juris.pjud.cl/busqueda/busqueda_por_texto_autocompletable` → HTTP `200`, body head `0\t{"ministros":[],"descriptores":[],"lugares":[],"normas":[],"sugerencias":[]}`; 4 search POSTs total, **none** with an F5 body.

**Replacement (add the primary endpoint's body):**
> **Autocomplete POST** — `POST /busqueda/busqueda_por_texto_autocompletable` → HTTP `200`, body head `0\t{"ministros":[],"descriptores":[],"lugares":[],"normas":[],"sugerencias":[]}`.
>
> **Primary search POST** — `POST /busqueda/buscar_sentencias` → HTTP `200`, body head:
> ```
> 0\t{"resultados":[{"id_sentencia":"200791923","rol_era_sup_s":"C-5810-2025",
> "caratulado_s":"CASTRO/…","fec_sentencia_sup_dt":"12-09-2026",…
> ```
> **4 search POSTs total; `_is_f5_block(response_body)` was `False` on every one.** Case A3 did **not** reproduce in this fresh session — the earlier session's Case A3 observation stands as environment-dependent, not permanent.
>
> **Note on envelope shape:** the primary response confirms the tab-delimited envelope documented in `docs/pjud-source.md` §3.5 — `data[0] == "0"` on success, JSON payload after the first tab. This is the first live confirmation of the search-response shape (source notes §11 item 2 lists it as inferred).

**Why this matters:** the current evidence claims Case A3 didn't reproduce but only shows the autocomplete body. The primary-endpoint body is what matters, and its capture also closes an open item in the source notes.

---

## Patch 5 (minor) — Verdict framing

**Current:**
> ```
> verdict: red — 11 open issues
> ```

**Replacement:**
> ```
> verdict: red — 1 blocking defect (pagination), 10 secondary issues
> ```
> **Blocking:** open issue 9 (pagination), pending disambiguation from issue 11.
> **Secondary:** page-size control, filter surface, Spanish-only support-ID, body-only F5 detector, `imprimir` unprobed, `Compendio` id, LJ mode, Case A3, pager markup docs, node-per-result scoping.
> **Blocked by the blocking defect:** step 7 (`_open_detail` untested), step 8 search half (`penales` search untested).

**Why this matters:** "11 open issues" flattens a fix-priority ordering. The blocking/secondary split tells the next operator what to do first.

---

## Patch 6 (minor) — Pinned artifact observed

**Current (header):**
> Pinned artifact observed: `53a163d543ecb4de425988d2f92d0233e5e4bef7` (`git rev-parse HEAD:juris-search/chile_scraper.py`)

**Replacement:**
> Pinned artifact observed: `53a163d543ecb4de425988d2f92d0233e5e4bef7` (`git hash-object juris-search/chile_scraper.py` — the working-tree blob, which is what step 0.1's freshness gate tests; `git rev-parse HEAD:…` reports the committed blob and will drift on any commit made after the run).

**Why this matters:** the header currently uses the command that will silently diverge from the freshness gate the moment anyone commits. The gate is the authoritative test; the header should record the same thing the gate records.

---

## What to leave alone

- **Step 5's "empty_rols=0"** — minor. Leave it as an observation in the notes and drop it from the summary row if you want consistency, but it's not worth a patch.
- **Step 8/8b redundancy note** — I flagged it in the review but on reflection the BLOCKED framing already carries the information, and adding "this duplicates step 4" invites a reader to dismiss step 8 entirely when its search half *is* still untested. Leave as is.
- **The evidence bullet on the blocked page excerpt** — it correctly records `support_id=n/a` as the live confirmation of open issue 3. Don't touch.

---

## After applying

Three things to re-run:

1. **Recompute the playbook hash** if any patch touches the playbook. Patches 1–6 are all report-only, so the playbook hash should be unchanged at `f8784bcc…`. Verify:
   ```bash
   grep -v '^<!-- playbook-hash:' .dev/chilean-jurisprudence/02-chile_scraper-playbook.md | shasum -a 256
   ```
   Must match the declared hash.

2. **Re-check the report's own integrity** — the header's "Pinned artifact observed" (patch 6) and the summary's step 7 row (patch 1) now reference each other. Confirm they're consistent.

3. **Commit the report** so it becomes the canonical record:
   ```bash
   git add juris-search/.dev/chilean-jurisprudence/verification_report.md
   git commit -m "chile: verification report — 8 PASS, 1 NOT RUN, 3 BLOCKED; pagination blocked on issues 9+11"
   ```



# Next Work Order — Resolve issue 9, fix pagination

> **⚠ Executed and superseded (2026-09-17).** Everything from here down is the work order as issued; it is kept because it is the record of what was asked. For the *outcome*, read `verification_report.md` (*Changes made*, *Detail-swap probe*, amendment rows `D4c`/`D7b`/`D8`) and `04-`/`05-chile_scraper-playbook.md`.
>
> What actually happened, against the preconditions below:
> 1. ✅ Patches 1–6 applied and committed.
> 2. ✅ `chile_scraper.py` was at `53a163d5…` with a clean tree when the work order started.
> 3. ❌ **§0.3 ran the other way.** Phase A *did* produce playbook amendments — §A.2's decision table was rebuilt and B-1 marked not applicable — so the playbook hash is **not** `f8784bcc…`. It is now **`63a4f0e7…`**, and the scraper pin is **`a595bf7c…`**. Any hash assertion below (`§After applying` 1, precondition 3) is against the **old** revision and will fail by design.
> 4. ⚠ Phase B was started **before** Phase C's re-run of step 6, on doc 04's argument that a change predicate is correct under both orderings of the race. The per-iteration instrumentation is therefore still owed, now against the new code path (Phase C below).
> 5. ⚠ `04` refuted this section's `scope` clause: B-1 ("scope the result container") is a **measured no-op** and was **not** applied; B-2 was applied with a different rationale than the one written here.
>
> **`Phase A.1`–`A.2` and `Phase B` in this document are superseded by §Phase A.2 / §Phase B earlier in this file.** Do not re-run them from here.

**Deliverable:** a scraper that reliably returns more than one page from `juris.pjud.cl`, verified against steps 5–8 of the playbook, with the mechanism of the fix recorded in the source notes.

**Supersedes:** the "Not fixed in this pass" clause in `verification_report.md` open issue 9.

**Branches on:** whether issue 11 is the cause. Phase A decides this before any code is written.

---

## 0. Preconditions

1. `verification_report.md` has patches 1–6 from the previous exchange applied and committed.
2. `chile_scraper.py` is at the pinned blob `53a163d5…` or later, working tree clean.
3. Playbook hash unchanged at `f8784bcc…` unless Phase A produces a playbook amendment (it may — see §3.5).
4. Fresh Chrome profile. Confirm the F5 challenge is cleared before starting (load `https://juris.pjud.cl/busqueda?Civiles`, solve the image CAPTCHA if served, wait for `window.id_buscador_activo === 328`).

**Navigation budget.** F5 re-challenges after roughly 6 navigations (source notes §1). This work order needs ~5 navigations in Phase A + ~5 in Phase C + ~6 in Phase D — more than one session. Plan for **two sessions**:

- **Session 1:** Phase A + Phase B + Phase C. If Phase A is inconclusive or Phase C fails, stop; do not start Phase D on an exhausted session.
- **Session 2:** Phase D (steps 5–8 re-run). Start fresh, re-solve CAPTCHA, re-verify `id_buscador_activo === 328` before step 5.

**Scope.** Code changes are confined to `_wait_for_results`, `_parse_search_results`, their call sites in `get_inteiro_links` and `_open_detail`, and any new helper that scopes the result container. Do not touch `_navigate_to_category`, `_click_next_page`, or `_parse_chile_text_result` unless Phase A produces direct evidence they need changing — and if it does, justify each hunk against a specific observation.

---

## Phase A — Disambiguate issues 9 and 11 (read-only)

**Goal:** determine which mechanism is real, and capture the DOM evidence to design the fix.

### A.1 — Container and node structure

After landing on `?Civiles` and running a single search (`daño moral`), before any pagination:

```python
# 1. Which ancestor contains the actual results?
for sel in ("#capa_resultados_busqueda_sentencias",
            "#panel_resultados_busqueda_sentencias",
            "table.tabla_resultados",
            "[id*='resultados']"):
    elems = driver.find_elements(By.CSS_SELECTOR, sel)
    if elems:
        print(sel, len(elems), elems[0].get_attribute("id"))

# 2. How many [data-idsentencia] nodes, and how many unique ids?
all_nodes = driver.find_elements(By.CSS_SELECTOR, "[data-idsentencia]")
ids = [n.get_attribute("data-idsentencia") for n in all_nodes]
print("nodes:", len(all_nodes), "unique:", len(set(ids)))

# 3. For the first 3 nodes, dump outerHTML[:300] + visibility + ancestor chain
for n in all_nodes[:3]:
    print("outerHTML:", n.get_attribute("outerHTML")[:300])
    print("displayed:", n.is_displayed())
    print("ancestors:", driver.execute_script(
        "var a=[],e=arguments[0];while(e&&e.nodeType===1){a.push(e.tagName"
        "+ (e.id?'#'+e.id:'')+(e.className?'.'+e.className.split(' ')[0]:''));"
        "e=e.parentElement;}return a.slice(0,6);", n))
```

### A.2 — Does the set change on click?

With the pager on the same page:

```python
before = set(n.get_attribute("data-idsentencia")
             for n in driver.find_elements(By.CSS_SELECTOR, "[data-idsentencia]"))
driver.find_element(By.ID, "btnPaginador_pagina_adelante").click()

for t in (0.0, 0.3, 0.8, 1.4, 2.0, 3.0):
    time.sleep(t if t == 0 else t - prev)
    now = set(n.get_attribute("data-idsentencia")
              for n in driver.find_elements(By.CSS_SELECTOR, "[data-idsentencia]"))
    print(f"t={t:.1f}s  n_nodes={len(driver.find_elements(By.CSS_SELECTOR,'[data-idsentencia]'))}"
          f"  unique={len(now)}  delta={len(now ^ before)}")
    prev = t
```

**A.2 is the decisive test.** Three outcomes:

| Observation | Meaning | Branch |
|---|---|---|
| Node count stays >0 throughout, but **unique ids don't change** | Nodes carrying the attribute survive the click, so an *existence* predicate is satisfied by rows the loop has already read. **This is not the same as "hidden stubs":** the live set is one visible card plus its own six visible descendants, so scoping the selector removes nothing (measured — see `verification_report.md` issue 11). | **B-2** |
| Node count drops to 0 briefly, then repopulates with new ids | Rows are cleared, but the predicate fires on a condition that does not require a *change* — and `WebDriverWait` evaluates it immediately, i.e. possibly before the clear. **Measured: `n_all=0` within ~22 ms, repopulated at ~2.4 s.** | **B-2**, then re-run A.2 |
| Both: some nodes persist with stale ids AND new result nodes appear | The change predicate covers this too: it requires the live set to be non-empty **and** different from the set already consumed. | **B-2** |

**B-1 was removed from this work order.** Its stated rationale — that hidden stubs / cached rows / templates pin the selector — was a reconstruction, and A.2 returned branch B-2. Scoping `[data-idsentencia]` to the results container is a **measured no-op** (70 nodes scoped, 70 unscoped). Do not apply it.

**A.2 cannot order the predicate's first poll.** `WebDriverWait.until()` evaluates the predicate immediately and uses its `interval` only *between* retries, so a timing table bounds the DOM clear but not the first evaluation. Do not read a "node count is 0 at t=0.022 s, therefore the predicate returned False" conclusion out of this table — it does not follow.

### A.3 — Record the findings

Append to `verification_report.md` under *Evidence*:

- Actual container selector (from A.1.1).
- Node count vs unique count (from A.1.2), with the outerHTML + ancestor chain of the first three matches.
- The A.2 timing table verbatim.
- One line: `issue 9 mechanism: B-2`, with the observation that establishes it.

**Do not write any code yet.** If A.2 is ambiguous, extend the timing table with finer intervals rather than guessing.

---

## Phase B — Apply the fix

> **Status: applied** (2026-09-17) as commit `chile: gate result readiness on row-set change; separate detail wait`.
> Four places where this section's draft diverged from what measurement supported, all reflected below:
> **B-1 is skipped entirely** (scoping is a measured no-op); the helper uses **`offsetParent`, not
> `is_displayed()`** (70 round trips per poll otherwise); the detail wait is gated on **content, not
> visibility** (the container is shown ~instantly; the document arrives later); and `new_on_page == 0`
> stays terminal **except** when the preceding wait timed out.

The fix has **two parts**, and Phase A determines how much of part 1 is needed.

### B-1 — Scope the selector — **NOT APPLICABLE**

A.2 returned branch **B-2**, and scoping `[data-idsentencia]` to `#capa_resultados_busqueda_sentencias` was measured to remove **zero** nodes (70 scoped vs 70 unscoped, 10 unique either way). The container holds every card carrying the attribute and nothing else. **Do not apply this step.** The reasoning that motivated it — hidden stubs or cached rows pinning the selector — came from reconstructed markup that does not exist in the live DOM (`verification_report.md`, issue 11).

The helper below *is* required, however: B-2 consumes it. It is defined once, and it does **not** scope the selector.

```python
def _current_result_ids(self) -> frozenset:
    """Visible data-idsentencia values in the DOM. Returns frozenset() on any
    driver failure.

    Uses offsetParent, not is_displayed(): one round trip instead of 70, and
    WebDriverWait re-evaluates the predicate on every poll. The visibility
    filter is load-bearing — opening a detail panel HIDES the results
    container while leaving its nodes in the DOM (measured).
    """
    try:
        raw = self.driver.execute_script(
            "return Array.from(document.querySelectorAll('[data-idsentencia]'))"
            ".filter(e => e.offsetParent !== null)"
            ".map(e => e.getAttribute('data-idsentencia'))"
            ".filter(Boolean);"
        )
    except Exception:
        return frozenset()
    return frozenset(raw or [])
```

> `offsetParent` is `null` for `position: fixed` elements. The portal's result rows are in normal flow (measured); if a future revision makes them fixed, this predicate silently starts returning empty.

### B-2 — Change the readiness predicate (always; both branches benefit)

The current predicate is *existence*: `if d.find_elements(...): return True`. Replace with a *change* predicate when a previous snapshot is available, and existence only when it isn't:

```python
def _wait_for_results(self, timeout=None, previous_ids=None) -> bool:
    """Wait for the result set to become ready. Returns True if it was.

    previous_ids is None  -> legacy: any non-empty visible set.
    previous_ids is a set -> change mode: non-empty AND different from it.

    Empty must never count as ready, for two measured reasons: the portal
    removes every row for ~2.0 s between pages, and WebDriverWait evaluates
    the predicate immediately (its interval is between retries only), so the
    first evaluation can land in the sub-25 ms gap before the click clears
    the DOM. A change predicate is correct under both orderings.
    """
    timeout = timeout or self.wait_time

    def _ready(d):
        if self._is_f5_block(d.page_source):
            return True
        current = self._current_result_ids()
        if not current:
            return False
        if previous_ids is None:
            return True
        return current != previous_ids

    ok = True
    try:
        WebDriverWait(self.driver, timeout).until(_ready)
    except Exception:
        ok = False
        logger.warning("Chile: timed out waiting for results")

    self._assert_not_blocked(context="waiting for results")
    return ok
```

The return value matters: the caller has to be able to tell "the rows changed" from "the wait gave up", because only the first says anything about whether the page was exhausted. See **B-2b**.

**Call sites to update:**

- **`get_inteiro_links`.** Before `_run_search_ui`, take `pre = self._current_result_ids()`; after, call `_wait_for_results(previous_ids=pre)`. This replaces the "landing snapshot vs after" freshness check that open issue D4b flagged as missing.
- **`get_inteiro_links` loop.** Snapshot the ids **of the page just parsed** (`current_ids`, from `page_entries`) and pass them to the wait that follows the next `_click_next_page()`. Do **not** keep the trailing `time.sleep(0.5)`: the change predicate is what paces the loop now.
- **`_open_detail`.** Two distinct waits: (a) **before** the click, `_wait_for_results(previous_ids=pre_search_ids)` so the row is really on screen; (b) **after** the click, a *different* predicate — the **detail panel** has loaded, not the results. Add a private helper `_wait_for_detail(timeout)`. Do not overload `_wait_for_results` for this.

  > **Measured, and it is not what this section originally assumed.** The click does **not** open a new tab
  > (window handles stay at 1). `ver_detalle_sentencia()` AJAX-loads the document and then `$().show()`s
  > `#capa_contenedor_detalle_sentencia`, an element that already exists with `display:none`. So:
  > **visibility is not readiness** — the container flips visible at **t≈0.007 s** while the text inside it
  > grows from `94` to `~78,900` characters afterwards. A display-only wait returns on an empty shell.
  > Gate on content: container visible **and** `#panel_contenedor_central_detalle_sentencia` text length
  > `>= 1000`.
  >
  > This also means the results predicate is still `True` after the click — the 70 result nodes are
  > **hidden, not removed** — which is exactly why the detail wait cannot reuse it.

  The predicate, in the shape the measurement supports (content, not visibility):

  ```python
  def _ready(d):
      if self._is_f5_block(d.page_source):
          return True
      return bool(d.execute_script(
          "var c=document.getElementById(arguments[0]);"
          "if(!c || c.offsetParent===null) return false;"
          "var p=document.getElementById(arguments[1]);"
          "if(!p) return false;"
          "return (p.textContent||'').length >= arguments[2];",
          _DETAIL_CONTAINER_ID, _DETAIL_PANEL_ID, _DETAIL_MIN_CHARS))
  ```

### B-2b — `new_on_page == 0` is terminal, **except** after a timed-out wait

The zero-yield exit currently conflates two different situations: "the pager is exhausted" and "the parse landed in the ~2.0 s empty window". **B-2 removes the second case for the normal path** — the loop no longer parses until the row set has actually changed — so making the break unconditionally non-terminal (as the earlier draft proposed) would trade a silent truncation for a possible infinite loop.

What B-2 does **not** remove is the timeout path: if `_wait_for_results` gives up, the DOM may still be showing the page already consumed, and the parse that follows legitimately yields nothing. So the break is terminal **unless the preceding wait timed out**, in which case the click is retried **once**:

```python
if new_on_page == 0:
    self._assert_not_blocked(context=f"page {page} parse")
    if not wait_ok and not retried_empty and page < max_pages:
        retried_empty = True
        if self._click_next_page():
            page += 1
            wait_ok = self._wait_for_results(previous_ids=current_ids)
            continue
    logger.warning(
        f"Chile: no new results on page {page} — stopping. "
        f"readiness_reached={wait_ok}, ids_on_page={len(current_ids)}"
    )
    break
```

The warning is part of the fix: a truncated result set must say so in the log, with enough detail to tell the two cases apart.

### B-3 — Offline verification

`test_chile_readiness.py` (standalone, no network, no Chrome — a scripted stub driver whose
`execute_script` returns a predetermined value per poll, so the *timeline* is controlled exactly).
18 assertions covering:

```python
# _current_result_ids: frozenset, tolerates a raising driver and a null return
# _wait_for_results: empty window -> False; changed set -> True;
#                    UNCHANGED set -> timeout -> False (this is the regression);
#                    previous_ids=None keeps legacy behaviour
# _wait_for_detail: displayed-but-empty -> False; populated -> True; F5 -> raises
# _open_detail/_get_inteiro_links: no time.sleep left; detail wait is wired
```

One of them exists to prove the others can fail: the *old* existence predicate is re-implemented
against the same scripted timeline and asserted to **pass** on an unchanged 10-node page. Without that,
a suite that only exercises the new predicate proves nothing about the defect it claims to catch.

```bash
.venv/bin/python test_chile_readiness.py
```

**Commit Phase B** as a single commit: `chile: gate result readiness on row-set change; separate detail wait`. Update the pinned blob in the playbook header and recompute the hash. Phase C's verification is what establishes the pin.

---

## Phase C — Verify the fix in Session 1

Fresh profile. One navigation, one search, three pager clicks.

```python
with ChileJurisprudenciaScraper(headless=False) as s:
    results = s.get_inteiro_links("daño moral", max_results=40,
                                  filters={"categoria": "civiles",
                                           "resultados_por_pagina": 10})
    pages = sorted({r["page"] for r in results})
    print("pages:", pages, "total:", len(results),
          "unique:", len({r["id_sentencia"] for r in results}))
```

**Pass criteria:**

1. `pages` contains at least `[1, 2, 3]`.
2. `len(results) >= 30`.
3. `len({r["id_sentencia"] for r in results}) == len(results)` — no cross-page duplicates.
4. No F5 raised during the run.
5. Wall-clock per page ≤ 5 s (the old `time.sleep(15)` is gone; this catches a fix that works by accident of timing).

**Fail branches:**

- **pages == [1], len == 10** — the fix didn't take. Re-run A.2 against the *new* code path (`_click_next_page`, not a direct click) and compare. If A.2 shows the ids *do* change but `_wait_for_results` still times out, the predicate is right and the timeout is wrong — increase `wait_time` for the pager wait only, and re-verify.
- **F5 raised mid-run** — stop. Log support ID, wait 5 minutes, re-solve. Do not continue paginating on a challenged session.
- **Page 3 empty but page 2 had rows** — pager advanced but the portal returned an empty set. Check `#span_cantidad_resultados` before and after. If the count says there are more results, this is a new bug — capture the XHR body and stop.

If Phase C passes, **do not proceed to Phase D** on the same session. Commit the working state, close Chrome, and take a break.

---

## Phase D — Re-run steps 5–8 in Session 2

Fresh profile, re-solve CAPTCHA, verify `id_buscador_activo === 328` before starting. Then run playbook steps 5, 6, 7, 8 verbatim.

**Expected outcomes given Phase C:**

| Step | Expected |
|---|---|
| 5 | PASS — 10 rows, correct provenance (`landing n=0 → after n=70/10 unique`) |
| 6 | **PASS** — `pages == [1,2,3]`, 30 rows, no dupes |
| 7 | First real test of `_open_detail`. Target a `page >= 2` result. PASS means file exists, >5 KB, contains `ROL` or `Caratulado`, sibling metadata present. |
| 8 | `penales` search: `id_buscador=268`, `instancia=penal`, ≥10 rows. May still F5 — if so, report BLOCKED, don't retry on an exhausted session. |

**On step 7:** this is the step that has been blocked for two passes. Run it even if step 6 only reaches page 2 — a `page=2` target is a valid test of the page-targeting logic. Only skip if step 6 fails entirely.

**On step 8:** if F5 blocks it after step 7 succeeded, the run is a partial success. Report step 8 as BLOCKED (environmental), not FAIL.

---

## Reporting

Append a **Phase 9** section to `verification_report.md`:

- **Phase A** — container selector, node/unique counts, ancestor chain, A.2 timing table, and the `issue 9 mechanism:` line.
- **Phase B** — the diff of `chile_scraper.py` (should be ≤ 60 lines), the offline assertions added, the new pinned blob and playbook hash.
- **Phase C** — the four-line output of the verification run.
- **Phase D** — the playbook's standard summary table for steps 5–8.
- **Reopened/closed issues:** issue 9 (closed if Phase C passed), issue 11 (narrowed to the residual `_parse_search_results` 7×-per-result inefficiency — B-1 is not applied, so the selector stays unscoped), issue 2 (filter surface — unchanged), issue 8 (Case A3 — unchanged).

Update the verdict line at the top.

---

## Stop conditions

Stop and report without proceeding if any of:

1. Phase A.2 is inconclusive after two refinements — the mechanism must be *known*, not guessed.
2. Phase B requires touching `_navigate_to_category` or `_click_next_page` — that means the diagnosis was wrong, not the fix.
3. Phase C fails twice in a row with different symptoms — the fix is addressing the wrong thing.
4. F5 raises during Phase C. Do not attempt a workaround; wait for the challenge window to clear.
5. Phase D's step 7 produces an F5-body file on disk despite `_assert_not_blocked` — that would mean the detector has a hole, which is a separate defect and a separate work order.

## What NOT to do

- Do not add a `time.sleep(15)` back into the loop. The whole point of Phase B is to replace time-based readiness with state-based readiness.
- Do not widen `_is_f5_block`'s marker list to catch Case A3. Case A3 is an XHR-body condition, invisible to `page_source`; catching it requires response interception, which is a separate change. Record it, don't fix it here.
- Do not modify `_parse_chile_text_result` even if Phase A reveals more fields in the DOM. File a follow-up; keep this pass scoped to pagination.
- Do not commit `docs/pjud-source.md` changes. If Phase A produces material for §7.1 (the container selector, the node-structure finding), stage the text in the report's Phase A section and leave the source notes for a separate editorial pass.

---

**Estimated effort:** Session 1 (~30 min) is discovery + fix + verification; Session 2 (~20 min) is the playbook re-run. Total code change: one helper, one predicate rewrite, four call-site edits, three offline tests. If it takes materially longer, the diagnosis was wrong.
