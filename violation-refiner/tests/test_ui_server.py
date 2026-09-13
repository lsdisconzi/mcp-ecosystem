"""Tests for the browser bridge (`violation_pack.ui_server` + the UI page).

Two things are worth guarding here:

1. **The bridge contract.** `/api/tools` must describe every registered tool and
   `/api/tool` must round-trip a real call, map tool errors to 400, unknown
   tools to 404, and refuse destructive tools without confirmation.

2. **UI ↔ server drift.** The HTML hard-codes tool names in `data-tool`
   attributes and `STEP_TOOLS`. If a tool is renamed, that binding silently
   breaks and the button just stops working. `test_ui_references_only_real_tools`
   turns that into a test failure instead.

These tests need the `[mcp]` extra (starlette + a TestClient-capable httpx), so
they skip cleanly when it is absent — same pattern as the qdrant/neo4j tests.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="needs the [mcp] extra")
pytest.importorskip("httpx", reason="needs httpx for the Starlette TestClient")

from starlette.testclient import TestClient  # noqa: E402

from violation_pack.mcp_server import build_server  # noqa: E402
from violation_pack.ui_server import (  # noqa: E402
    UI_FILENAME,
    describe_tools,
    discover_sources,
    discover_transcript,
    browse_workspace,
    discover_bundles,
    find_ui_path,
    probe_runtime,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = REPO_ROOT / "ui" / UI_FILENAME

#: API routes the bridge promises. `/health` is MCP-owned and asserted too.
EXPECTED_API_ROUTES = {"/", "/api/health", "/api/tools", "/api/tool", "/api/catalog", "/api/sources", "/api/source-transcript", "/api/browse", "/api/bundles"}


@pytest.fixture(scope="module")
def server():
    return build_server()


@pytest.fixture(scope="module")
def client(server):
    with TestClient(server.streamable_http_app()) as c:
        yield c


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------

def _server_tool_names(server) -> set[str]:
    # ToolManager.list_tools() is SYNCHRONOUS despite the async-sounding name.
    return {t.name for t in server._tool_manager.list_tools()}


def _referenced_tool_names() -> set[str]:
    """Every concrete tool name the HTML names, from `data-tool` and `STEP_TOOLS`.

    `openToolPanel()` builds its run button with ``data-tool="${name}"``, where
    the value is whatever tool the user opened — a wildcard, not a literal name,
    so template-literal placeholders are excluded.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    names = {
        n for n in re.findall(r'data-tool="([^"]+)"', html)
        if "${" not in n
    }
    step_block = re.search(r"const STEP_TOOLS = \{(.*?)\n\};", html, re.S)
    assert step_block, "STEP_TOOLS map not found in the UI"
    names |= set(re.findall(r"'([a-z0-9_]+_tool)'", step_block.group(1)))
    return names


# ---------------------------------------------------------------------------
# Asset discovery
# ---------------------------------------------------------------------------

def test_ui_html_exists():
    assert HTML_PATH.is_file(), f"missing {HTML_PATH}"


def test_find_ui_path_resolves_to_the_workspace_file():
    found = find_ui_path()
    assert found is not None, "find_ui_path() could not locate the UI"
    assert found.name == UI_FILENAME
    assert found.is_file()


# ---------------------------------------------------------------------------
# Tool descriptors
# ---------------------------------------------------------------------------

def test_describe_tools_covers_every_registered_tool(server):
    described = describe_tools(server._tool_manager)
    assert {t["name"] for t in described} == _server_tool_names(server)
    assert len(described) == 39


def test_describe_tools_exposes_json_schema(server):
    by_name = {t["name"]: t for t in describe_tools(server._tool_manager)}
    init = by_name["init_violation"]
    assert init["required"] == ["violation_id", "title", "severity", "incident"]
    assert "open_questions" in init["optional"]
    assert init["parameters"]["properties"]["violation_id"]["type"] == "string"


def test_only_the_reset_tools_are_marked_destructive(server):
    destructive = {t["name"] for t in describe_tools(server._tool_manager) if t["destructive"]}
    assert destructive == {"qdrant_reset_collections_tool", "neo4j_reset_database_tool"}


# ---------------------------------------------------------------------------
# Runtime probe
# ---------------------------------------------------------------------------

def test_probe_runtime_reports_python_and_pydantic():
    probe = probe_runtime(tool_count=39)
    assert probe["status"] == "ok"
    assert probe["python"]["ok"] is True
    assert probe["python"]["required"] == ">=3.10"
    assert probe["packages"]["pydantic"]["present"] is True
    assert probe["tools"]["count"] == 39
    assert probe["ui"]["present"] is True


def test_probe_runtime_lists_every_optional_extra():
    modules = {e["module"] for e in probe_runtime()["packages"]["extras"]}
    assert modules == {"mcp", "httpx", "qdrant_client", "neo4j"}


# ---------------------------------------------------------------------------
# Route mounting
# ---------------------------------------------------------------------------

def test_ui_routes_are_mounted_on_the_mcp_app(server):
    paths = {getattr(r, "path", None) for r in server._custom_starlette_routes}
    assert EXPECTED_API_ROUTES <= paths

def test_include_ui_false_omits_the_bridge():
    bare = build_server(include_ui=False)
    paths = {getattr(r, "path", None) for r in bare._custom_starlette_routes}
    assert not (EXPECTED_API_ROUTES & paths)


# ---------------------------------------------------------------------------
# HTTP contract
# ---------------------------------------------------------------------------

def test_get_root_serves_the_ui(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "ViolationRefiner" in res.text


def test_get_api_tools_matches_the_server(client):
    payload = client.get("/api/tools").json()
    assert payload["count"] == 39
    assert len(payload["tools"]) == 39
    assert {t["name"] for t in payload["tools"]} == _server_tool_names(build_server())


def test_get_api_health_is_ok(client):
    payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert payload["python"]["ok"] is True


def test_discover_sources_matches_the_data_corpus():
    payload = discover_sources()
    assert payload["ok"] is True
    assert len(payload["transcripts"]) == 27
    assert len(payload["frameworks"]) >= 20
    stg7 = next(t for t in payload["transcripts"] if "STG_7" in t["name"])
    assert stg7["source_id"] == "STG-7"
    assert stg7["segment_count"] == 183
    assert stg7["path"] == stg7["uri"]
    assert not stg7["path"].startswith("/")
    chipencod = next(f for f in payload["frameworks"] if f["name"] == "CHIPENCOD_CP.md")
    assert chipencod["jurisdiction"] == "CL"
    assert chipencod["framework_code"] == "CHIPENCOD"
    assert chipencod["article_count"] == 12


def test_get_api_sources_returns_transcript_and_framework_metadata(client):
    res = client.get("/api/sources")
    assert res.status_code == 200
    payload = res.json()
    assert payload["root"].endswith("/data")
    assert payload["transcripts"]
    assert payload["frameworks"]


def test_discover_transcript_returns_parsed_segments():
    uri = "data/transcripts/html/I-002_05_NAR-07_STG_7_post_removal_investigation.html"
    payload = discover_transcript(uri)
    assert payload is not None
    assert payload["source_id"] == "STG-7"
    assert payload["segment_count"] == 183
    assert payload["segments"][0] == {
        "segment_id": "seg-0",
        "audio_offset_start": 94.0,
        "audio_offset_end": 95.3,
        "speaker": "passenger",
        "verbatim": "Una pregunta?",
    }


def test_get_api_source_transcript_rejects_unknown_uri(client):
    res = client.get("/api/source-transcript", params={"uri": "data/transcripts/json/nope.json"})
    assert res.status_code == 400


def test_browse_workspace_lists_real_project_entries():
    payload = browse_workspace("data/transcripts/html")
    assert payload is not None
    assert payload["kind"] == "directory"
    assert any(entry["name"].endswith(".html") for entry in payload["entries"])


def test_browse_workspace_rejects_escape_paths(client):
    assert browse_workspace("../../") is None
    res = client.get("/api/browse", params={"path": "../../", "kind": "directory"})
    assert res.status_code == 400


def test_browse_workspace_follows_a_symlink_that_leaves_the_workspace():
    """``data/law`` and ``data/transcripts/html`` are symlinks out of the workspace.

    Resolving before checking containment made them unreachable — ``data/law`` was
    refused silently for as long as it has existed, with no test covering it.
    """
    law = browse_workspace("data/law")
    assert law is not None, "data/law is a symlink to ../transcription/data — must be browsable"
    assert law["kind"] == "directory"
    assert law["path"] == "data/law"
    assert [(e["name"], e["kind"]) for e in law["entries"]][:1] != []

    html = browse_workspace("data/transcripts/html")
    assert html is not None
    assert html["path"] == "data/transcripts/html"
    assert html["parent"] == "data/transcripts"
    assert len([e for e in html["entries"] if e["name"].endswith(".html")]) == 27
    # Entries must stay workspace-relative, not resolve to the symlink's target.
    assert all(e["path"].startswith("data/transcripts/html/") for e in html["entries"])


def test_browse_workspace_still_rejects_traversal_through_a_symlink(client):
    """Fixing the symlink case must not have opened a traversal hole."""
    assert browse_workspace("../transcription/data/law") is None
    assert browse_workspace("data/law/../../..") is None
    assert browse_workspace("/etc") is None
    assert browse_workspace("data/transcripts/html/../../../../olivia") is None
    res = client.get("/api/browse", params={"path": "data/law/../../..", "kind": "directory"})
    assert res.status_code == 400


def test_browse_workspace_rejects_a_missing_target():
    """A link whose target is gone must resolve to nothing, not raise."""
    assert browse_workspace("data/does-not-exist") is None
    assert browse_workspace("data/transcripts/nope.html", kind="file") is None


def test_discover_bundles_reads_real_build_directories():
    payload = discover_bundles()
    assert payload["root"] == "build"
    assert {bundle["id"] for bundle in payload["bundles"]} == {"CL-005"}
    assert payload["bundles"][0]["file_count"] > 0


def test_get_api_bundles_returns_real_build_directories(client):
    res = client.get("/api/bundles")
    assert res.status_code == 200
    assert res.json()["bundles"][0]["id"] == "CL-005"


def test_build_evidence_rejects_untrusted_transcript_paths(client):
    for path in ("/etc/passwd", "data/transcripts/html/../../../../etc/passwd"):
        res = client.post(
            "/api/tool",
            json={
                "name": "build_evidence_layer_tool",
                "args": {"transcript_path": path},
            },
        )
        assert res.status_code == 400
        assert "data/transcripts/html" in res.json()["error"]


def test_post_api_tool_round_trips_a_real_call(client):
    res = client.post(
        "/api/tool",
        json={"name": "init_violation", "args": {
            "violation_id": "CL-TEST",
            "title": "Bridge round-trip",
            "severity": "LOW",
            "incident": {"date": "2025-01-01", "location": "SCL"},
            "open_questions": [],
        }},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    # call_tool() returns the tool's real value, not an MCP content envelope.
    assert isinstance(body["result"], dict)
    assert body["result"]["violation_id"] == "CL-TEST"
    assert "confidence" in body["result"]


def test_post_api_tool_maps_validation_errors_to_400(client):
    res = client.post("/api/tool", json={"name": "init_violation", "args": {}})
    assert res.status_code == 400
    body = res.json()
    assert body["ok"] is False
    assert "validation error" in body["error"]


def test_post_api_tool_returns_404_for_unknown_tool(client):
    res = client.post("/api/tool", json={"name": "definitely_not_a_tool", "args": {}})
    assert res.status_code == 404
    assert "Unknown tool" in res.json()["error"]


def test_destructive_tool_requires_confirmation(client):
    res = client.post("/api/tool", json={"name": "qdrant_reset_collections_tool", "args": {}})
    assert res.status_code == 409
    body = res.json()
    assert body["requires_confirmation"] is True
    assert body["destructive"] is True


def test_malformed_body_is_rejected(client):
    res = client.post("/api/tool", json=["not", "an", "object"])
    assert res.status_code == 400
    assert res.json()["ok"] is False


def test_cors_preflight_is_answered(client):
    res = client.options("/api/tool", headers={"Origin": "null"})
    assert res.status_code == 204
    assert res.headers["access-control-allow-origin"] == "*"


# ---------------------------------------------------------------------------
# Drift guards — the whole point of wiring the UI
# ---------------------------------------------------------------------------

def test_ui_references_only_real_tools(server):
    """Every tool the HTML binds to must exist on the server."""
    missing = _referenced_tool_names() - _server_tool_names(server)
    assert not missing, (
        f"UI references tools the server does not expose: {sorted(missing)}. "
        "A button bound to these would fail at click time."
    )


def test_every_server_tool_is_reachable_from_the_ui(server):
    """No tool should be orphaned — each needs a panel or a step-strip entry."""
    unused = _server_tool_names(server) - _referenced_tool_names()
    assert not unused, f"tools with no UI binding: {sorted(unused)}"


def test_step_tools_cover_every_wizard_step():
    html = HTML_PATH.read_text(encoding="utf-8")
    block = re.search(r"const STEP_TOOLS = \{(.*?)\n\};", html, re.S).group(1)
    steps = set(re.findall(r"(s\d+):", block))
    assert steps == {f"s{i}" for i in range(15)}, "STEP_TOOLS must cover S0–S14"


def test_ui_calls_the_documented_endpoints():
    html = HTML_PATH.read_text(encoding="utf-8")
    for endpoint in ("/api/health", "/api/tools", "/api/sources", "/api/bundles", "/api/tool"):
        assert f"'{endpoint}'" in html, f"UI never calls {endpoint}"
    assert "'/api/source-transcript?uri='" in html


def test_tool_manager_list_tools_is_synchronous(server):
    """Pin the private-API assumption so an `mcp` upgrade fails loudly.

    The bridge calls `server._tool_manager.list_tools()` and treats the result as
    a plain list. If a future `mcp` release makes it a coroutine, every `/api/*`
    route would break; this test makes that a red test instead of a dead UI.
    """
    result = server._tool_manager.list_tools()
    assert isinstance(result, list), (
        "ToolManager.list_tools() no longer returns a plain list — "
        "update ui_server.py (do NOT await it)."
    )
    assert len(result) == 39


def test_tool_manager_call_tool_returns_a_plain_value(server):
    """Pin that call_tool() is awaited but returns the unwrapped result."""
    import asyncio
    import inspect

    assert inspect.iscoroutinefunction(server._tool_manager.call_tool)
    result = asyncio.run(server._tool_manager.call_tool("llm_provider_info_tool", {}))
    assert isinstance(result, dict)
    assert "content" not in result, "call_tool() started returning an MCP envelope"
    assert result["supported_providers"]


def test_ui_server_module_is_importable_without_starlette_installed():
    """The bridge must stay lazily imported so the core stays Pydantic-only.

    `mcp_server` imports it inside `build_server()`, and `ui_server` imports
    starlette inside `build_ui_routes()` — so importing the module itself must
    not require starlette at all.
    """
    source = (REPO_ROOT / "violation_pack" / "ui_server.py").read_text(encoding="utf-8")
    top_level_imports = [
        line for line in source.splitlines()
        if line.startswith(("import ", "from ")) and "starlette" in line
    ]
    assert not top_level_imports, (
        "starlette must only be imported inside build_ui_routes(), not at module "
        f"scope, or the core package stops working without the [mcp] extra: {top_level_imports}"
    )
