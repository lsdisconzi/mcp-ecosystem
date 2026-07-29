"""
STF (Supremo Tribunal Federal) Jurisprudence Scraper.

Uses HTTP requests for search (no captcha required) with Selenium
fallback for downloads. The STF jurisprudence portal is the simplest
of the three courts — GET-based search with simple pagination.

Interface matches TJRSJurisprudenciaScraper for drop-in compatibility.
"""

import os
import re
import time
import json
import logging
import urllib3
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from _shared.chrome_driver import (
    create_chrome_driver,
    write_sidecar_metadata,
    infer_extension,
)

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
    search_index: str = "ementa"  # "acordao" or "monocraticas"
    max_results: int = 20


# ── STF-specific constants ───────────────────────────────────────────────────

STF_BASE_URL = "https://www.stf.jus.br"
STF_SEARCH_URL = f"{STF_BASE_URL}/portal/jurisprudencia/listarConsolidada.asp"
STF_INTEIRO_TEOR_BASE = f"{STF_BASE_URL}/portal/inteiroTeor"

# Database mapping
BASE_MAP = {
    "acordao": "baseAcordaos",
    "acórdão": "baseAcordaos",
    "acordãos": "baseAcordaos",
    "ementa": "baseAcordaos",
    "inteiro_teor": "baseAcordaos",
    "monocratica": "baseMonocraticas",
    "monocrática": "baseMonocraticas",
    "decisao_monocratica": "baseMonocraticas",
}


class STFJurisprudenciaScraper:
    """Scraper for STF jurisprudence.

    Uses HTTP requests for search (STF has no captcha) and
    Selenium for downloads as needed.
    """

    def __init__(self, headless=True, wait_time=30):
        self.wait_time = wait_time
        self.driver = None
        self._driver_headless = headless
        self._session = requests.Session()
        # STF uses ICP-Brasil certificates which are not in standard CA bundles.
        # The ICP-Brasil PKI hierarchy (ICP-Brasil → AC Raiz → AC intermediárias)
        # is a government-operated CA that standard root stores don't include.
        # Setting verify=False accepts any certificate — exposed to MITM on the
        # network path between this server and STF's portal.
        #
        # To use proper verification, obtain the ICP-Brasil CA chain from
        # https://www.gov.br/iti/pt-br/assuntos/repositorio/cadeia-de-certificados
        # and set JURIS_SEARCH_STF_SSL_BUNDLE=/path/to/icp-brasil-ca-bundle.pem
        #
        # If the env var is absent or empty, verification is disabled (backward compatible).
        _ssl_bundle = os.environ.get("JURIS_SEARCH_STF_SSL_BUNDLE", "").strip()
        if _ssl_bundle:
            self._session.verify = _ssl_bundle
            logger.info("STF: SSL verification enabled with bundle: %s", _ssl_bundle)
        else:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            self._session.verify = False
            logger.warning("STF: SSL verification DISABLED — MITM risk. "
                           "Set JURIS_SEARCH_STF_SSL_BUNDLE to enable.")
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        })

    def _ensure_driver(self):
        """Lazily initialize Selenium WebDriver (only when needed for downloads)."""
        if self.driver is not None:
            return
        self.driver = create_chrome_driver(headless=self._driver_headless)

    # ── Search ────────────────────────────────────────────────────────────

    def _resolve_base(self, search_index: Optional[str]) -> str:
        key = (search_index or "ementa").strip().lower()
        return BASE_MAP.get(key, "baseAcordaos")

    def _format_date_for_stf(self, date_str: Optional[str]) -> str:
        """Convert various date formats to dd/mm/aaaa for STF."""
        if not date_str:
            return ""
        date_str = date_str.strip()
        if re.match(r"^\d{2}/\d{2}/\d{4}$", date_str):
            return date_str
        iso_match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", date_str)
        if iso_match:
            return f"{iso_match.group(3)}/{iso_match.group(2)}/{iso_match.group(1)}"
        return date_str

    def _build_search_url(
        self,
        query: str,
        search_index: str = "ementa",
        filters: Optional[Dict[str, Optional[str]]] = None,
    ) -> str:
        """Build the search URL with query parameters."""
        filters = filters or {}
        base = self._resolve_base(search_index)

        params = {
            "base": base,
            "txtPesquisaLivre": query or "",
        }

        # Add date filters
        data_inicial = self._format_date_for_stf(
            filters.get("data_julgamento_inicio") or filters.get("dtJulgamentoInicio")
        )
        data_final = self._format_date_for_stf(
            filters.get("data_julgamento_fim") or filters.get("dtJulgamentoFim")
        )
        if data_inicial:
            params["dataInicial"] = data_inicial
        if data_final:
            params["dataFinal"] = data_final

        return f"{STF_SEARCH_URL}?{urlencode(params)}"

    def _parse_page_count(self, soup: BeautifulSoup) -> int:
        """Extract total page count from the STF results page."""
        try:
            link_pagina = soup.select_one(".linkPagina")
            if link_pagina:
                text = link_pagina.get_text(strip=True)
                numbers = re.findall(r"\d+", text)
                if numbers:
                    total = int(numbers[-1])
                    pages = (total + 9) // 10  # 10 results per page
                    return max(1, pages)
        except Exception:
            pass
        return 1

    def _extract_tinyurl(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract the tinyURL segment from the page for pagination."""
        try:
            link_pagina = soup.select_one(".linkPagina")
            if link_pagina:
                href = link_pagina.get("href", "")
                if href:
                    return href
        except Exception:
            pass
        return None

    def _parse_result_block(self, div_element) -> Optional[Dict[str, Any]]:
        """Parse a single result div into a dict."""
        try:
            entry: Dict[str, Any] = {
                "tribunal": "STF",
            }

            # Get the strong metadata block
            strong = div_element.select_one("p > strong")
            if not strong:
                return None

            text = strong.get_text("\n", strip=True)
            lines = [l.strip() for l in text.split("\n") if l.strip()]

            if len(lines) < 6:
                return None

            # Parse processo/origem from first line
            first_line = lines[0] if lines else ""
            if "/" in first_line:
                parts = first_line.split("/", 1)
                entry["numero_processo"] = parts[0].strip()
                entry["origem"] = parts[1].strip() if len(parts) > 1 else ""
            else:
                entry["numero_processo"] = first_line
                entry["origem"] = ""

            # Classe is typically the 6th line
            entry["classe_cnj"] = lines[5] if len(lines) > 5 else ""

            # Relator extraction
            relator_match = re.search(r"Relator\(a\):\s*(.+)", text)
            if relator_match:
                relator_raw = relator_match.group(1).strip()
                # Extract "Min. Name"
                min_match = re.search(r"Min\.\s*(.+)", relator_raw)
                if min_match:
                    entry["relator"] = f"Min. {min_match.group(1).strip()}"
                else:
                    entry["relator"] = relator_raw
            else:
                entry["relator"] = ""

            # Data julgamento
            date_match = re.search(r"(\d{2}/\d{2}/\d{4})", text)
            if date_match:
                entry["data_julgamento"] = date_match.group(1)
            else:
                entry["data_julgamento"] = ""

            # Órgão julgador
            orgao_match = re.search(r"(?:Órgão|orgao)\s*Julgador:\s*(.+)", text, re.IGNORECASE)
            if orgao_match:
                entry["orgao_julgador"] = orgao_match.group(1).strip()
            else:
                entry["orgao_julgador"] = ""

            # Ementa
            ementa_div = div_element.select_one("div[style*='line-height: 150%']")
            if ementa_div:
                entry["ementa_trecho"] = ementa_div.get_text(strip=True)[:500]
            else:
                entry["ementa_trecho"] = ""

            # Data publicação
            pub_elem = div_element.select_one("p:has(strong)")
            if pub_elem and "Publicação" in pub_elem.get_text():
                pub_text = pub_elem.get_text()
                pub_match = re.search(r"(\d{2}/\d{2}/\d{4})", pub_text)
                if pub_match:
                    entry["data_publicacao"] = pub_match.group(1)
                else:
                    entry["data_publicacao"] = ""
            else:
                entry["data_publicacao"] = ""

            # Inteiro teor URL
            inteiro_links = div_element.select("a[href*='obterInteiroTeor']")
            if inteiro_links:
                href = inteiro_links[0].get("href", "")
                if href:
                    if href.startswith("/"):
                        href = f"{STF_BASE_URL}{href}"
                    entry["inteiro_url"] = href
                else:
                    entry["inteiro_url"] = None
            else:
                # Try to find any link to inteiro teor
                for a in div_element.select("a[href]"):
                    href = a.get("href", "")
                    if "inteiroTeor" in href or "obterInteiroTeor" in href:
                        if href.startswith("/"):
                            href = f"{STF_BASE_URL}{href}"
                        entry["inteiro_url"] = href
                        break
                else:
                    entry["inteiro_url"] = None

            return entry
        except Exception as e:
            logger.debug(f"STF: error parsing result block: {e}")
            return None

    def get_inteiro_links(
        self,
        query: str,
        max_results: int = 20,
        search_index: str = "ementa",
        filters: Optional[Dict[str, Optional[str]]] = None,
    ) -> List[Dict[str, Any]]:
        """Search STF jurisprudence and return list of result dicts.

        Uses HTTP GET requests — STF has no captcha for search.
        """
        filters = filters or {}
        search_url = self._build_search_url(query, search_index, filters)
        logger.info(f"STF: searching: {search_url}")

        entries: List[Dict[str, Any]] = []
        seen_nums = set()

        try:
            # First request
            resp = self._session.get(search_url, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Determine total pages
            total_pages = self._parse_page_count(soup)
            tinyurl = self._extract_tinyurl(soup)
            logger.info(f"STF: {total_pages} pages available")

            # Process pages
            for page_num in range(1, min(total_pages + 1, 50)):
                if len(entries) >= max_results:
                    break

                if page_num > 1:
                    if tinyurl:
                        page_url = f"{STF_BASE_URL}/portal/jurisprudencia/{tinyurl}&pagina={page_num}"
                    else:
                        page_url = f"{search_url}&pagina={page_num}"
                    logger.info(f"STF: loading page {page_num}: {page_url}")
                    resp = self._session.get(page_url, timeout=30)
                    resp.raise_for_status()
                    soup = BeautifulSoup(resp.text, "html.parser")

                # Find result divs
                result_divs = soup.select("div.processosJurisprudenciaAcordaos")
                logger.info(f"STF: found {len(result_divs)} result blocks on page {page_num}")

                for div in result_divs:
                    if len(entries) >= max_results:
                        break
                    entry = self._parse_result_block(div)
                    if entry and entry.get("numero_processo"):
                        num = entry["numero_processo"]
                        if num in seen_nums:
                            continue
                        seen_nums.add(num)
                        entry["page"] = page_num
                        entry["search_terms"] = query
                        entries.append(entry)
                        logger.info(f"STF: found result {len(entries)}: {num} - {entry.get('relator')}")

        except requests.RequestException as e:
            logger.error(f"STF: HTTP request failed: {e}")
        except Exception as e:
            logger.error(f"STF: search error: {e}")

        logger.info(f"STF: total results collected: {len(entries)}")
        return entries

    def search_with_criteria(self, criteria: SearchCriteria) -> List[Dict[str, Any]]:
        """Search using a SearchCriteria object."""
        filters = {
            "data_julgamento_inicio": criteria.data_julgamento_inicio,
            "data_julgamento_fim": criteria.data_julgamento_fim,
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
        ext = infer_extension(url, content_type)
        if ext == "bin":
            return "pdf"  # STF default
        return ext

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
        """Download the inteiro teor document from an STF URL.

        STF downloads are typically PDFs with no captcha.
        """
        if save_dir is None:
            save_dir = os.path.abspath(os.path.join(os.getcwd(), "workspace", "STF_jurisprudencia"))

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
            "tribunal": "STF",
        })

        try:
            download_url = url
            if download_url.startswith("/"):
                download_url = f"{STF_BASE_URL}{download_url}"

            # Try direct download first
            resp = self._session.get(download_url, timeout=30, allow_redirects=True)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "").lower()
            ext = self._infer_extension(download_url, content_type)

            # Extract process number for filename
            num_processo = metadata.get("numero_processo", "")
            if not num_processo:
                # Try to extract from URL
                num_match = re.search(r"numero=(\d+)", download_url)
                if num_match:
                    num_processo = num_match.group(1)

            if "text/html" in content_type:
                # STF might return an HTML page with embedded PDF viewer
                soup = BeautifulSoup(resp.text, "html.parser")
                # Look for iframe or embed with PDF
                for tag in soup.select("iframe, embed, object"):
                    src = tag.get("src", "")
                    if src and ".pdf" in src.lower():
                        if src.startswith("/"):
                            src = f"{STF_BASE_URL}{src}"
                        pdf_resp = self._session.get(src, timeout=30)
                        pdf_resp.raise_for_status()
                        resp = pdf_resp
                        content_type = "application/pdf"
                        ext = "pdf"
                        break

            if not filename:
                classe = metadata.get("classe", "")
                num = num_processo or "unknown"
                filename = f"inteiro_teor_{num}_{classe}.{ext}" if classe else f"inteiro_teor_{num}.{ext}"

            filepath = os.path.join(final_save_dir, filename)
            content = resp.content if "text/html" not in content_type else resp.text.encode("utf-8")
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
                    logger.error(f"STF: incomplete PDF discarded from {download_url}: {verify_exc}")
                    return None

            sidecar = {
                "downloaded_at": datetime.utcnow().isoformat() + "Z",
                "download_url": download_url,
                "source_url": url,
                "numero_processo": num_processo,
                "content_type": content_type,
                "file_size_bytes": len(content),
                "tribunal": "STF",
            }
            sidecar.update(metadata)
            self._write_sidecar_metadata(filepath, sidecar)

            logger.info(f"STF: saved inteiro teor to {filepath}")
            return filepath

        except requests.RequestException as e:
            logger.warning(f"STF: HTTP download failed: {e}, trying Selenium fallback...")
            return self._download_via_selenium(url, filename, final_save_dir, metadata)

        except Exception as e:
            logger.error(f"STF: download failed: {e}")
            return None

    def _download_via_selenium(
        self,
        url: str,
        filename: Optional[str],
        save_dir: str,
        metadata: Dict[str, Any],
    ) -> Optional[str]:
        """Fallback download using Selenium for pages that require JS."""
        try:
            self._ensure_driver()
            download_url = url
            if download_url.startswith("/"):
                download_url = f"{STF_BASE_URL}{download_url}"

            self.driver.get(download_url)
            time.sleep(3)

            if not filename:
                filename = f"inteiro_teor_stf_{int(time.time())}.pdf"

            filepath = os.path.join(save_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)

            self._write_sidecar_metadata(filepath, {
                "downloaded_at": datetime.utcnow().isoformat() + "Z",
                "download_url": download_url,
                "fetch_mode": "selenium_fallback",
                "tribunal": "STF",
                **(metadata or {}),
            })

            logger.info(f"STF: saved via Selenium to {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"STF: Selenium fallback also failed: {e}")
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
            save_dir = os.path.abspath(os.path.join(os.getcwd(), "workspace", "STF_jurisprudencia"))

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
                    "tribunal": "STF",
                }, f, indent=2, ensure_ascii=False)

        saved_files = []
        for idx, res in enumerate(results, 1):
            url = res.get("inteiro_url")
            if not url:
                logger.warning(f"STF: result {idx} missing 'inteiro_url', skipping")
                continue

            num = res.get("numero_processo", "unknown")
            existing_matches = [
                os.path.join(final_save_dir, name)
                for name in os.listdir(final_save_dir)
                if str(num) in name
            ]

            if existing_matches and not overwrite:
                logger.info(f"STF: skipping existing file: {existing_matches[0]}")
                saved_files.append(existing_matches[0])
                continue

            logger.info(f"STF: downloading ({idx}/{len(results)}): {num}")
            saved = self.download_inteiro_teor_url(
                url,
                save_dir=final_save_dir,
                metadata={
                    "numero_processo": num,
                    "classe": res.get("classe_cnj"),
                    "relator": res.get("relator"),
                    "tribunal": "STF",
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
                logger.warning(f"STF: failed to download: {num}")

            if delay and idx < len(results):
                time.sleep(delay)

        return saved_files

    def canonicalize_inteiro_url(self, raw_url: str, fallback_num: Optional[str] = None) -> Dict[str, Optional[str]]:
        """Extract canonical parameters from an STF inteiro teor URL."""
        raw = (raw_url or "").replace("&amp;", "&").strip()
        if raw.startswith("/"):
            raw = f"{STF_BASE_URL}{raw}"

        numero_match = re.search(r"numero=(\d+)", raw)
        classe_match = re.search(r"classe=([^&\s]+)", raw)

        return {
            "source_url": raw,
            "numero_processo": numero_match.group(1) if numero_match else fallback_num,
            "classe": classe_match.group(1) if classe_match else None,
            "url": raw,
            "is_canonical": bool(numero_match),
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
    scraper = STFJurisprudenciaScraper(headless=True)
    try:
        query = "repercussão geral"
        max_results = 20
        print(f"STF: searching for '{query}'...")
        results = scraper.get_inteiro_links(query, max_results=max_results)
        print(f"Found {len(results)} results")
        for r in results[:5]:
            print(f"  - {r.get('numero_processo')} | {r.get('relator')} | {r.get('data_julgamento')}")
            print(f"    Inteiro teor: {r.get('inteiro_url', 'N/A')[:80]}")
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        scraper.close()
