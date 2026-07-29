# Court Coverage & Status Report — juris-search

Generated: 2026-05-27

## Summary

| Tier | Courts | Count | Status |
|---|---|---|---|
| 1 — WORKING | TJSP, TJMS, TJCE | 3 | Real PDFs, text extracted, extraction schemas ready |
| 2 — NEEDS CONVERSION | TJRS | 1 | 265 .doc files downloaded, need LibreOffice conversion |
| 3 — CAPTCHA BLOCKED | TJAC, TJAL, TJAM (+TJSP partial) | 4 | Search works, downloads are CAPTCHA/403 pages |
| 4 — SEARCH OK, NO DOWNLOADS | TJMA, TJBA, TJPE, TJPB, TJRN, TJSE, TJPI, TJES, TJPR, TJSC, TJMT, TJPA, TJRO, TJGO, TJDFT, TJTO, TJRR, TJAP | 18 | Search returned results but batch download not triggered |
| 5 — SEARCH FAILED | TJMG, TJRJ, STF | 3 | Search returned 0 results or error |

Total attempted: 29 courts (28 TJs + STF)

---

## Tier 1 — Working Courts (Ready for Full Extraction)

These courts use the e-SAJ system. Search + download + text extraction work correctly.

| Court | Real Docs | Blocked | No Text | Scraper |
|---|---|---|---|---|
| **TJSP** | 294 PDF | 112 (403) | 62 | `tjsp_scraper.py` |
| **TJMS** | 128 PDF | 0 | 33 | `_shared/esaj_scraper.py` |
| **TJCE** | 23 PDF | 0 | 24 | `_shared/esaj_scraper.py` |
| **Total** | **445** | 112 | 119 | |

**Action**: Run `court_extractor.py` on all 445 real-text docs. The extraction schemas in
`court_samples/EXTRACTION_SCHEMAS.md` cover all 3 courts.

**TJSP 403 issue**: 112 TJSP docs got HTTP 403 errors. All are `text_chars=172` HTML pages saying
"Access denied". These need re-downloading — same scraper with different timing/IP.

---

## Tier 2 — TJRS: Downloaded but Needs Conversion

**265 .doc files** downloaded. The TJRS-specific scraper (`tjrs_scraper.py`) works — it downloads
binary .doc files directly from `tjrs.jus.br`. But the text extraction pipeline requires DOCX
format (python-docx can't read .doc).

**Status today**: The watcher just converted 2 new .doc files to .docx (visible in
`docx_jurisprudence/index.json` from 17:38). The `convert_docs.py` or `parallel_convert.py`
scripts handle this via LibreOffice headless.

**Action**:
1. Run `parallel_convert.py` to convert all 265 .doc → .docx
2. Copy converted DOCXs to `court_samples/jurisprudence-documents/docx/`
3. Run `court_extractor.py --courts TJRS` on all 265 documents

**Note**: TJRS documents have a unique multi-facto structure (different from TJSP/TJMS/TJCE).
The TJRS extractor handles this but cross-references master_index for metadata not in body text.

---

## Tier 3 — CAPTCHA-Blocked Courts

These courts use the e-SAJ system. The search works (results are returned) but when downloading
the full document (inteiro teor), the system returns a Google reCAPTCHA challenge instead of the
document.

| Court | CAPTCHA | No Text | System |
|---|---|---|---|
| **TJAM** (Amazonas) | 47/47 | 0 | e-SAJ |
| **TJAC** (Acre) | 33/42 | 9 | e-SAJ |
| **TJAL** (Alagoas) | 38/39 | 1 | e-SAJ |
| **TJSP** (partial) | 0 (403) | 112 | e-SAJ |

**Root cause**: The e-SAJ `cjsg/captchaControleAcesso.do` endpoint requires a CAPTCHA token
before serving the document. The current scrapers don't include CAPTCHA solving.

**Fix options** (in order of feasibility):
1. **Session cookie injection** — Manually solve CAPTCHA once in a browser, capture session
   cookies, inject them into the scraper's requests session. Simplest, works for batch runs.
2. **2captcha API** — Integrate a CAPTCHA solving service (~$3 per 1000 solves).
3. **Playwright stealth** — Use Playwright with stealth plugin to avoid triggering CAPTCHA.

**Action**: Implement option 1 first (fastest to test). Re-download affected courts.

---

## Tier 4 — Search Works, Downloads Not Triggered (18 courts)

These 18 courts all returned search results (40-90 per search) but the batch download was never
triggered. All use the e-SAJ system and should work once download is enabled.

| Court | Max Results | Searches |
|---|---|---|
| TJMT | 90 | 3 |
| TJMA, TJBA, TJPE, TJPB, TJRN, TJSE, TJPI, TJES, TJPR, TJSC | 60 each | 4-5 |
| TJPA, TJRO, TJGO, TJDFT, TJTO, TJRR, TJAP | 40 each | 2-3 |

**Root cause**: These courts were included in search jobs but the batch download was either:
- Not called (search-only mode)
- Failed silently before writing results to master index

**Action**: Trigger batch download for these courts. They use the generic `esaj_scraper.py` which
already handles the search→download pipeline for TJMS and TJCE successfully.

**Note**: Some of these may also hit CAPTCHA (same e-SAJ system as Tier 3). We won't know until
we try downloading.

---

## Tier 5 — Search Failed (Zero Results)

| Court | Status | Scraper |
|---|---|---|
| **TJMG** | 6 searches, 0 results | `tjmg_scraper.py` (custom) |
| **TJRJ** | 4 searches, 0 results | `tjrj_scraper.py` (custom) |
| **STF** | 4 searches, 0 results | No dedicated scraper |

**TJMG and TJRJ** have custom scrapers that are failing silently (no errors logged in search
history, but no results either). These courts use different systems than e-SAJ:
- TJMG uses `tjmg.jus.br` with its own search interface
- TJRJ uses `tjrj.jus.br` with its own search interface

**STF** (Supremo Tribunal Federal) uses `stf.jus.br` — completely different system, no scraper.

**Action**: Debug TJMG and TJRJ scrapers. STF needs a new scraper entirely.

---

## Recommended Priority Order

1. **IMMEDIATE**: Run full extraction on Tier 1 (445 docs across TJSP/TJMS/TJCE)
2. **IMMEDIATE**: Convert TJRS .doc files and extract (265 docs)
3. **THIS WEEK**: Fix CAPTCHA for TJAC/TJAL/TJAM (118 docs blocked)
4. **THIS WEEK**: Trigger batch downloads for Tier 4 courts (18 courts, may need CAPTCHA)
5. **NEXT**: Debug TJMG/TJRJ scrapers
6. **LATER**: Build STF scraper

## Expected Full Corpus

After fixing Tiers 1-4:
- Tier 1: 445 docs (already have)
- Tier 2: 265 docs (already have, need conversion)
- Tier 3: ~118 docs (need CAPTCHA fix + re-download)
- Tier 4: ~800-1000 docs (need download trigger)
- **Total**: ~1,600-1,800 documents from 25 courts
