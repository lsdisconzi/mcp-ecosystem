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
    describe_schema,
    describe_settings,
    describe_tools,
    discover_bundle,
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
EXPECTED_API_ROUTES = {"/", "/api/health", "/api/tools", "/api/tool", "/api/catalog", "/api/sources", "/api/source-transcript", "/api/browse", "/api/bundles", "/api/bundle", "/api/schema", "/api/settings"}


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
    # The S3/S13 pickers and the Settings overlay print these roots instead of
    # assuming a layout, so they must reflect the real corpus directories.
    assert payload["transcripts_root"] == "data/transcripts/html"
    assert payload["frameworks_root"] == "data/law"
    # ...and they are workspace-relative, which is what /api/browse accepts.
    assert not payload["transcripts_root"].startswith("/")
    assert payload["transcripts_json"], "the JSON evidence corpus came back empty"
    assert payload["transcripts_json"][0]["path"].startswith("data/transcripts/json/")
    assert all("segment_count" in t for t in payload["transcripts_json"])


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
    # ``build/`` is a generated output tree whose contents grow with every
    # conversion, so assert the structural contract instead of a pinned list.
    ids = [bundle["id"] for bundle in payload["bundles"]]
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"CL-\d+", bundle_id) for bundle_id in ids)
    assert "CL-005" in ids
    by_id = {bundle["id"]: bundle for bundle in payload["bundles"]}
    assert by_id["CL-005"]["file_count"] > 0


def test_get_api_bundles_returns_real_build_directories(client):
    res = client.get("/api/bundles")
    assert res.status_code == 200
    ids = [bundle["id"] for bundle in res.json()["bundles"]]
    assert ids == sorted(ids)
    assert "CL-005" in ids


def test_discover_bundle_reads_the_real_cl005_artifacts():
    payload = discover_bundle("CL-005")
    assert payload is not None
    assert payload["path"] == "build/CL-005"
    # Every artifact the UI renders from must be present for a finished bundle.
    assert payload["artifacts_present"] == {
        "violation": True, "contract": True, "validation": True,
        "manifest": True, "warnings": True,
    }

    violation = payload["violation"]
    assert violation["violation_id"] == "CL-005"
    # The bundle's own values, not the demo fixtures the UI used to hardcode.
    assert violation["severity"] == "CRITICAL"
    assert violation["incident"]["flight"] == "LA8159"

    # checks.json has no summary key, so the counts are recomputed server-side.
    assert payload["validation_summary"] == {
        "total": len(payload["validation"]["checks"]),
        "pass": sum(c["status"] == "pass" for c in payload["validation"]["checks"]),
        "warn": sum(c["status"] == "warn" for c in payload["validation"]["checks"]),
        "fail": sum(c["status"] == "fail" for c in payload["validation"]["checks"]),
    }
    assert payload["validation_summary"]["total"] > 0

    # The file listing feeds the drawer's Files tab; paths stay workspace-relative.
    assert payload["file_count"] > 0
    assert all(not f["path"].startswith("/") for f in payload["files"])
    assert all(f["path"].startswith("build/CL-005/") for f in payload["files"])


def test_discover_bundle_refuses_bad_and_traversing_ids():
    for bad in ("", "CL-abc", "CL-005/../CL-001", "../../etc", "/etc/passwd", "build/CL-005"):
        assert discover_bundle(bad) is None, bad
    # A well-formed id with no directory is absent, not an error shape.
    assert discover_bundle("CL-999999") is None


def test_get_api_bundle_route(client):
    res = client.get("/api/bundle", params={"violation_id": "CL-005"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["violation"]["violation_id"] == "CL-005"

    bad = client.get("/api/bundle", params={"violation_id": "../etc"})
    assert bad.status_code == 400
    assert client.get("/api/bundle").status_code == 400


def test_describe_schema_derives_every_option_list_from_the_models():
    from typing import get_args

    from violation_pack import models
    from violation_pack.pack import BUNDLE_LAYOUT

    def args(name: str, field: str) -> list[str]:
        annotation = getattr(models, name).model_fields[field].annotation
        return [str(v) for v in get_args(annotation)]

    schema = describe_schema()
    # Each list must equal the Literal it claims to describe, so adding a member
    # to models.py cannot leave the UI unable to display it.
    assert schema["severity"] == args("Violation", "severity")
    assert schema["proof_status"] == args("Element", "proof_status")
    assert schema["proof_weights"] == models.PROOF_WEIGHTS
    assert schema["authority_protocol"] == args("VerificationProvenance", "protocol")
    assert schema["check_status"] == args("CheckResult", "status")
    assert schema["nexus_strength"] == args("NexusEntry", "strength")
    assert schema["norm_type"] == args("CachedArticle", "norm_type")
    # The staging destinations are the layout keys pack.copy_source_into_bundle
    # accepts, not a parallel hand-written list.
    assert schema["bundle_layout"] == dict(BUNDLE_LAYOUT)
    assert "transcripts_dir" in schema["bundle_layout"]

    # S9 and S10 render these registries; mirroring them by hand is how a stage
    # or check silently disappears from the UI when the backend grows one.
    from violation_pack.enrich import ENRICHMENT_STAGES
    from violation_pack.validation import DEFAULT_PIPELINE

    assert schema["enrichment_stages"] == list(ENRICHMENT_STAGES)
    assert len(schema["enrichment_stages"]) == 8
    assert schema["validation_pipeline"] == [
        {"check_id": cid, "name": name} for cid, name, _ in DEFAULT_PIPELINE
    ]
    assert [c["check_id"] for c in schema["validation_pipeline"]][0] == "V01"


def test_get_api_schema_and_settings(client):
    schema = client.get("/api/schema")
    assert schema.status_code == 200
    assert schema.json()["severity"][0] == "LOW"

    res = client.get("/api/settings")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    # Defaults come from config.Settings, so they match what tools actually see.
    assert body["settings"]["qdrant_collection_prefix"] == "violationrefiner_v1"
    assert body["settings"]["neo4j_database"] == "agent.violation.refiner"
    assert body["settings"]["authority_verification_floor"] == 0.85
    # Secrets never round-trip; only their configured-ness does.
    assert set(body["secrets"]) == {"qdrant_api_key", "neo4j_password", "llm_api_key"}
    assert all(isinstance(v, bool) for v in body["secrets"].values())
    assert body["paths"]["buildRoot"].endswith("/build")
    assert body["paths"]["uiFile"] == str(HTML_PATH)


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


def test_ui_hydrates_from_the_server_instead_of_a_baked_in_bundle():
    """The wizard must render live artifacts, not the demo values it shipped with.

    The page was originally a static mock: every step carried fabricated demo
    content (``LA-1234``, ``Detencion irregular...``, ``AUTH-CL005-01``,
    ``0.74``, ``violation-pack-mcp``) that matched no bundle on disk. Each
    section now derives from ``/api/bundle``, ``/api/schema``, or
    ``/api/settings``; this test fails if any of those literals creeps back, or
    if a step quietly stops calling its hydration function.
    """
    html = HTML_PATH.read_text(encoding="utf-8")

    demo_literals = {
        # incident identity from the old mock
        "LA-1234", "LA8159-2025", "Detención irregular", "Detencion irregular",
        "2025-11-02", "15:16",
        # fabricated legal findings
        "OQ-CL005-PDI-PARTE", "AUTH-CL005-01", "AUTH-CL005-02",
        "CL.CHIPENCOD.Art.193.8.elem.dolo", "STG-7.seg-55",
        # fabricated scores / counts
        "0.74", "0.43", "9 checks", "11 checks",
        # invented infrastructure names
        "violation-pack-mcp", "rulings_index.json", "violation-pack-dev",
        # a confirm-token literal the UI must read off Settings instead
        "agent.violation.refiner", "violationrefiner_v1",
    }
    # Only the document body is scanned: the design system legitimately uses
    # values like ``font-size: 0.74rem`` in <style>, which say nothing about
    # whether the wizard renders live data.
    body = html.split("</style>", 1)[1]
    found = sorted(l for l in demo_literals if l in body)
    assert not found, (
        f"hardcoded demo values are back in the UI: {found}. "
        "Derive them from /api/bundle, /api/schema or /api/settings."
    )

    # Every hydration function the dispatcher claims to have must exist.
    declared = set(re.findall(r"^\s*function\s+(hydrate\w+)\s*\(", html, re.M))
    expected = {f"hydrateS{i}" for i in range(15)} | {
        "hydrateSettings", "hydrateSettingsEnv", "hydrateHealth",
        "hydrateS14Catalog", "hydrateValidation", "hydrateStats",
        "hydrateBundleSelector", "hydrateSourceSelectors",
    }
    assert expected - declared == set(), (
        f"UI is missing hydrators: {sorted(expected - declared)}"
    )


def test_every_wizard_step_derives_its_gate_from_the_bundle():
    """Each step shows a live gate banner; a static one would misreport state."""
    html = HTML_PATH.read_text(encoding="utf-8")
    for index in range(15):
        gate = f'id="s{index}Gate"'
        assert gate in html, f"step S{index} has no {gate} banner"
        start = html.index(f"function hydrateS{index}(")
        end = html.index("\n}\n", start)
        assert f"'s{index}Gate'" in html[start:end], (
            f"hydrateS{index}() never writes its gate banner"
        )


def test_ui_source_picker_prefers_the_bundles_own_transcript():
    """The S2 picker must not hardcode which corpus file is 'the' transcript."""
    html = HTML_PATH.read_text(encoding="utf-8")
    assert "STG-7'" not in html, (
        "the S2 transcript picker prefers a hardcoded source id; "
        "derive it from the bundle's segment source_uri instead"
    )
    assert "function preferredTranscript()" in html


def test_tool_panels_read_required_args_from_the_json_schema():
    """`Tool` has no `.required` field — the list lives on its JSON Schema.

    Reading ``tool.required`` yields ``undefined``, so no seed value is applied
    for required arguments and the panel silently submits an incomplete call.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    assert "tool.required" not in html, (
        "the Tool model has no `required` attribute — read "
        "`tool.parameters.required` instead"
    )
    assert re.search(r"tool\.parameters[\s\S]{0,24}\.required", html), (
        "required tool arguments must be read from tool.parameters.required"
    )


def test_s2_gate_counts_the_bundle_not_the_browsed_transcript():
    """S2 must describe the violation, never the corpus file the picker shows.

    The transcript picker browses a whole rendered transcript (STG-*: ~180
    segments) while the bundle anchors only the segments it cites. Deriving the
    gate from `state.activeTranscript` therefore reported a number the violation
    JSON never contained.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    start = html.index("function hydrateS2(")
    body = html[start:html.index("\n}\n", start)]
    assert "state.activeTranscript" not in body, (
        "hydrateS2() must not derive its gate from the browsed transcript"
    )
    assert "citedSegmentIds(" in body, (
        "the S2 gate must report how many segments the bundle actually cites"
    )

    assert "function citedSegmentIds(" in html
    cited = html[html.index("function citedSegmentIds("):]
    cited = cited[:cited.index("\n}\n")]
    assert "proof_evidence_segments" in cited and "nexus_matrix" in cited, (
        "cited segments come from the element grid AND the nexus matrix"
    )


def test_transcript_picker_prefers_the_bundle_over_its_boot_default():
    """A bundle's own source wins unless the user picked a transcript.

    `hydrateSourceSelectors()` runs on every step switch, so without an explicit
    "the user chose this" flag the boot default (the first corpus entry) keeps
    winning and the picker never follows the loaded bundle.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    assert "state.transcriptChosen" in html, (
        "an explicit pick must be distinguished from the boot default"
    )
    start = html.index("function hydrateSourceSelectors(")
    body = html[start:html.index("\n}\n", start)]
    assert "transcriptChosen" in body and "preferredTranscript()" in body
    assert "if (id === 's2') { hydrateSourceSelectors(); hydrateS2(); }" in html, (
        "the picker must re-hydrate once the bundle is loaded"
    )


def test_every_hydration_target_exists_in_the_markup():
    """A hydrator writing to an id that is not in the markup is a silent no-op.

    The S7/S9/S13 gate banners were missing exactly this way: the JS "worked",
    nothing threw, and the step kept showing its static placeholder forever.
    Comparing the two sets makes that a red test instead of a cosmetic surprise.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    declared = set(re.findall(r'\bid="([A-Za-z0-9_-]+)"', html))
    targets = set()
    for helper in ("setText", "setInput", "setHtml", "setGate", "fillSelect"):
        targets |= set(re.findall(rf"\b{helper}\(\s*'([A-Za-z0-9_-]+)'", html))
    assert targets, "no hydration targets matched — the scan pattern went stale"
    assert targets <= declared, (
        "hydration targets with no matching element: "
        f"{sorted(targets - declared)}"
    )


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
