"""MCP server exposing the violation-pack pipeline as tools.

Each tool is a thin JSON-in / JSON-out wrapper around the corresponding pure
function in `violation_pack`. Violations are passed as dicts and the server
round-trips them through `Violation.model_validate` / `model_dump` so MCP
clients never need to know about Pydantic.

Run:
    python -m violation_pack.mcp_server
    # or, after `pip install -e .[mcp]`:
    violation-pack-mcp

Transport: stdio (--catalog) or streamable-http (MCP_TRANSPORT=streamable-http).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .confidence import attach_confidence, derive_confidence
from .layers import (
    add_authority_stub,
    add_element_grid,
    build_evidence_layer,
    build_nexus_layer,
    build_norms_layer,
)
from .authority_verification import (
    VerificationError,
    verify_human_attested,
    verify_statute_external_fetch,
    verify_statute_in_bundle,
)
from .models import ArticleElementGrid, Incident, NexusEntry, Violation
from .pack import (
    build_manifest as _build_manifest,
    copy_source_into_bundle as _copy_source,
    write_violation_json as _write_violation_json,
    zip_bundle as _zip_bundle,
)
from .sources import HtmlTranscriptSource, MarkdownFrameworkSource
from .validation import run_pipeline as _run_pipeline


# ---------------------------------------------------------------------------
# Lazy FastMCP import so the rest of the package stays dependency-free.
# ---------------------------------------------------------------------------

def _get_mcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - import-time guard
        raise SystemExit(
            "The 'mcp' package is required to run the MCP server.\n"
            "Install with: pip install -e '.[mcp]'  (or: pip install mcp)"
        ) from exc
    return FastMCP("violation-pack")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _v_load(violation: dict) -> Violation:
    return Violation.model_validate(violation)


def _v_dump(violation: Violation) -> dict:
    return json.loads(violation.model_dump_json(exclude_none=False))


def _transcript(path: str, source_id: str, bundle_uri: str) -> HtmlTranscriptSource:
    return HtmlTranscriptSource(
        path=Path(path), source_id=source_id, bundle_uri=bundle_uri
    )


def _framework(path: str, framework_code: str, bundle_uri: str) -> MarkdownFrameworkSource:
    return MarkdownFrameworkSource(
        path=Path(path), framework_code=framework_code, bundle_uri=bundle_uri
    )


# ---------------------------------------------------------------------------
# Server construction
# ---------------------------------------------------------------------------

def build_server():
    mcp = _get_mcp()

    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "violation-pack"})

    @mcp.tool()
    def init_violation(
        violation_id: str,
        title: str,
        severity: str,
        incident: dict,
        cross_references: list[dict] | None = None,
        open_questions: list[dict] | None = None,
    ) -> dict:
        """Create a blank Violation. `incident` must include date and location.
        Returns the canonical Violation JSON dict."""
        v = Violation(
            violation_id=violation_id,
            title=title,
            severity=severity,
            incident=Incident(**incident),
            cross_references=cross_references or [],
            open_questions=open_questions or [],
        )
        return _v_dump(v)

    @mcp.tool()
    def build_evidence_layer_tool(
        violation: dict,
        transcript_path: str,
        transcript_source_id: str,
        transcript_bundle_uri: str,
        segment_specs: list[dict],
    ) -> dict:
        """Layer 1: anchor segments to a transcript HTML on disk.
        Each segment_spec needs segment_id, role_in_argument, translation_en."""
        v = _v_load(violation)
        t = _transcript(transcript_path, transcript_source_id, transcript_bundle_uri)
        return _v_dump(build_evidence_layer(v, t, segment_specs))

    @mcp.tool()
    def build_norms_layer_tool(
        violation: dict,
        framework_path: str,
        framework_code: str,
        framework_bundle_uri: str,
        article_specs: list[dict],
        candidate_specs: list[dict] | None = None,
    ) -> dict:
        """Layer 2: anchor cited articles against a framework Markdown cache.
        Excerpts not present in the cache are rejected (use candidate_specs)."""
        v = _v_load(violation)
        f = _framework(framework_path, framework_code, framework_bundle_uri)
        return _v_dump(build_norms_layer(v, f, article_specs, candidate_specs or []))

    @mcp.tool()
    def add_element_grid_tool(violation: dict, grid: dict) -> dict:
        """Layer 3: add (or replace) one ArticleElementGrid."""
        v = _v_load(violation)
        return _v_dump(add_element_grid(v, ArticleElementGrid.model_validate(grid)))

    @mcp.tool()
    def build_nexus_layer_tool(violation: dict, entries: list[dict]) -> dict:
        """Layer 4: upsert NexusEntry rows keyed by (fact_id, norm_id, element_id)."""
        v = _v_load(violation)
        parsed = [NexusEntry.model_validate(e) for e in entries]
        return _v_dump(build_nexus_layer(v, parsed))

    @mcp.tool()
    def add_authority_stub_tool(
        violation: dict,
        authority_id: str,
        type: str,
        supports: list[str],
        research_query: str,
        proposition_to_verify: str,
        verification_protocol: str | None = None,
        fabrication_risk_note: str | None = None,
    ) -> dict:
        """Layer 5: add an unverified authority stub. court/rol/decision_date
        cannot be set here by design (anti-fabrication safeguard)."""
        v = _v_load(violation)
        return _v_dump(add_authority_stub(
            v,
            authority_id=authority_id,
            type_=type,
            supports=supports,
            research_query=research_query,
            proposition_to_verify=proposition_to_verify,
            verification_protocol=verification_protocol,
            fabrication_risk_note=fabrication_risk_note,
        ))

    @mcp.tool()
    def verify_statute_in_bundle_tool(
        violation: dict,
        authority_id: str,
        framework_md_path: str,
        framework_code: str,
        article_number: str,
        target_quote: str,
        instrument: str | None = None,
        pages: str | None = None,
    ) -> dict:
        """Verify a statute authority against the bundled framework cache.

        Substring-matches `target_quote` byte-for-byte against the body of
        `article_number` in the markdown file at `framework_md_path`. On
        success, flips `verified=True`, populates `instrument`/`pages`, and
        SHA-pins the cache file in `verification_provenance`. On any
        mismatch, raises VerificationError and leaves the authority
        unchanged.

        This is the ONLY tool that may flip `verified=True` for a statute
        citation. The LLM-facing enrichment path cannot call it.
        """
        v = _v_load(violation)
        fw = _framework(framework_md_path, framework_code, f"Legal framework/{Path(framework_md_path).name}")
        try:
            v2 = verify_statute_in_bundle(
                v,
                authority_id=authority_id,
                framework=fw,
                article_number=article_number,
                target_quote=target_quote,
                instrument=instrument,
                pages=pages,
            )
        except VerificationError as exc:
            raise ValueError(f"verification_failed: {exc}") from exc
        return _v_dump(v2)

    @mcp.tool()
    def verify_statute_external_fetch_tool(
        violation: dict,
        authority_id: str,
        source_uri: str,
        source_content: str,
        target_quote: str,
        instrument: str,
        pages: str | None = None,
    ) -> dict:
        """Verify a statute authority against externally-fetched content.

        Caller is responsible for the fetch and for passing the raw content
        as `source_content`. This tool substring-matches and SHA-pins the
        content; it does NOT fetch anything itself (keeps the server
        network-free for reproducibility).
        """
        v = _v_load(violation)
        try:
            v2 = verify_statute_external_fetch(
                v,
                authority_id=authority_id,
                source_uri=source_uri,
                source_content=source_content,
                target_quote=target_quote,
                instrument=instrument,
                pages=pages,
            )
        except VerificationError as exc:
            raise ValueError(f"verification_failed: {exc}") from exc
        return _v_dump(v2)

    @mcp.tool()
    def verify_human_attested_tool(
        violation: dict,
        authority_id: str,
        source_uri: str,
        source_content: str,
        target_quote: str,
        attestor: str,
        court: str | None = None,
        rol: str | None = None,
        decision_date: str | None = None,
        author: str | None = None,
        work: str | None = None,
        pages: str | None = None,
        instrument: str | None = None,
        holding_summary: str | None = None,
    ) -> dict:
        """Verify a jurisprudence or doctrine authority against a human-attested
        source. Caller MUST have read the source. Requires court+rol+date for
        jurisprudence and author+work for doctrine. V11 surfaces a
        W_HUMAN_ATTESTED_AUTHORITY warning so reviewers can see the chain of
        trust includes a human signature."""
        from datetime import datetime as _dt
        v = _v_load(violation)
        parsed_date = _dt.fromisoformat(decision_date) if decision_date else None
        try:
            v2 = verify_human_attested(
                v,
                authority_id=authority_id,
                source_uri=source_uri,
                source_content=source_content,
                target_quote=target_quote,
                attestor=attestor,
                court=court,
                rol=rol,
                decision_date=parsed_date,
                author=author,
                work=work,
                pages=pages,
                instrument=instrument,
                holding_summary=holding_summary,
            )
        except VerificationError as exc:
            raise ValueError(f"verification_failed: {exc}") from exc
        return _v_dump(v2)

    @mcp.tool()
    def derive_confidence_tool(violation: dict) -> dict:
        """Compute and return a ConfidenceDerivation for the given violation
        without attaching it. Useful for previewing the formula."""
        v = _v_load(violation)
        c = derive_confidence(v)
        return json.loads(c.model_dump_json())

    @mcp.tool()
    def attach_confidence_tool(violation: dict) -> dict:
        """Compute confidence and return the violation with it attached,
        preserving prior values in `confidence.history`."""
        v = _v_load(violation)
        return _v_dump(attach_confidence(v))

    @mcp.tool()
    def run_pipeline_tool(
        violation: dict,
        transcripts: list[dict] | None = None,
        frameworks: list[dict] | None = None,
        contract: dict | None = None,
        known_violation_ids: list[str] | None = None,
    ) -> dict:
        """Run V01-V10 validation. `transcripts` and `frameworks` are lists of
        {path, source_id|framework_code, bundle_uri} entries used to construct
        readers."""
        v = _v_load(violation)
        ts = {}
        for spec in transcripts or []:
            t = _transcript(spec["path"], spec["source_id"], spec["bundle_uri"])
            ts[t.source_id()] = t
        fs = {}
        for spec in frameworks or []:
            f = _framework(spec["path"], spec["framework_code"], spec["bundle_uri"])
            fs[f.framework_code()] = f
        report = _run_pipeline(
            v,
            transcripts=ts,
            frameworks=fs,
            contract=contract,
            known_violation_ids=set(known_violation_ids or []),
        )
        payload = json.loads(report.model_dump_json())
        payload["summary"] = report.summary
        return payload

    @mcp.tool()
    def write_violation_json_tool(violation: dict, bundle_root: str) -> dict:
        """Serialize the Violation JSON into <bundle_root>/<violation_id>.json."""
        v = _v_load(violation)
        out = _write_violation_json(v, Path(bundle_root))
        return {"path": str(out)}

    @mcp.tool()
    def build_manifest_tool(bundle_root: str, schema_version: str = "3.0") -> dict:
        """Produce MANIFEST.txt for every file in the bundle root."""
        out = _build_manifest(Path(bundle_root), schema_version=schema_version)
        return {"path": str(out)}

    @mcp.tool()
    def zip_bundle_tool(bundle_root: str, out_zip: str) -> dict:
        """Zip the bundle directory."""
        out = _zip_bundle(Path(bundle_root), Path(out_zip))
        return {"path": str(out)}

    @mcp.tool()
    def copy_source_into_bundle_tool(
        source_path: str, bundle_root: str, kind: str
    ) -> dict:
        """Copy a source artifact into the bundle's canonical location.
        `kind` is a key from BUNDLE_LAYOUT (e.g. 'transcripts_dir',
        'framework_dir')."""
        out = _copy_source(Path(source_path), Path(bundle_root), kind)
        return {"path": str(out)}

    @mcp.tool()
    def refine_batch_tool(
        input_root: str,
        only: list[str] | None = None,
        include_extra: bool = False,
        limit: int | None = None,
        write_backup: bool = True,
        zip_output: bool = False,
    ) -> dict:
        """Run the batch refiner over a folder of CL-* bundles. Returns the
        summary dict written to refine_batch_summary.json."""
        from violation_pack.refine_batch_core import run as batch_run

        rc = batch_run(
            root=Path(input_root),
            include_extra=include_extra,
            only=only or [],
            limit=limit,
            write_backup=write_backup,
            zip_output=zip_output,
        )
        summary_path = Path(input_root) / "refine_batch_summary.json"
        summary: dict[str, Any] = {"exit_code": rc}
        if summary_path.exists():
            summary["summary"] = json.loads(summary_path.read_text(encoding="utf-8"))
        return summary

    # ------------------------------------------------------------------
    # Extension tools — Qdrant / Neo4j / Jurisprudence
    # Each is registered only if the corresponding optional dependency is
    # installed AND configured. Errors at runtime surface as MCP tool errors,
    # which is the intended UX (so MCP clients can see *why* a tool failed).
    # ------------------------------------------------------------------

    @mcp.tool()
    def qdrant_index_violation_tool(violation: dict) -> dict:
        """Upsert every segment / article / authority of a violation into the
        configured Qdrant collections. Returns counts per collection."""
        from . import get_vector_index

        v = _v_load(violation)
        idx = get_vector_index()
        return idx.upsert_violation(v)

    @mcp.tool()
    def qdrant_search_segments_tool(query: str, top_k: int = 5) -> dict:
        """Vector search over indexed evidence segments."""
        from . import get_vector_index

        return {"hits": get_vector_index().search_segments(query, top_k=top_k)}

    @mcp.tool()
    def qdrant_search_articles_tool(query: str, top_k: int = 5) -> dict:
        """Vector search over indexed articles."""
        from . import get_vector_index

        return {"hits": get_vector_index().search_articles(query, top_k=top_k)}

    @mcp.tool()
    def qdrant_search_authorities_tool(query: str, top_k: int = 5) -> dict:
        """Vector search over indexed authorities (verified or stubs)."""
        from . import get_vector_index

        return {"hits": get_vector_index().search_authorities(query, top_k=top_k)}

    @mcp.tool()
    def qdrant_search_jurisprudence_tool(query: str, top_k: int = 5) -> dict:
        """Vector search over the jurisprudence corpus."""
        from . import get_vector_index

        return {"hits": get_vector_index().search_jurisprudence(query, top_k=top_k)}

    @mcp.tool()
    def qdrant_upsert_jurisprudence_tool(
        record_id: str, text: str, payload: dict
    ) -> dict:
        """Ingest one jurisprudence excerpt. Payload should include court,
        rol, decision_date, primary_source_url, holding."""
        from . import get_vector_index

        get_vector_index().upsert_jurisprudence_record(record_id, text, payload)
        return {"status": "ok", "record_id": record_id}

    @mcp.tool()
    def neo4j_upsert_violation_tool(violation: dict) -> dict:
        """Write the violation (and its segments/articles/elements/authorities
        /open-questions/cross-references) into Neo4j. Idempotent (MERGE)."""
        from . import get_knowledge_graph

        v = _v_load(violation)
        with get_knowledge_graph() as kg:
            kg.upsert_violation(v)
        return {"status": "ok", "violation_id": v.violation_id}

    @mcp.tool()
    def neo4j_find_violations_citing_tool(article_id: str) -> dict:
        """List violations that cite the given article."""
        from . import get_knowledge_graph

        with get_knowledge_graph() as kg:
            return {"violation_ids": kg.find_violations_citing(article_id)}

    @mcp.tool()
    def neo4j_find_violations_with_contested_element_tool(
        element_id_glob: str,
    ) -> dict:
        """Find violations where an element matching the glob is contested.
        Use '*' as a wildcard in element ids."""
        from . import get_knowledge_graph

        with get_knowledge_graph() as kg:
            return {
                "violation_ids": kg.find_violations_with_contested_element(
                    element_id_glob
                )
            }

    @mcp.tool()
    def neo4j_walk_implications_tool(open_question_id: str) -> dict:
        """Walk BLOCKS edges from an open question to the elements / articles /
        violations whose proof would re-derive if it resolved."""
        from . import get_knowledge_graph

        with get_knowledge_graph() as kg:
            return {"implications": kg.walk_implications_of_open_question(
                open_question_id
            )}

    @mcp.tool()
    def jurisprudence_search_tool(
        query: str, supports: list[str], max_results: int = 5
    ) -> dict:
        """Search the jurisprudence corpus and return Authority *stubs*.
        Stubs are never auto-verified; call jurisprudence_verify_tool for that."""
        from . import get_jurisprudence_provider

        authorities = get_jurisprudence_provider().search(
            query, supports, max_results=max_results
        )
        return {"authorities": [
            json.loads(a.model_dump_json()) for a in authorities
        ]}

    @mcp.tool()
    def jurisprudence_verify_tool(authority: dict) -> dict:
        """Run verify() on an Authority. Returns the Authority unchanged unless
        the backing Qdrant record carries a primary_source_url."""
        from . import get_jurisprudence_provider
        from .models import Authority as _A

        a = _A.model_validate(authority)
        result = get_jurisprudence_provider().verify(a)
        return json.loads(result.model_dump_json())

    @mcp.tool()
    def qdrant_reset_collections_tool() -> dict:
        """DESTRUCTIVE. Delete and recreate every collection under the
        configured prefix with the current embedder's dim. Only affects
        the violation-refiner namespace; other tenants in Qdrant are safe."""
        from . import get_vector_index

        return {"collections": get_vector_index().reset_collections()}

    @mcp.tool()
    def neo4j_reset_database_tool() -> dict:
        """DESTRUCTIVE. Delete every node and relationship in the configured
        Neo4j database. Only affects the violation-refiner database."""
        from . import get_knowledge_graph

        with get_knowledge_graph() as kg:
            return kg.reset_database()

    @mcp.tool()
    def embedder_info_tool() -> dict:
        """Report which embedder the running process will use, and its dim."""
        from .embeddings import default_embedder

        e = default_embedder()
        return {"name": getattr(e, "name", type(e).__name__), "dim": e.dim}

    # ---------------- Bulk ingest tools ------------------------------------

    @mcp.tool()
    def jurisprudence_ingest_tool(
        index_path: str,
        limit: int | None = None,
        skip: int = 0,
        batch_size: int = 64,
        sleep_between_batches: float = 0.0,
        max_chunks_per_ruling: int | None = 8,
    ) -> dict:
        """Ingest a juris-search corpus into the `<prefix>_jurisprudence`
        Qdrant collection. `index_path` is the absolute path of the
        scraper's `index.json` (e.g. /Users/dev/services/juris-search/
        json_jurisprudence/index.json). Returns IngestStats as a dict."""
        from . import get_vector_index
        from .ingesters import JurisprudenceIngester

        ing = JurisprudenceIngester(
            index=get_vector_index(),
            batch_size=batch_size,
            sleep_between_batches=sleep_between_batches,
            max_chunks_per_ruling=max_chunks_per_ruling,
        )
        return ing.ingest(index_path, limit=limit, skip=skip).as_dict()

    @mcp.tool()
    def transcript_ingest_tool(
        bundle_root: str,
        bundle_id: str | None = None,
        limit_segments: int | None = None,
        batch_size: int = 64,
        sleep_between_batches: float = 0.0,
    ) -> dict:
        """Ingest every utterance from an OliviaLegal incident bundle's
        transcripts into the `<prefix>_segments` collection. Points are
        tagged with synthetic violation_id="TRANSCRIPT:<filename>" so they
        don't collide with real Violation segments."""
        from . import get_vector_index
        from .ingesters import TranscriptIngester

        ing = TranscriptIngester(
            index=get_vector_index(),
            batch_size=batch_size,
            sleep_between_batches=sleep_between_batches,
        )
        return ing.ingest_bundle(
            bundle_root, bundle_id=bundle_id, limit_segments=limit_segments
        ).as_dict()

    @mcp.tool()
    def framework_ingest_tool(
        markdown_path: str,
        framework_code: str,
        framework_name: str | None = None,
        batch_size: int = 64,
    ) -> dict:
        """Parse a Markdown framework file and upsert each `### Art. N — …`
        block into the `<prefix>_articles` collection."""
        from . import get_vector_index
        from .ingesters import FrameworkIngester

        ing = FrameworkIngester(index=get_vector_index(), batch_size=batch_size)
        return ing.ingest_markdown(
            markdown_path, framework_code=framework_code, framework_name=framework_name
        ).as_dict()

    # ---------------------------------------------------------------
    # LLM enrichment + verifier tools
    # ---------------------------------------------------------------

    def _build_llm_client(override: dict | None):
        """Resolve an LLM client from Settings, optionally overridden."""
        from .config import Settings
        from .llm import build_client
        s = Settings.from_env()
        override = override or {}
        return build_client(
            provider=override.get("provider", s.llm_provider),
            model=override.get("model", s.llm_model),
            api_key=override.get("api_key", s.llm_api_key),
            base_url=override.get("base_url", s.llm_base_url),
        )

    def _load_frameworks(framework_specs: list[dict] | None) -> dict:
        out: dict = {}
        for fs in framework_specs or []:
            fw = _framework(fs["path"], fs["framework_code"], fs["bundle_uri"])
            out[fw.framework_code()] = fw
        return out

    @mcp.tool()
    def enrich_violation_tool(
        violation: dict,
        framework_specs: list[dict] | None = None,
        known_violation_ids: list[str] | None = None,
        stages: list[str] | None = None,
        llm_override: dict | None = None,
    ) -> dict:
        """Run the full LLM enrichment pipeline (segments → subsections →
        element_grids → nexus → candidates → authorities → open_questions
        → cross_references) on a Violation and return the enriched dict.

        `framework_specs` is a list of {path, framework_code, bundle_uri}
        used for substring verification of article excerpts.
        `stages` (optional) restricts which stages run.
        `llm_override` (optional) overrides provider/model/api_key/base_url.
        """
        from .enrich import enrich_violation
        client = _build_llm_client(llm_override)
        v = _v_load(violation)
        fws = _load_frameworks(framework_specs)
        enriched = enrich_violation(
            v,
            client=client,
            frameworks=fws,
            known_violation_ids=set(known_violation_ids or []),
            stages=stages,
        )
        return _v_dump(enriched)

    @mcp.tool()
    def enrich_stage_tool(
        stage: str,
        violation: dict,
        framework_specs: list[dict] | None = None,
        known_violation_ids: list[str] | None = None,
        llm_override: dict | None = None,
    ) -> dict:
        """Run a single enrichment stage. `stage` must be one of:
        segments, subsections, element_grids, nexus, candidates,
        authorities, open_questions, cross_references."""
        from .enrich import ENRICHMENT_STAGES, enrich_violation
        if stage not in ENRICHMENT_STAGES:
            raise ValueError(
                f"unknown stage {stage!r}; must be one of {ENRICHMENT_STAGES}"
            )
        client = _build_llm_client(llm_override)
        v = _v_load(violation)
        fws = _load_frameworks(framework_specs)
        enriched = enrich_violation(
            v,
            client=client,
            frameworks=fws,
            known_violation_ids=set(known_violation_ids or []),
            stages=[stage],
        )
        return _v_dump(enriched)

    @mcp.tool()
    def verify_enrichment_tool(
        violation: dict,
        framework_specs: list[dict] | None = None,
        known_violation_ids: list[str] | None = None,
    ) -> dict:
        """Run the enrichment verifier (substring/segment/nexus/authority
        integrity checks). Returns the structured VerificationReport.
        Errors block; warnings annotate."""
        from .verifier import verify_enrichment
        v = _v_load(violation)
        fws = _load_frameworks(framework_specs)
        report = verify_enrichment(
            v,
            frameworks=fws,
            known_violation_ids=set(known_violation_ids or []),
        )
        return report.as_dict()

    @mcp.tool()
    def llm_provider_info_tool() -> dict:
        """Report the currently-configured LLM provider, model, and base URL
        (without leaking the API key)."""
        from .config import Settings
        from .llm import PROVIDER_DEFAULTS
        s = Settings.from_env()
        return {
            "provider": s.llm_provider,
            "model": s.llm_model or PROVIDER_DEFAULTS.get(s.llm_provider, {}).get("model"),
            "base_url": s.llm_base_url or PROVIDER_DEFAULTS.get(s.llm_provider, {}).get("base_url"),
            "has_api_key": bool(s.llm_api_key),
            "supported_providers": sorted(PROVIDER_DEFAULTS.keys()),
        }

    return mcp


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Start the MCP server (stdio or streamable-http), or emit catalog info."""
    import argparse
    parser = argparse.ArgumentParser(prog="violation-pack-mcp")
    parser.add_argument(
        "--catalog", choices=["catalog", "vscode", "claude"], default=None,
        help="Instead of starting the server, print the MCP catalog "
             "(or a VS Code / Claude Desktop client config snippet) and exit.",
    )
    args = parser.parse_args()

    if args.catalog:
        from .mcp_catalog import main as catalog_main
        raise SystemExit(catalog_main(["--format", args.catalog]))

    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8124"))

    server = build_server()

    if transport == "stdio":
        server.run()
        return

    if transport not in {"sse", "streamable-http"}:
        raise ValueError(
            f"Unsupported MCP_TRANSPORT '{transport}'. Use: stdio, sse, streamable-http"
        )

    if hasattr(server, "settings"):
        if hasattr(server.settings, "host"):
            server.settings.host = host
        if hasattr(server.settings, "port"):
            server.settings.port = port

    server.run(transport=transport)


if __name__ == "__main__":
    main()
