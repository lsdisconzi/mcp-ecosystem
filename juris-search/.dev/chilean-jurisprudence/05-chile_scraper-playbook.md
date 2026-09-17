# Phase B — concrete diff

Three hunks against `chile_scraper.py` at blob `53a163d5…`. Line numbers are approximate and will shift — apply with context, not offsets. Total net change: **+62 / −13**.

> **⚠ APPLIED, WITH FOUR CORRECTIONS (2026-09-17, commit `2f4a2cd`).** Do not apply this diff again — the code already contains it. The applied version is described in `03-chile_scraper-playbook.md` §Phase B and `verification_report.md` §*Changes made*; what follows is kept as the record of what was drafted. Where the draft and the shipped code differ:
>
> 1. **Hunk C's rationale was wrong, though its shape was right.** The draft guessed that `#capa_contenedor_detalle_sentencia` was "a container dump guess… the probe confirmed the id exists but not that it becomes visible on click." The live detail probe showed the id **is** real and **does** become visible — at **t≈0.007 s**, while `#panel_contenedor_central_detalle_sentencia` still holds 94 chars and only later grows to ~78,900. So an `is_displayed()`-only predicate as drafted would have returned on an **empty panel**. The shipped `_wait_for_detail` gates on container-visible **and** panel text `>= 1000`.
> 2. **Hunk A's removed line was transcribed wrong.** The draft shows `self._assert_not_blocked("waiting for results")`; the real source passes it as a keyword, `self._assert_not_blocked(context="waiting for results")`. Applying the draft literally would break the call.
> 3. **New sub-hunk B-2b.** The draft kept `new_on_page == 0` terminal. It is, but a zero-yield page now **retries the click once when the preceding wait timed out**, and logs `readiness_reached=` / `ids_on_page=`. Unconditional terminality silently truncates the result set; unconditional retrying risks an infinite loop.
> 4. **`_open_detail` needed the same treatment in two places.** The draft scoped hunk C to the post-click wait only. The pre-click page-advance loop called `_wait_for_results()` with no baseline, so it inherited the identical race; it now snapshots `page_ids` and passes them. The bare `time.sleep(0.3)` went with it.
>
> **Also note:** the "Commit shape" section below went out as the body of commit `500ae05`, which **made none of these code changes** (`git show 500ae05 -- juris-search/chile_scraper.py` is empty). The real change is `2f4a2cd`, whose subject line is the one this document specified. Work-order **B-1 was deliberately not applied** (measured no-op: 70 nodes scoped vs 70 unscoped).

I'm assuming the file layout I saw earlier: `_wait_for_results` and `_click_next_page` around L389–425, `get_inteiro_links` around L296–350, `_open_detail` around L581. Verify before applying.

---

## Hunk A — new helper + rewrite `_wait_for_results`

**Why:** the current predicate is *existence*-based and fires immediately. Per the probe, after a click the rows clear within ~22 ms and stay empty ~2.0 s. An existence check either (a) fires in the pre-clear window on stale rows, or (b) fires in the post-clear window on `false`, then on the next poll (0.5 s) sees rows still empty and — because the predicate returns `False` — correctly keeps polling until repopulation. Both behaviors are wrong for the pagination case because we don't know which window we hit. A **change predicate that treats empty as never-ready** is correct for both.

```diff
@@
-    def _wait_for_results(self, timeout: Optional[int] = None):
-        """Poll until result rows appear, an explicit 'no results' state, or timeout."""
-        timeout = timeout or self.wait_time
-
-        def _ready(d):
-            # F5 rejection page — bail immediately.
-            src = d.page_source
-            if self._is_f5_block(src):
-                return True
-            # Results present?
-            if d.find_elements(By.CSS_SELECTOR, "[data-idsentencia]"):
-                return True
-            return False
-
-        try:
-            WebDriverWait(self.driver, timeout).until(_ready)
-        except Exception:
-            logger.warning("Chile: timed out waiting for results")
-
-        self._assert_not_blocked(context="waiting for results")
+    def _current_result_ids(self) -> frozenset:
+        """Visible [data-idsentencia] values currently in the DOM.
+
+        The portal replicates the attribute ~7x per result (card + 4 title
+        spans + button + form — see verification_report.md, patch 4a). We
+        dedupe via a set and filter by rendered-box presence (offsetParent),
+        which is the cheap equivalent of is_displayed() for in-flow rows.
+
+        Returns frozenset() when the results container is absent, empty, or
+        the driver call fails — never raises.
+        """
+        try:
+            raw = self.driver.execute_script(
+                "return Array.from(document.querySelectorAll('[data-idsentencia]'))"
+                ".filter(e => e.offsetParent !== null)"
+                ".map(e => e.getAttribute('data-idsentencia'))"
+                ".filter(Boolean);"
+            )
+        except Exception:
+            return frozenset()
+        return frozenset(raw or [])
+
+    def _wait_for_results(
+        self,
+        timeout: Optional[int] = None,
+        previous_ids: Optional[frozenset] = None,
+    ):
+        """Wait for the result set to become ready.
+
+        Two modes:
+          previous_ids is None
+            Legacy: wait for any non-empty result set.
+          previous_ids is a frozenset (possibly empty)
+            Change mode: wait until the visible id set is non-empty AND
+            differs from previous_ids. Required after any action that
+            mutates the result set (search submit, next-page click,
+            section navigation) — see verification_report.md, open issue 9.
+
+        Empty is NEVER considered ready: the portal clears rows for ~2.0 s
+        between pages, and WebDriverWait evaluates its predicate immediately,
+        so an empty-window poll must not short-circuit the wait.
+        """
+        timeout = timeout or self.wait_time
+
+        def _ready(d):
+            if self._is_f5_block(d.page_source):
+                return True
+            current = self._current_result_ids()
+            if not current:
+                return False
+            if previous_ids is None:
+                return True
+            return current != previous_ids
+
+        try:
+            WebDriverWait(self.driver, timeout).until(_ready)
+        except Exception:
+            logger.warning("Chile: timed out waiting for results")
+
+        self._assert_not_blocked(context="waiting for results")
+
+    def _wait_for_detail(self, timeout: Optional[int] = None):
+        """Wait for the detail panel to render after clicking 'Ver sentencia'.
+
+        Distinct from _wait_for_results: clicking the detail button replaces
+        the results list with a detail panel; the post-condition is panel
+        visibility, not a new id set. Container id verified live in the
+        Phase A probe (verification_report.md, Evidence).
+        """
+        timeout = timeout or self.wait_time
+
+        def _ready(d):
+            if self._is_f5_block(d.page_source):
+                return True
+            try:
+                panel = d.find_element(
+                    By.ID, "capa_contenedor_detalle_sentencia"
+                )
+                return panel.is_displayed()
+            except Exception:
+                return False
+
+        try:
+            WebDriverWait(self.driver, timeout).until(_ready)
+        except Exception:
+            logger.warning("Chile: timed out waiting for detail panel")
+
+        self._assert_not_blocked(context="waiting for detail panel")
```

---

## Hunk B — `get_inteiro_links` loop restructure

**Why three separate problems:**

1. The initial `_wait_for_results()` (existence mode) can pass on the landing page's *default listing* (855.792 results rendered ~1.1 s after load). Search results then replace it. Without a change-predicate, we can't tell the two apart — this is the D4b false-pass.
2. The trailing `time.sleep(0.5)` is now redundant (the predicate polls) and, more importantly, wrong — after 0.5 s the predicate may still see empty rows.
3. The `new_on_page == 0` break is terminal and conflates "empty-window parse" with "pager exhausted". With the change-predicate in place, `new_on_page == 0` genuinely means "the clicked page returned nothing new" — but we must still capture the ids *before* the click so the predicate has something to compare against.

```diff
@@
         # ── Page 1: run the search via UI ────────────────────────────────
-        self._run_search_ui(query)
-        self._wait_for_results()
+        pre_search_ids = self._current_result_ids()
+        self._run_search_ui(query)
+        self._wait_for_results(previous_ids=pre_search_ids)
 
         while len(entries) < max_results and page <= max_pages:
             page_entries = self._parse_search_results(query, id_buscador, cat_info)
+
+            # Snapshot ids BEFORE we advance, so the next wait has a
+            # comparison basis.
+            current_ids = frozenset(
+                r.get("id_sentencia") for r in page_entries
+                if r.get("id_sentencia")
+            )
 
             new_on_page = 0
             for r in page_entries:
                 key = r.get("id_sentencia") or r.get("rol")
                 if not key or key in seen_ids:
                     continue
                 seen_ids.add(key)
                 r["page"] = page
                 r["categoria"] = categoria
                 r["id_buscador"] = id_buscador
                 r["tribunal_pais"] = "CHILE"
                 entries.append(r)
                 new_on_page += 1
                 if len(entries) >= max_results:
                     break
 
             logger.info(
                 f"Chile: page {page} — {new_on_page} new "
                 f"({len(entries)}/{max_results} total)"
             )
 
             if len(entries) >= max_results:
                 break
             if new_on_page == 0:
-                # Either the pager is done or F5 ate the page.
                 self._assert_not_blocked(context=f"page {page} parse")
                 logger.info("Chile: no new results — stopping.")
                 break
 
             if not self._click_next_page():
                 logger.info("Chile: no next-page control — stopping.")
                 break
 
             page += 1
-            self._wait_for_results()
-            time.sleep(0.5)  # small human-like gap
+            self._wait_for_results(previous_ids=current_ids)
 
         logger.info(f"Chile: total results: {len(entries)}")
         return entries
```

Note the removal of the `time.sleep(0.5)`. The change-predicate wait is what paces the loop now.

---

## Hunk C — `_open_detail` waits

**Why:** `_open_detail` has the same race in two places:
- After re-running the search, before clicking `Ver sentencia` — same false-pass risk as `get_inteiro_links` page 1.
- After clicking the detail button, waiting on the *results* predicate is wrong; the post-condition is a detail panel, not a new result set.

```diff
@@
         if not (categoria and id_sentencia):
             return False
 
         self._navigate_to_category(categoria)
+        pre_search_ids = self._current_result_ids()
         self._run_search_ui(result.get("search_terms") or "")
-        self._wait_for_results()
+        self._wait_for_results(previous_ids=pre_search_ids)
 
         # Advance to the page where this result was found.
         for _ in range(target_page - 1):
+            pre_page_ids = self._current_result_ids()
             if not self._click_next_page():
                 break
-            self._wait_for_results()
-            time.sleep(0.3)
+            self._wait_for_results(previous_ids=pre_page_ids)
 
         # Find the row and click the detail button.
         try:
             rows = self.driver.find_elements(By.CSS_SELECTOR, "[data-idsentencia]")
             for row in rows:
                 if row.get_attribute("data-idsentencia") != str(id_sentencia):
                     continue
                 # Try the labelled button first, then any button in the row.
                 btns = row.find_elements(
                     By.XPATH, ".//button[contains(., 'Ver sentencia')]"
                 )
                 if not btns:
                     btns = row.find_elements(By.XPATH, ".//button")
                 for btn in btns:
                     if btn.is_displayed():
                         self.driver.execute_script("arguments[0].click();", btn)
-                        self._wait_for_results(timeout=self.wait_time)
+                        self._wait_for_detail(timeout=self.wait_time)
                         return True
         except Exception as e:
             logger.error(f"Chile: detail click failed: {e}")
 
         return False
```

---

## Application notes

1. **Do not scope the selector.** The Phase A probe showed `#capa_resultados_busqueda_sentencias [data-idsentencia]` returns the same **70** nodes as the unscoped selector. All 70 are visible. Scoping is a measured no-op, and the work order's stated rationale ("excludes hidden stubs") was based on markup that doesn't exist in the live DOM. Do **not** apply B-1.

2. **Do not add an explicit sleep.** The change-predicate is the pacing mechanism. If the first application produces pagination that's too fast or too slow, adjust `wait_time` or `WebDriverWait`'s poll interval, not the loop.

3. **`_current_result_ids` uses `offsetParent !== null`**, not Selenium's `is_displayed()`. This is deliberate: 70 elements × `is_displayed()` is 70 WebDriver round-trips per poll, and `WebDriverWait` polls every 0.5 s by default. The JS form is one round-trip. Caveat: `offsetParent` is `null` for `position: fixed` elements; the portal's result rows are in normal flow, so this is fine, but if a future revision changes the layout the predicate will silently start returning empty. Add a comment in the source noting this dependency.

4. **`_wait_for_detail`'s container id is a guess from the probe's container dump** (`capa_contenedor_detalle_sentencia`). If Phase C shows step 7 timing out on the detail wait, dump the visible container ids immediately after a manual `Ver sentencia` click and update the constant. The probe confirmed the id exists on the page but not that it becomes visible on click.

5. **The `new_on_page == 0` break is still terminal**, but now for the right reason: after the change-predicate fires, rows are non-empty and differ from `previous_ids`; a subsequent parse yielding zero new means the pager landed on the same result set (last page reached, or a no-op next). If Phase C shows legitimate multi-page results but this break fires on page 2 or 3, that means the id set on the new page *is* a subset of a prior page — which would be a portal behavior we haven't seen. Capture and stop.

6. **`_wait_for_results` now has a required `previous_ids` parameter in practice.** Existing callers that pass only `timeout` still work (legacy mode), but every call site in `get_inteiro_links` and `_open_detail` must be updated per hunks B and C. Grep for `_wait_for_results(` after applying to confirm no stale calls remain.

---

## Verification the agent should run after applying

**Offline (no network):**

```python
# _current_result_ids tolerates a driver that raises
class BadDriver:
    def execute_script(self, *a, **k): raise RuntimeError("boom")
s = object.__new__(ChileJurisprudenciaScraper)
s.driver = BadDriver()
assert s._current_result_ids() == frozenset()

# _wait_for_results accepts previous_ids=None and previous_ids=frozenset()
# (both must not raise; use a stub driver returning an F5 body so _ready
#  short-circuits to True)
```

**Phase C (Session 1, fresh profile):**

```python
with ChileJurisprudenciaScraper(headless=False) as s:
    results = s.get_inteiro_links(
        "daño moral", max_results=40,
        filters={"categoria": "civiles", "resultados_por_pagina": 10},
    )
    pages = sorted({r["page"] for r in results})
    print("pages:", pages, "total:", len(results),
          "unique:", len({r["id_sentencia"] for r in results}))
```

Pass criteria are the same as the work order's Phase C. If `pages == [1]` again, the probe was wrong about the mechanism and we need to re-diagnose before touching anything else — but two independent probe runs say it isn't.

**If Phase C passes**, Phase D follows per the work order. **If Phase C fails with a different symptom** (e.g. pagination advances but step 7 times out on the detail wait), capture that as a distinct failure and do not roll back the pagination fix — the two are independent.

---

## What NOT to touch in this pass

- `_parse_chile_text_result`, `_parse_search_results`, `_navigate_to_category`, `_click_next_page` — unchanged.
- `_is_f5_block`, `_extract_support_id`, `_F5_BODY_MARKERS` — unchanged. Case A3 (XHR-body F5) is a separate open issue; fixing it needs response interception, not a detector tweak.
- `download_inteiro_teor_url` — unchanged. It calls `_open_detail`, which is what Hunk C fixes.
- `docs/pjud-source.md` — unchanged. The container id and the 7-nodes-per-result anatomy belong in §7.1 but that's a separate editorial pass.

---

## Commit shape

One commit, `chile: gate result readiness on row-set change; separate detail wait`:

```
- add _current_result_ids, _wait_for_detail
- _wait_for_results: previous_ids param; empty is never ready
- get_inteiro_links: snapshot ids before search and before each click
- _open_detail: same snapshot discipline; use _wait_for_detail post-click
- drop the trailing time.sleep(0.5) — the predicate paces the loop

Refs: verification_report.md open issue 9 (mechanism B-2, sub-25ms race);
      patch 4a (scoping is a measured no-op — B-1 not applied).
```

After the commit, re-pin: update `chile_scraper.py @ sha1:…` in the playbook header to the new working-tree blob (`git hash-object`), recompute the playbook hash, and update the same value in the report. Both must round-trip from `HEAD`.