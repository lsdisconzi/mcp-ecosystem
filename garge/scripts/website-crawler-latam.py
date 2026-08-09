import os
import re
import asyncio
import logging
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===================== CONFIGURATION =====================
BASE_URL = 'https://www.latamairlines.com/en/'
SAVE_DIR = './crawler_output/latam'
MAX_PAGES = 100
MAX_DEPTH = 3
DOWNLOAD_ASSETS = False
SAME_DOMAIN_ONLY = True
PAGE_LOAD_TIMEOUT = 45          # seconds for initial load
CONTENT_WAIT_TIMEOUT = 30       # seconds to wait for dynamic content
CHALLENGE_TIMEOUT = 60          # seconds to wait for Cloudflare to pass

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


async def handle_cloudflare(page):
    """Wait for Cloudflare challenge to finish."""
    try:
        # Look for the challenge iframe or text
        challenge_selector = 'iframe[src*="challenge"], #cf-challenge-running, .cf-browser-verification'
        await page.wait_for_selector(challenge_selector, timeout=5000)
        logger.info("Cloudflare challenge detected – waiting for it to pass...")
        # Wait until the challenge disappears
        await page.wait_for_selector(challenge_selector, state='detached', timeout=CHALLENGE_TIMEOUT * 1000)
        logger.info("Cloudflare challenge passed.")
    except Exception:
        # No challenge or already passed
        pass


async def accept_cookies(page):
    """Try to click the cookie consent button if present."""
    try:
        # Common cookie consent selectors
        cookie_selectors = [
            'button[aria-label*="cookie"]',
            'button[id*="cookie"]',
            'button[class*="cookie"]',
            '#onetrust-accept-btn-handler',
            '.cookie-accept'
        ]
        for selector in cookie_selectors:
            if await page.locator(selector).count() > 0:
                await page.locator(selector).first.click(timeout=5000)
                logger.info("Cookie consent accepted.")
                await asyncio.sleep(1)
                break
    except Exception:
        pass


async def wait_for_content(page, url):
    """
    Wait for meaningful content to appear.
    Uses a set of selectors and falls back to text length.
    """
    # Primary content containers (based on common SPA patterns)
    primary_selectors = [
        'main',
        'article',
        '.content',
        '.main-content',
        '.page-content',
        '.post-content',
        '#content',
        '#main',
        '[role="main"]'
    ]

    # Try each selector, stop at first success
    for selector in primary_selectors:
        try:
            await page.wait_for_selector(selector, timeout=8000)
            logger.debug(f"Content detected with selector '{selector}' on {url}")
            return
        except Exception:
            continue

    # Fallback: wait until body text length > 500 characters
    try:
        await page.wait_for_function(
            "document.body.innerText.length > 500",
            timeout=CONTENT_WAIT_TIMEOUT * 1000
        )
        logger.debug(f"Content detected by text length on {url}")
    except Exception:
        logger.warning(f"Content not found within {CONTENT_WAIT_TIMEOUT}s on {url}, proceeding anyway.")


async def crawl():
    async with async_playwright() as p:
        # Launch with stealth-friendly args
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-site-isolation-trials'
            ]
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='en-US',
            timezone_id='America/New_York',
            bypass_csp=True
        )
        page = await context.new_page()

        # Stealth: hide automation traces
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en'] });
            window.chrome = { runtime: {} };
        """)

        queue = [(BASE_URL, 0)]
        visited = set()

        while queue and len(visited) < MAX_PAGES:
            url, depth = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            logger.info(f"Fetching: {url} (depth {depth})")

            try:
                # Load page with 'domcontentloaded' to avoid endless network idle
                response = await page.goto(url, wait_until='domcontentloaded', timeout=PAGE_LOAD_TIMEOUT * 1000)

                # If response is blocked or error, skip
                if response and not response.ok:
                    logger.warning(f"HTTP {response.status} for {url}, skipping.")
                    continue

                # Handle Cloudflare
                await handle_cloudflare(page)

                # Accept cookies if present
                await accept_cookies(page)

                # Wait for dynamic content to render
                await wait_for_content(page, url)

                # Additional short sleep to allow any final DOM updates
                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"Error loading {url}: {e}")
                continue

            # Extract HTML and text
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')

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

            # Download assets (if enabled)
            if DOWNLOAD_ASSETS:
                assets = []
                for img in soup.find_all('img', src=True):
                    src = img['src']
                    if not src.startswith('data:'):
                        assets.append(urljoin(url, src))
                for link in soup.find_all('link', href=True, rel=lambda x: x and 'stylesheet' in x):
                    assets.append(urljoin(url, link['href']))
                for script in soup.find_all('script', src=True):
                    assets.append(urljoin(url, script['src']))
                for asset in set(assets):
                    if is_same_domain(BASE_URL, asset):
                        download_file(asset, SAVE_DIR)

            # Extract links for crawling
            for link in soup.find_all('a', href=True):
                href = urljoin(url, link['href']).split('#')[0].rstrip('/')
                if href in visited:
                    continue
                if any(href.endswith(ext) for ext in SKIP_EXTENSIONS):
                    if DOWNLOAD_ASSETS:
                        download_file(href, SAVE_DIR)
                    continue
                if should_crawl(href, BASE_URL) and (depth + 1) <= MAX_DEPTH:
                    queue.append((href, depth + 1))

        await browser.close()
        logger.info(f"Crawling finished. Visited {len(visited)} pages.")


def main():
    os.makedirs(os.path.join(SAVE_DIR, 'pages'), exist_ok=True)
    os.makedirs(os.path.join(SAVE_DIR, 'texts'), exist_ok=True)
    asyncio.run(crawl())

    # Statistics
    pages_dir = os.path.join(SAVE_DIR, 'pages')
    texts_dir = os.path.join(SAVE_DIR, 'texts')
    html_files = [f for f in os.listdir(pages_dir) if f.endswith('.html')] if os.path.exists(pages_dir) else []
    txt_files = [f for f in os.listdir(texts_dir) if f.endswith('.txt')] if os.path.exists(texts_dir) else []
    logger.info(f"HTML pages saved: {len(html_files)}")
    logger.info(f"Text files saved: {len(txt_files)}")


if __name__ == '__main__':
    main()