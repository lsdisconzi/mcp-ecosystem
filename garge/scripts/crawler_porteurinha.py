import os
import re
import time
import asyncio
import logging
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import nodriver as uc
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===================== CONFIGURATION =====================
BASE_URL = 'https://ilai.memory.com.br/#/9CJZDH/1/share?resource=public/inicio'
BASE_ORIGIN = 'https://ilai.memory.com.br'

SAVE_DIR = './crawler_output/porteurinha'
MAX_PAGES = 500
MAX_DEPTH = 5
DOWNLOAD_ASSETS = False
SAME_DOMAIN_ONLY = True
TIMEOUT = 30
CONTENT_WAIT_TIMEOUT = 25

SKIP_PATHS = {
    '/assets/', '/images/', '/img/', '/css/', '/js/', '/fonts/',
    '/wp-admin/', '/wp-includes/', '/wp-json/', '/wp-content/uploads/',
    '/feed/', '/trackback/', '/xmlrpc.php', '/search/'
}
SKIP_EXTENSIONS = ('.pdf', '.jpg', '.jpeg', '.png', '.gif', '.svg',
                   '.css', '.js', '.doc', '.docx', '.xls', '.xlsx',
                   '.zip', '.rar', '.xml', '.txt', '.csv')
# =========================================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def download_file(url, save_dir):
    """Download an asset file with retries."""
    parsed = urlparse(url)
    domain = parsed.netloc.replace(':', '_')
    path = parsed.path.lstrip('/') or 'index.html'
    local_path = os.path.join(save_dir, domain, path)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    for attempt in range(3):
        try:
            r = requests.get(url, stream=True, timeout=30, verify=False)
            if r.status_code == 200:
                with open(local_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                return True
        except Exception:
            time.sleep(2)
    return False


def extract_text(soup):
    """Remove scripts/styles/nav/footer and return clean text."""
    for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
        tag.decompose()
    text = soup.get_text(separator=' ', strip=True)
    return re.sub(r'\s+', ' ', text)


def clean_url(url):
    """Safe filename from URL (hash-friendly)."""
    name = re.sub(r'https?://(www\.)?', '', url)
    name = name.replace('/', '_')
    name = re.sub(r'[^\w\-_. ]', '_', name)
    return name[:200]


def is_same_domain(url1, url2):
    d1 = urlparse(url1).netloc.lower().replace('www.', '')
    d2 = urlparse(url2).netloc.lower().replace('www.', '')
    return d1 == d2


def normalize_link(base_origin, href):
    """Convert hash-based href to absolute URL."""
    href = href.strip()
    if href.startswith('#'):
        if href.startswith('#/'):
            return base_origin + '/' + href
        else:
            return base_origin + href
    else:
        return urljoin(base_origin, href)


def should_crawl(url, base):
    """Decide whether to crawl a URL."""
    if SAME_DOMAIN_ONLY and not is_same_domain(base, url):
        return False

    parsed = urlparse(url)
    path = parsed.path.lower()
    has_hash = bool(parsed.fragment)

    # Allow hash-based routes even when path is '/'
    if path in ('', '/'):
        if not has_hash:
            return False

    # Skip share links (they would lead to duplicate pages)
    if '/share' in parsed.fragment or 'share?' in parsed.fragment:
        return False

    if any(path.startswith(skip) for skip in SKIP_PATHS):
        return False
    if any(path.endswith(ext) for ext in SKIP_EXTENSIONS):
        return False
    return True


async def wait_for_content(tab, url):
    """Wait for meaningful content."""
    await asyncio.sleep(3)

    try:
        await tab.wait_for(
            "document.body.innerText.length > 500",
            timeout=CONTENT_WAIT_TIMEOUT
        )
        logger.debug(f"Content found on {url}")
    except Exception:
        logger.warning(f"Content slow or missing on {url}")


async def get_current_url(tab):
    """Return current URL after SPA routing."""
    return await tab.evaluate("window.location.href")


async def crawl():
    browser = await uc.start(
        headless=True,
        browser_args=['--no-sandbox', '--disable-dev-shm-usage']
    )

    # Optional: pre-load the main site to obtain any necessary cookies/session
    # This may help avoid being redirected to login.
    try:
        pre_tab = await browser.get(BASE_ORIGIN)
        await asyncio.sleep(5)
        logger.info("Pre-loaded base origin to set initial cookies/session")
    except Exception as e:
        logger.warning(f"Could not pre-load base origin: {e}")

    queue = [(BASE_URL, 0)]
    visited = set()

    while queue and len(visited) < MAX_PAGES:
        url, depth = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        logger.info(f"Fetching: {url} (depth {depth})")

        tab = None
        try:
            tab = await browser.get(url)
            await wait_for_content(tab, url)

            current_url = await get_current_url(tab)
            current_url = current_url.strip()
            logger.info(f"Resolved to: {current_url}")

            if current_url != url:
                visited.add(current_url)

        except Exception as e:
            logger.error(f"Error loading {url}: {e}")
            continue

        html = await tab.get_content()
        soup = BeautifulSoup(html, 'html.parser')

        # Save HTML using the canonical URL
        html_filename = os.path.join(SAVE_DIR, 'pages', clean_url(current_url) + '.html')
        os.makedirs(os.path.dirname(html_filename), exist_ok=True)
        with open(html_filename, 'w', encoding='utf-8') as f:
            f.write(soup.prettify())
        logger.info(f"Saved HTML: {html_filename}")

        # Save text
        text = extract_text(soup)
        if text.strip():
            txt_filename = os.path.join(SAVE_DIR, 'texts', clean_url(current_url) + '.txt')
            os.makedirs(os.path.dirname(txt_filename), exist_ok=True)
            with open(txt_filename, 'w', encoding='utf-8') as f:
                f.write(text)
            logger.info(f"Saved text: {txt_filename}")

        # Extract internal links (skip share links)
        for link in soup.find_all('a', href=True):
            raw_href = link['href'].strip()
            if not raw_href:
                continue

            absolute = normalize_link(BASE_ORIGIN, raw_href)

            if '/share' in absolute or 'share?' in absolute:
                continue

            if absolute in visited:
                continue

            if any(absolute.endswith(ext) for ext in SKIP_EXTENSIONS):
                if DOWNLOAD_ASSETS:
                    download_file(absolute, SAVE_DIR)
                continue

            if should_crawl(absolute, BASE_URL) and (depth + 1) <= MAX_DEPTH:
                queue.append((absolute, depth + 1))

    # Correctly stop the browser (no await)
    browser.stop()
    logger.info(f"Finished. Visited {len(visited)} pages.")


def main():
    os.makedirs(os.path.join(SAVE_DIR, 'pages'), exist_ok=True)
    os.makedirs(os.path.join(SAVE_DIR, 'texts'), exist_ok=True)
    asyncio.run(crawl())

    pages_dir = os.path.join(SAVE_DIR, 'pages')
    texts_dir = os.path.join(SAVE_DIR, 'texts')
    html_files = [f for f in os.listdir(pages_dir) if f.endswith('.html')] if os.path.exists(pages_dir) else []
    txt_files = [f for f in os.listdir(texts_dir) if f.endswith('.txt')] if os.path.exists(texts_dir) else []
    logger.info(f"HTML pages saved: {len(html_files)}")
    logger.info(f"Text files saved: {len(txt_files)}")


if __name__ == '__main__':
    main()