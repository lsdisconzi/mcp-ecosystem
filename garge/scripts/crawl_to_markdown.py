#!/usr/bin/env python3
"""
crawl_to_markdown.py
=====================

Turns a folder of crawled pages (HTML in /pages, plain text in /texts) into
Markdown. Two modes are available:

  raw          Deterministic, no AI. Converts every file to Markdown and
               concatenates them behind a Table of Contents. This is the
               original script's behavior, hardened and cleaned up.

  synthesize   Uses the Claude API to read *all* crawled content for a site
               and rewrite it as a single, deduplicated, well-organized
               Markdown document: sensible heading hierarchy, tables for
               list-like/tabular data, and Mermaid diagrams where a diagram
               genuinely helps (processes, hierarchies, relationships).
               Nothing is invented -- the model is instructed to work only
               from the supplied source text.

  both         Runs raw, then synthesize.

Requirements
------------
    pip install markdownify beautifulsoup4 anthropic

Environment
-----------
    ANTHROPIC_API_KEY   required for --mode synthesize / both
                         (get one at https://console.anthropic.com)

Usage
-----
    python crawl_to_markdown.py --input ./crawler_output/anac --mode both
    python crawl_to_markdown.py --input ./crawler_output/anac --mode raw --keep-images
    python crawl_to_markdown.py --input ./crawler_output/anac --mode synthesize \
        --site-name "ANAC" --source-url "https://example.com" --dry-run

See `--help` for the full list of options.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

try:
    from markdownify import markdownify as md
    MARKDOWNIFY_AVAILABLE = True
except ImportError:
    MARKDOWNIFY_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5"  # good balance of quality/cost for this task;
                                    # use "claude-haiku-4-5-20251001" for a cheaper/faster pass
                                    # on very large sites. See https://docs.claude.com for the
                                    # current model list.

# Roughly the point at which we stop trying to synthesize in one API call and
# switch to a map-reduce (summarize-then-merge) strategy instead. This is a
# character count, not a token count, so it's deliberately conservative.
DEFAULT_SINGLE_PASS_CHAR_BUDGET = 150_000
# How many characters of *summary* each page is allowed to contribute during
# the "map" step of the map-reduce path.
DEFAULT_MAP_STEP_TARGET_CHARS = 1_200


# ----------------------------------------------------------------------------
# Shared helpers
# ----------------------------------------------------------------------------

def sanitize_anchor(text: str, used: Optional[set] = None) -> str:
    """Make a safe, unique Markdown/HTML anchor from arbitrary text."""
    base = os.path.splitext(text)[0] if "." in text else text
    anchor = re.sub(r"[^\w\s-]", "", base).strip().lower()
    anchor = re.sub(r"[\s_]+", "-", anchor).strip("-") or "section"
    if used is None:
        return anchor
    candidate = anchor
    i = 2
    while candidate in used:
        candidate = f"{anchor}-{i}"
        i += 1
    used.add(candidate)
    return candidate


def escape_md_inline(text: str) -> str:
    """Escape characters that would otherwise break inline Markdown (e.g. in a
    TOC link or a table cell). Does NOT touch text meant to render as Markdown
    (like already-converted page bodies) -- only short inline strings such as
    titles."""
    if not text:
        return text
    # Order matters: backslash first so we don't double-escape.
    for ch in ("\\", "|", "[", "]", "*", "_", "`"):
        text = text.replace(ch, "\\" + ch)
    return text.strip()


def collapse_blank_lines(text: str, max_consecutive: int = 2) -> str:
    """Collapse runs of 3+ blank lines down to `max_consecutive`, and strip
    trailing whitespace from every line."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    out = []
    blank_run = 0
    for ln in lines:
        if ln == "":
            blank_run += 1
            if blank_run <= max_consecutive:
                out.append(ln)
        else:
            blank_run = 0
            out.append(ln)
    return "\n".join(out).strip() + "\n"


def read_text_file(filepath: str) -> str:
    """Read a text file, tolerating encoding issues instead of crashing on a
    single bad file mid-run."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        logger.warning("UTF-8 decode failed for %s, retrying with errors='replace'", filepath)
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read()


def extract_title_from_html(html_content: str, fallback_filename: str) -> str:
    """Best-effort human-readable title: <title> -> og:title -> first <h1> -> filename."""
    soup = BeautifulSoup(html_content, "html.parser")
    if soup.title and soup.title.string and soup.title.string.strip():
        return soup.title.string.strip()
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content", "").strip():
        return og["content"].strip()
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    return os.path.splitext(fallback_filename)[0].replace("-", " ").replace("_", " ").strip()


def html_to_clean_markdown(html_content: str, keep_images: bool = False) -> str:
    """Convert HTML to Markdown, stripping chrome (nav/footer/script/style/etc.)
    and preferring the main content region when one can be identified."""
    soup = BeautifulSoup(html_content, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "form", "iframe"]):
        tag.decompose()
    # Common "skip to content" / cookie-banner boilerplate
    for tag in soup.select('[class*="cookie"], [id*="cookie"], [aria-hidden="true"]'):
        tag.decompose()

    main = (
        soup.find("article")
        or soup.find("main")
        or soup.find(attrs={"role": "main"})
        or soup.find("div", class_=re.compile(r"\b(content|main|post|article)\b", re.I))
        or soup.find("div", id=re.compile(r"\b(content|main)\b", re.I))
    )
    target = main if main else soup

    strip_tags = [] if keep_images else ["img"]
    text = md(str(target), heading_style="ATX", strip=strip_tags, bullets="-")
    # markdownify often leaves 3+ blank lines and trailing spaces
    return collapse_blank_lines(text)


def gather_files(base_dir: str, subfolder: str, extension: str):
    """Return a sorted list of (filepath, filename) for files with `extension`
    inside base_dir/subfolder. Sorting is natural (page2 before page10)."""
    folder = os.path.join(base_dir, subfolder)
    if not os.path.isdir(folder):
        return []

    def natural_key(name: str):
        return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]

    files = sorted(
        (f for f in os.listdir(folder) if f.lower().endswith(extension.lower())),
        key=natural_key,
    )
    return [(os.path.join(folder, f), f) for f in files]


# ----------------------------------------------------------------------------
# Mode 1: raw combine (improved version of the original script)
# ----------------------------------------------------------------------------

def build_combined_markdown(file_list, output_path, file_type, source_label, keep_images=False):
    """
    file_list: list of (filepath, filename)
    file_type: 'html' or 'text'
    output_path: where to write the combined .md file
    """
    if not file_list:
        logger.warning("No %s files to process - skipping %s", file_type, output_path)
        return False

    logger.info("Creating %s from %d %s files", output_path, len(file_list), file_type)

    used_anchors: set = set()
    entries = []
    for filepath, filename in file_list:
        try:
            content = read_text_file(filepath)
        except Exception as e:
            logger.warning("Skipping %s (read error): %s", filename, e)
            continue
        title = extract_title_from_html(content, filename) if file_type == "html" else (
            os.path.splitext(filename)[0].replace("-", " ").replace("_", " ").strip()
        )
        anchor = sanitize_anchor(filename, used_anchors)
        entries.append((filepath, filename, title, anchor, content))

    if not entries:
        logger.info("No valid entries for %s", output_path)
        return False

    with open(output_path, "w", encoding="utf-8") as out:
        out.write(f"# Combined {file_type.capitalize()} Content\n\n")
        out.write(f"*Source: {source_label} — {len(entries)} {file_type} file(s)*  \n")
        out.write(f"*Generated: {_dt.datetime.now().isoformat(timespec='seconds')}*\n\n")

        out.write("## Table of Contents\n\n")
        for idx, (_, _, title, anchor, _) in enumerate(entries, 1):
            out.write(f"{idx}. [{escape_md_inline(title)}](#{anchor})\n")
        out.write("\n---\n\n")

        for idx, (filepath, filename, title, anchor, content) in enumerate(entries, 1):
            logger.info("Processing %s", filename)
            out.write(f'<a id="{anchor}"></a>\n\n')
            out.write(f"## {idx}. {title}\n\n")
            out.write(f"*Source file: `{filename}`*\n\n")

            if file_type == "html":
                if not MARKDOWNIFY_AVAILABLE:
                    out.write("```html\n" + content + "\n```\n\n")
                else:
                    try:
                        out.write(html_to_clean_markdown(content, keep_images=keep_images))
                        out.write("\n")
                    except Exception as e:
                        logger.error("Conversion failed for %s: %s", filename, e)
                        out.write("```html\n" + content + "\n```\n")
            else:
                out.write("```text\n" + content.strip() + "\n```\n")

            out.write("\n---\n\n")

    logger.info("Done: %s", output_path)
    print(f"Created: {output_path}")
    return True


def run_raw_mode(input_dir: str, output_dir: str, source_name: str, keep_images: bool, skip_empty: bool = True):
    pages_output_file = os.path.join(output_dir, f"{source_name}_combined_pages.md")
    texts_output_file = os.path.join(output_dir, f"{source_name}_combined_texts.md")

    html_files = gather_files(input_dir, "pages", ".html")
    if html_files or not skip_empty:
        build_combined_markdown(html_files, pages_output_file, "html", input_dir, keep_images=keep_images)
    else:
        logger.info("No HTML pages found - skipping HTML Markdown generation.")

    text_files = gather_files(input_dir, "texts", ".txt")
    if text_files or not skip_empty:
        build_combined_markdown(text_files, texts_output_file, "text", input_dir, keep_images=keep_images)
    else:
        logger.info("No text files found - skipping text Markdown generation.")


# ----------------------------------------------------------------------------
# Mode 2: AI-synthesized single document
# ----------------------------------------------------------------------------

@dataclass
class PageEntry:
    stem: str
    title: str
    content: str
    source_type: str  # "html" or "text"
    filename: str
    chars: int = field(init=False)

    def __post_init__(self):
        self.chars = len(self.content)


def collect_unique_pages(input_dir: str, keep_images: bool = False) -> list[PageEntry]:
    """Gather every crawled page, preferring the HTML-derived Markdown for a
    given page stem over the plain-text version (HTML usually preserves more
    structure), and falling back to text when no HTML counterpart exists.
    This avoids sending the model two near-duplicate copies of the same page.
    """
    by_stem: dict[str, PageEntry] = {}

    for filepath, filename in gather_files(input_dir, "pages", ".html"):
        try:
            html = read_text_file(filepath)
            title = extract_title_from_html(html, filename)
            content = html_to_clean_markdown(html, keep_images=keep_images) if MARKDOWNIFY_AVAILABLE else html
        except Exception as e:
            logger.warning("Skipping %s: %s", filename, e)
            continue
        stem = os.path.splitext(filename)[0]
        if content.strip():
            by_stem[stem] = PageEntry(stem, title, content.strip(), "html", filename)

    for filepath, filename in gather_files(input_dir, "texts", ".txt"):
        stem = os.path.splitext(filename)[0]
        if stem in by_stem:
            continue  # HTML version already covers this page
        try:
            content = read_text_file(filepath).strip()
        except Exception as e:
            logger.warning("Skipping %s: %s", filename, e)
            continue
        if content:
            title = stem.replace("-", " ").replace("_", " ").strip()
            by_stem[stem] = PageEntry(stem, title, content, "text", filename)

    return list(by_stem.values())


SYNTHESIS_SYSTEM_PROMPT = """You are a technical writer. You turn raw, possibly \
messy content crawled from a single website into ONE polished, well-organized \
Markdown reference document for humans to read.

Rules:
- Work ONLY from the supplied source content. Never invent facts, numbers, \
company names, or claims that are not present in the source.
- Merge duplicate or overlapping information from different pages into one \
coherent section instead of repeating it. If two pages genuinely disagree, \
note the discrepancy briefly rather than silently picking one.
- Organize the material by topic/theme, not by "page 1, page 2, ...". Choose \
a heading structure that best serves a reader trying to understand the site's \
subject matter as a whole.
- Use standard Markdown: `#` for the document title, `##`/`###` for sections, \
tables for tabular or list-like data (e.g. comparisons, criteria, catalogs), \
bold/italics sparingly for emphasis.
- Escape any literal Markdown-special characters that appear inside prose \
(e.g. a literal `*`, `_`, `|`, or `[` that isn't meant to trigger formatting).
- Include a short Mermaid diagram ONLY where it genuinely clarifies a process, \
hierarchy, decision flow, or set of relationships described in the source -- \
never as decoration. Use fenced ```mermaid blocks. Prefer `flowchart`, \
`mindmap`, or `graph` syntax. If nothing in the source has that kind of \
structure, include no diagrams at all.
- Start with a one-paragraph overview, then a Table of Contents with anchor \
links, then the sections.
- Preserve concrete details (names, numbers, criteria, links) exactly as given.
- Output ONLY the final Markdown document. No preamble, no commentary, no \
"Here is your document", no markdown code fences wrapping the whole thing.
"""


def build_source_blob(entries: list[PageEntry], max_chars: Optional[int] = None) -> str:
    parts = []
    for e in entries:
        header = f"\n\n===== SOURCE PAGE: {e.title} (file: {e.filename}) =====\n\n"
        parts.append(header + e.content)
    blob = "".join(parts)
    if max_chars and len(blob) > max_chars:
        blob = blob[:max_chars] + "\n\n[... truncated ...]"
    return blob


def call_claude(client, model: str, system: str, user: str, max_tokens: int = 8000) -> str:
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(block.text for block in response.content if getattr(block, "type", None) == "text")


def synthesize_markdown(
    entries: list[PageEntry],
    output_path: str,
    site_name: str,
    source_url: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    api_key: Optional[str] = None,
    single_pass_char_budget: int = DEFAULT_SINGLE_PASS_CHAR_BUDGET,
    map_step_target_chars: int = DEFAULT_MAP_STEP_TARGET_CHARS,
    dry_run: bool = False,
) -> bool:
    if not entries:
        logger.warning("No content to synthesize.")
        return False

    total_chars = sum(e.chars for e in entries)
    logger.info(
        "Synthesizing %d unique page(s), %d total characters (%s)",
        len(entries), total_chars,
        "single-pass" if total_chars <= single_pass_char_budget else "map-reduce",
    )

    context_line = f"Website: {site_name}" + (f" ({source_url})" if source_url else "")

    if total_chars <= single_pass_char_budget:
        user_prompt = (
            f"{context_line}\n\n"
            f"Below is the raw content of every crawled page from this site, "
            f"{len(entries)} page(s) total. Produce the single synthesized "
            f"Markdown document described in your instructions.\n"
            f"{build_source_blob(entries)}"
        )
        prompt_for_dry_run = user_prompt
    else:
        # Map step: compress each page to a short, faithful summary first, so
        # the final "reduce" call fits comfortably in one request even for
        # large sites.
        logger.info("Content exceeds single-pass budget - running map step (per-page summaries)...")
        prompt_for_dry_run = None  # built incrementally below

    if dry_run:
        print("\n--- DRY RUN: no API calls made ---")
        print(f"Mode: {'single-pass' if total_chars <= single_pass_char_budget else 'map-reduce'}")
        print(f"Pages: {len(entries)}  Total source characters: {total_chars}")
        if prompt_for_dry_run:
            print(f"Single-pass user prompt length: {len(prompt_for_dry_run)} chars")
        return True

    try:
        import anthropic
    except ImportError:
        logger.error("The 'anthropic' package is required for --mode synthesize. Install it with:\n"
                      "    pip install anthropic")
        return False

    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        logger.error("No API key found. Set ANTHROPIC_API_KEY or pass --api-key.")
        return False

    client = anthropic.Anthropic(api_key=key)

    if total_chars <= single_pass_char_budget:
        try:
            final_md = call_claude(client, model, SYNTHESIS_SYSTEM_PROMPT, user_prompt, max_tokens=8000)
        except Exception as e:
            logger.error("Synthesis call failed: %s", e)
            return False
    else:
        summaries = []
        map_system = (
            "Summarize the following single web page's content into faithful, "
            "dense bullet points capturing every distinct fact, number, and "
            "claim. No commentary, no invented content, no headings -- bullets only."
        )
        for e in entries:
            try:
                summary = call_claude(
                    client, model, map_system,
                    f"Page title: {e.title}\n\n{e.content}",
                    max_tokens=max(300, map_step_target_chars // 3),
                )
            except Exception as ex:
                logger.warning("Map step failed for %s, using truncated raw content instead: %s", e.title, ex)
                summary = e.content[:map_step_target_chars]
            summaries.append(f"\n\n===== SOURCE PAGE: {e.title} (file: {e.filename}) =====\n\n{summary}")

        reduce_user_prompt = (
            f"{context_line}\n\n"
            f"Below are dense per-page summaries of every crawled page from this "
            f"site ({len(entries)} pages). Produce the single synthesized Markdown "
            f"document described in your instructions, written as if from the "
            f"original material.\n" + "".join(summaries)
        )
        try:
            final_md = call_claude(client, model, SYNTHESIS_SYSTEM_PROMPT, reduce_user_prompt, max_tokens=8000)
        except Exception as e:
            logger.error("Reduce/synthesis call failed: %s", e)
            return False

    final_md = collapse_blank_lines(final_md)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_md)

    logger.info("Done: %s", output_path)
    print(f"Created: {output_path}")
    return True


def run_synthesize_mode(args, input_dir: str, output_dir: str, source_name: str):
    entries = collect_unique_pages(input_dir, keep_images=args.keep_images)
    output_path = os.path.join(output_dir, f"{source_name}_synthesized.md")
    synthesize_markdown(
        entries,
        output_path,
        site_name=args.site_name or source_name,
        source_url=args.source_url,
        model=args.model,
        api_key=args.api_key,
        single_pass_char_budget=args.single_pass_char_budget,
        dry_run=args.dry_run,
    )


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Combine crawled HTML/text pages into Markdown (raw concatenation and/or AI-synthesized).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--input", "-i", dest="input_dir", required=True,
                   help="Crawl output directory containing /pages and/or /texts subfolders.")
    p.add_argument("--output-dir", "-o", default=None,
                   help="Where to write output files (default: same as --input).")
    p.add_argument("--mode", choices=["raw", "synthesize", "both"], default="raw",
                   help="raw = deterministic concatenation; synthesize = AI-rewritten single doc; both = run both.")
    p.add_argument("--source-name", default=None,
                   help="Short name used as a filename prefix (default: input folder name).")
    p.add_argument("--site-name", default=None,
                   help="Human-readable site name for the synthesized doc's title/context (default: --source-name).")
    p.add_argument("--source-url", default=None, help="Original site URL, included as context for synthesis.")
    p.add_argument("--keep-images", action="store_true",
                   help="Keep image references (as Markdown image syntax) instead of stripping them.")
    p.add_argument("--include-empty", action="store_true",
                   help="Still write output files even if a subfolder has no matching files.")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Claude model ID to use for synthesis.")
    p.add_argument("--api-key", default=None, help="Anthropic API key (default: ANTHROPIC_API_KEY env var).")
    p.add_argument("--single-pass-char-budget", type=int, default=DEFAULT_SINGLE_PASS_CHAR_BUDGET,
                   help="Above this many total source characters, switch to map-reduce summarization.")
    p.add_argument("--dry-run", action="store_true",
                   help="For --mode synthesize: build prompts and report their size without calling the API.")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    input_dir = os.path.normpath(args.input_dir)
    if not os.path.isdir(input_dir):
        logger.error("Input directory does not exist: %s", input_dir)
        sys.exit(1)

    output_dir = os.path.normpath(args.output_dir) if args.output_dir else input_dir
    os.makedirs(output_dir, exist_ok=True)

    source_name = args.source_name or os.path.basename(input_dir.rstrip(os.sep)) or "site"

    if args.mode in ("raw", "both"):
        if not MARKDOWNIFY_AVAILABLE or not BS4_AVAILABLE:
            logger.warning("markdownify/beautifulsoup4 not installed - HTML pages will be embedded as raw HTML blocks.")
        run_raw_mode(input_dir, output_dir, source_name, keep_images=args.keep_images,
                     skip_empty=not args.include_empty)

    if args.mode in ("synthesize", "both"):
        run_synthesize_mode(args, input_dir, output_dir, source_name)


if __name__ == "__main__":
    main()
