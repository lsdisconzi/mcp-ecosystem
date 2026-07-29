"""
Master jurisprudence indexer + dynamic watcher.

Scans the four canonical folders:
  - searches_history/         (search jobs, fields, and result lists)
  - jurisprudence_downloads/  (raw .doc/.docx/.pdf/.html + .metadata.json sidecars)
  - docx_jurisprudence/       (normalized DOCX + index.json)
  - json_jurisprudence/       (structured per-doc JSON + index.json)

Builds a unified master index (master_index.json + per-doc records),
keyed by a canonical document ID derived from the most reliable identifier
available (process number + ano + codigo for TJRS, cdacordao for TJSP, etc.),
with as much extracted detail as possible.

The output schema follows the **optimal JSON structure** (nested objects for
órgão julgador, partes, advogados, decisão, etc.), enabling powerful queries
and analytics while maintaining backward compatibility for most consumers.

Optionally pushes each document to:
  - Qdrant (via the 8066 management API) — collection `law_br`
  - Awareness memory (via the 8066 API)  — collection `juris_search_memory`

Designed to run as a background watcher thread inside the FastAPI app
without adding new Python dependencies (uses only stdlib + urllib).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("juris-search.indexer")

# ── Filename / text patterns ─────────────────────────────────────────────────

TJRS_FNAME_RE = re.compile(
    r"inteiro_teor_(?P<numero>\d+)_(?P<ano>\d{4})_(?P<codigo>\d+)",
    re.IGNORECASE,
)
ESAJ_FNAME_RE = re.compile(
    r"(?:inteiro_teor|acordao|cdacordao)[_\-]?(?P<cdacordao>\d{6,})",
    re.IGNORECASE,
)
TJMG_FNAME_RE = re.compile(
    r"inteiro_teor[_\-]?(?P<numero>\d{7,})",
    re.IGNORECASE,
)
TJRJ_FNAME_RE = re.compile(
    r"inteiro_teor[_\-]?(?P<numero>\d{7,})",
    re.IGNORECASE,
)
CNJ_PROC_RE = re.compile(r"\b(\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4})\b")

DESC_RELATOR_RE = re.compile(r"Relator:\s*([^|]+?)(?:\s*\||$)", re.IGNORECASE)
DESC_TIPO_RE = re.compile(r"Tipo:\s*([^|]+?)(?:\s*\||$)", re.IGNORECASE)
DESC_COMARCA_RE = re.compile(r"Comarca:\s*(?:de\s+Origem:\s*)?([^|]+?)(?:\s*\||$)", re.IGNORECASE)
DESC_PROCESSO_RE = re.compile(r"Processo\s+(\d{6,})", re.IGNORECASE)
DESC_ORGAO_RE = re.compile(r"(?:Órgão|Orgao)\s+Julgador:\s*([^|]+?)(?:\s*\||$)", re.IGNORECASE)
DESC_DATA_JULG_RE = re.compile(r"(?:Data\s+de\s+Julgamento|Julgado\s+em):\s*([0-9/\-\.]+)", re.IGNORECASE)
DESC_DATA_PUB_RE = re.compile(r"(?:Data\s+de\s+Publica[cç][aã]o|Publica[cç][aã]o):\s*([0-9/\-\.]+)", re.IGNORECASE)

DATE_DDMMYYYY_RE = re.compile(r"\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})\b")
MONEY_RE = re.compile(r"R\$\s*[\d\.\,]+", re.IGNORECASE)
OUTCOME_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("negado_provimento",     re.compile(r"\bnegar(?:am)?\s+provimento\b", re.IGNORECASE)),
    ("dado_provimento",       re.compile(r"\bd(?:ar(?:am)?|eram)\s+provimento\b", re.IGNORECASE)),
    ("provimento_parcial",    re.compile(r"\bparcial(?:mente)?\s+provimento\b|\bprovimento\s+parcial\b", re.IGNORECASE)),
    ("reformada",             re.compile(r"\bsenten[cç]a\s+reformada\b", re.IGNORECASE)),
    ("mantida",               re.compile(r"\bmantida\s+a\s+senten[cç]a\b|\bmantenho\s+por\s+seus\s+pr[oó]prios\s+fundamentos\b", re.IGNORECASE)),
    ("procedente",            re.compile(r"\bjulgo\s+procedente\b|\bprocedente\s+o\s+pedido\b", re.IGNORECASE)),
    ("improcedente",          re.compile(r"\bjulgo\s+improcedente\b|\bimprocedente\s+o\s+pedido\b", re.IGNORECASE)),
    ("unanime",               re.compile(r"\bun[aâ]nime\b", re.IGNORECASE)),
]
EMENTA_END_RE = re.compile(r"\b(AC[ÓO]RD[ÃA]O|RELAT[ÓO]RIO|VOTOS?)\b")

TRIBUNAL_HINTS = (
    ("tjrs.jus.br", "TJRS"),
    ("tjsp.jus.br", "TJSP"),
    ("esaj.tjsp", "TJSP"),
    ("stf.jus.br", "STF"),
    ("portal.stf", "STF"),
    ("tjpr.jus.br", "TJPR"),      # add this
    ("projudi.tjpr", "TJPR"),     # for Projudi links
)

# ── Config ───────────────────────────────────────────────────────────────────

def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}

@dataclass
class IndexerConfig:
    base_dir: Path
    downloads_dir: Path
    docx_dir: Path
    json_dir: Path
    history_dir: Path
    master_dir: Path
    extractions_dir: Path
    interval_seconds: int = 30
    qdrant_enabled: bool = True
    qdrant_base_url: str = "http://localhost:8114"
    qdrant_collection: str = "juris_br_v1"
    qdrant_vector_size: int = 768
    awareness_enabled: bool = False
    awareness_base_url: str = "http://localhost:8114"
    awareness_collection: str = "juris_search_memory"
    request_timeout: float = 60.0

    @classmethod
    def from_env(cls, base_dir: Path, downloads_dir: Path, docx_dir: Path, json_dir: Path, history_dir: Path) -> "IndexerConfig":
        master_dir = Path(os.environ.get("JURIS_SEARCH_MASTER_INDEX_DIR", str(base_dir / "master_index")))
        extractions_dir = Path(os.environ.get("JURIS_SEARCH_EXTRACTIONS_DIR", str(base_dir / "extracted_documents")))
        return cls(
            base_dir=base_dir,
            downloads_dir=downloads_dir,
            docx_dir=docx_dir,
            json_dir=json_dir,
            history_dir=history_dir,
            master_dir=master_dir,
            extractions_dir=extractions_dir,
            interval_seconds=max(5, int(os.environ.get("JURIS_SEARCH_MASTER_INDEX_INTERVAL", "30"))),
            qdrant_enabled=_env_flag("JURIS_SEARCH_QDRANT_INGEST", True),
            qdrant_base_url=os.environ.get("JURIS_SEARCH_QDRANT_API", "http://localhost:8114").rstrip("/"),
            qdrant_collection=os.environ.get("JURIS_SEARCH_QDRANT_COLLECTION", "juris_br_v1"),
            qdrant_vector_size=int(os.environ.get("JURIS_SEARCH_QDRANT_VECTOR_SIZE", "768")),
            awareness_enabled=_env_flag("JURIS_SEARCH_AWARENESS_INGEST", False),
            awareness_base_url=os.environ.get("JURIS_SEARCH_AWARENESS_API", "http://localhost:8114").rstrip("/"),
            awareness_collection=os.environ.get("JURIS_SEARCH_AWARENESS_COLLECTION", "juris_search_memory"),
            request_timeout=float(os.environ.get("JURIS_SEARCH_INDEX_HTTP_TIMEOUT", "60")),
        )

# ── Utilities ────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"

def _read_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except Exception as exc:
        logger.debug("read_json failed for %s: %s", path, exc)
        return default

def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    tmp.replace(path)

def _stable_id(*parts: str) -> str:
    raw = "|".join(p for p in parts if p)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

_DOC_UUID_NS = uuid.NAMESPACE_URL

def _doc_uuid(doc_id: str) -> str:
    return str(uuid.uuid5(_DOC_UUID_NS, f"juris-search://doc/{doc_id}"))

def _detect_tribunal(*hints: Optional[str]) -> Optional[str]:
    for hint in hints:
        if not hint:
            continue
        h = hint.lower()
        for needle, label in TRIBUNAL_HINTS:
            if needle in h:
                return label
    return None

def _parse_iso_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    if re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return value[:10]
    return None

def _http_post_json(url: str, payload: Dict[str, Any], timeout: float) -> Tuple[int, Dict[str, Any]]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", errors="replace")
            data = json.loads(raw) if raw else {"detail": str(exc)}
        except Exception:
            data = {"detail": str(exc)}
        return exc.code, data
    except Exception as exc:
        return 0, {"detail": str(exc)}

def _http_get_json(url: str, timeout: float) -> Tuple[int, Any]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        return exc.code, {"detail": str(exc)}
    except Exception as exc:
        return 0, {"detail": str(exc)}

# ── Document record extraction ───────────────────────────────────────────────

@dataclass
class DocRecord:
    """Internal flat representation – remains unchanged for flexibility."""
    id: str
    tribunal: Optional[str] = None
    numero_processo: Optional[str] = None
    cnj_numero: Optional[str] = None
    ano: Optional[str] = None
    codigo: Optional[str] = None
    cdacordao: Optional[str] = None
    classe: Optional[str] = None
    tipo_processo: Optional[str] = None
    assunto: Optional[str] = None
    relator: Optional[str] = None
    orgao_julgador: Optional[str] = None
    comarca: Optional[str] = None
    data_julgamento: Optional[str] = None
    data_publicacao: Optional[str] = None
    data_registro: Optional[str] = None
    downloaded_at: Optional[str] = None
    ementa: Optional[str] = None
    outcome: List[str] = field(default_factory=list)
    monetary_values: List[str] = field(default_factory=list)
    cited_processes: List[str] = field(default_factory=list)
    inteiro_url: Optional[str] = None
    source_page_url: Optional[str] = None
    download_url: Optional[str] = None
    file_size_bytes: Optional[int] = None
    content_type: Optional[str] = None
    parser: Optional[str] = None
    text_chars: Optional[int] = None
    text_excerpt: Optional[str] = None
    full_text_path: Optional[str] = None
    raw_source_path: Optional[str] = None
    docx_path: Optional[str] = None
    json_path: Optional[str] = None
    sidecar_path: Optional[str] = None
    source_signature: Optional[str] = None
    json_status: Optional[str] = None
    json_error: Optional[str] = None
    search_jobs: List[str] = field(default_factory=list)
    search_terms: List[str] = field(default_factory=list)
    courts_searched: List[str] = field(default_factory=list)
    # Enriched fields from court_extractor.py (may contain nested structures)
    partes: Optional[Dict[str, Any]] = None
    advogados: Optional[List[Dict[str, str]]] = None
    decisao: Optional[str] = None
    votacao: Optional[str] = None
    legislacao_citada: Optional[List[str]] = None
    jurisprudencia_citada: Optional[List[str]] = None
    assuntos: Optional[List[str]] = None
    court_specific: Optional[Dict[str, Any]] = None
    texto_inteiro: Optional[str] = None
    texto_length: Optional[int] = None
    extractions_source: Optional[str] = None
    indexed_at: str = field(default_factory=_utc_now)

def _extract_outcomes(text: str) -> List[str]:
    if not text:
        return []
    found: List[str] = []
    for label, pat in OUTCOME_PATTERNS:
        if pat.search(text):
            found.append(label)
    return found

def _extract_monetary_values(text: str, limit: int = 8) -> List[str]:
    if not text:
        return []
    seen: List[str] = []
    for match in MONEY_RE.finditer(text):
        val = match.group(0).strip()
        if val not in seen:
            seen.append(val)
            if len(seen) >= limit:
                break
    return seen

def _extract_cited_processes(text: str, limit: int = 12) -> List[str]:
    if not text:
        return []
    seen: List[str] = []
    for match in CNJ_PROC_RE.finditer(text):
        val = match.group(1).strip()
        if val not in seen:
            seen.append(val)
            if len(seen) >= limit:
                break
    return seen

def _extract_ementa(text: str, max_chars: int = 1800) -> Optional[str]:
    if not text:
        return None
    head = text[:8000]
    m = EMENTA_END_RE.search(head)
    snippet = head[: m.start()] if m else head
    snippet = re.sub(r"\s+\n", "\n", snippet).strip()
    if not snippet:
        return None
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars].rsplit(" ", 1)[0] + "…"
    return snippet

def _enrich_from_description(record: DocRecord, description: Optional[str]) -> None:
    if not description:
        return
    if not record.relator:
        m = DESC_RELATOR_RE.search(description)
        if m:
            record.relator = m.group(1).strip()
    if not record.tipo_processo:
        m = DESC_TIPO_RE.search(description)
        if m:
            record.tipo_processo = m.group(1).strip()
    if not record.comarca:
        m = DESC_COMARCA_RE.search(description)
        if m:
            record.comarca = m.group(1).strip()
    if not record.numero_processo:
        m = DESC_PROCESSO_RE.search(description)
        if m:
            record.numero_processo = m.group(1).strip()
    if not record.orgao_julgador:
        m = DESC_ORGAO_RE.search(description)
        if m:
            record.orgao_julgador = m.group(1).strip()
    if not record.data_julgamento:
        m = DESC_DATA_JULG_RE.search(description)
        if m:
            record.data_julgamento = _parse_iso_date(m.group(1)) or m.group(1).strip()
    if not record.data_publicacao:
        m = DESC_DATA_PUB_RE.search(description)
        if m:
            record.data_publicacao = _parse_iso_date(m.group(1)) or m.group(1).strip()

def _build_record_from_json_entry(entry: Dict[str, Any], json_dir: Path, downloads_dir: Path) -> Optional[DocRecord]:
    json_path_str = entry.get("json_path")
    source_path_str = entry.get("source_path")

    name = Path(source_path_str or "").name.lower()
    if name == "search_metadata.json":
        return None

    record = DocRecord(id="pending")
    record.source_signature = entry.get("source_signature")
    record.json_status = entry.get("status")
    record.json_error = entry.get("error")
    record.raw_source_path = source_path_str
    record.json_path = json_path_str
    record.sidecar_path = entry.get("source_sidecar_path")

    if source_path_str:
        m = TJRS_FNAME_RE.search(name)
        if m:
            record.numero_processo = m.group("numero")
            record.ano = m.group("ano")
            record.codigo = m.group("codigo")
        m2 = ESAJ_FNAME_RE.search(name)
        if m2 and not record.cdacordao:
            record.cdacordao = m2.group("cdacordao")

    text_excerpt: Optional[str] = None
    parsed_text: Optional[str] = None
    if entry.get("status") == "ready" and json_path_str:
        per_doc = _read_json(Path(json_path_str), default=None)
        if isinstance(per_doc, dict):
            record.parser = per_doc.get("parser")
            record.content_type = per_doc.get("content_type")
            record.text_chars = per_doc.get("text_chars")
            parsed_text = per_doc.get("text") or ""
            if parsed_text:
                text_excerpt = parsed_text[:600]

            sm = per_doc.get("source_metadata") or {}
            if isinstance(sm, dict):
                record.downloaded_at = sm.get("downloaded_at") or record.downloaded_at
                record.download_url = sm.get("download_url") or record.download_url
                record.source_page_url = sm.get("source_page_url") or record.source_page_url
                record.inteiro_url = sm.get("inteiro_url") or record.inteiro_url
                record.file_size_bytes = sm.get("file_size_bytes") or record.file_size_bytes
                if not record.numero_processo and sm.get("numero_processo"):
                    record.numero_processo = str(sm.get("numero_processo"))
                if not record.ano and sm.get("ano"):
                    record.ano = str(sm.get("ano"))
                if not record.codigo and sm.get("codigo"):
                    record.codigo = str(sm.get("codigo"))
                if not record.cdacordao and sm.get("cdacordao"):
                    record.cdacordao = str(sm.get("cdacordao"))
                _enrich_from_description(record, sm.get("result_description"))
                tribunal_hint = (sm.get("search_params") or {}).get("tribunal")
                if isinstance(tribunal_hint, str) and tribunal_hint not in ("ALL", "", None):
                    record.tribunal = tribunal_hint
            if record.docx_path is None:
                record.docx_path = per_doc.get("docx_fallback")

    if entry.get("status") != "ready" and entry.get("source_sidecar_path"):
        sidecar = _read_json(Path(entry["source_sidecar_path"]), default=None)
        if isinstance(sidecar, dict):
            record.downloaded_at = sidecar.get("downloaded_at") or record.downloaded_at
            record.download_url = sidecar.get("download_url") or record.download_url
            record.source_page_url = sidecar.get("source_page_url") or record.source_page_url
            record.file_size_bytes = sidecar.get("file_size_bytes") or record.file_size_bytes
            if not record.numero_processo and sidecar.get("numero_processo"):
                record.numero_processo = str(sidecar.get("numero_processo"))
            if not record.ano and sidecar.get("ano"):
                record.ano = str(sidecar.get("ano"))
            if not record.codigo and sidecar.get("codigo"):
                record.codigo = str(sidecar.get("codigo"))
            _enrich_from_description(record, sidecar.get("result_description"))

    if not record.tribunal:
        record.tribunal = _detect_tribunal(record.download_url, record.source_page_url, record.inteiro_url)
    if not record.tribunal and record.numero_processo and record.numero_processo.startswith("7"):
        record.tribunal = "TJRS"

    if parsed_text:
        record.ementa = _extract_ementa(parsed_text)
        record.outcome = _extract_outcomes(parsed_text)
        record.monetary_values = _extract_monetary_values(parsed_text)
        cited = _extract_cited_processes(parsed_text)
        if cited and not record.cnj_numero:
            record.cnj_numero = cited[0]
        record.cited_processes = cited
        record.text_excerpt = text_excerpt

    record.id = _canonical_doc_id(record)
    return record

def _canonical_doc_id(record: DocRecord) -> str:
    if record.cdacordao:
        return f"tjsp_{record.cdacordao}"
    if record.numero_processo and record.ano and record.codigo:
        return f"tjrs_{record.numero_processo}_{record.ano}_{record.codigo}"
    if record.cnj_numero:
        return f"cnj_{re.sub(r'[^0-9]', '', record.cnj_numero)}"
    if record.numero_processo:
        prefix = (record.tribunal or "doc").lower()
        return f"{prefix}_{record.numero_processo}"
    return _stable_id(record.raw_source_path or "", record.json_path or "")

def _normalize_process_number(num: Optional[str]) -> Optional[str]:
    """Return digits-only CNJ number for dedup matching."""
    if not num:
        return None
    return re.sub(r"[^0-9]", "", num)

def _record_dedup_keys(rec: DocRecord) -> List[str]:
    """Generate candidate deduplication keys for a record."""
    keys = []
    # e-SAJ id
    if rec.cdacordao:
        keys.append(f"e-saj:{rec.cdacordao}")
    # Full CNJ number (digits only)
    norm_np = _normalize_process_number(rec.numero_processo)
    if norm_np:
        keys.append(f"cnj:{norm_np}")
        if rec.ano:
            keys.append(f"cnj:{norm_np}|ano:{rec.ano}")
    # TJRS composite key
    if rec.numero_processo and rec.ano and rec.codigo:
        keys.append(f"tjrs:{rec.numero_processo}:{rec.ano}:{rec.codigo}")
    # Content signature (for exact file duplicates)
    if rec.source_signature:
        keys.append(f"hash:{rec.source_signature}")
    return keys

# ── Search history ingestion ─────────────────────────────────────────────────

def _scan_search_history(history_dir: Path) -> List[Dict[str, Any]]:
    jobs: List[Dict[str, Any]] = []
    if not history_dir.is_dir():
        return jobs
    for path in sorted(history_dir.glob("search_*.json")):
        data = _read_json(path, default=None)
        if not isinstance(data, dict):
            continue
        jobs.append({
            "job_id": data.get("job_id") or path.stem,
            "saved_at": data.get("saved_at"),
            "fields": data.get("fields") or {},
            "total": data.get("total"),
            "results": data.get("results") or [],
            "history_path": str(path),
        })
    return jobs

def _result_keys(result: Dict[str, Any]) -> List[str]:
    keys: List[str] = []
    cda = result.get("cdacordao")
    if cda:
        keys.append(f"tjsp_{cda}")
    np = result.get("numero_processo") or ""
    digits = re.sub(r"[^0-9]", "", np)
    if digits:
        keys.append(f"cnj_{digits}")
        keys.append(f"tjsp_{digits}")
    if np and "tjrs" in (result.get("tribunal") or "").lower():
        keys.append(f"tjrs_raw_{digits or np}")
    return keys

# ── Output normalizer → optimal JSON schema ──────────────────────────────────

OUTCOME_TO_RESULTADO = {
    "dado_provimento": "PROVIDO",
    "negado_provimento": "NEGADO",
    "provimento_parcial": "PARCIALMENTE_PROVIDO",
    "procedente": "PROCEDENTE",
    "improcedente": "IMPROCEDENTE",
    "reformada": "REFORMADA",
    "mantida": "MANTIDA",
}

def _parse_monetary(values: List[str]) -> List[Dict[str, Any]]:
    """Convert raw 'R$ 10.000,00' strings into structured monetary objects."""
    parsed = []
    for v in values:
        # Remove 'R$' and formatting, then convert to float
        clean = re.sub(r'[R$\s]', '', v).replace('.', '').replace(',', '.')
        try:
            num = float(clean)
        except ValueError:
            num = None
        parsed.append({
            "valor": num,
            "moeda": "BRL",
            "tipo": None,           # could be inferred later via context
            "contexto": v.strip(),
        })
    return parsed

def _build_optimal_document(rec: DocRecord) -> Dict[str, Any]:
    """Transform internal DocRecord into the optimal nested JSON schema."""

    # ── Core identification ──
    doc = {
        "id": rec.id,
        "tribunal": rec.tribunal,
        "tribunal_nome": None,           # optional, can be filled later
        "numero_processo": rec.numero_processo,
        "cnj_numero": rec.cnj_numero,
        "cdacordao": rec.cdacordao,
        "ano": rec.ano,
        "classe": rec.classe,
        "assunto": rec.assuntos or [],
    }

    # ── Dates & Organs ──
    doc["data_julgamento"] = rec.data_julgamento
    doc["data_publicacao"] = rec.data_publicacao
    doc["data_registro"] = rec.data_registro

    # Relator as object
    doc["relator"] = {"nome": rec.relator, "cargo": None} if rec.relator else None

    # Comarca as object
    comarca_obj: Dict[str, Any] = {}
    if rec.comarca:
        comarca_obj["nome"] = rec.comarca
        # Attempt to extract vara/juiz from court_specific or description (future)
        comarca_obj["vara"] = None
        comarca_obj["juiz_origem"] = None
    doc["comarca"] = comarca_obj if comarca_obj else None

    # ── Decision & Outcome ──
    decisao_resumo = rec.decisao or ""
    resultado = "UNKNOWN"
    for tag in rec.outcome:
        if tag in OUTCOME_TO_RESULTADO:
            resultado = OUTCOME_TO_RESULTADO[tag]
            break
    doc["decisao"] = {
        "resumo": decisao_resumo,
        "resultado": resultado,
        "resultado_original": rec.decisao or "",  # keep raw text
        "dispositivo": None,                       # to be extracted later
    }

    # Legacy outcome list (for analytics)
    doc["outcome"] = rec.outcome or []

    # ── Monetary values ──
    doc["monetary_values"] = _parse_monetary(rec.monetary_values)

    # ── Cited processes ──
    doc["cited_processes"] = rec.cited_processes or []

    # ── Legislation / Jurisprudence (may be strings or objects) ──
    doc["legislacao_citada"] = rec.legislacao_citada or []
    doc["jurisprudencia_citada"] = rec.jurisprudencia_citada or []

    # ── Orgão julgador ──
    orgao_obj: Dict[str, Any] = {
        "nome": rec.orgao_julgador,
        "presidente": None,
        "membros": [],
        "votacao": "UNANIME" if "unanime" in rec.outcome else ("MAIORIA" if rec.outcome else None),
    }
    # If court_specific contains structured orgao info, merge it
    if rec.court_specific and isinstance(rec.court_specific, dict):
        cs = rec.court_specific
        orgao_obj["nome"] = cs.get("camara") or cs.get("orgao_julgador") or orgao_obj["nome"]
        if cs.get("presidente"):
            orgao_obj["presidente"] = {"nome": cs["presidente"], "com_voto": cs.get("presidente_com_voto", False)}
        if isinstance(cs.get("membros"), list):
            orgao_obj["membros"] = [{"nome": m, "com_voto": True} for m in cs["membros"]]
    doc["orgao_julgador"] = orgao_obj

    # ── Parties and Representatives ──
    doc["partes"] = rec.partes or {}
    doc["advogados"] = rec.advogados or []

    # ── Full texts / sources ──
    doc["ementa"] = rec.ementa
    doc["texto_inteiro"] = rec.texto_inteiro
    doc["texto_length"] = rec.texto_length
    doc["inteiro_url"] = rec.inteiro_url
    doc["download_url"] = rec.download_url
    doc["file_size_bytes"] = rec.file_size_bytes
    doc["content_type"] = rec.content_type
    doc["parser"] = rec.parser
    doc["json_status"] = rec.json_status
    doc["source_signature"] = rec.source_signature

    # ── Court-specific metadata (flexible catch-all) ──
    doc["court_specific"] = rec.court_specific or {}

    # ── Search & indexing metadata ──
    doc["search_jobs"] = rec.search_jobs
    doc["search_terms"] = rec.search_terms
    doc["courts_searched"] = rec.courts_searched
    doc["downloaded_at"] = rec.downloaded_at
    doc["indexed_at"] = rec.indexed_at
    doc["extractions_source"] = rec.extractions_source

    # ── Paths (for internal use) ──
    doc["json_path"] = rec.json_path
    doc["raw_source_path"] = rec.raw_source_path
    doc["docx_path"] = rec.docx_path
    doc["sidecar_path"] = rec.sidecar_path

    return doc

# ── Helper to safely extract relator name from document dict (for queries) ──
def _relator_name(doc: Dict[str, Any]) -> str:
    r = doc.get("relator")
    if isinstance(r, dict):
        return r.get("nome", "")
    return str(r or "")

def _comarca_name(doc: Dict[str, Any]) -> str:
    c = doc.get("comarca")
    if isinstance(c, dict):
        return c.get("nome", "")
    return str(c or "")

def _orgao_name(doc: Dict[str, Any]) -> str:
    o = doc.get("orgao_julgador")
    if isinstance(o, dict):
        return o.get("nome", "")
    return str(o or "")

# ── Master indexer ───────────────────────────────────────────────────────────

class JurisMasterIndexer:
    """Builds and maintains the unified jurisprudence index."""

    def __init__(self, config: IndexerConfig) -> None:
        self.config = config
        self.config.master_dir.mkdir(parents=True, exist_ok=True)
        self.master_index_path = config.master_dir / "master_index.json"
        self.state_path = config.master_dir / ".watch_state.json"
        self.qdrant_state_path = config.master_dir / ".qdrant_state.json"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._paused_collections: set = set()
        self._thread: Optional[threading.Thread] = None
        self._last_scan_summary: Dict[str, Any] = {}

    # -- Public API -----------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="juris-master-indexer", daemon=True)
        self._thread.start()
        logger.info(
            "Juris master indexer started (interval=%ss, qdrant=%s, awareness=%s)",
            self.config.interval_seconds,
            self.config.qdrant_enabled,
            self.config.awareness_enabled,
        )

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._pause.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    def pause(self, collection: Optional[str] = None) -> Dict[str, Any]:
        if collection:
            self._paused_collections.add(collection)
        else:
            self._paused_collections.add("all")
        self._pause.set()
        return self.paused_state()

    def resume(self, collection: Optional[str] = None) -> Dict[str, Any]:
        if collection:
            self._paused_collections.discard(collection)
        else:
            self._paused_collections.clear()
        if not self._paused_collections:
            self._pause.clear()
        return self.paused_state()

    def paused_state(self) -> Dict[str, Any]:
        return {
            "paused": self._pause.is_set(),
            "paused_collections": sorted(self._paused_collections),
        }

    def rebuild(self, force_ingest: bool = False) -> Dict[str, Any]:
        with self._lock:
            return self._scan(force_ingest=force_ingest)

    def stats(self) -> Dict[str, Any]:
        idx = _read_json(self.master_index_path, default=None)
        if not isinstance(idx, dict):
            return {"available": False, "last_scan": self._last_scan_summary}
        out = {
            "available": True,
            "generated_at": idx.get("generated_at"),
            "total_documents": idx.get("total_documents"),
            "by_tribunal": idx.get("by_tribunal"),
            "by_year": idx.get("by_year"),
            "by_outcome": idx.get("by_outcome"),
            "by_classe": idx.get("by_classe"),
            "top_relators": idx.get("top_relators"),
            "top_comarcas": idx.get("top_comarcas"),
            "top_assuntos": idx.get("top_assuntos"),
            "search_jobs": idx.get("search_jobs_count"),
            "qdrant": idx.get("qdrant"),
            "awareness": idx.get("awareness"),
            "last_scan": self._last_scan_summary,
            "pause": self.paused_state(),
        }
        return out

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        idx = _read_json(self.master_index_path, default=None) or {}
        for doc in idx.get("documents", []) or []:
            if doc.get("numero_processo") == doc_id:
                return doc
        for doc in idx.get("documents", []) or []:
            if (doc.get("source_file") or "") == doc_id:
                return doc
        return None

    def list_documents(
        self,
        *,
        tribunal: Optional[str] = None,
        year: Optional[str] = None,
        relator: Optional[str] = None,
        outcome: Optional[str] = None,
        assunto: Optional[str] = None,
        comarca: Optional[str] = None,
        text: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        idx = _read_json(self.master_index_path, default=None) or {}
        docs = idx.get("documents", []) or []
        text_lc = (text or "").strip().lower()
        relator_lc = (relator or "").strip().lower()
        assunto_lc = (assunto or "").strip().lower()
        comarca_lc = (comarca or "").strip().lower()
        outcome_lc = (outcome or "").strip().lower()
        filtered: List[Dict[str, Any]] = []
        for doc in docs:
            if tribunal and (doc.get("tribunal") or "").upper() != tribunal.upper():
                continue
            if year:
                dj = str(doc.get("data_julgamento") or "")
                doc_year = dj[:4]
                if not doc_year or doc_year != str(year):
                    continue
            if relator_lc and relator_lc not in _relator_name(doc).lower():
                continue
            if outcome_lc:
                # check both legacy outcome list and structured decisao.resultado
                doc_outcomes = [o.lower() for o in (doc.get("outcome") or [])]
                decisao_resultado = (doc.get("decisao") or {}).get("resultado", "").lower()
                if outcome_lc not in doc_outcomes and outcome_lc != decisao_resultado:
                    continue
            if assunto_lc:
                doc_assuntos = [a.lower() for a in (doc.get("assunto") or [])]
                if not any(assunto_lc in a for a in doc_assuntos):
                    continue
            if comarca_lc and comarca_lc not in _comarca_name(doc).lower():
                continue
            if text_lc:
                blob = " ".join([
                    str(doc.get("ementa") or ""),
                    _relator_name(doc),
                    _comarca_name(doc),
                    str(doc.get("numero_processo") or ""),
                    " ".join(doc.get("assunto") or []),
                    " ".join(str(x) for x in doc.get("legislacao_citada") or []),
                ]).lower()
                if text_lc not in blob:
                    continue
            filtered.append(doc)
        total = len(filtered)
        page = filtered[offset : offset + limit]
        return {"total": total, "limit": limit, "offset": offset, "items": page}

    def correlate_document(self, doc_id: str) -> Dict[str, Any]:
        doc = self.get_document(doc_id)
        if not doc:
            return {"error": "not found"}
        idx = _read_json(self.master_index_path, default=None) or {}
        all_docs = idx.get("documents", []) or []
        relator_lc = _relator_name(doc).lower()
        assuntos = set(a.lower() for a in (doc.get("assunto") or []))
        legislacao = set(str(l).lower() for l in (doc.get("legislacao_citada") or []))

        same_relator = []
        same_assuntos = []
        same_legislacao = []
        for d in all_docs:
            proc = d.get("numero_processo")
            if proc == doc_id:
                continue
            if relator_lc and relator_lc in _relator_name(d).lower():
                same_relator.append(proc)
            d_assuntos = set(a.lower() for a in (d.get("assunto") or []))
            if assuntos & d_assuntos:
                same_assuntos.append(proc)
            d_leg = set(str(l).lower() for l in (d.get("legislacao_citada") or []))
            if legislacao & d_leg:
                same_legislacao.append(proc)

        return {
            "document": doc_id,
            "same_relator": list(set(same_relator))[:20],
            "same_assuntos": list(set(same_assuntos))[:20],
            "same_legislacao": list(set(same_legislacao))[:20],
            "total_same_relator": len(set(same_relator)),
            "total_same_assuntos": len(set(same_assuntos)),
            "total_same_legislacao": len(set(same_legislacao)),
        }

    # -- Internal -------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._pause.is_set():
                self._stop.wait(2.0)
                continue
            try:
                with self._lock:
                    self._scan(force_ingest=False)
            except Exception as exc:
                logger.warning("Master indexer cycle failed: %s", exc)
            self._stop.wait(self.config.interval_seconds)

    def _scan(self, force_ingest: bool) -> Dict[str, Any]:
        cfg = self.config
        json_index_path = cfg.json_dir / "index.json"
        json_index = _read_json(json_index_path, default={"entries": []})
        entries = json_index.get("entries") or []

        records: Dict[str, DocRecord] = {}
        for entry in entries:
            try:
                rec = _build_record_from_json_entry(entry, cfg.json_dir, cfg.downloads_dir)
            except Exception as exc:
                logger.debug("entry build failed: %s (%s)", exc, entry.get("source_path"))
                continue
            if not rec:
                continue
            existing = records.get(rec.id)
            if existing:
                if existing.json_status != "ready" and rec.json_status == "ready":
                    records[rec.id] = rec
                continue
            records[rec.id] = rec

        # Cross-reference with search history
        history_jobs = _scan_search_history(cfg.history_dir)
        by_keys: Dict[str, str] = {}
        for rid, rec in records.items():
            for k in self._record_keys(rec):
                by_keys.setdefault(k, rid)

        for job in history_jobs:
            job_id = job.get("job_id")
            terms = (job.get("fields") or {}).get("search_text") or ""
            courts = (job.get("fields") or {}).get("courts") or []
            for result in job.get("results") or []:
                target_id = None
                for cand in _result_keys(result):
                    if cand in by_keys:
                        target_id = by_keys[cand]
                        break
                if not target_id:
                    synthetic = DocRecord(id="pending")
                    synthetic.cdacordao = result.get("cdacordao") or None
                    synthetic.numero_processo = result.get("numero_processo") or None
                    synthetic.cnj_numero = result.get("numero_processo") or None
                    synthetic.tribunal = result.get("tribunal") or None
                    synthetic.comarca = result.get("comarca_origem") or None
                    synthetic.relator = result.get("relator") or None
                    synthetic.orgao_julgador = result.get("orgao_julgador") or None
                    synthetic.data_julgamento = _parse_iso_date(result.get("data_julgamento")) or result.get("data_julgamento") or None
                    synthetic.data_publicacao = _parse_iso_date(result.get("data_publicacao")) or result.get("data_publicacao") or None
                    synthetic.data_registro = _parse_iso_date(result.get("data_registro")) or result.get("data_registro") or None
                    synthetic.inteiro_url = result.get("inteiro_url") or None
                    synthetic.ementa = result.get("ementa_trecho") or None
                    synthetic.json_status = "search_only"
                    synthetic.id = _canonical_doc_id(synthetic)
                    if synthetic.id not in records:
                        records[synthetic.id] = synthetic
                        for k in self._record_keys(synthetic):
                            by_keys.setdefault(k, synthetic.id)
                    target_id = synthetic.id

                rec = records[target_id]
                if job_id and job_id not in rec.search_jobs:
                    rec.search_jobs.append(job_id)
                if terms and terms not in rec.search_terms:
                    rec.search_terms.append(terms)
                for c in courts:
                    if c and c not in rec.courts_searched:
                        rec.courts_searched.append(c)

        # Enrich from court_extractor.py structured extractions
        extractions = _scan_extractions(cfg.extractions_dir)
        for ext in extractions:
            proc = ext.get("numero_processo")
            trib = ext.get("tribunal")
            if not proc:
                continue
            for rec in records.values():
                if rec.numero_processo and proc in rec.numero_processo and (not trib or trib == rec.tribunal):
                    _enrich_from_extraction(rec, ext)
                    break

        # Deduplicate records (merge duplicates by process number/cdacordao/hash)
        records = self._deduplicate_records(records)

        # Transform every record to the optimal JSON schema
        documents = [_build_optimal_document(r) for r in records.values()]
        documents.sort(key=lambda d: (
            d.get("data_julgamento") or "",
            d.get("downloaded_at") or "",
            d.get("id") or "",
        ), reverse=True)

        by_tribunal: Dict[str, int] = {}
        by_year: Dict[str, int] = {}
        by_outcome: Dict[str, int] = {}
        by_relator: Dict[str, int] = {}
        by_comarca: Dict[str, int] = {}
        by_classe: Dict[str, int] = {}
        by_assuntos: Dict[str, int] = {}
        for d in documents:
            t = d.get("tribunal") or "UNKNOWN"
            by_tribunal[t] = by_tribunal.get(t, 0) + 1
            y = d.get("ano") or (d.get("data_julgamento") or "")[:4] or ""
            if y:
                by_year[y] = by_year.get(y, 0) + 1
            for o in (d.get("outcome") or []):
                by_outcome[o] = by_outcome.get(o, 0) + 1
            r = _relator_name(d)
            if r:
                by_relator[r] = by_relator.get(r, 0) + 1
            c = _comarca_name(d)
            if c:
                by_comarca[c] = by_comarca.get(c, 0) + 1
            classe = d.get("classe")
            if classe:
                by_classe[classe] = by_classe.get(classe, 0) + 1
            for a in (d.get("assunto") or []):
                by_assuntos[a] = by_assuntos.get(a, 0) + 1

        paused = self._paused_collections
        qdrant_paused = "all" in paused or cfg.qdrant_collection in paused
        awareness_paused = "all" in paused or cfg.awareness_collection in paused

        qdrant_report = (
            {"enabled": cfg.qdrant_enabled, "ok": True, "paused": True, "collection": cfg.qdrant_collection}
            if qdrant_paused
            else self._maybe_ingest_qdrant(documents, force_ingest=force_ingest)
        )
        awareness_report = (
            {"enabled": cfg.awareness_enabled, "ok": True, "paused": True, "collection": cfg.awareness_collection}
            if awareness_paused
            else self._maybe_ingest_awareness(documents, force_ingest=force_ingest)
        )

        payload = {
            "schema_version": 2,   # bumped for the new optimal structure
            "generated_at": _utc_now(),
            "base_dir": str(cfg.base_dir),
            "downloads_dir": str(cfg.downloads_dir),
            "json_dir": str(cfg.json_dir),
            "docx_dir": str(cfg.docx_dir),
            "history_dir": str(cfg.history_dir),
            "total_documents": len(documents),
            "search_jobs_count": len(history_jobs),
            "by_tribunal": by_tribunal,
            "by_year": dict(sorted(by_year.items())),
            "by_outcome": by_outcome,
            "by_classe": by_classe,
            "top_relators": dict(sorted(by_relator.items(), key=lambda kv: kv[1], reverse=True)[:25]),
            "top_comarcas": dict(sorted(by_comarca.items(), key=lambda kv: kv[1], reverse=True)[:25]),
            "top_assuntos": dict(sorted(by_assuntos.items(), key=lambda kv: kv[1], reverse=True)[:25]),
            "qdrant": qdrant_report,
            "awareness": awareness_report,
            "documents": documents,
        }
        _write_json(self.master_index_path, payload)

        try:
            from render_master_markdown import render_master_markdown
            md_path = self.config.master_dir / "master_index.md"
            render_master_markdown(self.master_index_path, md_path)
        except Exception as exc:
            logger.debug("markdown render skipped: %s", exc)

        try:
            from render_masterjurisprudence import render as render_juris
            render_juris(
                self.master_index_path,
                jx_path=self.config.master_dir / "masterjurisprudence.jsx",
                md_path=self.config.master_dir / "masterjurisprudence.md",
            )
        except Exception as exc:
            logger.debug("master jurisprudence render skipped: %s", exc)

        summary = {
            "ran_at": _utc_now(),
            "documents": len(documents),
            "search_jobs": len(history_jobs),
            "qdrant": qdrant_report,
            "awareness": awareness_report,
        }
        self._last_scan_summary = summary
        logger.info(
            "Master index rebuilt: docs=%d jobs=%d tribunals=%s",
            len(documents),
            len(history_jobs),
            by_tribunal,
        )
        return summary

    @staticmethod
    def _record_keys(rec: DocRecord) -> List[str]:
        keys = [rec.id]
        if rec.cdacordao:
            keys.append(f"tjsp_{rec.cdacordao}")
        if rec.numero_processo:
            keys.append(f"tjsp_{rec.numero_processo}")
            digits = re.sub(r"[^0-9]", "", rec.numero_processo)
            if digits:
                keys.append(f"cnj_{digits}")
            keys.append(f"tjrs_raw_{rec.numero_processo}")
        if rec.cnj_numero:
            keys.append(f"cnj_{re.sub(r'[^0-9]', '', rec.cnj_numero)}")
        return keys

    def _deduplicate_records(self, records: Dict[str, DocRecord]) -> Dict[str, DocRecord]:
        """Merge records that represent the same document, keeping the richest one."""
        # index by dedup keys -> list of record ids
        idx: Dict[str, List[str]] = {}
        for rec_id, rec in records.items():
            for key in _record_dedup_keys(rec):
                idx.setdefault(key, []).append(rec_id)

        # process each group of duplicate keys
        merged_ids = set()
        final_map: Dict[str, DocRecord] = {}
        handled_ids = set()

        for dup_key, rec_ids in idx.items():
            if len(rec_ids) < 2:
                continue
            # choose the best primary record
            group = [records[rid] for rid in rec_ids]
            # prefer 'ready' > anything else; then prefer the one with more fields populated
            primary = max(group, key=lambda r: (
                0 if r.json_status == "ready" else 1,
                bool(r.relator),
                bool(r.ementa),
                bool(r.orgao_julgador),
                bool(r.data_julgamento),
                len(r.outcome),
            ))
            for other in group:
                if other is primary:
                    continue
                # merge search metadata
                for job_id in other.search_jobs:
                    if job_id not in primary.search_jobs:
                        primary.search_jobs.append(job_id)
                for term in other.search_terms:
                    if term not in primary.search_terms:
                        primary.search_terms.append(term)
                for court in other.courts_searched:
                    if court not in primary.courts_searched:
                        primary.courts_searched.append(court)
                # fill missing core fields if primary lacks them
                for field in [
                    "tribunal", "numero_processo", "cnj_numero", "ano", "codigo",
                    "classe", "tipo_processo", "relator", "orgao_julgador", "comarca",
                    "data_julgamento", "data_publicacao", "data_registro",
                    "ementa", "text_excerpt", "inteiro_url", "download_url",
                    "file_size_bytes", "content_type", "parser", "json_status",
                    "source_signature",
                ]:
                    if not getattr(primary, field) and getattr(other, field):
                        setattr(primary, field, getattr(other, field))
                # merge lists (outcome, monetary_values, cited_processes, etc.)
                for src in other.outcome:
                    if src not in primary.outcome:
                        primary.outcome.append(src)
                for val in other.monetary_values:
                    if val not in primary.monetary_values:
                        primary.monetary_values.append(val)
                for proc in other.cited_processes:
                    if proc not in primary.cited_processes:
                        primary.cited_processes.append(proc)
                # partes, advogados: keep the one that is non-empty
                if not primary.partes and other.partes:
                    primary.partes = other.partes
                if not primary.advogados and other.advogados:
                    primary.advogados = other.advogados
                if not primary.decisao and other.decisao:
                    primary.decisao = other.decisao
                if not primary.legislacao_citada and other.legislacao_citada:
                    primary.legislacao_citada = other.legislacao_citada
                if not primary.jurisprudencia_citada and other.jurisprudencia_citada:
                    primary.jurisprudencia_citada = other.jurisprudencia_citada
                if not primary.assuntos and other.assuntos:
                    primary.assuntos = other.assuntos
                if not primary.court_specific and other.court_specific:
                    primary.court_specific = other.court_specific
                if not primary.texto_inteiro and other.texto_inteiro:
                    primary.texto_inteiro = other.texto_inteiro
                if not primary.texto_length and other.texto_length:
                    primary.texto_length = other.texto_length

            # primary will be kept; mark others as merged
            for rec_id in rec_ids:
                handled_ids.add(rec_id)
            final_map[primary.id] = primary

        # add any records not involved in any duplicate group
        for rec_id, rec in records.items():
            if rec_id not in handled_ids:
                final_map[rec_id] = rec

        return final_map

    @staticmethod
    def _ingest_signature(doc: Dict[str, Any]) -> str:
        explicit = str(doc.get("source_signature") or "").strip()
        if explicit:
            return explicit
        material = {
            "id": doc.get("id"),
            "json_path": doc.get("json_path"),
            "raw_source_path": doc.get("raw_source_path"),
            "file_size_bytes": doc.get("file_size_bytes"),
            "text_chars": doc.get("text_chars"),
            "ementa": doc.get("ementa") or doc.get("text_excerpt") or "",
        }
        raw = json.dumps(material, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    # -- Qdrant ingestion -----------------------------------------------------

    def _maybe_ingest_qdrant(self, documents: List[Dict[str, Any]], *, force_ingest: bool) -> Dict[str, Any]:
        cfg = self.config
        if not cfg.qdrant_enabled:
            return {"enabled": False}
        try:
            self._ensure_qdrant_collection()
        except Exception as exc:
            return {"enabled": True, "ok": False, "error": f"collection_init_failed: {exc}"}

        state = _read_json(self.qdrant_state_path, default={"ingested": {}}) or {"ingested": {}}
        ingested: Dict[str, str] = state.get("ingested", {}) or {}

        items: List[Dict[str, Any]] = []
        targets: List[Tuple[str, str]] = []
        for doc in documents:
            if not doc.get("ementa") and not doc.get("text_excerpt"):
                continue
            sig = self._ingest_signature(doc)
            prev = ingested.get(doc["id"])
            if not force_ingest and prev == sig:
                continue
            items.append(self._build_qdrant_item(doc))
            targets.append((doc["id"], sig))

        if not items:
            return {
                "enabled": True,
                "ok": True,
                "ingested_now": 0,
                "total_tracked": len(ingested),
                "collection": cfg.qdrant_collection,
            }

        qdrant_batch_size = int(os.environ.get("JURIS_SEARCH_QDRANT_BATCH_SIZE", "20"))
        url = f"{cfg.qdrant_base_url}/v1/qdrant/collections/structured_ingest"
        total_ok = 0
        last_err = None
        for i in range(0, len(items), qdrant_batch_size):
            chunk = items[i : i + qdrant_batch_size]
            chunk_targets = targets[i : i + qdrant_batch_size]
            chunk_payload = {
                "collection_name": cfg.qdrant_collection,
                "data_type": "law",
                "items": chunk,
            }
            chunk_status, chunk_body = _http_post_json(url, chunk_payload, timeout=cfg.request_timeout)
            if 200 <= chunk_status < 300:
                now = _utc_now()
                for doc_id, sig in chunk_targets:
                    ingested[doc_id] = sig
                state["ingested"] = ingested
                state["last_ok_at"] = now
                _write_json(self.qdrant_state_path, state)
                total_ok += len(chunk)
            elif isinstance(chunk_body, dict):
                last_err = (
                    chunk_body.get("detail")
                    or (chunk_body.get("error") or {}).get("message")
                    or json.dumps(chunk_body)[:500]
                )

        ok = total_ok > 0
        items_len = len(items)
        if ok and last_err is not None:
            items_len = total_ok
        return {
            "enabled": True,
            "ok": ok,
            "status": 200 if ok else 0,
            "ingested_now": total_ok,
            "total_tracked": len(ingested),
            "collection": cfg.qdrant_collection,
            "error": last_err,
        }

    def _build_qdrant_item(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        # Use the helper to get flat relator/comarca strings
        relator = _relator_name(doc)
        comarca = _comarca_name(doc)
        orgao = _orgao_name(doc)

        parts = [
            f"Tribunal: {doc.get('tribunal') or 'N/D'}",
            f"Processo: {doc.get('numero_processo') or doc.get('cnj_numero') or doc.get('cdacordao') or 'N/D'}",
        ]
        if relator:
            parts.append(f"Relator: {relator}")
        if orgao:
            parts.append(f"Órgão julgador: {orgao}")
        if comarca:
            parts.append(f"Comarca: {comarca}")
        if doc.get("data_julgamento"):
            parts.append(f"Julgado em: {doc['data_julgamento']}")
        if doc.get("classe"):
            parts.append(f"Tipo: {doc['classe']}")
        outcome = doc.get("outcome") or []
        if outcome:
            parts.append(f"Resultado: {', '.join(outcome)}")
        header = " | ".join(parts)
        ementa = doc.get("ementa") or doc.get("text_excerpt") or ""
        text = f"{header}\n\nEMENTA / TRECHO:\n{ementa}"

        payload = {
            "doc_id": doc.get("id"),
            "tribunal": doc.get("tribunal"),
            "numero_processo": doc.get("numero_processo"),
            "cnj_numero": doc.get("cnj_numero"),
            "cdacordao": doc.get("cdacordao"),
            "ano": doc.get("ano"),
            "codigo": doc.get("codigo"),
            "relator": relator,
            "orgao_julgador": orgao,
            "comarca": comarca,
            "classe": doc.get("classe"),
            "data_julgamento": doc.get("data_julgamento"),
            "data_publicacao": doc.get("data_publicacao"),
            "outcome": outcome,
            "monetary_values": doc.get("monetary_values") or [],
            "search_terms": doc.get("search_terms") or [],
            "search_jobs": doc.get("search_jobs") or [],
            "inteiro_url": doc.get("inteiro_url"),
            "json_path": doc.get("json_path"),
            "docx_path": doc.get("docx_path"),
            "raw_source_path": doc.get("raw_source_path"),
            "source": "juris-search",
        }
        return {
            "id": _doc_uuid(doc.get("id") or ""),
            "doc_id": doc.get("id"),
            "text": text,
            "content": text,
            "metadata": payload,
            **payload,
        }

    def _ensure_qdrant_collection(self, collection_name: Optional[str] = None) -> None:
        cfg = self.config
        coll = collection_name or cfg.qdrant_collection
        connect_url = f"{cfg.qdrant_base_url}/v1/qdrant/connect"
        for conn_attempt in range(3):
            cstatus, _ = _http_post_json(connect_url, {}, timeout=cfg.request_timeout)
            if 200 <= cstatus < 300:
                break
            if conn_attempt < 2:
                logger.debug("qdrant connect attempt %d failed (%s), retrying...", conn_attempt + 1, cstatus)
                time.sleep(3)
            else:
                raise RuntimeError(f"qdrant_connect_failed: {cstatus}")

        info_url = f"{cfg.qdrant_base_url}/v1/qdrant/collections/{coll}/summary"
        for attempt in range(3):
            status, _ = _http_get_json(info_url, timeout=cfg.request_timeout)
            if 200 <= status < 300:
                return
            if status == 0:
                logger.debug("qdrant collection info attempt %d timed out, retrying...", attempt + 1)
                time.sleep(5)
            else:
                break
        create_url = f"{cfg.qdrant_base_url}/v1/qdrant/collections"
        payload = {
            "name": coll,
            "vector_size": cfg.qdrant_vector_size,
            "distance_metric": "cosine",
        }
        cstatus, cbody = _http_post_json(create_url, payload, timeout=cfg.request_timeout)
        if not (200 <= cstatus < 300) and cstatus != 409:
            raise RuntimeError(f"create_collection {cstatus}: {cbody}")

    # -- Awareness memory ingestion ------------------------------------------

    def _maybe_ingest_awareness(self, documents: List[Dict[str, Any]], *, force_ingest: bool) -> Dict[str, Any]:
        cfg = self.config
        if not cfg.awareness_enabled:
            return {"enabled": False}

        try:
            self._ensure_qdrant_collection(collection_name=cfg.awareness_collection)
        except Exception as exc:
            return {"enabled": True, "ok": False, "error": f"collection_init_failed: {exc}"}

        items: List[Dict[str, Any]] = []
        for doc in documents:
            if not doc.get("ementa") and not doc.get("text_excerpt"):
                continue
            items.append(self._build_awareness_item(doc))

        if not items:
            return {
                "enabled": True,
                "ok": True,
                "ingested_now": 0,
                "collection": cfg.awareness_collection,
            }

        batch_size = int(os.environ.get("JURIS_SEARCH_AWARENESS_BATCH_SIZE", "20"))
        url = f"{cfg.awareness_base_url}/v1/qdrant/collections/structured_ingest"
        total_ok = 0
        last_err = None
        for i in range(0, len(items), batch_size):
            chunk = items[i : i + batch_size]
            payload = {
                "collection_name": cfg.awareness_collection,
                "data_type": "law",
                "items": chunk,
            }
            status, body = _http_post_json(url, payload, timeout=cfg.request_timeout)
            if 200 <= status < 300:
                total_ok += len(chunk)
            elif isinstance(body, dict):
                last_err = (
                    body.get("detail")
                    or (body.get("error") or {}).get("message")
                    or json.dumps(body)[:500]
                )

        ok = total_ok > 0
        items_len = len(items)
        if ok and last_err is not None:
            items_len = total_ok
        return {
            "enabled": True,
            "ok": ok,
            "status": 200 if ok else 0,
            "ingested_now": total_ok,
            "collection": cfg.awareness_collection,
            "error": last_err,
        }

    @staticmethod
    def _build_awareness_item(doc: Dict[str, Any]) -> Dict[str, Any]:
        relator = _relator_name(doc)
        comarca = _comarca_name(doc)

        text = "\n".join(
            line
            for line in [
                f"[{doc.get('tribunal') or 'N/D'}] {doc.get('numero_processo') or doc.get('cdacordao') or doc.get('id')}",
                f"Relator: {relator}" if relator else "",
                f"Comarca: {comarca}" if comarca else "",
                f"Julgado em: {doc.get('data_julgamento')}" if doc.get("data_julgamento") else "",
                f"Resultado: {', '.join(doc.get('outcome') or [])}" if doc.get("outcome") else "",
                "",
                doc.get("ementa") or doc.get("text_excerpt") or "",
            ]
            if line is not None and line != ""
        )
        return {
            "id": _doc_uuid(doc.get("id") or ""),
            "doc_id": doc.get("id"),
            "text": text,
            "content": text,
            "metadata": {
                "doc_id": doc.get("id"),
                "tribunal": doc.get("tribunal"),
                "relator": relator,
                "comarca": comarca,
                "outcome": doc.get("outcome") or [],
                "search_terms": doc.get("search_terms") or [],
                "source": "juris-search-awareness",
            },
            "tribunal": doc.get("tribunal"),
            "relator": relator,
            "comarca": comarca,
            "source": "juris-search-awareness",
        }

# ── Extraction enrichment ────────────────────────────────────────────────────

def _scan_extractions(extractions_dir: Path) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    if not extractions_dir or not extractions_dir.exists():
        return results
    for f in sorted(extractions_dir.glob("*.json")):
        try:
            data = _read_json(f)
            if data and isinstance(data, dict) and "tribunal" in data:
                results.append(data)
        except Exception:
            pass
    return results

def _enrich_from_extraction(rec: DocRecord, ext: Dict[str, Any]) -> None:
    """Merge structured extraction fields into a DocRecord."""
    for key, field in [
        ("ementa", "ementa"),
        ("decisao", "decisao"),
        ("votacao", "votacao"),
        ("classe", "classe"),
        ("relator", "relator"),
        ("orgao_julgador", "orgao_julgador"),
        ("comarca", "comarca"),
        ("data_julgamento", "data_julgamento"),
    ]:
        val = ext.get(key)
        if val and not getattr(rec, field, None):
            setattr(rec, field, val)

    if ext.get("partes") and not rec.partes:
        rec.partes = ext["partes"]
    if ext.get("advogados") and not rec.advogados:
        rec.advogados = ext["advogados"]
    if ext.get("legislacao_citada") and not rec.legislacao_citada:
        rec.legislacao_citada = ext["legislacao_citada"]
    if ext.get("jurisprudencia_citada") and not rec.jurisprudencia_citada:
        rec.jurisprudencia_citada = ext["jurisprudencia_citada"]
    if ext.get("assuntos") and not rec.assuntos:
        rec.assuntos = ext["assuntos"]
    if ext.get("court_specific") and not rec.court_specific:
        rec.court_specific = ext["court_specific"]
    if ext.get("texto_inteiro") and not rec.texto_inteiro:
        rec.texto_inteiro = ext["texto_inteiro"]
    if ext.get("texto_length") and not rec.texto_length:
        rec.texto_length = ext["texto_length"]
    rec.extractions_source = os.path.basename(ext.get("source_file", ""))

# ── Module-level singleton ──────────────────────────────────────────────────

_indexer_instance: Optional[JurisMasterIndexer] = None
_instance_lock = threading.Lock()

def get_indexer(config: Optional[IndexerConfig] = None) -> JurisMasterIndexer:
    global _indexer_instance
    with _instance_lock:
        if _indexer_instance is None:
            if config is None:
                raise RuntimeError("Indexer not initialised yet; pass config on first call")
            _indexer_instance = JurisMasterIndexer(config)
        return _indexer_instance