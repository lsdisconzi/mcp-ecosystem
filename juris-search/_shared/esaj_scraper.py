"""
Generic e-SAJ CJSG Jurisprudence Scraper.

Parameterized scraper for any Brazilian Tribunal de Justiça that uses the
Softplan e-SAJ CJSG (Consulta de Julgados de Segundo Grau) system.

Covers ~22 courts with a single codebase. Court-specific variations are
configured in _shared/esaj_config.py.

Usage:
    from _shared.esaj_config import ESAJ_COURTS
    from _shared.esaj_scraper import EsajJurisprudenciaScraper

    scraper = EsajJurisprudenciaScraper("TJSC", headless=True)
    results = scraper.get_inteiro_links("dano moral", max_results=20)
"""

import os
import re
import time
import json
import logging
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

from _shared.chrome_driver import (
    create_chrome_driver,
    write_sidecar_metadata,
    infer_extension,
)
from _shared.esaj_config import (
    EsajCourtConfig,
    get_esaj_config,
    is_esaj_court,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class SearchCriteria:
    """Search parameters — identical interface across all scrapers."""
    search_text: str = ""
    tribunal: Optional[str] = None
    orgao_julgador: Optional[str] = None
    relator: Optional[str] = None
    tipo_processo: Optional[str] = None
    classe_cnj: Optional[str] = None
    assunto_cnj: Optional[str] = None
    comarca_origem: Optional[str] = None
    tipo_decisao: Optional[str] = None
    data_julgamento_inicio: Optional[str] = None
    data_julgamento_fim: Optional[str] = None
    data_publicacao_inicio: Optional[str] = None
    data_publicacao_fim: Optional[str] = None
    search_index: str = "ementa"
    max_results: int = 20


# ── Default form field names (standardized across e-SAJ) ─────────────────────

DEFAULT_FORM_FIELDS = {
    "conversationId": "",
    "dados.buscaInteiroTeor": "",
    "dados.pesquisarComSinonimos": "S",
    "contadoragente": "0",
    "contadorMaioragente": "0",
    "contadorjuizProlator": "0",
    "contadorMaiorjuizProlator": "0",
    "classesTreeSelection.values": "",
    "assuntosTreeSelection.values": "",
    "contadorcomarca": "0",
    "contadorMaiorcomarca": "0",
    "secoesTreeSelection.values": "",
    "dados.dtJulgamentoInicio": "",
    "dados.dtJulgamentoFim": "",
    "dados.dtRegistroInicio": "",
    "dados.dtRegistroFim": "",
    "dados.dtPublicacaoInicio": "",
    "dados.dtPublicacaoFim": "",
    "dados.origensSelecionadas": "T",      # 2º grau
    "tipoDecisaoSelecionados": "A",         # default: Acórdãos
    "dados.ordenarPor": "dtPublicacao",
}


class EsajJurisprudenciaScraper:
    """Generic scraper for any e-SAJ CJSG-based Brazilian TJ.

    Uses Selenium to POST the search form, navigate pagination,
    parse .fundocinza1 result blocks, and download inteiro teor documents.
    """

    def __init__(self, court_key: str = "TJSP", headless: bool = True, wait_time: int = 30):
        if not is_esaj_court(court_key):
            raise ValueError(
                f"'{court_key}' is not a configured e-SAJ court. "
                f"Available: {list_esaj_courts_simple()}"
            )

        self.court_key = court_key.upper()
        self.config: EsajCourtConfig = get_esaj_config(self.court_key)
        self.wait_time = wait_time
        self.driver = create_chrome_driver(headless=headless)
        self._session: Optional[requests.Session] = None

        logger.info(f"e-SAJ scraper initialized for {self.court_key} ({self.config.name})")

    # ── Internal helpers ──────────────────────────────────────────────────

    def _resolve_tipo_decisao(self, tipo: Optional[str]) -> str:
        if not tipo:
            return "A"
        key = tipo.strip().lower()
        return self.config.tipo_decisao_map.get(key, "A")

    @staticmethod
    def _format_date_for_esaj(date_str: Optional[str]) -> str:
        """Convert various date formats to dd/mm/aaaa for e-SAJ forms."""
        if not date_str:
            return ""
        date_str = date_str.strip()
        if re.match(r"^\d{2}/\d{2}/\d{4}$", date_str):
            return date_str
        iso_match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", date_str)
        if iso_match:
            return f"{iso_match.group(3)}/{iso_match.group(2)}/{iso_match.group(1)}"
        short_match = re.match(r"^(\d{2})/(\d{2})/(\d{2})$", date_str)
        if short_match:
            return f"{short_match.group(1)}/{short_match.group(2)}/20{short_match.group(3)}"
        return date_str

    def _build_search_form_data(
        self, query: str, filters: Optional[Dict[str, Optional[str]]] = None
    ) -> Dict[str, str]:
        """Build POST form data for e-SAJ CJSG search, applying court overrides."""
        filters = filters or {}
        data = dict(DEFAULT_FORM_FIELDS)
        data.update(self.config.form_field_overrides)

        data["dados.buscaInteiroTeor"] = query or ""
        data["dados.dtJulgamentoInicio"] = self._format_date_for_esaj(
            filters.get("data_julgamento_inicio") or filters.get("dtJulgamentoInicio")
        )
        data["dados.dtJulgamentoFim"] = self._format_date_for_esaj(
            filters.get("data_julgamento_fim") or filters.get("dtJulgamentoFim")
        )
        data["dados.dtPublicacaoInicio"] = self._format_date_for_esaj(
            filters.get("data_publicacao_inicio") or filters.get("dtPublicacaoInicio")
        )
        data["dados.dtPublicacaoFim"] = self._format_date_for_esaj(
            filters.get("data_publicacao_fim") or filters.get("dtPublicacaoFim")
        )
        data["tipoDecisaoSelecionados"] = self._resolve_tipo_decisao(
            filters.get("tipo_decisao")
        )
        return data

    @staticmethod
    def _normalize_metadata_key(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-z0-9]+", "_", ascii_only.lower()).strip("_")

    @staticmethod
    def _split_classe_assunto(value: str) -> Tuple[str, str]:
        raw = str(value or "").strip()
        if not raw:
            return "", ""
        separators = sorted(
            [" / ", " - ", " | ", ";", "/", "-"],
            key=lambda s: len(s), reverse=True,
        )
        for separator in separators:
            if separator in raw:
                left, right = raw.split(separator, 1)
                return left.strip(), right.strip()
        return raw, ""

    def _pick_metadata(self, metadata: Dict[str, str], keys: List[str]) -> str:
        """Pick the first non-empty value from a list of possible metadata keys."""
        for key in keys:
            val = metadata.get(key, "").strip()
            if val:
                return val
        return ""

    def _build_inteiro_url(self, cdacordao: str) -> Optional[str]:
        """Build the inteiro teor download URL for a cdAcordao."""
        if not cdacordao:
            return None
        return f"{self.config.download_url}?cdAcordao={cdacordao}&cdForo=0"

    # ── Result parsing ────────────────────────────────────────────────────

    def _parse_result_block(self, block) -> Optional[Dict[str, Any]]:
        """Parse a single .fundocinza1 result block into a normalized dict."""
        try:
            html = block.get_attribute("innerHTML")
            soup = BeautifulSoup(html, "html.parser")
            entry: Dict[str, Any] = {}

            # Download link with cdacordao
            download_link = soup.select_one(self.config.download_link_selector)
            if download_link:
                entry["cdacordao"] = download_link.get("cdacordao", "")
                entry["numero_processo"] = download_link.get_text(strip=True)
            else:
                entry["cdacordao"] = ""
                entry["numero_processo"] = ""

            # Class and subject
            assunto_classe = soup.select_one(self.config.assunto_classe_selector)
            if assunto_classe:
                entry["classe_assunto"] = assunto_classe.get_text(strip=True)
            else:
                entry["classe_assunto"] = ""
            classe_cnj, assunto_cnj = self._split_classe_assunto(entry["classe_assunto"])
            entry["classe_cnj"] = classe_cnj
            entry["assunto_cnj"] = assunto_cnj

            # Metadata fields from .ementaClass2 spans
            metadata: Dict[str, str] = {}
            for span in soup.select(self.config.metadata_selector):
                text = span.get_text(strip=True)
                if ":" in text:
                    key, _, value = text.partition(":")
                    key_norm = self._normalize_metadata_key(key)
                    metadata[key_norm] = value.strip()

            entry["comarca_origem"] = self._pick_metadata(metadata, self.config.comarca_label_keys)
            entry["orgao_julgador"] = self._pick_metadata(metadata, self.config.orgao_label_keys)
            entry["data_julgamento"] = self._pick_metadata(metadata, self.config.data_julgamento_keys)
            entry["data_publicacao"] = self._pick_metadata(metadata, self.config.data_publicacao_keys)
            entry["data_registro"] = self._pick_metadata(metadata, self.config.data_registro_keys)
            entry["relator"] = self._pick_metadata(metadata, self.config.relator_label_keys)
            entry["tipo_processo"] = (
                metadata.get("tipo_processo", "")
                or metadata.get("tipo_de_processo", "")
                or entry["classe_cnj"]
            )
            entry["tribunal"] = self.court_key

            # Ementa: try configured selectors in order
            ementa = ""
            for selector in self.config.ementa_selectors:
                if selector == "textarea":
                    textarea = soup.select_one("textarea")
                    if textarea:
                        ementa = textarea.get_text(strip=True)
                else:
                    ementa_el = soup.select_one(selector)
                    if ementa_el:
                        for meta_span in ementa_el.select(self.config.metadata_selector):
                            meta_span.decompose()
                        ementa = ementa_el.get_text(" ", strip=True)
                if ementa:
                    break

            if not ementa:
                for candidate in soup.select("span, div, p"):
                    ctext = candidate.get_text(strip=True)
                    upper = ctext.upper()
                    if (
                        len(ctext) > 80
                        and any(kw in upper for kw in (
                            "APELAÇÃO", "APELACAO", "RECURSO", "INDENIZ",
                            "DANO", "RESPONSABILIDADE", "AGRAVO", "EMBARGOS",
                        ))
                        and candidate.name not in ("html", "body")
                    ):
                        ementa = ctext
                        break

            entry["ementa_trecho"] = re.sub(r"\s+", " ", ementa).strip()[:500]

            # Build download URL
            cdacordao = entry.get("cdacordao", "")
            entry["inteiro_url"] = self._build_inteiro_url(cdacordao)
            entry["download_id"] = cdacordao or None

            return entry
        except Exception as e:
            logger.debug(f"[{self.court_key}] Error parsing result block: {e}")
            return None

    # ── Search ────────────────────────────────────────────────────────────

    def get_inteiro_links(
        self,
        query: str,
        max_results: int = 20,
        search_index: str = "ementa",
        filters: Optional[Dict[str, Optional[str]]] = None,
    ) -> List[Dict[str, Any]]:
        """Search e-SAJ CJSG and return list of result dicts with inteiro teor URLs."""
        filters = filters or {}
        tipo_decisao = self._resolve_tipo_decisao(filters.get("tipo_decisao"))
        search_url = self.config.search_url

        logger.info(f"[{self.court_key}] Loading search page: {search_url}")

        self.driver.get(search_url)
        time.sleep(2)

        # Fill and submit the search form
        form_data = self._build_search_form_data(query, filters)
        logger.info(
            f"[{self.court_key}] Submitting search: query='{query}', "
            f"tipo_decisao={tipo_decisao}"
        )

        try:
            for field_name, field_value in form_data.items():
                if not field_value:
                    continue
                try:
                    elem = self.driver.find_element(By.NAME, field_name)
                    if elem.is_displayed() and elem.is_enabled():
                        elem.clear()
                        elem.send_keys(str(field_value))
                except Exception:
                    pass

            submit_selectors = [
                "//input[@value='Pesquisar']",
                "//button[contains(text(), 'Pesquisar')]",
                "//input[@type='submit']",
                "//button[@type='submit']",
            ]
            submitted = False
            for selector in submit_selectors:
                try:
                    btn = self.driver.find_element(By.XPATH, selector)
                    if btn.is_displayed():
                        btn.click()
                        submitted = True
                        break
                except Exception:
                    continue

            if not submitted:
                self.driver.execute_script("document.forms[0].submit()")

        except Exception as e:
            logger.warning(f"[{self.court_key}] Form fill failed: {e}, trying direct POST")
            try:
                cookies = self.driver.get_cookies()
                session = requests.Session()
                for cookie in cookies:
                    session.cookies.set(cookie["name"], cookie["value"])
                resp = session.post(search_url, data=form_data, timeout=30)
                self.driver.get(search_url)
                self.driver.execute_script(
                    f"document.open(); document.write({json.dumps(resp.text)}); document.close();"
                )
            except Exception as e2:
                logger.error(f"[{self.court_key}] Direct POST fallback also failed: {e2}")

        time.sleep(3)

        entries: List[Dict[str, Any]] = []
        page_num = 1
        max_pages = 50

        try:
            while len(entries) < max_results and page_num <= max_pages:
                logger.info(f"[{self.court_key}] Processing page {page_num}...")

                try:
                    WebDriverWait(self.driver, self.wait_time).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, self.config.result_block_selector)
                        )
                    )
                except Exception:
                    logger.warning(f"[{self.court_key}] No results on page {page_num}")
                    break

                time.sleep(2)

                result_blocks = self.driver.find_elements(
                    By.CSS_SELECTOR, self.config.result_block_selector
                )
                logger.info(
                    f"[{self.court_key}] Found {len(result_blocks)} result blocks "
                    f"on page {page_num}"
                )

                for block in result_blocks:
                    if len(entries) >= max_results:
                        break
                    entry = self._parse_result_block(block)
                    if entry and entry.get("numero_processo"):
                        existing_nums = {e.get("numero_processo") for e in entries}
                        if entry["numero_processo"] in existing_nums:
                            continue
                        entry["page"] = page_num
                        entry["search_terms"] = query
                        entries.append(entry)

                if len(entries) >= max_results:
                    break

                if not self._go_to_next_page(page_num, tipo_decisao):
                    logger.info(f"[{self.court_key}] No more pages")
                    break

                page_num += 1
                time.sleep(3)

        except Exception as e:
            logger.error(f"[{self.court_key}] Error during search: {e}")

        logger.info(f"[{self.court_key}] Total results: {len(entries)}")
        return entries

    def _go_to_next_page(self, current_page: int, tipo_decisao: str = "A") -> bool:
        """Navigate to the next page of e-SAJ results."""
        next_page = current_page + 1

        selectors = [
            f"//*[@id='paginacaoSuperior-{tipo_decisao}']//a[text()='{next_page}']",
            f"//*[@id='paginacaoSuperior-{tipo_decisao}']//span[text()='{next_page}']",
            f"//a[contains(@href, 'trocaDePagina') and contains(text(), '{next_page}')]",
            f"//a[contains(@onclick, 'pagina') and text()='{next_page}']",
        ]

        for selector in selectors:
            try:
                elem = self.driver.find_element(By.XPATH, selector)
                if elem.is_displayed():
                    self.driver.execute_script("arguments[0].click();", elem)
                    time.sleep(2)
                    return True
            except Exception:
                continue

        # Fallback: direct GET to pagination URL
        try:
            page_url = (
                f"{self.config.pagination_url}"
                f"?tipoDeDecisao={tipo_decisao}&pagina={next_page}&conversationId="
            )
            self.driver.get(page_url)
            time.sleep(2)
            return True
        except Exception:
            pass

        return False

    def search_with_criteria(self, criteria: SearchCriteria) -> List[Dict[str, Any]]:
        """Search using a SearchCriteria object."""
        filters = {
            "tipo_decisao": criteria.tipo_decisao,
            "data_julgamento_inicio": criteria.data_julgamento_inicio,
            "data_julgamento_fim": criteria.data_julgamento_fim,
            "data_publicacao_inicio": criteria.data_publicacao_inicio,
            "data_publicacao_fim": criteria.data_publicacao_fim,
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
        """Download inteiro teor document for an e-SAJ result."""
        if save_dir is None:
            save_dir = os.path.abspath(
                os.path.join(os.getcwd(), "workspace", f"{self.court_key}_jurisprudencia")
            )

        if _skip_org:
            final_save_dir = save_dir
            os.makedirs(final_save_dir, exist_ok=True)
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            folder_parts = []
            if agent_id:
                folder_parts.append(agent_id)
            if folder_name:
                folder_parts.append(folder_name)
            folder_parts.append(timestamp)
            final_save_dir = os.path.join(save_dir, *folder_parts)
            os.makedirs(final_save_dir, exist_ok=True)

        if metadata is None:
            metadata = {}
        metadata.update({
            "agent_id": agent_id,
            "folder_name": folder_name,
            "search_params": search_params,
            "download_timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "folder_path": final_save_dir,
            "tribunal": self.court_key,
        })

        try:
            cdacordao = None
            num_match = re.search(r"cdAcordao=(\d+)", url)
            if num_match:
                cdacordao = num_match.group(1)
            else:
                cdacordao = metadata.get("cdacordao") or metadata.get("download_id")

            if not cdacordao:
                logger.error(f"[{self.court_key}] Could not extract cdAcordao from: {url}")
                return None

            download_url = f"{self.config.download_url}?cdAcordao={cdacordao}&cdForo=0"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/pdf,*/*",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            }

            selenium_cookies = self.driver.get_cookies()
            session = requests.Session()
            for cookie in selenium_cookies:
                session.cookies.set(cookie["name"], cookie["value"])

            self.driver.get(download_url)
            time.sleep(2)

            page_source = self.driver.page_source
            current_url = self.driver.current_url
            content_type = ""

            # Captcha handling (court-specific)
            # Definitive marker for a *real* Google reCAPTCHA widget (TJAL/TJAM,
            # etc.) is the reCAPTCHA bubble, the google recaptcha iframe, or a
            # reCAPTCHA sitekey (6L...). The e-SAJ "Código de Acesso" section
            # heading appears on many portals and is NOT a captcha by itself, and
            # a generic hidden "g-recaptcha-response" field is not proof either.
            # So we treat reCAPTCHA as dominant when unambiguously present; only
            # otherwise do we attempt the legacy image-captcha (OCR) flow.
            has_grecaptcha_widget = bool(
                "g-recaptcha-bubble" in page_source
                or "www.google.com/recaptcha" in page_source
                or re.search(r"k=6L[A-Za-z0-9_\-]{20,}", page_source) is not None
                or re.search(r'class="g-recaptcha"', page_source) is not None
            )
            image_captcha_seen = (
                "imagemCaptcha" in page_source
                or bool(re.search(r"src=[^>]*imagemCaptcha", page_source))
                or "vlCaptcha" in page_source
                or 'name="vlCaptcha"' in page_source
            )

            if self.config.captcha_type in ("image_captcha", "recaptcha_v3"):
                if "captcha" in page_source.lower() or image_captcha_seen or has_grecaptcha_widget:
                    logger.info(f"[{self.court_key}] Captcha detected, attempting to solve...")

                    if has_grecaptcha_widget:
                        # Genuine Google reCAPTCHA (checkbox variant on TJAL/
                        # TJAM). Free path first: click the "I'm not a robot"
                        # checkbox in the live browser and press Enviar. Falls
                        # back to a paid solving service if available.
                        from modules.captcha_solver import (
                            click_checkbox_captcha,
                            solve_and_submit,
                        )
                        solved = click_checkbox_captcha(self.driver)
                        if not solved:
                            solved = solve_and_submit(self.driver)
                        if not solved:
                            logger.warning(
                                f"[{self.court_key}] Google reCAPTCHA could not be solved "
                                "(checkbox click failed and no solver configured; set "
                                "JURIS_CAPTCHA_SOLVER + JURIS_CAPTCHA_API_KEY). Skipping "
                                f"download of {cdacordao}."
                            )
                            return None
                        current_url = self.driver.current_url
                        page_source = self.driver.page_source
                    elif image_captcha_seen:
                        # Legacy e-SAJ image captcha (other portals): OCR first,
                        # external service fallback if OCR unavailable/fails.
                        try:
                            captcha_img = self._find_captcha_image()
                            captcha_src = captcha_img.get_attribute("src") if captcha_img else None
                            if captcha_src:
                                captcha_response = session.get(captcha_src, headers=headers)
                                if captcha_response.status_code == 200:
                                    captcha_path = os.path.join(
                                        final_save_dir, f"captcha_{cdacordao}.png"
                                    )
                                    with open(captcha_path, "wb") as f:
                                        f.write(captcha_response.content)
                                    captcha_text = self._solve_captcha(captcha_path)
                                    if not captcha_text:
                                        from modules.captcha_solver import _configured_solver
                                        svc = _configured_solver()
                                        if svc is not None:
                                            try:
                                                captcha_text = svc.solve_image_captcha(captcha_path)
                                            except Exception as sexc:
                                                logger.warning(
                                                    f"[{self.court_key}] service captcha solve failed: {sexc}"
                                                )
                                    if captcha_text:
                                        captcha_input = self.driver.find_element(
                                            By.NAME, "vlCaptcha"
                                        )
                                        captcha_input.clear()
                                        captcha_input.send_keys(captcha_text)
                                        submit_btn = self.driver.find_element(
                                            By.XPATH, "//input[@value='Confirmar']"
                                        )
                                        submit_btn.click()
                                        time.sleep(3)
                                        current_url = self.driver.current_url
                                    else:
                                        logger.warning(
                                            f"[{self.court_key}] Could not solve image captcha for {cdacordao}"
                                        )
                                        return None
                                else:
                                    logger.warning(
                                        f"[{self.court_key}] Captcha image fetch failed ({captcha_response.status_code}) for {cdacordao}"
                                    )
                                    return None
                            else:
                                self._dump_captcha_debug(cdacordao, final_save_dir)
                                logger.warning(
                                    f"[{self.court_key}] No captcha image element found for {cdacordao}"
                                )
                                return None
                        except Exception as e:
                            logger.warning(f"[{self.court_key}] Captcha solving failed: {e}")
                            return None

            try:
                resp = requests.get(
                    current_url, headers=headers,
                    cookies=session.cookies, timeout=30,
                )
                content_type = resp.headers.get("content-type", "").lower()
            except Exception:
                resp = None

            if resp and "application/pdf" in content_type:
                ext = "pdf"
            else:
                # The response is HTML. If it is a captcha/interstitial page
                # rather than a real document, do not save it as a fake record.
                page_html = self.driver.page_source
                fresh_captcha = (
                    "imagemCaptcha" in page_html
                    or "Código de Acesso" in page_html
                    or "digite o código da figura" in page_html.lower()
                    or (
                        "g-recaptcha-response" in page_html
                        and "userrecaptcha" in page_html
                    )
                )
                if fresh_captcha:
                    logger.warning(
                        f"[{self.court_key}] Got a captcha/interstitial page (not a document) "
                        f"for {cdacordao}; skipping to avoid indexing a fake file."
                    )
                    return None
                content = page_html.encode("utf-8")
                ext = "html"

            if not filename:
                num = metadata.get("numero_processo") or cdacordao or "unknown"
                filename = f"inteiro_teor_{cdacordao}.{ext}"

            filepath = os.path.join(final_save_dir, filename)

            if ext == "pdf":
                # Resilient, verified stream (guards against truncated PDFs).
                from modules.download_utils import download_to_file
                try:
                    written = download_to_file(
                        current_url, filepath,
                        headers=headers, cookies=session.cookies,
                        timeout=60, retries=3, session=session,
                    )
                except Exception as dl_exc:
                    logger.error(
                        f"[{self.court_key}] PDF download failed from {current_url}: {dl_exc}"
                    )
                    return None
                file_size_bytes = written
            else:
                with open(filepath, "wb") as f:
                    f.write(content)
                file_size_bytes = len(content)

            sidecar = {
                "downloaded_at": datetime.utcnow().isoformat() + "Z",
                "download_url": current_url,
                "source_url": url,
                "cdacordao": cdacordao,
                "content_type": content_type,
                "file_size_bytes": file_size_bytes,
                "tribunal": self.court_key,
            }
            sidecar.update(metadata)
            write_sidecar_metadata(filepath, sidecar)

            logger.info(f"[{self.court_key}] Saved inteiro teor to {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"[{self.court_key}] Download failed from {url}: {e}")
            return None

    def _solve_captcha(self, image_path: str) -> Optional[str]:
        """Attempt to solve an e-SAJ captcha image using OCR (offline, free).

        e-SAJ "Código de Acesso" figures are distorted; we binarise, upscale,
        and try several page-segmentation modes + the alphanumeric whitelist,
        then keep the best alphanumeric guess of plausible length.
        """
        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            logger.warning(f"[{self.court_key}] pytesseract/Pillow not available")
            return None

        try:
            WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

            def preprocess(img: "Image.Image") -> "Image.Image":
                img = img.convert("L")
                # upscale for small, noisy captchas
                img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
                # binarise by mean luminance (handles light/dark variants)
                px = list(img.getdata())
                thr = sum(px) / len(px) if px else 128
                return img.point(lambda x: 0 if x < thr else 255)

            base = Image.open(image_path)
            candidates = []
            for variant in [preprocess(base), base.convert("L")]:
                for psm in (7, 8, 6):
                    cfg = f"--psm {psm} -c tessedit_char_whitelist={WHITELIST}"
                    try:
                        text = pytesseract.image_to_string(variant, config=cfg)
                    except Exception:
                        continue
                    text = "".join(ch for ch in text.upper() if ch in WHITELIST)
                    if 4 <= len(text) <= 6:
                        candidates.append(text)

            if not candidates:
                return None
            # Prefer the longest candidate (e-SAJ codes are usually 5-6 chars).
            candidates.sort(key=len, reverse=True)
            return candidates[0]
        except Exception as e:
            logger.warning(f"[{self.court_key}] Captcha OCR error: {e}")
            return None

    def _find_captcha_image(self):
        """Locate the captcha <img> using several common e-SAJ selectors."""
        from selenium.common.exceptions import NoSuchElementException

        selectors = [
            "img[src*='imagemCaptcha']",
            "img[src*='captcha']",
            "img[id*='captcha']",
            "img[class*='captcha']",
            "img[src*='CódigoAcesso']",
            "img[src*='codigoAcesso']",
            "img[src*='validacao']",
        ]
        for sel in selectors:
            try:
                el = self.driver.find_element(By.CSS_SELECTOR, sel)
                if el and el.get_attribute("src"):
                    return el
            except NoSuchElementException:
                continue
        # Fallback: an <img> anywhere inside the captcha form (near vlCaptcha).
        try:
            form = self.driver.find_element(By.XPATH, "//form[contains(., 'Código de Acesso')]")
            img = form.find_element(By.CSS_SELECTOR, "img")
            if img and img.get_attribute("src"):
                return img
        except Exception:
            pass
        return None

    def _dump_captcha_debug(self, cdacordao, save_dir: str) -> None:
        """Save the current page source for selector diagnosis."""
        try:
            snippet = self.driver.page_source
            out = os.path.join(save_dir, f"captcha_debug_{cdacordao}.html")
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(snippet)
            logger.info(f"[{self.court_key}] Captcha page HTML dumped to {out}")
        except Exception as exc:
            logger.debug("captcha debug dump failed: %s", exc)

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
        """Download inteiro teor for all results in the list."""
        if save_dir is None:
            save_dir = os.path.abspath(
                os.path.join(os.getcwd(), "workspace", f"{self.court_key}_jurisprudencia")
            )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_parts = []
        if agent_id:
            folder_parts.append(agent_id)
        if folder_name:
            folder_parts.append(folder_name)
        folder_parts.append(timestamp)
        final_save_dir = os.path.join(save_dir, *folder_parts)
        os.makedirs(final_save_dir, exist_ok=True)

        if search_params:
            metadata_file = os.path.join(final_save_dir, "search_metadata.json")
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump({
                    "search_params": search_params,
                    "agent_id": agent_id,
                    "folder_name": folder_name,
                    "timestamp": timestamp,
                    "total_results": len(results),
                    "download_started": datetime.utcnow().isoformat() + "Z",
                    "tribunal": self.court_key,
                }, f, indent=2, ensure_ascii=False)

        saved_files = []
        for idx, res in enumerate(results, 1):
            url = res.get("inteiro_url")
            if not url:
                logger.warning(f"[{self.court_key}] Result {idx} missing 'inteiro_url'")
                continue

            cdacordao = res.get("cdacordao") or res.get("download_id") or "unknown"
            existing = [
                os.path.join(final_save_dir, name)
                for name in os.listdir(final_save_dir)
                if str(cdacordao) in name and not name.startswith("captcha_")
            ]
            if existing and not overwrite:
                logger.info(f"[{self.court_key}] Skipping existing: {existing[0]}")
                saved_files.append(existing[0])
                continue

            logger.info(f"[{self.court_key}] Downloading ({idx}/{len(results)}): {cdacordao}")
            saved = self.download_inteiro_teor_url(
                url,
                save_dir=final_save_dir,
                metadata={
                    "cdacordao": cdacordao,
                    "numero_processo": res.get("numero_processo"),
                    "tribunal": self.court_key,
                    "agent_id": agent_id,
                    "folder_name": folder_name,
                    "search_params": search_params,
                },
                search_params=search_params,
                _skip_org=True,
            )
            if saved:
                saved_files.append(saved)
            else:
                logger.warning(f"[{self.court_key}] Failed download: {cdacordao}")

            if delay and idx < len(results):
                time.sleep(delay)

        return saved_files

    def canonicalize_inteiro_url(
        self, raw_url: str, fallback_num: Optional[str] = None
    ) -> Dict[str, Optional[str]]:
        """Extract canonical parameters from an e-SAJ inteiro teor URL."""
        raw = (raw_url or "").replace("&amp;", "&").strip()
        cdacordao = None
        match = re.search(r"cdAcordao=(\d+)", raw)
        if match:
            cdacordao = match.group(1)
        else:
            cdacordao = fallback_num

        return {
            "source_url": raw,
            "cdacordao": cdacordao,
            "numero_processo": fallback_num,
            "url": self._build_inteiro_url(cdacordao) if cdacordao else raw,
            "is_canonical": bool(cdacordao),
        }

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def close(self):
        if self.driver:
            self.driver.quit()
            self.driver = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def list_esaj_courts_simple() -> List[str]:
    """Return sorted list of all available e-SAJ court keys."""
    from _shared.esaj_config import ESAJ_COURTS
    return sorted(ESAJ_COURTS.keys())
