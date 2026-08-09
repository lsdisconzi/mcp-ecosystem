import os
import re
import logging

# Required for HTML → Markdown conversion
try:
    from markdownify import markdownify as md
    MARKDOWNIFY_AVAILABLE = True
except ImportError:
    MARKDOWNIFY_AVAILABLE = False
from bs4 import BeautifulSoup

# ===================== CONFIGURATION =====================
# The directory that contains /pages and /texts subdirectories
CRAWL_OUTPUT_DIR = './crawler_output/shawfield-timber'

# Output filenames (will be saved inside CRAWL_OUTPUT_DIR)
PAGES_OUTPUT = 'combined_pages.md'      # from HTML
TEXTS_OUTPUT = 'combined_texts.md'      # from plain text

# If True, skip creating a file when no source files are found
SKIP_EMPTY = True
# =========================================================

# Extract the source folder name to use in output filenames and headers
SOURCE_FOLDER_NAME = os.path.basename(os.path.normpath(CRAWL_OUTPUT_DIR))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ----------------------- Helpers -----------------------
def sanitize_anchor(filename):
    """Make a safe HTML anchor from a filename."""
    base = os.path.splitext(filename)[0]
    anchor = re.sub(r'[^\w\s-]', '', base).strip().lower()
    anchor = re.sub(r'[\s]+', '-', anchor)
    return anchor


def extract_title_from_html(html_content, fallback_filename):
    """Extract a human-readable title from HTML."""
    soup = BeautifulSoup(html_content, 'html.parser')
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find('h1')
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    return os.path.splitext(fallback_filename)[0]


def html_to_clean_markdown(html_content):
    """Convert HTML to Markdown, removing non-content tags."""
    soup = BeautifulSoup(html_content, 'html.parser')
    # Remove navigation, scripts, styles
    for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
        tag.decompose()

    # Try to focus on main content
    main = soup.find('article') or soup.find('main') or soup.find('div', class_='content')
    target = main if main else soup

    return md(str(target), heading_style="ATX", strip=['img']).strip()


def gather_files(base_dir, subfolder, extension):
    """Return sorted list of (filepath, filename) from a subfolder with the given extension."""
    folder = os.path.join(base_dir, subfolder)
    if not os.path.isdir(folder):
        return []
    files = [f for f in os.listdir(folder) if f.endswith(extension)]
    files = sorted(files)
    return [(os.path.join(folder, f), f) for f in files]


def build_combined_markdown(file_list, output_path, file_type):
    """
    file_list: list of (filepath, filename)
    file_type: 'html' or 'text'
    output_path: where to write the .md file
    """
    if not file_list:
        logger.warning("No %s files to process – skipping %s", file_type, output_path)
        return

    logger.info("Creating %s from %d %s files", output_path, len(file_list), file_type)

    # First pass: extract titles/anchors
    entries = []
    for filepath, filename in file_list:
        anchor = sanitize_anchor(filename)
        title = filename
        try:
            if file_type == 'html':
                with open(filepath, 'r', encoding='utf-8') as f:
                    html = f.read()
                title = extract_title_from_html(html, filename)
            else:  # text
                title = os.path.splitext(filename)[0]
        except Exception as e:
            logger.warning("Skipping %s: %s", filename, e)
            continue
        entries.append((filepath, filename, title, anchor))

    if not entries:
        logger.info("No valid entries for %s", output_path)
        return

    # Write combined Markdown
    with open(output_path, 'w', encoding='utf-8') as out:
        out.write(f"# Combined {file_type.capitalize()} Content\n\n")
        out.write(f"*Generated from {len(entries)} {file_type} files*\n\n")
        # Mention the source folder so the reader knows where this came from
        out.write(f"*Source folder: `{CRAWL_OUTPUT_DIR}`*\n\n")

        # Table of Contents
        out.write("## Table of Contents\n\n")
        for idx, (_, _, title, anchor) in enumerate(entries, 1):
            out.write(f"{idx}. [{title}](#{anchor})\n")
        out.write("\n---\n\n")

        # Add each page
        for idx, (filepath, filename, title, anchor) in enumerate(entries, 1):
            logger.info("Processing %s", filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception as e:
                logger.error("Cannot read %s: %s", filename, e)
                continue

            out.write(f'<a id="{anchor}"></a>\n\n')
            out.write(f"## {idx}. {title}\n\n")
            out.write(f"*Source file: {filename}*\n\n")

            # Convert/embed content
            if file_type == 'html':
                if not MARKDOWNIFY_AVAILABLE:
                    out.write("```html\n")
                    out.write(content)
                    out.write("\n```\n\n")
                else:
                    try:
                        md_text = html_to_clean_markdown(content)
                        out.write(md_text)
                    except Exception as e:
                        logger.error("Conversion failed for %s: %s", filename, e)
                        out.write("```html\n")
                        out.write(content)
                        out.write("\n```\n")
            else:  # text
                # Wrap plain text in a fenced code block to preserve layout
                out.write("```text\n")
                out.write(content)
                out.write("\n```\n")

            out.write("\n---\n\n")

    logger.info("Done: %s", output_path)
    print(f"✅ Created: {output_path}")


def main():
    # Build output filenames that include the source folder name
    pages_output_file = os.path.join(CRAWL_OUTPUT_DIR, f"{SOURCE_FOLDER_NAME}_{PAGES_OUTPUT}")
    texts_output_file = os.path.join(CRAWL_OUTPUT_DIR, f"{SOURCE_FOLDER_NAME}_{TEXTS_OUTPUT}")

    # Process HTML pages
    html_files = gather_files(CRAWL_OUTPUT_DIR, 'pages', '.html')
    if html_files or not SKIP_EMPTY:
        build_combined_markdown(html_files, pages_output_file, 'html')
    else:
        logger.info("No HTML pages found – skipping HTML Markdown generation.")

    # Process plain text files
    text_files = gather_files(CRAWL_OUTPUT_DIR, 'texts', '.txt')
    if text_files or not SKIP_EMPTY:
        build_combined_markdown(text_files, texts_output_file, 'text')
    else:
        logger.info("No text files found – skipping text Markdown generation.")


if __name__ == '__main__':
    main()