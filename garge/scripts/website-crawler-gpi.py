import os
import argparse
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import threading
import re
import string
import logging
import time
import socket
import urllib3
from webdriver_manager.chrome import ChromeDriverManager

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
MAX_RETRIES = 3
RETRY_DELAY = 2
TIMEOUT = 60
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    )
}

# Cache the ChromeDriver path so concurrent threads don't re-download it
_driver_path: str | None = None
_driver_path_lock = threading.Lock()

def get_driver_path() -> str:
    global _driver_path
    if _driver_path is None:
        with _driver_path_lock:
            if _driver_path is None:
                _driver_path = ChromeDriverManager().install()
    return _driver_path


def build_driver():
    """Build a Chrome WebDriver optimized for crawler stability."""
    chrome_options = Options()
    chrome_options.page_load_strategy = 'eager'
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument("--allow-running-insecure-content")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-background-networking")

    service = ChromeService(get_driver_path())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(TIMEOUT)
    driver.implicitly_wait(5)
    return driver


def fetch_html_with_requests(url):
    """Try fast HTTP fetch first to avoid renderer timeout issues."""
    try:
        response = requests.get(
            url,
            timeout=(12, TIMEOUT),
            verify=False,
            headers=REQUEST_HEADERS,
        )
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '').lower()
        if 'text/html' not in content_type:
            logger.info(f"Skipping non-HTML URL: {url} ({content_type})")
            return None, 'non-html'
        return response.text, None
    except requests.exceptions.ConnectTimeout as e:
        logger.warning(f"Requests connect timeout for {url}: {e}")
        return None, 'connect-timeout'
    except requests.exceptions.ConnectionError as e:
        logger.warning(f"Requests connection error for {url}: {e}")
        return None, 'connection-error'
    except Exception as e:
        logger.warning(f"Requests fetch failed for {url}: {e}")
        return None, 'other'


def is_host_reachable(url, timeout=6):
    """Quick TCP reachability check to fail fast when target is offline."""
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False

    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == 'https' else 80

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def normalize_base_url(url):
    parsed = urlparse(url)
    if not parsed.scheme:
        url = f'https://{url}'
    return url.rstrip('/') + '/'


def pick_reachable_base_url(base_url):
    """Try base URL and www/non-www variant, returning the first reachable one."""
    normalized = normalize_base_url(base_url)
    parsed = urlparse(normalized)
    host = parsed.hostname or ''

    candidates = [normalized]
    if host.startswith('www.'):
        alt_host = host[4:]
    else:
        alt_host = f'www.{host}'

    if alt_host:
        alt_url = f"{parsed.scheme}://{alt_host}{parsed.path or '/'}"
        alt_url = alt_url.rstrip('/') + '/'
        if alt_url not in candidates:
            candidates.append(alt_url)

    for candidate in candidates:
        if is_host_reachable(candidate):
            if candidate != normalized:
                logger.warning(f"Primary base URL unreachable, using fallback: {candidate}")
            return candidate

    logger.error(f"No reachable host found for base URL candidates: {candidates}")
    return None

def download_file(url, save_dir):
    """Download files with retry logic and better error handling"""
    parsed_url = urlparse(url)
    domain = parsed_url.netloc.replace(':', '_')
    path = parsed_url.path.lstrip('/')
    if not path:
        path = 'index.html'
    
    # Create proper file structure
    local_filename = os.path.join(save_dir, domain, path)
    os.makedirs(os.path.dirname(local_filename), exist_ok=True)
    
    for attempt in range(MAX_RETRIES):
        try:
            logger.info(f"Downloading: {url} (attempt {attempt + 1})")
            r = requests.get(url, stream=True, timeout=TIMEOUT, verify=False)
            if r.status_code == 200:
                with open(local_filename, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                logger.info(f"Downloaded: {local_filename}")
                return True
            else:
                logger.warning(f"Failed to download {url}: Status code {r.status_code}")
        except Exception as e:
            logger.error(f"Error downloading file {url} (attempt {attempt + 1}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
    
    return False

def download_page(url, base_url, save_dir, visited, to_visit, lock):
    """Download a single page with improved handling for dynamic content"""
    driver = None
    try:
        logger.info(f"Visiting: {url}")
        content, fetch_error = fetch_html_with_requests(url)

        if not content and fetch_error in ('connect-timeout', 'connection-error'):
            raise RuntimeError(
                'Host unreachable with requests client; skipping Selenium fallback to avoid long timeout'
            )

        if not content:
            logger.info(f"Falling back to Selenium for: {url}")
            driver = build_driver()
            driver.get(url)

            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            content = driver.page_source

        if not content:
            raise RuntimeError("No HTML content retrieved")

        soup = BeautifulSoup(content, 'html.parser')
        
        # Save the HTML file with better organization
        filename = os.path.join(save_dir, 'pages', clean_url(url) + '.html')
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        with open(filename, 'w', encoding='utf-8') as file:
            file.write(soup.prettify())
        logger.info(f"Saved HTML: {filename}")

        # Process and download assets with better filtering
        assets = []

        # Images (including SVG)
        for img in soup.find_all('img', src=True):
            src = img['src']
            if not src.startswith('data:'):  # Skip data URIs
                asset_url = urljoin(url, src)
                assets.append(asset_url)

        # CSS files
        for link in soup.find_all('link', href=True, rel=lambda x: x and 'stylesheet' in x):
            href = link['href']
            asset_url = urljoin(url, href)
            assets.append(asset_url)

        # JavaScript files
        for script in soup.find_all('script', src=True):
            src = script['src']
            asset_url = urljoin(url, src)
            assets.append(asset_url)

        # Font files
        for link in soup.find_all('link', href=True, rel=lambda x: x and 'font' in x):
            href = link['href']
            asset_url = urljoin(url, href)
            assets.append(asset_url)

        # Download assets (filter external domains if needed)
        for asset_url in set(assets):
            if is_same_domain(base_url, asset_url) or should_download_external_asset(asset_url):
                download_file(asset_url, save_dir)

        # Process links on the page with better filtering
        with lock:
            visited.add(url)
            for link in soup.find_all('a', href=True):
                href = urljoin(url, link['href'])
                href = href.split('#')[0]  # Remove fragments
                href = href.rstrip('/')  # Remove trailing slash
                
                # Skip if already processed
                if href in visited or href in to_visit:
                    continue
                
                # Check if it's a direct file link
                if any(href.lower().endswith(ext) for ext in ('.pdf', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.css', '.js', '.doc', '.docx', '.xls', '.xlsx')):
                    download_file(href, save_dir)
                    visited.add(href)
                elif is_same_domain(base_url, href):
                    # Additional filtering for UN SDSN specific patterns
                    if should_crawl_url(href, base_url):
                        logger.info(f"Adding to queue: {href}")
                        to_visit.add(href)
                else:
                    # Handle external links if needed
                    if should_crawl_external(href):
                        logger.info(f"Adding external link to queue: {href}")
                        to_visit.add(href)
                        
    except Exception as e:
        logger.error(f"Error downloading {url}: {e}")
    finally:
        if driver:
            driver.quit()

def is_same_domain(url1, url2):
    """Check if two URLs belong to the same domain"""
    domain1 = urlparse(url1).netloc.lower().replace('www.', '')
    domain2 = urlparse(url2).netloc.lower().replace('www.', '')
    return domain1 == domain2

def should_download_external_asset(url):
    """Determine whether to download external assets"""
    # Download common CDN assets but skip tracking/analytics
    external_domains_to_download = [
        'fonts.googleapis.com',
        'fonts.gstatic.com',
        'cdnjs.cloudflare.com',
        'unpkg.com'
    ]
    
    parsed_url = urlparse(url)
    domain = parsed_url.netloc.lower()
    
    # Skip analytics and tracking
    if any(tracker in domain for tracker in ['google-analytics', 'googletag', 'doubleclick']):
        return False
    
    return domain in external_domains_to_download

def should_crawl_url(url, base_url):
    """Determine whether to crawl a URL."""
    parsed_url = urlparse(url)
    path = parsed_url.path.lower()

    # Skip non-content / infrastructure paths
    skip_patterns = [
        '/wp-admin/',
        '/wp-json/',
        '/wp-content/uploads/',
        '/search/',
        '/feed/',
        '/trackback/',
        '/xmlrpc.php',
    ]

    if any(pattern in path for pattern in skip_patterns):
        return False

    return True

def should_crawl_external(url):
    """Determine whether to crawl external URLs"""
    # For now, skip external crawling to focus on main site
    return False

def download_site(base_url, save_dir, max_workers=3):
    """Download entire site with improved resource management"""
    visited = set()
    to_visit = {base_url}
    lock = threading.Lock()
    
    # Create directory structure
    os.makedirs(os.path.join(save_dir, 'pages'), exist_ok=True)
    
    logger.info(f"Starting crawl of {base_url}")
    logger.info(f"Save directory: {save_dir}")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        while to_visit or futures:
            # Fill up to max_workers slots
            while to_visit and len(futures) < max_workers:
                with lock:
                    if not to_visit:
                        break
                    url = to_visit.pop()

                if url not in visited:
                    futures.append(executor.submit(download_page, url, base_url, save_dir, visited, to_visit, lock))

            if not futures:
                break

            # Wait for at least one future to finish, then collect all done ones
            done_futures = []
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Error in future: {e}")
                done_futures.append(future)
                break  # Re-evaluate to_visit after each completion

            futures = [f for f in futures if f not in done_futures]

            # Small delay to avoid overwhelming the server
            time.sleep(0.5)

    logger.info(f"Download complete. Visited {len(visited)} pages.")

def clean_url(url):
    """Clean URL for use in filenames"""
    url = re.sub(r'https?://(www\.)?', '', url)
    url = url.replace('/', '_')
    url = re.sub(r'[^\w\-_\. ]', '_', url)
    # Limit filename length
    if len(url) > 200:
        url = url[:200]
    return url

def list_files(directory, extensions):
    """List files with specified extensions"""
    files = []
    for root, _, filenames in os.walk(directory):
        for filename in filenames:
            if filename.lower().endswith(extensions):
                files.append(os.path.join(root, filename))
    return files

def main():
    parser = argparse.ArgumentParser(description='Website crawler with requests/selenium fallback.')
    parser.add_argument('--base-url', default='scripts/website-crawler.py', help='Base URL to crawl')
    parser.add_argument(
        '--directory',
        default='crawler_output/bidx',
        help='Output directory',
    )
    parser.add_argument('--max-workers', type=int, default=3, help='Concurrent workers')
    args = parser.parse_args()

    base_url = args.base_url
    directory = args.directory
    extensions = ('.doc', '.csv', '.txt', '.docx', '.zip', '.css', '.xml', '.html', '.pdf', '.js', '.jpg', '.jpeg', '.png', '.gif', '.svg')

    # Ensure the directory exists
    if not os.path.exists(directory):
        os.makedirs(directory)

    if base_url != '':
        reachable_base_url = pick_reachable_base_url(base_url)
        if not reachable_base_url:
            logger.error('Crawl aborted: target host is unreachable from this machine/network.')
            return
        download_site(reachable_base_url, directory, max_workers=args.max_workers)

    # List the directory contents for debugging
    logger.info("Listing directory contents:")
    for root, dirs, files in os.walk(directory):
        for file in files:
            logger.info(os.path.join(root, file))

    files = list_files(directory, extensions)
    logger.info(f"Total files found: {len(files)}")

if __name__ == '__main__':
    main()

