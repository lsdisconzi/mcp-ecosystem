# PDF Upload → Extraction → Indexing Flow (Administração do Sistema)

This document describes the end-to-end flow added by the **"Upload de Documentos (PDF)"**
card, including where each artifact is written, what shows up in which dashboard, and the
current gaps (open questions for review).

---

## 1. User flow (frontend)

Location: `tjrs-frontend/src/AdminView.jsx` → section "Upload de Documentos (PDF)"
(Sec. 4.5, before the API Tester).

1. Admin selects a `.pdf` file (file input, `accept=".pdf"`). There is **no** URL/endpoint
   field — the input is the file itself.
2. Admin picks a tribunal from the dropdown (`TJPR` default; options:
   `TJSP, TJMS, TJCE, TJRS, TJPR`).
3. Click **Enviar** → `POST /api/ingest-pdf/upload` saves the file and returns a `fileId`.
4. Click **Processar** → `POST /api/ingest-pdf/process` runs extraction + Qdrant ingestion.
5. On success, the UI calls `fetchAllData()` so the System Overview / Qdrant tiles refresh.

---

## 2. Backend endpoints

Router: `modules/routes_ingest_pdf.py` (mounted under both `/api` and `/juris/api` in
`main.py`).

### `POST /api/ingest-pdf/upload`
- Receives the multipart PDF, streams it (1 MB chunks) to
  `uploads/<uuid>.pdf` (`UPLOAD_DIR`, overridable via `JURIS_SEARCH_PDF_UPLOAD_DIR`).
- Returns `{ fileId, filename }`.

### `POST /api/ingest-pdf/process`  `{ fileId, tribunal }`
1. Validates the tribunal is supported.
2. Resolves `uploads/<fileId>.pdf`.
3. Calls `court_extractor.process_file(file_path, tribunal, master_lookup)`:
   - Extracts text from the PDF (pdfplumber/PyPDF-style extractor inside `court_extractor`).
   - For `TJPR`, **splits on every process-number marker** (`Processo:` + CNJ pattern, now
     case-insensitive and tolerant of extra spaces/dashes) and runs `TJPRExtractor` on each
     block → a **list of case dicts** (one per judgment). For other tribunals, one dict.
   - Each case dict contains: `numero_processo`, `relator`, `orgao_julgador`,
     `data_publicacao`, `comarca`, `classe`, `partes`, `ementa`, `votacao`, `decisao`,
     `texto_integro`, `tribunal`, `texto_length`, `extraction_confidence`, plus metadata.
4. Loops over every case dict and calls `court_extractor.ingest_extracted_to_qdrant(doc)`,
   which delegates to `ingest_to_qdrant.ingest_single(doc, collection="juris_br_v1",
   api_base=<qdrant mgmt API>)`.
5. Returns `{ casesExtracted, ingested, failed, details }`.

---

## 3. Where things are saved

| Artifact | Location | Written by |
|---|---|---|
| Uploaded PDF | `uploads/<uuid>.pdf` | `ingest-pdf/upload` |
| Per-case JSON (extraction) | `extracted_documents/` (via `court_extractor`) | `ingest_extracted_to_qdrant` → `ingest_to_qdrant` (intermediate export) |
| Qdrant vectors | collection `juris_br_v1` (dimension 768) | `ingest_single` → Qdrant mgmt API |

> **Important:** the current `process` step goes **PDF → Qdrant directly**. It does *not*
> write the case JSONs into the standard `json_jurisprudence/` directory, nor does it
> register them in `master_index/master_index.json`.

---

## 4. What shows up where (dashboard mapping)

| Dashboard tile | Data source | Reflects PDF ingest? |
|---|---|---|
| **Qdrant Vectors** (Visão Geral) | `/api/admin/qdrant-collections` → sum of `vectors_count` across all collections | ✅ Yes — `juris_br_v1` grows (e.g. 580 → 595) |
| **Coleções Qdrant** | same endpoint | ✅ `juris_br_v1` points increase |
| **Total Docs** | `/api/master-index/stats` → `master_index` | ❌ **No** — count comes from `master_index.json`, not Qdrant |
| **Por Tribunal (TJSP: 522 …)** | `master_index.stats.by_tribunal` | ❌ **No** — TJPR not in `master_index`; never appears |
| **Extração / Índice (715 docs)** | `master_index.total_documents` | ❌ **No** — same reason |
| **JSON Ready (921)** | `/api/json/index` (scans `json_jurisprudence/`) | ❌ **No** — JSONs not written there |
| **DOCX Ready (5)** | `/api/docx/index` | ❌ **No** |

So a TJPR PDF ingest **only** moves the Qdrant vector counts — which is why the Overview
"felt unchanged" for Total Docs / Tribunais.

---

## 5. Open questions for review (decide before next step)

1. **Should ingested PDFs count toward "Total Docs"?** Today they don't, because that number
   is sourced from `master_index.json`. To make TJPR uploads show up in `Total Docs`,
   `by_tribunal`, and `Extração/Índice`, we would need the `process` step to also:
   - write each case JSON into `json_jurisprudence/`, and
   - update / rebuild `master_index.json` (or feed the master indexer).

2. **Re-ingest vs. dedupe.** `ingest_single` keys points by `doc_id` (default = source file).
   Multiple cases in one PDF could collide on the same `doc_id` and overwrite each other in
   Qdrant. We should key by `numero_processo` so each judgment is a distinct, idempotent
   point.

3. **Blocking vs. async.** `process` is a synchronous, blocking request. Large PDFs will
   time out the HTTP call. The spec suggested a background task + status poll (Celery/RQ or
   a `/process-status/{taskId}` endpoint). Fine to keep blocking for now?

4. **Tribunal detection.** Today the admin must pick the tribunal. We could auto-detect from
   the CNJ (the 7th digit block `8.16` → TJPR, etc.), removing the manual selector.

---

## 6. How to observe an ingest today

```bash
# In api.log (start.sh points the API at LOG_DIR/api.log):
grep "INGEST PDF" "$LOG_DIR/api.log"

# Sample lines:
# INGEST PDF | caso ingerido | tribunal=TJPR | processo=0008633-59.2022.8.16.0017 | fileId=...
# INGEST PDF | concluído | tribunal=TJPR | arquivo=...pdf | fileId=... | extraidos=15 | ingeridos=15 | falhas=0

# Confirm Qdrant collection grew:
curl -s localhost:8066/v1/qdrant/collections | jq '.collections[] | select(.name=="juris_br_v1")'
```
