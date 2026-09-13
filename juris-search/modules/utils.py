"""Pure utility functions used across the juris-search API."""

import os
import re
import json
import hashlib
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from modules.config import DOWNLOADS_BASE_DIR


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _pick_first_value(*values: Any) -> str:
    for value in values:
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return ""


def _normalize_label_key(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", _clean_text(value))
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_only.lower()).strip("_")


_CLASSE_ASSUNTO_SEPARATORS = sorted(
    [" / ", " - ", " | ", ";", "/", "-"],
    key=lambda s: len(s),
    reverse=True,
)


def _split_classe_assunto(value: Any) -> Tuple[str, str]:
    raw = _clean_text(value)
    if not raw:
        return "", ""

    for separator in _CLASSE_ASSUNTO_SEPARATORS:
        if separator in raw:
            left, right = raw.split(separator, 1)
            return left.strip(), right.strip()
    return raw, ""


def _normalize_result_item(item: Dict[str, Any], court_key: str) -> Dict[str, Any]:
    from modules.courts import _resolve_court

    normalized = dict(item)
    metadata = normalized.get("metadata") if isinstance(normalized.get("metadata"), dict) else {}
    metadata_norm = {_normalize_label_key(k): _clean_text(v) for k, v in metadata.items()}

    classe_guess, assunto_guess = _split_classe_assunto(normalized.get("classe_assunto"))

    normalized["tribunal"] = _resolve_court(
        _pick_first_value(normalized.get("court"), normalized.get("tribunal"), court_key)
    )
    normalized["numero_processo"] = _pick_first_value(
        normalized.get("numero_processo"),
        normalized.get("num_processo"),
        normalized.get("processo"),
        normalized.get("cdacordao"),
    )
    normalized["tipo_processo"] = _pick_first_value(
        normalized.get("tipo_processo"),
        metadata_norm.get("tipo_processo"),
        metadata_norm.get("tipo_de_processo"),
        normalized.get("classe_cnj"),
        classe_guess,
    )
    normalized["classe_cnj"] = _pick_first_value(
        normalized.get("classe_cnj"),
        metadata_norm.get("classe_cnj"),
        metadata_norm.get("classe"),
        classe_guess,
    )
    normalized["assunto_cnj"] = _pick_first_value(
        normalized.get("assunto_cnj"),
        metadata_norm.get("assunto_cnj"),
        metadata_norm.get("assunto"),
        assunto_guess,
    )
    normalized["relator"] = _pick_first_value(
        normalized.get("relator"),
        normalized.get("relatora"),
        normalized.get("relator_a"),
        metadata_norm.get("relator"),
        metadata_norm.get("relatora"),
        metadata_norm.get("relator_a"),
    )
    normalized["comarca_origem"] = _pick_first_value(
        normalized.get("comarca_origem"),
        normalized.get("comarca"),
        metadata_norm.get("comarca_origem"),
        metadata_norm.get("comarca"),
    )
    normalized["orgao_julgador"] = _pick_first_value(
        normalized.get("orgao_julgador"),
        metadata_norm.get("orgao_julgador"),
        metadata_norm.get("orgao_judicante"),
        metadata_norm.get("orgao"),
    )
    normalized["data_julgamento"] = _pick_first_value(
        normalized.get("data_julgamento"),
        metadata_norm.get("data_do_julgamento"),
        metadata_norm.get("data_julgamento"),
        metadata_norm.get("data_de_julgamento"),
    )
    normalized["data_publicacao"] = _pick_first_value(
        normalized.get("data_publicacao"),
        metadata_norm.get("data_publicacao"),
        metadata_norm.get("data_de_publicacao"),
    )
    normalized["data_registro"] = _pick_first_value(
        normalized.get("data_registro"),
        metadata_norm.get("data_registro"),
        metadata_norm.get("data_de_registro"),
    )
    normalized["ementa_trecho"] = _pick_first_value(
        normalized.get("ementa_trecho"),
        normalized.get("ementa"),
        normalized.get("resumo"),
        normalized.get("result_description"),
    )[:500]

    # ── Document URL / download capability ───────────────────────────────────
    # CL  (PJud): the buscador is SPA-based and exposes no direct document URL,
    #              so no inteiro_url is fabricated and the "Inteiro Teor" link
    #              stays hidden. Downloads re-drive the browser and are keyed by
    #              id_sentencia + categoria (chile_scraper.py).
    # CLTC (TC Chile): the REST backend DOES expose a stable document URL,
    #              https://buscador-backend.tcchile.cl/api/extended/{folio}/download,
    #              which tc_chile_scraper.py puts in inteiro_url/download_url.
    #
    # The frontend used to treat "downloadable" as "has inteiro_url", which made
    # every CL (PJud) result a dead end: no link, no checkbox, both download
    # buttons disabled. Publish the capability explicitly so the UI can offer
    # the two download modes without inferring them from a URL alone.
    inteiro_url = _clean_text(
        normalized.get("inteiro_url")
        or normalized.get("download_url")
        or normalized.get("url")
    )
    normalized["inteiro_url"] = inteiro_url

    tribunal_key = normalized.get("tribunal")
    id_sentencia = _clean_text(normalized.get("id_sentencia"))
    if inteiro_url:
        normalized["download_mode"] = "url"
    elif tribunal_key == "CL" and id_sentencia:
        # PJud has no document URL; download works by id_sentencia + categoria.
        normalized["download_mode"] = "browser"
    else:
        normalized["download_mode"] = "none"
    normalized["downloadable"] = normalized["download_mode"] != "none"

    return normalized


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json_file(path: Path, default: Any) -> Any:
    try:
        if not path.is_file():
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _ensure_named_symlink(source: Path, link_path: Path) -> Dict[str, Any]:
    source_path = source.expanduser().resolve()
    link_path = link_path.expanduser()
    link_path.parent.mkdir(parents=True, exist_ok=True)

    result: Dict[str, Any] = {
        "link": str(link_path),
        "target": str(source_path),
        "status": "unknown",
    }

    try:
        if link_path.exists() or link_path.is_symlink():
            if link_path.is_symlink():
                current_target = os.path.realpath(link_path)
                if os.path.abspath(current_target) == os.path.abspath(str(source_path)):
                    result["status"] = "already_linked"
                    return result
                link_path.unlink()
            else:
                result["status"] = "skipped_non_symlink"
                result["error"] = "destination exists and is not a symlink"
                return result

        os.symlink(str(source_path), str(link_path))
        result["status"] = "linked"
        return result
    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)
        return result


def _safe_path_component(value: Optional[str], fallback: str) -> str:
    raw = (value or fallback).strip() or fallback
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in raw)
    return cleaned[:64] or fallback
