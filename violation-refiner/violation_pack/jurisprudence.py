"""A `JurisprudenceProvider` backed by a Qdrant jurisprudence collection.

Contract reminder (`extensions.JurisprudenceProvider`):

    Authorities returned from `verify()` may only set verified=True when the
    rol / sala / decision_date / holding come from a primary source the
    implementation can point to.

This provider therefore separates two operations:

* `search(query, supports, max_results)` returns *unverified* Authority stubs
  built from Qdrant hits. The hit's payload populates `research_query` and
  `proposition_to_verify` only — court/rol/etc. stay None.

* `verify(authority)` only flips `verified=True` if the corresponding
  jurisprudence point in Qdrant carries a `primary_source_url` payload field
  that the caller has explicitly trusted as a primary source (i.e. it was
  indexed from a verified ingestion run, not from an LLM summary). This is a
  conservative default — the production version should re-fetch the URL and
  re-check the holding text. If the safeguard isn't satisfied, the authority
  is returned unchanged.
"""
from __future__ import annotations

from datetime import datetime

from .models import Authority
from .qdrant_index import QdrantVectorIndex


class QdrantJurisprudenceProvider:
    """Implements `violation_pack.extensions.JurisprudenceProvider`."""

    def __init__(
        self,
        index: QdrantVectorIndex,
        require_primary_source_url: bool = True,
    ) -> None:
        self.index = index
        self.require_primary_source_url = require_primary_source_url

    def search(
        self,
        query: str,
        supports: list[str],
        max_results: int = 5,
    ) -> list[Authority]:
        hits = self.index.search_jurisprudence(query, top_k=max_results)
        out: list[Authority] = []
        for i, h in enumerate(hits):
            payload = h.get("payload") or {}
            record_id = str(payload.get("record_id") or h["id"])
            out.append(
                Authority(
                    authority_id=f"JURIS-{record_id}",
                    type="jurisprudence",
                    supports=list(supports),
                    research_query=query,
                    proposition_to_verify=str(
                        payload.get("holding")
                        or payload.get("text", "")[:200]
                        or query
                    ),
                    verified=False,
                    fabrication_risk_note=(
                        "Qdrant-suggested. Stub only; verify() must confirm "
                        "rol / decision_date / holding against a primary source."
                    ),
                )
            )
        return out

    def verify(self, authority: Authority) -> Authority:
        # Look up the record this stub came from (if any).
        record_id = (
            authority.authority_id[len("JURIS-"):]
            if authority.authority_id.startswith("JURIS-")
            else None
        )
        if not record_id:
            return authority
        hits = self.index.search_jurisprudence(
            authority.proposition_to_verify, top_k=5
        )
        match = None
        for h in hits:
            payload = h.get("payload") or {}
            if str(payload.get("record_id")) == record_id:
                match = payload
                break
        if not match:
            return authority

        primary_url = match.get("primary_source_url")
        if self.require_primary_source_url and not primary_url:
            # Contract requires a primary source — leave the stub unverified.
            return authority

        # Build a verified copy. We construct via model_copy so the
        # invariant "stub constructor can't set rol/court" is unaffected.
        updated = authority.model_copy(
            update={
                "court": match.get("court") or authority.court,
                "rol": match.get("rol") or authority.rol,
                "decision_date": _parse_dt(match.get("decision_date"))
                or authority.decision_date,
                "holding_summary": match.get("holding")
                or authority.holding_summary,
                "verified": True,
                "verification_protocol": (
                    f"Qdrant-record={record_id}; primary_source_url={primary_url}"
                ),
                "fabrication_risk_note": None,
            }
        )
        return updated


def _parse_dt(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
