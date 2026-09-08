import os
import re
import time
import asyncio
import logging
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===================== CONFIGURATION =====================
BASE_URL = 'https://www.theburntchefproject.com/'
SAVE_DIR = './crawler_output/theburntchefproject'
MAX_PAGES = 500
MAX_DEPTH = 5
DOWNLOAD_ASSETS = False
SAME_DOMAIN_ONLY = True
TIMEOUT = 60                     # seconds per page
MIN_BODY_TEXT = 200              # minimum characters to consider page loaded
SCROLL_TO_BOTTOM = True          # enable lazy-loading

# Paths to skip (only obvious non-content directories)
SKIP_PATHS = {
    '/wp-admin/', '/wp-includes/', '/wp-json/', '/wp-content/uploads/',
    '/feed/', '/trackback/', '/xmlrpc.php', '/search/',
    '/assets/', '/images/', '/img/', '/css/', '/js/', '/fonts/'
}
SKIP_EXTENSIONS = ('.pdf', '.zip', '.mp4', '.mp3', '.exe', '.doc', '.docx')
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
    """
    Extract clean text from BeautifulSoup.
    Removes scripts/styles and (optionally) common navigation/footer elements,
    while preserving paragraph structure.
    """
    # Remove script and style tags
    for tag in soup(['script', 'style']):
        tag.decompose()

    # Optionally remove nav/footer/header – but you might want to keep them.
    # Uncomment the next line if you want to strip them:
    # for tag in soup(['nav', 'footer', 'header', 'aside']):
    #     tag.decompose()

    # Replace block-level tags with newlines to preserve paragraphs
    for tag in soup.find_all(['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'blockquote']):
        tag.append('\n')

    text = soup.get_text(separator=' ', strip=True)
    # Collapse multiple spaces/newlines
    text = re.sub(r'\s+', ' ', text).strip()
    return text


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
    # Do not skip root or empty path
    if path in ('', '/', '/index.html'):
        return True
    return True


# ===================== MAIN CRAWL =====================
async def wait_for_content(page, url, min_text=MIN_BODY_TEXT):
    """Wait for the page to load sufficient text content."""
    try:
        # Wait for a common main content selector (customize as needed)
        selectors = [
            '[role="main"]',
            '.entry-content',
            '.post-content',
            'article',
            'main',
            '.markdown',
            '.docMainContainer'
        ]
        # Try each selector
        for sel in selectors:
            try:
                await page.wait_for_selector(sel, timeout=5000)
                logger.debug(f"Selector {sel} found on {url}")
                return
            except:
                continue
        # Fallback: wait until body text length exceeds threshold
        await page.wait_for_function(
            f"document.body.innerText.length > {min_text}",
            timeout=10000
        )
        logger.debug(f"Body text length exceeded {min_text} on {url}")
    except Exception:
        logger.warning(f"Timeout waiting for content on {url}, proceeding anyway.")


async def scroll_page(page):
    """Scroll to bottom and back to top to trigger lazy loading."""
    try:
        await page.evaluate("""
            window.scrollTo(0, document.body.scrollHeight);
        """)
        await asyncio.sleep(1)
        await page.evaluate("""
            window.scrollTo(0, 0);
        """)
        await asyncio.sleep(0.5)
    except Exception as e:
        logger.debug(f"Scroll failed: {e}")


async def crawl():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='en-US',
            timezone_id='America/New_York'
        )
        page = await context.new_page()
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en'] });
            window.chrome = { runtime: {} };
        """)

        # Optional: dismiss cookie consent (uncomment if needed)
        # try:
        #     await page.click('button:has-text("Accept")', timeout=5000)
        # except:
        #     pass

        queue = [(BASE_URL, 0)]
        visited = set()


        while queue and len(visited) < MAX_PAGES:
            url, depth = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            logger.info(f"Fetching: {url} (depth {depth})")

            # Retry navigation on failure (with 'load' instead of 'networkidle')
            for attempt in range(2):
                try:
                    await page.goto(url, wait_until='load', timeout=30000)  # 30s timeout
                    # Wait a moment for dynamic content to start
                    await asyncio.sleep(1)
                    break
                except Exception as e:
                    if attempt == 0:
                        logger.warning(f"Navigation error (attempt {attempt+1}): {e}, retrying...")
                        await asyncio.sleep(2)
                    else:
                        logger.error(f"Navigation failed after retries: {e}")
                        raise

            # Check for security / blocking pages
            content = await page.content()
            if 'Security Checkpoint' in content or 'Code 11' in content:
                logger.warning("Security checkpoint detected – skipping this page.")
                continue

            # Scroll to load lazy content
            if SCROLL_TO_BOTTOM:
                await scroll_page(page)

            # Wait for dynamic content (this will also give extra time if needed)
            await wait_for_content(page, url)


            # Get final rendered HTML
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')

            # Save HTML
            html_filename = os.path.join(SAVE_DIR, 'pages', clean_url(url) + '.html')
            os.makedirs(os.path.dirname(html_filename), exist_ok=True)
            with open(html_filename, 'w', encoding='utf-8') as f:
                f.write(soup.prettify())
            logger.info(f"Saved HTML: {html_filename}")

            # Save plain text
            text = extract_text(soup)
            if text.strip():
                txt_filename = os.path.join(SAVE_DIR, 'texts', clean_url(url) + '.txt')
                os.makedirs(os.path.dirname(txt_filename), exist_ok=True)
                with open(txt_filename, 'w', encoding='utf-8') as f:
                    f.write(text)
                logger.info(f"Saved text: {txt_filename} ({len(text)} chars)")
            else:
                logger.warning(f"No text extracted from {url}")

            # Download assets if enabled
            if DOWNLOAD_ASSETS:
                assets = []
                for img in soup.find_all('img', src=True):
                    src = img['src']
                    if isinstance(src, list): src = src[0]
                    if not src.startswith('data:'):
                        assets.append(urljoin(url, src))
                for link in soup.find_all('link', href=True, rel=lambda x: x and 'stylesheet' in x):
                    href = link['href']
                    if isinstance(href, list): href = href[0]
                    assets.append(urljoin(url, href))
                for script in soup.find_all('script', src=True):
                    src = script['src']
                    if isinstance(src, list): src = src[0]
                    assets.append(urljoin(url, src))
                for asset in set(assets):
                    if is_same_domain(BASE_URL, asset):
                        download_file(asset, SAVE_DIR)

            # Extract new links
            for link in soup.find_all('a', href=True):
                href_attr = link['href']
                if isinstance(href_attr, list): href_attr = href_attr[0]
                href = urljoin(url, href_attr).split('#')[0].rstrip('/')
                if href in visited:
                    continue
                # Download asset files if enabled
                if any(href.endswith(ext) for ext in SKIP_EXTENSIONS):
                    if DOWNLOAD_ASSETS:
                        download_file(href, SAVE_DIR)
                    continue
                if should_crawl(href, BASE_URL):
                    new_depth = depth + 1
                    if new_depth <= MAX_DEPTH:
                        queue.append((href, new_depth))

        await browser.close()
        logger.info(f"Crawling finished. Visited {len(visited)} pages.")


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