"""
Website document crawler.

Strategy (3 phases):
  1. WordPress REST API  — enumerate all media by mime type (most reliable)
  2. XML Sitemap         — parse sitemap for any direct document URLs
  3. HTML page crawl    — follow internal links, harvest <a href> doc links

Phase 4: Download everything found in phases 1-3.
"""

import os
import argparse
import requests
import xml.etree.ElementTree as ET
import threading
import logging
import time
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_RETRIES = 3
RETRY_DELAY = 2
TIMEOUT = 60

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

DOCUMENT_EXTENSIONS = (
    '.pdf', '.doc', '.docx', '.xls', '.xlsx',
    '.ppt', '.pptx', '.odt', '.ods', '.odp',
    '.csv', '.txt', '.zip', '.rar', '.7z',
    '.epub', '.rtf',
)

# WordPress REST API mime types to query
WP_DOCUMENT_MIMES = [
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/vnd.oasis.opendocument.text',
    'application/vnd.oasis.opendocument.spreadsheet',
    'text/csv',
    'application/zip',
    'application/epub+zip',
    'application/rtf',
]

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def get(url, stream=False, timeout=None):
    """GET with retry logic. Returns Response or None."""
    t = timeout or (12, TIMEOUT)
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(url, headers=HEADERS, timeout=t, verify=False,
                             stream=stream, allow_redirects=True)
            r.raise_for_status()
            return r
        except requests.HTTPError as e:
            logger.debug(f"HTTP {e.response.status_code} for {url}")
            return None
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                logger.debug(f"Retry {attempt+1}/{MAX_RETRIES} for {url}: {e}")
                time.sleep(RETRY_DELAY)
            else:
                logger.warning(f"Failed after {MAX_RETRIES} attempts: {url} — {e}")
    return None


# ---------------------------------------------------------------------------
# URL utilities
# ---------------------------------------------------------------------------

def is_document_url(url):
    path = urlparse(url).path.lower().split('?')[0]
    return any(path.endswith(ext) for ext in DOCUMENT_EXTENSIONS)


def same_domain(base, url):
    d1 = urlparse(base).netloc.lower().lstrip('www.')
    d2 = urlparse(url).netloc.lower().lstrip('www.')
    return d1 == d2


def should_crawl(url):
    path = urlparse(url).path.lower()
    skip = [
        '/wp-admin/', '/wp-json/', '/feed/', '/trackback/',
        '/xmlrpc.php', '/cart/', '/checkout/', '/login/',
        '/wp-login.php', '/wp-cron.php',
    ]
    return not any(s in path for s in skip)


def url_to_local_path(url, save_dir):
    parsed = urlparse(url)
    domain = parsed.netloc.replace(':', '_')
    path = parsed.path.lstrip('/')
    if not path:
        path = 'index'
    return os.path.join(save_dir, 'documents', domain, path)


# ---------------------------------------------------------------------------
# Phase 1 — WordPress REST API
# ---------------------------------------------------------------------------

def phase_wp_api(base_url):
    """Return set of document URLs from the WP REST media API."""
    found = set()
    api_base = urljoin(base_url, '/wp-json/wp/v2/media')

    for mime in WP_DOCUMENT_MIMES:
        page = 1
        while True:
            url = f"{api_base}?per_page=100&page={page}&mime_type={mime}"
            try:
                r = requests.get(url, headers=HEADERS, timeout=(12, 30), verify=False)
                if r.status_code == 400:
                    break  # invalid page — exhausted
                if r.status_code != 200:
                    logger.debug(f"WP API {r.status_code} for mime={mime} page={page}")
                    break
                items = r.json()
                if not items:
                    break
                for item in items:
                    src = item.get('source_url') or (item.get('guid') or {}).get('rendered')
                    if src:
                        found.add(src)
                total_pages = int(r.headers.get('X-WP-TotalPages', 1))
                if page >= total_pages:
                    break
                page += 1
            except Exception as e:
                logger.debug(f"WP API error mime={mime}: {e}")
                break

    logger.info(f"[WP API] Found {len(found)} document URLs")
    return found


# ---------------------------------------------------------------------------
# Phase 2 — XML Sitemap
# ---------------------------------------------------------------------------

def _parse_sitemap(sitemap_url, depth=0):
    """Recursively parse sitemap/sitemap-index, return set of all locs."""
    if depth > 4:
        return set()
    urls = set()
    ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    try:
        r = requests.get(sitemap_url, headers=HEADERS, timeout=(10, 20), verify=False)
        if r.status_code != 200:
            return urls
        root = ET.fromstring(r.content)
        for sitemap in root.findall('.//sm:sitemap/sm:loc', ns):
            urls |= _parse_sitemap(sitemap.text.strip(), depth + 1)
        for loc in root.findall('.//sm:url/sm:loc', ns):
            urls.add(loc.text.strip())
    except Exception as e:
        logger.debug(f"Sitemap parse error {sitemap_url}: {e}")
    return urls


def phase_sitemap(base_url):
    """Return document URLs and page URLs found in sitemaps."""
    candidates = [
        urljoin(base_url, '/sitemap.xml'),
        urljoin(base_url, '/wp-sitemap.xml'),
        urljoin(base_url, '/sitemap_index.xml'),
    ]
    all_urls = set()
    for c in candidates:
        urls = _parse_sitemap(c)
        if urls:
            all_urls |= urls
            logger.info(f"[Sitemap] {c} -> {len(urls)} URLs")
            break

    doc_urls = {u for u in all_urls if is_document_url(u)}
    page_urls = {u for u in all_urls if not is_document_url(u) and same_domain(base_url, u)}
    logger.info(f"[Sitemap] {len(doc_urls)} doc URLs, {len(page_urls)} page URLs")
    return doc_urls, page_urls


# ---------------------------------------------------------------------------
# Phase 3 — HTML page crawl
# ---------------------------------------------------------------------------

def _crawl_one_page(url, base_url, visited, to_visit, doc_urls, lock):
    """Fetch one HTML page, add document links to doc_urls and new pages to to_visit."""
    try:
        r = get(url, timeout=(12, 30))
        if r is None:
            return
        ct = r.headers.get('Content-Type', '')
        if 'text/html' not in ct:
            return

        soup = BeautifulSoup(r.text, 'html.parser')

        with lock:
            visited.add(url)
            for tag in soup.find_all(['a', 'link', 'area'], href=True):
                raw = tag['href'].strip()
                if not raw or raw.startswith('mailto:') or raw.startswith('tel:'):
                    continue
                href = urljoin(url, raw).split('#')[0].rstrip('/')
                if not href or href in visited:
                    continue

                if is_document_url(href):
                    if href not in doc_urls:
                        doc_urls.add(href)
                        logger.info(f"[Page crawl] Found document: {href}")
                elif same_domain(base_url, href) and should_crawl(href):
                    if href not in to_visit:
                        to_visit.add(href)

    except Exception as e:
        logger.error(f"[Page crawl] Error on {url}: {e}")


def phase_crawl(base_url, seed_pages, doc_urls, max_workers=5):
    """Crawl all pages, collecting doc URLs. Mutates doc_urls in-place."""
    visited = set()
    to_visit = set(seed_pages) | {base_url.rstrip('/')}
    lock = threading.Lock()

    logger.info(f"[Page crawl] Starting with {len(to_visit)} seed pages")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        while to_visit or futures:
            while to_visit and len(futures) < max_workers:
                with lock:
                    if not to_visit:
                        break
                    url = to_visit.pop()
                if url in visited:
                    continue
                with lock:
                    visited.add(url)
                f = executor.submit(
                    _crawl_one_page, url, base_url, visited, to_visit, doc_urls, lock
                )
                futures[f] = url

            if not futures:
                break

            for f in as_completed(list(futures.keys())):
                try:
                    f.result()
                except Exception as e:
                    logger.error(f"[Page crawl] Future error: {e}")
                futures.pop(f, None)
                break  # re-check to_visit after each page

            time.sleep(0.2)

    logger.info(f"[Page crawl] Visited {len(visited)} pages, total docs so far: {len(doc_urls)}")


# ---------------------------------------------------------------------------
# Phase 4 — Download
# ---------------------------------------------------------------------------

def _download_one(url, save_dir):
    dest = url_to_local_path(url, save_dir)
    if os.path.exists(dest):
        logger.info(f"[Download] Already exists: {dest}")
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        r = get(url, stream=True, timeout=(12, TIMEOUT))
        if r is None:
            return None
        with open(dest, 'wb') as fh:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    fh.write(chunk)
        logger.info(f"[Download] Saved: {dest}")
        return dest
    except Exception as e:
        logger.error(f"[Download] Failed {url}: {e}")
        return None


def phase_download(doc_urls, save_dir, max_workers=5):
    """Download all discovered document URLs."""
    logger.info(f"[Download] Downloading {len(doc_urls)} documents...")
    saved = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_download_one, u, save_dir): u for u in doc_urls}
        for f in as_completed(futures):
            try:
                result = f.result()
                if result:
                    saved.append(result)
            except Exception as e:
                logger.error(f"[Download] Error: {e}")
    return saved


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run(base_url, save_dir, max_workers=5):
    base_url = base_url.rstrip('/') + '/'
    os.makedirs(os.path.join(save_dir, 'documents'), exist_ok=True)

    logger.info("=== Phase 1: WordPress REST API ===")
    doc_urls = phase_wp_api(base_url)

    logger.info("=== Phase 2: XML Sitemap ===")
    sitemap_docs, sitemap_pages = phase_sitemap(base_url)
    doc_urls |= sitemap_docs

    logger.info("=== Phase 3: HTML Page Crawl ===")
    phase_crawl(base_url, sitemap_pages, doc_urls, max_workers=max_workers)

    logger.info("=== Phase 4: Downloading Documents ===")
    saved = phase_download(doc_urls, save_dir, max_workers=max_workers)

    logger.info("=== Summary ===")
    logger.info(f"Total documents downloaded: {len(saved)}")
    by_ext = {}
    for p in sorted(saved):
        ext = os.path.splitext(p)[1].lower() or 'unknown'
        by_ext[ext] = by_ext.get(ext, 0) + 1
        logger.info(f"  {p}")
    logger.info("--- by type ---")
    for ext, count in sorted(by_ext.items()):
        logger.info(f"  {ext}: {count} file(s)")


def main():
    parser = argparse.ArgumentParser(description='Document crawler — WP API + sitemap + page crawl.')
    parser.add_argument('--base-url', default='https://italianscotland.com/', help='Base URL to crawl')
    parser.add_argument('--directory', default='crawler_output/italianscot-docs', help='Output directory')
    parser.add_argument('--max-workers', type=int, default=5, help='Concurrent workers')
    args = parser.parse_args()
    run(args.base_url, args.directory, args.max_workers)


if __name__ == '__main__':
    main()
