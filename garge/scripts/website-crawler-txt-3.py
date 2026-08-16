import os
import re
import time
import asyncio
import logging
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import nodriver as uc          # <-- using nodriver instead of Playwright
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===================== CONFIGURATION =====================
BASE_URL = 'https://sixthstreetlendingpartners.com/team/'
SAVE_DIR = './crawler_output/sixthstreet-team'  # where to save HTML and text
MAX_PAGES = 100
MAX_DEPTH = 3
DOWNLOAD_ASSETS = False
SAME_DOMAIN_ONLY = True
TIMEOUT = 30                   # seconds for page load
CONTENT_WAIT_TIMEOUT = 25      # seconds to wait for dynamic content

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
    """Download an asset file with retries (unchanged)."""
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
    """Safe filename from URL."""
    name = re.sub(r'https?://(www\.)?', '', url)
    name = name.replace('/', '_')
    name = re.sub(r'[^\w\-_\. ]', '_', name)
    return name[:200]


def is_same_domain(url1, url2):
    d1 = urlparse(url1).netloc.lower().replace('www.', '')
    d2 = urlparse(url2).netloc.lower().replace('www.', '')
    return d1 == d2


def should_crawl(url, base):
    if SAME_DOMAIN_ONLY and not is_same_domain(base, url):
        return False
    path = urlparse(url).path.lower()
    if any(path.startswith(skip) for skip in SKIP_PATHS):
        return False
    if any(path.endswith(ext) for ext in SKIP_EXTENSIONS):
        return False
    if path in ('', '/'):
        return False
    return True


async def wait_for_content(tab, url):
    """Wait for meaningful content on the page (nodriver version)."""
    # Try common selectors
    selectors = 'main, article, .content, .main-content, .page-content, .post-content'
    try:
        await tab.wait_for(selector=selectors, timeout=CONTENT_WAIT_TIMEOUT)
        logger.debug(f"Content detected with selector on {url}")
        return
    except Exception:
        pass

    # Fallback: wait for body text length
    try:
        await tab.wait_for(
            "document.body.innerText.length > 200",
            timeout=CONTENT_WAIT_TIMEOUT
        )
    except Exception:
        logger.warning(f"Content not found within {CONTENT_WAIT_TIMEOUT}s on {url}")


async def crawl():
    browser = await uc.start(headless=True, browser_args=['--no-sandbox', '--disable-dev-shm-usage'])
    queue = [(BASE_URL, 0)]
    visited = set()

    while queue and len(visited) < MAX_PAGES:
        url, depth = queue.pop(0)
        if url in visited: continue
        visited.add(url)
        logger.info(f"Fetching: {url} (depth {depth})")

        tab = None
        try:
            # Get a new tab (nodriver handles reuse internally)
            tab = await browser.get(url)
            await asyncio.sleep(1)

            # Security check
            if 'Just a moment' in await tab.evaluate("document.title") or 'cf-challenge-running' in await tab.get_content():
                logger.warning(f"Cloudflare challenge on {url} – skipping")
                continue

            await wait_for_content(tab, url)

        except Exception as e:
            logger.error(f"Error loading {url}: {e}")
            continue
        finally:
            # Don't close tab manually – let nodriver manage it
            pass

        # Process the page (unchanged)
        html = await tab.get_content()
        soup = BeautifulSoup(html, 'html.parser')

        html_filename = os.path.join(SAVE_DIR, 'pages', clean_url(url) + '.html')
        os.makedirs(os.path.dirname(html_filename), exist_ok=True)
        with open(html_filename, 'w', encoding='utf-8') as f:
            f.write(soup.prettify())
        logger.info(f"Saved HTML: {html_filename}")

        text = extract_text(soup)
        if text.strip():
            txt_filename = os.path.join(SAVE_DIR, 'texts', clean_url(url) + '.txt')
            os.makedirs(os.path.dirname(txt_filename), exist_ok=True)
            with open(txt_filename, 'w', encoding='utf-8') as f:
                f.write(text)
            logger.info(f"Saved text: {txt_filename}")

        if DOWNLOAD_ASSETS:
            assets = []
            for img in soup.find_all('img', src=True):
                if not img['src'].startswith('data:'):
                    assets.append(urljoin(url, img['src']))
            for link in soup.find_all('link', href=True, rel=lambda r: r and 'stylesheet' in r):
                assets.append(urljoin(url, link['href']))
            for script in soup.find_all('script', src=True):
                assets.append(urljoin(url, script['src']))
            for asset in set(assets):
                if is_same_domain(BASE_URL, asset):
                    download_file(asset, SAVE_DIR)

        # Extract links
        for link in soup.find_all('a', href=True):
            href = urljoin(url, link['href']).split('#')[0].rstrip('/')
            if href in visited: continue
            if any(href.endswith(ext) for ext in SKIP_EXTENSIONS):
                if DOWNLOAD_ASSETS: download_file(href, SAVE_DIR)
                continue
            if should_crawl(href, BASE_URL) and (depth + 1) <= MAX_DEPTH:
                queue.append((href, depth + 1))

    await browser.stop()
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