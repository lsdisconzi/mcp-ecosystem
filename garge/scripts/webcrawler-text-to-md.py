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

# NEW: Markdown conversion
from markdownify import markdownify as md

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===================== CONFIGURATION =====================
BASE_URL = 'https://comunitamonzabrianza.it/'
SAVE_DIR = './crawler_output/comunitamonzabrianza'
MAX_PAGES = 100
MAX_DEPTH = 3
DOWNLOAD_ASSETS = False
SAME_DOMAIN_ONLY = True
TIMEOUT = 60

# NEW: Path for the combined Markdown file
COMBINED_MD_FILENAME = 'combined_knowledge.md'

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


# ----------------------- EXISTING HELPERS -----------------------
def download_file(url, save_dir):
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
    for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
        tag.decompose()
    text = soup.get_text(separator=' ', strip=True)
    return re.sub(r'\s+', ' ', text)


def clean_url(url):
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


# ----------------------- NEW: MARKDOWN GENERATION -----------------------
def html_to_markdown(html_content):
    """Convert HTML to clean Markdown, stripping non-content tags."""
    soup = BeautifulSoup(html_content, 'html.parser')

    # Remove the same unwanted elements as in text extraction
    for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
        tag.decompose()

    # Optional: if a main content container exists, narrow down to it
    main = soup.find('article') or soup.find('main') or soup.find('div', class_='content')
    target = main if main else soup

    # Convert to Markdown with ATX-style headings (###)
    markdown = md(str(target), heading_style="ATX", strip=['img'])
    return markdown.strip()


def extract_title(html_content, fallback_filename):
    """Extract a human-readable title from the HTML page."""
    soup = BeautifulSoup(html_content, 'html.parser')
    # Prefer <title>
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    # Try first <h1>
    h1 = soup.find('h1')
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    # Fallback: use filename without extension
    return os.path.splitext(fallback_filename)[0]


def sanitize_anchor(text):
    """Create a URL‑safe anchor from text (for internal TOC links)."""
    # Keep only alphanumeric, spaces, hyphens – then replace spaces with hyphens
    anchor = re.sub(r'[^\w\s-]', '', text).strip().lower()
    anchor = re.sub(r'[\s]+', '-', anchor)
    return anchor


def generate_combined_markdown(save_dir, output_filename):
    """Read all saved HTML pages, convert to Markdown, and produce one file with TOC."""
    pages_dir = os.path.join(save_dir, 'pages')
    if not os.path.isdir(pages_dir):
        logger.warning("No 'pages' directory found – cannot build combined Markdown.")
        return

    html_files = sorted([f for f in os.listdir(pages_dir) if f.endswith('.html')])
    if not html_files:
        logger.warning("No HTML files to process.")
        return

    # Collect data for TOC
    entries = []
    for filename in html_files:
        filepath = os.path.join(pages_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            html = f.read()

        title = extract_title(html, filename)
        anchor = sanitize_anchor(filename)  # unique anchor based on filename
        entries.append((filename, title, anchor, html))

    # Build the combined Markdown
    output_path = os.path.join(save_dir, output_filename)
    with open(output_path, 'w', encoding='utf-8') as out:
        # Document header
        out.write("# Combined Crawled Knowledge Base\n\n")
        out.write(f"*Generated from {len(entries)} pages crawled from {BASE_URL}*\n\n")

        # Table of contents
        out.write("## Table of Contents\n\n")
        for idx, (_, title, anchor, _) in enumerate(entries, 1):
            out.write(f"{idx}. [{title}](#{anchor})\n")
        out.write("\n---\n\n")

        # Add each page content
        for idx, (filename, title, anchor, html) in enumerate(entries, 1):
            logger.info(f"Converting to Markdown: {filename}")
            md_content = html_to_markdown(html)

            # Section anchor (using HTML <a> for reliable in‑document links)
            out.write(f'<a id="{anchor}"></a>\n\n')
            out.write(f"## {idx}. {title}\n\n")
            out.write(f"*Original URL: {BASE_URL}{'' if BASE_URL.endswith('/') else '/'}... (see filename {filename})*\n\n")
            out.write(md_content)
            out.write("\n\n---\n\n")

    logger.info(f"Combined Markdown saved to: {output_path}")
    print(f"\n✅ Combined Markdown file ready: {output_path}")


# ----------------------- CRAWLING LOGIC (unchanged except final step) -----------------------
async def wait_for_content(page, url):
    selectors = 'article, main, .markdown, .docMainContainer'
    try:
        await page.wait_for_selector(selectors, timeout=15000)
        logger.debug(f"Content loaded on {url}")
    except Exception:
        logger.warning(f"No typical content container found on {url}, proceeding anyway.")
        try:
            await page.wait_for_function("document.body.innerText.length > 200", timeout=10000)
        except Exception:
            logger.warning(f"Fallback text wait failed for {url}")


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

        queue = [(BASE_URL, 0)]
        visited = set()

        while queue and len(visited) < MAX_PAGES:
            url, depth = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            logger.info(f"Fetching: {url} (depth {depth})")

            try:
                await page.goto(url, wait_until='networkidle', timeout=TIMEOUT * 1000)
            except Exception as e:
                logger.error(f"Navigation error: {e}")
                continue

            content = await page.content()
            if 'Security Checkpoint' in content or 'Code 11' in content:
                logger.warning("Security checkpoint detected – skipping this page.")
                continue

            await wait_for_content(page, url)
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

            for link in soup.find_all('a', href=True):
                href = urljoin(url, link['href']).split('#')[0].rstrip('/')
                if href in visited:
                    continue
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


# ----------------------- MAIN -----------------------
def main():
    os.makedirs(os.path.join(SAVE_DIR, 'pages'), exist_ok=True)
    os.makedirs(os.path.join(SAVE_DIR, 'texts'), exist_ok=True)

    # Run the crawler
    asyncio.run(crawl())

    # Show stats
    pages_dir = os.path.join(SAVE_DIR, 'pages')
    texts_dir = os.path.join(SAVE_DIR, 'texts')
    html_files = [f for f in os.listdir(pages_dir) if f.endswith('.html')] if os.path.exists(pages_dir) else []
    txt_files = [f for f in os.listdir(texts_dir) if f.endswith('.txt')] if os.path.exists(texts_dir) else []
    logger.info(f"HTML pages saved: {len(html_files)}")
    logger.info(f"Text files saved: {len(txt_files)}")

    # NEW: Convert all HTML pages to one navigable Markdown file
    generate_combined_markdown(SAVE_DIR, COMBINED_MD_FILENAME)


if __name__ == '__main__':
    main()