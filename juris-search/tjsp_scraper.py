"""
TJSP (Tribunal de Justiça de São Paulo) Jurisprudence Scraper.

Uses Selenium to search the e-SAJ CJSG (Consulta de Julgados de Segundo Grau)
and download inteiro teor documents.

Interface matches TJRSJurisprudenciaScraper for drop-in compatibility.
"""

import os
import sys
import re
import time
import json
import shutil
import subprocess
import logging
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlencode, urljoin, urlparse

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By

from _shared.chrome_driver import (
    resolve_chrome_binary,
    create_chrome_driver,
    build_chrome_options,
    write_sidecar_metadata,
    infer_extension,
)
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from bs4 import BeautifulSoup

try:
    from webdriver_manager.chrome import ChromeDriverManager
except Exception:
    ChromeDriverManager = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class SearchCriteria:
    """Data class for search parameters — same interface as TJRS."""
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
    search_index: str = "ementa"  # ementa or inteiro_teor
    max_results: int = 20


# ── TJSP-specific constants ──────────────────────────────────────────────────

# TJSP decision type mapping
TIPOS_DECISAO = {
    "acórdão": "A",
    "acordao": "A",
    "acórdão": "A",
    "monocrática": "D",
    "monocratica": "D",
    "decisão monocrática": "D",
    "homologação": "H",
    "homologacao": "H",
}

CJSG_SEARCH_URL = "https://esaj.tjsp.jus.br/cjsg/resultadoCompleta.do"
CJSG_PAGE_URL = "https://esaj.tjsp.jus.br/cjsg/trocaDePagina.do"
CJSG_DOWNLOAD_URL = "https://esaj.tjsp.jus.br/cjsg/getArquivo.do"
CJSG_BASE = "https://esaj.tjsp.jus.br"


class TJSPJurisprudenciaScraper:
    """Scraper for TJSP jurisprudence (e-SAJ CJSG system).

    Searches the CJSG (second degree) database and downloads
    inteiro teor documents.
    """

    def __init__(self, headless=True, wait_time=30):
        self.wait_time = wait_time
        self.driver = create_chrome_driver(headless=headless)


    # ── Search ────────────────────────────────────────────────────────────

    def _resolve_tipo_decisao(self, tipo: Optional[str]) -> str:
        if not tipo:
            return "A"  # default: Acórdãos
        key = tipo.strip().lower()
        return TIPOS_DECISAO.get(key, "A")

    def _format_date_for_tjsp(self, date_str: Optional[str]) -> str:
        """Convert various date formats to dd/mm/aaaa for TJSP forms."""
        if not date_str:
            return ""
        date_str = date_str.strip()
        # Already in dd/mm/aaaa format
        if re.match(r"^\d{2}/\d{2}/\d{4}$", date_str):
            return date_str
        # ISO format yyyy-mm-dd
        iso_match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", date_str)
        if iso_match:
            return f"{iso_match.group(3)}/{iso_match.group(2)}/{iso_match.group(1)}"
        # dd/mm/yy
        short_match = re.match(r"^(\d{2})/(\d{2})/(\d{2})$", date_str)
        if short_match:
            return f"{short_match.group(1)}/{short_match.group(2)}/20{short_match.group(3)}"
        return date_str

    def _build_search_form_data(self, query: str, filters: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, str]:
        """Build the POST form data for a CJSG search."""
        filters = filters or {}

        data = {
            "conversationId": "",
            "dados.buscaInteiroTeor": query or "",
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
            "dados.dtJulgamentoInicio": self._format_date_for_tjsp(filters.get("data_julgamento_inicio") or filters.get("dtJulgamentoInicio")),
            "dados.dtJulgamentoFim": self._format_date_for_tjsp(filters.get("data_julgamento_fim") or filters.get("dtJulgamentoFim")),
            "dados.dtRegistroInicio": "",
            "dados.dtRegistroFim": "",
            "dados.dtPublicacaoInicio": self._format_date_for_tjsp(filters.get("data_publicacao_inicio") or filters.get("dtPublicacaoInicio")),
            "dados.dtPublicacaoFim": self._format_date_for_tjsp(filters.get("data_publicacao_fim") or filters.get("dtPublicacaoFim")),
            "dados.origensSelecionadas": "T",  # 2º grau
            "tipoDecisaoSelecionados": self._resolve_tipo_decisao(filters.get("tipo_decisao")),
            "dados.ordenarPor": "dtPublicacao",
        }
        return data

    def _parse_page_count(self, tipo_decisao: str = "A") -> int:
        """Extract total page count from the pagination element."""
        try:
            pagination_id = f"paginacaoSuperior-{tipo_decisao}"
            elem = self.driver.find_element(By.ID, pagination_id)
            text = elem.text
            # Text like "Página 1 de 45"
            numbers = re.findall(r"\d+", text)
            if len(numbers) >= 2:
                total = int(numbers[-1])
                per_page = int(numbers[0]) if len(numbers) >= 3 else 1
                pages = (total + per_page - 1) // per_page if per_page > 0 else 1
                return max(1, pages)
        except Exception:
            pass
        return 1

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
            key=lambda s: len(s),
            reverse=True,
        )
        for separator in separators:
            if separator in raw:
                left, right = raw.split(separator, 1)
                return left.strip(), right.strip()
        return raw, ""

    def _parse_result_block(self, block) -> Optional[Dict[str, Any]]:
        """Parse a single result block (.fundocinza1) into a dict."""
        try:
            html = block.get_attribute("innerHTML")
            soup = BeautifulSoup(html, "html.parser")

            entry: Dict[str, Any] = {}

            # Download link with decision ID
            download_link = soup.select_one(".downloadEmenta")
            if download_link:
                entry["cdacordao"] = download_link.get("cdacordao", "")
                entry["numero_processo"] = download_link.get_text(strip=True)
            else:
                entry["cdacordao"] = ""
                entry["numero_processo"] = ""

            # Class and subject
            assunto_classe = soup.select_one(".assuntoClasse")
            if assunto_classe:
                entry["classe_assunto"] = assunto_classe.get_text(strip=True)
            else:
                entry["classe_assunto"] = ""
            classe_cnj, assunto_cnj = self._split_classe_assunto(entry["classe_assunto"])
            entry["classe_cnj"] = classe_cnj
            entry["assunto_cnj"] = assunto_cnj

            # Metadata fields from .ementaClass2
            # TJSP label keys after unicode normalization:
            #   "Relator(a):"         -> relator_a
            #   "Órgão julgador:"     -> orgao_julgador
            #   "Comarca:"            -> comarca
            #   "Data do julgamento:" -> data_do_julgamento
            #   "Data de publicação:" -> data_de_publicacao
            #   "Data de registro:"   -> data_de_registro
            metadata: Dict[str, str] = {}
            for span in soup.select(".ementaClass2"):
                text = span.get_text(strip=True)
                if ":" in text:
                    key, _, value = text.partition(":")
                    key_norm = self._normalize_metadata_key(key)
                    metadata[key_norm] = value.strip()

            entry["comarca_origem"] = (
                metadata.get("comarca", "")
                or metadata.get("comarca_origem", "")
            )
            entry["orgao_julgador"] = (
                metadata.get("orgao_julgador", "")
                or metadata.get("orgao_judicante", "")
                or metadata.get("orgao", "")
            )
            entry["data_julgamento"] = (
                metadata.get("data_do_julgamento", "")  # "Data do julgamento:"
                or metadata.get("data_julgamento", "")
                or metadata.get("data_de_julgamento", "")
            )
            entry["data_publicacao"] = (
                metadata.get("data_de_publicacao", "")  # "Data de publicação:"
                or metadata.get("data_publicacao", "")
            )
            entry["data_registro"] = (
                metadata.get("data_de_registro", "")  # "Data de registro:"
                or metadata.get("data_registro", "")
            )
            entry["relator"] = (
                metadata.get("relator_a", "")  # "Relator(a):"
                or metadata.get("relatora", "")
                or metadata.get("relator", "")
            )
            entry["tipo_processo"] = (
                metadata.get("tipo_processo", "")
                or metadata.get("tipo_de_processo", "")
                or entry["classe_cnj"]
            )
            entry["tribunal"] = "TJSP"

            # Ementa: try textarea, then .ementaClass (TJSP uses both structures)
            ementa = ""
            textarea = soup.select_one("textarea")
            if textarea:
                ementa = textarea.get_text(strip=True)
            if not ementa:
                # .ementaClass (without trailing 2) holds the ementa body
                ementa_el = soup.select_one(".ementaClass")
                if ementa_el:
                    # Strip out nested .ementaClass2 metadata text
                    for meta_span in ementa_el.select(".ementaClass2"):
                        meta_span.decompose()
                    ementa = ementa_el.get_text(" ", strip=True)
            if not ementa:
                # Last resort: look for any span/div containing ementa-like keywords
                for candidate in soup.select("span, div, p"):
                    ctext = candidate.get_text(strip=True)
                    upper = ctext.upper()
                    if len(ctext) > 80 and any(
                        kw in upper for kw in ("APELAÇÃO", "RECURSO", "INDENIZ", "DANO", "RESPONSABILIDADE")
                    ) and candidate.name not in ("html", "body"):
                        ementa = ctext
                        break
            entry["ementa_trecho"] = re.sub(r"\s+", " ", ementa).strip()[:500]

            # Build inteiro teor download URL
            cdacordao = entry.get("cdacordao", "")
            if cdacordao:
                entry["inteiro_url"] = f"{CJSG_DOWNLOAD_URL}?cdAcordao={cdacordao}&cdForo=0"
                entry["download_id"] = cdacordao
            else:
                entry["inteiro_url"] = None
                entry["download_id"] = None

            return entry
        except Exception as e:
            logger.debug(f"Error parsing result block: {e}")
            return None

    def get_inteiro_links(
        self,
        query: str,
        max_results: int = 20,
        search_index: str = "ementa",
        filters: Optional[Dict[str, Optional[str]]] = None,
    ) -> List[Dict[str, Any]]:
        """Search TJSP CJSG and return list of result dicts with inteiro teor URLs.

        Uses Selenium to POST the search form and navigate pagination.
        """
        filters = filters or {}
        tipo_decisao = self._resolve_tipo_decisao(filters.get("tipo_decisao"))

        logger.info(f"TJSP: loading search page: {CJSG_SEARCH_URL}")

        # Step 1: Load the initial search page
        self.driver.get(CJSG_SEARCH_URL)
        time.sleep(2)

        # Step 2: Fill and submit the search form
        form_data = self._build_search_form_data(query, filters)
        logger.info(f"TJSP: submitting search with query='{query}', tipo_decisao={tipo_decisao}")

        try:
            # Find the form and fill fields
            for field_name, field_value in form_data.items():
                if not field_value:
                    continue
                clean_name = field_name.replace("dados.", "").replace(".", "")
                try:
                    elem = self.driver.find_element(By.NAME, field_name)
                    if elem.is_displayed() and elem.is_enabled():
                        elem.clear()
                        elem.send_keys(str(field_value))
                except Exception:
                    pass

            # Submit the form by clicking the search button
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
                # Try JavaScript form submission
                self.driver.execute_script(
                    "document.forms[0].submit()"
                )
                submitted = True

        except Exception as e:
            logger.warning(f"Form filling via Selenium failed: {e}, trying direct POST")
            # Fallback: POST directly via requests using the driver's cookies
            try:
                cookies = self.driver.get_cookies()
                session = requests.Session()
                for cookie in cookies:
                    session.cookies.set(cookie["name"], cookie["value"])
                resp = session.post(CJSG_SEARCH_URL, data=form_data, timeout=30)
                self.driver.get(CJSG_SEARCH_URL)
                # Inject the response
                self.driver.execute_script(
                    f"document.open(); document.write({json.dumps(resp.text)}); document.close();"
                )
            except Exception as e2:
                logger.error(f"Direct POST fallback also failed: {e2}")

        time.sleep(3)

        entries: List[Dict[str, Any]] = []
        page_num = 1
        max_pages = 50

        try:
            while len(entries) < max_results and page_num <= max_pages:
                logger.info(f"TJSP: processing page {page_num}...")

                # Wait for results to load
                try:
                    WebDriverWait(self.driver, self.wait_time).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".fundocinza1"))
                    )
                except Exception:
                    logger.warning(f"No results found on page {page_num}")
                    break

                time.sleep(2)

                # Find all result blocks
                result_blocks = self.driver.find_elements(By.CSS_SELECTOR, ".fundocinza1")
                logger.info(f"TJSP: found {len(result_blocks)} result blocks on page {page_num}")

                processed_on_page = 0
                for block in result_blocks:
                    if len(entries) >= max_results:
                        break
                    entry = self._parse_result_block(block)
                    if entry and entry.get("numero_processo"):
                        # Skip duplicates
                        existing_nums = {e.get("numero_processo") for e in entries}
                        if entry["numero_processo"] in existing_nums:
                            continue
                        entry["page"] = page_num
                        entry["search_terms"] = query
                        entries.append(entry)
                        processed_on_page += 1
                        logger.info(
                            f"TJSP: found result {len(entries)}: {entry['numero_processo']} "
                            f"(ID: {entry.get('download_id')})"
                        )

                logger.info(f"TJSP: processed {processed_on_page} results on page {page_num} (total: {len(entries)})")

                if len(entries) >= max_results:
                    break

                # Try to go to next page
                if not self._go_to_next_page(page_num, tipo_decisao):
                    logger.info("TJSP: no more pages")
                    break

                page_num += 1
                time.sleep(3)

        except Exception as e:
            logger.error(f"TJSP: error during search: {e}")

        logger.info(f"TJSP: total results collected: {len(entries)}")
        return entries

    def _go_to_next_page(self, current_page: int, tipo_decisao: str = "A") -> bool:
        """Navigate to the next page of results."""
        next_page = current_page + 1

        # First try: click the page number in pagination
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
                    logger.info(f"TJSP: clicked page {next_page}")
                    time.sleep(2)
                    return True
            except Exception:
                continue

        # Second try: directly navigate via GET
        try:
            page_url = f"{CJSG_PAGE_URL}?tipoDeDecisao={tipo_decisao}&pagina={next_page}&conversationId="
            logger.info(f"TJSP: navigating to page URL: {page_url}")
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

    def _write_sidecar_metadata(self, filepath: str, metadata: Dict[str, Any]) -> None:
        write_sidecar_metadata(filepath, metadata)

    def _infer_extension(self, url: str = "", content_type: str = "") -> str:
        return infer_extension(url, content_type)

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
        """Download the inteiro teor document for a TJSP result.

        TJSP serves PDFs with an image captcha on the direct download.
        Strategy: Use Selenium to navigate to the download page,
        handle the captcha via the browser session, and download the PDF.
        """
        if save_dir is None:
            save_dir = os.path.abspath(os.path.join(os.getcwd(), "workspace", "TJSP_jurisprudencia"))

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
            "tribunal": "TJSP",
        })

        try:
            # Extract cdAcordao from URL
            cdacordao = None
            num_match = re.search(r"cdAcordao=(\d+)", url)
            if num_match:
                cdacordao = num_match.group(1)
            else:
                cdacordao = metadata.get("cdacordao") or metadata.get("download_id")

            if not cdacordao:
                logger.error(f"TJSP: could not extract cdAcordao from URL: {url}")
                return None

            # Use Selenium to navigate to the download page
            # The captcha might be triggered, so use the browser's session
            download_url = f"{CJSG_DOWNLOAD_URL}?cdAcordao={cdacordao}&cdForo=0"

            # Try direct HTTP download first (might work if captcha is not enforced)
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/pdf,*/*",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            }

            # Get cookies from Selenium session
            selenium_cookies = self.driver.get_cookies()
            session = requests.Session()
            for cookie in selenium_cookies:
                session.cookies.set(cookie["name"], cookie["value"])

            # First, access the download page to get the captcha uuid if needed
            self.driver.get(download_url)
            time.sleep(2)

            page_source = self.driver.page_source

            # Check if we got a captcha page or the PDF directly
            current_url = self.driver.current_url
            content_type = ""

            # If we see a captcha form, we need to solve or bypass it
            if "captcha" in page_source.lower() or "imagemCaptcha" in page_source or "g-recaptcha" in page_source:
                logger.info("TJSP: captcha detected on download page, attempting to solve...")
                
                # Check if it's a Google reCAPTCHA v3 (much harder to solve)
                if "g-recaptcha" in page_source or "recaptcha" in page_source.lower():
                    logger.warning("TJSP: Google reCAPTCHA detected - automatic solving not supported (requires JavaScript challenge or solver service)")

                # Try to find the captcha image and form
                try:
                    captcha_uuid_elem = self.driver.find_element(By.NAME, "uuidCaptcha")
                    captcha_uuid = captcha_uuid_elem.get_attribute("value") if captcha_uuid_elem else ""
                except Exception:
                    captcha_uuid = ""

                # Try reading the captcha image and solving it
                try:
                    captcha_img = self.driver.find_element(By.CSS_SELECTOR, "img[src*='imagemCaptcha']")
                    captcha_src = captcha_img.get_attribute("src")

                    # Download captcha image
                    captcha_response = session.get(captcha_src, headers=headers)
                    if captcha_response.status_code == 200:
                        # Save captcha for manual inspection / OCR
                        captcha_path = os.path.join(final_save_dir, f"captcha_{cdacordao}.png")
                        with open(captcha_path, "wb") as f:
                            f.write(captcha_response.content)
                        logger.info(f"TJSP: captcha saved to {captcha_path}")

                        # Attempt to read captcha text (simple heuristic)
                        captcha_text = self._solve_captcha(captcha_path)
                        if captcha_text:
                            # Submit the captcha form
                            captcha_input = self.driver.find_element(By.NAME, "vlCaptcha")
                            captcha_input.clear()
                            captcha_input.send_keys(captcha_text)

                            submit_btn = self.driver.find_element(By.XPATH, "//input[@value='Confirmar']")
                            submit_btn.click()
                            time.sleep(3)
                            current_url = self.driver.current_url
                except Exception as e:
                    logger.warning(f"TJSP: captcha solving failed: {e}")
                    # Fall through to save whatever we have

            # After captcha (or if no captcha), download the page content
            # Check if we're now on a PDF or still on HTML
            try:
                resp = requests.get(current_url, headers=headers, cookies=session.cookies, timeout=30)
                content_type = resp.headers.get("content-type", "").lower()
            except Exception:
                # Fall back to Selenium page source
                resp = None

            if resp and "application/pdf" in content_type:
                content = resp.content
                ext = "pdf"
            else:
                # Save the HTML page source
                content = self.driver.page_source.encode("utf-8")
                ext = "html"

            if not filename:
                num = metadata.get("numero_processo") or cdacordao or "unknown"
                ano = metadata.get("ano") or ""
                filename = f"inteiro_teor_{num}_{ano}.{ext}" if ano else f"inteiro_teor_{cdacordao}.{ext}"

            filepath = os.path.join(final_save_dir, filename)
            with open(filepath, "wb") as f:
                f.write(content)

            # Guard against truncated downloads: verify the PDF is complete
            # before recording success, otherwise discard it so it can retry.
            if ext == "pdf":
                from modules.download_utils import _verify_pdf_complete
                try:
                    _verify_pdf_complete(filepath)
                except Exception as verify_exc:
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass
                    logger.error(f"TJSP: incomplete PDF discarded from {current_url}: {verify_exc}")
                    return None

            sidecar = {
                "downloaded_at": datetime.utcnow().isoformat() + "Z",
                "download_url": current_url,
                "source_url": url,
                "cdacordao": cdacordao,
                "content_type": content_type,
                "file_size_bytes": len(content),
                "tribunal": "TJSP",
            }
            sidecar.update(metadata)
            self._write_sidecar_metadata(filepath, sidecar)

            logger.info(f"TJSP: saved inteiro teor to {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"TJSP: failed to download from {url}: {e}")
            return None

    def _solve_captcha(self, image_path: str) -> Optional[str]:
        """Attempt to solve a TJSP captcha image using basic OCR heuristics.

        TJSP captchas are typically 5 alphanumeric characters.
        Returns the solved text or None if unsolvable.
        """
        try:
            from PIL import Image
            img = Image.open(image_path).convert("L")  # grayscale
            # Simple threshold to binarize
            img = img.point(lambda x: 0 if x < 128 else 255)

            # Try pytesseract if available
            try:
                import pytesseract
                text = pytesseract.image_to_string(
                    img, config="--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
                )
                text = text.strip()
                if len(text) >= 4:
                    return text[:6]
            except ImportError:
                pass

            # Without tesseract, we cannot solve captchas automatically
            logger.warning("TJSP: pytesseract not available, cannot auto-solve captcha")
            return None
        except Exception as e:
            logger.warning(f"TJSP: captcha solving error: {e}")
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
        """Download inteiro teor for all results in the list."""
        if save_dir is None:
            save_dir = os.path.abspath(os.path.join(os.getcwd(), "workspace", "TJSP_jurisprudencia"))

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
                    "tribunal": "TJSP",
                }, f, indent=2, ensure_ascii=False)

        saved_files = []
        for idx, res in enumerate(results, 1):
            url = res.get("inteiro_url")
            if not url:
                logger.warning(f"TJSP: result {idx} missing 'inteiro_url', skipping")
                continue

            cdacordao = res.get("cdacordao") or res.get("download_id") or "unknown"
            existing_matches = [
                os.path.join(final_save_dir, name)
                for name in os.listdir(final_save_dir)
                if str(cdacordao) in name and not name.startswith("captcha_")
            ]

            if existing_matches and not overwrite:
                logger.info(f"TJSP: skipping existing file: {existing_matches[0]}")
                saved_files.append(existing_matches[0])
                continue

            logger.info(f"TJSP: downloading ({idx}/{len(results)}): {cdacordao}")
            saved = self.download_inteiro_teor_url(
                url,
                save_dir=final_save_dir,
                metadata={
                    "cdacordao": cdacordao,
                    "numero_processo": res.get("numero_processo"),
                    "tribunal": "TJSP",
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
                logger.warning(f"TJSP: failed to download: {cdacordao}")

            if delay and idx < len(results):
                time.sleep(delay)

        return saved_files

    def canonicalize_inteiro_url(self, raw_url: str, fallback_num: Optional[str] = None) -> Dict[str, Optional[str]]:
        """Extract canonical parameters from a TJSP inteiro teor URL."""
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
            "url": f"{CJSG_DOWNLOAD_URL}?cdAcordao={cdacordao}&cdForo=0" if cdacordao else raw,
            "is_canonical": bool(cdacordao),
        }

    def close(self):
        if self.driver:
            self.driver.quit()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ── Example usage ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    scraper = TJSPJurisprudenciaScraper(headless=True)
    try:
        query = "dano moral"
        max_results = 20
        print(f"TJSP: searching for '{query}'...")
        results = scraper.get_inteiro_links(query, max_results=max_results)
        print(f"Found {len(results)} results")
        for r in results[:5]:
            print(f"  - {r.get('numero_processo')} | {r.get('relator')} | {r.get('data_julgamento')}")
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        scraper.close()
