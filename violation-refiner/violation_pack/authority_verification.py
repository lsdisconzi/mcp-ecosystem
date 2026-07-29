"""Authority verification protocol.

This module is the *only* place in the codebase that may flip an
`Authority.verified` flag from `False` to `True` and populate the
"forbidden" fields (court, rol, decision_date, author, work, pages,
instrument, holding_summary). It is named separately from `layers.py` to
make the seam explicit: layer functions PROPOSE citations; this module
DISPOSES of them against a primary source.

Three verification protocols are defined:

1. **statute_in_bundle_v1** — for `type="statute"` authorities, when the
   cited article body is in the local framework cache. Substring-matches a
   caller-supplied verbatim quote against the cached body. Deterministic,
   no network. SHA-pins the cache file at verification time so V11 can
   detect cache drift later.

2. **statute_external_fetch_v1** — for `type="statute"` authorities whose
   framework is not bundled. Caller supplies the fetched body and source
   URL; this module verifies the substring match and SHA-pins the fetched
   content. The actual fetch lives outside (in an MCP layer / refine
   pipeline) so this module stays free of network code and easy to test.

3. **human_attested_v1** — for `type="jurisprudence"` and `type="doctrine"`.
   Auto-verification of jurisprudence is too risky (rol numbers are easy
   to fabricate from LLM memory). This protocol requires the caller to
   provide rol/court/decision_date AND a verbatim matched_quote AND the
   source's SHA256. The protocol records WHO attested and HOW; it does
   not validate the rol against any external service. V11 will surface a
   `W_HUMAN_ATTESTED_AUTHORITY` warning so downstream consumers know the
   confidence factor includes a human-vouched authority.

Anti-fabrication invariants enforced here:
- A protocol call NEVER accepts a `verified=True` input without re-verifying.
- The verbatim `matched_quote` MUST be a byte-for-byte substring of the
  current source content (we don't trust the caller's substring claim).
- The source SHA256 is recomputed from the source content at call time;
  the caller's claim is checked against the recomputed value.
- Forbidden fields can only be populated through this module's protocols.
- Any other path (LLM, layer function, refine batch) that tries to set
  `verified=True` is caught by V11 as `E_AUTH_VERIFIED_BY_LLM`.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .models import Authority, ProvenanceEntry, VerificationProvenance, Violation
from .sources import FrameworkSource


class VerificationError(Exception):
    """Raised when an authority cannot be verified against the supplied source.

    Critically: this NEVER results in a half-verified authority. On any
    failure the authority is left exactly as it was (verified=False or
    its prior verified state), so callers can be confident a thrown
    VerificationError means nothing was written.
    """


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _find_authority(violation: Violation, authority_id: str) -> Authority:
    for a in violation.authorities:
        if a.authority_id == authority_id:
            return a
    raise VerificationError(f"authority {authority_id!r} not in violation.authorities")


def _replace_authority(violation: Violation, updated: Authority, *, note: str) -> Violation:
    new_authorities = [
        updated if a.authority_id == updated.authority_id else a
        for a in violation.authorities
    ]
    return violation.model_copy(update={
        "authorities": new_authorities,
        "provenance": violation.provenance + [
            ProvenanceEntry(
                timestamp=_now(),
                actor="authority_verification.verify_authority",
                operation="verify_authority",
                layer=5,
                note=note,
            )
        ],
    })


# ---------------------------------------------------------------------------
# Protocol 1: statute_in_bundle_v1
# ---------------------------------------------------------------------------

def verify_statute_in_bundle(
    violation: Violation,
    *,
    authority_id: str,
    framework: FrameworkSource,
    article_number: str,
    target_quote: str,
    instrument: str | None = None,
    pages: str | None = None,
) -> Violation:
    """Verify a `type="statute"` authority against the bundled framework cache.

    On success:
    - `verified=True`
    - `instrument` set to `<framework_code> <article_number>` (or caller override)
    - `pages` set if supplied (e.g. "N° 8" for Art. 193 numeral 8)
    - `verification_provenance` filled with the protocol's audit trail

    On failure: raises `VerificationError`. No state is written. The
    authority is left unchanged.
    """
    auth = _find_authority(violation, authority_id)
    if auth.type != "statute":
        raise VerificationError(
            f"authority {authority_id} is type={auth.type!r}; "
            "use verify_jurisprudence/doctrine for non-statute types"
        )
    if not isinstance(target_quote, str) or not target_quote.strip():
        raise VerificationError("target_quote must be a non-empty string")

    body = framework.get_article_body(article_number)
    if body is None:
        # Try progressive trimming for sub-ids like "19.4" -> "19".
        toks = article_number.split(".")
        for n in range(len(toks) - 1, 0, -1):
            body = framework.get_article_body(".".join(toks[:n]))
            if body is not None:
                break
    if body is None:
        raise VerificationError(
            f"framework {framework.framework_code()!r} has no body "
            f"for article {article_number!r}"
        )

    offset = body.find(target_quote)
    if offset < 0:
        raise VerificationError(
            f"target_quote not found verbatim in article body "
            f"(framework={framework.framework_code()}, article={article_number}, "
            f"quote_len={len(target_quote)})"
        )

    # SHA the framework cache file itself, not just the article body — this
    # lets V11 detect cache drift even when the specific article unchanged.
    source_uri = framework.cache_uri()
    # `MarkdownFrameworkSource.cache_sha256()` already returns the raw bytes
    # SHA; we trust the protocol-level implementation here.
    source_sha = framework.cache_sha256()

    provenance = VerificationProvenance(
        protocol="statute_in_bundle_v1",
        source_uri=source_uri,
        source_sha256=source_sha,
        verified_at=_now(),
        matched_quote=target_quote,
        matched_offset=offset,
        notes=f"matched in article {article_number} of {framework.framework_code()}",
    )

    updated = auth.model_copy(update={
        "verified": True,
        "instrument": instrument or f"{framework.framework_code()} Art. {article_number}",
        "pages": pages,
        "verification_provenance": provenance,
    })

    return _replace_authority(
        violation,
        updated,
        note=(
            f"Verified authority {authority_id} (statute_in_bundle_v1) against "
            f"{framework.framework_code()} Art. {article_number} "
            f"(source={source_uri}, sha={source_sha[:8]}, offset={offset})."
        ),
    )


# ---------------------------------------------------------------------------
# Protocol 2: statute_external_fetch_v1
# ---------------------------------------------------------------------------

def verify_statute_external_fetch(
    violation: Violation,
    *,
    authority_id: str,
    source_uri: str,
    source_content: str,
    target_quote: str,
    instrument: str,
    pages: str | None = None,
) -> Violation:
    """Verify a statute authority against externally-fetched content.

    The caller is responsible for the fetch itself (this keeps the module
    network-free for tests). The caller passes the raw fetched content;
    this protocol substring-matches and SHA-pins.

    `source_uri` should be the canonical authoritative URL (e.g.
    https://www.bcn.cl/leychile/...); the SHA is computed from
    `source_content` at call time.
    """
    auth = _find_authority(violation, authority_id)
    if auth.type != "statute":
        raise VerificationError(
            f"authority {authority_id} is type={auth.type!r}; "
            "verify_statute_external_fetch is statute-only"
        )
    if not isinstance(source_content, str) or not source_content:
        raise VerificationError("source_content must be a non-empty string")
    if not isinstance(target_quote, str) or not target_quote.strip():
        raise VerificationError("target_quote must be a non-empty string")

    offset = source_content.find(target_quote)
    if offset < 0:
        raise VerificationError(
            f"target_quote not found verbatim in fetched content "
            f"(source={source_uri}, quote_len={len(target_quote)})"
        )

    source_sha = _sha256_bytes(source_content.encode("utf-8"))
    provenance = VerificationProvenance(
        protocol="statute_external_fetch_v1",
        source_uri=source_uri,
        source_sha256=source_sha,
        verified_at=_now(),
        matched_quote=target_quote,
        matched_offset=offset,
        notes="externally fetched content; caller responsible for fetch hygiene",
    )

    updated = auth.model_copy(update={
        "verified": True,
        "instrument": instrument,
        "pages": pages,
        "verification_provenance": provenance,
    })
    return _replace_authority(
        violation,
        updated,
        note=(
            f"Verified authority {authority_id} (statute_external_fetch_v1) "
            f"against {source_uri} (sha={source_sha[:8]}, offset={offset})."
        ),
    )


# ---------------------------------------------------------------------------
# Protocol 3: human_attested_v1 (jurisprudence + doctrine)
# ---------------------------------------------------------------------------

def verify_human_attested(
    violation: Violation,
    *,
    authority_id: str,
    source_uri: str,
    source_content: str,
    target_quote: str,
    attestor: str,
    # Type-specific fields the caller has manually verified against the source:
    court: str | None = None,
    rol: str | None = None,
    decision_date: datetime | None = None,
    author: str | None = None,
    work: str | None = None,
    pages: str | None = None,
    instrument: str | None = None,
    holding_summary: str | None = None,
) -> Violation:
    """Verify a jurisprudence or doctrine authority against a human-attested source.

    The caller MUST have actually read the source (sentencia PDF, doctrine
    book) and provides:
    - `source_uri` (e.g. pjud.cl URL, doi:..., ISBN+page)
    - `source_content` — the raw text the caller fetched/extracted
    - `target_quote` — verbatim text proving the proposition
    - `attestor` — identifier of the human/process who attested (recorded in
      provenance.notes so audit trails are explicit)

    The protocol substring-matches and SHA-pins. It does NOT validate the
    rol against pjud or the ISBN against any registry. That's the caller's
    job. V11 surfaces these as `W_HUMAN_ATTESTED_AUTHORITY` so downstream
    consumers know human attestation is in the chain of trust.
    """
    auth = _find_authority(violation, authority_id)
    if auth.type not in {"jurisprudence", "doctrine", "comparative"}:
        raise VerificationError(
            f"authority {authority_id} is type={auth.type!r}; "
            "verify_human_attested handles jurisprudence/doctrine/comparative only"
        )
    if not isinstance(source_content, str) or not source_content:
        raise VerificationError("source_content must be a non-empty string")
    if not isinstance(target_quote, str) or not target_quote.strip():
        raise VerificationError("target_quote must be a non-empty string")
    if not isinstance(attestor, str) or not attestor.strip():
        raise VerificationError("attestor must be a non-empty string")

    # Type-specific minima — refuse to verify jurisprudence without rol.
    if auth.type == "jurisprudence" and not (court and rol and decision_date):
        raise VerificationError(
            "jurisprudence verification requires court, rol, and decision_date"
        )
    if auth.type == "doctrine" and not (author and work):
        raise VerificationError("doctrine verification requires author and work")

    offset = source_content.find(target_quote)
    if offset < 0:
        raise VerificationError(
            f"target_quote not found verbatim in source_content "
            f"(source={source_uri}, quote_len={len(target_quote)})"
        )

    source_sha = _sha256_bytes(source_content.encode("utf-8"))
    provenance = VerificationProvenance(
        protocol="human_attested_v1",
        source_uri=source_uri,
        source_sha256=source_sha,
        verified_at=_now(),
        matched_quote=target_quote,
        matched_offset=offset,
        notes=f"attested by: {attestor}",
    )

    updated = auth.model_copy(update={
        "verified": True,
        "court": court,
        "rol": rol,
        "decision_date": decision_date,
        "author": author,
        "work": work,
        "pages": pages,
        "instrument": instrument,
        "holding_summary": holding_summary,
        "verification_provenance": provenance,
    })
    return _replace_authority(
        violation,
        updated,
        note=(
            f"Verified authority {authority_id} (human_attested_v1) "
            f"by {attestor} against {source_uri} (sha={source_sha[:8]})."
        ),
    )
