"""
Chile Poder Judicial — Jurisprudence Scraper.

Scrapes the "Buscador Unificado de Fallos del Poder Judicial" at
https://juris.pjud.cl — Chile's unified judicial rulings search portal.

Architecture (see docs/pjud-source.md for full reverse-engineering):
  - Laravel Blade shell + jQuery/AJAX SPA. Each section sets
    window.id_buscador_activo; that numeric id is the *required* key for every
    search request. See CHILE_CATEGORIES below.
  - Anti-bot stack is TWO layers:
      (1) F5 BIG-IP ASM / TSPD — JS challenge + image CAPTCHA, guards the whole
          pjud.cl domain family. POSTs to /busqueda/buscar_sentencias are
          rejected with HTTP **200** and body "La URL solicitada ha sido
          rechazada" (header x-security-action: 0800000200).
      (2) Google reCAPTCHA v3, site key 6Lf5adcZ..., validated server-side.
    Because of (1)+(2), plain requests / direct fetch() is impossible.
    The working strategy is to drive a real Chrome session and click the UI
    button instead of calling the AJAX endpoint directly.
  - Results are read from the DOM: elements carrying [data-idsentencia].
  - Document download re-drives the browser (the POST path is F5-blocked).

Usage:
    scraper = ChileJurisprudenciaScraper(headless=True)
    results = scraper.get_inteiro_links("daño moral", max_results=20)
"""

import os
import re
import time
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any
from urllib.parse import quote

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from _shared.chrome_driver import (
    create_chrome_driver,
    write_sidecar_metadata,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ── Chile Search Categories ──────────────────────────────────────────────────
#
# `id_buscador` is REQUIRED for every search. Values verified live 2026-09-13
# (see docs/pjud-source.md §4). `tipo_instancia_principal` is a second axis
# independent of id_buscador (e.g. Salud_CS -> corte_suprema).

CHILE_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "corte_suprema": {
        "slug": "Corte_Suprema",
        "name": "Corte Suprema",
        "id_buscador": 528,
        "tipo_instancia_principal": "corte_suprema",
        "es_lj": False,
        "description": "Fallos de la Corte Suprema de Chile",
    },
    "corte_apelaciones": {
        "slug": "Corte_de_Apelaciones",
        "name": "Corte de Apelaciones",
        "id_buscador": 168,
        "tipo_instancia_principal": "corte_apelaciones",
        "es_lj": False,
        "description": "Fallos de las Cortes de Apelaciones",
    },
    "civiles": {
        "slug": "Civiles",
        "name": "Civiles",
        "id_buscador": 328,
        "tipo_instancia_principal": "civil",
        "es_lj": False,
        "description": "Jurisprudencia civil",
    },
    "penales": {
        "slug": "Penales",
        "name": "Penales",
        "id_buscador": 268,
        "tipo_instancia_principal": "penal",
        "es_lj": False,
        "description": "Jurisprudencia penal",
    },
    "laborales": {
        "slug": "Laborales",
        "name": "Laborales",
        "id_buscador": 271,
        "tipo_instancia_principal": "laboral",
        "es_lj": False,
        "description": "Jurisprudencia laboral",
    },
    "familia": {
        "slug": "Familia",
        "name": "Familia",
        "id_buscador": 270,
        "tipo_instancia_principal": "familia",
        "es_lj": False,
        "description": "Jurisprudencia de familia",
    },
    "cobranza": {
        "slug": "Cobranza",
        "name": "Cobranza",
        "id_buscador": 269,
        "tipo_instancia_principal": "cobranza",
        "es_lj": False,
        "description": "Jurisprudencia de cobranza",
    },
    "compendio_extranjeria": {
        # NOTE: id_buscador UNVERIFIED — F5 blocked recon (§11 item 1). When a
        # clean session is available, load the section and read
        # `window.id_buscador_activo` to fill this in.
        "slug": "Compendio_Extranjería",
        "name": "Compendio Extranjería",
        "id_buscador": None,
        "tipo_instancia_principal": None,
        "es_lj": False,
        "description": "Compendio de extranjería",
    },
    "lineas_jurisprudenciales": {
        "slug": "Lineas_Jurisprudenciales",
        "name": "Líneas Jurisprudenciales",
        "id_buscador": 628,
        "tipo_instancia_principal": "corte_suprema",
        "es_lj": True,   # sets window.es_lj = true; own faceting model
        "description": "Líneas jurisprudenciales",
    },
    "salud_cs": {
        "slug": "Salud_CS",
        "name": "Salud CS",
        "id_buscador": 127,
        "tipo_instancia_principal": "corte_suprema",
        "es_lj": False,
        "description": "Salud - Corte Suprema",
    },
}

CHILE_BASE_URL = "https://juris.pjud.cl"

# F5 block signatures (docs/pjud-source.md §1)
_F5_BODY_MARKERS = (
    "La URL solicitada ha sido rechazada",
    "Su numero de soporte",
    "Su número de soporte",
    "human visitor",
    "What code is in the image",
)


@dataclass
class SearchCriteria:
    """Search parameters for Chile Poder Judicial."""
    search_text: str = ""
    categoria: str = "civiles"
    tribunal: Optional[str] = None
    juez: Optional[str] = None
    materia: Optional[str] = None
    rol: Optional[str] = None
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None
    orden: str = "recientes"
    max_results: int = 20
    resultados_por_pagina: int = 20     # see §6: config exposes "10-20-50"
    search_index: str = "texto_libre"
    tipo_norma: Optional[str] = None


class ChileJurisprudenciaScraper:
    """Scraper for Chile's Poder Judicial unified jurisprudence search."""

    def __init__(self, headless=True, wait_time=30):
        self.wait_time = wait_time
        self.driver = create_chrome_driver(headless=headless)
        self._csrf_token: Optional[str] = None
        self._categoria_actual: Optional[str] = None

    # ── F5 detection ─────────────────────────────────────────────────────

    @staticmethod
    def _is_f5_block(page_source: str) -> bool:
        """Return True if the page body looks like an F5 rejection.

        F5 responses are HTTP 200 with a `<title>La URL solicitada ha sido
        rechazada</title>` body — easily mistaken for "no results".
        """
        if not page_source:
            return False
        return any(m in page_source for m in _F5_BODY_MARKERS)

    def _assert_not_blocked(self, context: str = ""):
        if self._is_f5_block(self.driver.page_source):
            support_id = self._extract_support_id(self.driver.page_source)
            raise RuntimeError(
                f"Chile: F5 block detected{' while ' + context if context else ''}. "
                f"support_id={support_id or 'n/a'}. "
                f"Manual CAPTCHA solve in a real browser may be required."
            )

    @staticmethod
    def _extract_support_id(html: str) -> Optional[str]:
        m = re.search(r"soporte es\s*:?\s*(\d+)", html, re.IGNORECASE)
        return m.group(1) if m else None

    # ── Page navigation ──────────────────────────────────────────────────

    def _navigate_to_category(self, categoria: str, force: bool = False) -> int:
        """Load the search page for a category. Returns the expected id_buscador."""
        cat_info = CHILE_CATEGORIES.get(categoria)
        if not cat_info:
            raise ValueError(
                f"Categoría desconocida: '{categoria}'. "
                f"Disponibles: {list(CHILE_CATEGORIES.keys())}"
            )
        if cat_info["id_buscador"] is None:
            raise ValueError(
                f"Categoría '{categoria}' has no verified id_buscador. "
                f"See docs/pjud-source.md §11 item 1."
            )

        expected_id = str(cat_info["id_buscador"])

        # Guard: skip only if the live page confirms the expected section.
        if not force and self._categoria_actual == categoria:
            try:
                live_id = self.driver.execute_script("return window.id_buscador_activo;")
                if live_id is not None and str(live_id) == expected_id:
                    return cat_info["id_buscador"]
            except Exception:
                pass  # page state broken — fall through to re-navigate

        slug = quote(cat_info["slug"], safe="")
        url = f"{CHILE_BASE_URL}/busqueda?{slug}"
        logger.info(f"Chile: Loading category '{categoria}' -> {url}")
        self.driver.get(url)

        # Wait for section config to attach (id_buscador_activo is set inline).
        try:
            WebDriverWait(self.driver, self.wait_time).until(
                lambda d: d.execute_script(
                    "return (typeof window.id_buscador_activo !== 'undefined') "
                    "? window.id_buscador_activo : null;"
                ) is not None
            )
        except Exception:
            pass

        self._assert_not_blocked(context=f"loading {categoria}")

        # Verify id matches expectation.
        try:
            live_id = self.driver.execute_script("return window.id_buscador_activo;")
            if live_id is not None and str(live_id) != expected_id:
                logger.warning(
                    f"Chile: id_buscador mismatch on {categoria}: "
                    f"expected {expected_id}, got {live_id}. "
                    f"Proceeding with config value."
                )
        except Exception:
            pass

        self._categoria_actual = categoria

        # Extract CSRF token (needed only if we ever POST directly).
        try:
            csrf_meta = self.driver.find_element(
                By.CSS_SELECTOR, "meta[name='csrf-token']"
            )
            self._csrf_token = csrf_meta.get_attribute("content")
        except Exception:
            logger.warning("Chile: Could not extract CSRF token")
            self._csrf_token = None

        return cat_info["id_buscador"]

    # ── Search ───────────────────────────────────────────────────────────

    def get_inteiro_links(
        self,
        query: str,
        max_results: int = 20,
        search_index: str = "texto_libre",
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search Chile Poder Judicial and return the result list."""
        filters = filters or {}
        categoria = filters.get("categoria") or "civiles"
        cat_info = CHILE_CATEGORIES.get(categoria) or {}
        id_buscador = self._navigate_to_category(categoria)

        per_page = filters.get("resultados_por_pagina") or filters.get("per_page") or 20
        if isinstance(per_page, str):
            per_page = int(per_page)

        entries: List[Dict[str, Any]] = []
        seen_ids: set = set()
        page = 1  # 1-indexed for logging / result["page"]

        # Hard cap so a broken pager can't spin forever.
        max_pages = max(1, (max_results // per_page) + 2)

        # ── Page 1: run the search via UI ────────────────────────────────
        self._run_search_ui(query)
        self._wait_for_results()

        while len(entries) < max_results and page <= max_pages:
            page_entries = self._parse_search_results(query, id_buscador, cat_info)

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
                # Either the pager is done or F5 ate the page.
                self._assert_not_blocked(context=f"page {page} parse")
                logger.info("Chile: no new results — stopping.")
                break

            if not self._click_next_page():
                logger.info("Chile: no next-page control — stopping.")
                break

            page += 1
            self._wait_for_results()
            time.sleep(0.5)  # small human-like gap

        logger.info(f"Chile: total results: {len(entries)}")
        return entries

    def _run_search_ui(self, query: str):
        """Fill the omnibox and click Buscar. Idempotent for empty queries."""
        try:
            omnibox = self.driver.find_element(By.ID, "tb_input_omnibox")
            if omnibox.is_displayed():
                omnibox.clear()
                if query:
                    # NOTE: sending keys is required — assigning .value leaves
                    # the component's internal state empty (docs §5.2 quirk).
                    omnibox.send_keys(query)
                    time.sleep(0.5)
        except Exception as e:
            logger.warning(f"Chile: omnibox interaction failed: {e}")

        clicked = False
        try:
            botones = self.driver.find_elements(
                By.XPATH, "//button[contains(@class,'btn_buscar') or "
                          "contains(text(), 'Buscar')]"
            )
            for btn in botones:
                if btn.is_displayed():
                    # execute_script click bypasses the #capa_carga overlay
                    # and reCAPTCHA click interception.
                    self.driver.execute_script("arguments[0].click();", btn)
                    clicked = True
                    break
            if not clicked and botones:
                self.driver.execute_script("arguments[0].click();", botones[0])
                clicked = True
        except Exception as e:
            logger.error(f"Chile: Buscar click failed: {e}")

        if not clicked:
            raise RuntimeError("Chile: could not locate Buscar button")

    def _wait_for_results(self, timeout: Optional[int] = None):
        """Poll until result rows appear, an explicit 'no results' state, or timeout."""
        timeout = timeout or self.wait_time

        def _ready(d):
            # F5 rejection page — bail immediately.
            src = d.page_source
            if self._is_f5_block(src):
                return True
            # Results present?
            if d.find_elements(By.CSS_SELECTOR, "[data-idsentencia]"):
                return True
            return False

        try:
            WebDriverWait(self.driver, timeout).until(_ready)
        except Exception:
            logger.warning("Chile: timed out waiting for results")

        self._assert_not_blocked(context="waiting for results")

    def _click_next_page(self) -> bool:
        """Click the pager's 'next' control. Returns True on click.

        The portal does NOT use DataTables: the pager is Bootstrap 4 markup with
        stable ids inside #paginador_top. Verified live against
        https://juris.pjud.cl/busqueda?Civiles — clicking
        #btnPaginador_pagina_adelante advances the JS page cursor
        (pagina_resultados_busqueda_sentencias 0 -> 1). This markup is NOT yet
        recorded in docs/pjud-source.md §7.1 (which covers result rows only);
        the paging *parameters* it corresponds to are in §6.
        The DataTables selectors are kept only as fallbacks for the
        /busqueda/imprimir view, which is unprobed (§11).
        """
        selectors = (
            # Verified live — Bootstrap 4 pager. Must stay first.
            "#btnPaginador_pagina_adelante",
            "#paginador_top a.page-link#btnPaginador_pagina_adelante",
            # Unprobed fallbacks (print view).
            "a.paginate_button.next:not(.disabled)",
            "li.next:not(.disabled) a",
            ".dataTables_paginate .next:not(.disabled)",
            "button.paginate_button.next:not(.disabled)",
            "//a[contains(@class,'next') and not(contains(@class,'disabled'))]",
        )
        for sel in selectors:
            try:
                if sel.startswith("//"):
                    btns = self.driver.find_elements(By.XPATH, sel)
                else:
                    btns = self.driver.find_elements(By.CSS_SELECTOR, sel)
                for btn in btns:
                    if btn.is_displayed() and btn.is_enabled():
                        self.driver.execute_script("arguments[0].click();", btn)
                        return True
            except Exception:
                continue
        return False

    def _parse_search_results(
        self,
        query: str,
        id_buscador: Optional[int],
        cat_info: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Read [data-idsentencia] rows from the current DOM."""
        entries: List[Dict[str, Any]] = []
        try:
            elems = self.driver.find_elements(By.CSS_SELECTOR, "[data-idsentencia]")
        except Exception:
            return entries

        for elem in elems:
            id_sentencia = elem.get_attribute("data-idsentencia")
            if not id_sentencia:
                continue
            try:
                text = elem.text
            except Exception:
                continue
            entry = self._parse_chile_text_result(
                text, id_sentencia, query,
                id_buscador=id_buscador,
                tipo_instancia=(cat_info or {}).get("tipo_instancia_principal"),
                slug=(cat_info or {}).get("slug"),
            )
            if entry:
                entries.append(entry)
        return entries

    def _parse_chile_text_result(
        self,
        text: str,
        id_sentencia: str,
        query: str = "",
        id_buscador: Optional[int] = None,
        tipo_instancia: Optional[str] = None,
        slug: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Parse a Chile result card.

        Expected layout (docs §7.1):
            ROL: C-1944-2025
            Caratulado: MONSALVE/...
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

        m = re.search(r"ROL[:\s]*([A-Z]?[-\d]+[\d])", text, re.IGNORECASE)
        if m:
            rol = m.group(1).strip()

        m = re.search(
            r"Caratulado[:\s]*([^\n]+?)(?:\s*(?:Fecha|Tribunal|Materia|Juez|ROL|$))",
            text, re.IGNORECASE,
        )
        if m:
            caratulado = m.group(1).strip()

        m = re.search(r"Fecha[:\s]*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})", text, re.IGNORECASE)
        if m:
            fecha = m.group(1).strip()

        m = re.search(
            r"Tribunal[:\s]*([^\n]+?)(?:\s*(?:Materia|Juez|ROL|$))",
            text, re.IGNORECASE,
        )
        if m:
            tribunal = m.group(1).strip()

        m = re.search(
            r"Materia[:\s]*([^\n]+?)(?:\s*(?:Juez|ROL|$))",
            text, re.IGNORECASE,
        )
        if m:
            materia = m.group(1).strip()

        m = re.search(r"Juez[\(\s]*a[\)\s]*[:\s]*([^\n]+)", text, re.IGNORECASE)
        if m:
            juez = m.group(1).strip()

        # Provisional deep-link hint. There is no verified per-sentence URL
        # format; consumers should treat this as an *identifier*, not a fetch
        # target. See docs §11 open question on /busqueda/imprimir.
        url_detalle = (
            f"{CHILE_BASE_URL}/busqueda?{quote(slug, safe='')}#id_sentencia={id_sentencia}"
            if slug else None
        )

        return {
            "rol": rol,
            "caratulado": caratulado,
            "fecha": fecha,
            "tribunal": tribunal,
            "materia": materia,
            "juez": juez,
            "id_sentencia": id_sentencia,
            "id_buscador": id_buscador,
            "instancia": tipo_instancia,
            "texto_preview": re.sub(r"\s+", " ", text)[:500],
            "url_detalle": url_detalle,
            "search_terms": query,
            "tribunal_pais": "CHILE",
            "court": "CL",
        }

    def search_with_criteria(self, criteria: SearchCriteria) -> List[Dict[str, Any]]:
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

    # ── Download ─────────────────────────────────────────────────────────

    def _open_detail(self, result: Dict[str, Any]) -> bool:
        """Navigate to the right results page and click 'Ver sentencia'.

        Uses the stored `page` and `search_terms` from the search phase so we
        don't have to guess. Returns True on successful click.
        """
        categoria = result.get("categoria")
        id_sentencia = result.get("id_sentencia")
        target_page = int(result.get("page") or 1)

        if not (categoria and id_sentencia):
            return False

        self._navigate_to_category(categoria)
        self._run_search_ui(result.get("search_terms") or "")
        self._wait_for_results()

        # Advance to the page where this result was found.
        for _ in range(target_page - 1):
            if not self._click_next_page():
                break
            self._wait_for_results()
            time.sleep(0.3)

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
                        self._wait_for_results(timeout=self.wait_time)
                        return True
        except Exception as e:
            logger.error(f"Chile: detail click failed: {e}")

        return False

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
        """Download a sentence document (as .html) from Chile Poder Judicial."""
        if save_dir is None:
            save_dir = os.path.abspath(
                os.path.join(os.getcwd(), "workspace", "CL_jurisprudencia")
            )

        if _skip_org:
            final_save_dir = save_dir
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            parts = [p for p in [agent_id, folder_name, timestamp] if p]
            final_save_dir = os.path.join(save_dir, *parts)
        os.makedirs(final_save_dir, exist_ok=True)

        metadata = metadata or {}
        metadata.update({
            "tribunal_pais": "CHILE",
            "agent_id": agent_id,
            "download_timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        })

        try:
            opened = self._open_detail(metadata)
            if not opened:
                logger.warning(
                    f"Chile: could not open detail for "
                    f"id_sentencia={metadata.get('id_sentencia')}"
                )
                return None

            self._assert_not_blocked(context="opening detail")
            content = self.driver.page_source.encode("utf-8")
            ext = "html"

            # Best-effort "go back".
            try:
                back = self.driver.find_elements(
                    By.PARTIAL_LINK_TEXT, "Volver a la página de búsqueda"
                )
                if back:
                    self.driver.execute_script("arguments[0].click();", back[0])
                    time.sleep(1)
            except Exception:
                pass

            if not filename:
                rol = metadata.get("rol") or metadata.get("id_sentencia") or "unknown"
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
        if save_dir is None:
            save_dir = os.path.abspath(
                os.path.join(os.getcwd(), "workspace", "CL_jurisprudencia")
            )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        parts = [p for p in [agent_id, folder_name, timestamp] if p]
        final_save_dir = os.path.join(save_dir, *parts)
        os.makedirs(final_save_dir, exist_ok=True)

        # Group by (categoria, page) so we only navigate per page, not per doc.
        saved_files: List[str] = []
        for idx, res in enumerate(results, 1):
            rol = res.get("rol") or "unknown"
            logger.info(f"Chile: Downloading ({idx}/{len(results)}): {rol}")
            saved = self.download_inteiro_teor_url(
                res.get("url_detalle") or "",
                save_dir=final_save_dir,
                metadata={
                    "rol": rol,
                    "caratulado": res.get("caratulado"),
                    "tribunal": res.get("tribunal"),
                    "tribunal_pais": "CHILE",
                    "id_sentencia": res.get("id_sentencia"),
                    "id_buscador": res.get("id_buscador"),
                    "instancia": res.get("instancia"),
                    "categoria": res.get("categoria"),
                    "search_terms": res.get("search_terms"),
                    "page": res.get("page"),
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
        raw = (raw_url or "").strip()
        rol = fallback_num
        if not rol:
            m = re.search(r"rol[=:\s]*([\d\-]+)", raw, re.IGNORECASE)
            if m:
                rol = m.group(1)
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