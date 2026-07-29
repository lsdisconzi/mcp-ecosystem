"""
Shared Chrome/Chromium WebDriver initialization utilities.

Provides the multi-strategy driver initialization used by all three
court scrapers (TJRS, TJSP, STF). Previously duplicated across
tjrs_scraper.py, tjsp_scraper.py, and stf_scraper.py.
"""

import os
import re
import sys
import json
import shutil
import subprocess
import logging
import threading
from typing import Optional, Dict, Any, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

try:
    from webdriver_manager.chrome import ChromeDriverManager
except Exception:
    ChromeDriverManager = None

logger = logging.getLogger(__name__)

_path_lock = threading.Lock()


# ── LibreOffice ────────────────────────────────────────────────────────────

def find_libreoffice() -> Optional[str]:
    """Locate the LibreOffice binary.

    Checks environment variable LIBREOFFICE_BINARY first, then common
    paths by platform.
    """
    env_bin = os.getenv("LIBREOFFICE_BINARY", "").strip()
    if env_bin and os.path.exists(env_bin):
        return env_bin

    if sys.platform == "darwin":
        candidates = [
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        ]
    elif sys.platform.startswith("linux"):
        candidates = [
            shutil.which("soffice"),
            shutil.which("libreoffice"),
        ]
    elif sys.platform == "win32":
        prog_files = os.getenv("PROGRAMFILES", "")
        prog_files_x86 = os.getenv("PROGRAMFILES(X86)", "")
        candidates = [
            os.path.join(prog_files, "LibreOffice", "program", "soffice.exe"),
            os.path.join(prog_files_x86, "LibreOffice", "program", "soffice.exe"),
        ]
    else:
        candidates = [shutil.which("soffice"), shutil.which("libreoffice")]

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


# ── Chrome binary resolution ───────────────────────────────────────────────

def resolve_chrome_binary() -> Optional[str]:
    """Locate Chrome/Chromium binary on the system.

    Checks CHROME_BINARY env var first, then platform-specific paths.
    """
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


def detect_chrome_major_version(chrome_binary: Optional[str]) -> Optional[str]:
    """Detect the major version of a Chrome/Chromium binary via --version."""
    if not chrome_binary or not os.path.exists(chrome_binary):
        return None

    try:
        version_out = subprocess.check_output(
            [chrome_binary, "--version"], text=True, stderr=subprocess.STDOUT
        )
        match = re.search(r"(\d+)\.", version_out)
        if match:
            return match.group(1)
    except Exception as e:
        logger.warning(f"Could not detect Chrome version from {chrome_binary}: {e}")
    return None


def detect_path_chromedriver_version() -> Tuple[Optional[str], Optional[str]]:
    """Find chromedriver on PATH and detect its major version.

    Returns (path_to_chromedriver, major_version) or (None, None).
    """
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
        logger.warning(
            f"Could not detect chromedriver version from PATH ({chromedriver_path}): {e}"
        )
        return chromedriver_path, None


# ── Chrome options builder ─────────────────────────────────────────────────

def build_chrome_options(headless: bool = True,
                         chrome_binary: Optional[str] = None) -> Options:
    """Create a Chrome Options instance with standard anti-detection flags."""
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    if chrome_binary:
        chrome_options.binary_location = chrome_binary
        logger.info(f"Using Chrome binary: {chrome_binary}")

    return chrome_options


# ── Multi-strategy driver factory ──────────────────────────────────────────

def create_chrome_driver(headless: bool = True,
                         chrome_binary: Optional[str] = None) -> webdriver.Chrome:
    """Create a Chrome WebDriver with multi-strategy fallback.

    Strategies (in order):
    1. Snap Chromium's bundled chromedriver (version-matched)
    2. Selenium Manager (auto-downloads matching chromedriver)
    3. webdriver-manager package (Python package)

    Raises RuntimeError if all strategies fail.
    """
    # Resolve the browser binary automatically when the caller did not pass one.
    if not chrome_binary:
        resolved = resolve_chrome_binary()
        if resolved:
            chrome_binary = resolved
    chrome_options = build_chrome_options(headless=headless, chrome_binary=chrome_binary)

    SNAP_CHROMEDRIVER = "/snap/chromium/current/usr/lib/chromium-browser/chromedriver"
    SNAP_CHROME = "/snap/bin/chromium"

    driver = None
    attempts = []

    # Strategy 1: Snap Chromium
    if os.path.exists(SNAP_CHROMEDRIVER) and os.path.exists(SNAP_CHROME):
        try:
            chrome_options.binary_location = SNAP_CHROME
            service = Service(SNAP_CHROMEDRIVER)
            driver = webdriver.Chrome(service=service, options=chrome_options)
            logger.info("Started WebDriver using snap Chromium binary and driver")
        except Exception as e:
            attempts.append(f"snap_chromium: {e}")

    # Strategy 2: System chromedriver found on PATH (e.g. apt `chromium-driver`)
    path_driver, path_driver_major = detect_path_chromedriver_version()
    if driver is None and path_driver:
        try:
            chrome_major = detect_chrome_major_version(chrome_options.binary_location)
            if not chrome_major or chrome_major == path_driver_major:
                service = Service(path_driver)
                driver = webdriver.Chrome(service=service, options=chrome_options)
                logger.info(f"Started WebDriver using system chromedriver: {path_driver}")
            else:
                logger.warning(
                    f"Skipping system chromedriver {path_driver} (driver "
                    f"{path_driver_major} vs Chrome {chrome_major})"
                )
        except Exception as e:
            attempts.append(f"system_chromedriver: {e}")

    # Strategy 3: Selenium Manager with PATH manipulation for version mismatch
    if driver is None:
        original_path = None
        acquired = False
        try:
            _path_lock.acquire()
            acquired = True
            chrome_major = detect_chrome_major_version(chrome_options.binary_location)
            path_driver, driver_major = detect_path_chromedriver_version()
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

            driver = webdriver.Chrome(service=Service(), options=chrome_options)
            logger.info("Started WebDriver using Selenium Manager")
        except Exception as e:
            attempts.append(f"selenium_manager: {e}")
        finally:
            if original_path is not None:
                os.environ["PATH"] = original_path
            if acquired:
                _path_lock.release()

    # Strategy 3: webdriver-manager package
    if driver is None and ChromeDriverManager:
        try:
            chrome_major = detect_chrome_major_version(chrome_options.binary_location)
            if chrome_major:
                logger.info(
                    f"Trying webdriver-manager with Chrome major version {chrome_major}"
                )
                try:
                    service = Service(
                        ChromeDriverManager(driver_version=chrome_major).install()
                    )
                except TypeError:
                    # Compatibility with older webdriver-manager signature
                    service = Service(
                        ChromeDriverManager(version=chrome_major).install()
                    )
            else:
                service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            logger.info("Started WebDriver using webdriver-manager")
        except Exception as e:
            attempts.append(f"webdriver_manager: {e}")

    if driver is None:
        details = " | ".join(attempts) if attempts else "No attempts executed"
        raise RuntimeError(
            "Could not initialize Chrome WebDriver. "
            "If this is macOS, update Google Chrome and avoid old chromedriver "
            "binaries in PATH. Details: " + details
        )

    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


# ── File utility helpers ───────────────────────────────────────────────────

def write_sidecar_metadata(filepath: str, metadata: Dict[str, Any]) -> None:
    """Write a .metadata.json sidecar file for a downloaded artifact."""
    try:
        sidecar_path = f"{filepath}.metadata.json"
        with open(sidecar_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning(f"Could not write sidecar metadata for {filepath}: {exc}")


def infer_extension(url: str = "", content_type: str = "") -> str:
    """Infer file extension from URL and/or Content-Type header.

    Returns one of: docx, doc, pdf, rtf, tiff, html, bin.
    """
    lowered_url = (url or "").lower()
    lowered_ct = (content_type or "").lower()

    if ".docx" in lowered_url or "wordprocessingml.document" in lowered_ct:
        return "docx"
    if re.search(r"\.doc(\?|$)", lowered_url) or "msword" in lowered_ct or "application/doc" in lowered_ct:
        return "doc"
    if ".pdf" in lowered_url or "application/pdf" in lowered_ct:
        return "pdf"
    if ".rtf" in lowered_url or "application/rtf" in lowered_ct:
        return "rtf"
    if ".tiff" in lowered_url or ".tif" in lowered_url or "image/tiff" in lowered_ct:
        return "tiff"
    if "text/html" in lowered_ct or ".html" in lowered_url or ".htm" in lowered_url:
        return "html"
    return "bin"
