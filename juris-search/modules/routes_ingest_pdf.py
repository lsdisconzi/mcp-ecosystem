"""Upload + ingest PDF endpoints for juris-search.

Allows an administrator to upload a PDF containing one or more judgments and
run the existing court_extractor pipeline (extraction -> Qdrant ingestion).

Flow:
  1. POST /api/ingest-pdf/upload   -> saves the uploaded file, returns fileId
  2. POST /api/ingest-pdf/process  -> extracts every case and ingests to Qdrant
"""

import os
import re
import sys
import json
import uuid
import hashlib
import logging
import datetime as _dt
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from modules.config import BASE_DIR

logger = logging.getLogger("juris-search.ingest_pdf")

# Uploads are kept under a dedicated directory at the project root.
UPLOAD_DIR = os.environ.get(
    "JURIS_SEARCH_PDF_UPLOAD_DIR",
    str(BASE_DIR / "uploads"),
)
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Extracted case JSONs are written to extracted_documents/ — the same source
# directory the master indexer scans (JURIS_SEARCH_EXTRACTIONS_DIR). This keeps
# the upload pipeline consistent with court_extractor's own output location.
EXTRACTIONS_DIR = Path(os.environ.get(
    "JURIS_SEARCH_EXTRACTIONS_DIR",
    str(BASE_DIR / "extracted_documents"),
))
EXTRACTIONS_DIR.mkdir(parents=True, exist_ok=True)
JSON_OUT_DIR = EXTRACTIONS_DIR

# Supported tribunals (mirrors court_extractor.EXTRACTORS keys).
SUPPORTED_TRIBUNALS = ["TJSP", "TJMS", "TJCE", "TJRS", "TJPR"]


# ── lazy imports (court_extractor + ingest_to_qdrant + master indexer) ──────────

_extractor_available = False
_process_file = None
_load_master_lookup = None
_ingest_single = None
_master_indexer = None
_MASTER_INDEXER_AVAILABLE = False


def _try_import_extractor():
    global _extractor_available, _process_file, _load_master_lookup
    global _ingest_single, _master_indexer, _MASTER_INDEXER_AVAILABLE
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        import court_extractor
        _process_file = getattr(court_extractor, "process_file", None)
        _load_master_lookup = getattr(court_extractor, "_load_master_lookup", None)

        # Import the low-level ingest helper directly so we can key each point
        # by numero_processo (dedupe/idempotency across multi-case PDFs).
        import ingest_to_qdrant
        _ingest_single = getattr(ingest_to_qdrant, "ingest_single", None)

        # Master indexer, so uploaded cases also count in "Total Docs" / by_tribunal.
        try:
            from modules.master_indexer import _master_indexer as _mi, _MASTER_INDEXER_AVAILABLE as _mia
            _master_indexer = _mi
            _MASTER_INDEXER_AVAILABLE = bool(_mia)
        except Exception as exc:
            logger.warning("master_indexer not available: %s", exc)
            _master_indexer = None
            _MASTER_INDEXER_AVAILABLE = False

        _extractor_available = None not in (_process_file, _load_master_lookup, _ingest_single)
        if _extractor_available:
            logger.info("court_extractor + ingest_to_qdrant available for PDF ingestion")
    except Exception as exc:  # pragma: no cover
        logger.warning("court_extractor not available: %s", exc)


_try_import_extractor()

router = APIRouter()


class ProcessPdfRequest(BaseModel):
    fileId: str
    tribunal: str = "TJPR"


class IngestPdfResponse(BaseModel):
    ok: bool
    filename: Optional[str] = None
    casesExtracted: int = 0
    jsonWritten: int = 0
    ingested: int = 0
    failed: int = 0
    masterIndexUpdated: bool = False
    details: List[Dict[str, Any]] = []


@router.post("/api/ingest-pdf/upload")
async def upload_pdf(pdf: UploadFile = File(...)):
    """Receive a PDF, persist it under uploads/, and return a fileId."""
    if not (pdf.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Somente arquivos PDF são permitidos")

    file_id = str(uuid.uuid4())
    safe_name = os.path.basename(pdf.filename or "upload.pdf")
    dest = os.path.join(UPLOAD_DIR, f"{file_id}.pdf")
    try:
        with open(dest, "wb") as buffer:
            # FastAPI's UploadFile is already a buffered reader; stream in chunks.
            while True:
                chunk = await pdf.read(1024 * 1024)
                if not chunk:
                    break
                buffer.write(chunk)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao salvar o arquivo: {exc}")

    return {"fileId": file_id, "filename": safe_name}


@router.post("/api/ingest-pdf/process", response_model=IngestPdfResponse)
async def process_pdf(payload: ProcessPdfRequest):
    """Extract every case from the uploaded PDF and ingest each into Qdrant."""
    if not _extractor_available:
        raise HTTPException(
            status_code=503,
            detail="Pipeline de extração indisponível (court_extractor não carregado).",
        )

    tribunal = (payload.tribunal or "TJPR").strip().upper()
    if tribunal not in SUPPORTED_TRIBUNALS:
        raise HTTPException(
            status_code=400,
            detail=f"Tribunal '{tribunal}' não suportado. Use um de: {', '.join(SUPPORTED_TRIBUNALS)}.",
        )

    file_path = os.path.join(UPLOAD_DIR, f"{payload.fileId}.pdf")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado (fileId inválido).")

    # 1. Extract all cases from the PDF (returns List[dict]).
    master_lookup = _load_master_lookup()
    try:
        results = _process_file(file_path, tribunal, master_lookup)
    except Exception as exc:
        logger.exception("Falha na extração do PDF (fileId=%s, tribunal=%s)", payload.fileId, tribunal)
        raise HTTPException(status_code=500, detail=f"Erro na extração: {exc}")

    if not results:
        logger.warning(
            "Nenhum caso extraído do PDF (fileId=%s, tribunal=%s, arquivo=%s)",
            payload.fileId, tribunal, file_path,
        )
        raise HTTPException(status_code=422, detail="Nenhum caso extraído do PDF.")

    # 2. Persist each case as JSON + ingest into Qdrant, keyed by numero_processo
    #    so multiple cases in one PDF become distinct, idempotent points.
    ingested = 0
    failed = 0
    json_written = 0
    details: List[Dict[str, Any]] = []
    index_entries: List[Dict[str, Any]] = []
    for idx, doc in enumerate(results):
        proc = doc.get("numero_processo") or doc.get("cnj_numero") or f"desconhecido_{idx}"
        safe_proc = re.sub(r"[^0-9A-Za-z._-]", "_", proc)

        # 2a. Write the extracted case JSON into extracted_documents/ (per the
        #     court_extractor convention / JURIS_SEARCH_EXTRACTIONS_DIR). The master
        #     indexer reads numero_processo/tribunal from source_metadata, so we
        #     embed it there in addition to the top-level fields.
        json_path = JSON_OUT_DIR / f"{tribunal}_{safe_proc}.json"
        doc["source_file"] = file_path
        doc.setdefault("source_metadata", {})
        doc["source_metadata"]["numero_processo"] = proc
        doc["source_metadata"]["tribunal"] = tribunal
        # The master indexer reads tribunal from source_metadata.search_params.tribunal.
        doc["source_metadata"].setdefault("search_params", {})["tribunal"] = tribunal
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=2)
            json_written += 1
            # Register a ready entry in json_jurisprudence/index.json — the actual
            # source the master indexer counts documents from (see juris_indexer._scan).
            index_entries.append({
                "id": hashlib.sha1(str(json_path).encode("utf-8")).hexdigest()[:16],
                "status": "ready",
                "error": None,
                "parser": None,
                "source_path": file_path,
                "source_relative": f"extracted_documents/{json_path.name}",
                "source_signature": str(os.path.getsize(json_path)),
                "source_sidecar_path": None,
                "json_path": str(json_path),
                "json_relative": json_path.name,
                "processed_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            })
        except Exception as exc:
            logger.error(
                "INGEST PDF | falha ao escrever JSON | tribunal=%s | processo=%s | erro=%s",
                tribunal, proc, exc,
            )

        # 2b. Ingest into Qdrant (doc_id = numero_processo for dedupe).
        try:
            result = _ingest_single(doc, doc_id=proc)
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        if result.get("ok"):
            ingested += 1
            logger.info(
                "INGEST PDF | caso ingerido | tribunal=%s | processo=%s | fileId=%s",
                tribunal, proc, payload.fileId,
            )
        else:
            failed += 1
            logger.error(
                "INGEST PDF | falha na ingestão | tribunal=%s | processo=%s | fileId=%s | erro=%s",
                tribunal, proc, payload.fileId, result.get("error"),
            )
        details.append({
            "numero_processo": proc,
            "json_path": str(json_path.name),
            "ok": bool(result.get("ok")),
            "error": result.get("error"),
        })

    # 2c. Register the new case JSONs in json_jurisprudence/index.json — the source
    #     the master indexer actually counts documents from (juris_indexer._scan).
    #     extracted_documents/ alone only *enriches* existing records, it does not
    #     create new ones, so this registration is what makes Total Docs / by_tribunal
    #     grow. Idempotent: existing json_path entries are skipped.
    if index_entries:
        try:
            from modules.config import JSON_INDEX_PATH
            from modules.utils import _read_json_file, _write_json_file
            index_payload = _read_json_file(JSON_INDEX_PATH, {"entries": []})
            if not isinstance(index_payload, dict) or "entries" not in index_payload:
                index_payload = {"entries": []}
            existing_paths = {
                e.get("json_path")
                for e in (index_payload.get("entries") or [])
                if isinstance(e, dict)
            }
            added = 0
            for entry in index_entries:
                if entry["json_path"] not in existing_paths:
                    index_payload["entries"].append(entry)
                    existing_paths.add(entry["json_path"])
                    added += 1
            entries = index_payload.get("entries") or []
            index_payload["total_entries"] = len(entries)
            index_payload["ready_entries"] = sum(
                1 for e in entries if e.get("status") == "ready"
            )
            index_payload["failed_entries"] = sum(
                1 for e in entries if e.get("status") == "failed"
            )
            index_payload["generated_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
            _write_json_file(JSON_INDEX_PATH, index_payload)
            logger.info("INGEST PDF | index.json atualizado | novos=%d | total=%d", added, len(entries))
        except Exception as exc:
            logger.warning("INGEST PDF | falha ao atualizar index.json: %s", exc)

    # 3. Rebuild the master index so the new entries (and enriched extractions)
    #    reflect in "Total Docs", the by_tribunal breakdown, and the stats.
    master_index_updated = False
    if _MASTER_INDEXER_AVAILABLE and _master_indexer is not None:
        try:
            _master_indexer.rebuild(force_ingest=True)
            master_index_updated = True
            logger.info("INGEST PDF | master index rebuild disparado (force_ingest=True)")
        except Exception as exc:
            logger.warning("INGEST PDF | master index rebuild falhou: %s", exc)

    master_index_updated = False
    if _MASTER_INDEXER_AVAILABLE and _master_indexer is not None:
        try:
            _master_indexer.rebuild(force_ingest=True)
            master_index_updated = True
            logger.info("INGEST PDF | master index rebuild disparado (force_ingest=True)")
        except Exception as exc:
            logger.warning("INGEST PDF | master index rebuild falhou: %s", exc)

    logger.info(
        "INGEST PDF | concluído | tribunal=%s | arquivo=%s | fileId=%s | "
        "extraidos=%d | json=%d | ingeridos=%d | falhas=%d | master_index=%s",
        tribunal, os.path.basename(file_path), payload.fileId,
        len(results), json_written, ingested, failed, master_index_updated,
    )

    return IngestPdfResponse(
        ok=failed == 0,
        filename=os.path.basename(file_path),
        casesExtracted=len(results),
        jsonWritten=json_written,
        ingested=ingested,
        failed=failed,
        masterIndexUpdated=master_index_updated,
        details=details,
    )
