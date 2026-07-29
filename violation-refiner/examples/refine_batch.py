"""Batch refiner CLI for CL violation folders.

Loads each violation bundle (legacy or canonical schema), anchors segments
against the real transcript HTML, verifies article excerpts against the real
framework cache, re-derives confidence, runs V01-V10 validation, and writes
normalized outputs in place.

Usage:
    python3 examples/refine_batch.py --input /path/to/CL
    python3 examples/refine_batch.py --input /path/to/CL --only CL-005
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from violation_pack.config import Settings
from violation_pack.refine_batch_core import run


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Batch-refine CL violation folders")
    p.add_argument("--input", required=True, type=Path, help="Path containing CL-* folders")
    p.add_argument(
        "--include-extra", action="store_true",
        help="Also include non-numeric CL-* folders (e.g. CL-F7DD941E)",
    )
    p.add_argument(
        "--only", nargs="*", default=[], help="Process only the named folders (e.g. CL-005 CL-007)",
    )
    p.add_argument("--limit", type=int, default=None, help="Process first N folders only")
    p.add_argument(
        "--no-backup", action="store_true",
        help="Do not create .bak backups for violation JSON files",
    )
    p.add_argument(
        "--zip", action="store_true",
        help="Also generate <folder>_refined_pack.zip next to each bundle",
    )
    # --- LLM enrichment flags ---
    p.add_argument(
        "--enrich", action="store_true",
        help="Run the LLM enrichment stage between hydrate and validate. "
             "Uses provider-specific keys from .env (e.g. DEEPSEEK_API_KEY) "
             "or LLM_API_KEY.",
    )
    p.add_argument(
        "--no-enrich", action="store_true",
        help="Explicitly disable enrichment even if env says it's configured.",
    )
    p.add_argument(
        "--enrich-stages", default=None,
        help="Comma-separated subset of enrichment stages to run. "
             "Default: all (segments,subsections,element_grids,nexus,"
             "candidates,authorities,open_questions,cross_references).",
    )
    p.add_argument("--llm-provider", default=None,
                   help="Override LLM provider (openrouter|anthropic|deepseek|openai|ollama).")
    p.add_argument("--llm-model", default=None, help="Override LLM model id.")
    p.add_argument("--llm-base-url", default=None, help="Override LLM base URL.")
    return p.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)

    # Resolve enrichment toggle: --no-enrich wins; otherwise --enrich or
    # auto-on when Settings resolves a usable provider/key combo.
    settings = Settings.from_env()
    resolved_provider = (args.llm_provider or settings.llm_provider or "").strip().lower()
    can_enrich = bool(settings.llm_api_key) or resolved_provider == "ollama"

    if args.no_enrich:
        enrich = False
    elif args.enrich:
        enrich = True
    else:
        enrich = can_enrich

    stages = None
    if args.enrich_stages:
        stages = [s.strip() for s in args.enrich_stages.split(",") if s.strip()]

    llm_override: dict | None = None
    if any([args.llm_provider, args.llm_model, args.llm_base_url]):
        llm_override = {
            k: v for k, v in {
                "provider": args.llm_provider,
                "model": args.llm_model,
                "base_url": args.llm_base_url,
            }.items() if v
        }

    return run(
        root=args.input,
        include_extra=args.include_extra,
        only=args.only,
        limit=args.limit,
        write_backup=not args.no_backup,
        zip_output=args.zip,
        enrich=enrich,
        enrich_stages=stages,
        llm_override=llm_override,
    )


if __name__ == "__main__":
    raise SystemExit(main())
