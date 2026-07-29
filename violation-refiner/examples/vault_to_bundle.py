#!/usr/bin/env python3
"""Convert Obsidian vault violation markdown to legacy bundle format.

Reads .md files from the vault (with YAML frontmatter and structured body
sections) and writes per-violation directories containing contract.json and
segments_manifest.json — the format expected by stage_cl_batch.py.

Usage:
    python3 examples/vault_to_bundle.py \\
        /path/to/vault/01-violations/CL/CL-009.md \\
        --output build/vault_bundles

    python3 examples/vault_to_bundle.py CL-009 \\
        --source /path/to/vault/01-violations \\
        --output build/vault_bundles

    # Batch convert all CL violations:
    python3 examples/vault_to_bundle.py --all --jurisdiction CL \\
        --source /path/to/vault/01-violations \\
        --output build/vault_bundles
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import yaml


def _to_json_safe(obj: Any) -> Any:
    """Recursively convert YAML-parsed objects to JSON-serializable types."""
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    if isinstance(obj, datetime.date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_json_safe(v) for v in obj]
    return obj

# ── CLI ─────────────────────────────────────────────────────────────────────

def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Convert vault .md to legacy bundle")
    p.add_argument(
        "violation",
        nargs="?",
        help="Violation ID (e.g. CL-009) or path to a single .md file.",
    )
    p.add_argument(
        "--source",
        type=Path,
        help="Root of vault violations directory (e.g. .../01-violations). "
             "Required when violation is an ID rather than a direct path.",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Convert all .md files in --source/<jurisdiction>/ instead of a single one.",
    )
    p.add_argument(
        "--jurisdiction",
        default="CL",
        choices=["CL", "BR", "INT"],
        help="Jurisdiction subdirectory (default: CL).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path("build/vault_bundles"),
        help="Output root directory (default: build/vault_bundles).",
    )
    return p.parse_args(argv)


# ── YAML frontmatter ────────────────────────────────────────────────────────

def _normalize_yaml(yaml_text: str) -> str:
    """Fix Obsidian-specific YAML quirks before parsing.

    Obsidian allows ``key:[]`` and ``key:{}`` without a space after the colon,
    which is invalid YAML. Also, ``[[wikilink]]`` values get interpreted as
    nested YAML flow sequences; wrap them in quotes to preserve as strings.
    """
    # key:[] -> key: []    (no-space empty collections)
    yaml_text = re.sub(r"^(\s*[\w-]+):\[", r"\1: [", yaml_text, flags=re.MULTILINE)
    # key:{} -> key: {}
    yaml_text = re.sub(r"^(\s*[\w-]+):\{", r"\1: {", yaml_text, flags=re.MULTILINE)
    # [[wikilink]] -> "[[wikilink]]"   (only when NOT already quoted)
    yaml_text = re.sub(r'(?<!")(\[\[[^\]]+\]\])(?!")', r'"\1"', yaml_text)
    return yaml_text


def parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter from a markdown file."""
    # Frontmatter is delimited by --- on its own line(s)
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    normalized = _normalize_yaml(parts[1])
    return _to_json_safe(yaml.safe_load(normalized) or {})


# ── Body section parsing ────────────────────────────────────────────────────

def parse_body_sections(text: str) -> dict[str, str]:
    """Split the markdown body into H2 sections.

    Returns a dict mapping section name (lowercase) to its raw content.
    """
    body = text.split("---", 2)[-1] if text.startswith("---") else text
    sections: dict[str, str] = {}
    current_name: str | None = None
    current_lines: list[str] = []

    for line in body.split("\n"):
        if line.startswith("## ") and not line.startswith("### "):
            if current_name is not None and current_lines:
                sections[current_name] = "\n".join(current_lines)
            current_name = line[3:].strip().lower()
            current_lines = []
        elif current_name is not None:
            current_lines.append(line)

    if current_name is not None and current_lines:
        sections[current_name] = "\n".join(current_lines)

    return sections


def parse_legal_reasoning(text: str) -> dict[str, str]:
    """Parse bold-headered subsections from the Legal Reasoning section."""
    result: dict[str, str] = {}
    # Map bold header text to key names
    header_map = {
        "applicable framework": "applicable_framework",
        "factual subsumption": "factual_subsumption",
        "nexus fact norm": "nexus_fact_norm",
        "evidentiary strength": "evidentiary_strength",
        "severity assessment": "severity_assessment",
        "procedural integrity": "procedural_integrity",
    }
    # Split on **Header**: patterns
    parts = re.split(r"\*\*([^*]+)\*\*:\s*", text)
    # parts[0] is text before first header
    # parts[1], parts[2] = header1, content1
    # parts[3], parts[4] = header2, content2, etc.
    for i in range(1, len(parts) - 1, 2):
        header = parts[i].strip().lower()
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        key = header_map.get(header, header.replace(" ", "_"))
        result[key] = content
    return result


def parse_key_actions(text: str) -> list[dict[str, str]]:
    """Parse Key Actions section into action dicts.

    Each action is: **[Label]** + description + > quote, separated by ---.
    """
    actions: list[dict[str, str]] = []
    # Split on --- separators (must be on its own line)
    blocks = re.split(r"\n---\n", text)
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        action: dict[str, str] = {"action": "", "evidence_quote": ""}
        # Extract bold label: **[Label]**
        label_m = re.search(r"\*\*\[([^\]]*)\]\*\*", block)
        if label_m:
            action["action"] = label_m.group(1).strip()
            # Remove the label from block for description extraction
            desc_part = block[label_m.end():].strip()
        else:
            desc_part = block

        # Extract blockquote: lines starting with >
        quote_lines: list[str] = []
        desc_lines: list[str] = []
        for line in desc_part.split("\n"):
            if line.strip().startswith(">"):
                quote_lines.append(line.strip()[1:].strip())
            else:
                desc_lines.append(line)

        action["evidence_quote"] = " ".join(quote_lines)
        # If no explicit label but we have description text, use first line
        if not action["action"] and desc_lines:
            action["action"] = " ".join(desc_lines).strip()[:200]

        actions.append(action)
    return actions


def parse_legal_basis_table(text: str) -> list[dict[str, str]]:
    """Parse Legal Basis markdown table: | Article ID | Article | Nexus |.

    Returns list of {article_id, article_name, nexus} dicts.
    """
    articles: list[dict[str, str]] = []
    in_table = False
    for line in text.split("\n"):
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        # Skip header row
        if cells and cells[0].lower() in ("article id", "article_id", "article"):
            in_table = True
            continue
        # Skip separator row like |---|
        if all(re.match(r"^-+$", c) for c in cells):
            continue
        if in_table and len(cells) >= 3:
            # Clean backtick formatting from article_id
            aid = cells[0].strip("`").strip()
            articles.append({
                "article_id": aid,
                "article_name": cells[1].strip(),
                "nexus": cells[2].strip() if len(cells) > 2 else "",
            })
    return articles


# ── Remove wikilink markup ──────────────────────────────────────────────────

def clean_wikilink(value: str) -> str:
    """Strip [[ ]] from wikilinks."""
    if value.startswith("[[") and value.endswith("]]"):
        return value[2:-2]
    return value


def clean_wikilinks(values: list) -> list[str]:
    """Clean a list that may contain wikilinks."""
    return [clean_wikilink(str(v)) for v in values]


# ── Build contract.json ─────────────────────────────────────────────────────

def build_contract(fm: dict, body: dict[str, str]) -> dict:
    """Build contract.json from frontmatter and body sections."""
    vid = fm.get("violation_id", "UNKNOWN")
    jurisdiction = fm.get("jurisdiction", "CL")

    # ── Case ──
    incident_name = clean_wikilink(str(fm.get("incident", "")))
    case = {
        "id": fm.get("incident_id", ""),
        "name": incident_name,
    }

    # ── Framework ──
    framework = {
        "id": fm.get("framework_id", ""),
        "name": fm.get("framework_name", ""),
        "jurisdiction": jurisdiction,
    }

    # ── Incident detail ──
    ts_display = fm.get("incident_timestamp_display", "")
    incident = {
        "date": ts_display.split("—")[0].strip() if "—" in ts_display else ts_display,
        "location": "Santiago Airport (SCL), Chile",
        "flight": "LA8159",
        "operator": "LATAM Airlines",
        "clock_time_estimate": fm.get("incident_timestamp", ""),
    }

    # ── Legal basis ──
    # Merge frontmatter legal_basis list with table-derived nexus text
    fm_articles = fm.get("legal_basis") or []
    table_articles = parse_legal_basis_table(
        body.get("legal basis", "")
    )
    # Index table articles by article_id
    table_by_id: dict[str, dict] = {}
    for ta in table_articles:
        table_by_id[ta["article_id"]] = ta

    legal_basis: list[dict] = []
    for fa in fm_articles:
        aid = fa.get("article_id", "")
        article = {
            "article_id": aid,
            "article_name": fa.get("article_name", aid),
            "excerpt": "",
            "nexus": table_by_id.get(aid, {}).get("nexus", ""),
            "duty_bearer": "state",
            "norm_type": "definition",
            "applicability": "primary",
            "subsections_invoked": [],
        }
        legal_basis.append(article)

    # ── Legal reasoning ──
    legal_reasoning_text = body.get("legal reasoning", "")
    legal_reasoning = parse_legal_reasoning(legal_reasoning_text)
    if "related_allegations" not in legal_reasoning:
        related = fm.get("related_violations") or []
        if related:
            legal_reasoning["related_allegations"] = (
                "Connected to " + ", ".join(clean_wikilinks(related))
            )

    # ── Actions ──
    actions_text = body.get("key actions", "")
    actions = parse_key_actions(actions_text)

    # ── Evidence chain ──
    evidence_links = fm.get("evidence_links") or []
    evidence_chain: list[dict] = []
    for i, link in enumerate(evidence_links, start=1):
        name = clean_wikilink(str(link))
        evidence_chain.append({
            "id": f"EVID_{name[:20].upper()}",
            "type": "transcript",
            "source": name,
            "chain": f"EVID_{name[:20].upper()} -> TRNS_{name[:20].upper()}",
        })

    # ── Actors ──
    actors = [
        {"role_id": "ROLE_supervisor", "function": "LATAM Supervisor"},
        {"role_id": "ROLE_passenger", "function": "Leandro Disconzi"},
    ]

    # ── Related violations ──
    related_violations = clean_wikilinks(fm.get("related_violations") or [])

    # ── Assemble ──
    return {
        "schema_version": "1.0",
        "violation_id": vid,
        "violation_number": vid,
        "title": fm.get("title", vid),
        "case": case,
        "framework": framework,
        "category": fm.get("category", ""),
        "severity": fm.get("severity", "MEDIUM"),
        "confidence": fm.get("confidence", 0.5),
        "incident_timestamp": fm.get("incident_timestamp", ""),
        "incident_timestamp_display": ts_display,
        "allegation_summary": fm.get("allegation_summary", ""),
        "legal_basis": legal_basis,
        "legal_reasoning": legal_reasoning,
        "actions": actions,
        "evidence_chain": evidence_chain,
        "actors": actors,
        "related_violations": related_violations,
        "_provenance": {
            "source_vault": fm.get("_provenance", {}).get("source_vault", ""),
            "source_path": fm.get("_provenance", {}).get("source_path", ""),
            "converted_at": "",
        },
    }


# ── Build segments_manifest.json ────────────────────────────────────────────

def build_segments_manifest(fm: dict) -> dict:
    """Build a minimal segments_manifest.json from frontmatter.

    The vault .md files don't contain segment-level data, so we create a
    minimal manifest. The refinement step will populate actual segments.
    """
    transcripts = fm.get("transcripts") or []
    audio_sources: list[str] = []
    audio_sources_detail: dict[str, dict] = {}

    for t in transcripts:
        name = clean_wikilink(str(t))
        # TRNS-aeropuerto_arturo_merino_benitez_7 -> STG-7
        # TRNS-latam_stg_2 -> LATAM-2
        source_id = _infer_source_id(name)
        audio_sources.append(source_id)
        audio_sources_detail[source_id] = {
            "file": "",
            "raw_json": "",
            "recording_time": "",
            "description": name,
        }

    return {
        "violation_id": fm.get("violation_id", ""),
        "matched_audio_sources": audio_sources,
        "total_segments_matched": 0,
        "segments": [],
        "audio_sources_detail": audio_sources_detail,
        "generated_at": "",
        "schema_version": "2.3",
    }


def _infer_source_id(trns_name: str) -> str:
    """Infer a source ID like STG-7 from a TRNS name."""
    # TRNS-aeropuerto_arturo_merino_benitez_7 -> STG-7
    # TRNS-latam_stg_2 -> LATAM-2
    name = trns_name.replace("TRNS-", "")
    # Extract trailing number
    m = re.search(r"(\d+)$", name)
    if m:
        num = m.group(1)
        prefix = name[:m.start()].strip("_").replace("_", "-").upper()
        # Shorten known prefixes
        if "AEROPUERTO" in prefix:
            return f"STG-{num}"
        if "LATAM" in prefix:
            return f"LATAM-{num}"
        return f"{prefix}-{num}"
    return name


# ── Conversion ──────────────────────────────────────────────────────────────

def convert_one(md_path: Path, output_root: Path) -> Path:
    """Convert a single vault .md file to a bundle directory.

    Returns the path to the bundle directory.
    """
    text = md_path.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    body = parse_body_sections(text)

    vid = fm.get("violation_id") or md_path.stem
    bundle_dir = output_root / vid
    bundle_dir.mkdir(parents=True, exist_ok=True)

    contract = build_contract(fm, body)
    (bundle_dir / "contract.json").write_text(
        json.dumps(contract, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    manifest = build_segments_manifest(fm)
    (bundle_dir / "segments_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return bundle_dir


def find_md_path(violation_id: str, source_root: Path) -> Path | None:
    """Find a vault .md file by violation ID.

    Looks in source_root/<jurisdiction>/<violation_id>.md.
    """
    jurisdiction = violation_id.split("-")[0]
    # Also try INT for IN jurisdiction
    candidates = [jurisdiction]
    if jurisdiction == "IN":
        candidates.append("INT")
    elif jurisdiction == "INT":
        candidates.append("IN")

    for jur in candidates:
        path = source_root / jur / f"{violation_id}.md"
        if path.exists():
            return path
    return None


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)

    if args.all:
        if not args.source:
            print("--source is required with --all", file=sys.stderr)
            return 1
        jur_dir = args.source / args.jurisdiction
        if not jur_dir.is_dir():
            print(f"Jurisdiction directory not found: {jur_dir}", file=sys.stderr)
            return 1
        md_files = sorted(jur_dir.glob("*.md"))
        for md_path in md_files:
            bundle_dir = convert_one(md_path, args.output)
            print(f"  {md_path.stem} -> {bundle_dir}")
        print(f"\nConverted {len(md_files)} violations to {args.output}")
        return 0

    if not args.violation:
        print("Specify a violation ID or markdown file path.", file=sys.stderr)
        return 1

    # Determine the input path
    if args.violation.endswith(".md"):
        md_path = Path(args.violation)
        if not md_path.exists():
            print(f"File not found: {md_path}", file=sys.stderr)
            return 1
    else:
        if not args.source:
            # Try default vault path
            args.source = Path(
                "/Users/leandrodisconzi/obsidian/vault-22th-may/01-violations"
            )
        md_path = find_md_path(args.violation, args.source)
        if md_path is None:
            print(
                f"Violation {args.violation} not found in {args.source}",
                file=sys.stderr,
            )
            return 1

    bundle_dir = convert_one(md_path, args.output)
    print(json.dumps({
        "violation_id": md_path.stem,
        "ok": True,
        "bundle": str(bundle_dir),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
