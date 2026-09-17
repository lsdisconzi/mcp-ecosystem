# Where things stand, and what to do next

> **Outcome (2026-09-17, added after the fact).** Both decisions were taken as recommended, and both held up.
> - **Decision 1 — gate skipped, Phase B applied.** B-2 landed as a *change* predicate returning a bool, plus the non-terminal `new_on_page == 0` handler this doc insisted on (retry once, and only after a timed-out wait). Work order **B-1 was not applied** — the detail probe and the 7-node histogram both confirmed it is a measured no-op.
> - **Decision 2 — playbooks committed.** `02`'s declared hash was reproducible from `HEAD` before this pass, and is again at the new revision.
> - **One thing this doc did not anticipate.** Its §"Either way, a change-predicate is the correct fix" reasoning was applied to `get_inteiro_links`, but the same error existed one layer down in `_open_detail`: clicking `Ver sentencia` **hides** the results container without removing its 70 `[data-idsentencia]` nodes, so its post-click `_wait_for_results` was satisfied by *invisible* nodes. `_open_detail` therefore needed the fix too, and additionally a **content-gated** wait (`_wait_for_detail`), because the detail container flips `display:block` at ~7 ms while its text grows from 94 to ~78,900 chars. Full evidence in `verification_report.md` §*Detail-swap probe*.
> - **Superseded below:** the hash table in Decision 2 and the `must equal f8784bcc...` check are now historical — the current declared hash is **`63a4f0e7…`** and the scraper pin is **`a595bf7c…`** (Phase B moved the blob; the playbook hash moved with the amendment).

The agent did solid work here — two independent probes, a self-correction on an overclaim, and honest "not captured" reporting on the one piece of evidence (patch 4b's response body) that couldn't be obtained. The three commits are narrowly scoped to the report, as instructed. I'll weigh in on the two open decisions, then flag what I see in the evidence.

## Decision 1 — should Phases B/C/D wait?

**No. The probe has resolved enough to proceed. The proposed gate is over-cautious.**

The agent's stated reason is that "step 6 must be re-run with `max_pages` / `len(entries)` / `new_on_page` logged per iteration — Phase C's premise needs confirming."

But the probe *is* the confirmation. Two independent runs show:

- Rows clear within ~22 ms of the click.
- Rows stay empty for ~2.0 s.
- Rows repopulate with 10 **entirely different** ids.
- `_click_next_page()` returns `True` and the JS cursor moves `0 → 1`.

Step 6's observed failure (`pages == [1]`, `total == 10`) is *exactly* what you'd get if `_wait_for_results` returns on the empty window and `_parse_search_results` then reads nothing. There's no plausible alternative mechanism left. Re-running step 6 with the same code would just reproduce the same failure — it wouldn't add information.

What the agent is actually worried about is subtler and worth naming: **`WebDriverWait.until()` evaluates its predicate immediately.** So the ordering question — "does the predicate fire before or after the 22 ms clear?" — is not settled by bounding the clear. The agent's correction to the report is right, and it's an important correction. But it doesn't gate the fix:

- If the predicate fires **before** the clear, it sees stale rows → returns `True` → pagination loop parses stale data → `new_on_page == 0` → break. Fix: change predicate.
- If the predicate fires **after** the clear, it sees empty → returns `False` → polls every 0.5 s → sees rows back at ~2 s → returns `True`. Then pagination *should* work. But step 6 shows it doesn't.

Either way, a **change-predicate** is the correct fix, because it's robust to both orderings. That's B-2, and it's ready to apply.

The remaining real issue is the second one the agent identified: the `new_on_page == 0` break in `get_inteiro_links` is terminal, and it conflates "end of results" with "parse landed in the empty window". That's a defect **independent** of the predicate fix, and it must be fixed in the same pass, otherwise a predicate timeout on any page silently truncates the result set.

**Recommendation:** proceed to Phase B. Skip the "re-run step 6 first" gate — it's a diagnostic that the probe already delivered. Apply B-2 (change predicate) *plus* a non-terminal `new_on_page == 0` handler. Verify in Phase C with the instrumentation the work order already requires (`max_pages`, `len(entries)`, `new_on_page` per iteration). If Phase C's per-iteration log doesn't match the probe's timeline, *then* stop and re-diagnose — but design for the fix now.

## Decision 2 — commit the playbook

**Yes, definitively. Not doing so leaves a real integrity problem in the record.**

The agent documented the situation clearly:

| Source | hash (hash-line stripped) |
|---|---|
| `HEAD` | `3b9f08eb…` |
| index | `a6afbc5d…` |
| worktree (declared in report) | `f8784bcc…` |

The report and the playbook header both cite `f8784bcc…`, which is reproducible **only from an uncommitted working tree**. The doc's own acceptance check (`grep -v … | shasum`) passes trivially because it hashes the same file the value came from. A fresh checkout of the repo would produce `3b9f08eb…`, which does not match the report's declared pin.

The "report-only commit scope" was a per-session constraint, not a permanent rule. Committing the playbook now is what makes the report's own pin meaningful.

Two things to commit together:

1. `02-chile_scraper-playbook.md` — the amended playbook, whose declared hash must match `HEAD`.
2. `03-chile_scraper-playbook.md` — the work order, since the report now cites it.

After the commit, verify:

```bash
git show HEAD:juris-search/.dev/chilean-jurisprudence/02-chile_scraper-playbook.md \
  | grep -v '^<!-- playbook-hash:' | shasum -a 256
# must equal f8784bcc...
```

If it doesn't, the header needs to be updated to the hash that `HEAD` actually produces, and the report's declared hash (which cites the playbook) needs the same update.

Leave `violation-refiner/build/` alone — unrelated changes.

## What I see in the evidence that isn't in the report yet

The agent's edits are correct as far as they go, but a few things are worth folding in before Phase B starts:

### 1. Patch 4b's failed capture is itself an open issue

The report now says (correctly) that the response body was not captured. But it doesn't say **why**, and the reason matters:

> `getResponseBody` FAILED: unhandled inspector error `{"code":-32000,"message":"No data found for resource with given identifier"}`

That's CDP evicting the body before `getResponseBody` runs. It's a known limitation of CDP network capture when the request completes before the response listener resolves. The practical workaround is to enable `Fetch.enable` with `responseStage: Response` and capture the body from the `Fetch.requestPaused` event, not from `Network.responseReceived`. That's a one-line change in a future probe.

This matters because **Case A3's existence is still unresolved**. Case A3 was the earlier session's observation of an F5 rejection delivered inside the XHR body (HTTP 200, `page_source` clean). The fresh-session probes did not reproduce it, and the response body that would settle the question was evicted. So Case A3 stands as: "observed once, not reproduced, body not captured." The report should say that explicitly rather than implying non-reproduction means it can't happen.

### 2. The `[data-idsentencia]` finding is bigger than patch 4a suggests

The probe's anatomy is:

> 70 nodes = 10 results × **7 nodes per result**: `div.card` + 4 × `span.estilo_resultado_titulo` + `button.btn-primary` + `form`

All 70 are **visible** (`displayed=70`). The playbook's claimed classes (`fila_resultado_busqueda_sentencias`, `contenedor_carga_resultado`, `celda_detalle_sentencia`) don't exist. And critically:

> scoped (`#capa_resultados_busqueda_sentencias [data-idsentencia]`) = 70 nodes, unscoped = 70 nodes.

So not only is B-1 a no-op — the *stated reason* for B-1 in the work order ("excludes hidden stubs") was based on fabricated markup. The report corrects this, but a follow-up should rewrite work-order §A.2's decision table to reflect that:

- The 7×-multiplication is **intrinsic** to how the portal marks the result card — one id per result, replicated across the card and its children.
- Scoping cannot remove it; the correct optimization is `_parse_search_results` picking **one** node per `id_sentencia` (e.g. `[data-idsentencia]:not(:has([data-idsentencia]))` — the outermost node) and skipping the rest, or by early-exit on first node per id. This is an efficiency improvement, not a correctness one, and can be deferred.

### 3. `_open_detail` inherits the same race

`_open_detail` (per the current code) clicks `Ver sentencia` on the row, then calls `_wait_for_results` — the same existence predicate. When the row is clicked, the results container is likely cleared (the detail panel loads in its place). So `_open_detail` is subject to the same race as pagination.

The Phase B instructions already call this out ("(b) after clicking, a **different** predicate"), but the current `_open_detail` code doesn't have a separate helper. Ensure Phase B adds one; otherwise the fix to `get_inteiro_links` will leave `_open_detail` broken in exactly the same way the earlier verification report already failed to test.

## What to do, concretely

Short answer to the agent's two questions:

1. **Proceed to Phase B.** Design the fix now. Instrument Phase C. If the instrumentation disagrees with the probe, stop and re-diagnose. Don't gate on a step-6 re-run whose outcome is already determined.

2. **Commit the playbooks** (`02` and `03`) before Phase B, and verify the declared hash is reproducible from `HEAD`. Update the header and the report if it isn't. This is a five-minute fix that closes the integrity gap.

Then, in Phase B, the fix has **three** parts, not two:

| # | Fix | Why |
|---|-----|-----|
| B-2 | Change-predicate in `_wait_for_results(previous_ids=…)` | The primary fix, robust to both orderings |
| B-2b | Non-terminal `new_on_page == 0` in `get_inteiro_links` | Conflates end-of-results with empty-window parse |
| B-2c | Separate `_wait_for_detail` in `_open_detail` | Same race, different post-click predicate |

Skip B-1 (the selector scoping) — the probe proved it's a no-op and its stated rationale was based on markup that doesn't exist. Note this in the report so a future pass doesn't re-attempt it.
Find in .dev/chilean-jurisprudence/05-chile_scraper-playbook.md the draft the Phase B diff against the current `chile_scraper.py` — three hunks, roughly 40 lines net — so you have a concrete target for the fix rather than a description.