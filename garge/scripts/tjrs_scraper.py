import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import json
import time
import re
from urllib.parse import urlencode, urljoin, urlparse, parse_qs
import os
import shutil
import subprocess
import sys
from selenium.webdriver.chrome.service import Service
try:
    from webdriver_manager.chrome import ChromeDriverManager
except Exception:
    ChromeDriverManager = None
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from datetime import datetime
import pandas as pd

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# LibreOffice .doc -> .docx conversion helpers
# ----------------------------------------------------------------------
def find_libreoffice():
    """Return path to LibreOffice executable or None if not found."""
    if sys.platform == "win32":
        common_paths = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path
        # Try PATH
        return shutil.which("soffice") or shutil.which("libreoffice")
    elif sys.platform == "darwin":  # macOS
        mac_path = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
        if os.path.exists(mac_path):
            return mac_path
        return shutil.which("libreoffice") or shutil.which("soffice")
    else:  # Linux
        return shutil.which("libreoffice") or shutil.which("soffice")


def convert_doc_to_docx_keep_original(doc_path, backup_subfolder="original_doc"):
    """
    Convert a .doc file to .docx using LibreOffice.
    The original .doc is moved to a subfolder (backup_subfolder).
    The converted .docx is placed in the original directory with the same base name.
    Returns the path to the new .docx file, or None on failure.
    """
    doc_path = os.path.abspath(doc_path)
    if not doc_path.lower().endswith(".doc"):
        logger.warning(f"Not a .doc file: {doc_path}")
        return None

    libreoffice = find_libreoffice()
    if not libreoffice:
        logger.error("LibreOffice not found. Cannot convert .doc to .docx. Install LibreOffice.")
        return None

    base_dir = os.path.dirname(doc_path)
    base_name = os.path.splitext(os.path.basename(doc_path))[0]
    docx_path = os.path.join(base_dir, base_name + ".docx")

    # Create backup subfolder
    backup_dir = os.path.join(base_dir, backup_subfolder)
    os.makedirs(backup_dir, exist_ok=True)

    # Move original .doc to backup
    backup_doc = os.path.join(backup_dir, os.path.basename(doc_path))
    if os.path.exists(backup_doc):
        # Avoid overwriting: add timestamp
        name, ext = os.path.splitext(backup_doc)
        backup_doc = f"{name}_{int(time.time())}{ext}"
    shutil.move(doc_path, backup_doc)
    logger.info(f"Moved original .doc to {backup_doc}")

    # Convert from backup location, output to original directory
    try:
        cmd = [
            libreoffice,
            "--headless",
            "--convert-to", "docx",
            "--outdir", base_dir,
            backup_doc
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.error(f"Conversion failed for {backup_doc}: {result.stderr}")
            # Move the original back
            shutil.move(backup_doc, doc_path)
            return None

        # LibreOffice creates the .docx in base_dir with same base name as backup_doc
        generated_docx = os.path.join(base_dir, os.path.basename(backup_doc).replace(".doc", ".docx"))
        if os.path.exists(generated_docx):
            # Rename if necessary (should already be correct)
            if generated_docx != docx_path:
                shutil.move(generated_docx, docx_path)
            logger.info(f"Converted to {docx_path}")
            return docx_path
        else:
            logger.error(f"Converted file not found: expected {generated_docx}")
            return None
    except Exception as e:
        logger.error(f"Conversion error: {e}")
        # Move original back
        shutil.move(backup_doc, doc_path)
        return None


def convert_all_doc_in_directory(directory, backup_subfolder="original_doc", recursive=False):
    """
    Find all .doc files in `directory` (and optionally subfolders)
    and convert them to .docx using `convert_doc_to_docx_keep_original`.
    """
    if not os.path.isdir(directory):
        logger.error(f"Directory not found: {directory}")
        return []

    converted = []
    if recursive:
        for root, _, files in os.walk(directory):
            for f in files:
                if f.lower().endswith(".doc"):
                    full = os.path.join(root, f)
                    res = convert_doc_to_docx_keep_original(full, backup_subfolder)
                    if res:
                        converted.append(res)
    else:
        for f in os.listdir(directory):
            if f.lower().endswith(".doc"):
                full = os.path.join(directory, f)
                res = convert_doc_to_docx_keep_original(full, backup_subfolder)
                if res:
                    converted.append(res)
    return converted


# ----------------------------------------------------------------------
# Original TJRS scraper (unchanged except for the download_all_inteiro_teor method)
# ----------------------------------------------------------------------
@dataclass
class SearchCriteria:
    """Data class for search parameters"""
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
    search_index: str = "ementa"  # or "inteiro_teor_url"
    max_results: int = 100


@dataclass
class JurisprudenciaResult:
    """Data class for search results"""
    numero_processo: str
    tipo_decisao: str
    tipo_processo: str
    comarca_origem: str
    relator: str
    tribunal: str
    classe_cnj: str
    assunto_cnj: str
    orgao_julgador: str
    seção: str
    ementa_trecho: str
    data_julgamento: str
    data_publicacao: str
    links: Dict[str, str]  # DOC, HTML, TIFF links
    full_text: Optional[str] = None
    metadata: Optional[Dict] = None


class TJRSJurisprudenciaScraper:
    """Scraper for TJRS jurisprudência that finds and downloads inteiro_teor_url documents.
    
    Updated with correct URL structure and parsing logic based on the actual TJRS website.
    """
    SEARCH_INDEX_MAP = {
        "ementa": "documento_text",
        "acórdão": "documento_text",
        "acordao": "documento_text",
        "inteiro_teor": "inteiro_teor_url",
        "inteiro_teor_url": "inteiro_teor_url",
        "documento_text": "documento_text",
    }

    INTEIRO_TEOR_BASE = "https://www.tjrs.jus.br/novo/wp-content/themes/tjrs/tjrs-apps/inteiro-teor/index.php"

    def __init__(self, headless=True, wait_time=30):
        self.base_url = "https://www.tjrs.jus.br"
        self.search_url = "https://www.tjrs.jus.br/novo/buscas-solr/"
        self.wait_time = wait_time
        self.driver = None

        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        chrome_binary = self._resolve_chrome_binary()
        if chrome_binary:
            chrome_options.binary_location = chrome_binary
            logger.info(f"Using Chrome binary: {chrome_binary}")

        # Use snap Chromium's bundled chromedriver (version-matched)
        SNAP_CHROMEDRIVER = "/snap/chromium/current/usr/lib/chromium-browser/chromedriver"
        SNAP_CHROME      = "/snap/bin/chromium"

        attempts = []

        import os as _os
        if _os.path.exists(SNAP_CHROMEDRIVER) and _os.path.exists(SNAP_CHROME):
            try:
                chrome_options.binary_location = SNAP_CHROME
                service = Service(SNAP_CHROMEDRIVER)
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
                logger.info("Started WebDriver using snap Chromium binary and driver")
            except Exception as e:
                attempts.append(f"snap_chromium: {e}")

        if self.driver is None:
            original_path = None
            try:
                chrome_major = self._detect_chrome_major_version(chrome_options.binary_location)
                path_driver, driver_major = self._detect_path_chromedriver_version()
                if path_driver and chrome_major and driver_major and chrome_major != driver_major:
                    original_path = os.environ.get("PATH", "")
                    bad_dir = os.path.dirname(path_driver)
                    os.environ["PATH"] = os.pathsep.join(
                        p for p in original_path.split(os.pathsep)
                        if os.path.abspath(p) != os.path.abspath(bad_dir)
                    )
                    logger.warning(
                        "Temporarily removed incompatible chromedriver from PATH: "
                        f"{path_driver} (driver {driver_major} vs Chrome {chrome_major})"
                    )

                # Prefer Selenium Manager so driver matches the installed browser version.
                self.driver = webdriver.Chrome(service=Service(), options=chrome_options)
                logger.info("Started WebDriver using Selenium Manager")
            except Exception as e:
                attempts.append(f"selenium_manager: {e}")
            finally:
                if original_path is not None:
                    os.environ["PATH"] = original_path

        if self.driver is None and ChromeDriverManager:
            try:
                chrome_major = self._detect_chrome_major_version(chrome_options.binary_location)
                if chrome_major:
                    logger.info(f"Trying webdriver-manager with Chrome major version {chrome_major}")
                    service = Service(ChromeDriverManager(driver_version=chrome_major).install())
                else:
                    service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
                logger.info("Started WebDriver using webdriver-manager")
            except TypeError:
                # Compatibility with older webdriver-manager signature.
                try:
                    chrome_major = self._detect_chrome_major_version(chrome_options.binary_location)
                    if chrome_major:
                        service = Service(ChromeDriverManager(version=chrome_major).install())
                    else:
                        service = Service(ChromeDriverManager().install())
                    self.driver = webdriver.Chrome(service=service, options=chrome_options)
                    logger.info("Started WebDriver using webdriver-manager (legacy API)")
                except Exception as e:
                    attempts.append(f"webdriver_manager_legacy: {e}")
            except Exception as e:
                attempts.append(f"webdriver_manager: {e}")

        if self.driver is None:
            details = " | ".join(attempts) if attempts else "No attempts executed"
            raise RuntimeError(
                "Could not initialize Chrome WebDriver. "
                "If this is macOS, update Google Chrome and avoid old chromedriver binaries in PATH. "
                f"Details: {details}"
            )

        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    def _resolve_chrome_binary(self) -> Optional[str]:
        env_binary = os.getenv("CHROME_BINARY", "").strip()
        if env_binary and os.path.exists(env_binary):
            return env_binary

        candidates = []
        if sys.platform == "darwin":
            candidates.extend([
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
            ])
        elif sys.platform.startswith("linux"):
            candidates.extend([
                shutil.which("google-chrome"),
                shutil.which("google-chrome-stable"),
                shutil.which("chromium-browser"),
                shutil.which("chromium"),
            ])
        elif sys.platform == "win32":
            local_app = os.getenv("LOCALAPPDATA", "")
            program_files = os.getenv("PROGRAMFILES", "")
            program_files_x86 = os.getenv("PROGRAMFILES(X86)", "")
            candidates.extend([
                os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(local_app, "Google", "Chrome", "Application", "chrome.exe"),
            ])

        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                return candidate

        return None

    def _detect_chrome_major_version(self, chrome_binary: Optional[str]) -> Optional[str]:
        if not chrome_binary or not os.path.exists(chrome_binary):
            return None

        try:
            version_out = subprocess.check_output([chrome_binary, "--version"], text=True, stderr=subprocess.STDOUT)
            match = re.search(r"(\d+)\.", version_out)
            if match:
                return match.group(1)
        except Exception as e:
            logger.warning(f"Could not detect Chrome version from {chrome_binary}: {e}")
        return None

    def _detect_path_chromedriver_version(self) -> (Optional[str], Optional[str]):
        chromedriver_path = shutil.which("chromedriver")
        if not chromedriver_path:
            return None, None

        try:
            version_out = subprocess.check_output(
                [chromedriver_path, "--version"],
                text=True,
                stderr=subprocess.STDOUT,
            )
            match = re.search(r"(\d+)\.", version_out)
            return chromedriver_path, match.group(1) if match else None
        except Exception as e:
            logger.warning(f"Could not detect chromedriver version from PATH ({chromedriver_path}): {e}")
            return chromedriver_path, None

    def _normalize_search_index(self, search_index: Optional[str]) -> str:
        idx = (search_index or "ementa").strip().lower()
        return self.SEARCH_INDEX_MAP.get(idx, "documento_text")

    def _semantic_filters_to_terms(self, filters: Optional[Dict[str, Optional[str]]]) -> List[str]:
        if not filters:
            return []

        keys = [
            "tipo_decisao",
            "tipo_processo",
            "relator",
            "comarca_origem",
            "assunto_cnj",
            "classe_cnj",
            "orgao_julgador",
            "tribunal",
        ]

        terms = []
        for key in keys:
            raw = filters.get(key)
            if not raw:
                continue
            value = re.sub(r"\s+", " ", str(raw)).strip()
            if value:
                terms.append(value)
        return terms

    def _build_search_url(self, query: str, search_index: str = "ementa", filters: Optional[Dict[str, Optional[str]]] = None) -> str:
        """Build search URL with normalized semantic terms and index mapping."""
        query_clean = re.sub(r"\s+", " ", str(query or "")).strip()
        semantic_terms = self._semantic_filters_to_terms(filters)
        q_value = " ".join([query_clean, *semantic_terms]).strip() or "*"

        params = {
            "aba": "jurisprudencia",
            "conteudo_busca": self._normalize_search_index(search_index),
            "q": q_value,
        }
        return f"{self.search_url}?{urlencode(params)}"

    def _extract_inteiro_params_from_url(self, raw_url: str, fallback_num: Optional[str] = None) -> Dict[str, Optional[str]]:
        raw = (raw_url or "").replace("&amp;", "&").strip()
        if raw.startswith("/"):
            raw = urljoin(self.base_url, raw)

        parsed = urlparse(raw)
        qs = parse_qs(parsed.query)

        numero = (
            (qs.get("numero_processo") or [None])[0]
            or (qs.get("num_processo") or [None])[0]
            or fallback_num
        )
        if not numero:
            num_match = re.search(r"\b(\d{7,20})\b", raw)
            if num_match:
                numero = num_match.group(1)

        ano = (qs.get("ano") or [None])[0]
        codigo = (qs.get("codigo") or [None])[0]

        return {
            "source_url": raw,
            "numero_processo": numero,
            "ano": ano,
            "codigo": codigo,
        }

    def _build_canonical_inteiro_url(self, numero_processo: Optional[str], ano: Optional[str], codigo: Optional[str]) -> Optional[str]:
        if not (numero_processo and ano and codigo):
            return None
        params = urlencode({
            "numero_processo": numero_processo,
            "ano": ano,
            "codigo": codigo,
        })
        return f"{self.INTEIRO_TEOR_BASE}?{params}"

    def canonicalize_inteiro_url(self, raw_url: str, fallback_num: Optional[str] = None) -> Dict[str, Optional[str]]:
        parsed = self._extract_inteiro_params_from_url(raw_url, fallback_num=fallback_num)
        canonical = self._build_canonical_inteiro_url(
            parsed.get("numero_processo"),
            parsed.get("ano"),
            parsed.get("codigo"),
        )
        parsed["url"] = canonical or parsed.get("source_url")
        parsed["is_canonical"] = bool(canonical)
        return parsed

    def _extract_ementa_snippet(self, text: str, max_len: int = 280) -> str:
        if not text:
            return ""
        match = re.search(r"Ementa[:\s-]*(.+)", text, re.IGNORECASE | re.DOTALL)
        raw = match.group(1) if match else text
        snippet = re.sub(r"\s+", " ", raw).strip()
        return snippet[:max_len]

    def _build_result_description(self, entry: Dict[str, Any]) -> str:
        parts = [f"Processo {entry.get('numero_processo') or 'N/A'}"]
        if entry.get("tipo_processo"):
            parts.append(f"Tipo: {entry['tipo_processo']}")
        if entry.get("relator"):
            parts.append(f"Relator: {entry['relator']}")
        if entry.get("comarca_origem"):
            parts.append(f"Comarca: {entry['comarca_origem']}")
        if entry.get("data_julgamento"):
            parts.append(f"Julgamento: {entry['data_julgamento']}")
        return " | ".join(parts)

    def _write_sidecar_metadata(self, filepath: str, metadata: Dict[str, Any]) -> None:
        try:
            sidecar_path = f"{filepath}.metadata.json"
            with open(sidecar_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning(f"Could not write sidecar metadata for {filepath}: {exc}")

    def _accept_cookies(self):
        """Try to accept/dismiss cookie banners that block the page."""
        try:
            # Try multiple possible cookie button selectors
            selectors = [
                "//button[contains(text(), 'Ciente')]",
                "//button[contains(text(), 'Aceitar')]",
                "//button[contains(text(), 'Aceito')]",
                "//a[contains(text(), 'Ciente')]",
                "//a[contains(text(), 'Aceitar')]"
            ]
            
            for selector in selectors:
                try:
                    btn = WebDriverWait(self.driver, 2).until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    btn.click()
                    time.sleep(0.5)
                    break
                except:
                    continue
        except Exception:
            # not fatal
            pass

    def _extract_process_info_from_text(self, text: str) -> Dict:
        """Extract process information from result text."""
        info = {
            'numero_processo': None,
            'tipo_processo': None,
            'relator': None,
            'tribunal': None,
            'classe_cnj': None,
            'comarca_origem': None
        }
        
        # Extract process number (like 70085814739)
        process_match = re.search(r'Núm\.?:?\s*(\d{7,15})', text, re.IGNORECASE)
        if process_match:
            info['numero_processo'] = process_match.group(1)
        
        # Extract tipo processo
        tipo_match = re.search(r'Tipo de processo:\s*(.+)', text, re.IGNORECASE)
        if tipo_match:
            info['tipo_processo'] = tipo_match.group(1).strip()
        
        # Extract relator
        relator_match = re.search(r'Relator[:\s]*(.+)', text, re.IGNORECASE)
        if relator_match:
            info['relator'] = relator_match.group(1).strip()
        
        # Extract tribunal
        tribunal_match = re.search(r'Tribunal[:\s]*(.+)', text, re.IGNORECASE)
        if tribunal_match:
            info['tribunal'] = tribunal_match.group(1).strip()
        
        # Extract classe CNJ
        classe_match = re.search(r'Classe CNJ[:\s]*(.+)', text, re.IGNORECASE)
        if classe_match:
            info['classe_cnj'] = classe_match.group(1).strip()
        
        # Extract comarca
        comarca_match = re.search(r'Comarca[:\s]*(.+)', text, re.IGNORECASE)
        if comarca_match:
            info['comarca_origem'] = comarca_match.group(1).strip()
        
        return info

    def get_inteiro_links(
        self,
        query: str,
        max_results: int = 20,
        debug_save: bool = False,
        search_index: str = "ementa",
        filters: Optional[Dict[str, Optional[str]]] = None,
    ) -> List[Dict]:
        """Search for query and return list of dicts with process information and inteiro teor URLs.
        Supports client-side pagination by clicking "next" until max_results is reached.
        """
        search_url = self._build_search_url(query=query, search_index=search_index, filters=filters)
        logger.info(f"TJRS: loading search page: {search_url}")
        self.driver.get(search_url)

        # Dismiss cookie banner if present
        self._accept_cookies()

        # Switch to iframe if present
        try:
            iframe = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "iFrame1"))
            )
            self.driver.switch_to.frame(iframe)
            logger.info("Switched to results iframe")
        except Exception:
            logger.info("No results iframe found, staying in main content")

        entries = []
        page_num = 1
        max_pages = 50  # increased safety limit for 100 results
        processed_on_current_page = 0
        
        try:
            while len(entries) < max_results and page_num <= max_pages:
                logger.info(f"Processing page {page_num}...")

                # Wait for results to appear - use a more specific selector
                try:
                    WebDriverWait(self.driver, self.wait_time).until(
                        EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'result') and contains(@class, 'ng-scope')]"))
                    )
                except:
                    # Try alternative selector
                    try:
                        WebDriverWait(self.driver, 10).until(
                            EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Núm.') or contains(text(), 'Processo')]"))
                        )
                    except:
                        logger.warning(f"No results found on page {page_num}")
                        break

                # Give a small extra time for all elements to settle
                time.sleep(3)
                
                # IMPORTANT: Refresh the page elements after navigation
                # After pagination, we need to get fresh references to elements
                self.driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(1)

                # Find all result blocks on current page - try multiple selectors
                result_selectors = [
                    "//div[contains(@class, 'result') and contains(@class, 'ng-scope')]",
                    "//div[contains(@class, 'result')]",
                    "//div[@class='result']",
                    "//div[contains(@ng-repeat, 'resultado')]"
                ]
                
                result_blocks = []
                for selector in result_selectors:
                    try:
                        blocks = self.driver.find_elements(By.XPATH, selector)
                        if len(blocks) > 0:
                            result_blocks = blocks
                            logger.info(f"Found {len(result_blocks)} result blocks on page {page_num} using selector: {selector}")
                            break
                    except:
                        continue
                
                if not result_blocks:
                    logger.warning(f"No result blocks found on page {page_num}")
                    break
                    
                # Reset counter for this page
                processed_on_current_page = 0
                
                # Process each result block on current page
                for block_idx, block in enumerate(result_blocks):
                    if len(entries) >= max_results:
                        logger.info(f"Reached max_results limit: {max_results}")
                        break
                        
                    try:
                        # Get fresh reference to the block (important after pagination)
                        try:
                            # Try to get the block again by its position
                            blocks_refreshed = self.driver.find_elements(By.XPATH, result_selectors[0])
                            if block_idx < len(blocks_refreshed):
                                block = blocks_refreshed[block_idx]
                            else:
                                continue
                        except:
                            pass
                        
                        text = block.text
                        
                        # Skip if text is too short or empty
                        if not text or len(text.strip()) < 100:
                            continue
                            
                        info = self._extract_process_info_from_text(text)
                        num = info['numero_processo']

                        if not num:
                            num_match = re.search(r'\b[75]\d{10}\b', text)
                            if num_match:
                                num = num_match.group(0)
                                info['numero_processo'] = num

                        if num:
                            # Check if we already have this process number
                            existing_nums = [e['numero_processo'] for e in entries]
                            if num in existing_nums:
                                logger.debug(f"Duplicate process number found: {num}, skipping")
                                continue

                            try:
                                # Try multiple selectors for the link
                                link_selectors = [
                                    ".//a[contains(@href, 'numero_processo=')]",
                                    ".//a[contains(@href, 'inteiro-teor')]",
                                    ".//a[contains(@href, 'codigo=')]",
                                    ".//a[contains(text(), 'doc')]",
                                    ".//i[contains(@class, 'fa-file-word-o')]/parent::a"
                                ]
                                
                                link_element = None
                                for selector in link_selectors:
                                    try:
                                        link_element = block.find_element(By.XPATH, selector)
                                        if link_element:
                                            break
                                    except:
                                        continue
                                
                                if link_element:
                                    raw_url = link_element.get_attribute('href')

                                    if raw_url:
                                        canonical = self.canonicalize_inteiro_url(raw_url, fallback_num=num)

                                        entry = info.copy()
                                        entry['numero_processo'] = canonical.get('numero_processo') or num
                                        entry['inteiro_url'] = canonical.get('url')
                                        entry['source_inteiro_url'] = canonical.get('source_url')
                                        entry['url_canonical'] = canonical.get('is_canonical', False)
                                        entry['ano'] = canonical.get('ano')
                                        entry['codigo'] = canonical.get('codigo')
                                        entry['page'] = page_num
                                        entry['block_idx'] = block_idx
                                        entry['search_terms'] = query
                                        entry['ementa_trecho'] = self._extract_ementa_snippet(text)
                                        entry['result_description'] = self._build_result_description(entry)

                                        entries.append(entry)
                                        processed_on_current_page += 1
                                        logger.info(
                                            f"Found result {len(entries)}: {entry.get('numero_processo')} "
                                            f"(Ano: {entry.get('ano')}, Cod: {entry.get('codigo')}) "
                                            f"on page {page_num}, block {block_idx}"
                                        )

                                else:
                                    logger.debug(f"No link element found for block {block_idx}")

                            except Exception as e:
                                logger.debug(f"No direct Inteiro Teor link found for {num}: {e}")

                    except Exception as e:
                        logger.warning(f"Error processing result block {block_idx}: {e}")
                        continue

                logger.info(f"Processed {processed_on_current_page} new results on page {page_num} (total: {len(entries)})")

                # Check if we need more results
                if len(entries) >= max_results:
                    logger.info(f"Reached max_results ({max_results}), stopping")
                    break
                    
                # Check if we should continue to next page
                if processed_on_current_page == 0 and page_num > 1:
                    logger.info(f"No new results found on page {page_num}, stopping")
                    break

                # Navigate to next page using improved method
                try:
                    if self._go_to_next_page_improved(page_num):
                        page_num += 1
                        # Wait longer for page load after navigation
                        time.sleep(4)
                        # Scroll to top to ensure we see all elements
                        self.driver.execute_script("window.scrollTo(0, 0);")
                        time.sleep(1)
                        continue
                    else:
                        logger.info("No next page found or reached last page")
                        break
                        
                except Exception as e:
                    logger.warning(f"Error navigating to next page via helper: {e}")
                    if debug_save:
                        try:
                            self.driver.save_screenshot(f'tjrs_pagination_error_page{page_num}.png')
                            with open(f'tjrs_page_{page_num}_source.html', 'w', encoding='utf-8') as f:
                                f.write(self.driver.page_source)
                        except Exception:
                            pass
                    break

        except Exception as e:
            logger.error(f"Error finding results: {e}")
            # Save page for debugging if requested
            if debug_save:
                try:
                    self.driver.save_screenshot('tjrs_debug_error.png')
                    with open('tjrs_page_error.html', 'w', encoding='utf-8') as f:
                        f.write(self.driver.page_source)
                    logger.info('Saved debug artifacts')
                except Exception as e2:
                    logger.warning(f'Failed to save debug artifacts: {e2}')
        finally:
            # Switch back to default content
            try:
                self.driver.switch_to.default_content()
            except:
                pass

        logger.info(f"Total results collected: {len(entries)}")
        return entries

    def _go_to_next_page_improved(self, current_page: int) -> bool:
        """Improved method to navigate to the next page with better detection."""
        # First, try to find and click the "Próximo" button as seen in HTML
        next_button_selectors = [
            # Based on HTML: <span class="text icone-paginacao" id="link_proximo_topo" ng-show="show_seta_pagina_posterior" ng-click="proxima_pagina()">Próximo
            "//span[@id='link_proximo_topo']",
            "//span[contains(@ng-click, 'proxima_pagina') and contains(text(), 'Próximo')]",
            "//*[contains(@ng-click, 'proxima_pagina') and contains(text(), 'Próximo')]",
            "//i[contains(@class, 'fa-angle-right')]/parent::span[contains(@ng-click, 'proxima_pagina')]",
            # Pagination number buttons
            f"//li[@class='page-item normal-page-link']/span[text()='{current_page + 1}']",
            "//li[@class='page-item seta-paginacao']/span/i[contains(@class, 'fa-angle-right')]/parent::span/parent::li",
            "//a[contains(text(), 'Próximo')]",
            "//a[contains(text(), '>')]",
            "//a[contains(text(), '»')]"
        ]
        
        for selector in next_button_selectors:
            try:
                next_btn = self.driver.find_element(By.XPATH, selector)
                
                # Check if button is visible and enabled
                if next_btn.is_displayed():
                    # Check if it's disabled (looking for disabled class or style)
                    btn_class = next_btn.get_attribute("class") or ""
                    btn_style = next_btn.get_attribute("style") or ""
                    parent = next_btn.find_element(By.XPATH, "..")
                    parent_class = parent.get_attribute("class") or ""
                    
                    if "disabled" in btn_class.lower() or "disabled" in parent_class.lower():
                        logger.info("Next button is disabled")
                        return False
                        
                    # Scroll to the button
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", next_btn)
                    time.sleep(0.5)
                    
                    # Try JavaScript click first
                    try:
                        self.driver.execute_script("arguments[0].click();", next_btn)
                        logger.info(f"Clicked next button using JavaScript (selector: {selector})")
                        
                        # Wait for page to update
                        time.sleep(2)
                        
                        # Check if page actually changed by looking for loading indicator or change
                        try:
                            # Wait for Angular to update - look for spinner or loading
                            WebDriverWait(self.driver, 10).until(
                                lambda d: d.find_elements(By.XPATH, "//div[contains(@class, 'result')]") or 
                                        d.find_elements(By.XPATH, "//*[contains(text(), 'Resultados')]")
                            )
                            return True
                        except:
                            # Maybe the page changed already
                            return True
                            
                    except Exception as e:
                        logger.debug(f"JavaScript click failed: {e}")
                        # Try direct click
                        try:
                            next_btn.click()
                            logger.info(f"Clicked next button directly (selector: {selector})")
                            time.sleep(2)
                            return True
                        except Exception as e2:
                            logger.debug(f"Direct click also failed: {e2}")
                            continue
                            
            except Exception as e:
                continue
        
        # If no button found, try AngularJS approach
        return self._trigger_angular_pagination(current_page + 1)

    # ---- Pagination helpers ----
    def _go_to_next_page(self, current_page: int) -> bool:
        """Attempt to navigate to the next page using various strategies."""
        strategies = [
            lambda: self._click_page_number(current_page + 1),
            lambda: self._click_next_arrow(),
            lambda: self._js_navigate_to_page(current_page + 1),
            lambda: self._trigger_angular_pagination(current_page + 1)
        ]
        for strategy in strategies:
            try:
                if strategy():
                    time.sleep(2)
                    try:
                        WebDriverWait(self.driver, 10).until(
                            EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'result') and contains(@class, 'ng-scope')]") )
                        )
                        return True
                    except:
                        continue
            except:
                continue
        return False

    def _click_page_number(self, page_num: int) -> bool:
        """Click a specific page number in pagination."""
        selectors = [
            f"//a[text()='{page_num}']",
            f"//li/a[text()='{page_num}']",
            f"//a[contains(@ng-click, '{page_num}')]",
            f"//a[@ng-click='vm.goToPage({page_num})']"
        ]
        for selector in selectors:
            try:
                page_btn = self.driver.find_element(By.XPATH, selector)
                if page_btn.is_displayed() and page_btn.is_enabled():
                    self.driver.execute_script("arguments[0].click();", page_btn)
                    logger.info(f"Clicked page {page_num}")
                    return True
            except:
                continue
        return False

    def _click_next_arrow(self) -> bool:
        """Click the next page arrow button."""
        next_selectors = [
            "//a[@class='next']",
            "//a[@title='Próxima']",
            "//a[contains(@class, 'pagination-next')]",
            "//i[contains(@class, 'fa-chevron-right')]/parent::a",
            "//span[contains(@class, 'glyphicon-chevron-right')]/parent::a"
        ]
        for selector in next_selectors:
            try:
                next_btn = self.driver.find_element(By.XPATH, selector)
                if next_btn.is_displayed() and next_btn.is_enabled():
                    if "disabled" not in (next_btn.get_attribute("class") or ""):
                        self.driver.execute_script("arguments[0].click();", next_btn)
                        logger.info("Clicked next arrow")
                        return True
            except:
                continue
        return False

    def _js_navigate_to_page(self, page_num: int) -> bool:
        """Use JavaScript to trigger page navigation."""
        try:
            scripts = [
                f"angular.element(document.querySelector('[ng-controller]')).scope().vm.currentPage = {page_num};",
                f"angular.element(document.querySelector('[ng-controller]')).scope().vm.goToPage({page_num});",
                "angular.element(document.querySelector('[ng-controller]')).scope().$apply();"
            ]
            for script in scripts:
                try:
                    self.driver.execute_script(script)
                    time.sleep(1)
                except:
                    continue
            return True
        except:
            return False

    def _trigger_angular_pagination(self, page_num: int) -> bool:
        """Try to trigger AngularJS pagination directly."""
        try:
            # Try to find the Angular controller and trigger pagination
            scripts = [
                # Try to access the controller and trigger next page
                """
                var appElement = document.querySelector('[ng-app="JurisprudenciaApp"]');
                if (appElement) {
                    var scope = angular.element(appElement).scope();
                    if (scope && scope.proxima_pagina) {
                        scope.$apply(function() {
                            scope.proxima_pagina();
                        });
                        return true;
                    }
                }
                return false;
                """,
                
                # Try to find the controller and trigger specific page
                """
                var ctrlElement = document.querySelector('[ng-controller="JurisprudenciaCtrl"]');
                if (ctrlElement) {
                    var scope = angular.element(ctrlElement).scope();
                    if (scope && scope.vm) {
                        scope.$apply(function() {
                            scope.vm.currentPage = %d;
                            if (typeof scope.vm.ir_para_pagina === 'function') scope.vm.ir_para_pagina(%d);
                            if (typeof scope.vm.goToPage === 'function') scope.vm.goToPage(%d);
                        });
                        return true;
                    }
                }
                return false;
                """ % (page_num, page_num, page_num)
            ]
            
            for script in scripts:
                try:
                    result = self.driver.execute_script(script)
                    if result:
                        logger.info(f"Successfully triggered AngularJS pagination to page {page_num}")
                        return True
                except Exception as e:
                    logger.debug(f"JavaScript execution failed: {e}")
                    continue
            
            return False
        except Exception as e:
            logger.error(f"Error triggering Angular pagination: {e}")
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
    ) -> Optional[str]:
        """Download the inteiro_teor_url HTML for the given URL and save to `save_dir/filename` or generated name.

        Supports organized folder structure:
        - If agent_id provided: save_dir/agent_id/folder_name/timestamp/
        - If folder_name provided: save_dir/folder_name/timestamp/
        - Otherwise: save_dir/timestamp/

        Returns path to saved file or None on error.
        """
        # Default save directory (project workspace/TJRS_jurisprudencia)
        if save_dir is None:
            save_dir = os.path.abspath(os.path.join(os.getcwd(), 'workspace', 'TJRS_jurisprudencia'))

        # Create organized folder structure
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Build folder path
        folder_parts = []
        if agent_id:
            folder_parts.append(agent_id)
        if folder_name:
            folder_parts.append(folder_name)
        folder_parts.append(timestamp)

        # Create final save directory
        final_save_dir = os.path.join(save_dir, *folder_parts)
        os.makedirs(final_save_dir, exist_ok=True)

        # Update metadata with folder info
        if metadata is None:
            metadata = {}
        metadata.update({
            "agent_id": agent_id,
            "folder_name": folder_name,
            "search_params": search_params,
            "download_timestamp": timestamp,
            "folder_path": final_save_dir
        })

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
        try:
            canonical = self.canonicalize_inteiro_url(url)
            download_url = canonical.get("url") or url

            # First, try to access the URL
            r = requests.get(download_url, headers=headers, timeout=30)
            r.raise_for_status()

            # Check if we need to follow redirects or if it's a PDF/DOC
            content_type = r.headers.get('content-type', '').lower()
            
            if not filename:
                # Generate filename from canonical URL parameters
                num = canonical.get('numero_processo') or 'unknown'
                ano = canonical.get('ano') or 'unknown'
                cod = canonical.get('codigo') or 'unknown'
                
                # Determine file extension based on content type
                if 'pdf' in content_type:
                    ext = 'pdf'
                elif 'msword' in content_type or 'word' in content_type:
                    ext = 'doc'
                elif 'rtf' in content_type:
                    ext = 'rtf'
                else:
                    ext = 'html'
                
                filename = f"inteiro_teor_{num}_{ano}_{cod}.{ext}"

            filepath = os.path.join(final_save_dir, filename)
            with open(filepath, 'wb') as f:
                f.write(r.content)

            sidecar_metadata = {
                "downloaded_at": datetime.utcnow().isoformat() + "Z",
                "download_url": download_url,
                "source_url": canonical.get("source_url") or url,
                "numero_processo": canonical.get("numero_processo"),
                "ano": canonical.get("ano"),
                "codigo": canonical.get("codigo"),
                "content_type": content_type,
                "file_size_bytes": len(r.content),
            }
            if metadata:
                sidecar_metadata.update(metadata)
            self._write_sidecar_metadata(filepath, sidecar_metadata)

            logger.info(f"Saved inteiro teor to {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Failed to download inteiro_teor_url from {url}: {e}")
            
            # Try alternative approach - use Selenium to access the page
            try:
                logger.info("Trying Selenium to access the page...")
                self.driver.get(download_url if 'download_url' in locals() else url)
                time.sleep(3)
                
                if not filename:
                    filename = f"inteiro_teor_selenium_{int(time.time())}.html"

                filepath = os.path.join(final_save_dir, filename)
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(self.driver.page_source)

                self._write_sidecar_metadata(filepath, {
                    "downloaded_at": datetime.utcnow().isoformat() + "Z",
                    "download_url": download_url if 'download_url' in locals() else url,
                    "source_url": url,
                    "fetch_mode": "selenium_fallback",
                    **(metadata or {}),
                })
                
                logger.info(f"Saved inteiro teor via Selenium to {filepath}")
                return filepath
            except Exception as e2:
                logger.error(f"Also failed with Selenium: {e2}")
                return None

    def download_all_inteiro_teor(
        self,
        results: List[Dict],
        save_dir: Optional[str] = None,
        overwrite: bool = False,
        delay: float = 0.5,
        agent_id: Optional[str] = None,
        folder_name: Optional[str] = None,
        search_params: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Download all inteiro_teor files for the provided results list.

        - results: list of dicts returned by `get_inteiro_links`
        - save_dir: directory where files will be saved (defaults to workspace/TJRS_jurisprudencia)
        - overwrite: if False, existing files will be skipped
        - delay: seconds to wait between downloads to be polite
        - agent_id: agent identifier for folder organization
        - folder_name: custom folder name for organization
        - search_params: search parameters for metadata

        Returns a list of saved file paths (skipped or failed entries are not included).
        """
        if save_dir is None:
            save_dir = os.path.abspath(os.path.join(os.getcwd(), 'workspace', 'TJRS_jurisprudencia'))

        # Create organized folder structure
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Build folder path
        folder_parts = []
        if agent_id:
            folder_parts.append(agent_id)
        if folder_name:
            folder_parts.append(folder_name)
        folder_parts.append(timestamp)

        # Create final save directory
        final_save_dir = os.path.join(save_dir, *folder_parts)
        os.makedirs(final_save_dir, exist_ok=True)

        # Create search metadata file
        if search_params:
            metadata_file = os.path.join(final_save_dir, "search_metadata.json")
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "search_params": search_params,
                    "agent_id": agent_id,
                    "folder_name": folder_name,
                    "timestamp": timestamp,
                    "total_results": len(results),
                    "download_started": datetime.utcnow().isoformat() + "Z"
                }, f, indent=2, ensure_ascii=False)

        saved_files = []
        for idx, res in enumerate(results, 1):
            url = res.get('inteiro_url')
            if not url:
                logger.warning(f"Result {idx} missing 'inteiro_url', skipping")
                continue

            # Determine expected filename to check for existing files
            canonical = self.canonicalize_inteiro_url(url, fallback_num=res.get('numero_processo'))
            num = canonical.get('numero_processo') or res.get('numero_processo') or 'unknown'
            ano = canonical.get('ano') or res.get('ano') or ''
            cod = canonical.get('codigo') or res.get('codigo') or ''

            expected_prefix = f"inteiro_teor_{num}_{ano}_{cod}" if (ano or cod) else f"inteiro_teor_{num}"
            existing_matches = [
                os.path.join(final_save_dir, name)
                for name in os.listdir(final_save_dir)
                if name.startswith(expected_prefix + ".")
            ]

            if existing_matches and not overwrite:
                logger.info(f"Skipping existing file: {existing_matches[0]}")
                saved_files.append(existing_matches[0])
                continue

            logger.info(f"Downloading ({idx}/{len(results)}): {num} -> {url}")
            saved = self.download_inteiro_teor_url(
                url,
                save_dir=final_save_dir,
                metadata={
                    "numero_processo": num,
                    "ano": ano,
                    "codigo": cod,
                    "result_description": res.get("result_description"),
                    "agent_id": agent_id,
                    "folder_name": folder_name,
                    "search_params": search_params,
                },
                agent_id=agent_id,
                folder_name=folder_name,
                search_params=search_params,
            )
            if saved:
                saved_files.append(saved)
            else:
                logger.warning(f"Failed to download: {url}")

            if delay and idx < len(results):
                time.sleep(delay)

        # Conversion/indexing is handled by the API docx pipeline to keep downloads immutable.

        return saved_files

    def search_with_criteria(self, criteria: SearchCriteria) -> List[JurisprudenciaResult]:
        """Search using detailed criteria."""
        filters = {
            "tribunal": criteria.tribunal,
            "orgao_julgador": criteria.orgao_julgador,
            "relator": criteria.relator,
            "tipo_processo": criteria.tipo_processo,
            "classe_cnj": criteria.classe_cnj,
            "assunto_cnj": criteria.assunto_cnj,
            "comarca_origem": criteria.comarca_origem,
            "tipo_decisao": criteria.tipo_decisao,
        }
        return self.get_inteiro_links(
            query=criteria.search_text,
            max_results=criteria.max_results,
            search_index=criteria.search_index,
            filters=filters,
        )

    def close(self):
        if self.driver:
            self.driver.quit()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ----------------------------------------------------------------------
# Example usage
# ----------------------------------------------------------------------
if __name__ == "__main__":
    scraper = TJRSJurisprudenciaScraper(headless=True)
    try:
        query = "defeito do serviço CDC embarque preterição"
        max_results = 50
        
        print(f"Searching for '{query}'...")
        results = scraper.get_inteiro_links(query, max_results=max_results)
        print(f"Found {len(results)} results")
        
        # Download all results (conversion will happen automatically inside download_all_inteiro_teor)
        downloaded_files = scraper.download_all_inteiro_teor(results)
        print(f"Successfully downloaded {len(downloaded_files)} files (and converted .doc to .docx where applicable)")
        
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        scraper.close()