"""MCP catalog for ViolationRefiner.

A small machine-readable description of every MCP server this package
ships, plus a helper to emit a `claude.json`-style or VS Code
`settings.json`-style snippet a downstream project can copy in.

Why bother? Because the user wants to *add this MCP into another
project* without rediscovering all the env vars, tool names, and tags.
The catalog is the single source of truth that:
  - documents what each server exposes (transport, tool tags, env keys),
  - generates ready-to-paste client config,
  - is also exposed as a `mcp_catalog_tool` so an MCP-aware agent can
    introspect peers.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class ToolEntry:
    name: str
    description: str
    tags: list[str] = field(default_factory=list)


@dataclass
class ServerEntry:
    name: str
    description: str
    transport: str  # "stdio" | "sse" | "http"
    command: list[str]  # argv
    env: dict[str, str] = field(default_factory=dict)
    tools: list[ToolEntry] = field(default_factory=list)
    optional_env: list[str] = field(default_factory=list)


def _violation_pack_server(python: str | None = None) -> ServerEntry:
    py = python or sys.executable
    return ServerEntry(
        name="violation-pack",
        description=(
            "Anchor → hydrate → enrich → verify pipeline for OliviaLegal "
            "violation bundles. Exposes deterministic layers, LLM enrichment "
            "(multi-provider), an integrity verifier, and Qdrant/Neo4j tools."
        ),
        transport="stdio",
        command=[py, "-m", "violation_pack.mcp_server"],
        env={
            # Required for LLM enrichment; choose ONE provider:
            "LLM_PROVIDER": "openrouter",  # or anthropic | deepseek | openai | ollama
            "LLM_MODEL": "anthropic/claude-3.5-sonnet",
            "LLM_API_KEY": "${LLM_API_KEY}",
        },
        optional_env=[
            "LLM_BASE_URL",
            "LLM_TEMPERATURE",
            "LLM_MAX_TOKENS",
            "LLM_TOKEN_BUDGET",
            "LLM_TIMEOUT_SECONDS",
            "QDRANT_URL", "QDRANT_API_KEY", "QDRANT_COLLECTION_PREFIX",
            "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE",
            "EMBEDDING_MODEL", "EMBEDDING_DIM",
        ],
        tools=[
            ToolEntry("init_violation", "Construct an empty Violation skeleton.", ["layer-0"]),
            ToolEntry("build_evidence_layer_tool", "Attach evidence segments.", ["layer-1"]),
            ToolEntry("build_norms_layer_tool", "Attach cached norm articles.", ["layer-2"]),
            ToolEntry("add_element_grid_tool", "Attach a doctrinal element grid.", ["layer-3"]),
            ToolEntry("build_nexus_layer_tool", "Attach the fact↔norm↔element matrix.", ["layer-4"]),
            ToolEntry("add_authority_stub_tool", "Attach an unverified authority stub.", ["layer-5"]),
            ToolEntry("run_pipeline_tool", "Run V01–V11 validation.", ["validation"]),
            ToolEntry("enrich_violation_tool", "Run full LLM enrichment.", ["llm", "enrichment"]),
            ToolEntry("enrich_stage_tool", "Run one enrichment stage.", ["llm", "enrichment"]),
            ToolEntry("verify_enrichment_tool", "Run the LLM-output verifier.", ["verifier"]),
            ToolEntry("llm_provider_info_tool", "Report the active LLM provider.", ["llm"]),
            ToolEntry("qdrant_index_violation_tool", "Index a full Violation into Qdrant.", ["qdrant"]),
            ToolEntry("qdrant_search_segments_tool", "Vector search over transcript segments.", ["qdrant"]),
            ToolEntry("qdrant_search_articles_tool", "Vector search over framework articles.", ["qdrant"]),
            ToolEntry("qdrant_search_authorities_tool", "Vector search over authorities.", ["qdrant"]),
            ToolEntry("qdrant_search_jurisprudence_tool", "Vector search over jurisprudence.", ["qdrant"]),
            ToolEntry("qdrant_upsert_jurisprudence_tool", "Upsert jurisprudence records into Qdrant.", ["qdrant"]),
            ToolEntry("qdrant_reset_collections_tool", "Reset Qdrant collections.", ["qdrant", "destructive"]),
            ToolEntry("neo4j_upsert_violation_tool", "Upsert a Violation into the Neo4j graph.", ["neo4j"]),
            ToolEntry("neo4j_find_violations_citing_tool", "Find violations citing an article.", ["neo4j"]),
            ToolEntry("neo4j_find_violations_with_contested_element_tool", "Find violations with contested elements.", ["neo4j"]),
            ToolEntry("neo4j_walk_implications_tool", "Walk implication chains in the graph.", ["neo4j"]),
            ToolEntry("neo4j_reset_database_tool", "Reset Neo4j database.", ["neo4j", "destructive"]),
            ToolEntry("jurisprudence_search_tool", "Search jurisprudence in Qdrant.", ["jurisprudence"]),
            ToolEntry("jurisprudence_verify_tool", "Verify jurisprudence authority.", ["jurisprudence"]),
            ToolEntry("verify_statute_in_bundle_tool", "Verify statute against bundle framework cache.", ["verification"]),
            ToolEntry("verify_statute_external_fetch_tool", "Verify statute with externally fetched content.", ["verification"]),
            ToolEntry("verify_human_attested_tool", "Record human-attested authority verification.", ["verification"]),
            ToolEntry("derive_confidence_tool", "Derive confidence score for a violation.", ["confidence"]),
            ToolEntry("attach_confidence_tool", "Attach confidence to a violation.", ["confidence"]),
            ToolEntry("write_violation_json_tool", "Write violation to JSON file.", ["io"]),
            ToolEntry("build_manifest_tool", "Build manifest for violation bundle.", ["io"]),
            ToolEntry("zip_bundle_tool", "Create zip bundle.", ["io"]),
            ToolEntry("copy_source_into_bundle_tool", "Copy source files into bundle.", ["io"]),
            ToolEntry("refine_batch_tool", "Batch refine CL-* violation directories.", ["batch"]),
            ToolEntry("embedder_info_tool", "Report active embedder configuration.", ["introspection"]),
            ToolEntry("jurisprudence_ingest_tool", "Ingest rulings into Qdrant.", ["qdrant", "ingest"]),
            ToolEntry("transcript_ingest_tool", "Ingest a transcript bundle.", ["qdrant", "ingest"]),
            ToolEntry("framework_ingest_tool", "Ingest a Markdown framework.", ["qdrant", "ingest"]),
        ],
    )


def catalog(python: str | None = None) -> dict:
    """Full catalog as a JSON-serializable dict."""
    return {
        "version": 1,
        "servers": [_serializer(_violation_pack_server(python=python))],
    }


def _serializer(entry: ServerEntry) -> dict:
    d = asdict(entry)
    d["tools"] = [asdict(t) for t in entry.tools]
    return d


# ---------------------------------------------------------------------------
# Snippet generators
# ---------------------------------------------------------------------------

def to_vscode_mcp_snippet(python: str | None = None) -> dict:
    """Emit the shape VS Code's `mcp.json` / `settings.json` expects under
    `mcp.servers`."""
    entry = _violation_pack_server(python=python)
    return {
        "mcp": {
            "servers": {
                entry.name: {
                    "type": entry.transport,
                    "command": entry.command[0],
                    "args": entry.command[1:],
                    "env": entry.env,
                }
            }
        }
    }


def to_claude_desktop_snippet(python: str | None = None) -> dict:
    """Emit the shape Claude Desktop's `claude_desktop_config.json` wants."""
    entry = _violation_pack_server(python=python)
    return {
        "mcpServers": {
            entry.name: {
                "command": entry.command[0],
                "args": entry.command[1:],
                "env": entry.env,
            }
        }
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="violation-pack-catalog",
        description="Emit the MCP catalog for ViolationRefiner.",
    )
    parser.add_argument(
        "--format", choices=["catalog", "vscode", "claude"], default="catalog",
        help="Output shape: full catalog, VS Code snippet, or Claude Desktop snippet.",
    )
    parser.add_argument(
        "--python", default=None,
        help="Python interpreter path to embed (defaults to current sys.executable).",
    )
    parser.add_argument(
        "--out", default=None,
        help="Write to this file instead of stdout.",
    )
    args = parser.parse_args(argv)

    if args.format == "vscode":
        payload = to_vscode_mcp_snippet(python=args.python)
    elif args.format == "claude":
        payload = to_claude_desktop_snippet(python=args.python)
    else:
        payload = catalog(python=args.python)

    text = json.dumps(payload, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
