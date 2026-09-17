# Verification Playbook — `chile_scraper.py`

<!-- pinned: chile_scraper.py @ sha1:d46f896dadaacb2b5479420229f547938d688640 -->
<!-- playbook-hash: sha256:3853b92223bc690fe5a472fdd71ed7025cc2f129f9ae28767a9baa085a984d6e (of this file with this line removed) -->

Give this to the agent verbatim. It's ordered so each step either confirms a prior fix or fails loudly before the next step can mask it. The agent should **stop at the first failure** and report, rather than pressing on with downstream steps.

> **Provenance.** The `pinned:` line above is the git blob of `chile_scraper.py` the playbook was written against. Verify with
> `git rev-parse HEAD:juris-search/chile_scraper.py`. The `playbook-hash` line covers the playbook itself *excluding that line*; recompute with
> `grep -v '^<!-- playbook-hash:' <this file> | shasum -a 256`. If a later step deliberately re-pins the scraper, update the `pinned:` line and recompute the playbook hash.

---

## 0. Preconditions & environment

Before touching the scraper:

1. **Confirm the file on disk is the updated one.** Each sentinel grep must produce **at least one** match; multi-hit is expected (definition + call sites). If any fails, the agent is editing an old copy and must stop.
   ```bash
   # Each line must produce >=1 match. Multi-hit is expected (definition + call sites).
   grep -q "id_buscador.*328" chile_scraper.py       || { echo "STOP: map not updated"; exit 1; }
   grep -q "def _is_f5_block" chile_scraper.py       || { echo "STOP: F5 detector missing"; exit 1; }
   grep -q "def _click_next_page" chile_scraper.py   || { echo "STOP: pager missing"; exit 1; }
   echo "freshness OK"
   ```
   Also confirm the blob matches the `pinned:` line in this file's header:
   ```bash
   git rev-parse HEAD:juris-search/chile_scraper.py
   ```
   A mismatch is **not** automatically a STOP — the scraper may have been legitimately re-pinned. Record the observed hash and proceed; report it.

2. **Confirm `_shared/chrome_driver.py` exposes** `create_chrome_driver(headless=...)` and `write_sidecar_metadata(path, dict)`. If either is missing or renamed, all later steps will fail for the wrong reason.

3. **Chrome available** and able to launch headful. Most of the F5-sensitive steps need a real browser with a persistent profile (§11 item 4 of the source notes). Confirm the driver can launch `https://example.com` before proceeding.

4. **Read `docs/pjud-source.md` once.** The agent needs to know what an F5 rejection page looks like and what the section map says.

5. **Create a clean workspace:** run `mkdir -p workspace/CL_jurisprudencia` (the directory does not exist at repo root). Record what is already there before starting, so new artefacts can be attributed to this run.

---

## 1. Static checks (no network, ~2 min)

Run these imports and assertions. Any failure is a code defect, not a runtime one — fix before proceeding.

```python
from chile_scraper import (
    CHILE_CATEGORIES, ChileJurisprudenciaScraper,
    SearchCriteria, _F5_BODY_MARKERS,
)

# 1a. Every category has an id_buscador key (may be None for compendio_extranjeria)
for k, v in CHILE_CATEGORIES.items():
    assert "id_buscador" in v, f"{k} missing id_buscador"
    assert "tipo_instancia_principal" in v, f"{k} missing tipo_instancia"
    assert "es_lj" in v, f"{k} missing es_lj"

# 1b. Verified ids match docs/pjud-source.md §4
expected = {
    "corte_suprema": 528, "corte_apelaciones": 168, "civiles": 328,
    "penales": 268, "laborales": 271, "familia": 270, "cobranza": 269,
    "salud_cs": 127, "lineas_jurisprudenciales": 628,
}
for k, want in expected.items():
    got = CHILE_CATEGORIES[k]["id_buscador"]
    assert got == want, f"{k}: {got} != {want}"

# 1c. compendio_extranjeria is explicitly None, not a guessed number
assert CHILE_CATEGORIES["compendio_extranjeria"]["id_buscador"] is None

# 1d. Lineas Jurisprudenciales is flagged special
assert CHILE_CATEGORIES["lineas_jurisprudenciales"]["es_lj"] is True

# 1e. F5 markers cover the known body strings
for marker in ("rechazada", "Su numero de soporte", "human visitor"):
    assert any(marker.lower() in m.lower() for m in _F5_BODY_MARKERS), \
        f"missing F5 marker: {marker}"
```

**If any assert fails:** edit the map in `CHILE_CATEGORIES` to match §4 of the source notes. Do **not** invent a value for `compendio_extranjeria`.

---

## 2. F5 detector unit test (no browser, ~30 s)

The detector is the single most important new piece of logic. Test it directly against canned HTML before trusting it live.

```python
from chile_scraper import ChileJurisprudenciaScraper as S

# 2a. Real F5 rejection body (subset)
blocked = """
<html><head><title>La URL solicitada ha sido rechazada</title></head>
<body>Su numero de soporte es : 1234567890</body></html>
"""
assert S._is_f5_block(blocked) is True

# 2b. A normal results page must NOT trip the detector
normal = "<html><body><div data-idsentencia='abc'>ROL: C-1-2025</div></body></html>"
assert S._is_f5_block(normal) is False

# 2c. Support-id extractor
assert S._extract_support_id(blocked) == "1234567890"
assert S._extract_support_id(normal) is None

# 2d. Empty input doesn't raise
assert S._is_f5_block("") is False

# 2e. TSPD image challenge — support ID is English-texted, extractor must return None.
# This documents a known limitation, not a defect: _extract_support_id is Spanish-only.
tspd_image = ('<html><head><title>...</title></head>'
              '<body>What code is in the image? Your support ID is: 1234567890</body></html>')
assert S._is_f5_block(tspd_image) is True
assert S._extract_support_id(tspd_image) is None   # EN text not parsed; known gap

# 2f. Body-less F5 (x-security-action header only) — _is_f5_block cannot see it.
# Assert the current behaviour so the gap is regression-locked, not silently exploited.
bodyless = '<html><body><h1>Buscador Unificado de Fallos</h1></body></html>'
assert S._is_f5_block(bodyless) is False   # documented limitation, see open issues
```

**If 2b fails:** the marker list has drifted from §1 of the source notes; re-read §1 verbatim and restore the full phrases — do **not** loosen the list.

**If 2c fails:** the regex `soporte es\s*:?\s*(\d+)` no longer matches production HTML. Capture a fresh blocked page (see step 3) and update the regex.

**2e / 2f are expected to pass as written.** They lock in two *known* gaps (Spanish-only support-ID parsing; body-only detection). If 2e or 2f fails, the detector's behaviour has changed in a way the playbook does not yet describe — stop and report rather than "fixing" the test.

---

## 3. Live: F5 detection against production

This step is **read-only** and does not require solving anything, because F5 will serve the challenge on the very first hit if you have a fresh profile.

```python
with ChileJurisprudenciaScraper(headless=False) as s:
    s.driver.get("https://juris.pjud.cl/busqueda?Civiles")
    import time; time.sleep(6)
    src = s.driver.page_source
    print("F5 blocked?" , s._is_f5_block(src))
    print("support_id:", s._extract_support_id(src))
    print("Title:", s.driver.title[:120])
```

**Expected outcomes — all are acceptable, but you must record which one you hit:**

- **Case A1 — TSPD image challenge** (body contains `What code is in the image?`): `_is_f5_block` returns `True`; `_extract_support_id` returns **`None`, and that is correct** — the image challenge is English-texted (`Your support ID is: <n>`) while the extractor is Spanish-only (covered by test 2e). Do **not** treat `None` as a detector failure and do **not** "fix" the regex in this pass.
- **Case A2 — "rechazada" body**: `_is_f5_block` returns `True`; `_extract_support_id` returns the Spanish support number. This is the blocking-POST signature (`x-security-action: 0800000200`). Do **not** attempt an automated recovery.
- **Case B — through**: `_is_f5_block` returns `False` and the title contains *"Buscador Unificado de Fallos"*. Note this in the log; you have a usable session window (~6 navigations, §1). **This is the normal, healthy outcome — it does not mean the search works.** The landing GET is a different route from the search POST; see Case A3.

**If none of the three:** the detector is mis-classifying. Paste both `src[:500]` and the detected boolean into the report — this is a real defect.

**If Case A1 or A2:** solve the CAPTCHA manually in the visible browser, wait for the shell to load, then re-run the same snippet. It should now print `False`.

### Case A3 — F5 on the AJAX route only (invisible to `_is_f5_block`)

Navigation-level detection is **not** sufficient. `docs/pjud-source.md` §5.3 records that the **POST** path is the most aggressively filtered route on the host. When F5 filters the search `POST`, the rejection arrives as an **HTTP 200 XHR body** — it never touches `driver.page_source`, so:

- `_is_f5_block(page_source)` returns **`False`**,
- `_assert_not_blocked` raises **nothing**,
- the previously-rendered rows stay in the DOM, and
- the scraper silently reports **stale, unfiltered landing-page data** as search results.

Observed live 2026-09-17 (Case B navigation, then a search):

```
POST /busqueda/busqueda_por_texto_autocompletable  -> 200
  body: <title>La URL solicitada ha sido rechazada</title> … Su numero de soporte es : <12975407294819665921>
POST /busqueda/buscar_sentencias                   -> 200
  body: <title>La URL solicitada ha sido rechazada</title> … Su numero de soporte es : <12975407294819666965>
```

To confirm it on your run, wrap `XMLHttpRequest.send` before the search and read the bodies back:

```python
REC = """
if (!window.__rec) {
  window.__rec = [];
  const oOpen = XMLHttpRequest.prototype.open, oSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(m,u){ this.__m=m; this.__u=u; return oOpen.apply(this,arguments); };
  XMLHttpRequest.prototype.send = function(body) {
    const self = this;
    const rec = {m:self.__m, u:self.__u, status:null, resp:null};
    window.__rec.push(rec);
    self.addEventListener('loadend', function(){
      rec.status = self.status;
      try { rec.resp = String(self.responseText).slice(0,300); } catch(e){ rec.resp='ERR'; }
    });
    return oSend.apply(this, arguments);
  };
}
return 'installed';
"""
# install AFTER navigating, BEFORE calling get_inteiro_links:
s.driver.execute_script(REC)
s.get_inteiro_links("daño moral", max_results=10, filters={"categoria": "civiles"})
for r in s.driver.execute_script("return window.__rec;"):
    if "buscar" in (r["u"] or ""):
        print(r["status"], r["u"], "|", (r["resp"] or "")[:120])
```

A `200` whose body contains `La URL solicitada ha sido rechazada` is **Case A3**: the query never reached the server. Record it as a **blocker** with the support ID — it invalidates steps 5–8 for that session. Do **not** work around it by retrying in a loop, and do **not** add an XHR interceptor to production code in this pass: that is a design change, not a bug fix.

> **Known limitation (do not fix in this pass):** the detector is **body-only**. A response carrying `x-security-action: 0800000200` with no body marker passes `_is_f5_block`; so does an F5 rejection delivered *inside an XHR body* (Case A3). Also note that the **first** hit on a fresh profile is normally the TSPD image page — so `support_id is None` on a first hit is expected behaviour, not a bug. Record any header-only or XHR-only observation and stop.

---

## 4. Live: section config resolution (`_navigate_to_category`)

With a cleared session from step 3, verify `window.id_buscador_activo` matches the expected id for **three** sections. Do this **with delays** — rapid section hopping re-triggers F5 (§1 escalation pattern, ~6 navigations).

```python
import time
with ChileJurisprudenciaScraper(headless=False) as s:
    for cat in ("civiles", "penales", "corte_suprema"):
        expected = CHILE_CATEGORIES[cat]["id_buscador"]
        try:
            got = s._navigate_to_category(cat)
            live = s.driver.execute_script("return window.id_buscador_activo;")
            print(f"{cat}: map={got} live={live} expected={expected}")
            assert live is not None and str(live) == str(expected), \
                f"{cat}: live={live} expected={expected}"
        except (RuntimeError, AssertionError) as e:
            print(f"{cat}: FAILED -> {e}")
            break
        time.sleep(8)   # deliberate spacing
```

**Pass criteria:**
- For each of the three sections, `live == expected` (enforced by the assertion).
- No `RuntimeError` unless F5 genuinely re-challenged (support ID present in the message).

**Failure modes and fixes:**

| Symptom | Likely cause | Fix |
|---|---|---|
| `live is None` | Wait predicate resolved too early — inline `id_buscador_activo` not yet parsed | Increase `wait_time` in the constructor or tighten the `WebDriverWait` predicate to also require `document.readyState === 'complete'` |
| `live != expected` on `Salud_CS` / `Lineas_Jurisprudenciales` | These sections are URL-only; `id_buscador_activo` is set inline but may not be present on first paint | Increase the `WebDriverWait` before reading; do **not** change the map |
| `live != expected` after an F5 solve | Stale session — the config still belongs to the previous section | Force `_navigate_to_category(cat, force=True)` |
| `live != expected` on a normal section | Map value disagrees with §4 of the source notes | Correct the map only if §4 disagrees; otherwise re-read the page |
| `RuntimeError` on second iteration | Rapid hopping triggered F5 — **working as designed** | Increase the inter-section sleep to 10–15 s and re-test |
| `ValueError: no verified id_buscador` on `compendio_extranjeria` | Correct | Not tested here |

> **URL-encoding note.** `quote(slug, safe="")` is **correct** and is not a diagnosis for any of the above: Python's `quote` never escapes `_`, `.`, `-`, or `~`, and `safe=""` is *required* for the accented slugs (`Compendio_Extranjería` → `Compendio_Extranjer%C3%ADa`). Do not "fix" it.

**If all three pass:** record the result and move on. If any *non-F5* failure occurs, fix `_navigate_to_category` before proceeding — steps 5–8 depend on it.

---

## 5. Live: search + DOM parsing (`_run_search_ui`, `_parse_search_results`)

Run a **single-page** search in a fresh session.

> **Page-size reality (D3).** The scraper never transmits `numero_filas_paginacion`. `resultados_por_pagina` is consumed **only as arithmetic** inside `get_inteiro_links` (it feeds `per_page` → `max_pages`); `_run_search_ui` fills `#tb_input_omnibox` and clicks *Buscar*, nothing else. The portal therefore applies its own default of **10** rows/page (`docs/pjud-source.md` §5.1; `10-20-50` per §6). All criteria below are calibrated to **10 rows/page**, not 20.

> **Provenance trap (D4 — added after the first re-run).** `_navigate_to_category` lands on a page that **already contains a default listing** — `[data-idsentencia]` rows are present *before* any query is submitted, and `#span_cantidad_resultados` shows the *whole-section* total (observed: `Se ha(n) encontrado 855.792 resultados.` on `Civiles`). Consequences:
>
> 1. `_wait_for_results` is satisfied immediately by the landing rows, so it never actually waits for the search.
> 2. A "10 rows, all criteria green" result can be **entirely landing-page data** — a false pass.
> 3. F5 can reject the search `POST` while the DOM still shows the old listing, so nothing looks wrong.
>
> The script below therefore snapshots the landing state and **fails** if the row set did not change. Without this check the rest of step 5 is vacuous.

```python
import time
from chile_scraper import ChileJurisprudenciaScraper

JS_BASE = """
const rows = document.querySelectorAll('[data-idsentencia]');
const cant = document.getElementById('span_cantidad_resultados');
return {
  n: rows.length,
  cantidad: cant ? cant.innerText.trim() : 'MISSING',
  first: rows.length ? rows[0].getAttribute('data-idsentencia') : null,
};
"""

with ChileJurisprudenciaScraper(headless=False) as s:
    s._navigate_to_category("civiles")
    time.sleep(15)                      # let the default listing settle
    landing = s.driver.execute_script(JS_BASE)
    print("LANDING:", landing)

    results = s.get_inteiro_links("daño moral", max_results=10,
                                  filters={"categoria": "civiles",
                                           "resultados_por_pagina": 10})
    print(f"n={len(results)}")

    after = s.driver.execute_script(JS_BASE)
    print("AFTER  :", after)
    print("row set changed:", after["first"] != landing["first"])

    for r in results[:3]:
        print({k: r[k] for k in
               ("rol", "id_sentencia", "id_buscador", "instancia",
                "fecha", "categoria", "page")})
```

**Provenance criteria (D4 — check these first; if they fail, stop):**

- **P1 — row set changed.** `after["first"] != landing["first"]`, **or** `landing["n"] == 0`. If the first row is identical before and after, the search never took effect and **every other criterion below is meaningless**. Stop, and go to step 5.5's DevTools check to see whether the search `POST` was rejected.
- **P2 — `after["n"] > 0`.** A zero-row DOM after a search means the response did not render.

**Pass criteria for each result (only meaningful once P1/P2 hold):**

1. `id_sentencia` non-empty — this is the primary key.
2. `id_buscador == 328`.
3. `instancia == "civil"`.
4. `categoria == "civiles"`.
5. `page == 1` for all results.
6. `len(results) <= 10` — a *partial* page is not a pagination failure. Criteria 5 and 6 are deliberately separate so a short page does not read as a pager bug.
7. At least **one** of `caratulado`/`tribunal`/`materia` is non-empty — if all three are empty for every result, the regex parsing is off.
8. Record `len(results)`. If it is not 10, and no F5 block occurred, flag as an **open issue** — do not treat as failure without checking the corpus.

**ROL format check — derived from the parser, not hand-written (D3/minor).** Anchor the expectation to what `_parse_chile_text_result` actually does, so the test cannot drift into an aspirational contract:

```python
import re
from chile_scraper import ChileJurisprudenciaScraper as S
# No browser: the parser is pure, so build the instance without launching Chrome.
probe_s = object.__new__(S)

probe = probe_s._parse_chile_text_result(
    "ROL: C-1944-2025 Caratulado: x Fecha: 15-05-2026", "id", "q")
assert probe["rol"] == "C-1944-2025"

# The parser's own regex is loose and may accept a bare number. Record what it
# does rather than asserting a contract it was never written to satisfy.
probe_neg = probe_s._parse_chile_text_result(
    "ROL: 123 Caratulado: x Fecha: 15-05-2026", "id", "q")
assert probe_neg["rol"] != ""   # loose parser: recorded as an open issue, not a bug to fix here
```

If the loose-parse result looks wrong to you, add an **open issue** in the report — do **not** tighten `_parse_chile_text_result` in this pass.

---

## 5.5 Advanced-search surface reachability (NEW)

A green run does not prove the filter surface works: a fully passing step 5 still ships an inert advanced-search form, because `_run_search_ui` never populates any filter control (§12 of the source notes, gap analysis). Verify the gap explicitly so it is recorded rather than assumed.

With a cleared session:

```python
with ChileJurisprudenciaScraper(headless=False) as s:
    results = s.get_inteiro_links("daño moral", max_results=5,
                                  filters={"tribunal": "Corte Suprema"})
    print("n=", len(results))
```

Open DevTools → Network on the visible browser and inspect the `POST /busqueda/buscar_sentencias` **request form data *and* its response body**.

**Expected current behaviour: no tribunal filter is sent** — `_run_search_ui` only fills the omnibox. Record this as an **open issue**. Do **not** attempt to wire the filter in this pass.

**Also record the response.** Three things must be captured for this step to be useful:

1. The **form-data keys** actually sent (expected: the free-text term + section id; **no** `tribunal`).
2. The **status** (note that HTTP `200` does *not* mean success here).
3. The **response body** — if it contains `La URL solicitada ha sido rechazada`, the request was F5-filtered (Case A3 in step 3) and **every search-dependent step in this run is invalid**. This is the fastest way to diagnose a failed step 5 P1.

**Pass criterion:** the observation is recorded (either "no filter sent", or the exact form-data key if one *is* sent), **plus** the response verdict (`through` or `F5-filtered`). There is no expected-value assertion here — this step exists to make the gap visible and to classify the search route.

**Failure modes and fixes:**

| Symptom | Cause | Fix |
|---|---|---|
| **P1 fails: `after["first"] == landing["first"]`** | The search `POST` never took effect. This is *usually* F5 rejecting the XHR while the old listing stays on the page — `docs/pjud-source.md` §5.3 documents that the POST path is the most aggressively filtered route. `page_source` contains **no** rejection text, so `_assert_not_blocked` sees nothing. | **Environmental — stop and report.** Do not "fix" this by retrying in a loop. Confirm via step 5.5 (DevTools → Network: is `POST /busqueda/buscar_sentencias` returning a body containing `La URL solicitada ha sido rechazada`?). Record as a blocker with the observed `n` and `landing["first"]` |
| `after["n"] == 0` right after a search | Response rendered nothing | Check the XHR (step 5.5). If the XHR body is an F5 rejection, that is the same blocker as P1 |
| `n == 0` and an F5 block raised in the log | F5 rejected a **navigation** (GET), which `_is_f5_block` *can* see | Wait 30 s, re-solve CAPTCHA, retry |
| `n == 0`, no F5 in the log | `_wait_for_results` timed out, or the results container selector is wrong | Open the page manually, right-click a result, inspect — confirm it carries `data-idsentencia`. If the attribute has a different name (e.g. `data-id`), update `_parse_search_results` **and** `_wait_for_results` |
| `rol` empty for all rows | `elem.text` on the Selenium element returns a collapsed string missing the label | Replace `elem.text` with `elem.get_attribute("innerText")` — Selenium's `.text` can drop hidden lines |
| `instancia` is `None` | `cat_info` not threaded through | Check `_parse_search_results` passes `tipo_instancia` from `cat_info` into `_parse_chile_text_result` |
| `id_buscador` is `None` | Same as above | Same fix |
| Only 1–2 results, expected 10 | Selector matches a wrapper div, not each row | Inspect the DOM; the `[data-idsentencia]` must be on the **row**, not a parent. If it's on a parent wrapping several rows, that's a bug in the source notes — capture the real DOM and update §7.1 |

**Do not proceed to step 6** until a clean single-page search returns: **P1 and P2 satisfied**, a full page (10 rows), and `id_sentencia` + `id_buscador` populated. A green count with a failed P1 is a **false pass**, not a pass.

---

## 6. Live: pagination (`_click_next_page`)

The pager selector is the most likely thing to be wrong out of the box.

```python
with ChileJurisprudenciaScraper(headless=False) as s:
    results = s.get_inteiro_links("daño moral", max_results=30,
                                  filters={"categoria": "civiles",
                                           "resultados_por_pagina": 10})
    pages = sorted({r["page"] for r in results})
    ids = [r["id_sentencia"] for r in results]
    print("pages seen:", pages, "total:", len(results))
    print("duplicate ids:", len(ids) != len(set(ids)))
```

**Pass criteria:**
- `pages == [1, 2, 3]` **and** `20 <= len(results) <= 30`.
  With `max_results=30` and `resultados_por_pagina=10`, `max_pages = 30 // 10 + 2 = 5`, so up to 5 pages is *possible* — but 3 pages should suffice. If `pages == [1, 2]` (≈20 rows), that is a partial pass: note it and check whether the corpus is short before calling it a pager bug.
- No duplicate `id_sentencia` across pages.

**Sub-step 6a — the pager markup (observed live 2026-09-17).** The portal does **not** use DataTables. `#paginador_top` contains Bootstrap 4 markup with stable ids:

```html
<div id="paginador_top" class="col-md-6" align="right">
  <nav aria-label="Paginador"><ul class="pagination justify-content-end">
    <li class="page-item"><a class="page-link" href="#" id="btnPaginador_inicio">…</a></li>
    <li class="page-item"><a class="page-link" href="#" id="btnPaginador_pagina_atras">◀</a></li>
    <span id="capa_botones_paginas" class="page-item">
      <li class="page-item active"><a class="page-link"
        onclick="…pagina_resultados_busqueda_sentencias=0;cargar_datos_…();">1</a></li>
      <li class="page-item"><a class="page-link"
        onclick="…pagina_resultados_busqueda_sentencias=1;cargar_datos_…();">2</a></li>
    </span>
    <li class="page-item"><a class="page-link" href="#" id="btnPaginador_pagina_adelante">▶</a></li>
    <li class="page-item"><a class="page-link" href="#" id="btnPaginador_fin">▶▶</a></li>
  </ul></nav>
</div>
```

Key facts (all verified by clicking in the live page):

- **Forward control:** `#btnPaginador_pagina_adelante`. Clicking it moved `pagina_resultados_busqueda_sentencias` **0 → 1**.
- **Page cursor:** the JS global `pagina_resultados_busqueda_sentencias` (zero-based). Numeral links set it directly and call `cargar_datos_resultados_busqueda_sentencias()`.
- **Active page:** `#capa_botones_paginas li.page-item.active a`.
- No `.disabled` class is applied at the end of the range, so `is_enabled()` is always `True`; termination relies on the `new_on_page == 0` guard.

Confirm the selector still matches before blaming anything else:

```python
els = s.driver.find_elements("css selector", "#btnPaginador_pagina_adelante")
print(len(els), [e.is_displayed() for e in els])
```

**Sub-step 6b — document the page-size gap (do not fix).** Confirm by inspection that `resultados_por_pagina` is **not** sent to the portal:

```bash
grep -n "resultados_por_pagina\|per_page\|numero_filas_paginacion" chile_scraper.py
```

Expected: the value appears only in `get_inteiro_links` arithmetic (`per_page`, `max_pages`) — never in a request payload; `numero_filas_paginacion` appears nowhere. **This is expected current behaviour. Record as an open issue; do not fix in this pass.**

**Failure modes and fixes:**

| Symptom | Cause | Fix |
|---|---|---|
| **`pages == [1]`, `len(results) == 10`, and step 5's P1 also failed** | The search `POST` was F5-rejected, so page 1 is landing-page data and the pager advances a listing that was never queried | **Environmental — stop and report.** Do not diagnose the pager at all until step 5's P1 passes; a pager bug and a blocked search are indistinguishable from here |
| `pages == [1]`, `len(results) == 10`, P1 passed | `_click_next_page` returned `False` — no selector matched | Check `#btnPaginador_pagina_adelante` (sub-step 6a) is present and displayed; it is already first in the selector list. If it is *missing*, the pager was not rendered — check `span_cantidad_resultados` > 10 |
| `pages == [1]`, `len(results) == 10`, P1 passed, and `_click_next_page` returned `True` | The click fired but the result rows had not been replaced before `_parse_search_results` read the DOM — `_wait_for_results` returns immediately because stale rows still match `[data-idsentencia]`. Every page-2 row dedupes as a duplicate, `new_on_page == 0`, loop breaks | **Known gap.** Record as an open issue: the loop needs a wait for the row set to *change*, not merely exist. Same root cause as step 5's P1 (existence is used as a proxy for freshness) |
| `pages == [1]`, `len(results) < 10` | Pager never appeared because the query yielded fewer rows | Not a bug — pick a broader query (`""`) and retry |
| F5 block on page 2 | Rapid clicks tripped F5 | Increase `time.sleep(0.5)` to 2–3 s after `_click_next_page` |
| `RuntimeError: F5 block ... during page 2 parse` | F5 in the middle of pagination | Correct behaviour — verify the support ID in the message and log it |

If `_click_next_page` needs a selector change, **update the docstring** in the function to record the observed selector and the date, so the next agent doesn't re-guess.

---

## 7. Live: detail open + download (`_open_detail`, `download_inteiro_teor_url`)

> **Precondition: step 5's P1 must pass and step 6 must reach `page >= 2`.** `download_inteiro_teor_url` *re-runs the search* to repopulate the list (`docs/pjud-source.md` §7.2, step 2 of 6) — so it re-fires the very `POST` that Case A3 rejects. Under Case A3 this step cannot pass, and its `path is None` outcome is **not** evidence about `_open_detail`. Record it as *blocked*, not as *failed*.

Pick one result from the middle of a multi-page search (so `page >= 2`) — this tests the page-targeting fix.

```python
import os, time
with ChileJurisprudenciaScraper(headless=False) as s:
    results = s.get_inteiro_links("daño moral", max_results=30,
                                  filters={"categoria": "civiles",
                                           "resultados_por_pagina": 10})
    target = next((r for r in results if r["page"] >= 2), results[-1])
    print("target:", target["rol"], "page", target["page"],
          "id", target["id_sentencia"])

    save_dir = "/tmp/cl_test"
    os.makedirs(save_dir, exist_ok=True)
    before = set(os.listdir(save_dir))
    started = time.time()

    path = s.download_inteiro_teor_url(
        url=target.get("url_detalle") or "",
        metadata={
            "rol": target["rol"], "caratulado": target["caratulado"],
            "tribunal": target["tribunal"], "id_sentencia": target["id_sentencia"],
            "id_buscador": target["id_buscador"], "instancia": target["instancia"],
            "categoria": target["categoria"], "search_terms": target["search_terms"],
            "page": target["page"],
        },
        _skip_org=True,
        save_dir=save_dir,
    )
    print("saved:", path)

    if path is None:
        # An F5 body cannot reach disk: _assert_not_blocked raises *before*
        # page_source.encode(), and that RuntimeError is caught by the outer
        # handler -> return None. So on None, assert nothing was written.
        newcomers = [
            f for f in set(os.listdir(save_dir)) - before
            if f.startswith("sentencia_") and f.endswith(".html")
            and os.path.getmtime(os.path.join(save_dir, f)) >= started - 60
        ]
        print("new sentencia_*.html files on failure:", newcomers)
    else:
        print("size:", os.path.getsize(path))
        with open(path) as f:
            head = f.read(2000)
        print("looks like sentence?", "ROL" in head or "Caratulado" in head)
        print("sidecar present?", os.path.isfile(path + ".metadata.json"))
```

**Pass criteria:**
1. `path is None` **or** `os.path.isfile(path)` — never a returned path that does not exist.
2. **When `path is None`:** no new `sentencia_*.html` was created in `save_dir` during the last 60 s. (This replaces the old "size > 5 KB" / "body does not contain 'rechazada'" criteria, which were **unreachable**: `_assert_not_blocked` raises *before* `page_source.encode()`, and its `RuntimeError` is caught by the outer `except Exception` → `return None`. An F5 body provably cannot land on disk, so those checks could never fire.)
3. **When `path` is not `None`:** the file exists, size > 5 KB, and its body contains `ROL` or `Caratulado`.
4. `<file>.metadata.json` (i.e. the literal path + `.metadata.json`) exists **when `path` is not `None`**. Note: `write_sidecar_metadata` swallows its own exceptions, so an absent sidecar is **not** evidence of a download failure — assert primarily on the return value (`path`), and treat the sidecar as corroboration.

**Failure modes and fixes:**

| Symptom | Cause | Fix |
|---|---|---|
| `path is None`, log says "could not open detail" | `_open_detail` couldn't find the row after paginating back | Log which page it stopped on. If it stopped before `target["page"]`, increase `_click_next_page` retry or increase `_wait_for_results` timeout after each page click |
| `path is None` and a `sentencia_*.html` **was** written | `_assert_not_blocked`'s ordering relative to `page_source.encode()` regressed | Re-check the ordering inside `download_inteiro_teor_url` — the assert must run before the content is captured |
| File is small (~2 KB) with F5 markers | Detector missed the specific F5 variant | Add the observed marker to `_F5_BODY_MARKERS`, re-run step 2 |
| `Ver sentencia` button not found | Section renders the button with different text (e.g. `Ver fallo`) | Inspect the row DOM, add the label to the XPath in `_open_detail` |
| Works on page 1, fails on page ≥2 | Pagination never advanced inside `_open_detail` | Verify `result["page"]` is present in the metadata dict — if a caller forgot to forward it, `_open_detail` defaults to page 1. Fix the call site (or make `_open_detail` fail loudly when `page` is missing) |

---

## 8. End-to-end on a second section

> **Precondition: step 5's P1 must pass on `civiles`.** Under Case A3 the `penales` search is filtered identically, and the rows returned will again be landing-page data — with `id_buscador` still `268` (the landing page *is* section-scoped), so criterion 1 would pass **vacuously**. Do not run this step without a green P1.

Repeat step 5 with `categoria="penales"` and assert:

- **P1/P2 of step 5 hold** — the first `data-idsentencia` changed after the search. Without this, criteria 1–3 below are satisfied by the landing page and prove nothing.
- `id_buscador == 268`
- `instancia == "penal"`
- The pager works (step 6 criteria)

Then repeat with `categoria="salud_cs"` and assert:

- **P1/P2 hold** for the `salud_cs` query as well.
- `id_buscador == 127`
- `instancia == "corte_suprema"` ← this is the §6 point that section ≠ instance

**If `salud_cs` returns `instancia == "salud"` or similar:** the map is wrong; only `tipo_instancia_principal` from the source notes is authoritative, and it says `corte_suprema`.

---

## 9. `Lineas_Jurisprudenciales` — special mode

This section has a different facet model (`es_lj: true`). The updated scraper does not yet branch on it, but the map flags it.

**Verify only that:**
- `CHILE_CATEGORIES["lineas_jurisprudenciales"]["es_lj"] is True`
- Loading `_navigate_to_category("lineas_jurisprudenciales")` succeeds and returns `628`
- In the live browser: `window.es_lj === true`

**Do not attempt to parse results from this section yet.** The correct fix is a separate code path; if you find that search returns garbage, add a `NotImplementedError` guard in `get_inteiro_links` when `es_lj` is True so downstream callers fail loudly instead of ingesting wrong data. Record this as a follow-up.

---

## 10. `Compendio_Extranjería` — negative test

```python
with ChileJurisprudenciaScraper(headless=False) as s:
    try:
        s.get_inteiro_links("", max_results=5,
                            filters={"categoria": "compendio_extranjeria"})
        print("FAIL: expected ValueError")
    except ValueError as e:
        print("OK:", e)
```

Expected: `ValueError` mentioning *"no verified id_buscador"*. If it proceeds, someone has filled in a guessed number — **revert to `None`** and add a comment referencing §11 item 1 of the source notes.

---

## 11. Reporting

The agent produces one report file, `verification_report.md`, with this exact shape:

```markdown
# chile_scraper.py — Verification Report
Date: YYYY-MM-DD
Operator / session: <profile path or "fresh">
Pinned artifact: chile_scraper.py @ sha1:<hash from the playbook header>
Pinned artifact observed: <git rev-parse HEAD:juris-search/chile_scraper.py>
Playbook: <path> @ sha256:<grep -v '^<!-- playbook-hash:' file | shasum -a 256>

## Amendments applied (this playbook revision)
| ID | Section | Change |
|----|---------|--------|
| D1 | §0.1 | freshness gate: `grep -q` (>=1 match) instead of "one hit each" — the old form caused a false STOP |
| D2 | §4 | replaced the false `quote(slug, safe="")` diagnosis with the three real causes; added the URL-encoding note |
| D3 | §5, §5.5, §6 | recalibrated to the portal's 10-row default; split page/len criteria; added step 5.5 (inert filter surface) |
| H1 | §2, §3 | added tests 2e/2f (TSPD image, body-less F5); split Case A into A1/A2 |
| H2 | §7 | replaced unreachable size/body criteria with a no-file-on-failure check |
| D4 | §5, §8 | added **P1/P2 provenance criteria** — `_navigate_to_category` lands on a page that already contains a default listing, so a green "10 rows" result can be landing data. Added the landing-vs-after snapshot script |
| D5 | §3, §5.5 | added **Case A3** — F5 rejection delivered inside the search `POST` XHR body (HTTP 200, `page_source` clean). Detection recipe + the observation that it invalidates steps 5–8 |
| D6 | §6, §7, §8 | recorded the **real pager markup** (Bootstrap 4, `#btnPaginador_pagina_adelante`) replacing the wrong DataTables guidance; corrected step 6's failure table; added Case-A3 preconditions to §7/§8 |
| minor | §0.5, §4, §10, §11 | `mkdir -p workspace/CL_jurisprudencia`; in-loop assertion; §11.N → §11 item N |

## Summary
| Step | Result | Notes |
|------|--------|-------|
| 1 Static | PASS/FAIL | |
| 2 F5 unit | PASS/FAIL | incl. 2e/2f |
| 3 F5 live | Case A1 (TSPD image) / Case A2 (rechazada) / Case B (through) | support_id=<n or None>; also record **Case A3** if the search POST is filtered |
| 4 Section map | PASS/FAIL | sections tested: ... |
| 5 Search | PASS/FAIL | **P1/P2 first**, then n=<n> (target 10), sample ROLs: ... |
| 5.5 Filter surface | OBSERVED | filter sent? Y/N |
| 6 Pagination | PASS/FAIL | pages seen: [...], total=<n> |
| 7 Detail+download | PASS/FAIL | path=<path|None>, size=<n> |
| 8 Second section | PASS/FAIL | penales=..., salud_cs=... |
| 9 LJ mode | PASS (flag) / n/a | |
| 10 Compendio negative | PASS/FAIL | |

## Changes made
- <file> L<line>: <what> — reason
- ... (empty if none)

## Open issues / follow-ups
- ...

## Evidence
- blocked page excerpt: <first 300 chars>
- search XHR verdict: through | F5-filtered (status + first 120 chars of body)
- landing vs after snapshot: <landing first id> -> <after first id>
- one sample result dict: <json>
- one downloaded file's first 500 chars: <text>
```

**Rules for the agent:**

- If a step fails and the fix is in the scraper, **fix it and rerun that step**; don't move on.
- If a step fails and the fix is *outside* the scraper (F5 CAPTCHA, Chrome profile, network), **stop and report** — do not paper over it.
- **If step 5.5 shows the search `POST` filtered (Case A3), stop the live run.** Steps 5–8 cannot produce meaningful evidence in that session; report them as **blocked**, and do not report them as failures of `chile_scraper.py`. Fixing Case A3 is a design change (a response interceptor), not a bug fix, and must not be attempted inside a verification pass.
- Do not modify `CHILE_CATEGORIES` id values except to correct a verified mismatch with §4. Guessing is prohibited.
- Do not add a `try/except` around `_assert_not_blocked`. Its job is to raise.
- Do **not** refactor `_parse_chile_text_result`, `_navigate_to_category`, `_click_next_page`, or `_open_detail` unless the run produces a **concrete, reproducible failure** attributable to that function. "The code looks wrong" is not a failure.
- Every code change must carry a one-line comment referencing the source notes (`# see docs/pjud-source.md §X` or `§11 item N`).

**The "Open issues" section must always include, at minimum:**

1. Page-size control is **not wired up** — `resultados_por_pagina` is arithmetic-only; the portal default (10) applies.
2. Advanced-search filters (`tribunal`, `juez`, `materia`, `rol`, dates) **never reach the portal** — `_run_search_ui` only fills the omnibox.
3. `_extract_support_id` is **Spanish-only**; the TSPD image challenge (English) yields `None`.
4. `_is_f5_block` is **body-only**; header-only rejections (`x-security-action`) are undetected.
5. `/busqueda/imprimir` is unprobed as an alternative artefact source.
6. `Compendio_Extranjería` `id_buscador` is **still unverified**.
7. `Lineas_Jurisprudenciales` special mode is **not implemented** (a guard is suggested).
8. **F5 rejections delivered inside an XHR body are undetectable** (Case A3). `POST /busqueda/buscar_sentencias` returns HTTP 200 with `La URL solicitada ha sido rechazada` while `driver.page_source` stays clean — so `_assert_not_blocked` never fires and `get_inteiro_links` returns the *landing page listing* as if it were search results. Fixing this needs a response-interceptor injected before navigation; it is a design change, deliberately not made in this pass.
9. **No freshness check anywhere in the search loop.** `_wait_for_results` treats the *existence* of `[data-idsentencia]` as readiness, but `_navigate_to_category` already rendered a default listing — so it never waits for the search, and after `_click_next_page` it reads the previous page's rows (all dedupe away, `new_on_page == 0`, loop exits). Both step 5's P1 trap and step 6's stall share this root cause.
10. **The pager markup is undocumented** in `docs/pjud-source.md` §7.1, which covers result rows only. The verified markup is now recorded in playbook §6 sub-step 6a; it should be folded into the source notes.

---

## 12. Fast triage if something is red

Priority order to investigate:

1. **F5 live step failing with Case A1/A2** → environmental. Solve CAPTCHA, restart session, retry.
2. **Case A3: search returns a plausible 10 rows but the query has no effect** → check the `POST /busqueda/buscar_sentencias` *response body* (step 5.5), not just the status. A `200` with `La URL solicitada ha sido rechazada` means every search-dependent step this run is invalid. Environmental — stop and report.
3. **`live_id != expected`** → check the map against §4 first, then the wait/paint timing. Do **not** "fix" `quote(slug, safe="")` — it is correct (see §4).
4. **`n == 0` on search with no F5** → DOM selector (`data-idsentencia`) drift. Inspect live DOM, update **both** `_parse_search_results` and `_wait_for_results`.
5. **Pagination stuck** → the pager is `#btnPaginador_pagina_adelante` (§6 sub-step 6a), already first in the selector list. If the click fires (returns `True`) and the page still does not advance, the cause is the missing freshness wait (open issue 9), not the selector.
6. **`path is None` on download** → `_open_detail` failure (row not found / page targeting), *not* an F5 body on disk — that state is unreachable (see §7). Under Case A3, expect `path is None` for an unrelated reason: **blocked**, not failed.
7. **`id_buscador`/`instancia` `None` in results** → threading broken from `cat_info` into `_parse_chile_text_result`. Trace the call chain in `_parse_search_results`.
8. **`len(results) != 10` with no F5** → check the corpus before blaming the pager (§5 criterion 8).

Anything else is a new bug — report it with the failing step number, the exception, and the first 500 chars of `driver.page_source`.