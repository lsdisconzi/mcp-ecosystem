"""Tribunal Constitucional de Chile (TC) — buscador de jurisprudencia.

Scraper para el buscador oficial de jurisprudencia del Tribunal Constitucional
de Chile, disponible en https://buscador.tcchile.cl.

A diferencia de `chile_scraper.py` (Poder Judicial, SPA protegida con F5 +
reCAPTCHA que requiere Selenium), este buscador expone una API REST pública en
Laravel, sin autenticación, sin CSRF y sin CAPTCHA. Por lo tanto este scraper
usa `requests` y **no requiere un navegador**.

API base: https://buscador-backend.tcchile.cl/api

Endpoints utilizados
--------------------
* ``GET /buscadorexterno/ficha?page={n}&filter={json}``
  Búsqueda sobre metadatos (fichas). Paginado, ``per_page`` fijo en 5.
  Respuesta: ``{data: [...], meta: {total, current_page, per_page, last_page}}``
* ``GET /extended/sentencias?page={n}&filter={json}``
  Búsqueda de texto libre sobre el texto completo (OCR). ``per_page`` fijo en 5.
  Respuesta: ``{data: {count, next, previous, results: [...], corrected_query},
  meta: {...}}``. Sólo respeta ``search`` y ``literal``.
* ``GET /extended/{folio}/download``
  Descarga el PDF. Responde ``application/pdf`` y entrega el nombre real en
  ``Content-Disposition: attachment; filename="2012-04-30 16622.pdf"``.
  Devuelve 404 si no existe un documento con ese título.
* ``GET /buscadorexterno/tipodato?sortBy=id&descending=true&page=1&rowsPerPage=100``
  Catálogos (ministros, palabras clave, decisiones, competencias, etc.).

Notas importantes verificadas contra el API en vivo
---------------------------------------------------
1. La clave de descarga es el **folio**, no el ``id`` de la ficha. El SPA
   oficial hace ``rs(card.folio || card.rol)`` y ``rs(this.ficha.folio)``.
2. ``fecha_sentencia`` es una fecha **exacta** (``YYYY-MM-DD``), no un rango.
   Un rango de fechas se resuelve iterando día por día.
3. ``per_page`` está fijado en 5 y no puede sobreescribirse por query param.
4. Los filtros de catálogo esperan **nombres exactos** del catálogo, no ids.
   ``resolve_catalog_value()`` hace una resolución difusa para tolerar entradas
   parciales (p. ej. "INA" -> "Inaplicabilidad de Precepto Legal (Art. 93 N° 6 - INA) ").
5. ``articulo_constitucion`` es aceptado pero ignorado por el backend en
   ``/buscadorexterno/ficha`` (se envía igual por fidelidad con el SPA).
6. Peligro verificado: ``/buscadorexterno/ficha`` **descarta el filtro ``search``
   en silencio cuando el término no coincide con nada** y devuelve el corpus
   completo (12.329 fichas) en lugar de cero. Buscar "latam airlines" devolvía
   12.329 fichas ajenas al caso. Antes de confiar en ese endpoint,
   ``search_with_criteria()`` compara el total filtrado con el total sin término
   (cacheado) y, si coinciden, reintenta la consulta en ``/extended/sentencias``,
   que sí respeta ``search`` y reporta la verdad vía ``data.count``.
   Ver ``docs/tc-chile-source.md`` §0 — *The silent-corpus trap*.

Uso
---
    from tc_chile_scraper import TCChileJurisprudenciaScraper, SearchCriteria

    with TCChileJurisprudenciaScraper() as scraper:
        results = scraper.search_with_criteria(
            SearchCriteria(search_text="vida", max_results=10)
        )
        paths = scraper.download_all_inteiro_teor(results, "jurisprudence_downloads")
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field, fields as dc_fields
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests

try:  # El helper vive en _shared/chrome_driver.py, que importa Selenium.
    from _shared.chrome_driver import write_sidecar_metadata
except Exception:  # noqa: BLE001 - este scraper no debe requerir Selenium
    def write_sidecar_metadata(filepath: str, metadata: Dict[str, Any]) -> None:
        """Escribe un sidecar ``.metadata.json`` junto al artefacto descargado."""
        try:
            with open(f"{filepath}.metadata.json", "w", encoding="utf-8") as handle:
                json.dump(metadata, handle, ensure_ascii=False, indent=2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudo escribir el sidecar de %s: %s", filepath, exc)


logger = logging.getLogger(__name__)

# ── Constantes del servicio ────────────────────────────────────────────────

TC_COURT_KEY = "CLTC"
TC_COURT_NAME = "Tribunal Constitucional de Chile"

TC_API_BASE = "https://buscador-backend.tcchile.cl/api"
TC_PUBLIC_BASE = "https://buscador.tcchile.cl"

#: El backend fija per_page=5 y no permite sobreescribirlo.
PER_PAGE = 5

#: Catálogos expuestos por ``/buscadorexterno/tipodato``.
CAT_MINISTROS = 1
CAT_PALABRAS_CLAVE = 2
CAT_CAUSAL_INADMISIBILIDAD = 25
CAT_SALA = 26
CAT_DECISION = 27
CAT_PRECEPTO_LEGAL = 28
CAT_ARTICULO_CONSTITUCION = 29
CAT_CUERPO_LEGAL = 30
CAT_TIPO_RESOLUCION = 31
CAT_COMPETENCIAS = 33

#: Nombres de parámetro de ``detalle`` usados para construir metadatos ricos.
PARAM_PRECEPTO_IMPUGNADO = 2
PARAM_GESTION_PENDIENTE = 3
PARAM_RESULTADO = 5
PARAM_VOTO_MAYORIA = 6
PARAM_REDACTOR_MAYORIA = 7
PARAM_VOTO_DISIDENCIA = 39
PARAM_REDACTOR_DISIDENCIA = 42
PARAM_DOCTRINA = 50
PARAM_ARTICULO_CONSTITUCION = 63
PARAM_PALABRAS_CLAVE = 64
PARAM_SENTENCIAS_RELACIONADAS = 68
PARAM_TIPO_RESOLUCION = 71

#: Límites de seguridad para no golpear el servicio.
DEFAULT_TIMEOUT = 60
DEFAULT_REQUEST_DELAY = 0.35
MAX_PAGES_PER_DAY = 40
MAX_DATE_SCAN_DAYS = 400


# ── Criterios de búsqueda ──────────────────────────────────────────────────

@dataclass
class SearchCriteria:
    """Criterios de búsqueda del Tribunal Constitucional de Chile.

    Los campos «nativos» (``folio``, ``competencia``, ``ministro``, ...) son los
    que realmente viajan al API. Los campos marcados como *alias* existen para
    que la capa de rutas del backend (``modules/routes_search.py``) y el prompt
    en español puedan enviar nombres heredados de otras cortes sin que se
    pierdan silenciosamente.
    """

    # ── Núcleo ──
    search_text: str = ""
    folio: str = ""
    literal: bool = False          # frase exacta -> busca en texto completo
    exclusion: bool = False        # modo exclusión (excluye las palabras clave)

    # ── Filtros por catálogo (aceptan nombres del catálogo o ids) ──
    competencia: List[Any] = field(default_factory=list)
    tipo_resolucion: List[Any] = field(default_factory=list)
    resultado: List[Any] = field(default_factory=list)
    ministro: List[Any] = field(default_factory=list)
    cuerpo_legal: List[Any] = field(default_factory=list)
    palabra_clave: List[Any] = field(default_factory=list)
    articulo_constitucion: List[Any] = field(default_factory=list)

    # ── Fechas ──
    fecha_sentencia: str = ""      # fecha exacta YYYY-MM-DD
    fecha_inicio: str = ""         # rango: inicio (se itera día por día)
    fecha_fin: str = ""            # rango: fin

    # ── Enrutamiento / paginación ──
    buscar_en_texto: bool = False  # fuerza /extended/sentencias
    max_results: int = 20
    search_index: str = ""         # informativo: "texto_libre" | "metadatos"
    orden: str = ""                # "recientes" | "antiguos" | "relevancia"
    resultados_por_pagina: int = PER_PAGE
    incluir_reservadas: bool = False

    # ── Alias de compatibilidad con la capa de rutas ──
    tribunal: str = ""
    juez: str = ""
    materia: str = ""
    rol: str = ""
    categoria: str = ""
    tipo_norma: str = ""
    orgao_julgador: str = ""
    relator: str = ""
    tipo_processo: str = ""
    tipo_decisao: str = ""
    assunto_cnj: str = ""
    classe_cnj: str = ""
    comarca_origem: str = ""
    data_julgamento_inicio: str = ""
    data_julgamento_fim: str = ""


# ── Utilidades ─────────────────────────────────────────────────────────────

def _norm_text(value: Any) -> str:
    """Normaliza texto para comparaciones tolerantes (minúsculas, sin tildes)."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _as_list(value: Any) -> List[Any]:
    """Coacciona escalares, CSV, JSON y secuencias a una lista plana."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        out: List[Any] = []
        for item in value:
            out.extend(_as_list(item))
        return out
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        if raw.startswith("["):
            try:
                return _as_list(json.loads(raw))
            except (ValueError, TypeError):
                pass
        if "," in raw:
            return [part.strip() for part in raw.split(",") if part.strip()]
        return [raw]
    return [value]


def _first_str(*values: Any) -> str:
    """Devuelve el primer valor con contenido, como string limpio."""
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _parse_date(value: Any) -> Optional[date]:
    """Interpreta fechas en los formatos que aparecen en este proyecto."""
    text = _first_str(value)
    if not text:
        return None
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[: len(fmt) + 2].strip(), fmt).date()
        except ValueError:
            continue
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    return None


def _sanitize_filename(name: str, fallback: str = "document") -> str:
    """Limpia un nombre de archivo proveniente del servidor.

    Los espacios se colapsan a ``_`` para que los nombres sean cómodos de usar
    desde la shell y en las URLs de descarga de la API.
    """
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", str(name or "")).strip()
    cleaned = "_".join(cleaned.split())
    return cleaned or fallback


# ── Scraper ────────────────────────────────────────────────────────────────

class TCChileJurisprudenciaScraper:
    """Cliente para el buscador de jurisprudencia del Tribunal Constitucional.

    Implementa el contrato de scraper del proyecto (``search_with_criteria``,
    ``download_inteiro_teor_url``, ``download_all_inteiro_teor``, ``close``)
    pero sin Selenium: todo se resuelve con HTTP directo.
    """

    BASE = TC_API_BASE
    COURT = TC_COURT_KEY

    # Totales de ``/buscadorexterno/ficha`` sin término de búsqueda, por
    # combinación de filtros residuales. Compartido entre instancias porque el
    # API crea un scraper nuevo por búsqueda; ver ``_baseline_total``.
    _BASELINE_CACHE: Dict[str, int] = {}

    HEADERS = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": TC_PUBLIC_BASE,
        "Referer": f"{TC_PUBLIC_BASE}/",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
    }

    def __init__(
        self,
        headless: bool = True,
        wait_time: int = 30,
        request_delay: float = DEFAULT_REQUEST_DELAY,
        timeout: int = DEFAULT_TIMEOUT,
        cache_dir: Optional[str] = None,
    ) -> None:
        # ``headless``/``wait_time`` se aceptan por paridad con el resto de
        # scrapers del proyecto; aquí no hay navegador que configurar.
        self.headless = headless
        self.wait_time = wait_time
        self.request_delay = max(0.0, float(request_delay))
        self.timeout = timeout

        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

        self._last_request_at = 0.0
        self._catalogs: Optional[Dict[int, Dict[str, Any]]] = None
        self._catalog_cache_path = (
            Path(cache_dir) / "tc_chile_catalogs.json"
            if cache_dir
            else Path("master_index") / "tc_chile_catalogs.json"
        )

    # ── Infraestructura HTTP ───────────────────────────────────────────────

    def _throttle(self) -> None:
        """Espacia las peticiones para no castigar el servicio público."""
        if self.request_delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.request_delay - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """GET contra el API devolviendo JSON, con reintentos suaves."""
        url = f"{self.BASE}{path}"
        last_error: Optional[Exception] = None

        for attempt in range(3):
            self._throttle()
            try:
                response = self.session.get(url, params=params or {}, timeout=self.timeout)
                self._last_request_at = time.monotonic()

                if response.status_code == 404:
                    raise FileNotFoundError(
                        f"Sin resultados en {url} (HTTP 404)"
                    )
                if response.status_code >= 500:
                    raise RuntimeError(f"HTTP {response.status_code} desde {url}")
                response.raise_for_status()
                return response.json()
            except FileNotFoundError:
                raise
            except Exception as exc:  # noqa: BLE001 - reintento genérico
                last_error = exc
                if attempt < 2:
                    time.sleep(0.8 * (attempt + 1))

        raise RuntimeError(f"No se pudo consultar {url}: {last_error}")

    # ── Catálogos ─────────────────────────────────────────────────────────

    def load_catalogs(self, force_refresh: bool = False) -> Dict[int, Dict[str, Any]]:
        """Carga los catálogos de ``tipodato``, con caché en disco.

        Devuelve ``{catalog_id: {"nombre": str, "items": [{"id", "nombre"}], ...}}``.
        """
        if self._catalogs is not None and not force_refresh:
            return self._catalogs

        if not force_refresh and self._catalog_cache_path.is_file():
            try:
                cached = json.loads(self._catalog_cache_path.read_text(encoding="utf-8"))
                self._catalogs = {int(k): v for k, v in cached.items()}
                logger.debug("Catálogos TC cargados desde %s", self._catalog_cache_path)
                return self._catalogs
            except Exception as exc:  # noqa: BLE001
                logger.warning("Caché de catálogos TC ilegible, se recarga: %s", exc)

        try:
            payload = self._get_json(
                "/buscadorexterno/tipodato",
                {"sortBy": "id", "descending": "true", "page": 1, "rowsPerPage": 100},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudieron cargar los catálogos TC: %s", exc)
            self._catalogs = {}
            return self._catalogs

        rows = payload.get("data") if isinstance(payload, dict) else payload
        catalogs: Dict[int, Dict[str, Any]] = {}
        for row in rows or []:
            if not isinstance(row, dict) or row.get("id") is None:
                continue
            items = [
                {
                    "id": item.get("id"),
                    "nombre": str(item.get("nombre") or "").strip(),
                }
                for item in (row.get("tipo_dato_contenido") or [])
                if isinstance(item, dict)
            ]
            catalogs[int(row["id"])] = {
                "id": int(row["id"]),
                "nombre": row.get("nombre"),
                "items": items,
            }

        self._catalogs = catalogs
        try:
            self._catalog_cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._catalog_cache_path.write_text(
                json.dumps(
                    {str(k): v for k, v in catalogs.items()},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("No se pudo escribir la caché de catálogos TC: %s", exc)

        return catalogs

    def resolve_catalog_value(self, catalog_id: int, value: Any) -> Optional[str]:
        """Resuelve un valor de filtro al nombre exacto del catálogo.

        Acepta el nombre exacto, un id numérico, o una variante parcial/parafraseada
        (p. ej. ``"INA"`` o ``"código civil"``). Devuelve ``None`` si no hay
        coincidencia razonable, de modo que el llamador pueda hacer *fallback*.
        """
        catalogs = self.load_catalogs()
        catalog = catalogs.get(int(catalog_id))
        if not catalog:
            return None

        items = catalog.get("items") or []
        if not items:
            return None

        raw = _first_str(value)
        if not raw:
            return None

        # 1. Coincidencia exacta por nombre.
        for item in items:
            if item["nombre"] == raw:
                return item["nombre"]

        # 2. Coincidencia por id.
        if str(raw).isdigit():
            for item in items:
                if str(item.get("id")) == str(raw):
                    return item["nombre"]

        # 3. Coincidencia normalizada (sin tildes / mayúsculas).
        target = _norm_text(raw)
        if not target:
            return None
        for item in items:
            if _norm_text(item["nombre"]) == target:
                return item["nombre"]

        # 4. Subcadena en cualquiera de las direcciones.
        for item in items:
            norm = _norm_text(item["nombre"])
            if target and (target in norm or norm in target):
                return item["nombre"]

        # 5. Mayor solapamiento de tokens significativos.
        target_tokens = {t for t in target.split() if len(t) > 2}
        if not target_tokens:
            return None
        best: Optional[str] = None
        best_score = 0.0
        for item in items:
            norm = _norm_text(item["nombre"])
            tokens = {t for t in norm.split() if len(t) > 2}
            if not tokens:
                continue
            overlap = len(target_tokens & tokens)
            if not overlap:
                continue
            score = overlap / math.sqrt(len(target_tokens) * len(tokens))
            if score > best_score:
                best_score = score
                best = item["nombre"]
        if best is not None and best_score >= 0.45:
            return best
        return None

    def _resolve_filter_values(self, catalog_id: int, values: Iterable[Any]) -> List[str]:
        """Resuelve una lista de valores de filtro contra un catálogo."""
        resolved: List[str] = []
        for value in values:
            name = self.resolve_catalog_value(catalog_id, value)
            if name and name not in resolved:
                resolved.append(name)
            elif not name:
                # Se conserva el valor original: el backend decide si lo ignora.
                raw = _first_str(value)
                if raw and raw not in resolved:
                    logger.warning(
                        "Valor '%s' no coincide con el catálogo %s; se envía tal cual.",
                        raw,
                        catalog_id,
                    )
                    resolved.append(raw)
        return resolved

    # ── Construcción del filtro ───────────────────────────────────────────

    def _build_filter(self, criteria: SearchCriteria) -> Dict[str, Any]:
        """Traduce ``SearchCriteria`` al objeto ``filter`` que espera el API."""
        search_text = _first_str(criteria.search_text)
        folio = _first_str(criteria.folio, criteria.rol)

        # Alias heredados de otras cortes.
        ministro_values = _as_list(criteria.ministro) + _as_list(criteria.juez)
        ministro_values += _as_list(criteria.orgao_julgador) + _as_list(criteria.relator)

        tipo_resolucion_values = _as_list(criteria.tipo_resolucion)
        tipo_resolucion_values += _as_list(criteria.tipo_processo)

        resultado_values = _as_list(criteria.resultado) + _as_list(criteria.tipo_decisao)

        cuerpo_legal_values = _as_list(criteria.cuerpo_legal) + _as_list(criteria.tipo_norma)

        palabra_clave_values = _as_list(criteria.palabra_clave) + _as_list(criteria.materia)
        palabra_clave_values += _as_list(criteria.assunto_cnj)

        payload: Dict[str, Any] = {
            "search": search_text,
            "folio": folio,
        }

        competencia = self._resolve_filter_values(CAT_COMPETENCIAS, _as_list(criteria.competencia))
        if competencia:
            payload["competencia"] = competencia

        tipo_resolucion = self._resolve_filter_values(CAT_TIPO_RESOLUCION, tipo_resolucion_values)
        if tipo_resolucion:
            payload["tipo_resolucion"] = tipo_resolucion

        resultado = self._resolve_filter_values(CAT_DECISION, resultado_values)
        if resultado:
            payload["resultado"] = resultado

        ministro = self._resolve_filter_values(CAT_MINISTROS, ministro_values)
        if ministro:
            payload["ministro"] = ministro

        cuerpo_legal = self._resolve_filter_values(CAT_CUERPO_LEGAL, cuerpo_legal_values)
        if cuerpo_legal:
            payload["cuerpo_legal"] = cuerpo_legal

        palabra_clave = self._resolve_filter_values(CAT_PALABRAS_CLAVE, palabra_clave_values)
        if palabra_clave:
            payload["palabra_clave"] = palabra_clave

        articulo = self._resolve_filter_values(
            CAT_ARTICULO_CONSTITUCION, _as_list(criteria.articulo_constitucion)
        )
        if articulo:
            # Verificado: el backend acepta pero ignora este filtro en /ficha.
            payload["articulo_constitucion"] = articulo

        if criteria.exclusion:
            payload["exclusion"] = True

        if criteria.literal:
            payload["literal"] = True

        return payload

    def _use_fulltext_endpoint(self, criteria: SearchCriteria, payload: Dict[str, Any]) -> bool:
        """Decide si la búsqueda debe ir a ``/extended/sentencias``.

        Regla del SPA oficial: con frase exacta (``literal``) se usa el índice de
        texto completo; en cualquier otro caso se usan los metadatos de ``ficha``.
        """
        if criteria.buscar_en_texto:
            return True
        if criteria.literal:
            return True
        index = _norm_text(criteria.search_index)
        if index in {
            "texto libre", "texto_libre", "texto completo", "texto_completo",
            "fulltext", "full text", "sentencias",
            # Alias heredados del formulario brasileño.
            "inteiro teor", "inteiro_teor",
        }:
            return True
        return False

    # ── Detección de filtro descartado ────────────────────────────────────

    def _ficha_total(self, payload: Dict[str, Any]) -> Optional[int]:
        """Total de coincidencias según ``ficha`` para un filtro dado."""
        try:
            data = self._fetch_ficha_page(payload, 1)
        except Exception as exc:  # noqa: BLE001 - sondeo best-effort
            logger.warning("TC Chile: no se pudo sondear el total de ficha: %s", exc)
            return None
        meta = data.get("meta") or {}
        total = meta.get("total")
        try:
            return int(total) if total is not None else None
        except (TypeError, ValueError):
            return None

    def _baseline_total(self, payload: Dict[str, Any]) -> Optional[int]:
        """Total sin término de búsqueda, manteniendo el resto de filtros.

        Se cachea a **nivel de clase** porque el API crea un scraper nuevo por
        cada búsqueda (`routes_search.py`), así que una caché de instancia nunca
        sobreviviría. El total del corpus sin filtro es una propiedad global
        estable, y ahorra un sondeo (~0,35 s de `request_delay`) por búsqueda.

        Los sondeos fallidos **no** se cachean: guardar un `None` desactivaría la
        guarda para siempre en este proceso.
        """
        baseline_payload = dict(payload)
        baseline_payload["search"] = ""
        baseline_payload.pop("literal", None)
        key = json.dumps(baseline_payload, sort_keys=True, ensure_ascii=False)
        if key in self._BASELINE_CACHE:
            return self._BASELINE_CACHE[key]
        total = self._ficha_total(baseline_payload)
        if total is not None and total > 0:
            self._BASELINE_CACHE[key] = total
        return total

    def _search_refused_free_text(self, payload: Dict[str, Any]) -> bool:
        """¿El endpoint de metadatos ignoró el término de búsqueda?

        ``/buscadorexterno/ficha`` devuelve el corpus COMPLETO cuando el término
        no coincide con ningún registro, en lugar de devolver cero. Es decir,
        una consulta sin coincidencias degenera en "dame todo": buscar
        ``latam airlines`` devolvía 12.329 fichas (el total sin filtro).

        Detectarlo comparando el total filtrado con el total sin término permite
        redirigir la consulta al índice de texto completo, que sí respeta el
        término y responde 0 de forma honesta.

        La comparación usa ``>=`` (no ``==``) a propósito: el corpus crece con el
        tiempo, así que una caché ligeramente desactualizada debe seguir
        detectando el fallo, y un total filtrado nunca puede superar el total sin
        filtro salvo que el filtro se haya descartado.
        """
        if not _norm_text(payload.get("search")):
            return False
        filtered_total = self._ficha_total(payload)
        if filtered_total is None:
            return False
        baseline_total = self._baseline_total(payload)
        if baseline_total is None or baseline_total <= 0:
            return False
        return filtered_total >= baseline_total

    # ── Búsqueda ──────────────────────────────────────────────────────────

    def _fetch_ficha_page(self, payload: Dict[str, Any], page: int) -> Dict[str, Any]:
        return self._get_json(
            "/buscadorexterno/ficha",
            {"page": page, "filter": json.dumps(payload, ensure_ascii=False)},
        )

    def _fetch_sentencias_page(self, payload: Dict[str, Any], page: int) -> Dict[str, Any]:
        # El endpoint de texto completo sólo respeta `search` y `literal`.
        fulltext_payload = {
            "search": payload.get("search", ""),
            "literal": bool(payload.get("literal")),
        }
        return self._get_json(
            "/extended/sentencias",
            {"page": page, "filter": json.dumps(fulltext_payload, ensure_ascii=False)},
        )

    def _search_ficha(
        self,
        payload: Dict[str, Any],
        max_results: int,
        include_reserved: bool,
    ) -> List[Dict[str, Any]]:
        """Pagina ``/buscadorexterno/ficha`` normalizando cada ficha."""
        collected: List[Dict[str, Any]] = []
        skipped_reserved = 0
        page = 1
        last_page = 1

        while len(collected) < max_results and page <= last_page and page <= MAX_PAGES_PER_DAY:
            data = self._fetch_ficha_page(payload, page)
            rows = data.get("data") or []
            meta = data.get("meta") or {}

            if page == 1:
                last_page = int(meta.get("last_page") or 1)

            if not rows:
                break

            for row in rows:
                if not isinstance(row, dict):
                    continue

                if not self._is_downloadable(row):
                    continue

                if self._is_reserved(row) and not include_reserved:
                    skipped_reserved += 1
                    continue

                item = self._normalize_ficha(row, payload)
                if item:
                    collected.append(item)
                    if len(collected) >= max_results:
                        break

            if meta.get("current_page") and int(meta["current_page"]) >= last_page:
                break
            page += 1

        if skipped_reserved:
            logger.info(
                "TC Chile: %d ficha(s) omitida(s) por estar marcadas como reservadas "
                "(activa incluir_reservadas=True para incluirlas).",
                skipped_reserved,
            )
        return collected

    def _search_sentencias(
        self,
        payload: Dict[str, Any],
        max_results: int,
        include_reserved: bool,
    ) -> List[Dict[str, Any]]:
        """Pagina ``/extended/sentencias`` normalizando cada sentencia."""
        collected: List[Dict[str, Any]] = []
        skipped_reserved = 0
        page = 1
        last_page = 1
        corrected_query: Optional[str] = None

        while len(collected) < max_results and page <= last_page and page <= MAX_PAGES_PER_DAY:
            data = self._fetch_sentencias_page(payload, page)
            block = data.get("data") or {}
            meta = data.get("meta") or {}
            rows = block.get("results") or []

            if page == 1:
                last_page = int(meta.get("last_page") or 1)
                corrected_query = block.get("corrected_query")

                # ``count`` es la verdad del índice: a diferencia de ``/ficha``,
                # este endpoint sí respeta el término y devuelve 0 en lugar de
                # volcar el corpus cuando no hay coincidencias.
                total = block.get("count")
                try:
                    total = int(total) if total is not None else None
                except (TypeError, ValueError):
                    total = None
                if total == 0 and _norm_text(payload.get("search")):
                    logger.info(
                        "TC Chile: el índice de texto completo no tiene "
                        "coincidencias para %r (count=0).",
                        payload.get("search"),
                    )
                    return []

            if not rows:
                break

            for row in rows:
                if not isinstance(row, dict):
                    continue
                if self._is_reserved(row) and not include_reserved:
                    skipped_reserved += 1
                    continue
                item = self._normalize_sentencia(row, payload)
                if item:
                    collected.append(item)
                    if len(collected) >= max_results:
                        break

            if meta.get("current_page") and int(meta["current_page"]) >= last_page:
                break
            page += 1

        if corrected_query:
            logger.info("TC Chile: el buscador sugirió la consulta %r", corrected_query)
        if skipped_reserved:
            logger.info(
                "TC Chile: %d sentencia(s) omitida(s) por estar marcadas como reservadas.",
                skipped_reserved,
            )
        return collected

    def search_with_criteria(self, criteria: SearchCriteria) -> List[Dict[str, Any]]:
        """Ejecuta la búsqueda y devuelve resultados normalizados.

        Si se entrega un rango ``fecha_inicio``/``fecha_fin`` (y no una fecha
        exacta), se itera día por día porque ``fecha_sentencia`` es una
        coincidencia exacta en el backend.
        """
        max_results = max(1, int(criteria.max_results or 20))
        include_reserved = bool(criteria.incluir_reservadas)
        payload = self._build_filter(criteria)

        use_fulltext = self._use_fulltext_endpoint(criteria, payload)
        if not use_fulltext and self._search_refused_free_text(payload):
            logger.warning(
                "TC Chile: el índice de metadatos ignoró el término %r (devolvió "
                "el corpus completo). Se repite la búsqueda en texto completo.",
                payload.get("search"),
            )
            use_fulltext = True
        exact_date = _parse_date(criteria.fecha_sentencia)
        start = _parse_date(criteria.fecha_inicio or criteria.data_julgamento_inicio)
        end = _parse_date(criteria.fecha_fin or criteria.data_julgamento_fim)

        # Un rango con inicio y fin idénticos equivale a una fecha exacta.
        if start and end and start == end:
            exact_date, start, end = start, None, None

        logger.info(
            "TC Chile: buscando (endpoint=%s, max=%d) payload=%s",
            "/extended/sentencias" if use_fulltext else "/buscadorexterno/ficha",
            max_results,
            json.dumps(payload, ensure_ascii=False),
        )

        results: List[Dict[str, Any]] = []

        if exact_date:
            day_payload = dict(payload)
            day_payload["fecha_sentencia"] = exact_date.isoformat()
            fetcher = self._search_sentencias if use_fulltext else self._search_ficha
            return fetcher(day_payload, max_results, include_reserved)

        if start or end:
            if use_fulltext:
                # ``/extended/sentencias`` sólo respeta ``search`` y ``literal``:
                # iterar día por día repetiría la misma consulta N veces.
                logger.info(
                    "TC Chile: el índice de texto completo ignora las fechas; "
                    "se omite el recorrido día por día."
                )
                return self._search_sentencias(payload, max_results, include_reserved)
            return self._search_date_range(
                payload, start, end, max_results, include_reserved, use_fulltext
            )

        fetcher = self._search_sentencias if use_fulltext else self._search_ficha
        results = fetcher(payload, max_results, include_reserved)
        return results

    def _search_date_range(
        self,
        payload: Dict[str, Any],
        start: Optional[date],
        end: Optional[date],
        max_results: int,
        include_reserved: bool,
        use_fulltext: bool,
    ) -> List[Dict[str, Any]]:
        """Recorre un rango de fechas día por día, del más reciente al más antiguo."""
        today = date.today()
        range_end = end or today
        range_start = start or (range_end - timedelta(days=30))
        if range_start > range_end:
            range_start, range_end = range_end, range_start

        span = (range_end - range_start).days + 1
        if span > MAX_DATE_SCAN_DAYS:
            logger.warning(
                "TC Chile: el rango solicitado abarca %d días; se limita a los %d "
                "más recientes para no saturar el servicio.",
                span,
                MAX_DATE_SCAN_DAYS,
            )
            range_start = range_end - timedelta(days=MAX_DATE_SCAN_DAYS - 1)
            span = MAX_DATE_SCAN_DAYS

        logger.info(
            "TC Chile: barriendo %d día(s) entre %s y %s (fecha exacta por día).",
            span,
            range_start.isoformat(),
            range_end.isoformat(),
        )

        fetcher = self._search_sentencias if use_fulltext else self._search_ficha
        collected: List[Dict[str, Any]] = []
        seen: set = set()

        current = range_end
        while current >= range_start and len(collected) < max_results:
            day_payload = dict(payload)
            day_payload["fecha_sentencia"] = current.isoformat()

            try:
                day_items = fetcher(day_payload, max_results - len(collected), include_reserved)
            except Exception as exc:  # noqa: BLE001 - un día fallido no debe abortar todo
                logger.warning("TC Chile: fallo al consultar %s: %s", current.isoformat(), exc)
                day_items = []

            for item in day_items:
                key = item.get("numero_processo") or item.get("id")
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                collected.append(item)
                if len(collected) >= max_results:
                    break

            current -= timedelta(days=1)

        return collected

    # ── Normalización ─────────────────────────────────────────────────────

    @staticmethod
    def _is_downloadable(record: Dict[str, Any]) -> bool:
        """``exist_file`` distinto de 1/True indica que no hay PDF asociado."""
        if "exist_file" not in record:
            return True
        return str(record.get("exist_file")).strip() in {"1", "true", "True"}

    @staticmethod
    def _is_reserved(record: Dict[str, Any]) -> bool:
        return str(record.get("es_reservada")).strip() in {"1", "true", "True"}

    @staticmethod
    def _detalle_map(record: Dict[str, Any]) -> Dict[str, List[str]]:
        """Agrupa ``detalle`` por nombre de parámetro, preservando múltiples valores."""
        grouped: Dict[str, List[str]] = {}
        for entry in record.get("detalle") or []:
            if not isinstance(entry, dict):
                continue
            param = entry.get("parametro") or {}
            name = str(param.get("nombre") or "").strip()
            if not name:
                continue

            values: List[str] = []
            single = _first_str(entry.get("valor"))
            if single:
                values.append(single)
            for multi in entry.get("detalle_multiple") or []:
                if isinstance(multi, dict):
                    value = _first_str(multi.get("valor"))
                    if value:
                        values.append(value)

            if values:
                grouped.setdefault(name, []).extend(values)
        return grouped

    def _normalize_ficha(self, record: Dict[str, Any], payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convierte una ficha del API en el dict normalizado del proyecto."""
        folio = _first_str(record.get("folio"), record.get("codigo"))
        if not folio:
            return None

        template = record.get("template") or {}
        estado = record.get("estado") or {}
        detalle = self._detalle_map(record)

        sentencia_date = _parse_date(record.get("fecha_sentencia"))
        fecha_display = sentencia_date.isoformat() if sentencia_date else ""

        doctrina = " ".join(detalle.get("Doctrina", [])).strip()
        resultado = " / ".join(detalle.get("Resultado", [])).strip()
        competencia = " / ".join(detalle.get("Competencia", [])).strip()
        tipo_resolucion = " / ".join(detalle.get("Tipo de resolución", [])).strip()

        relator = _first_str(
            *detalle.get("Redactor voto mayoría", []),
            *detalle.get("Redactor disidencia", []),
        )
        sala = _first_str(*detalle.get("Sala", []))
        rol = _first_str(record.get("codigo"), folio)

        metadata: Dict[str, Any] = {
            "source": "TC Chile (buscador.tcchile.cl)",
            "ficha_id": record.get("id"),
            "folio": folio,
            "codigo": record.get("codigo"),
            "nombre": record.get("nombre"),
            "template": template.get("complete_name") or template.get("nombre"),
            "template_codigo": template.get("codigo"),
            "estado": estado.get("nombre"),
            "fecha_sentencia": record.get("fecha_sentencia"),
            "es_reservada": bool(self._is_reserved(record)),
            "sala": sala,
        }
        for name, values in detalle.items():
            metadata[f"tc_{name}"] = " | ".join(values) if len(values) > 1 else values[0]

        return {
            "court": TC_COURT_KEY,
            "tribunal": TC_COURT_NAME,
            "tribunal_pais": "Chile",
            "numero_processo": folio,
            "rol": rol,
            "classe_assunto": competencia or tipo_resolucion,
            "tipo_processo": competencia or tipo_resolucion,
            "relator": relator,
            "orgao_julgador": sala or TC_COURT_NAME,
            "data_julgamento": fecha_display,
            "ementa_trecho": (doctrina or resultado)[:500],
            "resultado": resultado,
            "fecha": fecha_display,
            "inteiro_url": f"{self.BASE}/extended/{folio}/download",
            "download_url": f"{self.BASE}/extended/{folio}/download",
            "url_detalle": f"{TC_PUBLIC_BASE}/#/ficha/{folio}",
            "search_terms": payload.get("search", ""),
            "search_endpoint": "/buscadorexterno/ficha",
            "source": "tc_chile",
            "metadata": metadata,
        }

    def _normalize_sentencia(self, record: Dict[str, Any], payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convierte una sentencia de texto completo en el dict normalizado."""
        # En /extended/sentencias el campo `id` corresponde al folio y coincide
        # con la clave de descarga (verificado: el PDF contiene el mismo texto).
        folio = _first_str(record.get("id"), record.get("rol"))
        if not folio:
            return None

        content = _first_str(record.get("content"))
        competencia = _first_str(record.get("competencia"))
        short_name = _first_str(record.get("competenciaShortName"))

        highlights: List[str] = []
        for paragraph in record.get("highlightParagraphs") or []:
            if isinstance(paragraph, dict):
                value = _first_str(paragraph.get("full"), paragraph.get("summary"))
                if value:
                    highlights.append(value)

        custom_fields: List[str] = []
        for entry in record.get("custom_fields") or []:
            if isinstance(entry, dict):
                value = _first_str(entry.get("value"), entry.get("nombre"))
                if value:
                    custom_fields.append(value)

        metadata: Dict[str, Any] = {
            "source": "TC Chile (buscador.tcchile.cl)",
            "folio": folio,
            "sentence_id": record.get("sentence_id"),
            "competencia": competencia,
            "competencia_short": short_name,
            "es_reservada": bool(self._is_reserved(record)),
            "highlight_count": record.get("highlightParagraphsAmount"),
        }
        if custom_fields:
            metadata["tc_custom_fields"] = " | ".join(custom_fields)
        if highlights:
            metadata["tc_highlight"] = " ".join(highlights[:3])[:1500]

        return {
            "court": TC_COURT_KEY,
            "tribunal": TC_COURT_NAME,
            "tribunal_pais": "Chile",
            "numero_processo": folio,
            "rol": folio,
            "tipo_processo": short_name or competencia,
            "classe_assunto": competencia,
            "orgao_julgador": TC_COURT_NAME,
            "relator": "",
            "data_julgamento": "",
            "ementa_trecho": (content or " ".join(highlights))[:500],
            "texto_completo": content,
            "inteiro_url": f"{self.BASE}/extended/{folio}/download",
            "download_url": f"{self.BASE}/extended/{folio}/download",
            "url_detalle": f"{TC_PUBLIC_BASE}/#/ficha/{folio}",
            "search_terms": payload.get("search", ""),
            "search_endpoint": "/extended/sentencias",
            "source": "tc_chile",
            "metadata": metadata,
        }

    # ── Descarga ──────────────────────────────────────────────────────────

    def _download_pdf(self, folio: str) -> tuple[bytes, str]:
        """Descarga el PDF de un folio y devuelve ``(contenido, nombre_sugerido)``."""
        url = f"{self.BASE}/extended/{folio}/download"
        self._throttle()
        response = self.session.get(url, timeout=self.timeout)
        self._last_request_at = time.monotonic()

        if response.status_code == 404:
            raise FileNotFoundError(
                f"El Tribunal Constitucional no tiene documento para el folio {folio}"
            )
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        if "application/pdf" not in content_type.lower():
            raise ValueError(
                f"Respuesta inesperada para el folio {folio}: Content-Type={content_type!r}"
            )

        suggested = ""
        disposition = response.headers.get("Content-Disposition", "")
        match = re.search(r"filename\*=UTF-8''([^;]+)", disposition)
        if match:
            from urllib.parse import unquote

            suggested = unquote(match.group(1).strip().strip('"'))
        else:
            match = re.search(r'filename="?([^";]+)"?', disposition)
            if match:
                suggested = match.group(1).strip()

        return response.content, suggested

    def download_inteiro_teor_url(
        self,
        url: str,
        filename: Optional[str] = None,
        save_dir: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
        folder_name: Optional[str] = None,
        search_params: Optional[Dict[str, Any]] = None,
        _skip_org: bool = False,
    ) -> Optional[str]:
        """Descarga el PDF de un folio y escribe su sidecar de metadatos.

        ``url`` puede ser un folio (``"16622"``), la ruta ya construida
        (``.../extended/16622/download``) o la URL pública de detalle.
        Devuelve la ruta del PDF escrito, o ``None`` si falló.

        La firma replica el contrato del resto de scrapers del proyecto
        (``folder_name``/``agent_id`` organizan la carpeta destino).
        """
        metadata = dict(metadata or {})
        folio = self.canonicalize_download_id(url)
        if not folio:
            logger.error("TC Chile: no se pudo determinar el folio desde %r", url)
            return None

        if save_dir is None:
            save_dir = os.path.abspath(
                os.path.join(os.getcwd(), "workspace", "CLTC_jurisprudencia")
            )
        if _skip_org:
            target_dir = Path(save_dir)
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            parts = [p for p in (agent_id, folder_name, timestamp) if p]
            target_dir = Path(save_dir).joinpath(*parts)
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            logger.error("TC Chile: no se pudo crear %s: %s", target_dir, exc)
            return None

        # El nombre del servidor ("2012-04-30 16622") trae una fecha que no
        # corresponde a la de la sentencia, así que solo se conserva en el
        # sidecar. El nombre local se arma con datos verificados.
        fecha = _first_str(
            metadata.get("fecha"),
            (metadata.get("metadata") or {}).get("tc_fecha_sentencia")
            if isinstance(metadata.get("metadata"), dict)
            else None,
        )
        if not filename:
            name_parts = ["CLTC"]
            if fecha:
                name_parts.append(_sanitize_filename(fecha))
            name_parts.append(_sanitize_filename(folio))
            name = f"{'_'.join(name_parts)}.pdf"
        else:
            name = _sanitize_filename(filename)

        path = target_dir / name

        try:
            content, suggested = self._download_pdf(folio)
        except FileNotFoundError as exc:
            logger.warning("TC Chile: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.error("TC Chile: error al descargar el folio %s: %s", folio, exc)
            return None

        try:
            path.write_bytes(content)
        except Exception as exc:  # noqa: BLE001
            logger.error("TC Chile: no se pudo escribir %s: %s", path, exc)
            return None

        inner = metadata.get("metadata")
        sidecar = {
            **{k: v for k, v in metadata.items() if k != "metadata"},
            "court": TC_COURT_KEY,
            "tribunal": TC_COURT_NAME,
            "tribunal_pais": "CHILE",
            "source": "tc_chile",
            "agent_id": agent_id,
            "folio": folio,
            "download_url": url if str(url).startswith("http") else f"{self.BASE}/extended/{folio}/download",
            "resolved_download_url": f"{self.BASE}/extended/{folio}/download",
            "server_filename": suggested,
            "content_type": "application/pdf",
            "file_size_bytes": len(content),
            "bytes": len(content),
            "search_params": search_params,
            "download_timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "downloaded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if isinstance(inner, dict):
            sidecar["metadata"] = inner
        write_sidecar_metadata(str(path), sidecar)

        logger.info("TC Chile: descargado folio %s -> %s (%d bytes)", folio, path, len(content))
        return str(path)

    def download_all_inteiro_teor(
        self,
        results: Sequence[Dict[str, Any]],
        save_dir: Optional[str] = None,
        overwrite: bool = False,
        delay: float = 0.5,
        agent_id: Optional[str] = None,
        folder_name: Optional[str] = None,
        search_params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[str]:
        """Descarga los PDFs de una lista de resultados normalizados."""
        if save_dir is None:
            save_dir = os.path.abspath(
                os.path.join(os.getcwd(), "workspace", "CLTC_jurisprudencia")
            )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        parts = [p for p in (agent_id, folder_name, timestamp) if p]
        final_save_dir = os.path.join(save_dir, *parts)

        paths: List[str] = []
        for index, item in enumerate(results or [], start=1):
            if not isinstance(item, dict):
                continue

            folio = _first_str(
                item.get("numero_processo"),
                item.get("folio"),
                item.get("rol"),
            )
            if not folio:
                logger.warning("TC Chile: resultado sin folio, se omite (%d)", index)
                continue

            metadata = dict(item)
            if not overwrite:
                candidate = self._existing_path(final_save_dir, folio, item)
                if candidate:
                    logger.info("TC Chile: %s ya existe, se omite", candidate)
                    paths.append(candidate)
                    continue

            logger.info("TC Chile: descargando %d/%d (folio %s)", index, len(results), folio)
            path = self.download_inteiro_teor_url(
                folio,
                save_dir=final_save_dir,
                metadata=metadata,
                agent_id=agent_id,
                folder_name=folder_name,
                search_params=search_params,
                _skip_org=True,
            )
            if path:
                paths.append(path)

            if delay and index < len(results):
                time.sleep(delay)

        return paths

    @staticmethod
    def _existing_path(save_dir: str, folio: str, item: Dict[str, Any]) -> str:
        """Devuelve la ruta de un PDF ya descargado para ``folio``, si existe."""
        fecha = _first_str(
            item.get("fecha"),
            (item.get("metadata") or {}).get("tc_fecha_sentencia")
            if isinstance(item.get("metadata"), dict)
            else None,
        )
        parts = ["CLTC"]
        if fecha:
            parts.append(_sanitize_filename(fecha))
        parts.append(_sanitize_filename(folio))
        candidate = Path(save_dir) / f"{'_'.join(parts)}.pdf"
        return str(candidate) if candidate.exists() else ""

    @staticmethod
    def canonicalize_download_id(url: str) -> str:
        """Extrae el folio desde una URL, ruta o folio suelto."""
        raw = _first_str(url)
        if not raw:
            return ""

        match = re.search(r"/extended/([^/?#]+)/download", raw)
        if match:
            return match.group(1).strip()

        match = re.search(r"/ficha/([^/?#]+)", raw)
        if match:
            return match.group(1).strip()

        # Un folio suelto, sin esquema ni separadores de ruta.
        if not re.search(r"[/:?#]", raw):
            return raw.strip()
        return ""

    # ── Compatibilidad con el resto de scrapers ───────────────────────────

    def canonicalize_inteiro_url(self, raw_url: str, fallback_num: Optional[str] = None) -> Dict[str, Optional[str]]:
        """Homólogo de ``chile_scraper``/``tjrs_scraper`` para no romper llamadas."""
        folio = self.canonicalize_download_id(raw_url) or _first_str(fallback_num)
        return {
            "folio": folio or None,
            "url": f"{self.BASE}/extended/{folio}/download" if folio else None,
        }

    def get_inteiro_links(self, query: str, max_results: int = 20) -> List[Dict[str, Any]]:
        """Azúcar sintáctico para búsquedas rápidas por texto."""
        return self.search_with_criteria(
            SearchCriteria(search_text=query, max_results=max_results)
        )

    def close(self) -> None:
        """No hay navegador que cerrar; se cierra la sesión HTTP."""
        try:
            self.session.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> "TCChileJurisprudenciaScraper":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _criteria_field_names() -> List[str]:
    """Nombres de campo aceptados por ``SearchCriteria`` (útil para diagnóstico)."""
    return [f.name for f in dc_fields(SearchCriteria)]


if __name__ == "__main__":  # pragma: no cover - utilidad de línea de comandos
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    with TCChileJurisprudenciaScraper() as scraper:
        print("Catálogos:", {k: v["nombre"] for k, v in scraper.load_catalogs().items()})

        found = scraper.search_with_criteria(
            SearchCriteria(search_text="vida", max_results=5)
        )
        print(f"\n{len(found)} resultado(s):")
        for entry in found:
            print(f"  folio={entry['numero_processo']} fecha={entry['data_julgamento']} "
                  f"resultado={entry.get('resultado')}")

        if found:
            saved = scraper.download_all_inteiro_teor(found[:1], "jurisprudence_downloads")
            print("\nDescargado:", saved)
