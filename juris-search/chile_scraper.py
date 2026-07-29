"""
Chile Poder Judicial — Jurisprudence Scraper.

Scrapes the "Buscador Unificado de Fallos del Poder Judicial" at
https://juris.pjud.cl — Chile's unified judicial rulings search portal.

Architecture:
  - SPA-style application with AJAX search (POST buscar_sentencias)
  - Google reCAPTCHA v3 + CSRF token protection
  - 10 search categories: Corte Suprema, Corte de Apelaciones, Civiles,
    Penales, Laborales, Familia, Cobranza, Compendio Extranjería,
    Lineas Jurisprudenciales, Salud CS
  - Results include: ROL, Caratulado, Fecha, Tribunal, Materia, Juez(a)
  - PDF documents downloadable via /busqueda/documentos endpoint
"""

import os
import re
import time
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any

import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from _shared.chrome_driver import (
    create_chrome_driver,
    write_sidecar_metadata,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ── Chile Search Categories ──────────────────────────────────────────────────

CHILE_CATEGORIES = {
    "corte_suprema": {
        "slug": "Corte_Suprema",
        "name": "Corte Suprema",
        "description": "Fallos de la Corte Suprema de Chile",
    },
    "corte_apelaciones": {
        "slug": "Corte_de_Apelaciones",
        "name": "Corte de Apelaciones",
        "description": "Fallos de las Cortes de Apelaciones",
    },
    "civiles": {
        "slug": "Civiles",
        "name": "Civiles",
        "description": "Jurisprudencia civil",
    },
    "penales": {
        "slug": "Penales",
        "name": "Penales",
        "description": "Jurisprudencia penal",
    },
    "laborales": {
        "slug": "Laborales",
        "name": "Laborales",
        "description": "Jurisprudencia laboral",
    },
    "familia": {
        "slug": "Familia",
        "name": "Familia",
        "description": "Jurisprudencia de familia",
    },
    "cobranza": {
        "slug": "Cobranza",
        "name": "Cobranza",
        "description": "Jurisprudencia de cobranza",
    },
    "compendio_extranjeria": {
        "slug": "Compendio_Extranjería",
        "name": "Compendio Extranjería",
        "description": "Compendio de extranjería",
    },
    "lineas_jurisprudenciales": {
        "slug": "Lineas_Jurisprudenciales",
        "name": "Líneas Jurisprudenciales",
        "description": "Líneas jurisprudenciales",
    },
    "salud_cs": {
        "slug": "Salud_CS",
        "name": "Salud CS",
        "description": "Salud - Corte Suprema",
    },
}

CHILE_BASE_URL = "https://juris.pjud.cl"
CHILE_SEARCH_URL = f"{CHILE_BASE_URL}/busqueda/buscar_sentencias"
CHILE_DOCUMENTOS_URL = f"{CHILE_BASE_URL}/busqueda/documentos"
CHILE_DETALLE_URL = f"{CHILE_BASE_URL}/busqueda/buscar_sentencias"


@dataclass
class SearchCriteria:
    """Search parameters for Chile Poder Judicial."""
    search_text: str = ""
    categoria: str = "civiles"                 # Category key from CHILE_CATEGORIES
    tribunal: Optional[str] = None              # Specific court name
    juez: Optional[str] = None                 # Judge name
    materia: Optional[str] = None               # Subject matter
    rol: Optional[str] = None                   # ROL or RIT number
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None
    orden: str = "recientes"                   # recientes, antiguos, rol, relevancia
    max_results: int = 20
    resultados_por_pagina: int = 20             # 10, 20, 50, 100, 250
    search_index: str = "texto_libre"
    tipo_norma: Optional[str] = None             # Optional: filter by legal code


class ChileJurisprudenciaScraper:
    """Scraper for Chile's Poder Judicial unified jurisprudence search.

    Navigates the SPA-based search interface at juris.pjud.cl, submits
    searches via AJAX, and downloads PDF documents.

    Usage:
        scraper = ChileJurisprudenciaScraper(headless=True)
        results = scraper.get_inteiro_links("daño moral", max_results=20)
    """

    def __init__(self, headless=True, wait_time=30):
        self.wait_time = wait_time
        self.driver = create_chrome_driver(headless=headless)
        self._csrf_token: Optional[str] = None
        self._categoria_actual: Optional[str] = None

    # ── Page navigation ──────────────────────────────────────────────────

    def _navigate_to_category(self, categoria: str):
        """Load the search page for a specific category."""
        cat_info = CHILE_CATEGORIES.get(categoria)
        if not cat_info:
            raise ValueError(
                f"Categoría desconocida: '{categoria}'. "
                f"Disponibles: {list(CHILE_CATEGORIES.keys())}"
            )

        if self._categoria_actual == categoria:
            return  # Already on this page

        slug = cat_info["slug"]
        url = f"{CHILE_BASE_URL}/busqueda?{slug}"
        logger.info(f"Chile: Loading category '{categoria}' -> {url}")
        self.driver.get(url)
        time.sleep(4)
        self._categoria_actual = categoria

        # Extract CSRF token
        try:
            csrf_meta = self.driver.find_element(
                By.CSS_SELECTOR, "meta[name='csrf-token']"
            )
            self._csrf_token = csrf_meta.get_attribute("content")
        except Exception:
            logger.warning("Chile: Could not extract CSRF token")
            self._csrf_token = None

    # ── Search ────────────────────────────────────────────────────────────

    def get_inteiro_links(
        self,
        query: str,
        max_results: int = 20,
        search_index: str = "texto_libre",
        filters: Optional[Dict[str, Optional[str]]] = None,
    ) -> List[Dict[str, Any]]:
        """Search Chile Poder Judicial and return result list.

        The search is performed via JavaScript interception — we inject a
        fetch to the buscar_sentencias endpoint using the page's session.
        """
        filters = filters or {}
        categoria = filters.get("categoria") or "civiles"
        self._navigate_to_category(categoria)

        entries: List[Dict[str, Any]] = []
        page = 0
        per_page = filters.get("resultados_por_pagina") or filters.get("per_page") or 20
        if isinstance(per_page, str):
            per_page = int(per_page)

        max_pages = min(50, (max_results // per_page) + 2)

        while len(entries) < max_results and page < max_pages:
            logger.info(f"Chile: Searching page {page + 1}...")

            try:
                page_results = self._search_page(
                    query=query,
                    page=page,
                    per_page=min(per_page, max_results - len(entries)),
                    categoria=categoria,
                    filters=filters,
                )

                if not page_results:
                    logger.info(f"Chile: No more results on page {page + 1}")
                    break

                for result in page_results:
                    if len(entries) >= max_results:
                        break
                    existing = {e.get("rol") for e in entries}
                    if result.get("rol") in existing:
                        continue
                    result["page"] = page + 1
                    result["categoria"] = categoria
                    result["tribunal_pais"] = "CHILE"
                    entries.append(result)

                page += 1
                time.sleep(1)

            except Exception as e:
                logger.error(f"Chile: Search error on page {page + 1}: {e}")
                break

        logger.info(f"Chile: Total results: {len(entries)}")
        return entries

    def _search_page(
        self,
        query: str,
        page: int = 0,
        per_page: int = 20,
        categoria: str = "civiles",
        filters: Optional[Dict[str, Optional[str]]] = None,
    ) -> List[Dict[str, Any]]:
        """Execute a single page search using form interaction."""
        # Note: We use the form-fill approach as primary because it works with
        # reCAPTCHA v3 (real browser interaction). The JS fetch approach is
        # blocked by CSRF + reCAPTCHA server-side validation.
        return self._search_via_form_fallback(query, page, per_page, filters)

    def _parse_search_results(
        self, html_or_json: str, query: str = ""
    ) -> List[Dict[str, Any]]:
        """Parse search results from DOM elements with data-idsentencia."""
        entries: List[Dict[str, Any]] = []

        # Primary: parse DOM elements in the browser
        try:
            result_elems = self.driver.find_elements(
                By.CSS_SELECTOR, "[data-idsentencia]"
            )
            seen_ids = set()
            for elem in result_elems:
                id_sentencia = elem.get_attribute("data-idsentencia")
                if not id_sentencia or id_sentencia in seen_ids:
                    continue
                seen_ids.add(id_sentencia)
                text = elem.text
                entry = self._parse_chile_text_result(text, id_sentencia, query)
                if entry:
                    entries.append(entry)
            if entries:
                return entries
        except Exception:
            pass

        # Fallback: parse HTML string
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_or_json, "html.parser")
        for elem in soup.select("[data-idsentencia]"):
            id_sentencia = elem.get("data-idsentencia", "")
            text = elem.get_text(" ", strip=True)
            entry = self._parse_chile_text_result(text, id_sentencia, query)
            if entry:
                entries.append(entry)
        return entries

    def _parse_chile_text_result(
        self, text: str, id_sentencia: str, query: str = ""
    ) -> Optional[Dict[str, Any]]:
        """Parse Chile result text format.

        Expected: ROL: C-1944-2025 Caratulado: MONSALVE/...
                  Fecha: 15-05-2026
                  Tribunal: 1º Juzgado de Letras de Osorno
                  Materia: PERJUICIOS, INDEMNIZACIÓN DE
                  Juez(a): Raul Fredy Ramírez López
        """
        rol = ""
        caratulado = ""
        fecha = ""
        tribunal = ""
        materia = ""
        juez = ""

        rol_match = re.search(r"ROL[:\s]*([A-Z]?[-\d]+[\d])", text, re.IGNORECASE)
        if rol_match:
            rol = rol_match.group(1).strip()

        cara_match = re.search(
            r"Caratulado[:\s]*([^\n]+?)(?:\s*(?:Fecha|Tribunal|Materia|Juez|ROL|$))",
            text, re.IGNORECASE
        )
        if cara_match:
            caratulado = cara_match.group(1).strip()

        fecha_match = re.search(
            r"Fecha[:\s]*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})", text, re.IGNORECASE
        )
        if fecha_match:
            fecha = fecha_match.group(1).strip()

        trib_match = re.search(
            r"Tribunal[:\s]*([^\n]+?)(?:\s*(?:Materia|Juez|ROL|$))",
            text, re.IGNORECASE
        )
        if trib_match:
            tribunal = trib_match.group(1).strip()

        mat_match = re.search(
            r"Materia[:\s]*([^\n]+?)(?:\s*(?:Juez|ROL|$))",
            text, re.IGNORECASE
        )
        if mat_match:
            materia = mat_match.group(1).strip()

        juez_match = re.search(
            r"Juez[\(\s]*a[\)\s]*[:\s]*([^\n]+)", text, re.IGNORECASE
        )
        if juez_match:
            juez = juez_match.group(1).strip()

        texto_preview = re.sub(r"\s+", " ", text)[:500]

        return {
            "rol": rol,
            "caratulado": caratulado,
            "fecha": fecha,
            "tribunal": tribunal,
            "materia": materia,
            "juez": juez,
            "id_sentencia": id_sentencia,
            "texto_preview": texto_preview,
            "url_detalle": CHILE_DETALLE_URL,
            "search_terms": query,
            "tribunal_pais": "CHILE",
            "court": "CL",
        }

    def _search_via_form_fallback(
        self, query: str, page: int, per_page: int,
        filters: Dict[str, Optional[str]]
    ) -> List[Dict[str, Any]]:
        """Search by filling the omnibox and clicking the Buscar button.

        Uses execute_script click to avoid reCAPTCHA interception.
        """
        try:
            if page == 0:
                omnibox = self.driver.find_element(By.ID, "tb_input_omnibox")
                if omnibox.is_displayed():
                    omnibox.clear()
                    omnibox.send_keys(query or "")
                    time.sleep(1)

                # Click the first visible Buscar button via JS (bypasses reCAPTCHA intercept)
                botones = self.driver.find_elements(
                    By.XPATH, "//button[contains(text(), 'Buscar')]"
                )
                clicked = False
                for btn in botones:
                    if btn.is_displayed():
                        self.driver.execute_script("arguments[0].click();", btn)
                        clicked = True
                        break
                if not clicked and botones:
                    self.driver.execute_script("arguments[0].click();", botones[0])

                time.sleep(15)

            # Parse results from updated page (only first page; pagination via DOM)
            html = self.driver.page_source
            entries = self._parse_search_results(html, query)

            # Apply per-page limit
            return entries[:per_page] if entries else []
        except Exception as e:
            logger.error(f"Chile: Form search failed: {e}")

        return []

    def search_with_criteria(self, criteria: SearchCriteria) -> List[Dict[str, Any]]:
        """Search using a SearchCriteria object."""
        filters = {
            "categoria": criteria.categoria,
            "tribunal": criteria.tribunal,
            "juez": criteria.juez,
            "materia": criteria.materia,
            "rol": criteria.rol,
            "fecha_inicio": criteria.fecha_inicio,
            "fecha_fin": criteria.fecha_fin,
            "orden": criteria.orden,
            "resultados_por_pagina": criteria.resultados_por_pagina,
            "tipo_norma": criteria.tipo_norma,
        }
        return self.get_inteiro_links(
            query=criteria.search_text,
            max_results=criteria.max_results,
            search_index=criteria.search_index,
            filters=filters,
        )

    # ── Download ──────────────────────────────────────────────────────────

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
        """Download a sentence document from Chile Poder Judicial."""
        if save_dir is None:
            save_dir = os.path.abspath(
                os.path.join(os.getcwd(), "workspace", "CL_jurisprudencia")
            )

        if _skip_org:
            final_save_dir = save_dir
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            folder_parts = [p for p in [agent_id, folder_name, timestamp] if p]
            final_save_dir = os.path.join(save_dir, *folder_parts)
        os.makedirs(final_save_dir, exist_ok=True)

        if metadata is None:
            metadata = {}
        metadata.update({
            "tribunal_pais": "CHILE",
            "agent_id": agent_id,
            "download_timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        })

        try:
            id_sentencia = metadata.get("id_sentencia")
            categoria = metadata.get("categoria")
            if id_sentencia and categoria:
                # Navigate to the category search page first
                self._navigate_to_category(categoria)
                time.sleep(4)

                # Fill omnibox with search terms to get results on page
                if metadata.get("search_terms"):
                    try:
                        omnibox = self.driver.find_element(By.ID, "tb_input_omnibox")
                        if omnibox.is_displayed():
                            omnibox.clear()
                            omnibox.send_keys(metadata["search_terms"] or "")
                            time.sleep(1)
                            botones = self.driver.find_elements(
                                By.XPATH, "//button[contains(text(), 'Buscar')]"
                            )
                            for btn in botones:
                                if btn.is_displayed():
                                    self.driver.execute_script("arguments[0].click();", btn)
                                    break
                            time.sleep(10)
                    except Exception:
                        pass

                # Find the specific result and click "Ver sentencia"
                try:
                    result_elems = self.driver.find_elements(
                        By.CSS_SELECTOR, "[data-idsentencia]"
                    )
                    for elem in result_elems:
                        if elem.get_attribute("data-idsentencia") == str(id_sentencia):
                            btn = elem.find_element(
                                By.XPATH, ".//button[contains(text(), 'Ver sentencia')]"
                            )
                            self.driver.execute_script("arguments[0].click();", btn)
                            time.sleep(8)
                            break
                except Exception:
                    pass

                content = self.driver.page_source.encode("utf-8")
                ext = "html"

                # Click "Volver"
                try:
                    back_btns = self.driver.find_elements(
                        By.PARTIAL_LINK_TEXT, "Volver a la página de búsqueda"
                    )
                    if back_btns:
                        self.driver.execute_script("arguments[0].click();", back_btns[0])
                        time.sleep(3)
                except Exception:
                    pass
            else:
                # No ID — save current page
                self.driver.get(url or CHILE_BASE_URL + "/busqueda?Civiles")
                time.sleep(3)
                content = self.driver.page_source.encode("utf-8")
                ext = "html"

            if not filename:
                rol = metadata.get("rol") or id_sentencia or "unknown"
                filename = f"sentencia_{rol}.{ext}"

            filepath = os.path.join(final_save_dir, filename)
            with open(filepath, "wb") as f:
                f.write(content)

            sidecar = {
                "downloaded_at": datetime.utcnow().isoformat() + "Z",
                "source_url": url,
                "tribunal_pais": "CHILE",
                "file_size_bytes": len(content),
            }
            sidecar.update(metadata)
            write_sidecar_metadata(filepath, sidecar)

            return filepath
        except Exception as e:
            logger.error(f"Chile: Download failed: {e}")
            return None

    def download_all_inteiro_teor(
        self,
        results: List[Dict[str, Any]],
        save_dir: Optional[str] = None,
        overwrite: bool = False,
        delay: float = 0.5,
        agent_id: Optional[str] = None,
        folder_name: Optional[str] = None,
        search_params: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Download all results."""
        if save_dir is None:
            save_dir = os.path.abspath(
                os.path.join(os.getcwd(), "workspace", "CL_jurisprudencia")
            )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_parts = [p for p in [agent_id, folder_name, timestamp] if p]
        final_save_dir = os.path.join(save_dir, *folder_parts)
        os.makedirs(final_save_dir, exist_ok=True)

        saved_files = []
        for idx, res in enumerate(results, 1):
            url = res.get("url_detalle") or res.get("url_pdf") or ""
            rol = res.get("rol") or "unknown"
            logger.info(f"Chile: Downloading ({idx}/{len(results)}): {rol}")
            saved = self.download_inteiro_teor_url(
                url,
                save_dir=final_save_dir,
                metadata={
                    "rol": rol,
                    "caratulado": res.get("caratulado"),
                    "tribunal": res.get("tribunal"),
                    "tribunal_pais": "CHILE",
                    "id_sentencia": res.get("id_sentencia"),
                    "categoria": res.get("categoria"),
                    "search_terms": res.get("search_terms"),
                    "agent_id": agent_id,
                    "search_params": search_params,
                },
                _skip_org=True,
            )
            if saved:
                saved_files.append(saved)
            if delay and idx < len(results):
                time.sleep(delay)
        return saved_files

    def canonicalize_inteiro_url(
        self, raw_url: str, fallback_num: Optional[str] = None
    ) -> Dict[str, Optional[str]]:
        """Normalize a Chile jurisprudence URL."""
        raw = (raw_url or "").strip()
        rol = fallback_num
        if not rol:
            rol_match = re.search(r"rol[=:\s]*([\d\-]+)", raw, re.IGNORECASE)
            if rol_match:
                rol = rol_match.group(1)

        return {
            "source_url": raw,
            "url": raw,
            "rol": rol,
            "tribunal_pais": "CHILE",
            "is_canonical": True,
        }

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def close(self):
        if self.driver:
            self.driver.quit()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
