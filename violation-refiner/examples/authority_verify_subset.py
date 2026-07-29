#!/usr/bin/env python3
"""Verify a subset of violation authorities using statute_in_bundle_v1.

This workflow is intentionally deterministic and local-only:
- add a statute authority stub tied to an established article
- verify it against the bundle's markdown framework cache
- write provenance-rich authority data back to the bundle JSON
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from violation_pack.authority_verification import VerificationError, verify_statute_in_bundle
from violation_pack.confidence import attach_confidence
from violation_pack.layers import add_authority_stub
from violation_pack.models import Violation
from violation_pack.sources import MarkdownFrameworkSource


def _article_number(article_id: str) -> str:
    if ".Art." not in article_id:
        raise ValueError(f"article_id has no .Art. marker: {article_id!r}")
    tail = article_id.split(".Art.", 1)[1]
    return tail.split(".", 1)[0]


def _tokenize(value: str) -> str:
    chars = [ch if ch.isalnum() else "-" for ch in value.upper()]
    token = "".join(chars)
    while "--" in token:
        token = token.replace("--", "-")
    return token.strip("-")


def _pick_framework_path(bundle_dir: Path, violation: Violation, framework_code: str) -> tuple[Path, str]:
    for fw in violation.framework_caches:
        if fw.framework_code == framework_code:
            rel_uri = fw.cache_file
            return bundle_dir / rel_uri, rel_uri
    raise ValueError(f"framework {framework_code!r} not found in framework_caches")


def _pick_fallback_anchor(violation: Violation) -> tuple[str, str]:
    """Pick (framework_code, article_number) when established_articles is empty.

    Priority:
    1) candidate_articles that can be parsed and whose framework exists in cache
    2) first framework cache + its first cached article number
    """
    known_frameworks = {fw.framework_code for fw in violation.framework_caches}

    for cand in violation.candidate_articles:
        cid = cand.candidate_article_id
        if ".Art." not in cid:
            continue
        parts = cid.split(".")
        if len(parts) < 3:
            continue
        fw_code = parts[1]
        if fw_code not in known_frameworks:
            continue
        art_num = _article_number(cid)
        return fw_code, art_num

    for fw in violation.framework_caches:
        if fw.articles_cached:
            return fw.framework_code, fw.articles_cached[0]

    raise ValueError(f"{violation.violation_id}: no framework/article anchor available for fallback")


def _verify_one(bundle_dir: Path) -> dict:
    violation_id = bundle_dir.name
    vio_path = bundle_dir / f"{violation_id}.json"
    violation = Violation.model_validate_json(vio_path.read_text(encoding="utf-8"))

    if violation.established_articles:
        article = violation.established_articles[0]
        framework_code = article.framework_code
        article_number = _article_number(article.article_id)
        supports = [article.article_id]
        research_query = (
            f"Verify {article.article_id} verbatim excerpt against bundled "
            f"framework cache {framework_code}."
        )
        proposition = (
            f"{article.article_id} appears verbatim in the framework cache and "
            "is grounded as a legal basis in this violation."
        )
        target_quote = article.verbatim_excerpt
    else:
        framework_code, article_number = _pick_fallback_anchor(violation)
        supports = []
        research_query = (
            f"Verify fallback statute anchor {framework_code} Art. {article_number} "
            "against bundled framework cache for authority bootstrap."
        )
        proposition = (
            f"{framework_code} Art. {article_number} is present in the local framework cache "
            "and can be protocol-verified while article enrichment is pending."
        )
        target_quote = ""

    framework_path, framework_uri = _pick_framework_path(bundle_dir, violation, framework_code)
    framework = MarkdownFrameworkSource(
        path=framework_path,
        framework_code=framework_code,
        bundle_uri=framework_uri,
    )
    if not target_quote:
        body = framework.get_article_body(article_number)
        if not body:
            raise ValueError(
                f"{violation_id}: fallback article body missing for {framework_code} Art. {article_number}"
            )
        # Use a deterministic snippet for substring verification.
        target_quote = body.strip()[:220]

    authority_id = f"AUTH-STAT-{framework_code}-{_tokenize(article_number)}"
    violation = add_authority_stub(
        violation,
        authority_id=authority_id,
        type_="statute",
        supports=supports,
        research_query=research_query,
        proposition_to_verify=proposition,
        verification_protocol="statute_in_bundle_v1",
        fabrication_risk_note="Protocol-based local verification only; no fabricated citation metadata.",
    )
    try:
        violation = verify_statute_in_bundle(
            violation,
            authority_id=authority_id,
            framework=framework,
            article_number=article_number,
            target_quote=target_quote,
            instrument=f"{framework_code} Art. {article_number}",
        )
    except VerificationError as exc:
        raise RuntimeError(f"{violation_id}: verification failed for {authority_id}: {exc}") from exc

    violation = attach_confidence(violation)
    vio_path.write_text(violation.model_dump_json(indent=2), encoding="utf-8")

    auth = next(a for a in violation.authorities if a.authority_id == authority_id)
    return {
        "violation_id": violation_id,
        "authority_id": authority_id,
        "supports": auth.supports,
        "verified": auth.verified,
        "protocol": auth.verification_provenance.protocol if auth.verification_provenance else None,
        "source_uri": auth.verification_provenance.source_uri if auth.verification_provenance else None,
        "source_sha256": auth.verification_provenance.source_sha256 if auth.verification_provenance else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify statute authorities for a subset of bundles")
    parser.add_argument("--input", default="build/cl_batch", help="Directory containing CL-### bundle folders")
    parser.add_argument(
        "--only",
        nargs="+",
        default=["CL-001", "CL-005", "CL-015"],
        help="Violation IDs to process",
    )
    args = parser.parse_args()

    root = Path(args.input)
    summaries: list[dict] = []
    for vid in args.only:
        summaries.append(_verify_one(root / vid))

    print(json.dumps({"processed": summaries}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())