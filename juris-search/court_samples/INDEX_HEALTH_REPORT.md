# juris-search Index Health & Completeness Report

**Generated**: 2026-05-27  
**Master index**: 1,049 documents across 7 courts  
**Qdrant collection**: `law_br` — 1,051 vectors (768 dims)

---

## 1. Executive Summary

| Metric | Value | Status |
|---|---|---|
| Total documents in master index | 1,049 | OK |
| Courts covered | 7 (TJSP, TJRS, TJMS, TJAM, TJCE, TJAC, TJAL) | OK |
| Qdrant vectors | 1,051 | OK |
| Documents with real extracted text (>1k chars) | 445 (42%) | DEGRADED |
| Documents with blocked content (403/CAPTCHA) | 230 (22%) | BLOCKED |
| Documents with no text extraction (null/0 chars) | 374 (36%) | MISSING |
| Search history jobs | 30 | OK |
| ID prefix mismatch (TJRS) | 245 docs | BUG |

---

## 2. Per-Court Breakdown

### TJSP — São Paulo (468 docs)
| Aspect | Status |
|---|---|
| Real text (>1k chars) | 294 docs |
| Blocked (403 errors) | 112 docs |
| No text | 62 docs |
| Format | PDF → text extraction working |
| **Readiness** | **GOOD — 63% have usable content** |

### TJRS — Rio Grande do Sul (245 docs)
| Aspect | Status |
|---|---|
| Real text | **0 docs** |
| No text | 245 docs |
| Raw files | .doc format (binary MS Word), all downloaded |
| Format | .doc → needs LibreOffice conversion |
| ID bug | Master uses `tjsp_` prefix, Qdrant uses `cnj_` prefix |
| **Readiness** | **BLOCKED — needs .doc→text conversion pipeline** |

### TJMS — Mato Grosso do Sul (161 docs)
| Aspect | Status |
|---|---|
| Real text | 128 docs |
| No text | 33 docs |
| Format | PDF → text extraction working |
| **Readiness** | **GOOD — 80% have usable content** |

### TJCE — Ceará (47 docs)
| Aspect | Status |
|---|---|
| Real text | 23 docs |
| No text | 24 docs |
| Format | PDF → text extraction working |
| **Readiness** | **FAIR — 49% have usable content** |

### TJAM — Amazonas (47 docs)
| Aspect | Status |
|---|---|
| Real text | **0 docs** |
| CAPTCHA | 47 docs (100%) |
| **Readiness** | **BLOCKED — all downloads are CAPTCHA pages** |

### TJAC — Acre (42 docs)
| Aspect | Status |
|---|---|
| Real text | **0 docs** |
| CAPTCHA | 33 docs |
| No text | 9 docs |
| **Readiness** | **BLOCKED — 79% CAPTCHA** |

### TJAL — Alagoas (39 docs)
| Aspect | Status |
|---|---|
| Real text | **0 docs** |
| CAPTCHA | 38 docs |
| No text | 1 doc |
| **Readiness** | **BLOCKED — 97% CAPTCHA** |

---

## 3. Qdrant Collection Status

### `law_br` Collection
- **Points**: 1,051 vectors
- **Dimension**: 768
- **Frameworks**: 0 (no statute linkage)
- **Doc types**: All classified as `unknown`
- **Last OK**: 2026-05-27T12:35:57Z

### Issues Found

1. **ID Prefix Mismatch (TJRS)**: The 245 TJRS documents were ingested into Qdrant with `cnj_` prefix but the master index references them with `tjsp_` prefix. The `.qdrant_state.json` file uses `cnj_` keys. This means:
   - Master index can't look up Qdrant vectors by ID for TJRS docs
   - The state file is inconsistent with the master index

2. **No Framework Association**: All 1,051 vectors are typed `unknown`. The ARGUS law library frameworks (61 statutes) are not linked to any jurisprudence document.

3. **No doc_type Classification**: Documents aren't classified by type (acórdão, sentença, decisão monocrática, etc.)

4. **2 Extra Vectors**: Qdrant has 1,051 points vs 1,049 in master index. 2 vectors exist in Qdrant without corresponding master index entries.

---

## 4. File Storage

| Directory | Files | Size |
|---|---|---|
| `json_jurisprudence/` | 968 JSON files | 24 MB |
| `docx_jurisprudence/` | 304 DOCX files | 451 MB |
| `jurisprudence_downloads/` | 2,499 files | 408 MB |
| `searches_history/` | 30 search job files | 1.6 MB |

### Download File Types
- `.json` (sidecar/metadata): 1,272 files
- `.pdf`: 618 files
- `.html`: 305 files
- `.doc`: 304 files (all TJRS)

---

## 5. Critical Gaps & Recommended Actions

### BLOCKER 1: CAPTCHA Courts (TJAC, TJAL, TJAM)
**118 docs total — zero real content.**
- All downloads returned Google reCAPTCHA pages
- Need: CAPTCHA solver integration (2captcha, stealth Playwright, or session cookies)
- These 3 courts use SAJ system (same as TJSP) and likely have similar document structure once scraped

### BLOCKER 2: TJRS .doc Conversion
**245 docs downloaded but zero text extracted.**
- All 245 files are binary `.doc` format
- `convert_docs.py` exists at `/home/disconzi1986_gmail_com/juris-search-VPS/docx_jurisprudence/convert_docs.py` but hasn't been executed
- LibreOffice is installed and confirmed working (converted sample successfully)
- Estimated conversion time: ~30-60 minutes for 245 docs via LibreOffice --headless
- After conversion: need to run the text extraction and Qdrant ingestion

### BUG: TJRS ID Prefix Mismatch
- Master index IDs: `tjsp_700XXXXXXXX`
- Qdrant state IDs: `cnj_700XXXXXXXX`
- Fix: normalize IDs in either direction, re-sync state file

### GAP: No Framework/Law Linking
- `law_br` collection has 0 frameworks
- ARGUS law library has 61 statutes available
- Need: semantic linking between jurisprudence and applicable legislation

### GAP: CAPTCHA-Residue in TJSP (112 docs)
- 112 TJSP docs also hit CAPTCHA (24% of TJSP total)
- These need re-downloading with CAPTCHA bypass

---

## 6. What's Ready Now

These courts have real, extractable content and are ready for structured field extraction:

| Court | Docs | Sample File |
|---|---|---|
| TJSP | 294 | `court_samples/TJSP_tjsp_20537826.json` |
| TJMS | 128 | `court_samples/TJMS_tjsp_1768660.json` |
| TJCE | 23 | `court_samples/TJCE_tjsp_3836138.json` |
| TJRS | 1* | `court_samples/TJRS_tjsp_70078303831.txt` |

*TJRS sample converted manually as proof of concept.

Extraction schemas defined in: `court_samples/EXTRACTION_SCHEMAS.md`
