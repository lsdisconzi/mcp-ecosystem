"""
TJRJ (Tribunal de Justiça do Rio de Janeiro) Jurisprudence Scraper.

TJRJ uses its own custom jurisprudence portal (not e-SAJ).
Search interface: https://www.tjrj.jus.br/consultas/jurisprudencia/

Uses Selenium for HTML scraping. The portal uses a custom search form.
Implementation follows the standard scraper interface.
"""

import os
import re
import time
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class SearchCriteria:
    """Search parameters — standard interface."""
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


# ── TJRJ-specific constants ──────────────────────────────────────────────────

TJRJ_BASE_URL = "https://www.tjrj.jus.br"
TJRJ_SEARCH_URL = "https://www.tjrj.jus.br/consultas/jurisprudencia/"


class TJRJJurisprudenciaScraper:
    """Scraper for TJRJ jurisprudence (custom portal).

    TJRJ's portal:
      - URL: https://www.tjrj.jus.br/consultas/jurisprudencia/
      - Search: custom form with keyword and structured fields
      - Results: paginated list with process metadata
      - Download: links to inteiro teor PDF/DOC

    NOTE: TJRJ uses a custom portal, not e-SAJ. The HTML structure requires
    live inspection to determine exact CSS selectors. This scraper provides
    a best-effort implementation with fallback strategies for parsing.
    """

    def __init__(self, headless=True, wait_time=30):
        self.wait_time = wait_time
        self.driver = create_chrome_driver(headless=headless)

    # ── Search ────────────────────────────────────────────────────────────

    def get_inteiro_links(
        self,
        query: str,
        max_results: int = 20,
        search_index: str = "ementa",
        filters: Optional[Dict[str, Optional[str]]] = None,
    ) -> List[Dict[str, Any]]:
        """Search TJRJ jurisprudence portal and return result list."""
        filters = filters or {}
        logger.info(f"TJRJ: Loading search page: {TJRJ_SEARCH_URL}")
        self.driver.get(TJRJ_SEARCH_URL)
        time.sleep(3)

        entries: List[Dict[str, Any]] = []

        try:
            # Attempt search form fill
            search_input_selectors = [
                "input[name='palavra']",
                "input[name='pesquisaLivre']",
                "input[name='textoPesquisa']",
                "textarea[name='ementa']",
                "input[name='q']",
                "input[type='search']",
            ]
            search_filled = False
            for selector in search_input_selectors:
                try:
                    elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if elem.is_displayed() and elem.is_enabled():
                        elem.clear()
                        elem.send_keys(query or "")
                        search_filled = True
                        logger.info(f"TJRJ: Filled search: {selector}")
                        break
                except Exception:
                    continue

            if not search_filled:
                logger.warning("TJRJ: Could not locate search input")
                return entries

            # Submit
            submit_selectors = [
                "input[type='submit']",
                "button[type='submit']",
                "//button[contains(text(), 'Pesquisar')]",
                "//button[contains(text(), 'Consultar')]",
                "//input[@value='Pesquisar']",
                "//input[@value='Consultar']",
            ]
            submitted = False
            for selector in submit_selectors:
                try:
                    if selector.startswith("//"):
                        btn = self.driver.find_element(By.XPATH, selector)
                    else:
                        btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if btn.is_displayed():
                        btn.click()
                        submitted = True
                        break
                except Exception:
                    continue

            if not submitted:
                self.driver.execute_script("document.forms[0].submit()")

            time.sleep(4)

            page_num = 1
            max_pages = 50

            while len(entries) < max_results and page_num <= max_pages:
                logger.info(f"TJRJ: Processing page {page_num}...")
                time.sleep(2)

                result_selectors = [
                    "table.lista-resultados tr",
                    ".resultados-pesquisa .item",
                    "div[class*='resultado']",
                    "li[class*='resultado']",
                    ".consulta-resultado tr",
                ]
                found_blocks = []
                for sel in result_selectors:
                    try:
                        blocks = self.driver.find_elements(By.CSS_SELECTOR, sel)
                        if blocks:
                            found_blocks = blocks
                            break
                    except Exception:
                        continue

                if not found_blocks:
                    logger.warning(f"TJRJ: No result blocks on page {page_num}")
                    break

                for block in found_blocks:
                    if len(entries) >= max_results:
                        break
                    entry = self._parse_tjrj_result(block, query)
                    if entry and entry.get("numero_processo"):
                        existing = {e.get("numero_processo") for e in entries}
                        if entry["numero_processo"] in existing:
                            continue
                        entry["page"] = page_num
                        entry["tribunal"] = "TJRJ"
                        entries.append(entry)

                if len(entries) >= max_results:
                    break

                if not self._go_to_next_page_tjrj(page_num):
                    break
                page_num += 1

        except Exception as e:
            logger.error(f"TJRJ: Search error: {e}")

        return entries

    def _parse_tjrj_result(self, block, query: str = "") -> Optional[Dict[str, Any]]:
        """Parse a TJRJ result block into a dict."""
        try:
            html = block.get_attribute("innerHTML") or block.get_attribute("outerHTML")
            soup = BeautifulSoup(html, "html.parser")
            text = soup.get_text(" ", strip=True)
            entry: Dict[str, Any] = {}

            # Process number
            proc_match = re.search(
                r"\b(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})\b"
                r"|"
                r"\b(\d{7,20})\b",
                text
            )
            if proc_match:
                entry["numero_processo"] = proc_match.group(1) or proc_match.group(2)
            else:
                entry["numero_processo"] = ""

            # Inteiro teor link
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                link_text = link.get_text(strip=True).lower()
                if any(kw in href.lower() + link_text for kw in (
                    "inteiro", "download", "visualizar", "documento", "acordao",
                )):
                    entry["inteiro_url"] = href if href.startswith("http") else (
                        f"{TJRJ_BASE_URL}{href}" if href.startswith("/") else href
                    )
                    dl_id = re.search(r"(\d{6,})", href)
                    entry["download_id"] = dl_id.group(1) if dl_id else None
                    break

            if "inteiro_url" not in entry:
                entry["inteiro_url"] = None
                entry["download_id"] = None

            # Metadata
            relator_match = re.search(
                r"(?:Relator[ao]?|Des\.?|Desembargador[ao]?)[:\s]+([^\n,;]+)", text,
                re.IGNORECASE
            )
            entry["relator"] = relator_match.group(1).strip() if relator_match else ""

            comarca_match = re.search(
                r"(?:Comarca|Origem)[:\s]+([^\n,;]+)", text, re.IGNORECASE
            )
            entry["comarca_origem"] = comarca_match.group(1).strip() if comarca_match else ""

            data_match = re.search(
                r"(?:Data\s+(?:de\s+)?(?:Julgamento|Publicação|Publicacao)|Julgado\s+em)[:\s]+([\d/]+)",
                text, re.IGNORECASE
            )
            entry["data_julgamento"] = data_match.group(1).strip() if data_match else ""

            orgao_match = re.search(
                r"(?:Órgão|Orgao|C[aâ]mara|Turma)[:\s]+([^\n,;]+)", text, re.IGNORECASE
            )
            entry["orgao_julgador"] = orgao_match.group(1).strip() if orgao_match else ""

            # Ementa
            ementa_el = soup.select_one(".ementa, .corpo-ementa, p[class*='ementa']")
            if ementa_el:
                entry["ementa_trecho"] = re.sub(r"\s+", " ", ementa_el.get_text(strip=True))[:500]
            else:
                for p in soup.find_all(["p", "div", "span"]):
                    ptext = p.get_text(strip=True)
                    if len(ptext) > 100:
                        entry["ementa_trecho"] = re.sub(r"\s+", " ", ptext)[:500]
                        break
                else:
                    entry["ementa_trecho"] = text[:500]

            entry["classe_cnj"] = ""
            entry["assunto_cnj"] = ""
            entry["tipo_processo"] = ""
            entry["search_terms"] = query

            return entry
        except Exception as e:
            logger.debug(f"TJRJ: Parse error: {e}")
            return None

    def _go_to_next_page_tjrj(self, current_page: int) -> bool:
        """Navigate to next page in TJRJ results."""
        next_page = current_page + 1
        selectors = [
            f"//a[text()='{next_page}']",
            f"//a[contains(@href, 'pagina={next_page}')]",
            f"//a[contains(@href, 'page={next_page}')]",
            "//a[contains(text(), 'Próximo')]",
            "//a[contains(text(), 'Seguinte')]",
            "//a[contains(@class, 'next')]",
        ]
        for selector in selectors:
            try:
                elem = self.driver.find_element(By.XPATH, selector)
                if elem.is_displayed():
                    self.driver.execute_script("arguments[0].click();", elem)
                    time.sleep(3)
                    return True
            except Exception:
                continue
        return False

    def search_with_criteria(self, criteria: SearchCriteria) -> List[Dict[str, Any]]:
        """Search using a SearchCriteria object."""
        filters = {
            "tipo_decisao": criteria.tipo_decisao,
            "data_julgamento_inicio": criteria.data_julgamento_inicio,
            "data_julgamento_fim": criteria.data_julgamento_fim,
            "data_publicacao_inicio": criteria.data_publicacao_inicio,
            "data_publicacao_fim": criteria.data_publicacao_fim,
            "relator": criteria.relator,
            "orgao_julgador": criteria.orgao_julgador,
            "comarca_origem": criteria.comarca_origem,
            "classe_cnj": criteria.classe_cnj,
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
        """Download inteiro teor from TJRJ."""
        if save_dir is None:
            save_dir = os.path.abspath(
                os.path.join(os.getcwd(), "workspace", "TJRJ_jurisprudencia")
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
            "tribunal": "TJRJ",
            "agent_id": agent_id,
            "download_timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        })

        try:
            self.driver.get(url)
            time.sleep(3)
            current_url = self.driver.current_url
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/pdf,*/*",
            }

            try:
                cookies = self.driver.get_cookies()
                session = requests.Session()
                for c in cookies:
                    session.cookies.set(c["name"], c["value"])
                resp = session.get(current_url, headers=headers, timeout=30)
                content_type = resp.headers.get("content-type", "").lower()
                if "application/pdf" in content_type:
                    content = resp.content
                    ext = "pdf"
                else:
                    content = self.driver.page_source.encode("utf-8")
                    ext = "html"
            except Exception:
                content = self.driver.page_source.encode("utf-8")
                ext = "html"
                content_type = ""

            if not filename:
                num = metadata.get("numero_processo", "unknown")
                filename = f"inteiro_teor_{num}.{ext}"

            filepath = os.path.join(final_save_dir, filename)
            with open(filepath, "wb") as f:
                f.write(content)

            if ext == "pdf":
                from modules.download_utils import _verify_pdf_complete
                try:
                    _verify_pdf_complete(filepath)
                except Exception as verify_exc:
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass
                    logger.error(f"TJRJ: incomplete PDF discarded from {current_url}: {verify_exc}")
                    return None

            sidecar = {
                "downloaded_at": datetime.utcnow().isoformat() + "Z",
                "download_url": current_url,
                "source_url": url,
                "content_type": content_type,
                "file_size_bytes": len(content),
                "tribunal": "TJRJ",
            }
            sidecar.update(metadata)
            write_sidecar_metadata(filepath, sidecar)

            return filepath
        except Exception as e:
            logger.error(f"TJRJ: Download failed: {e}")
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
        """Download inteiro teor for all results."""
        if save_dir is None:
            save_dir = os.path.abspath(
                os.path.join(os.getcwd(), "workspace", "TJRJ_jurisprudencia")
            )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_parts = [p for p in [agent_id, folder_name, timestamp] if p]
        final_save_dir = os.path.join(save_dir, *folder_parts)
        os.makedirs(final_save_dir, exist_ok=True)

        saved_files = []
        for idx, res in enumerate(results, 1):
            url = res.get("inteiro_url")
            if not url:
                continue
            logger.info(f"TJRJ: Downloading ({idx}/{len(results)})")
            saved = self.download_inteiro_teor_url(
                url,
                save_dir=final_save_dir,
                metadata={
                    "numero_processo": res.get("numero_processo"),
                    "tribunal": "TJRJ",
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
        """Normalize a TJRJ inteiro teor URL."""
        raw = (raw_url or "").replace("&amp;", "&").strip()
        if raw.startswith("/"):
            raw = f"{TJRJ_BASE_URL}{raw}"
        return {
            "source_url": raw,
            "url": raw,
            "is_canonical": True,
            "numero_processo": fallback_num,
        }

    def close(self):
        if self.driver:
            self.driver.quit()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
