#!/usr/bin/env python3
"""
WordPress Document Crawler
Finds & downloads all documents (PDF, DOC, XLS, etc.) from a WordPress site.
Uses REST API, sitemap, and page crawling – but only saves documents.
"""

import requests
from bs4 import BeautifulSoup
import os
import time
import re
import csv
import json
import mimetypes
from html import unescape
from urllib.parse import urljoin, urlparse, unquote, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed
import xml.etree.ElementTree as ET

# ------------------------------
# CONFIGURATION
# ------------------------------
BASE_URL = "https://alta.aero/ccma/2026/"
DOWNLOAD_DIR = "alta"          # where documents will be saved
REQUEST_DELAY = 0.3                         # polite delay between requests
MAX_PAGE_CRAWL = 500                        # max HTML pages to crawl (safety)
MAX_WORKERS = 5                             # concurrent downloads/requests
RESTRICT_CRAWL_TO_BASE_PATH = False         # set True to stay strictly under BASE_URL path
ALLOW_SUBDOMAINS = True                     # include subdomains like *.frigo-data.com.br
ALLOW_EXTERNAL_DOCUMENTS = False            # keep only target domain docs by default
PRIORITY_SEED_URLS = [
    "https://alta.aero/ccma/2026/"]                                           # pages worth crawling even if sitemap is missing
EXPORT_DISCOVERED_URLS_CSV = "discovered_documents.csv"
ENABLE_CRAWL_CHECKPOINT = True
CRAWL_CHECKPOINT_FILE = "crawl_state.json"
CRAWL_CHECKPOINT_SAVE_EVERY = 50            # save state every N visited pages
CLEAR_CHECKPOINT_ON_COMPLETE = True

# File extensions we care about
DOCUMENT_EXTENSIONS = {
    '.pdf', '.doc', '.docx', '.xls', '.xlsx',
    '.csv', '.ppt', '.pptx', '.odt', '.ods', '.odp',
    '.rtf', '.txt', '.zip', '.rar', '.7z'
}

# MIME types to query via WP REST API (all subtypes of these will be fetched)
DOCUMENT_MIME_TYPES = [
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/csv",
    "application/zip",
    "application/x-rar-compressed",
    "application/x-7z-compressed",
]

# Standard headers to avoid being blocked
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DocCrawler/1.0; +http://example.com)"
}

EXTRA_LINK_ATTRIBUTES = (
    'href', 'src', 'data-href', 'data-url', 'data-download',
    'data-file', 'onclick'
)

NON_HTML_SUFFIXES = ('.jpg', '.jpeg', '.png', '.gif', '.css', '.js', '.xml')

BASE_PARSED = urlparse(BASE_URL)
BASE_DOMAIN = BASE_PARSED.netloc.lower()
BASE_DOMAIN_SUFFIX = BASE_DOMAIN[4:] if BASE_DOMAIN.startswith("www.") else BASE_DOMAIN
BASE_SCOPE_PATH = BASE_PARSED.path or "/"
if not BASE_SCOPE_PATH.endswith('/'):
    BASE_SCOPE_PATH += '/'

# ------------------------------
# UTILITY FUNCTIONS
# ------------------------------
def get(url, stream=False, retries=3, log_errors=True):
    """GET request with retries and backoff."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30, stream=stream)
            if resp.status_code == 429:
                wait = 5 * (attempt + 1)
                print(f"Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue

            # Client errors (except 429) are usually permanent for this URL.
            if 400 <= resp.status_code < 500:
                if log_errors:
                    print(f"Request failed: {resp.status_code} Client Error for url: {url}")
                return None

            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            if log_errors:
                print(f"Request failed (attempt {attempt+1}): {e}")
            time.sleep(2 ** attempt)
    return None


def is_same_domain(url):
    host = urlparse(url).netloc.lower()
    if host == BASE_DOMAIN:
        return True
    if not ALLOW_SUBDOMAINS:
        return False
    return host == BASE_DOMAIN_SUFFIX or host.endswith(f".{BASE_DOMAIN_SUFFIX}")


def is_page_in_scope(url):
    parsed = urlparse(url)
    if not is_same_domain(url):
        return False
    if not RESTRICT_CRAWL_TO_BASE_PATH or BASE_SCOPE_PATH == "/":
        return True
    path = parsed.path or "/"
    return path.startswith(BASE_SCOPE_PATH)


def is_document_url(url):
    """Check if the URL points to a document by its extension."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    if any(path.endswith(ext) for ext in DOCUMENT_EXTENSIONS):
        return True

    # Some portals use download routes without file extensions.
    if re.search(r"/(download|baixar)(/|$)", path):
        return True

    query = parse_qs(parsed.query or "", keep_blank_values=True)
    for key in ("download", "arquivo", "anexo", "file", "nomearquivo"):
        values = query.get(key, [])
        if any(str(v).strip() for v in values):
            return True

    return False


def safe_filename(url):
    """Create a safe filename from a URL."""
    parsed = urlparse(url)
    name = os.path.basename(parsed.path)
    if not name:
        name = "document_" + str(abs(hash(url)))
    # Remove query strings if they are part of the filename
    if '?' in name:
        name = name.split('?')[0]
    return name


def sanitize_filename(name):
    """Keep filename filesystem-safe and deterministic."""
    cleaned = os.path.basename(unescape(name or ""))
    cleaned = re.sub(r"[\\/:*?\"<>|]", "_", cleaned)
    cleaned = cleaned.strip().strip('.')
    return cleaned or "document"


def extract_urls_from_text(text):
    """Extract URL-like tokens from arbitrary text blocks."""
    if not text:
        return []
    text = unescape(str(text))
    pattern = r"https?://[^\s'\"<>]+|[A-Za-z0-9_./-]+\.(?:pdf|doc|docx|xls|xlsx|csv|ppt|pptx|odt|ods|odp|rtf|txt|zip|rar|7z)(?:\?[^\s'\"<>]*)?|/[A-Za-z0-9_./-]*(?:download|baixar)[^\s'\"<>]*"
    return re.findall(pattern, text, flags=re.IGNORECASE)


def normalize_candidate_url(raw, current_url):
    """Normalize candidate URL by removing wrappers, escapes, and fragments."""
    if not raw:
        return None

    value = unescape(str(raw)).strip().strip("'\"()[]{}")
    if not value or value.startswith('#') or value.lower().startswith("javascript:"):
        return None

    value = value.replace('\\/', '/')
    absolute = urljoin(current_url, value)
    absolute = absolute.split('#')[0].strip().rstrip(".,;)")
    return absolute or None


def filename_from_response(url, resp):
    """Derive best-effort filename from headers/content type and URL."""
    content_disposition = resp.headers.get('content-disposition') or ''

    filename = None
    match = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition, flags=re.IGNORECASE)
    if match:
        filename = unquote(match.group(1))
    else:
        match = re.search(r'filename="?([^\";]+)"?', content_disposition, flags=re.IGNORECASE)
        if match:
            filename = match.group(1)

    filename = sanitize_filename(filename or safe_filename(url))

    content_type = (resp.headers.get('content-type') or '').split(';', 1)[0].strip().lower()
    base, ext = os.path.splitext(filename)
    if not ext and content_type:
        guessed = mimetypes.guess_extension(content_type)
        if guessed:
            filename = f"{base}{guessed}"

    return filename


def is_document_host_allowed(url):
    """Restrict saved document URLs to target host/scope unless explicitly allowed."""
    if ALLOW_EXTERNAL_DOCUMENTS:
        return True
    return is_same_domain(url)


def load_crawl_checkpoint(path):
    """Load persisted crawl state, when available."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as e:
        print(f"Could not load checkpoint '{path}': {e}")
    return None


def save_crawl_checkpoint(path, visited, to_visit, doc_urls):
    """Persist crawl state so long runs can be resumed."""
    payload = {
        "visited": list(visited),
        "to_visit": list(to_visit),
        "doc_urls": list(doc_urls),
        "saved_at": int(time.time()),
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)


def clear_crawl_checkpoint(path):
    """Remove checkpoint file after successful completion."""
    if os.path.exists(path):
        os.remove(path)


def export_discovered_urls_csv(doc_urls, csv_path):
    """Export discovered URLs for auditing before/after downloads."""
    directory = os.path.dirname(csv_path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["url", "host", "path"])
        for url in sorted(doc_urls):
            parsed = urlparse(url)
            writer.writerow([url, parsed.netloc, parsed.path])

    print(f"Exported discovered URLs to '{csv_path}'")


# ------------------------------
# PHASE 1: WordPress REST API
# ------------------------------
def discover_wp_media_endpoints():
    """Return possible wp/v2/media endpoints for both subpath and root installs."""
    candidates = []

    def add_candidate(value):
        if value and value not in candidates:
            candidates.append(value)

    add_candidate(urljoin(BASE_URL, "wp-json/wp/v2/media"))
    add_candidate(urljoin(BASE_URL, "/wp-json/wp/v2/media"))

    # Some WP sites expose rest base via a link rel="https://api.w.org/".
    start_page = get(BASE_URL, log_errors=False)
    if start_page:
        soup = BeautifulSoup(start_page.text, 'lxml')
        for link in soup.find_all('link', href=True):
            rel = link.get('rel') or []
            if any("api.w.org" in str(r) for r in rel):
                rest_base = urljoin(BASE_URL, link['href'])
                rest_base = rest_base.rstrip('/')
                add_candidate(f"{rest_base}/wp/v2/media")

    return candidates


def get_wp_media_documents():
    """
    Enumerate all document media via WP REST API.
    Returns a set of direct download URLs.
    """
    found = set()
    per_page = 100

    endpoints = discover_wp_media_endpoints()
    if not endpoints:
        print("REST API: no endpoint candidates discovered.")
        return found

    for base in endpoints:
        probe = get(f"{base}?per_page=1&page=1", log_errors=False)
        if not probe:
            continue
        print(f"REST API: using endpoint {base}")

        for mime in DOCUMENT_MIME_TYPES:
            page = 1
            while True:
                url = f"{base}?per_page={per_page}&page={page}&mime_type={mime}"
                resp = get(url, log_errors=False)
                if not resp:
                    break
                try:
                    data = resp.json()
                except Exception:
                    break
                if not data or not isinstance(data, list):
                    break

                for item in data:
                    source_url = item.get('source_url') or item.get('guid', {}).get('rendered')
                    if source_url and is_document_url(source_url):
                        found.add(source_url)

                # Check if we got a full page
                if len(data) < per_page:
                    break
                page += 1
                time.sleep(REQUEST_DELAY)

        # If one endpoint worked, no need to keep trying others.
        break

    print(f"REST API: found {len(found)} document URLs.")
    return found


# ------------------------------
# PHASE 2: XML Sitemap
# ------------------------------
def parse_sitemap(sitemap_url):
    """
    Parse an XML sitemap (or sitemap index) and return all page URLs.
    Only extracts URLs ending in document extensions (rare), and page URLs
    (for later crawling). But we'll return all locs and filter later.
    """
    urls = set()
    resp = get(sitemap_url)
    if not resp:
        return urls

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return urls

    # Namespace might be present
    ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    # Direct URLs
    for url_elem in root.findall('url/loc') or root.findall('.//sm:loc', ns):
        if url_elem is not None and url_elem.text:
            urls.add(url_elem.text.strip())

    # Sitemap index
    for sitemap_elem in root.findall('sitemap/loc') or root.findall('.//sm:sitemap/sm:loc', ns):
        if sitemap_elem is not None and sitemap_elem.text:
            sub_url = sitemap_elem.text.strip()
            urls.update(parse_sitemap(sub_url))   # recursive
    return urls


def get_sitemap_documents():
    """Try both common sitemap locations and return document URLs."""
    sitemap_candidates = []

    def add_candidate(candidate):
        if candidate and candidate not in sitemap_candidates:
            sitemap_candidates.append(candidate)

    for name in ("wp-sitemap.xml", "sitemap.xml", "sitemap_index.xml"):
        add_candidate(urljoin(BASE_URL, name))
        add_candidate(urljoin(BASE_URL, f"/{name}"))

    # Also inspect robots.txt for explicit sitemap entries.
    for robots_url in (urljoin(BASE_URL, "robots.txt"), urljoin(BASE_URL, "/robots.txt")):
        robots_resp = get(robots_url, log_errors=False)
        if not robots_resp:
            continue
        for line in robots_resp.text.splitlines():
            if line.lower().startswith("sitemap:"):
                maybe_sitemap = line.split(":", 1)[1].strip()
                if maybe_sitemap:
                    add_candidate(maybe_sitemap)

    all_urls = set()
    for sitemap_url in sitemap_candidates:
        print(f"Trying sitemap: {sitemap_url}")
        urls = parse_sitemap(sitemap_url)
        if urls:
            all_urls.update(urls)

    # Filter to only document URLs (if any)
    doc_urls = {u for u in all_urls if is_document_url(u)}
    print(f"Sitemap: {len(all_urls)} total URLs, {len(doc_urls)} document URLs.")
    return doc_urls, all_urls  # also return page URLs for crawling


# ------------------------------
# PHASE 3: Page Crawling
# ------------------------------
def crawl_pages(start_urls):
    """Visit HTML pages, extract <a href> document links."""
    visited = set()
    to_visit = []
    doc_urls = set()

    checkpoint_loaded = False
    if ENABLE_CRAWL_CHECKPOINT:
        checkpoint = load_crawl_checkpoint(CRAWL_CHECKPOINT_FILE)
        if checkpoint:
            visited = set(checkpoint.get("visited", []))
            to_visit = list(checkpoint.get("to_visit", []))
            doc_urls = set(checkpoint.get("doc_urls", []))
            checkpoint_loaded = True
            print(
                f"Resuming checkpoint: {len(visited)} visited, "
                f"{len(to_visit)} queued, {len(doc_urls)} docs"
            )

    if not checkpoint_loaded:
        to_visit = list(dict.fromkeys(start_urls))[:MAX_PAGE_CRAWL]
    else:
        for seed in start_urls:
            if seed not in visited and seed not in to_visit and len(to_visit) < MAX_PAGE_CRAWL:
                to_visit.append(seed)

    pages_since_checkpoint = 0

    def extract_links(html, current_url):
        soup = BeautifulSoup(html, 'lxml')
        seen_here = set()

        def evaluate_candidate(raw_value, parse_embedded=False):
            if not raw_value:
                return

            candidates = []
            if not parse_embedded:
                candidates.append(raw_value)
            if parse_embedded:
                candidates.extend(extract_urls_from_text(raw_value))

            for token in candidates:
                href = normalize_candidate_url(token, current_url)
                if not href or href in seen_here:
                    continue
                seen_here.add(href)

                if is_document_url(href):
                    if is_document_host_allowed(href):
                        doc_urls.add(href)
                    continue

                if not is_same_domain(href):
                    continue

                if href not in visited and len(to_visit) < MAX_PAGE_CRAWL:
                    if href not in to_visit and is_page_in_scope(href) and not href.endswith(NON_HTML_SUFFIXES):
                        to_visit.append(href)

        for tag in soup.find_all(True):
            for attr in EXTRA_LINK_ATTRIBUTES:
                value = tag.get(attr)
                if value:
                    evaluate_candidate(value, parse_embedded=(attr == 'onclick'))

        # Also inspect raw HTML/inline scripts for hardcoded URLs.
        evaluate_candidate(html, parse_embedded=True)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        while to_visit and len(visited) < MAX_PAGE_CRAWL:
            # Add new URLs to visit in batches
            while to_visit and len(futures) < MAX_WORKERS * 2:
                url = to_visit.pop(0)
                if url in visited:
                    continue
                visited.add(url)
                pages_since_checkpoint += 1
                futures[executor.submit(get, url)] = url
            # Process completed
            done = []
            for future in as_completed(futures):
                url = futures.pop(future)
                try:
                    resp = future.result()
                    if resp and resp.status_code == 200:
                        content_type = (resp.headers.get('content-type') or '').lower()
                        if 'xml' not in content_type or 'html' in content_type:
                            extract_links(resp.text, url)
                except Exception as e:
                    print(f"Error crawling {url}: {e}")
                time.sleep(REQUEST_DELAY)
                done.append(future)
            # Remove done futures
            for f in done:
                if f in futures:
                    del futures[f]

            if ENABLE_CRAWL_CHECKPOINT and pages_since_checkpoint >= CRAWL_CHECKPOINT_SAVE_EVERY:
                save_crawl_checkpoint(CRAWL_CHECKPOINT_FILE, visited, to_visit, doc_urls)
                pages_since_checkpoint = 0

    if ENABLE_CRAWL_CHECKPOINT:
        if CLEAR_CHECKPOINT_ON_COMPLETE and not to_visit:
            clear_crawl_checkpoint(CRAWL_CHECKPOINT_FILE)
        else:
            save_crawl_checkpoint(CRAWL_CHECKPOINT_FILE, visited, to_visit, doc_urls)

    print(f"Page crawl: visited {len(visited)} pages, found {len(doc_urls)} document links.")
    return doc_urls


# ------------------------------
# PHASE 4: Download All Documents
# ------------------------------
def download_document(url, directory):
    """Download a single document and save it."""
    try:
        resp = get(url, stream=True)
        if not resp:
            return None

        content_type = (resp.headers.get('content-type') or '').lower()
        if content_type.startswith('image/') or content_type.startswith('video/'):
            print(f"Skipping media response at {url} (content-type: {content_type})")
            return None

        if 'text/html' in content_type and not any(urlparse(url).path.lower().endswith(ext) for ext in DOCUMENT_EXTENSIONS):
            print(f"Skipping non-document response at {url} (content-type: {content_type})")
            return None

        filename = filename_from_response(url, resp)
        filepath = os.path.join(directory, filename)

        # Avoid overwriting; append number if exists
        base, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(filepath):
            filepath = os.path.join(directory, f"{base}_{counter}{ext}")
            counter += 1

        total = int(resp.headers.get('content-length', 0))
        with open(filepath, 'wb') as f:
            if total:
                print(f"Downloading {filename} ({total//1024} KB)...")
            else:
                print(f"Downloading {filename}...")
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return filepath
    except Exception as e:
        print(f"Failed to download {url}: {e}")
        return None


def download_all(doc_urls):
    """Download all discovered documents in parallel."""
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    downloaded = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(download_document, url, DOWNLOAD_DIR): url
                   for url in doc_urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                result = future.result()
                if result:
                    downloaded.append(result)
            except Exception as e:
                print(f"Error on {url}: {e}")
    return downloaded


# ------------------------------
# MAIN
# ------------------------------
def main():
    print(f"Starting document discovery on {BASE_URL}")
    all_doc_urls = set()

    # Phase 1: WordPress REST API (most effective)
    wp_docs = get_wp_media_documents()
    all_doc_urls.update(wp_docs)

    # Phase 2: Sitemaps
    sitemap_docs, page_urls = get_sitemap_documents()
    all_doc_urls.update(sitemap_docs)

    # Phase 3: Crawl HTML pages for extra documents.
    crawl_seeds = set(page_urls)
    crawl_seeds.add(BASE_URL)
    crawl_seeds.update(PRIORITY_SEED_URLS)
    crawled_docs = crawl_pages(crawl_seeds)
    all_doc_urls.update(crawled_docs)

    # Final dedup
    all_doc_urls = set(u for u in all_doc_urls if is_document_url(u) and is_document_host_allowed(u))
    export_discovered_urls_csv(all_doc_urls, EXPORT_DISCOVERED_URLS_CSV)
    print(f"\nTotal unique document URLs found: {len(all_doc_urls)}")
    if not all_doc_urls:
        print("No documents found.")
        return

    # Phase 4: Download
    print("Starting downloads...")
    downloaded = download_all(all_doc_urls)
    print(f"Downloaded {len(downloaded)} documents to '{DOWNLOAD_DIR}/'")

    # Summary
    for f in sorted(os.listdir(DOWNLOAD_DIR))[:10]:
        print(f" - {f}")
    if len(downloaded) > 10:
        print(f" ... and {len(downloaded)-10} more files")


if __name__ == "__main__":
    main()