import argparse
import hashlib
import logging
import os
import re
import socket
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# Suppress SSL warnings for sites with intermittent certificate chain issues.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TIMEOUT_CONNECT = 12
TIMEOUT_READ = 60
FILE_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".csv",
    ".zip",
    ".rar",
    ".7z",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".txt",
    ".xml",
}
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    )
}


@dataclass
class MenuNode:
    title: str
    url: Optional[str]
    children: list["MenuNode"] = field(default_factory=list)
    content_html: Optional[str] = None
    base_url: Optional[str] = None


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def slugify(value: str) -> str:
    value = clean_text(value).lower()
    value = re.sub(r"[^a-z0-9\-\s_]", "", value)
    value = re.sub(r"[\s_]+", "-", value).strip("-")
    return value or "item"


def unique_slug(title: str, url: Optional[str]) -> str:
    base = slugify(title)
    digest_source = url or title
    digest = hashlib.md5(digest_source.encode("utf-8")).hexdigest()[:8]
    return f"{base}-{digest}"


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme:
        url = f"https://{url}"
    return url.strip()


def is_host_reachable(url: str, timeout: int = 6) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def pick_reachable_url(base_url: str) -> Optional[str]:
    normalized = normalize_url(base_url)
    parsed = urlparse(normalized)
    if not parsed.hostname:
        return None

    host = parsed.hostname or ""
    scheme = parsed.scheme or "https"

    candidate_hosts = [host]
    if host.startswith("www."):
        alt_host = host[4:]
    else:
        alt_host = f"www.{host}"

    if alt_host:
        candidate_hosts.append(alt_host)

    candidate_hosts = list(dict.fromkeys(candidate_hosts))

    for candidate_host in candidate_hosts:
        probe_url = f"{scheme}://{candidate_host}/"
        if is_host_reachable(probe_url):
            if candidate_host == host:
                return normalized

            rebuilt = parsed._replace(netloc=candidate_host)
            fallback_url = rebuilt.geturl()
            logger.warning("Primary URL unreachable, using fallback: %s", fallback_url)
            return fallback_url
    return None


def build_driver() -> webdriver.Chrome:
    options = Options()
    options.page_load_strategy = "eager"
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--allow-running-insecure-content")

    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(TIMEOUT_READ)
    driver.implicitly_wait(5)
    return driver


def fetch_html(url: str, session: requests.Session, driver: Optional[webdriver.Chrome]) -> Optional[str]:
    try:
        response = session.get(
            url,
            timeout=(TIMEOUT_CONNECT, TIMEOUT_READ),
            verify=False,
            headers=REQUEST_HEADERS,
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" in content_type or "application/xhtml+xml" in content_type:
            return response.text
        logger.info("Skipping non-HTML URL: %s (%s)", url, content_type)
        return None
    except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as err:
        logger.warning("Network error for %s: %s", url, err)
        return None
    except Exception as err:
        logger.warning("HTTP fetch failed for %s: %s", url, err)

    if not driver:
        return None

    try:
        logger.info("Falling back to Selenium for: %s", url)
        driver.get(url)
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        return driver.page_source
    except Exception as err:
        logger.warning("Selenium fetch failed for %s: %s", url, err)
        return None


def score_sidebar_candidate(node: BeautifulSoup) -> int:
    text = clean_text(node.get_text(" ", strip=True)).lower()
    links = node.find_all("a", href=True)
    nested_items = node.find_all("ul")
    score = len(links) + len(nested_items)

    keywords = [
        "resid",
        "processo seletivo",
        "coremu",
        "edital",
        "menu",
    ]
    for keyword in keywords:
        if keyword in text:
            score += 10
    if "sidebar" in " ".join(node.get("class", [])).lower():
        score += 15
    return score


def parse_menu_list(menu_ul: BeautifulSoup, base_url: str) -> list[MenuNode]:
    nodes: list[MenuNode] = []
    seen: set[tuple[str, Optional[str]]] = set()

    for li in menu_ul.find_all("li", recursive=False):
        anchor = li.find("a", href=True)
        nested = li.find("ul", recursive=False)

        title = ""
        link_url: Optional[str] = None

        if anchor:
            title = clean_text(anchor.get_text(" ", strip=True))
            href = clean_text(anchor.get("href", ""))
            if href:
                link_url = urljoin(base_url, href).split("#")[0]

        if not title:
            title = clean_text(li.get_text(" ", strip=True))
        if not title:
            continue

        children = parse_menu_list(nested, base_url) if nested else []
        key = (title.lower(), link_url)
        if key in seen:
            continue
        seen.add(key)
        nodes.append(MenuNode(title=title, url=link_url, children=children))

    return nodes


def extract_unirg_panel_tree(soup: BeautifulSoup, base_url: str) -> list[MenuNode]:
    """Extract UNIRG residency left sidebar that toggles in-page content panels."""
    container = soup.select_one("#accordionDesktop")
    if not container:
        return []

    menu_items = container.select("a.select-menu[id]")
    nodes: list[MenuNode] = []

    for item in menu_items:
        menu_id = clean_text(item.get("id", ""))
        if not menu_id:
            continue

        panel = container.select_one(f"#content{menu_id}")
        if not panel:
            panel = soup.select_one(f"#content{menu_id}")

        title = clean_text(item.get_text(" ", strip=True))
        if panel:
            heading = panel.select_one("h4.tituloCursos")
            if heading:
                heading_text = clean_text(heading.get_text(" ", strip=True))
                if heading_text:
                    title = heading_text

        if not title:
            continue

        node = MenuNode(
            title=title,
            url=f"{base_url}#content{menu_id}",
            content_html=str(panel) if panel else None,
            base_url=base_url,
        )

        if panel:
            for card in panel.select("div.card.cardSubItem"):
                btn = card.select_one("button.select-menu2")
                card_title = clean_text(btn.get_text(" ", strip=True)) if btn else ""
                card_title = re.sub(r"^add\s+remove\s+", "", card_title, flags=re.IGNORECASE)
                if not card_title:
                    header = card.select_one("div.card-header")
                    if header:
                        card_title = clean_text(header.get_text(" ", strip=True))

                card_body = card.select_one("div.card-body")
                if not card_title or not card_body:
                    continue

                node.children.append(
                    MenuNode(
                        title=card_title,
                        url=f"{base_url}#card-{slugify(card_title)}",
                        content_html=str(card_body),
                        base_url=base_url,
                    )
                )

        nodes.append(node)

    if len(nodes) >= 5:
        return nodes
    return []


def extract_sidebar_tree(soup: BeautifulSoup, base_url: str) -> list[MenuNode]:
    # UNIRG residency uses in-page sidebar tabs + content panels rather than regular nav links.
    unirg_nodes = extract_unirg_panel_tree(soup, base_url)
    if unirg_nodes:
        return unirg_nodes

    selectors = [
        "aside",
        "div.sidebar",
        "div[class*='sidebar']",
        "div[class*='left']",
        "nav",
        "div.widget",
    ]
    candidates = []
    for selector in selectors:
        candidates.extend(soup.select(selector))

    if not candidates:
        candidates = soup.find_all(["aside", "nav", "div"])

    best_candidate = None
    best_score = -1
    for candidate in candidates:
        if not candidate.find("a", href=True):
            continue
        score = score_sidebar_candidate(candidate)
        if score > best_score:
            best_score = score
            best_candidate = candidate

    if not best_candidate:
        return []

    menu_candidates = best_candidate.find_all("ul")
    if not menu_candidates:
        return []

    menu_ul = max(menu_candidates, key=lambda node: len(node.find_all("a", href=True)))
    return parse_menu_list(menu_ul, base_url)


def pick_content_root(soup: BeautifulSoup) -> BeautifulSoup:
    selectors = [
        "main",
        "article",
        "div.entry-content",
        "div.post-content",
        "section.content",
        "div#content",
        "div.site-content",
    ]
    for selector in selectors:
        root = soup.select_one(selector)
        if root and len(clean_text(root.get_text(" ", strip=True))) > 100:
            return root
    return soup.body or soup


def element_is_in_banned_zone(element) -> bool:
    banned = {"script", "style", "noscript", "header", "footer", "nav"}
    for parent in element.parents:
        if getattr(parent, "name", None) in banned:
            return True
    return False


def html_to_markdown_lines(content_root: BeautifulSoup) -> list[str]:
    lines: list[str] = []
    for element in content_root.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        if element_is_in_banned_zone(element):
            continue
        text = clean_text(element.get_text(" ", strip=True))
        if not text:
            continue

        if element.name and element.name.startswith("h"):
            level = max(1, min(4, int(element.name[1])))
            line = f"{'#' * level} {text}"
        elif element.name == "li":
            line = f"- {text}"
        else:
            line = text

        if not lines or lines[-1] != line:
            lines.append(line)
    return lines


def should_download_link(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in FILE_EXTENSIONS)


def safe_filename(url: str) -> str:
    parsed = urlparse(url)
    name = os.path.basename(parsed.path) or "download.bin"
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    if len(name) > 180:
        base, ext = os.path.splitext(name)
        name = base[:160] + ext
    return name


def download_link_file(session: requests.Session, url: str, target_dir: str) -> Optional[str]:
    os.makedirs(target_dir, exist_ok=True)
    filename = safe_filename(url)
    local_path = os.path.join(target_dir, filename)

    if os.path.exists(local_path):
        return local_path

    try:
        response = session.get(
            url,
            timeout=(TIMEOUT_CONNECT, TIMEOUT_READ),
            verify=False,
            headers=REQUEST_HEADERS,
            stream=True,
        )
        response.raise_for_status()
        with open(local_path, "wb") as file_obj:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file_obj.write(chunk)
        return local_path
    except Exception as err:
        logger.warning("File download failed for %s: %s", url, err)
        return None


def collect_page_links(
    content_root: BeautifulSoup,
    page_url: str,
    session: requests.Session,
    download_dir: str,
    download_files: bool,
) -> list[dict]:
    links: list[dict] = []
    seen: set[str] = set()

    for anchor in content_root.find_all("a", href=True):
        href = clean_text(anchor.get("href", ""))
        if not href:
            continue
        full_url = urljoin(page_url, href).split("#")[0]
        if not full_url or full_url in seen:
            continue
        seen.add(full_url)

        text = clean_text(anchor.get_text(" ", strip=True)) or safe_filename(full_url)
        record = {
            "text": text,
            "url": full_url,
            "downloaded_path": None,
        }

        if download_files and should_download_link(full_url):
            downloaded = download_link_file(session, full_url, download_dir)
            if downloaded:
                record["downloaded_path"] = downloaded

        links.append(record)

    return links


def write_section_markdown(
    file_path: str,
    node: MenuNode,
    source_url: Optional[str],
    markdown_lines: list[str],
    links: list[dict],
    output_dir: str,
    error: Optional[str],
) -> None:
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    lines = [f"# {node.title}", ""]
    if source_url:
        lines.append(f"Source URL: {source_url}")
        lines.append("")
    if error:
        lines.append(f"Error: {error}")
        lines.append("")

    if markdown_lines:
        lines.append("## Content")
        lines.append("")
        lines.extend(markdown_lines)
        lines.append("")

    lines.append("## Links")
    lines.append("")
    if not links:
        lines.append("No links found.")
    else:
        for item in links:
            line = f"- [{item['text']}]({item['url']})"
            if item["downloaded_path"]:
                rel_path = os.path.relpath(item["downloaded_path"], os.path.dirname(file_path)).replace("\\", "/")
                line += f" -> downloaded: [{os.path.basename(item['downloaded_path'])}]({rel_path})"
            lines.append(line)

    with open(file_path, "w", encoding="utf-8") as file_obj:
        file_obj.write("\n".join(lines).strip() + "\n")


def build_tree_lines(nodes: list[MenuNode], depth: int = 0) -> list[str]:
    lines: list[str] = []
    prefix = "  " * depth
    for node in nodes:
        if node.url:
            lines.append(f"{prefix}- [{node.title}]({node.url})")
        else:
            lines.append(f"{prefix}- {node.title}")
        if node.children:
            lines.extend(build_tree_lines(node.children, depth + 1))
    return lines


def scrape_node(
    node: MenuNode,
    parent_dir: str,
    session: requests.Session,
    driver: Optional[webdriver.Chrome],
    output_dir: str,
    max_depth: int,
    depth: int,
    download_files: bool,
) -> dict:
    slug = unique_slug(node.title, node.url)
    node_dir = os.path.join(parent_dir, slug)
    os.makedirs(node_dir, exist_ok=True)
    section_md = os.path.join(node_dir, "index.md")

    links: list[dict] = []
    markdown_lines: list[str] = []
    error: Optional[str] = None

    if node.content_html:
        soup = BeautifulSoup(node.content_html, "html.parser")
        content_root = soup
        markdown_lines = html_to_markdown_lines(content_root)
        links = collect_page_links(
            content_root=content_root,
            page_url=node.base_url or node.url or "",
            session=session,
            download_dir=os.path.join(output_dir, "downloads", slug),
            download_files=download_files,
        )
    elif node.url:
        html = fetch_html(node.url, session, driver)
        if html:
            soup = BeautifulSoup(html, "html.parser")
            content_root = pick_content_root(soup)
            markdown_lines = html_to_markdown_lines(content_root)
            links = collect_page_links(
                content_root=content_root,
                page_url=node.url,
                session=session,
                download_dir=os.path.join(output_dir, "downloads", slug),
                download_files=download_files,
            )
        else:
            error = "Unable to fetch page content"
    else:
        error = "Menu item has no URL"

    write_section_markdown(
        file_path=section_md,
        node=node,
        source_url=node.url,
        markdown_lines=markdown_lines,
        links=links,
        output_dir=output_dir,
        error=error,
    )

    children_meta = []
    if depth < max_depth:
        for child in node.children:
            children_meta.append(
                scrape_node(
                    node=child,
                    parent_dir=node_dir,
                    session=session,
                    driver=driver,
                    output_dir=output_dir,
                    max_depth=max_depth,
                    depth=depth + 1,
                    download_files=download_files,
                )
            )

    return {
        "title": node.title,
        "url": node.url,
        "section_md": section_md,
        "children": children_meta,
    }


def write_master_markdown(
    file_path: str,
    start_url: str,
    sidebar_nodes: list[MenuNode],
    results: list[dict],
) -> None:
    lines = [
        "# UNIRG Residencia Multiprofissional - Sidebar Mirror",
        "",
        f"Start page: {start_url}",
        f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Sidebar Tree",
        "",
    ]
    tree_lines = build_tree_lines(sidebar_nodes)
    lines.extend(tree_lines if tree_lines else ["No sidebar items found."])
    lines.extend(["", "## Section Files", ""])

    for item in results:
        rel_path = os.path.relpath(item["section_md"], os.path.dirname(file_path)).replace("\\", "/")
        if item["url"]:
            lines.append(f"- [{item['title']}]({rel_path}) (source: {item['url']})")
        else:
            lines.append(f"- [{item['title']}]({rel_path})")

    with open(file_path, "w", encoding="utf-8") as file_obj:
        file_obj.write("\n".join(lines).strip() + "\n")


def run_sidebar_scrape(
    start_url: str,
    output_dir: str,
    max_depth: int,
    enable_selenium_fallback: bool,
    download_files: bool,
) -> int:
    os.makedirs(output_dir, exist_ok=True)
    reachable = pick_reachable_url(start_url)
    if not reachable:
        logger.error("Host unreachable for both www and non-www variants: %s", start_url)
        return 1

    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)

    driver: Optional[webdriver.Chrome] = None
    if enable_selenium_fallback:
        try:
            driver = build_driver()
        except Exception as err:
            logger.warning("Failed to initialize Selenium driver: %s", err)

    try:
        html = fetch_html(reachable, session, driver)
        if not html:
            logger.error("Could not fetch start page: %s", reachable)
            return 1

        soup = BeautifulSoup(html, "html.parser")
        sidebar_nodes = extract_sidebar_tree(soup, reachable)
        if not sidebar_nodes:
            logger.error("Could not detect sidebar menu on start page.")
            return 1

        logger.info("Detected %d top-level sidebar items.", len(sidebar_nodes))
        sections_root = os.path.join(output_dir, "sections")
        os.makedirs(sections_root, exist_ok=True)

        results: list[dict] = []
        for node in sidebar_nodes:
            results.append(
                scrape_node(
                    node=node,
                    parent_dir=sections_root,
                    session=session,
                    driver=driver,
                    output_dir=output_dir,
                    max_depth=max_depth,
                    depth=1,
                    download_files=download_files,
                )
            )

        master_md = os.path.join(output_dir, "unirg_sidebar_mirror.md")
        write_master_markdown(
            file_path=master_md,
            start_url=reachable,
            sidebar_nodes=sidebar_nodes,
            results=results,
        )
        logger.info("Sidebar mirror generated: %s", master_md)
        return 0
    finally:
        if driver:
            driver.quit()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape UNIRG residency sidebar sections and export structured Markdown."
    )
    parser.add_argument(
        "--start-url",
        default="https://www.unirg.edu.br/residencia-multiprofissional/",
        help="Start page containing the left sidebar.",
    )
    parser.add_argument(
        "--output-dir",
        default="crawler_output/unirg_residencia_multiprofissional/sidebar_mirror",
        help="Output directory for markdown and downloaded files.",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=6,
        help="Maximum sidebar submenu recursion depth.",
    )
    parser.add_argument(
        "--enable-selenium-fallback",
        action="store_true",
        help="Use Selenium fallback when requests cannot fetch HTML.",
    )
    parser.add_argument(
        "--no-download-files",
        action="store_true",
        help="Do not download linked files; only index links in markdown.",
    )

    args = parser.parse_args()
    exit_code = run_sidebar_scrape(
        start_url=args.start_url,
        output_dir=args.output_dir,
        max_depth=max(1, args.max_depth),
        enable_selenium_fallback=args.enable_selenium_fallback,
        download_files=not args.no_download_files,
    )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()