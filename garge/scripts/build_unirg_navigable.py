#!/usr/bin/env python3
"""Build a single navigable Markdown from the UNIRG sidebar mirror.

Consolidates all per-section ``index.md`` files into one document with a
table of contents, anchor links for navigation, and rewrites archive URLs
to the locally downloaded files whenever a matching file exists on disk.
"""

from __future__ import annotations

import argparse
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse


LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def safe_filename(url: str) -> str:
    parsed = urlparse(url)
    name = os.path.basename(parsed.path) or "download.bin"
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    if len(name) > 180:
        base, ext = os.path.splitext(name)
        name = base[:160] + ext
    return name


def slugify(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    norm = norm.lower()
    norm = re.sub(r"[^a-z0-9]+", "-", norm).strip("-")
    return norm or "section"


@dataclass
class Section:
    title: str
    path: Path
    source_url: str | None
    content_lines: list[str]
    links: list[tuple[str, str]]  # (text, url)
    children: list["Section"] = field(default_factory=list)
    anchor: str = ""


def parse_section(index_md: Path) -> Section:
    text = index_md.read_text(encoding="utf-8")
    lines = text.splitlines()

    title = lines[0].lstrip("# ").strip() if lines else index_md.parent.name
    source_url: str | None = None
    for line in lines[:10]:
        if line.startswith("Source URL:"):
            source_url = line.split("Source URL:", 1)[1].strip()
            break

    # Split into Content / Links blocks
    content_lines: list[str] = []
    links: list[tuple[str, str]] = []
    mode = None
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "## Content":
            mode = "content"
            continue
        if stripped == "## Links":
            mode = "links"
            continue
        if mode == "content":
            content_lines.append(line)
        elif mode == "links":
            if stripped.startswith("- "):
                match = LINK_RE.search(stripped)
                if match:
                    links.append((match.group(1).strip(), match.group(2).strip()))

    # Clean noisy residual UI text and duplicate subtitle lines
    cleaned: list[str] = []
    for raw in content_lines:
        stripped = raw.strip()
        if stripped.startswith("#### "):
            # Drop the duplicated section heading captured from the panel
            continue
        cleaned_line = re.sub(r"^##\s*add\s*remove\s*", "### ", raw)
        cleaned_line = re.sub(r"\badd\s+remove\b", "", cleaned_line)
        cleaned.append(cleaned_line.rstrip())
    content_lines = cleaned
    # Trim leading/trailing blank lines in content
    while content_lines and not content_lines[0].strip():
        content_lines.pop(0)
    while content_lines and not content_lines[-1].strip():
        content_lines.pop()

    return Section(
        title=title,
        path=index_md,
        source_url=source_url,
        content_lines=content_lines,
        links=links,
    )


def load_sections(sections_root: Path) -> list[Section]:
    top: list[Section] = []
    for child in sorted(sections_root.iterdir()):
        if not child.is_dir():
            continue
        index_md = child / "index.md"
        if not index_md.exists():
            continue
        section = parse_section(index_md)
        for grand in sorted(child.iterdir()):
            if grand.is_dir() and (grand / "index.md").exists():
                section.children.append(parse_section(grand / "index.md"))
        top.append(section)
    # Assign anchors, unique
    used: set[str] = set()
    def assign(sec: Section, prefix: str = "") -> None:
        base = slugify((prefix + "-" + sec.title) if prefix else sec.title)
        anchor = base
        counter = 2
        while anchor in used:
            anchor = f"{base}-{counter}"
            counter += 1
        used.add(anchor)
        sec.anchor = anchor
        for ch in sec.children:
            assign(ch, sec.title)
    for sec in top:
        assign(sec)
    return top


def index_downloads(downloads_root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    if not downloads_root.exists():
        return index
    for file in downloads_root.rglob("*"):
        if file.is_file():
            index.setdefault(file.name, []).append(file)
    return index


def resolve_local(url: str, downloads_index: dict[str, list[Path]]) -> Path | None:
    fname = safe_filename(url)
    candidates = downloads_index.get(fname)
    if not candidates:
        # Try without query/fragment
        parsed = urlparse(url)
        name = os.path.basename(unquote(parsed.path))
        fname2 = re.sub(r"[^A-Za-z0-9._-]", "_", name)
        candidates = downloads_index.get(fname2)
    if not candidates:
        return None
    return candidates[0]


def rel(target: Path, base: Path) -> str:
    return os.path.relpath(target, base).replace("\\", "/")


def render_links(
    links: list[tuple[str, str]],
    downloads_index: dict[str, list[Path]],
    base_dir: Path,
) -> list[str]:
    out: list[str] = []
    for text, url in links:
        local = resolve_local(url, downloads_index)
        if local is not None:
            rel_path = rel(local, base_dir)
            out.append(f"- [{text}]({rel_path}) — [original]({url})")
        else:
            out.append(f"- [{text}]({url})")
    return out


def build_document(
    sections: list[Section],
    downloads_index: dict[str, list[Path]],
    base_dir: Path,
    source_page: str,
) -> str:
    lines: list[str] = []
    lines.append("# UNIRG — Residência Multiprofissional (Mirror Local Navegável)")
    lines.append("")
    lines.append(
        "Documento consolidado para navegação local de todo o conteúdo da página "
        f"**Residência Multiprofissional** da UNIRG. Fonte: [{source_page}]({source_page})."
    )
    lines.append("")
    lines.append(
        "Os links apontam primeiro para o **arquivo local já baixado** (quando "
        "disponível) e, ao lado, mantêm o link **original** do Web Archive."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append('## <a id="indice"></a>Índice')
    lines.append("")
    for sec in sections:
        lines.append(f"- [{sec.title}](#{sec.anchor})")
        for ch in sec.children:
            lines.append(f"  - [{ch.title}](#{ch.anchor})")
    lines.append("")
    lines.append("---")
    lines.append("")

    def emit_section(sec: Section, level: int) -> None:
        hashes = "#" * level
        lines.append(f'{hashes} <a id="{sec.anchor}"></a>{sec.title}')
        lines.append("")
        if sec.source_url:
            lines.append(f"_Fonte: [{sec.source_url}]({sec.source_url})_")
            lines.append("")
        if sec.content_lines:
            lines.append("**Conteúdo**")
            lines.append("")
            lines.extend(sec.content_lines)
            lines.append("")
        if sec.links:
            lines.append("**Arquivos e links**")
            lines.append("")
            lines.extend(render_links(sec.links, downloads_index, base_dir))
            lines.append("")
        lines.append("[⬆ voltar ao índice](#indice)")
        lines.append("")
        for ch in sec.children:
            emit_section(ch, level + 1)

    for sec in sections:
        emit_section(sec, 2)

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mirror-dir",
        default=(
            "crawler_output/unirg_residencia_multiprofissional/"
            "sidebar_mirror_wayback_final"
        ),
        help="Root of the sidebar mirror (contains sections/ and downloads/).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output markdown path. Defaults to <mirror-dir>/unirg_navigable.md.",
    )
    parser.add_argument(
        "--source-page",
        default=(
            "https://web.archive.org/web/20260120125055/"
            "https://www.unirg.edu.br/residencia-multiprofissional"
        ),
        help="Label used as the source page reference in the document header.",
    )
    args = parser.parse_args()

    mirror_dir = Path(args.mirror_dir).resolve()
    sections_root = mirror_dir / "sections"
    downloads_root = mirror_dir / "downloads"
    if not sections_root.exists():
        raise SystemExit(f"Sections directory not found: {sections_root}")

    output_path = Path(args.output) if args.output else mirror_dir / "unirg_navigable.md"

    sections = load_sections(sections_root)
    downloads_index = index_downloads(downloads_root)
    doc = build_document(
        sections=sections,
        downloads_index=downloads_index,
        base_dir=mirror_dir,
        source_page=args.source_page,
    )
    output_path.write_text(doc, encoding="utf-8")

    total_links = sum(
        len(s.links) + sum(len(c.links) for c in s.children) for s in sections
    )
    resolved = 0
    for s in sections:
        for text, url in s.links:
            if resolve_local(url, downloads_index):
                resolved += 1
        for c in s.children:
            for text, url in c.links:
                if resolve_local(url, downloads_index):
                    resolved += 1
    print(
        f"Generated {output_path} — {len(sections)} sections, "
        f"{sum(len(s.children) for s in sections)} subsections, "
        f"{resolved}/{total_links} links resolved to local files."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
