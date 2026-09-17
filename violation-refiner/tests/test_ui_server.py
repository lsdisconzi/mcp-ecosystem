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

import base64
import hashlib
import json
import re
import shutil
import subprocess
import threading
import time
from html.parser import HTMLParser
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="needs the [mcp] extra")
pytest.importorskip("httpx", reason="needs httpx for the Starlette TestClient")

from starlette.testclient import TestClient  # noqa: E402

from violation_pack.config import Settings  # noqa: E402
from violation_pack.mcp_server import build_server  # noqa: E402
from violation_pack.ui_server import (  # noqa: E402
    UI_FILENAME,
    _resolve_framework_uri,
    _resolve_transcript_uri,
    bundle_jurisdiction,
    describe_schema,
    describe_settings,
    describe_tools,
    discover_bundle,
    discover_framework_article,
    discover_sources,
    discover_transcript,
    browse_workspace,
    discover_bundles,
    find_ui_path,
    framework_article_reason,
    framework_uri_reason,
    is_bundle_dir,
    probe_runtime,
    transcript_uri_reason,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = REPO_ROOT / "ui" / UI_FILENAME

#: API routes the bridge promises. `/health` is MCP-owned and asserted too.
EXPECTED_API_ROUTES = {"/", "/api/health", "/api/tools", "/api/tool", "/api/tool-job", "/api/catalog", "/api/sources", "/api/source-transcript", "/api/framework-article", "/api/browse", "/api/bundles", "/api/bundle", "/api/schema", "/api/settings", "/api/authority-source", "/api/authority-source/delete", "/api/authority-source/reading"}


@pytest.fixture(scope="module")
def server():
    return build_server()


@pytest.fixture(autouse=True)
def _clean_jobs_and_progress():
    """Reset the two process-wide slots around every test.

    `/api/tool` refuses a second call while one is running, and both the registry
    and the progress slot live at module scope — so a test that leaves a job
    "running" (a `TestClient` that exits before its `create_task` ever ran) would
    make every later test see a busy server, and mid-flight assertions would pass
    for the wrong reason.
    """
    from violation_pack import progress, ui_server

    progress._slot.clear()
    ui_server._JOBS.clear()
    ui_server._JOB_ORDER.clear()
    yield
    progress._slot.clear()
    ui_server._JOBS.clear()
    ui_server._JOB_ORDER.clear()


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


def _js_function(name: str) -> str:
    """The source of one top-level ``function name(...) { ... }`` from the page.

    Brace-matched rather than cut at the first blank line: these bodies nest
    blocks, so a `\\n}\\n` split works only until a nested brace reaches column
    zero, at which point the helper would silently return half a function and
    every assertion on it would pass for the wrong reason.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    match = re.search(rf"^(?:async )?function {re.escape(name)}\(", html, re.M)
    assert match, f"{name}() is not defined at top level in the UI page"
    # The *body* brace, not the first brace on the line: a default argument like
    # `opts = {}` opens and closes before the body does, and starting the depth
    # count there returns the signature alone — every assertion on it then passes
    # for the wrong reason. Skip the parameter list first.
    paren = html.index("(", match.start())
    depth = 0
    for i in range(paren, len(html)):
        if html[i] == "(":
            depth += 1
        elif html[i] == ")":
            depth -= 1
            if depth == 0:
                break
    opening = html.index("{", i)
    depth = 0
    for i in range(opening, len(html)):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                return html[match.start() : i + 1]
    raise AssertionError(f"unbalanced braces in {name}()")


def _js_const(name: str) -> str:
    """The source of one top-level ``const name = ...;`` declaration from the page.

    Cut at the first end-of-line `;`, which is how the page's simple (single
    expression) constants are written. A restated copy of one of these in a test
    would defeat the point — the tests exist to check the page's own string — so
    the declaration is pulled from the file, like `_js_function` does.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    match = re.search(rf"^const {re.escape(name)} = .*?;\n", html, re.M | re.S)
    assert match, f"const {name} is not declared at top level in the UI page"
    return match.group(0)


def _run_js(script: str):
    """Evaluate a snippet under node and return its `console.log(JSON)` payload.

    Half of this page is arithmetic over server payloads, and a regex over the
    source cannot tell `'a' + stem` from `'a' + stem.toUpperCase()`. Running the
    extracted function is the only way to assert what it *computes*; the tests
    that do are skipped where node is unavailable rather than silently passing.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed, so the page's JS cannot be executed")
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, f"node failed:\n{done.stdout}\n{done.stderr}"
    return json.loads(done.stdout)


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
    # Parity with the render on disk, not a pinned count: the corpus grows
    # (27 -> 29 on 2026-09-13) and a magic number fails on every new transcript
    # while still missing a one-sided gap.
    rendered = {
        p.name for p in (REPO_ROOT / "data" / "transcripts" / "html").glob("*.html")
    }
    assert {t["name"] for t in payload["transcripts"]} == rendered
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


# ---------------------------------------------------------------------------
# The canonical corpus is a tree of symlinks.
#
# `test_discover_transcript_returns_parsed_segments` above only exercises the
# HTML render, which is made of real files. Every `data/transcripts/json/*.json`
# is a *symlink* into `transcription/data/transcripts/`, so a resolver that
# followed the link before testing containment rejected the entire canonical
# corpus with a 400 while the render passed — the segment browser came up empty
# and it looked like a UI bug. These tests pin the JSON path and the traversal
# guard together, so neither can be fixed by breaking the other.
# ---------------------------------------------------------------------------

def test_canonical_json_transcript_is_resolved_through_its_symlink():
    """The symlink is the layout, not an escape — resolving it must work."""
    from tests.test_sources_json import FIRST

    rel = f"data/transcripts/json/{FIRST}.json"
    on_disk = REPO_ROOT / rel
    assert on_disk.is_file(), "canonical corpus fixture moved"
    assert on_disk.is_symlink(), (
        "the canonical corpus is no longer symlinked; revisit whether the "
        "lexical containment check in _resolve_transcript_uri is still needed"
    )

    resolved = _resolve_transcript_uri(rel)
    assert resolved is not None, "a symlinked corpus file must resolve"
    # Deliberately *not* the symlink target: callers key bundles and manifests
    # off the corpus-relative name, so the unresolved corpus path is the contract.
    assert resolved == on_disk
    assert resolved.samefile(on_disk.resolve())


def test_discover_transcript_returns_canonical_json_segments():
    """The JSON branch of `discover_transcript` was untested; it 400'd for real."""
    from tests.test_sources_json import FIRST

    uri = f"data/transcripts/json/{FIRST}.json"
    payload = discover_transcript(uri)
    assert payload is not None
    assert payload["kind"] == "json"
    assert payload["authoritative"] is True
    # The id that the manifest and the violation JSON both prefix their
    # `segment_id`s with — an HTML read would report a display label instead.
    assert payload["source_id"] == FIRST
    assert payload["segment_count"] > 0
    assert payload["segments"][0]["segment_id"].startswith("seg-")
    assert payload["sha256"]
    # Present for the canonical reader, absent from the render's payload.
    assert payload["reviewed_count"] >= 0
    assert "participants" in payload


def test_transcript_uri_still_refuses_traversal_and_subdirectories():
    """Lexical containment must not have been traded away for the symlink fix."""
    for uri in (
        "/etc/passwd",
        "etc/passwd",
        "data/transcripts/json/../../../etc/passwd",
        "data/transcripts/json/../../html/x.html",
        "data/transcripts/json/sub/x.json",
        "data/transcripts/json",
        "data/transcripts/json/..",
        "data/transcripts/json/x.txt",
        "data/transcripts/other/x.json",
    ):
        assert _resolve_transcript_uri(uri) is None, uri
    # An in-corpus symlink whose target does not exist is not a file.
    assert _resolve_transcript_uri("data/transcripts/json/missing.json") is None


def test_transcript_uri_refuses_shapes_that_normpath_would_otherwise_absorb():
    """The cases the shape test alone is load-bearing for.

    Dropping the shape test leaves the other assertions above still passing,
    because those URI forms are refused for unrelated reasons (a missing file,
    an unknown extension). These three normpath *back onto a real transcript*,
    so without the shape test they resolve to a genuine file — a URI that
    visibly walks out of the corpus silently reading a top-level transcript.
    """
    from tests.test_sources_json import FIRST

    name = f"{FIRST}.json"
    for uri in (
        f"data/transcripts/json/sub/../{name}",
        f"data/transcripts/json/../../transcripts/json/{name}",
        f"data/transcripts/json/../json/{name}",
    ):
        # Guard the guard: if these ever stop collapsing onto a real file, the
        # test would go vacuous the same way the earlier assertions did.
        collapsed = REPO_ROOT / "data" / "transcripts" / "json" / name
        assert collapsed.is_file(), "the collapse target must exist for this to bite"
        assert _resolve_transcript_uri(uri) is None, uri
        assert "directly inside" in transcript_uri_reason(uri)


def test_transcript_uri_reason_names_the_actual_cause():
    """One opaque 400 for 'unresolvable' and 'unparseable' hid this bug."""
    assert transcript_uri_reason("") == "no uri was supplied"
    assert "does not exist" in transcript_uri_reason("data/transcripts/json/nope.json")
    assert "absolute" in transcript_uri_reason("/etc/passwd")
    assert "must start with data/transcripts/" in transcript_uri_reason("etc/passwd")
    assert "unsupported transcript extension" in transcript_uri_reason(
        "data/transcripts/json/x.txt"
    )
    assert "directly inside" in transcript_uri_reason("data/transcripts/json/sub/x.json")
    # Unique to this bug's shape: resolves fine, and says so rather than
    # blaming the uri.
    from tests.test_sources_json import FIRST

    assert transcript_uri_reason(f"data/transcripts/json/{FIRST}.json") == (
        "the transcript was found but its reader could not parse it"
    )


def test_api_source_transcript_error_distinguishes_the_cause(client):
    found = client.get(
        "/api/source-transcript", params={"uri": "data/transcripts/json/absent.json"}
    )
    assert found.status_code == 400
    assert "does not exist" in found.json()["error"]
    assert found.json()["uri"] == "data/transcripts/json/absent.json"

    escaped = client.get("/api/source-transcript", params={"uri": "/etc/passwd"})
    assert escaped.status_code == 400
    assert "absolute" in escaped.json()["error"]


def test_api_source_transcript_serves_the_canonical_corpus(client):
    """End-to-end over HTTP, the way the segment browser asks for it."""
    from tests.test_sources_json import FIRST

    res = client.get("/api/source-transcript", params={"uri": f"data/transcripts/json/{FIRST}.json"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["source_id"] == FIRST
    assert body["authoritative"] is True
    assert body["segments"], "the browser has nothing to render"


# The S3 article picker reads a bundle's own framework cache. `build/CL-030`
# is a real bundle whose `Legal framework/*.md` are per-file symlinks into
# `transcription/data/law/`, so these tests double as the symlink regression
# guard: a `.resolve()`-based containment check refuses every one of them.
FRAMEWORK_URI = "build/CL-030/Legal framework/CPCL.md"


def test_framework_article_body_is_taken_from_the_bundle_cache():
    """The body must be a byte-exact substring of the cached framework text —
    that is the property `build_norms_layer_tool` validates an excerpt on, so a
    fairly-read body that is not a substring would be worse than none."""
    payload = discover_framework_article(FRAMEWORK_URI, "255")
    assert payload is not None
    assert payload["ok"] is True
    assert payload["framework_code"] == "CPCL"
    assert payload["article"] == "255"
    cache_text = (REPO_ROOT / FRAMEWORK_URI).read_text(encoding="utf-8")
    assert payload["body"] in cache_text
    assert "El empleado publico" in payload["body"]


def test_framework_article_body_drops_the_metadata_block():
    payload = discover_framework_article(FRAMEWORK_URI, "255")
    assert "**ELI ID:**" not in payload["body"]
    assert "**Hierarchy:**" not in payload["body"]


def test_framework_article_id_comes_from_the_cache_declaration():
    """The hierarchy segments are not derivable from the article number, so the
    id has to be read, not rebuilt: '412' alone cannot yield 'T2.P6'."""
    assert discover_framework_article(FRAMEWORK_URI, "412")["article_id"] == "CL.CPCL.T2.P6.Art.412"
    assert (
        discover_framework_article(FRAMEWORK_URI, "494 N 16")["article_id"]
        == "CL.CPCL.C1.Art.494.16"
    )
    # An ELI id and a header identifier differ only in spacing, and both resolve
    # to the same article.
    spaced = discover_framework_article(FRAMEWORK_URI, "269 ter")
    underscored = discover_framework_article(FRAMEWORK_URI, "269_ter")
    assert spaced["article_id"] == underscored["article_id"] == "CL.CPCL.C1.Art.269_ter"
    assert spaced["body"] == underscored["body"]


def test_framework_article_carries_the_title_and_hashes():
    payload = discover_framework_article(FRAMEWORK_URI, "255")
    assert payload["article_name"] == "Vejaciones injustas por empleado publico"
    assert len(payload["body_sha256"]) == 64
    # The cache's own sha, so the UI can show the text it read is the recorded one.
    assert len(payload["cache_sha256"]) == 64
    assert payload["articles"] == ["17", "94", "255", "269 ter", "412", "416", "494 N 16"]


def test_framework_uri_refuses_anything_outside_a_bundle_cache():
    """Only the bundle's own `Legal framework/<name>.md` is addressable. A
    discovered-but-uncached framework under `data/law/` is refused on purpose:
    the bundle does not carry it, so an excerpt read from it could never pass
    validation."""
    assert _resolve_framework_uri(FRAMEWORK_URI) is not None
    for refused in (
        "",
        "/etc/passwd",
        "../build/CL-030/Legal framework/CPCL.md",
        "build/CL-030/Legal framework/../../CPCL.md",
        "build/CL-030/Legal framework/sub/CPCL.md",
        "build/CL-030/other/CPCL.md",
        "build/CL-030/Legal framework/CPCL.txt",
        "data/law/CL/CodigoPenal.md",
        "build/not a bundle/Legal framework/CPCL.md",
        "build/CL-030/Legal framework/absent.md",
    ):
        assert _resolve_framework_uri(refused) is None, refused


def test_framework_uri_reason_agrees_with_the_resolver():
    """A reason that disagrees with the resolver sends the reader after the
    wrong cause — the mismatch that hid the transcript containment bug."""
    assert framework_uri_reason("") == "no uri was supplied"
    assert "absolute" in framework_uri_reason("/etc/passwd")
    assert "directly inside" in framework_uri_reason("build/CL-030/other/CPCL.md")
    assert "unsupported framework extension .txt" in framework_uri_reason(
        "build/CL-030/Legal framework/CPCL.txt"
    )
    assert "not a bundle id" in framework_uri_reason("build/not a bundle/Legal framework/CPCL.md")
    assert "does not exist" in framework_uri_reason("build/CL-030/Legal framework/absent.md")
    # Resolvable, but the article is not one the cache holds: this is the second
    # cause that must not be collapsed into the first.
    reason = framework_article_reason(FRAMEWORK_URI, "999")
    assert "not one of the 7 article(s)" in reason
    assert "255" in reason
    assert framework_article_reason(FRAMEWORK_URI, "") == "no article number was supplied"
    # A caller that asks why an article could not be read must get the *uri*
    # cause forwarded, not one generic sentence covering both causes — that is
    # exactly how the transcript containment bug stayed hidden behind a 400.
    assert "absolute" in framework_article_reason("/etc/passwd", "255")
    assert "does not exist" in framework_article_reason(
        "build/CL-030/Legal framework/absent.md", "255"
    )


def test_api_framework_article_serves_the_bundle_cache(client):
    res = client.get(
        "/api/framework-article", params={"uri": FRAMEWORK_URI, "article": "255"}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["article_id"] == "CL.CPCL.C1.Art.255"
    assert body["body"].startswith("El empleado publico")


def test_api_framework_article_error_distinguishes_the_cause(client):
    missing_article = client.get(
        "/api/framework-article", params={"uri": FRAMEWORK_URI, "article": "999"}
    )
    assert missing_article.status_code == 400
    assert "not one of the" in missing_article.json()["error"]

    escaped = client.get(
        "/api/framework-article", params={"uri": "/etc/passwd", "article": "255"}
    )
    assert escaped.status_code == 400
    assert "absolute" in escaped.json()["error"]


def test_s3_article_chips_are_buttons_wired_to_the_picker():
    """They were inert `<span class="chip">Art. 255</span>` labels, which made
    the block's instruction to 'select an article' describe behaviour that did
    not exist."""
    html = HTML_PATH.read_text(encoding="utf-8")
    assert 'data-action="pick-article"' in html
    # The handler must *record* the pick, not merely read it: the chip stays
    # highlighted across re-hydrations only because the pick is stored.
    assert re.search(r"state\.pickedArticle\s*=", html)
    assert "API.frameworkArticle" in html
    assert '<span class="chip">Art. ' not in html


def test_s3_pick_and_fields_share_one_validity_rule():
    """The chips remember the pick, so the excerpt/id fields must be re-decided
    from the same rule on every re-render — otherwise a re-hydration leaves a
    chip highlighted above a *different* article's excerpt."""
    html = HTML_PATH.read_text(encoding="utf-8")
    # Both the chip highlighting and the fields ask the same helper. Anchored on
    # the call sites: `pickedArticleFor\(code, articles\)` alone also matches the
    # function's own signature, which would make this guard unfalsifiable.
    assert re.search(r"const pickedHere = pickedArticleFor\(code, articles\)", html), \
        "chips bypass the rule"
    assert re.search(r"const picked = pickedArticleFor\(code, cached\)", html), \
        "fields bypass the rule"
    # Re-hydration re-reads the pick through the chip's own call.
    assert re.search(r"pickFrameworkArticle\(picked\);", html)
    assert re.search(r"syncFramework\(\);\s*\n\s*renderArticle\(\);", html), "hydrate skips the fields"
    # Changing framework changes which articles exist, so the fields follow.
    assert re.search(r"select\.onchange = \(\) => \{[^}]*renderArticle\(\)", html)


def test_derived_s3_and_s13_fields_are_read_only():
    """Framework code and article id are derived, never typed. `readonly` (not
    `disabled`) keeps the value selectable and keeps it in form collection, so
    `readStepForm()` still sees it."""
    html = HTML_PATH.read_text(encoding="utf-8")
    for field_id in ("s3FrameworkCode", "s3ArticleId", "s13FrameworkCode", "s2SourceId"):
        match = re.search(
            r'<div class="field readonly">\s*<label>[^<]*</label>\s*'
            r'<input id="' + field_id + r'"[^>]*readonly',
            html,
        )
        assert match, f"{field_id} is not a read-only field"
    # The `*` marker invites typing, so a derived field must not carry one.
    for label in ("Framework code", "Article ID", "Source ID"):
        assert f'<label>{label} <span class="req">*</span></label>' not in html


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
    """``data/law`` is a symlink out of the workspace.

    (The HTML render was vendored in-tree on 2026-09-13, so
    ``data/transcripts/html`` is now a real directory; ``data/law`` still leaves
    the repo.) Resolving before checking containment made the symlink
    unreachable — ``data/law`` was refused silently for as long as it has
    existed, with no test covering it.
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
    rendered = list((REPO_ROOT / "data" / "transcripts" / "html").glob("*.html"))
    assert len([e for e in html["entries"] if e["name"].endswith(".html")]) == len(
        rendered
    )
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
    assert "CL-005" in ids
    by_id = {bundle["id"]: bundle for bundle in payload["bundles"]}
    assert by_id["CL-005"]["file_count"] > 0


def test_discover_bundles_lists_every_real_bundle_on_disk():
    """Disk is the source of truth — a name filter must not hide bundles.

    A ``CL-\\d+`` test used to gate this list, which silently dropped every BR
    bundle, every INT bundle and non-numeric CL ids such as ``CL-f7dd941e``. An
    equivalence against the directory tree fails loudly if that returns.
    """
    root = REPO_ROOT / "build"
    on_disk = {
        path.name for path in root.iterdir()
        if path.is_dir() and (path / f"{path.name}.json").is_file()
    } if root.is_dir() else set()
    listed = {bundle["id"] for bundle in discover_bundles()["bundles"]}
    assert on_disk == listed


def test_discover_bundles_reports_a_derived_jurisdiction_per_bundle():
    payload = discover_bundles()
    for bundle in payload["bundles"]:
        assert bundle["jurisdiction"] == bundle["id"].split("-", 1)[0]
    assert payload["jurisdictions"] == sorted(set(payload["jurisdictions"]))


def test_bundle_jurisdiction_is_derived_not_mapped():
    assert bundle_jurisdiction("CL-001") == "CL"
    assert bundle_jurisdiction("BR-020") == "BR"
    assert bundle_jurisdiction("INT-019") == "INT"
    # The code must not assume a 2-letter jurisdiction or a numeric local id.
    assert bundle_jurisdiction("CL-f7dd941e") == "CL"
    assert bundle_jurisdiction("nodash") == ""


def test_is_bundle_dir_requires_the_named_payload(tmp_path):
    empty = tmp_path / "CL-001"
    empty.mkdir()
    # A directory that merely looks like a bundle is the remains of an
    # interrupted run, not a bundle.
    assert not is_bundle_dir(empty)
    (empty / "CL-001.json").write_text("{}", encoding="utf-8")
    assert is_bundle_dir(empty)
    # A payload named for a different id is not this directory's payload.
    other = tmp_path / "BR-001"
    other.mkdir()
    (other / "BR-002.json").write_text("{}", encoding="utf-8")
    assert not is_bundle_dir(other)


def test_discover_bundle_accepts_every_jurisdiction():
    """One id per jurisdiction shape, including a non-numeric local id."""
    for bundle_id in ("CL-005", "CL-f7dd941e", "BR-001", "INT-001"):
        payload = discover_bundle(bundle_id)
        assert payload is not None, bundle_id
        assert payload["violation_id"] == bundle_id
        assert payload["path"] == f"build/{bundle_id}"


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
    # The endpoint must report the SAME resolved values the tools use, so
    # compare against Settings rather than literals: these keys are all
    # env-overridable, so a literal pins whatever this machine's .env happens
    # to hold (the Aura deployment renames neo4j_database to the instance id).
    settings = Settings.from_env()
    assert body["settings"]["qdrant_collection_prefix"] == settings.qdrant_collection_prefix
    assert body["settings"]["neo4j_database"] == settings.neo4j_database
    assert (
        body["settings"]["authority_verification_floor"]
        == settings.authority_verification_floor
    )
    # ...but a bare echo is worthless, so pin the code defaults that hold when
    # nothing overrides them.
    assert settings.qdrant_collection_prefix == "violationrefiner_v1"
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
# Long-running tool calls — the background job path
#
# The MCP SDK invokes *synchronous* tools directly on the event loop
# (`mcp/server/fastmcp/utilities/func_metadata.py` ends in
# `return fn(**arguments_parsed_dict)`), so the whole server — `/api/health`
# included — goes dark for the duration of a call. Measured against the live
# server: a health poll sent 0.02 s into an 8.96 s `enrich_violation_tool` call
# was answered at 8.98 s. A full eight-stage enrichment is minutes, so "show the
# pipeline is running" is impossible while the call owns the loop; the page
# could not even ask. `background: true` moves the call to a worker thread and
# `/api/tool-job` reports on it.
# ---------------------------------------------------------------------------

def _wait_for_job(client, job_id, *, timeout=15.0):
    """Poll `/api/tool-job` until the job leaves `running`."""
    deadline = time.monotonic() + timeout
    body = {"status": "running"}
    while time.monotonic() < deadline:
        body = client.get("/api/tool-job", params={"id": job_id}).json()
        if body["status"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished (last: {body})")


def _start_background(client, name, args=None):
    return client.post(
        "/api/tool",
        json={"name": name, "args": args or {}, "background": True},
    )


def _minimal_bridge(tool_body):
    """A bridge app whose registry holds exactly one tool, defined by the test.

    `enrich_violation_tool` is the only tool that takes minutes, and calling it
    here would need an LLM. What these tests are about is the transport, not the
    enrichment, so they mount a tool that blocks on an event the test controls —
    the only way to hold a job mid-flight and observe the server around it.
    """
    from mcp.server.fastmcp import FastMCP

    from violation_pack.ui_server import build_ui_routes

    app = FastMCP("bridge-test")
    app.tool()(tool_body)
    build_ui_routes(app)
    return app


def test_post_api_tool_background_returns_a_job_id(client):
    res = _start_background(client, "llm_provider_info_tool")
    assert res.status_code == 202
    body = res.json()
    assert body["ok"] is True
    assert body["status"] == "running"
    assert body["tool"] == "llm_provider_info_tool"
    assert body["job_id"]


def test_background_job_reaches_done_with_the_real_result(client):
    job_id = _start_background(client, "llm_provider_info_tool").json()["job_id"]

    done = _wait_for_job(client, job_id)
    assert done["status"] == "done"
    assert done["ok"] is True
    assert done["job_id"] == job_id
    assert done["error"] is None
    assert done["seconds"] >= 0
    # Same payload as the synchronous path: the job changes where the call runs,
    # not what it returns.
    sync = client.post("/api/tool", json={"name": "llm_provider_info_tool", "args": {}})
    assert done["result"] == sync.json()["result"]


def test_a_finished_job_stops_publishing_progress(client):
    """`progress` is a live read, not history — a stale slot on a dead job would
    let the page draw a spinner next to a result that is already in."""
    from violation_pack import progress

    job_id = _start_background(client, "llm_provider_info_tool").json()["job_id"]
    done = _wait_for_job(client, job_id)
    assert "progress" not in done

    # Even with a slot still filled from some other run, `running` is the gate.
    progress.begin("some_other_tool", total=3)
    progress.end("some_other_tool")
    assert "progress" not in _wait_for_job(client, job_id)


def test_api_tool_job_404s_an_unknown_id(client):
    res = client.get("/api/tool-job", params={"id": "nope"})
    assert res.status_code == 404
    assert "Unknown job id" in res.json()["error"]


def test_a_background_job_leaves_the_event_loop_free():
    """The measurement that forced this design, as a test.

    Before the job path the loop was owned by the tool: an 8.96 s call answered
    `/api/health` 8.98 s late, so *nothing* was served in between. Here the tool
    is provably parked mid-call (`entered` is set from inside it) and the server
    still answers both the probe and the poll — and refuses a second run rather
    than interleaving two writers into one bundle.
    """
    released = threading.Event()
    entered = threading.Event()

    def block_tool(tag: str = "x") -> dict:
        """Park until the harness releases it."""
        entered.set()
        released.wait(timeout=10)
        return {"tag": tag}

    client = TestClient(_minimal_bridge(block_tool).streamable_http_app())
    with client:
        try:
            started = _start_background(client, "block_tool", {"tag": "A"})
            assert started.status_code == 202
            job_id = started.json()["job_id"]
            assert entered.wait(timeout=15), "the worker thread never reached the tool"

            # Parked inside the tool. These are only served because the loop is free.
            assert client.get("/api/health").status_code == 200
            live = client.get("/api/tool-job", params={"id": job_id}).json()
            assert live["status"] == "running"
            assert live["ok"] is True
            assert live["result"] is None

            # Double-tap: refused at the server, naming the run in flight.
            busy = _start_background(client, "block_tool", {"tag": "B"})
            assert busy.status_code == 409
            assert busy.json()["busy"] is True
            assert busy.json()["running_tool"] == "block_tool"
            assert busy.json()["job_id"] == job_id

            released.set()
            done = _wait_for_job(client, job_id)
            assert done["status"] == "done"
            assert done["result"] == {"tag": "A"}
            # The slot is genuinely reusable, not merely claimable: the next tap
            # is accepted *and* runs.
            again = _start_background(client, "block_tool", {"tag": "C"})
            assert again.status_code == 202
            assert _wait_for_job(client, again.json()["job_id"])["result"] == {"tag": "C"}
        finally:
            released.set()


def test_a_failing_background_job_reports_the_error():
    """A tool that raises must land in the job.

    `asyncio.create_task` would otherwise leave the exception in a task nobody
    awaits ("Task exception was never retrieved") and the page would poll a job
    that never leaves `running` — a spinner that outlives the failure.
    """
    def boom_tool() -> dict:
        """Always raises."""
        raise ValueError("kaboom")

    client = TestClient(_minimal_bridge(boom_tool).streamable_http_app())
    with client:
        job_id = _start_background(client, "boom_tool").json()["job_id"]
        done = _wait_for_job(client, job_id)
        assert done["status"] == "error"
        # `ok` is this bridge's verdict field everywhere else; a failed job must
        # not be the one response that reports `ok: true`.
        assert done["ok"] is False
        # `ToolManager` wraps whatever the tool raised, so the message — not the
        # type — is what the page has to show.
        assert "Error executing tool boom_tool" in done["error"]
        assert "kaboom" in done["error"]


# ---------------------------------------------------------------------------
# Progress publication — the seam that makes the spinner honest
# ---------------------------------------------------------------------------

def _segment_violation() -> dict:
    """A violation with one segment, so the `segments` stage has work to do."""
    from violation_pack.models import EvidenceSegment, Incident, Violation

    sha = "a" * 64
    return json.loads(
        Violation(
            violation_id="CL-PROGRESS",
            title="Progress publication",
            severity="LOW",
            incident=Incident(date="2025-01-01", location="SCL"),
            segments=[
                EvidenceSegment(
                    segment_id="STG-1.seg-1",
                    role_in_argument="unclassified",
                    audio_offset_start=0.0,
                    audio_offset_end=1.5,
                    speaker="SPK",
                    verbatim_es="no me consta",
                    verbatim_sha256=sha,
                    translation_en="",
                    source_uri="Transcripts/t.html#seg-1",
                    source_sha256=sha,
                )
            ],
        ).model_dump_json()
    )


def test_a_running_job_publishes_the_stage_it_is_on(client, monkeypatch):
    """The seam behind "there should be a clear display that it is running".

    A job id alone tells the page that *something* is in flight; it cannot say
    which of eight stages, and eight stages is minutes. `/api/tool-job` answers
    with whatever `violation_pack.progress` holds, and the slot is filled by the
    `on_stage` hook. Both halves are exercised here against the real bridge and
    the real tool, because either one silently returning nothing looks exactly
    like a slow run.

    The LLM is blocked inside the `segments` stage so the mid-flight state can
    be observed at all — a stage that finished would have moved the slot on.
    """
    entered = threading.Event()
    released = threading.Event()

    class _BlockingLLM:
        def chat_json(self, *, messages, system=None, max_tokens=None):
            entered.set()
            released.wait(timeout=10)
            return {"segments": []}

    monkeypatch.setattr("violation_pack.llm.build_client", lambda **kw: _BlockingLLM())

    started = client.post(
        "/api/tool",
        json={
            "name": "enrich_violation_tool",
            "args": {
                "violation": _segment_violation(),
                "stages": ["segments", "subsections"],
            },
            "background": True,
        },
    )
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    try:
        assert entered.wait(timeout=15), "the enrichment stage never reached the LLM"
        live = client.get("/api/tool-job", params={"id": job_id}).json()
        assert live["status"] == "running"
        assert live["progress"]["tool"] == "enrich_violation_tool"
        assert live["progress"]["stage"] == "segments"
        assert live["progress"]["index"] == 1
        assert live["progress"]["total"] == 2
        assert live["progress"]["running"] is True
    finally:
        released.set()

    done = _wait_for_job(client, job_id)
    assert done["status"] == "done"
    # A finished job carries no progress: a stale slot would let the page draw a
    # spinner next to a result that is already in.
    assert "progress" not in done
    # And the run is not invisible after the fact — one provenance entry per
    # stage is what the S9 panel and the sidebar tick read.
    assert [p["operation"] for p in done["result"]["provenance"]] == [
        "enrich_violation:segments",
        "enrich_violation:subsections",
    ]


def test_a_failing_enrichment_job_records_the_error_in_the_slot(client, monkeypatch):
    """The polling page must be able to tell "failed" from "still going".

    The client fails *inside* the first stage rather than at construction: only
    then has `progress.begin` run, which is the state this test is about — and
    only then does the failure carry the stage label that tells the operator
    which of eight prompts went wrong.
    """
    from violation_pack import progress
    from violation_pack.llm import LLMError

    class _FailingLLM:
        def chat_json(self, *, messages, system=None, max_tokens=None):
            raise LLMError("model did not return valid JSON")

    monkeypatch.setattr("violation_pack.llm.build_client", lambda **kw: _FailingLLM())

    job_id = client.post(
        "/api/tool",
        json={
            "name": "enrich_violation_tool",
            "args": {"violation": _segment_violation(), "stages": ["segments"]},
            "background": True,
        },
    ).json()["job_id"]

    done = _wait_for_job(client, job_id)
    assert done["status"] == "error"
    assert done["ok"] is False
    assert "enrichment stage 'segments'" in done["error"]
    # The slot is closed with the same message, so a poll that lands after the
    # stage label was lost still reports a failure rather than nothing.
    snap = progress.snapshot()
    assert snap["running"] is False
    assert snap["stage"] == "segments"
    assert "model did not return valid JSON" in snap["error"]
    progress._slot.clear()


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


# ---------------------------------------------------------------------------
# The evidence id space
#
# Two corpora ship the same 29 transcripts under different ids: the rendered
# HTML reports a display label (`STG-5`) while the canonical JSON reports the
# `transcript_id` that `segments_manifest.json` and the violation JSON both
# prefix their `segment_id`s with. Reading the render to build the evidence
# layer composes `STG-5.seg-1`, which joins nothing in the pack.
# ---------------------------------------------------------------------------

def test_transcript_reader_dispatches_on_the_files_own_suffix():
    """One loader, two formats — chosen by the artifact, not by the caller.

    `_transcript()` used to hardcode the HTML reader, so the canonical JSON
    corpus was reachable from `/api/source-transcript` but *not* from the tool
    that actually writes the evidence layer.
    """
    from violation_pack.mcp_server import _transcript
    from violation_pack.sources import HtmlTranscriptSource
    from violation_pack.sources_json import JsonTranscriptSource

    from tests.test_sources_json import FIRST

    json_path = REPO_ROOT / "data" / "transcripts" / "json" / f"{FIRST}.json"
    html_path = REPO_ROOT / "data" / "transcripts" / "html" / f"{FIRST}.html"
    assert json_path.is_file() and html_path.is_file(), "corpus fixture moved"

    reader = _transcript(str(json_path), "STG-1", "Transcripts/x.json")
    assert isinstance(reader, JsonTranscriptSource)
    assert isinstance(_transcript(str(html_path), "STG-1", "x.html"), HtmlTranscriptSource)


def test_json_transcript_ignores_the_callers_display_label():
    """A typed `source_id` must not shift the composed id off the collection key.

    The HTML reader needs its label passed in; the JSON reader derives the
    canonical id from the document. Letting the caller's `STG-5` win would
    compose `STG-5.seg-1` — a well-formed id that joins to nothing, which is
    exactly the silent failure this pins.
    """
    from violation_pack.mcp_server import _transcript

    from tests.test_sources_json import FIRST

    json_path = REPO_ROOT / "data" / "transcripts" / "json" / f"{FIRST}.json"
    reader = _transcript(str(json_path), "STG-1", "Transcripts/x.json")
    assert reader.source_id() == FIRST
    composed = {f"{reader.source_id()}.{s['segment_id']}" for s in reader.all_segments()}
    assert f"{FIRST}.seg-0" in composed
    assert not any(c.startswith("STG-1.") for c in composed), (
        "the caller's display label leaked into the composed segment ids"
    )


def test_evidence_ids_join_the_pack_manifest():
    """End-to-end: reader → composed id → the id the manifest declares.

    This is the whole point of the JSON reader. A pack built from the render
    silently anchors nothing; built from the canonical corpus, every manifest
    segment id is reproducible from the corpus file alone.
    """
    import json

    from violation_pack.mcp_server import _transcript

    bundles = sorted((REPO_ROOT / "build").glob("*/segments_manifest.json"))
    if not bundles:
        pytest.skip("no built bundle to compare against")
    manifest = json.loads(bundles[0].read_text(encoding="utf-8"))

    ids = [s["segment_id"] for s in manifest["segments"]]
    by_prefix: dict[str, list[str]] = {}
    for sid in ids:
        prefix, _, local = sid.partition(".")
        by_prefix.setdefault(prefix, []).append(local)

    joined = 0
    for prefix, locals_ in by_prefix.items():
        path = REPO_ROOT / "data" / "transcripts" / "json" / f"{prefix}.json"
        reader = _transcript(str(path), "IGNORED", str(path.relative_to(REPO_ROOT)))
        # The reader reports the transcript-LOCAL id; layers.py composes the
        # scoped one. Reproduce that composition here.
        joined += sum(f"{reader.source_id()}.{local}" in ids for local in locals_)
    assert joined == len(ids), f"only {joined}/{len(ids)} manifest ids are reproducible"


def test_s2_picker_is_fed_by_the_canonical_corpus():
    """Both corpora are published, so the picker must not silently take the render.

    `/api/sources` returns `transcripts` (the display-only HTML render) *and*
    `transcripts_json` (the canonical corpus). Feeding the picker from the first
    meant every marked segment produced a non-joining id.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    assert "function corpusTranscripts(" in html, "the two corpora are never merged"
    merged = html[html.index("function corpusTranscripts("):]
    merged = merged[:merged.index("\n}\n")]
    assert "transcripts_json" in merged and "transcripts" in merged, (
        "corpusTranscripts() must merge both published corpora"
    )

    start = html.index("function hydrateSourceSelectors(")
    body = html[start:html.index("\n}\n", start)]
    assert "corpusTranscripts()" in body, (
        "the picker must be built from the merged corpus list, not the HTML render"
    )
    assert "state.sources.transcripts" not in body, (
        "reading the render list directly is what produced ids that join nothing"
    )

    selected = html[html.index("function selectedTranscript("):]
    selected = selected[:selected.index("\n}\n")]
    assert "corpusTranscripts()" in selected, (
        "the args builder must resolve the pick from the same merged list"
    )


def test_s2_keeps_a_canonical_and_a_rendered_entry_for_each_stem():
    """Merging must be keyed on the file stem, and JSON must win.

    The two corpora share filenames but not id spaces; an unkeyed concat would
    list 58 near-duplicate entries and let the render's label reach the picker.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    merged = html[html.index("function corpusTranscripts("):]
    merged = merged[:merged.index("\n}\n")]
    assert "stemOfFile(" in merged, "the merge key must be the file stem"
    assert "Map(" in merged, "a Map is what makes the JSON entry replace the render"
    assert "authoritative" in merged, "the merged entry must record which corpus won"


def test_s2_parses_the_manifest_the_bridge_already_serves():
    """`discover_bundle()` has always returned the manifest; nothing read it.

    `/api/bundle` ships `manifest.segments` (the canonical id, the legacy vault
    id it was re-anchored from, the role, both texts, the anchor notes) and this
    page ignored the key entirely, so the S2 evidence panel could only ever show
    what the browser picker happened to be looking at.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    assert "function manifestSegments(" in html
    body = html[html.index("function manifestSegments("):]
    body = body[:body.index("\n}\n")]
    assert "state.bundle.manifest" in body, "the manifest must come off the bundle"

    # Join on the id, never on the text: the manifest's `verbatim_es` drops the
    # accents the violation JSON keeps, so a text-equality join reports
    # mismatches for segments that are in fact the same one.
    assert "segment_id" in body
    assert "verbatim_es" in body
    assert "refinement_added_segments" in body, (
        "the refinement-added ids have no vault ancestor; they are the one thing "
        "only the manifest can tell us"
    )
    assert "legacy_segment_id" in body, (
        "the legacy vault id is the manifest's whole reason to exist"
    )


def test_s2_renders_the_manifest_into_its_own_block():
    """A parsed manifest with no markup to land in is a silent no-op.

    The `segments_manifest.json` artifact now has a target in the S2 template
    and a hydrator that writes to it from `hydrateS2()`.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    for target in ("s2ManifestSegments", "s2ManifestSummary", "s2ManifestActions"):
        assert f'id="{target}"' in html, f"the manifest block is missing #{target}"
        assert f"'{target}'" in html, f"nothing hydrates #{target}"

    assert "function hydrateS2Manifest(" in html
    start = html.index("function hydrateS2(")
    body = html[start:html.index("\n}\n", start)]
    assert "hydrateS2Manifest()" in body, (
        "hydrateS2() must render the manifest, or the block stays on its placeholder"
    )
    assert "manifest" in body, "the S2 gate must report the manifest's own drift"


def test_s2_can_seed_specs_from_the_manifest():
    """Seeding is a copy from the manifest, not a guess off the corpus.

    The 30 `refinement_added_segments` ids exist in no transcript file, so a
    corpus-driven seed would silently skip them — and `segment_id` must be sent
    in its LOCAL form (`seg-12`), because `layers.py` composes the scoped id
    from the transcript document itself.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    assert "function seedManifestSpecs(" in html
    assert 'data-action="seed-manifest"' in html, "no control can trigger a seed"
    body = html[html.index("function seedManifestSpecs("):]
    body = body[:body.index("\n}\n")]
    assert "manifestSegments()" in body, "seed from the manifest, not the picker"
    assert "row.local_id" in body, (
        "the tool takes the local segment id; the scoped form is composed by layers.py"
    )
    assert "translation_en: row.translation_en" in body, (
        "the manifest already carries the English rendering — never fall back to "
        "writing the Spanish verbatim into an English field"
    )


def test_evidence_args_carry_only_the_selected_transcripts_specs():
    """`build_evidence_layer_tool` takes ONE transcript per call.

    Specs are keyed by scoped id so marks survive a transcript switch, which
    means the args builder must filter to the picked transcript — sending a
    segment's local id against another transcript composes an id that anchors
    nothing.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    start = html.index("if (tool.name === 'build_evidence_layer_tool')")
    body = html[start:start + 1600]
    assert "startsWith(prefix + '.')" in body, (
        "the args builder must drop specs belonging to other transcripts"
    )
    assert "state.segmentSpecs" in body


def test_marking_a_segment_borrows_the_packs_own_role_and_rendering():
    """A hand-marked segment is a known segment — reuse what the pack recorded.

    The old handler wrote `translation_en: segment.verbatim`, i.e. it put the
    Spanish verbatim into the English field. The manifest and the violation JSON
    already hold the real role and rendering for every cited segment.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    assert "function knownSpecFor(" in html
    start = html.index("// transcript segment marking toggle")
    body = html[start:start + 2000]
    assert "knownSpecFor(" in body
    assert "known.role_in_argument" in body and "known.translation_en" in body
    assert "translation_en: segment.verbatim," not in body, (
        "the Spanish verbatim must not be written into the English field"
    )


# ---------------------------------------------------------------------------
# The element grid's segment columns
#
# The S4 grid used to head its columns with a bare `seg-36`. Nothing on the page
# said which of the 29 recordings that was a segment *of*, and the cells were
# inert `<td>`s, so the one question the grid exists to answer — "what does this
# dot actually prove, and where does it say so?" — could not be asked of it.
# ---------------------------------------------------------------------------

def test_s4_group_headers_name_the_transcript_each_segment_came_from():
    """The column set is the transcripts, and the segments hang beneath them.

    Grouping has to happen on the scoped id's own prefix. Grouping on the
    rendered label instead silently merges `I-002_02_NAR-02_STG_2_boarding_gate`
    and `I-002_18_NAR_LATAM_STG_2` — both of which the render calls `STG-2`.
    """
    body = _js_function("hydrateS4")
    assert "segmentTranscript(" in body, "columns are not scoped to a transcript"
    assert "proof_evidence_segments" in body, (
        "the grid must head the segments it actually links, not the catalogue"
    )
    assert "mx-tr" in body, "no transcript header row is emitted"
    assert "colspan=" in body, "a group header must span exactly its own segments"

    # The group key is the scoped id's prefix and nothing else. Keying on
    # `transcriptLabel(...)` reads as "the same thing, prettier" but produces
    # `05 · STG-7`, which is not a file stem, so every column would then look up
    # a transcript that does not exist.
    assert re.search(r"const t = segmentTranscript\(id\);", body), (
        "the group key must be the scoped id's prefix"
    )
    assert not re.search(r"const t = transcriptLabel\(", body), (
        "the label is display-only: grouping on it merges the two transcripts"
        " the render both calls STG-2"
    )

    # The label is display only: the ids in `data-segment` stay in the scoped
    # form, because that is the only form the corpus and the manifest join on.
    assert "transcriptLabel(" in body
    assert "data-segment=\"${escapeHtml(c)}\"" in body, (
        "the dot must carry the scoped id, never the display label"
    )
    assert 'title="${escapeHtml(c)}"' in body, (
        "the full scoped id belongs in the tooltip, since the label is ambiguous"
    )


def test_segment_scoping_splits_on_the_first_dot_only():
    """`segmentTranscript` is a prefix split, and the tests below depend on it.

    Asserted by execution rather than by reading: the two branches are a
    ternary, and a rewrite that drops the `-1` guard would return the empty
    string for an unscoped id — which groups every such segment under one empty
    header instead of failing loudly.
    """
    result = _run_js(
        _js_function("segmentTranscript")
        + "\nconsole.log(JSON.stringify("
        + json.dumps(
            [
                "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-36",
                "I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-297",
                "seg-1",
                "",
            ]
        )
        + ".map(segmentTranscript)));"
    )
    assert result == [
        "I-002_05_NAR-07_STG_7_post_removal_investigation",
        "I-002_04_NAR-06_STG_6_jetbridge_standoff",
        "seg-1",
        "",
    ]


def test_the_short_transcript_label_is_qualified_because_it_is_not_unique():
    """`STG-2` names two different recordings, so the label carries the ordinal.

    `source_id` is the HTML render's own name for a stage and repeats across the
    LATAM transcripts; the canonical `transcript_id` is the file stem. The grid
    shows the friendly one and keeps the stem in `title`, which only works if
    the friendly one still separates the collision.
    """
    corpus = [
        {"stem": "I-002_05_NAR-07_STG_7_post_removal_investigation", "display_label": "STG-7"},
        {"stem": "I-002_02_NAR-02_STG_2_boarding_gate", "display_label": "STG-2"},
        {"stem": "I-002_18_NAR_LATAM_STG_2", "display_label": "STG-2"},
    ]
    result = _run_js(
        _js_function("segmentTranscript")
        + "\n"
        + _js_function("transcriptLabel")
        + "\nconst corpusTranscripts = () => " + json.dumps(corpus) + ";"
        + "\nconsole.log(JSON.stringify("
        + json.dumps([c["stem"] for c in corpus] + ["I-009_99_absent", "seg-1"])
        + ".map(transcriptLabel)));"
    )
    assert result == ["05 · STG-7", "02 · STG-2", "18 · STG-2", "99 · absent", "seg-1"]
    assert result[1] != result[2], (
        "the two transcripts the render both calls STG-2 now share a header"
    )


def test_s4_dots_and_proof_badges_are_buttons_pointing_at_one_modal():
    """A `<td>` click handler is invisible to the keyboard, so both became buttons.

    The dot is an intersection — it names a segment *and* the element it proves
    — while the badge names the element alone. Both land in the same modal, so
    they must agree on how they spell the payload or one of them opens only half
    the story.
    """
    body = _js_function("hydrateS4")
    assert '<td class="cell-on"><button class="dot-btn"' in body, (
        "the dot must be a real button inside the cell"
    )
    assert '<button class="proof-hit"' in body
    assert "data-action=\"open-segment\"" in body
    assert "data-action=\"open-proof\"" in body

    # Scoped to the dot's own markup. A whole-function search for `data-element`
    # is satisfied by the proof badge, which carries the identical attribute, so
    # it stays green while the dot silently loses the element and opens a modal
    # with a segment but no proof.
    dot = re.search(r'data-action="open-segment"(.*?)>●<', body, re.S)
    assert dot, "the dot's markup moved — re-anchor this guard before trusting it"
    assert "data-element=" in dot.group(1), (
        "the dot must name the element it proves, not just the segment"
    )

    html = HTML_PATH.read_text(encoding="utf-8")
    for action in ("open-segment", "open-proof"):
        # Anchored on the line start, deliberately: `else if (action ===
        # 'open-proof')` still *contains* `if (action === 'open-proof')`, so a
        # substring test passes for a dispatcher that made the dot unreachable.
        branch = re.search(
            rf"\n    if \(action === '{action}'\) \{{(.*?)\n    \}}", html, re.S
        )
        assert branch, f"nothing dispatches {action} as its own branch"
        assert "openEvidenceModal(" in branch.group(1), (
            f"{action} does not reach the shared modal"
        )


def test_s4_modal_prefers_the_corpus_and_never_touches_the_s2_picker():
    """One read order, stated once: corpus, then the bundle's own two records.

    `state.activeTranscript` is S2's form state. Reading a segment through it
    would move the picker every time a modal opened, so the modal keeps its own
    cache — asserted here, because the shared state is the obvious thing to
    reach for and the bug is invisible until someone is mid-edit in S2.
    """
    detail = _js_function("segmentDetail")
    assert "loadTranscriptDocument(" in detail, "the corpus is not consulted first"
    assert detail.index("loadTranscriptDocument(") < detail.index(
        "the violation JSON — the corpus text was unreachable"
    ) < detail.index("segments_manifest.json — the corpus text was unreachable"), (
        "the fallback ladder is out of order: the manifest drops accents and must"
        " never be preferred to the violation JSON"
    )
    assert "state.activeTranscript" not in detail
    assert "state.activeTranscript" not in _js_function("loadTranscriptDocument")
    assert "state.activeTranscript" not in _js_function("openEvidenceModal")

    loader = _js_function("loadTranscriptDocument")
    assert "state.transcriptDocs" in loader, (
        "the modal must cache whole documents outside S2's state"
    )
    assert "await API.transcript(" in loader, "the modal must read through the bridge"


def test_s4_drift_check_ignores_padding_but_keeps_real_differences():
    """A raw `!==` flags 2 of CL-030's segments for a trailing space.

    The corpus trims every segment; the bundle's `verbatim_es` keeps the space.
    Measured across every bundle in `build/`: 7189 segments agree byte for byte
    and only 2 disagree, both of them by whitespace alone — and one of them is
    reachable from the S4 grid, so an unnormalised check puts a "this is
    disputed" banner on a segment that says exactly the same thing in both
    records.

    Run, not read: the defect lives in the *result* of the comparison, and the
    two directions below are what separate a normaliser from a `replace` that
    truncates.
    """
    stem = "I-002_04_NAR-06_STG_6_jetbridge_standoff"
    scoped = f"{stem}.seg-300"
    corpus_text = "Porque si picó con una pregunta Puede decidir De atrasar el vuelo"

    harness = "\n".join(
        [
            _js_function("segmentTranscript"),
            _js_function("localSegmentId"),
            "const state = { bundle: null, transcriptDocs: {}, violation: { segments: [",
            f"  {{ segment_id: {json.dumps(scoped)},"
            " verbatim_es: JSON.parse(process.argv[1]) },",
            "] } };",
            f"const corpusTranscripts = () => [{{ stem: {json.dumps(stem)},"
            f" name: {json.dumps(stem + '.json')}, uri: 'stub' }}];",
            "const manifestSegments = () => null;",
            "const loadTranscriptDocument = async () => ({ segments: [",
            f"  {{ segment_id: 'seg-300', verbatim: {json.dumps(corpus_text)} }}] }});",
            _js_function("segmentDetail"),
            f"(async () => console.log(JSON.stringify(await segmentDetail({json.dumps(scoped)}))))();",
        ]
    )

    def detail_for(violation_text: str) -> dict:
        node = shutil.which("node")
        if not node:
            pytest.skip("node is not installed, so the page's JS cannot be executed")
        # The disputed text goes in through argv so the harness stays a literal.
        # Verified on this node: with `-e` the payload lands at argv[1] (`node -e
        # code -- x` and `node -e code x` both give [node, 'x']), and the index
        # is asserted below because a wrong one throws inside JSON.parse with a
        # message that never mentions argv.
        done = subprocess.run(
            [node, "-e", harness, json.dumps(violation_text)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert "is not valid JSON" not in done.stderr, (
            "the node argv layout changed: " + done.stderr
        )
        assert done.returncode == 0, "node failed: " + done.stdout + done.stderr
        return json.loads(done.stdout)

    padded = detail_for(corpus_text + " ")
    assert padded["verbatim"].endswith("vuelo"), "the corpus text must win the read"
    assert padded["differs_from_violation"] is False, (
        "a trailing space is not a second transcription of the same segment"
    )

    real = detail_for(corpus_text.replace("atrasar", "retrasar"))
    assert real["differs_from_violation"] is True, (
        "a changed word must still be reported, or the normaliser ate the check"
    )

    # Computing the flag is not the feature; showing it is. A `+ (false` in the
    # modal would leave every assertion above green, so the consumer is named.
    assert "d.differs_from_violation" in _js_function("openEvidenceModal"), (
        "the drift flag never reaches the modal, so the two reads can never be"
        " compared by the person who has to decide"
    )


# ---------------------------------------------------------------------------
# Naming a segment in a dropdown (S5)
# ---------------------------------------------------------------------------

def test_a_segment_option_names_its_transcript_because_the_local_id_is_not_unique():
    """`seg-11` exists in every transcript, so the local id alone is not a label.

    Measured on `build/CL-030`: 34 unique nexus `fact_id`s drawn from 5
    transcripts, and `seg-11` is in two of them (`05 · STG-7` and `03 · STG-5`).
    The picker showed the same text twice, which makes choosing a coin flip —
    and the two rows are different parts of the recording, so picking the wrong
    one silently attributes the fact to another witness.

    Executed, not read: the label is composed from three other functions whose
    interaction (incidence, rendered label, local tail) a regex cannot verify.
    """
    stg7 = "I-002_05_NAR-07_STG_7_post_removal_investigation"
    stg5 = "I-002_03_NAR-05_STG_5_aircraft_removal"
    no_render = "I-002_09_NAR-19_STG_9_no_render"
    script = "\n".join([
        _js_function("segmentTranscript"),
        _js_function("localSegmentId"),
        "const corpusTranscripts = () => [",
        f"  {{ stem: {json.dumps(stg7)}, display_label: 'STG-7' }},",
        f"  {{ stem: {json.dumps(stg5)}, display_label: 'STG-5' }},",
        f"  {{ stem: {json.dumps(no_render)}, display_label: null }},",
        "];",
        _js_function("transcriptLabel"),
        _js_function("segmentOptionLabel"),
        "const ids = [",
        f"  {json.dumps(stg7 + '.seg-36')},",
        f"  {json.dumps(stg7 + '.seg-11')},",
        f"  {json.dumps(stg5 + '.seg-11')},",
        f"  {json.dumps(no_render + '.seg-7')},",
        "  'seg-1',",
        "  '',",
        "];",
        "console.log(JSON.stringify(ids.map(segmentOptionLabel)));",
    ])
    labels = _run_js(script)

    assert labels[0] == "05 · STG-7 · seg-36"
    assert labels[1] == "05 · STG-7 · seg-11"
    assert labels[2] == "03 · STG-5 · seg-11"
    assert labels[1] != labels[2], (
        "the same local id in two transcripts renders identically, so the picker"
        " is back to being a coin flip"
    )
    # Without a render to borrow a short id from, the incidence still heads the
    # label — the exact tail prose is not pinned, only the contract.
    assert labels[3].startswith("09 · ") and labels[3].endswith(" · seg-7"), labels[3]
    assert labels[4] == "seg-1", "an unscoped id must not become `seg-1 · seg-1`"
    assert labels[5] == ""


def test_the_s5_fact_picker_and_its_rows_name_the_transcript():
    """Both surfaces that show a `fact_id`, and the value stays the scoped id.

    The label is display only: the tool is handed the full
    `<transcript_id>.seg-N`, because that is the only form that joins the
    manifest. A picker that displayed the qualified text but submitted the
    shortened one would look fixed and write nothing.
    """
    body = _js_function("hydrateS5")
    assert "{ value: f, label: segmentOptionLabel(f) }" in body, (
        "the fact picker went back to the bare local id"
    )
    # Scoped to the picker's own statement: `label: shortId(n.element_id)` is the
    # *element* picker, and element ids are not segments — asserting over the
    # whole of hydrateS5 would fail on a use that is correct.
    fact_line = [ln for ln in body.splitlines() if "segmentOptionLabel(f)" in ln]
    assert len(fact_line) == 1, "the fact picker's mapping is no longer one statement"
    assert "shortId(" not in fact_line[0], "the picker is labelling with shortId()"
    assert "value: segmentOptionLabel(" not in fact_line[0], (
        "the shortened label must never be the submitted value"
    )
    assert "segmentOptionLabel(n.fact_id)" in body, (
        "the rendered nexus rows still show an unqualified segment"
    )
    assert body.count("segmentOptionLabel(") == 2, (
        "one use of the helper was added but the other surface was missed"
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


def test_the_run_indicator_elements_exist_in_the_markup():
    """The banner and the step-local track are written by id, so a rename would
    leave `setText`/`setHidden` silently no-op and the run would look frozen."""
    html = HTML_PATH.read_text(encoding="utf-8")
    for element_id in ("runBanner", "runBannerText", "runBannerElapsed",
                       "enrichProgressWrap", "enrichProgressFill", "enrichProgressLabel"):
        assert f'id="{element_id}"' in html, f"#{element_id} is missing from the markup"
    # The banner starts hidden: an empty accent strip on every page load would
    # read as a stalled run.
    assert re.search(r'id="runBanner"[^>]*\bhidden\b', html)


def test_the_s9_run_filter_matches_the_hook_and_nothing_else():
    """Executed, not regexed: this filter is why the counter sat at zero.

    `enrich_violation` wrote no provenance of its own, so every operation string
    in the corpus was scanned for `/enrich/i` and none matched (0 of 493 entries
    across 81 bundles). Now the hook writes `enrich_violation:<stage>`, and the
    filter must key on that — an operation that merely mentions enrichment is a
    different thing from a stage that ran.
    """
    script = "\n".join([
        _js_const("ENRICH_OP_PREFIX"),
        _js_function("enrichTrail"),
        _js_function("enrichStagesLogged"),
        "const doc = { provenance: [",
        "  { operation: 'layers.add_element_grid::add_or_replace_element_grid', note: 'x' },",
        "  { operation: 'enrich_violation:segments', note: '35 item(s)' },",
        "  { operation: 'enrich_violation:cross_references', note: '12 item(s)' },",
        "  { operation: 'enrichment_notes', note: 'mentions the word, is not the hook' },",
        "  { note: 'no operation at all' },",
        "] };",
        "console.log(JSON.stringify({",
        "  ops: enrichTrail(doc).map(p => p.operation),",
        "  stages: [...enrichStagesLogged(doc)],",
        "  emptyDoc: enrichTrail({}).length,",
        "  nullDoc: enrichTrail(null).length,",
        "  noTrail: enrichTrail({ provenance: [{ note: 'x' }] }).length,",
        "}));",
    ])
    got = _run_js(script)
    assert got["ops"] == ["enrich_violation:segments", "enrich_violation:cross_references"]
    assert got["stages"] == ["segments", "cross_references"]
    # The shapes a half-loaded bundle actually hands these helpers.
    assert got["emptyDoc"] == 0
    assert got["nullDoc"] == 0
    assert got["noTrail"] == 0


def test_the_s9_gate_and_the_sidebar_tick_share_one_definition_of_ran():
    """They used to hold two copies of the same `/enrich/i` scan. One helper
    means they cannot drift into disagreeing about whether a run happened."""
    assert "enrichTrail(" in _js_function("hydrateS9")
    step_progress = re.search(
        r"const STEP_PROGRESS = \{(.*?)\n\};", HTML_PATH.read_text(encoding="utf-8"), re.S
    )
    assert step_progress, "STEP_PROGRESS map not found in the UI"
    assert "enrichTrail(" in step_progress.group(1)


def test_the_s9_gate_counts_runs_off_the_full_trail_not_the_display_slice():
    """The list is capped for display; the count must not be.

    `slice(-8)` on an eight-stage run hides the ninth entry, so a count taken
    from the slice under-reports exactly when the run is complete.
    """
    body = _js_function("hydrateS9")
    assert "enrichStagesLogged(v)" in body
    assert "logged.size" in body


def test_apply_result_refreshes_the_step_panel():
    """The bug the reviewer saw: the run succeeded and the panel never moved.

    `invokeTool` → `applyResult` updated `state` and re-rendered the drawer, but
    only a *step switch* re-ran the step's hydrator — so a tool button on the
    step you were already looking at appeared to do nothing at all. Verified
    live: a sentinel written into `state.violation` left the DOM byte-identical
    until `hydrateS8()` was called by hand.
    """
    body = _js_function("applyResult")
    assert "refreshStepPanel()" in body, (
        "applyResult() must re-hydrate the active step, or a tool run on the "
        "step you are looking at leaves the panel showing the previous result"
    )


def test_the_run_path_is_background_and_guarded_against_a_second_tap():
    """Three guards, three failure modes.

    A synchronous `/api/tool` call owns the event loop for its whole run, so the
    page cannot poll — and a full enrichment is minutes. `background: true` plus
    a job poll is the only shape that can show progress at all.
    """
    body = _js_function("invokeTool")
    assert "API.toolStart(" in body and "awaitJob(" in body, (
        "invokeTool() must go through the background job path; a synchronous "
        "call blocks the server, so nothing can be shown while it runs"
    )
    # Guard 1 — a second tap in this page.
    assert re.search(r"if \(run\)", body), "invokeTool() lost its re-entrancy guard"
    assert "busy" in body, "invokeTool() no longer handles the server's 409 busy"
    # The lock is released on every exit path, including a throw.
    assert "finally" in body and "endRun()" in body

    # Guard 2 — the controls themselves.
    lock = _js_function("setRunControlsBusy")
    assert '[data-action="run"]' in lock and "#argRun" in lock
    # A button that shipped disabled (the S12 store controls, the typed
    # confirmations) must not be handed back unlocked.
    assert "freeDisabled" in lock


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


# ---------------------------------------------------------------------------
# S6 — authority proof: uploading the official source behind a stub
# ---------------------------------------------------------------------------

@pytest.fixture
def proof_workspace(tmp_path, monkeypatch):
    """A throwaway workspace whose only bundle is `build/CL-001/`.

    `/api/authority-source` writes real files, so pointing it at the repository
    would have it store a reviewer's proof (or a test's junk) inside a tracked
    bundle. `resolve_bundle_dir` re-reads `find_workspace_root()` on every call,
    which is what makes this seam work without restarting the server.
    """
    root = tmp_path / "ws"
    bundle = root / "build" / "CL-001"
    bundle.mkdir(parents=True)
    (bundle / "CL-001.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("violation_pack.ui_server.find_workspace_root", lambda: root)
    return bundle


def test_authority_source_route_stores_a_pasted_passage(client, proof_workspace):
    res = client.post("/api/authority-source", json={
        "violation_id": "CL-001",
        "authority_id": "AUTH-CL-001-01",
        "source_url": "https://www.bcn.cl/leychile/navegar?idNorma=1",
        "text": "El artículo 193 num. 8 del Código del Trabajo",
    })
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["ok"] is True
    assert payload["source_content"] == "El artículo 193 num. 8 del Código del Trabajo"
    # The url is recorded as the citation, and *nothing was downloaded* — the
    # request never asked for a fetch, so no socket may be opened. This test was
    # written before the fetch flag existed to pin exactly that.
    assert payload["fetched"] is False
    assert payload["artefact"] is None
    assert payload["source_uri"] == "https://www.bcn.cl/leychile/navegar?idNorma=1"
    assert (proof_workspace / "Authority sources" / payload["proof"]["name"]).is_file()
    sidecar = json.loads((proof_workspace / payload["proof"]["rel"]).read_text(encoding="utf-8"))
    assert sidecar["fetched"] is False, "a url that was never opened is not a fetch"
    assert sidecar["final_url"] is None
    assert sidecar["source_url"] == "https://www.bcn.cl/leychile/navegar?idNorma=1"


def test_authority_source_route_reads_an_uploaded_text_document(client, proof_workspace):
    raw = "sentencia: el artículo 193 num. 8".encode("utf-8")
    res = client.post("/api/authority-source", json={
        "violation_id": "CL-001",
        "authority_id": "AUTH-CL-001-01",
        "filename": "sentencia.html",
        "content_base64": base64.b64encode(raw).decode("ascii"),
    })
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["text_source"] == "upload"
    assert payload["needs_text"] is False
    assert payload["text_sha256"] == hashlib.sha256(payload["source_content"].encode("utf-8")).hexdigest()
    # The artefact is named after the stub it proves, so a bundle carrying five
    # sentencias still says which one belongs to which proposition.
    assert payload["artefact"]["name"].startswith("AUTH-CL-001-01__")


def test_authority_source_route_keeps_an_unreadable_upload_and_says_so(client, proof_workspace):
    res = client.post("/api/authority-source", json={
        "violation_id": "CL-001",
        "authority_id": "AUTH-CL-001-01",
        "filename": "escaneo.pdf",
        "content_base64": base64.b64encode(b"\x00\x01 not a pdf").decode("ascii"),
    })
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["needs_text"] is True
    assert payload["source_content"] is None
    assert payload["warnings"]
    assert (proof_workspace / "Authority sources" / payload["artefact"]["name"]).is_file()


def test_authority_source_route_refuses_a_bundle_that_is_not_on_disk(client, proof_workspace):
    res = client.post("/api/authority-source", json={
        "violation_id": "CL-777", "authority_id": "A", "text": "x",
    })
    assert res.status_code == 404


@pytest.mark.parametrize("violation_id", ["../../etc", "..", "a/b", "", "with space"])
def test_authority_source_route_refuses_a_bundle_id_that_is_a_path(client, proof_workspace, violation_id):
    res = client.post("/api/authority-source", json={
        "violation_id": violation_id, "authority_id": "AUTH-1", "text": "x",
    })
    assert res.status_code in (400, 404), res.text
    assert not (proof_workspace.parent.parent / "etc").exists()


def test_authority_source_route_requires_an_authority_id(client, proof_workspace):
    res = client.post("/api/authority-source", json={
        "violation_id": "CL-001", "authority_id": "  ", "text": "x",
    })
    assert res.status_code == 400


def test_authority_source_route_rejects_malformed_bodies(client, proof_workspace):
    bad_json = client.post("/api/authority-source", content=b"{not json",
                           headers={"content-type": "application/json"})
    assert bad_json.status_code == 400
    not_an_object = client.post("/api/authority-source", json=["nope"])
    assert not_an_object.status_code == 400
    bad_base64 = client.post("/api/authority-source", json={
        "violation_id": "CL-001", "authority_id": "AUTH-1", "content_base64": "!!!",
    })
    assert bad_base64.status_code == 400
    assert "base64" in bad_base64.json()["error"].lower()


def test_authority_source_route_refuses_a_host_alias_that_is_this_machine(client, proof_workspace):
    """A url is not trusted just because it arrived through the bridge."""
    res = client.post("/api/authority-source", json={
        "violation_id": "CL-001", "authority_id": "AUTH-1",
        "source_url": "http://169.254.169.254/latest/meta-data/", "fetch_url": True,
    })
    assert res.status_code == 400
    stored = proof_workspace / "Authority sources"
    assert not stored.exists() or not list(stored.iterdir())


def test_authority_source_route_answers_the_preflight(client, proof_workspace):
    assert client.options("/api/authority-source").status_code == 204


def _stored_source(client, proof_workspace, **overrides):
    """Store one upload through the route and return the sidecar's own record."""
    payload = {
        "violation_id": "CL-001",
        "authority_id": "AUTH-CL-001-01",
        "filename": "decreto.html",
        "content_base64": base64.b64encode("el artículo 19 num. 3".encode("utf-8")).decode("ascii"),
        **overrides,
    }
    res = client.post("/api/authority-source", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


def test_delete_route_removes_one_source_and_leaves_the_rest(client, proof_workspace):
    """The replacement flow: the stored copy goes, and only the stored copy.

    A stored source is up to three files off one name, so the reviewer names the
    one they can see and the bundle decides the rest. What must *survive* is
    asserted as carefully as what must go: another stub's proof, and the `-2`
    neighbour `_unique_path` makes for a same-named upload with different bytes.
    That neighbour is the near-miss a grouping built on the prefix alone would
    sweep up.
    """
    first = _stored_source(client, proof_workspace)
    other = _stored_source(client, proof_workspace, authority_id="AUTH-CL-001-02")
    second = _stored_source(
        client, proof_workspace,
        content_base64=base64.b64encode("otra norma distinta".encode("utf-8")).decode("ascii"),
    )
    assert second["artefact"]["name"] == first["artefact"]["name"].replace(".html", "-2.html"), (
        "the second upload of the same name did not land beside the first"
    )

    stored = proof_workspace / "Authority sources"
    before = {p.name for p in stored.iterdir()}
    doomed = {first["artefact"]["name"], first["proof"]["name"]}

    res = client.post("/api/authority-source/delete", json={
        "violation_id": "CL-001",
        "authority_id": "AUTH-CL-001-01",
        "name": first["artefact"]["name"],
    })
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["ok"] is True
    assert set(payload["deleted"]) == {f"Authority sources/{name}" for name in doomed}, payload
    assert payload["freed_bytes"] > 0, "nothing was actually unlinked"

    after = {p.name for p in stored.iterdir()}
    assert after == before - doomed, (
        "the delete took a file it was not pointed at, or left one of the source's own files behind"
    )
    for kept in (other, second):
        assert (stored / kept["artefact"]["name"]).is_file(), (
            "a different source was removed by deleting this one"
        )
        assert (stored / kept["proof"]["name"]).is_file()


def test_delete_route_lets_the_same_document_be_stored_again(client, proof_workspace):
    """Delete then re-upload is the flow the page is built for.

    The identical bytes are *reused* on the way back in — `_unique_path` will not
    mint `-2` for content it already holds — so this asserts the round trip
    restores exactly the three files that went, with no `-2` residue.
    """
    first = _stored_source(client, proof_workspace, content_base64=base64.b64encode(
        b"<html><body>el art\xc3\xadculo 19 num. 3</body></html>"
    ).decode("ascii"))
    stored = proof_workspace / "Authority sources"
    before = {p.name for p in stored.iterdir()}

    res = client.post("/api/authority-source/delete", json={
        "violation_id": "CL-001", "authority_id": "AUTH-CL-001-01",
        "name": first["artefact"]["name"],
    })
    assert res.status_code == 200, res.text
    assert not list(stored.iterdir()), (
        "removing the only source left something behind in the directory"
    )

    again = _stored_source(client, proof_workspace, content_base64=base64.b64encode(
        b"<html><body>el art\xc3\xadculo 19 num. 3</body></html>"
    ).decode("ascii"))
    assert again["artefact"]["name"] == first["artefact"]["name"], (
        "re-storing the same document minted a second copy"
    )
    assert {p.name for p in stored.iterdir()} == before, (
        "the replacement is not the same set of files the removed source had"
    )


def test_delete_route_removes_the_matched_text_when_the_source_kept_one(client, proof_workspace):
    """A third file, when the text is not the artefact's own bytes.

    The text file's name is nowhere in the request, so a list the browser had to
    compute is where this goes wrong; the sidecar records it and the group is read
    off the directory instead.
    """
    res = client.post("/api/authority-source", json={
        "violation_id": "CL-001",
        "authority_id": "AUTH-CL-001-01",
        "filename": "pagina.html",
        "content_base64": base64.b64encode(
            b"<html><body><p>el art\xc3\xadculo 19</p></body></html>"
        ).decode("ascii"),
    })
    assert res.status_code == 200, res.text
    payload = res.json()
    sidecar_rel = payload["proof"]["rel"]
    sidecar = json.loads((proof_workspace / sidecar_rel).read_text(encoding="utf-8"))
    assert sidecar["text_file"], (
        "a markup upload whose text differs from its bytes must keep a text file"
    )
    text_file = proof_workspace / sidecar["text_file"]
    assert text_file.is_file()

    res = client.post("/api/authority-source/delete", json={
        "violation_id": "CL-001", "authority_id": "AUTH-CL-001-01",
        "name": payload["artefact"]["name"],
    })
    assert res.status_code == 200, res.text
    assert {f"Authority sources/{text_file.name}", sidecar_rel} <= set(res.json()["deleted"]), (
        "the matched text was left behind with nothing pointing at it"
    )
    assert not text_file.exists()
    assert not (proof_workspace / sidecar_rel).exists(), (
        "the sidecar outlived the document, so it still claims a proof that is gone"
    )


def test_delete_route_can_be_named_by_any_file_of_the_source(client, proof_workspace):
    """The sidecar's name is enough, because that is what the modal lists."""
    stored = _stored_source(client, proof_workspace)
    res = client.post("/api/authority-source/delete", json={
        "violation_id": "CL-001", "authority_id": "AUTH-CL-001-01",
        "name": stored["proof"]["name"],
    })
    assert res.status_code == 200, res.text
    assert not (proof_workspace / stored["artefact"]["rel"]).exists()


def test_delete_route_refuses_a_name_that_is_not_this_stub_source(client, proof_workspace):
    """Only a file this stub wrote can be removed by name.

    The modal lists every proof in the bundle, so the browser is one bug away from
    offering a delete for a file that belongs to somebody else's stub. The route
    is the last thing between that and the filesystem.
    """
    other = _stored_source(client, proof_workspace, authority_id="AUTH-CL-001-02")
    res = client.post("/api/authority-source/delete", json={
        "violation_id": "CL-001", "authority_id": "AUTH-CL-001-01",
        "name": other["artefact"]["name"],
    })
    assert res.status_code == 400, res.text
    assert "AUTH-CL-001-01" in res.json()["error"]
    assert (proof_workspace / other["artefact"]["rel"]).is_file(), (
        "another stub's proof was removed by a name that was refused"
    )


@pytest.mark.parametrize("template", [
    "sub/{name}",
    "./{name}",
    "Authority sources/{name}",
    "../CL-001/Authority sources/{name}",
])
def test_delete_route_refuses_a_path_that_would_normalise_to_a_real_file(
    client, proof_workspace, template,
):
    """The refusal cannot be judged by the status code alone.

    Every name here resolves to a file this stub really wrote if it is normalised
    first — `Path(name).name`, the habit this module's own `sanitise_filename`
    uses for *uploads*, where it is right. Here it would be the bug: a path the
    reviewer never saw, accepted because its last component names a real file. So
    the assertion is that the file survives, not that the call erred.
    """
    stored = _stored_source(client, proof_workspace)
    name = template.format(name=stored["artefact"]["name"])
    res = client.post("/api/authority-source/delete", json={
        "violation_id": "CL-001", "authority_id": "AUTH-CL-001-01", "name": name,
    })
    assert res.status_code == 400, (name, res.text)
    assert (proof_workspace / stored["artefact"]["rel"]).is_file(), (
        f"{name!r} was normalised to a stored file and deleted"
    )
    assert (proof_workspace / stored["proof"]["rel"]).is_file()


@pytest.mark.parametrize("name", [
    "../CL-001.json",
    "../../CL-001.json",
    "sub/decreto.html",
    "..\\decreto.html",
    "Authority sources/CL-001.json",
    "",
    "   ",
])
def test_delete_route_refuses_a_name_that_is_a_path(client, proof_workspace, name):
    """Nothing that arrives as "a filename" may reach outside the directory."""
    bundle_json = proof_workspace / "CL-001.json"
    marker = json.loads(bundle_json.read_text(encoding="utf-8"))
    res = client.post("/api/authority-source/delete", json={
        "violation_id": "CL-001", "authority_id": "AUTH-CL-001-01", "name": name,
    })
    assert res.status_code == 400, res.text
    assert bundle_json.is_file(), "the bundle JSON was removed by a traversal attempt"
    assert json.loads(bundle_json.read_text(encoding="utf-8")) == marker


def test_delete_route_reports_a_source_that_is_already_gone(client, proof_workspace):
    """Idempotent in effect, not silent about it: the second click says so."""
    stored = _stored_source(client, proof_workspace)
    body = {"violation_id": "CL-001", "authority_id": "AUTH-CL-001-01",
            "name": stored["artefact"]["name"]}
    assert client.post("/api/authority-source/delete", json=body).status_code == 200
    again = client.post("/api/authority-source/delete", json=body)
    assert again.status_code == 400
    assert "no stored source" in again.json()["error"]


def test_delete_route_requires_a_bundle_that_exists(client, proof_workspace):
    res = client.post("/api/authority-source/delete", json={
        "violation_id": "CL-777", "authority_id": "AUTH-1", "name": "x.html",
    })
    assert res.status_code == 404


@pytest.mark.parametrize("violation_id", ["../../etc", "a/b", "", "with space"])
def test_delete_route_refuses_a_bundle_id_that_is_a_path(client, proof_workspace, violation_id):
    res = client.post("/api/authority-source/delete", json={
        "violation_id": violation_id, "authority_id": "AUTH-1", "name": "x.html",
    })
    assert res.status_code in (400, 404), res.text
    assert not (proof_workspace.parent.parent / "etc").exists()


def test_delete_route_requires_an_authority_id(client, proof_workspace):
    res = client.post("/api/authority-source/delete", json={
        "violation_id": "CL-001", "authority_id": "  ", "name": "x.html",
    })
    assert res.status_code == 400


def test_delete_route_rejects_malformed_bodies(client, proof_workspace):
    bad_json = client.post("/api/authority-source/delete", content=b"{not json",
                           headers={"content-type": "application/json"})
    assert bad_json.status_code == 400
    assert client.post("/api/authority-source/delete", json=["nope"]).status_code == 400
    # The one field this route reads is `name`, and it must be a string: a list or
    # a number is not a file name, and must not become one on the way in.
    stored = _stored_source(client, proof_workspace)
    for bad in (123, [stored["artefact"]["name"]], {"name": "x"}, None):
        res = client.post("/api/authority-source/delete", json={
            "violation_id": "CL-001", "authority_id": "AUTH-CL-001-01", "name": bad,
        })
        assert res.status_code == 400, (bad, res.text)
    assert (proof_workspace / stored["artefact"]["rel"]).is_file(), (
        "a malformed body removed a file"
    )


def test_delete_route_answers_the_preflight(client, proof_workspace):
    assert client.options("/api/authority-source/delete").status_code == 204


# ---------------------------------------------------------------------------
# S6 — reading a stored source back
# ---------------------------------------------------------------------------

def test_reading_route_hands_back_the_text_the_store_returned(client, proof_workspace):
    """The round trip: what the store handed the browser, the bundle hands it again
    — without a second upload, which is the only way it could be had before."""
    stored = _stored_source(client, proof_workspace)
    directory = proof_workspace / "Authority sources"
    before = {p.name: p.read_bytes() for p in directory.iterdir()}

    res = client.get("/api/authority-source/reading", params={
        "violation_id": "CL-001", "authority_id": "AUTH-CL-001-01",
        "name": stored["artefact"]["name"],
    })
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["source_content"] == stored["source_content"]
    assert payload["text_sha256"] == stored["text_sha256"]
    assert payload["text_matches_record"] is True
    assert payload["warnings"] == []
    assert payload["sidecar"]["name"] == stored["proof"]["name"]
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before, (
        "a GET changed the bundle"
    )


def test_reading_route_hands_back_the_margin_the_record_holds(client, proof_workspace):
    """The half the route exists for. The reading, the citations and the numerals
    are in the sidecar, and before this route the page that wrote them could not
    read them: the only way to see a stored source's margin was to open the JSON in
    an editor."""
    stored = _stored_source(client, proof_workspace)
    sidecar = proof_workspace / stored["proof"]["rel"]
    record = json.loads(sidecar.read_text(encoding="utf-8"))
    record["citations"] = [{
        "text": "CPR Art. 19° N° 3 D.O. 24.10.1980", "page": 1, "first_line": 5,
        "last_page": 1, "last_line": 5, "crosses_page": False,
        "beside": 2, "named": 3, "agrees": False,
    }]
    record["notes"] = [{"page": 1, "line": 5, "text": "CPR Art. 19° N° 3 D.O. 24.10.1980"}]
    record["readings"] = {"derivation": {
        "citations": record["citations"], "numerals": [{"page": 1, "row": 9, "number": 2}],
    }}
    sidecar.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    res = client.get("/api/authority-source/reading", params={
        "violation_id": "CL-001", "authority_id": "AUTH-CL-001-01",
        "name": stored["artefact"]["name"],
    })
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["citations"] == record["citations"]
    assert payload["numerals"] == [{"page": 1, "row": 9, "number": 2}]
    assert payload["notes"] == record["notes"]
    assert payload["citations_recorded"] is True
    assert payload["reading_recorded"] is True
    assert payload["source_content"] == stored["source_content"]


def test_reading_route_says_a_text_that_drifted_from_its_record(client, proof_workspace):
    """Reported, not raised: `verifyProofStub` refuses on the flag, and a caller
    looking at the record is told which file to compare."""
    stored = _stored_source(client, proof_workspace)
    (proof_workspace / stored["artefact"]["rel"]).write_text("otra cosa", encoding="utf-8")

    res = client.get("/api/authority-source/reading", params={
        "violation_id": "CL-001", "authority_id": "AUTH-CL-001-01",
        "name": stored["artefact"]["name"],
    })
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["text_matches_record"] is False
    assert any("hashes" in w for w in payload["warnings"]), payload["warnings"]
    assert payload["source_content"] == "otra cosa"


def test_reading_route_refuses_a_name_that_is_not_stored(client, proof_workspace):
    _stored_source(client, proof_workspace)
    res = client.get("/api/authority-source/reading", params={
        "violation_id": "CL-001", "authority_id": "AUTH-CL-001-01",
        "name": "AUTH-CL-001-01__fantasma.proof.json",
    })
    assert res.status_code == 400
    assert "no stored source" in res.json()["error"]


def test_reading_route_refuses_a_name_that_is_a_path(client, proof_workspace):
    stored = _stored_source(client, proof_workspace)
    marker = (proof_workspace / "CL-001.json").read_text(encoding="utf-8")
    res = client.get("/api/authority-source/reading", params={
        "violation_id": "CL-001", "authority_id": "AUTH-CL-001-01",
        "name": "AUTH-CL-001-01__../CL-001.json",
    })
    assert res.status_code == 400, res.text
    assert (proof_workspace / "CL-001.json").read_text(encoding="utf-8") == marker
    assert (proof_workspace / stored["artefact"]["rel"]).is_file()


def test_reading_route_requires_a_bundle_and_an_authority(client, proof_workspace):
    _stored_source(client, proof_workspace)
    gone = client.get("/api/authority-source/reading", params={
        "violation_id": "CL-777", "authority_id": "AUTH-CL-001-01", "name": "x.html",
    })
    assert gone.status_code == 404

    no_authority = client.get("/api/authority-source/reading", params={
        "violation_id": "CL-001", "authority_id": "  ", "name": "x.html",
    })
    assert no_authority.status_code == 400

    no_name = client.get("/api/authority-source/reading", params={
        "violation_id": "CL-001", "authority_id": "AUTH-CL-001-01",
    })
    assert no_name.status_code == 400


def test_reading_route_answers_the_preflight(client, proof_workspace):
    assert client.options("/api/authority-source/reading").status_code == 204


# ---------------------------------------------------------------------------
# S6 — the page must name the authority by the field the model actually has
# ---------------------------------------------------------------------------

def test_the_ui_never_reads_an_authority_id_off_a_bare_id_field():
    """`Authority.authority_id` is not `id`, and Pydantic's extra="forbid" means
    the mistake cannot surface as a server error — it surfaces as the literal
    string "undefined" rendered as every stub's name, and as a `<select>` whose
    every option reads `undefined — type?`. Both look like data."""
    html = HTML_PATH.read_text(encoding="utf-8")
    offenders = [
        (i, line.strip())
        for i, line in enumerate(html.splitlines(), 1)
        if re.search(r"\b(?:a|authority)\.id\b", line)
    ]
    assert not offenders, f"authority id read from `id` at {offenders}"


def _extract_proof_plan(html: str) -> str:
    match = re.search(r"const PROOF_PLAN = \{.*?\n\};", html, re.S)
    assert match, "PROOF_PLAN is not defined in the UI page"
    return match.group(0)


def test_the_s6_proof_plan_names_parameters_the_verify_tools_actually_accept(server):
    """The form's field names are handed straight to `/api/tool` as arguments.

    A typo would not fail loudly: the tool would receive its own defaults and
    verify the stub against a court, rol or instrument nobody supplied. So the
    plan is compared against the real tool schemas rather than against a copy.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    script = "\n".join([
        _extract_proof_plan(html),
        _js_function("proofPlanFor"),
        _js_function("proofFieldId"),
        "const types = ['statute', 'jurisprudence', 'doctrine', 'comparative'];",
        "console.log(JSON.stringify({",
        "  plans: Object.fromEntries(types.map(t => [t, proofPlanFor({ type: t })])),",
        "  unknown: proofPlanFor({ type: 'not_a_type' }),",
        "  absent: proofPlanFor({}),",
        "  idsByPlan: Object.fromEntries(types.map(t => [t, PROOF_PLAN[t].fields.map(proofFieldId)])),",
        "  nameIds: types.flatMap(t => PROOF_PLAN[t].fields.map(n => [n, proofFieldId(n)])),",
        "}));",
    ])
    out = _run_js(script)
    tools = {t["name"]: set(t["required"]) | set(t["optional"])
             for t in describe_tools(server._tool_manager)}

    assert out["unknown"] is None and out["absent"] is None, (
        "an unroutable type must yield no plan at all — falling back to a "
        "protocol would verify a comparative citation under the statute rules"
    )
    for authority_type, plan in out["plans"].items():
        assert plan["tool"] in tools
        params = tools[plan["tool"]]
        missing = sorted((set(plan["fields"]) | set(plan["required"])) - params)
        assert not missing, f"{authority_type} would send {missing}, which {plan['tool']} does not accept"
        assert set(plan["required"]) <= set(plan["fields"]), authority_type
        assert "target_quote" not in plan["fields"], "the quote is the modal's own field"

    # One modal renders one plan, so ids only have to be unique *within* a plan;
    # `pages` appearing in four plans is correct. What is not allowed is two
    # controls in the same form answering to one id — the second would be read
    # back as the first, and the argument sent would be silently wrong.
    for authority_type, ids in out["idsByPlan"].items():
        assert len(set(ids)) == len(ids), (
            f"{authority_type} renders two fields under one DOM id: {ids}"
        )
        assert all(i.startswith("proof") for i in ids), ids
    mapping = dict(out["nameIds"])
    assert mapping["decision_date"] == "proofDecisionDate"
    assert len(mapping) == len({name for name, _ in out["nameIds"]}), (
        "one field name resolved to two DOM ids — the read-back would differ by plan"
    )


def test_the_plan_asks_for_every_field_the_protocol_refuses_without():
    """A deliberate snapshot: the protocols' minima are type-conditional and live
    in the protocols' own checks, which no schema exposes.

    Clearing `required` would not corrupt a record — the tool still refuses a
    jurisprudence without a rol — but the reviewer would meet a server error
    about a field the form never offered, which is the one thing the plan exists
    to prevent. The converse, requiring a field the protocol does not insist on,
    blocks a legitimate verification outright.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    script = "\n".join([
        _extract_proof_plan(html),
        _js_function("proofPlanFor"),
        "const types = ['statute', 'jurisprudence', 'doctrine', 'comparative'];",
        "console.log(JSON.stringify(Object.fromEntries("
        "types.map(t => [t, proofPlanFor({ type: t }).required]))));",
    ])
    assert _run_js(script) == {
        "statute": ["instrument"],
        "jurisprudence": ["attestor", "court", "rol", "decision_date"],
        "doctrine": ["attestor", "author", "work"],
        "comparative": ["attestor"],
    }


def _render_proof_source(source: dict, quote: str, authority: dict | None = None) -> dict:
    """Run `renderProofSource` under node against a fake document.

    The status line is the only place the page says which copy of the source was
    searched, so it cannot be asserted with a regex over its own source: the
    branch that runs is chosen at runtime by whether the quote was found.

    `authority` is the stub whose provenance the refusal note may have to name:
    the note compares the quote in the box with the one that stub was verified
    with, so the branch it takes depends on that record, not on the source alone.
    It is re-keyed to `AUTH-1`, the id `renderProofSource` is called with — the note
    reads the stub by that id, and its id is not what is under test.
    """
    if authority is not None:
        authority = {**authority, "authority_id": "AUTH-1"}
    script = "\n".join([
        "const els = {};",
        "function fakeEl(id) { return els[id] || (els[id] = { id, innerHTML: '',"
        " style: {}, value: '', textContent: '' }); }",
        "const document = { getElementById: (id) => fakeEl(id) };",
        "const state = { proofSources: { 'AUTH-1': JSON.parse("
        + json.dumps(json.dumps(source)) + ") },"
        " violation: { authorities: JSON.parse("
        + json.dumps(json.dumps([authority] if authority else [])) + ") } };",
        _js_function("escapeHtml"),
        _js_function("inputValue"),
        _js_function("proofStatus"),
        _js_function("proofRefusalNote"),
        _js_function("proofPreviewIsStale"),
        _js_const("PROOF_NO_SOURCE"),
        _js_function("highlightQuote"),
        _js_function("proofNumeralPair"),
        _js_function("proofMarginSection"),
        _js_function("renderProofSource"),
        f"fakeEl('proofQuote').value = {json.dumps(quote)};",
        "renderProofSource('AUTH-1');",
        "console.log(JSON.stringify({",
        "  match: fakeEl('proofMatch').innerHTML,",
        "  preview: fakeEl('proofPreview').innerHTML,",
        "}));",
    ])
    return _run_js(script)


def test_the_verdict_stays_attached_to_where_the_searched_text_came_from():
    """The provenance line must survive the verdict, not be replaced by it.

    A reviewer pastes the quote as the last thing before verifying, and that used
    to be the exact moment the line naming the served content type, the redirect
    target, the reader and the hash disappeared — leaving "Found verbatim" over an
    unlabelled blob. Both halves are asserted in the same run so that neither can
    be dropped again.
    """
    source = {
        "source_uri": "https://bcn.cl/24pdg",
        "source_content": "VISTOS: la vejación injusta requiere un trato degradante.",
        "text_source": "fetched",
        "content_type": "text/html",
        "fetched": True,
        "final_url": "https://www.bcn.cl/leychile/navegar?idNorma=242302",
        "extractor": "html-strip",
        "chars": 234,
        "text_sha256": "0123456789abcdef" * 4,
        "artefact": {"rel": "Authority sources/AUTH-1__page.html"},
        "warnings": [],
    }
    wanted = [
        "served as text/html",
        "redirected to https://www.bcn.cl/leychile/navegar?idNorma=242302",
        "read with html-strip",
        "234 characters",
        "sha256 0123456789ab…",
        "stored as Authority sources/AUTH-1__page.html",
    ]

    found = _render_proof_source(source, "la vejación injusta requiere un trato degradante")
    assert "Found verbatim at offset <b>8</b>" in found["match"]  # after "VISTOS: "
    for bit in wanted:
        assert bit in found["match"], f"the verdict hid {bit!r}"
    assert "<mark>" in found["preview"], "the found quote is not highlighted in the loaded text"

    missing = _render_proof_source(source, "una frase que no está en la página")
    assert "Not found verbatim" in missing["match"]
    for bit in wanted:
        assert bit in missing["match"], f"the refusal hid {bit!r}"

    unpasted = _render_proof_source(source, "")
    assert "Paste the quote that must appear." in unpasted["match"]
    for bit in wanted:
        assert bit in unpasted["match"], f"the waiting state hid {bit!r}"

    # A PDF with no reader: the artefact is still named and hashed, and the
    # reviewer is told the passage has to be pasted.
    unreadable = _render_proof_source(
        {**source, "source_content": "", "extractor": None, "text_source": "upload"},
        "algo",
    )
    assert "Nothing readable came out of it" in unreadable["match"]
    assert "stored as Authority sources/AUTH-1__page.html" in unreadable["match"]


#: The passage the modal has to explain a refusal about. Modelled on what BCN
#: serves for DTO-100 (03-MAY-2023): the sentence that verifies is
#: "Corresponderá al legislador establecer siempre las garantías de un
#: procedimiento y una investigación racionales y justos", but the PDF's text layer
#: puts the amendment's margin note *inside* it and breaks one word across a page.
_DTO_SPLICED = (
    "Artículo único.- Introdúcense las siguientes modificaciones en la Constitución "
    "Política de la República: 3°.- Incorpórase en el numeral 3° del artículo 19 la "
    "siguiente oración: Corresponderá al legislador establecer siempre las 26.08.2005 "
    "garantías de un procedimiento y una investigación racionales y justos. La ley "
    "dictada en conformidad con este numeral no podrá afectar derechos esenciales."
)
#: What a reviewer copies out of the official copy *after reading it* — the sentence
#: as the law writes it, with the page furniture removed.
_DTO_SENTENCE = (
    "Corresponderá al legislador establecer siempre las garantías de un "
    "procedimiento y una investigación racionales y justos"
)
#: A run that is contiguous in `_DTO_SPLICED`, unlike `_DTO_SENTENCE`: the plumbing
#: around the pane is tested with a quote that is actually found, so the pane has
#: text to show and the refusal note — which reads the stub — is not on the path.
_DTO_IN_ROW = "Introdúcense las siguientes modificaciones en la Constitución Política de la República"


def _stored_pdf_source(content: str) -> dict:
    """The payload `POST /api/authority-source` returns for an uploaded PDF."""
    return {
        "source_uri": "Authority sources/CL.CPR.Art.19.N3__DTO-100_03-MAY-2023.pdf",
        "source_content": content,
        "text_source": "upload",
        "content_type": "application/pdf",
        "extractor": "pypdf",
        "chars": len(content),
        "text_sha256": "c11f86b8" * 8,
        "artefact": {"rel": "Authority sources/CL.CPR.Art.19.N3__DTO-100_03-MAY-2023.pdf"},
        "warnings": [],
    }


def test_a_quote_whose_words_are_all_there_but_not_in_a_row_says_that():
    """The wording was right and the protocol still refused: the PDF's text layer
    put the amendment's margin note in the middle of the sentence, so the sentence
    as written exists nowhere in the loaded text. "Check the wording" sends the
    reviewer hunting for a typo that is not there — this is the note that names the
    real cause, and it must not read as an acceptance."""
    assert _DTO_SPLICED.find(_DTO_SENTENCE) < 0, "the fixture no longer reproduces the splice"
    out = _render_proof_source(_stored_pdf_source(_DTO_SPLICED), _DTO_SENTENCE)
    assert "not in a row" in out["match"], "a spliced sentence was reported as a wording problem"
    assert "Quote a run that reads continuously" in out["match"], "no remedy named"
    assert "Not found verbatim" not in out["match"]
    assert "Found verbatim" not in out["match"], "the note read as an acceptance"

    # The claim is "every word is here", so a quote with a word missing outright
    # must not collect it: the loose version ("some word of this is in there")
    # fires on any shared syllable and tells the reviewer their wording is fine
    # when the document does not contain it.
    mixed = _render_proof_source(_stored_pdf_source(_DTO_SPLICED), "racionales y conclusión errada")
    assert "not in a row" not in mixed["match"], "a word-missing quote was explained as scrambled"
    assert "Not found verbatim" in mixed["match"]


def test_a_quote_that_cannot_be_marked_still_shows_the_text_it_would_have_marked():
    """The loaded text is the only place the reviewer can find the wording they are
    being asked to quote, so it cannot be truncated to its head: the DTO-100 copy
    this was diagnosed on holds the sentence at offset 3,348 of 6,207, past the
    window the preview used to render when nothing matched."""
    content = "Relleno del considerando anterior. " * 130 + _DTO_SPLICED
    assert content.find("garantías de un procedimiento") > 3000, "the passage is not past the old cap"
    out = _render_proof_source(_stored_pdf_source(content), _DTO_SENTENCE)
    assert "garantías de un procedimiento" in out["preview"], (
        "the passage the refusal is about is not readable in the preview"
    )


def test_a_quote_brought_over_from_another_source_is_named_and_not_blamed_on_the_wording():
    """The stub's recorded quote is prefilled into the box because it is what was
    verified last time — but it was verified against a *different* source, and this
    modal exists to attach a new one. A quote is evidence about the document it was
    found in: an English translation of art. 19 N° 3 is not evidence about the
    Spanish DTO-100, and the reviewer has to be told which document to quote."""
    recorded = ("The legislator must always establish the guarantees of a rational "
                "and just procedure and investigation.")
    authority = {
        "authority_id": "CL.CPR.Art.19.N3",
        "type": "statute",
        "instrument": "Constitución Política de la República, Art. 19 N° 3",
        "verified": True,
        "verification_provenance": {
            "protocol": "statute_in_bundle_v1",
            "source_uri": "Legal framework/CONST.md",
            "source_sha256": "a42140a7" * 8,
            "matched_quote": recorded,
            "matched_offset": 1285,
            "verified_at": "2026-09-13T11:02:00+00:00",
        },
    }
    out = _render_proof_source(_stored_pdf_source(_DTO_SPLICED), recorded, authority)
    assert "Legal framework/CONST.md" in out["match"], "the source it was matched in is not named"
    assert "came with the stub" in out["match"]
    assert "Check the wording" not in out["match"], "the real cause was blamed on the wording"
    assert "not in a row" not in out["match"], "an absent quote was reported as a scrambled one"

    # The note is about *that* quote, the one the stub recorded. A quote the
    # reviewer typed beside the same stub is theirs, and calling it the stub's
    # would send them looking for a source they never used.
    typed = _render_proof_source(_stored_pdf_source(_DTO_SPLICED), _DTO_SENTENCE, authority)
    assert "came with the stub" not in typed["match"], (
        "a quote the reviewer typed was presented as the stub's recorded one"
    )

    # The note is about that mismatch. Loading the source it *was* matched in must
    # fall back to the ordinary verdict rather than repeat the story.
    same = _render_proof_source(
        {"source_uri": "Legal framework/CONST.md",
         "source_content": "…must be based on a previous legally held process. " + recorded,
         "text_source": "upload", "extractor": "text", "chars": 200,
         "artefact": {"rel": "Legal framework/CONST.md"}, "warnings": []},
        recorded, authority,
    )
    assert "came with the stub" not in same["match"], "the note fired against the source it names"
    assert "Found verbatim" in same["match"], "a quote in its own source was not accepted"


# ---------------------------------------------------------------------------
# S6 — the reading and the margin it set aside
# ---------------------------------------------------------------------------

def _dto_reading(**overrides) -> dict:
    """The payload `GET /api/authority-source/reading` returns for the DTO-100 copy."""
    reading = {
        "extractor": "pypdf",
        "columns_split": True,
        "gutter_column": 1,
        "furniture_lines": 37,
        "citations": [
            {"text": "CPR Art. 19° N° 3 D.O. 24.10.1980", "page": 1, "first_line": 5,
             "last_page": 1, "last_line": 5, "crosses_page": False,
             "beside": 3, "named": 3, "agrees": True},
            {"text": "CPR Art. 19° Nº 14 D.O. 26.08.2005", "page": 5, "first_line": 46,
             "last_page": 5, "last_line": 46, "crosses_page": False,
             "beside": 15, "named": 14, "agrees": False},
            {"text": "Ley 20516 Art. ÚNICO Nº 1 b) D.O. 11.07.2011", "page": 1,
             "first_line": 53, "last_page": 2, "last_line": 6, "crosses_page": True,
             "beside": None, "named": None, "agrees": None},
        ],
    }
    reading.update(overrides)
    return {
        "ok": True,
        "authority_id": "AUTH-1",
        "name": "CL.CPR.Art.19.N3__DTO-100_03-MAY-2023.pdf",
        "source_uri": "Authority sources/CL.CPR.Art.19.N3__DTO-100_03-MAY-2023.pdf",
        "source_content": _DTO_SPLICED,
        "chars": len(_DTO_SPLICED),
        "text_sha256": "c11f86b8" * 8,
        "text_matches_record": True,
        "reading_recorded": True,
        "citations_recorded": True,
        "reading": reading,
        "citations": reading["citations"],
        "numerals": [{"page": 1, "row": 9, "number": 3}],
        "notes": [{"page": 1, "line": 5, "text": "CPR Art. 19° N° 3 D.O. 24.10.1980"}],
        "warnings": [],
    }


def _render_margin(record: dict) -> str:
    """Run `proofMarginSection` on one record and return the markup it wrote.

    The section is the pane's only account of the margin, and which rows it shows
    is decided at runtime from the record — a regex over the function's own source
    would pass on a version that renders nothing.
    """
    script = "\n".join([
        _js_function("escapeHtml"),
        _js_function("proofNumeralPair"),
        _js_function("proofMarginSection"),
        f"console.log(JSON.stringify({{ html: proofMarginSection({json.dumps(record)}) }}));",
    ])
    return _run_js(script)["html"]


def test_a_record_that_never_kept_the_margin_says_so_rather_than_showing_none():
    """An older sidecar has no `citations` key, and rendering that as "no citation
    was found in the margin" would be a claim the record cannot make: nothing was
    looked for. The flag is what separates the two, so it is asserted on its own."""
    html = _render_margin({
        "source_uri": "Authority sources/AUTH-1__x.pdf",
        "source_content": "algo",
        "citations_recorded": False,
        "reading_recorded": False,
        "citations": [],
    })
    assert "written before the margin was kept" in html, html
    assert "No citation was found" not in html, "an unrecorded margin was reported as an empty one"


def test_a_text_source_with_no_reading_and_no_margin_adds_nothing_to_the_pane():
    """Nothing to say is said by saying nothing: a pasted passage has no margin
    column and no reading, and a "Margin — 0 citations" heading over it would be
    noise on every text source in the bundle."""
    assert _render_margin({
        "source_uri": "Authority sources/AUTH-1__page.html",
        "source_content": "texto pegado",
        "reading": None, "citations_recorded": True, "citations": [],
    }) == ""


def test_the_margin_a_reading_set_aside_is_readable_from_the_pane():
    """The point of keeping the margin is being able to read it back.

    Both numerals are shown for every citation, because they are different answers:
    the DTO-100 copy prints `Nº 14` beside numeral 15 of the sentence it amends, and
    a reviewer reading only one of the two would take the margin for an index it is
    not. The page and line are there because a citation with no position cannot be
    found in the document it was taken out of.
    """
    html = _render_margin(_dto_reading())
    assert "Margin —" in html and "3 citations" in html and "1 numeral" in html
    assert "read as two columns" in html
    assert "37 repeated lines of page furniture dropped" in html
    assert "not searched" in html, "the pane must say these citations are not part of the text"
    assert "CPR Art. 19° N° 3 D.O. 24.10.1980" in html
    assert "p5 l46" in html
    assert "beside 15, names 14 — differs" in html, "the two answers were collapsed into one"
    assert "beside 3, names 3 — agrees" in html
    assert "p1 l53 → p2 l6" in html, "a citation crossing a page lost the half after the break"


def test_an_unattributed_citation_is_not_reported_as_a_disagreement():
    """`agrees` is null when either numeral is unknown — the page-break citation has
    neither — and null is a third answer. Rendering it as "differs" would turn a
    citation the reader could not place into a contradiction with the body."""
    html = _render_margin(_dto_reading())
    assert "no numeral beside it, names none — unattributed" in html
    assert "— differs" in html  # the real disagreement, still reported


def test_only_the_first_citations_are_listed_and_the_rest_are_counted():
    """A consolidated article can carry a hundred margin rows, and the pane sits
    under the loaded text inside a `max-height` card. The count is what makes the
    truncation honest: a list that silently stopped at eight would read as the whole
    margin."""
    many = [{"text": f"CPR Art. {n}° D.O. 24.10.1980", "page": 1, "first_line": n,
             "last_page": 1, "last_line": n, "crosses_page": False,
             "beside": n, "named": n, "agrees": True} for n in range(1, 15)]
    html = _render_margin(_dto_reading(citations=many, numerals=[], notes=[]))
    assert "14 citations" in html
    assert "CPR Art. 1° D.O. 24.10.1980" in html and "CPR Art. 8° D.O. 24.10.1980" in html
    assert "CPR Art. 9° D.O. 24.10.1980" not in html, "the list was not capped"
    assert "…and 6 more" in html, "the rest of the margin was dropped without a count"


def test_a_reading_that_already_took_the_margin_out_blames_the_body_not_the_record():
    """Once the reading has the margin column out, an interruption that survives it
    is printed in the body — a word split across a page break. Saying "stored before
    the margin was kept, store it again" there would send the reviewer to re-read a
    document that has already been read, and re-reading cannot join a word the
    document itself splits."""
    out = _render_proof_source(_dto_reading(), _DTO_SENTENCE)
    assert "not in a row" in out["match"]
    assert "the margin column" in out["match"], "the reading's own work was not reported"
    assert "not searched" in out["match"], "the note must say the margin is not searched"
    assert "printed in the document itself" in out["match"], "the body was not named as the cause"
    assert "Store the document again" not in out["match"], "the reviewer was sent to re-read it"


def _load_stored(authority_id: str, *, fails: bool = False, again: bool = False,
                 preload: dict | None = None, replace_while_loading: bool = False) -> dict:
    """Run `loadStoredProofReading` under node against a fake `API`.

    The read-back is the only thing that makes a source stored in an earlier session
    visible, so what it does — one request, for the file that is actually on disk,
    landing in `state.proofSources` and re-rendering the pane — is the contract. It
    is also the only place the page decides *not* to re-render, which a regex over
    the source cannot check.
    """
    record = _dto_reading()
    # Workspace-relative, the way `/api/bundle` reports them: `proofArtefactsFor`
    # matches on `/Authority sources/` inside the path, so a bundle-relative fixture
    # would make every stub look like it has nothing on disk — and a test that
    # proved the read never happens would pass for the wrong reason.
    files = [
        {"name": "CL-001.json", "path": "build/CL-001/CL-001.json", "size": 10},
        {"name": "CL.CPR.Art.19.N3__DTO-100_03-MAY-2023.pdf",
         "path": "build/CL-001/Authority sources/CL.CPR.Art.19.N3__DTO-100_03-MAY-2023.pdf",
         "size": 20},
        {"name": "CL.CPR.Art.19.N3__DTO-100_03-MAY-2023.proof.json",
         "path": "build/CL-001/Authority sources/CL.CPR.Art.19.N3__DTO-100_03-MAY-2023.proof.json",
         "size": 30},
    ]
    body = "throw new Error('the server refused it');" if fails else (
        "return JSON.parse(" + json.dumps(json.dumps(record)) + ");")
    script = "\n".join([
        "const els = {};",
        "function fakeEl(id) { return els[id] || (els[id] = { id, innerHTML: '',"
        " style: {}, value: '', textContent: '', files: null }); }",
        "const document = { getElementById: (id) => fakeEl(id) };",
        "const state = { bundleId: 'CL-001', proofPreview: null, proofReadPending: null,"
        + " proofSources: JSON.parse(" + json.dumps(json.dumps(preload or {})) + "),"
        + " bundle: { files: JSON.parse(" + json.dumps(json.dumps(files)) + ") } };",
        "const log = [];",
        "function pushLog(msg, step, kind) { log.push([msg, kind]); }",
        "const calls = [];",
        "let renders = 0;",
        "function renderProofSource() { renders++; }",
        "const API = { authoritySourceReading: async (p) => { calls.push(p); " + body + " } };",
        _js_function("bundleFiles"),
        _js_function("proofArtefactsFor"),
        _js_function("loadStoredProofReading"),
        (f"const pending = loadStoredProofReading({json.dumps(authority_id)});"),
        (f"loadStoredProofReading({json.dumps(authority_id)});" if again else ""),
        ("state.proofSources[" + json.dumps(authority_id) + "] = { source_content: 'newer' };"
         if replace_while_loading else ""),
        "pending.then(() => console.log(JSON.stringify({",
        "  calls: calls,",
        "  sources: Object.fromEntries(Object.entries(state.proofSources)"
        "    .map(([k, v]) => [k, v && v.source_content ? v.source_content.length : v])),",
        "  renders: renders,",
        "  log: log,",
        "  pending: state.proofReadPending,",
        "})));",
    ])
    return _run_js(script)


def test_a_source_stored_in_an_earlier_session_is_read_back_into_the_pane():
    """The gap this closes: the store returns the text it has just read, so a proof
    stored yesterday was listed on disk with nothing in `state.proofSources`, and the
    pane said "no source loaded" over a document that is right there. One request,
    for a file that is actually on disk, and the pane re-renders with it.
    """
    out = _load_stored("CL.CPR.Art.19.N3")
    assert len(out["calls"]) == 1, out["calls"]
    assert out["calls"][0] == {
        "violation_id": "CL-001", "authority_id": "CL.CPR.Art.19.N3",
        "name": "CL.CPR.Art.19.N3__DTO-100_03-MAY-2023.pdf",
    }, "the read did not name the stored document"
    assert out["sources"] == {"CL.CPR.Art.19.N3": len(_DTO_SPLICED)}, (
        "the record did not reach the page")
    assert out["renders"] == 1, "the pane was not redrawn over the record that arrived"
    assert out["pending"] is None, "the in-flight mark outlived the request"
    assert any("3 margin citations" in row[0] for row in out["log"]), out["log"]


def test_a_record_already_in_hand_is_not_fetched_again_or_fetched_over():
    """Three ways this must not fire: a source the reviewer has just stored (its
    payload is newer than anything on disk), two opens in quick succession (the first
    request is still in flight), and a store that lands *while* the read is out —
    the store is the document the reviewer is looking at, and the record would
    replace it with the one it supersedes."""
    held = {"CL.CPR.Art.19.N3": {"source_content": "lo que ya estaba"}}
    already = _load_stored("CL.CPR.Art.19.N3", preload=held)
    assert already["calls"] == [], "a source already in hand was fetched again"
    assert already["sources"]["CL.CPR.Art.19.N3"] == len("lo que ya estaba")
    assert already["renders"] == 0

    twice = _load_stored("CL.CPR.Art.19.N3", again=True)
    assert len(twice["calls"]) == 1, "a second open while the first was in flight asked twice"

    raced = _load_stored("CL.CPR.Art.19.N3", replace_while_loading=True)
    assert raced["sources"]["CL.CPR.Art.19.N3"] == len("newer"), (
        "a slow read-back overwrote the source the reviewer had just stored"
    )
    assert raced["renders"] == 0, "the pane was redrawn over the newer source"


def test_a_stub_with_no_proof_on_disk_is_not_asked_about():
    """Most stubs have no source stored, and the route refuses an empty name — so a
    read per open would put a 400 in the log for every stub the reviewer looks at."""
    out = _load_stored("CL.SIN.FUENTE")
    assert out["calls"] == [], "a stub with nothing on disk was asked about"
    assert out["log"] == [] and out["renders"] == 0


def test_a_record_that_cannot_be_read_leaves_the_pane_alone_and_says_why():
    """Logged, not put in the verdict: the verdict is about the quote, and a record
    the server cannot read is a fact about the bundle. The modal stays on its neutral
    prompt, which is true — nothing is loaded — and the log names the file."""
    out = _load_stored("CL.CPR.Art.19.N3", fails=True)
    assert out["sources"] == {}
    assert out["renders"] == 0, "the pane was redrawn over a read that failed"
    assert out["pending"] is None, "a failed read left the in-flight mark behind"
    assert any(row[1] == "warn" and "the server refused it" in row[0] for row in out["log"]), out["log"]


def _render_pane_over_a_rebuilt_body(record: dict, quote: str) -> dict:
    """Run `renderProofSource` three times: once to fill the pane, once with nothing
    changed, and once after the pane element has been replaced the way
    `openProofModal` replaces it on every open.

    The third run is the one that used to do nothing. The pane is rebuilt from an
    empty `<div id="proofPreview">` inside a body written from scratch, while
    `state.proofPreview` still holds the last render — so a repeat by stub, text and
    quote was a repeat *of a pane that no longer existed*, and the fresh one was left
    blank for the rest of the session. Called with `_dto_reading()`, this is the
    margin pane: the section it swallowed is the whole reason a stored reading is
    read back at all.
    """
    script = "\n".join([
        "const els = {};",
        "function fakeEl(id) { return els[id] || (els[id] = { id, innerHTML: '',"
        " style: {}, value: '', textContent: '' }); }",
        "const document = { getElementById: (id) => fakeEl(id) };",
        "const state = { proofSources: { 'AUTH-1': JSON.parse("
        + json.dumps(json.dumps(record)) + ") },"
        " violation: { authorities: [] } };",
        _js_function("escapeHtml"),
        _js_function("inputValue"),
        _js_function("proofStatus"),
        _js_function("proofRefusalNote"),
        _js_function("proofPreviewIsStale"),
        _js_const("PROOF_NO_SOURCE"),
        _js_function("highlightQuote"),
        _js_function("proofNumeralPair"),
        _js_function("proofMarginSection"),
        _js_function("renderProofSource"),
        f"fakeEl('proofQuote').value = {json.dumps(quote)};",
        "renderProofSource('AUTH-1');",
        "const first = fakeEl('proofPreview').innerHTML;",
        # Nothing about the pane's inputs has moved, so a marker left in it has to
        # survive: the cache is what keeps a keystroke from re-escaping the document.
        "fakeEl('proofPreview').innerHTML = 'MARKER';",
        "renderProofSource('AUTH-1');",
        "const kept = fakeEl('proofPreview').innerHTML;",
        # `openProofModal` writes a whole new body, so this is the next open.
        "delete els['proofPreview'];",
        "renderProofSource('AUTH-1');",
        "const rebuilt = fakeEl('proofPreview').innerHTML;",
        "console.log(JSON.stringify({ first, kept, rebuilt,"
        " match: fakeEl('proofMatch').innerHTML }));",
    ])
    return _run_js(script)


def test_reopening_a_stub_writes_the_pane_again_rather_than_trusting_the_cache():
    """The cache is keyed on what was rendered, so it has to know *where* it went.

    Opening a stub, waiting for its record to be read back and reopening it left the
    loaded text and the margin blank for the rest of the session — measured in the
    browser against `build/CL-030`: 29,712 characters in the pane after the read, 0
    after the reopen, while the provenance line below it went on naming the document
    and its hash. Only the pane was cached, and only the pane was missing.
    """
    out = _render_pane_over_a_rebuilt_body(_dto_reading(), _DTO_IN_ROW)
    # The quote is a run of the loaded text, so the pane is the "found" branch: a
    # refused quote has no text to show under "Loaded text" and would prove less.
    assert "<mark>" in out["rebuilt"], "the reopened pane lost the highlighted quote"
    assert out["kept"] == "MARKER", (
        "the pane was rebuilt although nothing about its inputs had changed"
    )
    assert len(out["rebuilt"]) == len(out["first"]), (
        "the pane was never written again after the modal body was rebuilt, so "
        "reopening a stub whose record had been read back showed no text and no margin"
    )
    assert "Margin —" in out["rebuilt"] and "3 citations" in out["rebuilt"], (
        "the reopened pane came back without the margin the record holds"
    )
    # The provenance line and the pane come from one render, and the reported bug was
    # the line surviving over a blank pane — so both halves are asserted in the run
    # that rebuilt the body.
    assert f"{len(_DTO_SPLICED)} characters" in out["match"], out["match"]


def _verify_stored(source: dict) -> dict:
    """Run `verifyProofStub` with one source already in hand and nothing typed into
    the form, and report what the protocol was sent.

    `callTool` records its arguments instead of reaching a tool, so the run ends in
    the page's own "Verified." line — which is what makes a guard test able to fail:
    a guard that is missing shows up as a verification that happened.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    authority = {
        "authority_id": "AUTH-1", "type": "statute",
        "instrument": "Constitución Política de la República, Art. 19 N° 3",
        "verified": True, "verification_provenance": None,
    }
    script = "\n".join([
        "const els = {};",
        "function fakeEl(id) { return els[id] || (els[id] = { id, innerHTML: '', style: {},"
        " value: '', textContent: '', files: [],"
        " classList: { add() {}, remove() {} } }); }",
        "const document = { getElementById: (id) => fakeEl(id) };",
        "const logs = [];",
        "function pushLog(m, s, k) { logs.push([String(m), k]); }",
        "const state = { bundleId: 'CL-001', proofSources: {}, proofPreview: null,"
        + " violation: " + json.dumps({"violation_id": "CL-001", "authorities": [authority]})
        + ", settings: {} };",
        _extract_proof_plan(html),
        re.search(r"const PROOF_FIELD_LABEL = \{.*?\n\};", html, re.S).group(0),
        _js_function("proofPlanFor"),
        _js_function("proofFieldId"),
        _js_function("proofValue"),
        _js_function("escapeHtml"),
        _js_function("inputValue"),
        _js_function("proofStatus"),
        "let ingestCalls = 0;",
        "const ingestProofSource = async () => { ingestCalls++; return null; };",
        "const sent = [];",
        "const callTool = async (tool, args) => { sent.push([tool, args]); return { ok: true }; };",
        "const applyResult = () => {};",
        "const openProofModal = () => {};",
        "const applyBundleToStep = () => {};",
        _js_function("verifyProofStub"),
        "state.proofSources['AUTH-1'] = JSON.parse(" + json.dumps(json.dumps(source)) + ");",
        "fakeEl(proofFieldId('instrument')).value = 'Constitución Política de la República';",
        f"fakeEl('proofQuote').value = {json.dumps(_DTO_SENTENCE)};",
        "verifyProofStub('AUTH-1').then(() => console.log(JSON.stringify({",
        "  match: fakeEl('proofMatch').innerHTML,",
        "  ingestCalls: ingestCalls,",
        "  sent: sent,",
        "})));",
    ])
    return _run_js(script)


def test_verifying_from_a_stored_record_is_possible_without_storing_the_source_again():
    """The other half of the read-back, and the reason the record has to be kept by
    reference. `verifyProofStub` uses whatever is in `state.proofSources`, and before
    the read-back there was nothing there for a source stored in an earlier session —
    so it fell through to `ingestProofSource`, found no file, url or paste, and told
    the reviewer there was nothing to store. The stub's recorded `source_uri` alone
    was never enough: the text has to be the text, and it is on disk."""
    out = _verify_stored(_dto_reading())
    assert out["ingestCalls"] == 0, "the stored source was not used; the upload was asked for again"
    assert len(out["sent"]) == 1, out["sent"]
    tool, args = out["sent"][0]
    # Fixed by the stub's type in `PROOF_PLAN`, not chosen from the source: a statute
    # always goes through the external-fetch protocol from this modal.
    assert tool == "verify_statute_external_fetch_tool", tool
    assert args["source_content"] == _DTO_SPLICED, "the protocol was not sent the stored text"
    assert args["source_uri"] == "Authority sources/CL.CPR.Art.19.N3__DTO-100_03-MAY-2023.pdf"
    assert "Verified." in out["match"], out["match"]


def test_a_stored_text_that_no_longer_matches_its_record_is_not_verified():
    """A refusal, not a warning. Verifying hashes `source_content` and writes the
    result into the stub, while the sidecar beside the document goes on stating the
    hash of the text that was read. If the file changed since — which the read route
    reports and cannot prevent — the stub and the record would disagree, both would
    call themselves proof, and nothing would say which hash covers the quote."""
    drifted = dict(_dto_reading(), text_matches_record=False,
                   warnings=["the text on disk no longer hashes to the SHA256 the record gives"])
    out = _verify_stored(drifted)
    assert "no longer matches the record" in out["match"], out["match"]
    assert "Store the document again" in out["match"]
    assert out["sent"] == [], "the protocol was run over text the record contradicts"
    assert "Verified." not in out["match"]

    # An ingest payload is what it says it is and carries no such flag; an absent
    # flag must not read as a mismatch, or no freshly stored source could be
    # verified at all.
    assert "Verified." in _verify_stored(_stored_pdf_source(_DTO_SPLICED))["match"]


def test_the_modal_fills_the_required_fields_from_the_stub_without_overwriting_typed_ones():
    """The protocol refuses to run without a field the stub already carries, so a
    re-verify must not cost the reviewer a re-type of the instrument they verified
    with a moment ago — while a value already in the box stays theirs. This is the
    second refusal behind the one the quote produced: the field was blank."""
    statute = {
        "authority_id": "CL.CPR.Art.19.N3",
        "type": "statute",
        "instrument": "Constitución Política de la República, Art. 19 N° 3",
        "pages": None,
        "verified": True,
        "verification_provenance": {
            "protocol": "statute_external_fetch_v1",
            "source_uri": "Authority sources/CL.CPR.Art.19.N3__DTO-100_03-MAY-2023.pdf",
            "matched_quote": _DTO_SENTENCE,
            "matched_offset": 3348,
            "verified_at": "2026-09-15T08:31:00+00:00",
        },
    }
    opened = _render_proof_modal(statute, statute)
    assert opened["values"]["instrument"] == statute["instrument"], (
        "the required field was left blank although the stub carries it"
    )
    assert opened["values"]["pages"] == "", "a field with nothing recorded was invented"

    typed = _render_proof_modal(statute, statute, preset={"instrument": "Art. 19 N° 3 CPR"})
    assert typed["values"]["instrument"] == "Art. 19 N° 3 CPR", (
        "the stub overwrote a value the reviewer had typed"
    )

    # A day is what the date control accepts, and the stub carries a datetime.
    case = _render_proof_modal(
        {"authority_id": "CL.CS.16622-2025", "type": "jurisprudence",
         "court": "Corte Suprema", "rol": "16.622-2025",
         "decision_date": "2025-04-16T00:00:00Z", "pages": "c. 4",
         "verified": False, "verification_provenance": None},
        None,
    )
    assert case["values"]["decision_date"] == "2025-04-16", "the date control got a datetime"
    assert case["values"]["rol"] == "16.622-2025"
    assert case["values"]["pages"] == "c. 4"


def test_typing_in_the_quote_box_does_not_rebuild_the_loaded_text_every_keystroke():
    """`renderProofSource` runs on the quote box's `input` event, and the pane it
    writes is the whole loaded document, escaped — up to the ingest cap. Rebuilding
    that per keystroke is felt as lag exactly while the reviewer is typing the quote,
    which is the moment they are looking at the pane. The verdict is the half that
    must be rewritten every time, so this pins both halves: the pane survives a
    repeat render untouched (dropped content included), the verdict does not, and a
    quote that actually moved brings the pane back."""
    source = _stored_pdf_source(_DTO_SPLICED)
    script = "\n".join([
        "const els = {};",
        "function fakeEl(id) { return els[id] || (els[id] = { id, innerHTML: '',"
        " style: {}, value: '', textContent: '' }); }",
        "const document = { getElementById: (id) => fakeEl(id) };",
        "const state = { proofSources: { 'AUTH-1': JSON.parse("
        + json.dumps(json.dumps(source)) + ") }, proofPreview: null };",
        _js_function("escapeHtml"),
        _js_function("inputValue"),
        _js_function("proofStatus"),
        _js_function("proofRefusalNote"),
        _js_function("proofPreviewIsStale"),
        _js_const("PROOF_NO_SOURCE"),
        _js_function("highlightQuote"),
        _js_function("proofNumeralPair"),
        _js_function("proofMarginSection"),
        _js_function("renderProofSource"),
        "fakeEl('proofQuote').value = 'garantías de un procedimiento';",
        "renderProofSource('AUTH-1');",
        "const first = fakeEl('proofPreview').innerHTML;",
        # A sentinel stands in for "this pane was not rewritten": if the render ran,
        # it is gone, and nothing about the real markup can be mistaken for it. The
        # verdict gets one too, so a guard that swallowed it is visible.
        "fakeEl('proofPreview').innerHTML = 'SENTINEL';",
        "fakeEl('proofMatch').innerHTML = 'SENTINEL';",
        "renderProofSource('AUTH-1');",
        "const same = { preview: fakeEl('proofPreview').innerHTML,"
        " verdict: fakeEl('proofMatch').innerHTML };",
        "fakeEl('proofQuote').value = 'procedimiento y una investigación';",
        "renderProofSource('AUTH-1');",
        "console.log(JSON.stringify({",
        "  first: first.length,",
        "  previewKept: same.preview === 'SENTINEL',",
        "  verdictRewritten: same.verdict !== 'SENTINEL',",
        "  rebuilt: fakeEl('proofPreview').innerHTML !== 'SENTINEL',",
        "}));",
    ])
    out = _run_js(script)
    assert out["first"] > 0, "the pane was never rendered at all"
    assert out["previewKept"], "the loaded text was rebuilt for a keystroke that changed nothing"
    assert out["verdictRewritten"], "the verdict was swallowed by the pane's guard"
    assert out["rebuilt"], "a quote that moved left the pane showing the old highlight"


def test_deleting_the_source_clears_the_verdict_with_the_pane():
    """A verdict is about a *loaded* text, so it must not outlive it.

    Deleting a stored source empties the pane and then re-renders, and the render
    used to return from the no-source branch without touching `#proofMatch` — so the
    modal went on displaying the last verdict, "Found verbatim at offset 98." over an
    empty pane, for a document that was no longer loaded. Pinned by value, and
    against the page's own prompt string: the point is that the cleared line is the
    neutral one the markup ships, not a self-consistent substitute for it.
    """
    source = {
        "source_uri": "Authority sources/AUTH-1__page.html",
        "source_content": "Corresponderá al legislador establecer siempre las garantías.",
        "text_source": "fetched",
        "chars": 61,
        "warnings": [],
    }
    script = "\n".join([
        "const els = {};",
        "function fakeEl(id) { return els[id] || (els[id] = { id, innerHTML: '',"
        " style: {}, value: '', textContent: '' }); }",
        "const document = { getElementById: (id) => fakeEl(id) };",
        "const state = { proofSources: { 'AUTH-1': JSON.parse("
        + json.dumps(json.dumps(source)) + ") }, proofPreview: null };",
        _js_function("escapeHtml"),
        _js_function("inputValue"),
        _js_function("proofStatus"),
        _js_function("proofRefusalNote"),
        _js_function("proofPreviewIsStale"),
        _js_const("PROOF_NO_SOURCE"),
        _js_function("highlightQuote"),
        _js_function("proofNumeralPair"),
        _js_function("proofMarginSection"),
        _js_function("renderProofSource"),
        "fakeEl('proofQuote').value = 'establecer siempre las garantías';",
        "renderProofSource('AUTH-1');",
        "const loaded = { match: fakeEl('proofMatch').innerHTML,"
        " preview: fakeEl('proofPreview').innerHTML.length };",
        "delete state.proofSources['AUTH-1'];",
        "renderProofSource('AUTH-1');",
        "console.log(JSON.stringify({",
        "  prompt: PROOF_NO_SOURCE,",
        "  loaded: loaded,",
        "  afterMatch: fakeEl('proofMatch').innerHTML,",
        "  afterColor: fakeEl('proofMatch').style.color,",
        "  afterPreview: fakeEl('proofPreview').innerHTML,",
        "}));",
    ])
    out = _run_js(script)
    assert out["loaded"]["preview"] > 0, "the pane never held the source in the first place"
    assert out["afterPreview"] == "", "the pane was not cleared"
    assert out["afterMatch"] == out["prompt"], (
        "the verdict outlived the source: the modal still claims a match for a "
        "document that is no longer loaded"
    )
    assert out["afterColor"] == "", (
        "the neutral prompt was written as a failure; an empty form is not an error"
    )


def test_the_proof_modal_reads_back_every_field_it_renders():
    """`proofFieldId` is the only thing standing between a rendered input and the
    argument sent for it, so an unnamed field is a silently dropped parameter."""
    html = HTML_PATH.read_text(encoding="utf-8")
    plan = _extract_proof_plan(html)
    grouped = re.findall(r"fields: \[(.*?)\]", plan, re.S)
    assert grouped, "no `fields:` list found in PROOF_PLAN"
    names = sorted({n.strip().strip("'\"") for group in grouped for n in group.split(",") if n.strip()})
    script = "\n".join([
        _js_function("proofFieldId"),
        f"console.log(JSON.stringify({json.dumps(names)}.map(proofFieldId)));",
    ])
    ids = _run_js(script)
    assert len(ids) == len(names), "a name rendered no id at all"
    assert {"proofRol", "proofDecisionDate", "proofHoldingSummary"} <= set(ids)


#: A verified doctrine stub, plus the same stub as it would still look on disk
#: before anything is written. The write gap is the point of the two tests below.
_PROOF_AUTHORITY = {
    "authority_id": "CL.DOCTRINE.ETCHEBERRY",
    "type": "doctrine",
    "proposition_to_verify": "o dano moral coletivo prescinde da prova de dor individual",
    "supports": ["E1"],
    "verified": True,
    "verification_provenance": {
        "protocol": "human_attested_v1",
        "source_uri": "Authority sources/CL.DOCTRINE.ETCHEBERRY__note.text.txt",
        "source_sha256": "8e9b1322" * 8,
        "matched_quote": "o dano moral coletivo prescinde da prova de dor individual",
        "matched_offset": 64,
        "verified_at": "2026-09-15T10:30:39+00:00",
        "notes": "attested by: revisor@example.test",
    },
}
_PROOF_ON_DISK_BEFORE = {
    "authority_id": "CL.DOCTRINE.ETCHEBERRY",
    "type": "doctrine",
    "verified": False,
    "verification_provenance": None,
}


def _render_proof_modal(authority: dict, disk_authority: dict | None,
                        preset: dict | None = None) -> dict:
    """Run `openProofModal` under node against a fake document.

    Which of the two states the modal is in is decided at runtime by comparing the
    in-memory stub with the one on disk, so neither a regex over the source nor a
    scan of the template can say whether the reviewer is shown "in this page only"
    or "already written" — the body has to be rendered.

    `preset` types values into the form before it opens, so "the stub fills the
    blanks" is asserted against a box that is *not* blank rather than only against
    the empty case. Every field the plan renders is returned, keyed by name.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    violation = {"violation_id": "CL-900", "authorities": [authority]}
    # `state.bundle` is the bundle payload, so the copy of the violation that
    # arrived with it lives one level down — the modal compares *that* with the
    # stub in hand, which is the whole question this test asks.
    disk = {"violation_id": "CL-900",
            "authorities": [disk_authority] if disk_authority else []}
    state = {"violation": violation, "bundle": {"violation": disk, "files": []},
             "bundleId": "CL-900", "proofSources": {}, "proofAuthority": "",
             "settings": {}}
    script = "\n".join([
        "const els = {};",
        "function fakeEl(id) { return els[id] || (els[id] = { id, innerHTML: '', style: {},"
        " value: '', textContent: '', files: {}, checked: false,"
        " classList: { add() {}, remove() {} }, querySelectorAll: () => [] }); }",
        "const document = { getElementById: (id) => fakeEl(id) };",
        "const logs = [];",
        "function pushLog(m) { logs.push(String(m)); }",
        f"const state = {json.dumps(state)};",
        _extract_proof_plan(html),
        re.search(r"const PROOF_FIELD_LABEL = \{.*?\n\};", html, re.S).group(0),
        _js_function("proofPlanFor"),
        _js_function("proofFieldId"),
        _js_function("proofValue"),
        _js_function("proofIsOnDisk"),
        _js_function("proofArtefactsFor"),
        _js_function("proofRecordSection"),
        _js_function("proofArtefactSection"),
        _js_function("bundleFiles"),
        _js_function("escapeHtml"),
        _js_function("shortId"),
        _js_function("fmtStamp"),
        _js_function("fmtBytes"),
        _js_function("setInput"),
        _js_function("inputValue"),
        _js_function("associateLabels"),
        _js_function("proofStatus"),
        _js_function("proofRefusalNote"),
        _js_function("proofPreviewIsStale"),
        _js_const("PROOF_NO_SOURCE"),
        _js_function("highlightQuote"),
        _js_function("proofNumeralPair"),
        _js_function("proofMarginSection"),
        _js_function("renderProofSource"),
        # Stubbed, not lifted: this harness is about the modal's fields and disk
        # state, and the read-back would need a `fetch`. The page's own function is
        # exercised against a fake `API` in its own test.
        "const loadStoredProofReading = async () => {};",
        _js_function("openProofModal"),
        "Object.keys(PROOF_FIELD_LABEL).forEach(n => {"
        f"  const v = {json.dumps(preset or {})}[n];"
        "  if (v !== undefined) fakeEl(proofFieldId(n)).value = v;"
        "});",
        f"openProofModal({json.dumps(authority.get('authority_id'))});",
        "console.log(JSON.stringify({",
        "  body: fakeEl('modalBody').innerHTML,",
        "  onDisk: proofIsOnDisk(state.violation.authorities[0]),",
        "  values: Object.fromEntries(Object.keys(PROOF_FIELD_LABEL)",
        "    .map(n => [n, fakeEl(proofFieldId(n)).value])),",
        "}));",
    ])
    return _run_js(script)


def test_a_verification_that_is_only_in_the_page_is_not_presented_as_saved():
    """Every build/verify tool returns an updated violation and writes nothing —
    S11's "Build package" is the write gate — so a stub verified from S6 lives in
    the browser alone until something writes it. The modal used to say the stub
    "now carries the provenance", which is true of the page and false of the
    bundle: reload and it is unverified again.
    """
    unsaved = _render_proof_modal(_PROOF_AUTHORITY, _PROOF_ON_DISK_BEFORE)
    assert unsaved["onDisk"] is False, "a stub the bundle does not carry read as saved"
    assert "In this page only, not in the bundle" in unsaved["body"]
    assert 'data-action="proof-save"' in unsaved["body"], (
        "the reviewer is told the verification is unwritten but given no way to write it"
    )
    assert "Already verified" in unsaved["body"], "the record vanished from the unwritten state"

    saved = _render_proof_modal(_PROOF_AUTHORITY, _PROOF_AUTHORITY)
    assert saved["onDisk"] is True, "a stub the bundle already carries read as unwritten"
    assert "In this page only" not in saved["body"]
    assert 'data-action="proof-save"' not in saved["body"], (
        "a second write of an identical record is offered as if it were needed"
    )
    assert "Already verified" in saved["body"]

    # Absent from the bundle entirely — the same one write is still owed, and the
    # modal must not mistake "no copy" for "copy matches".
    absent = _render_proof_modal(_PROOF_AUTHORITY, None)
    assert absent["onDisk"] is False
    assert 'data-action="proof-save"' in absent["body"]

    # Verified on both sides but against a different hash: the page was edited
    # after the write, so the bundle does not carry what the modal is showing.
    drifted = _render_proof_modal(
        _PROOF_AUTHORITY,
        {**_PROOF_AUTHORITY,
         "verification_provenance": {
             **_PROOF_AUTHORITY["verification_provenance"], "source_sha256": "0" * 64}},
    )
    assert drifted["onDisk"] is False, "a stale hash on disk passed as the same record"
    assert 'data-action="proof-save"' in drifted["body"]


def test_saving_persists_through_the_tool_and_then_reads_the_file_back():
    """The save is the one write in this page, so it is asserted at the seam:
    which tool, which arguments, and that the page re-reads the bundle instead of
    assuming the write landed.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    state = {"violation": _PROOF_AUTHORITY, "bundle": {**_PROOF_ON_DISK_BEFORE, "files": []},
             "bundleId": "CL-900", "settings": {"bundleRoot": "build/CL-900"}}
    script = "\n".join([
        "const calls = [];",
        "const status = [];",
        f"const state = {json.dumps(state)};",
        "state.violation = { violation_id: 'CL-900', authorities: ["
        + json.dumps(_PROOF_AUTHORITY) + "] };",
        "async function callTool(name, args) {",
        "  calls.push({ kind: 'tool', name, root: args.bundle_root });",
        "  if (name === 'write_violation_json_tool' && FAILING) throw new Error('read-only filesystem');",
        "  return { path: args.bundle_root + '/CL-900.json' };",
        "}",
        "async function loadBundle(id) {",
        "  calls.push({ kind: 'loadBundle', id });",
        "  // Simulate the write landing: the file now carries what the page held.",
        "  state.bundle = { violation: state.violation, files: ["
        "    { path: 'Authority sources/CL.DOCTRINE.ETCHEBERRY__note.text.txt',"
        "      name: 'CL.DOCTRINE.ETCHEBERRY__note.text.txt', size: 168 }] };",
        "}",
        "function applyBundleToStep(id) { calls.push({ kind: 'step', id }); }",
        "function openProofModal(id) { calls.push({ kind: 'modal', id }); }",
        "function proofStatus(html, isError) { status.push({ html: String(html), isError }); }",
        "function pushLog(m) { calls.push({ kind: 'log', m: String(m) }); }",
        "function escapeHtml(s) { return String(s); }",
        _js_function("describeSync"),
        _js_function("persistProofAuthority"),
        "const FAILING = " + "false" + ";",
        "(async () => {",
        "  await persistProofAuthority('CL.DOCTRINE.ETCHEBERRY');",
        "  console.log(JSON.stringify({ calls, status, violations: state.violation }));",
        "})();",
    ])
    # The failure arm re-runs the same body with the write rejecting, because a
    # save that fails silently is worse than no save button at all.
    failing_script = script.replace("const FAILING = false;", "const FAILING = true;")
    out = _run_js(script)
    tool_calls = [c for c in out["calls"] if c.get("kind") == "tool"]
    assert [c["name"] for c in tool_calls] == ["write_violation_json_tool"], (
        "the save must write, and write through the same tool S11 runs"
    )
    assert tool_calls[0]["root"] == "build/CL-900", "the bundle root the form is showing was not used"
    assert [c["kind"] for c in out["calls"]].index("loadBundle") > 0, (
        "the page never re-read the bundle, so it cannot know the write landed"
    )
    assert out["calls"][-1]["kind"] == "modal", "the modal was not re-rendered from what is on disk"
    assert out["violations"]["authorities"][0]["verified"] is True, (
        "the write must not cost the verification it is saving"
    )
    assert out["status"][-1]["isError"] is False and "Saved" in out["status"][-1]["html"]

    bad = _run_js(failing_script)
    bad_status = bad["status"][-1]
    assert bad_status["isError"] is True, "a rejected write was reported as success"
    assert "Could not write the bundle" in bad_status["html"]
    assert not [c for c in bad["calls"] if c.get("kind") == "loadBundle"], (
        "a failed write must not re-read the bundle and pretend to be in sync"
    )
    assert not [c for c in bad["calls"] if c.get("kind") == "modal"]


def test_one_stored_source_gets_one_delete_button():
    """The grouping the button depends on, and the reason it is not per file.

    A stored source is the document, its `.proof.json` sidecar and the matched
    `.text.txt`, all off one stem. Read as three separate sources, the page would
    offer three buttons for one document — and deleting the *document* alone
    would leave the sidecar behind claiming a proof that is no longer there.
    Arming is matched on the stem for the same reason: a reviewer who clicks the
    row they can read (the sidecar) must arm the whole source, not a fragment.
    """
    prefix = "build/CL-900/Authority sources/CL.DOCTRINE.ETCHEBERRY__note"
    files = [
        {"path": f"{prefix}.pdf", "name": "CL.DOCTRINE.ETCHEBERRY__note.pdf", "kind": "file", "size": 2048},
        {"path": f"{prefix}.proof.json", "name": "CL.DOCTRINE.ETCHEBERRY__note.proof.json", "kind": "file", "size": 1026},
        {"path": f"{prefix}.text.txt", "name": "CL.DOCTRINE.ETCHEBERRY__note.text.txt", "kind": "file", "size": 32002},
        {"path": "build/CL-900/Authority sources/CL.DOCTRINE.OTRO__x.txt",
         "name": "CL.DOCTRINE.OTRO__x.txt", "kind": "file", "size": 10},
    ]
    state = {"bundle": {"files": files}, "proofDelete": None}
    script = "\n".join([
        f"const state = {json.dumps(state)};",
        _js_function("bundleFiles"),
        _js_function("proofArtefactsFor"),
        _js_function("proofStem"),
        _js_function("proofArtefactGroup"),
        _js_function("proofArtefactSection"),
        _js_function("escapeHtml"),
        _js_function("fmtBytes"),
        "const armedFromSidecar = () => {",
        "  state.proofDelete = { authority: 'CL.DOCTRINE.ETCHEBERRY',",
        "    name: 'CL.DOCTRINE.ETCHEBERRY__note.proof.json' };",
        "  return proofArtefactSection('CL.DOCTRINE.ETCHEBERRY');",
        "};",
        "const armedFromNowhere = () => {",
        "  state.proofDelete = { authority: 'CL.DOCTRINE.OTRO', name: 'CL.DOCTRINE.OTRO__x.txt' };",
        "  return proofArtefactSection('CL.DOCTRINE.ETCHEBERRY');",
        "};",
        "console.log(JSON.stringify({",
        "  idle: proofArtefactSection('CL.DOCTRINE.ETCHEBERRY'),",
        "  armed: armedFromSidecar(),",
        "  elsewhere: armedFromNowhere(),",
        "}));",
    ])
    out = _run_js(script)
    assert out["idle"].count('data-action="proof-delete"') == 1, (
        "one stored source must offer exactly one delete control, not one per file"
    )
    assert 'data-name="CL.DOCTRINE.ETCHEBERRY__note.pdf"' in out["idle"], (
        "the button did not name the source by its document"
    )
    for name in ("note.pdf", "note.proof.json", "note.text.txt"):
        assert f"CL.DOCTRINE.ETCHEBERRY__{name}" in out["idle"], (
            "a file of the source is not shown, so the reviewer cannot see what a delete takes"
        )
    assert out["armed"].count('data-action="proof-delete-now"') == 1
    assert "Delete 3 files for good" in out["armed"], (
        "arming from the sidecar's row did not arm the whole source, so the count "
        "on the button would not match what gets unlinked"
    )
    assert "Delete 3 files for good" not in out["elsewhere"], (
        "an armed delete for another stub rendered as armed here"
    )
    assert out["elsewhere"].count('data-action="proof-delete"') == 1


def test_re_reading_the_listing_does_not_discard_an_unwritten_verification():
    """Why the listing refresh is not a `loadBundle()` call.

    `bundleFiles()` reads the listing captured by the last `loadBundle()`, so a
    source stored a moment ago is invisible without a re-read. But `loadBundle()`
    also replaces `state.violation` with the copy on disk — which is exactly the
    stale copy a verification that has not been written yet would be reverted to.
    """
    state = {"violation": _PROOF_AUTHORITY, "bundleId": "CL-900",
             "bundle": {"violation": _PROOF_ON_DISK_BEFORE, "files": []}, "settings": {}}
    # The listing carries the directory itself; an artefact is a file, and a
    # sizeless directory row in the list is not something the reviewer can open.
    fresh_file = {"path": "build/CL-900/Authority sources/CL.DOCTRINE.ETCHEBERRY__note.text.txt",
                  "name": "CL.DOCTRINE.ETCHEBERRY__note.text.txt", "kind": "file", "size": 168}
    fresh_dir = {"path": "build/CL-900/Authority sources", "name": "Authority sources",
                 "kind": "directory", "size": None}
    script = "\n".join([
        f"const state = {json.dumps(state)};",
        "const logs = [];",
        "function pushLog(m) { logs.push(String(m)); }",
        f"const API = {{ bundle: async (id) => ({{ id, files: [{json.dumps(fresh_dir)}, {json.dumps(fresh_file)}],"
        f" violation: {json.dumps(_PROOF_ON_DISK_BEFORE)} }}) }};",
        _js_function("bundleFiles"),
        _js_function("proofArtefactsFor"),
        _js_function("proofStem"),
        _js_function("proofArtefactGroup"),
        _js_function("proofArtefactSection"),
        _js_function("escapeHtml"),
        _js_function("fmtBytes"),
        _js_function("refreshBundleFiles"),
        "(async () => {",
        "  await refreshBundleFiles();",
        "  console.log(JSON.stringify({",
        "    files: bundleFiles().length,",
        "    mine: proofArtefactsFor('CL.DOCTRINE.ETCHEBERRY').length,",
        "    verified: state.violation.verified,",
        "    onDiskViolationUntouched: state.bundle.violation.verified === false,",
        "    // The fallback list (a stub with no file of its own yet) is where the",
        "    // directory entry would otherwise be rendered as an artefact.",
        "    fallback: proofArtefactSection('CL.NO.SUCH.STUB'),",
        "    own: proofArtefactSection('CL.DOCTRINE.ETCHEBERRY'),",
        "  }));",
        "})();",
    ])
    out = _run_js(script)
    assert out["files"] == 2, "the fresh listing did not arrive"
    assert out["mine"] == 1, (
        "the source stored a moment ago is still missing from the artefact list"
    )
    assert 'rr-detail">build/CL-900/Authority sources <' not in out["fallback"], (
        "the directory was listed as an artefact, with no size and nothing to open"
    )
    assert "build/CL-900/Authority sources/CL.DOCTRINE.ETCHEBERRY__note.text.txt" in out["fallback"]
    assert out["verified"] is True, (
        "re-reading the listing reverted the verification the page was holding"
    )
    # The bundle-wide fallback is somebody else's proof: the route refuses to
    # delete by a name that is not this stub's, so offering the button there would
    # be a control that cannot work.
    assert "proof-delete" not in out["fallback"], (
        "another stub's proof was offered for deletion"
    )
    assert 'data-action="proof-delete"' in out["own"], (
        "this stub's own stored source has no way to be replaced"
    )


def test_deleting_a_stored_source_replaces_the_payload_and_says_what_it_broke():
    """Replacing a proof is a delete and then a store, in that order.

    Two things this asserts that a reviewer cannot check by reading the button:
    the loaded payload is dropped, because it was read out of the file that just
    went away and reusing it would record a `source_uri` naming a deleted
    document; and a verification that already names that file is called out,
    because the stub's JSON keeps citing it until the replacement is verified.
    """
    rel = "Authority sources/CL.DOCTRINE.ETCHEBERRY__note.pdf"
    deleted = [rel, "Authority sources/CL.DOCTRINE.ETCHEBERRY__note.proof.json",
               "Authority sources/CL.DOCTRINE.ETCHEBERRY__note.text.txt"]
    authority = {**_PROOF_AUTHORITY,
                 "verification_provenance": {"source_uri": rel, "matched_quote": "la ley"}}
    state = {"bundleId": "CL-900", "settings": {}, "violation": {"authorities": [authority]},
             "bundle": {"violation": _PROOF_ON_DISK_BEFORE, "files": []},
             "proofSources": {"CL.DOCTRINE.ETCHEBERRY": {"source_content": "text from the deleted file"}},
             "proofDelete": {"authority": "CL.DOCTRINE.ETCHEBERRY", "name": "CL.DOCTRINE.ETCHEBERRY__note.pdf"},
             "proofAuthority": "CL.DOCTRINE.ETCHEBERRY"}
    script = "\n".join([
        "const calls = [];",
        "const status = [];",
        f"const state = {json.dumps(state)};",
        "function pushLog(m) { calls.push({ kind: 'log', m: String(m) }); }",
        "function proofStatus(html, isError) { status.push({ html: String(html), isError }); }",
        "function escapeHtml(s) { return String(s); }",
        "function fmtBytes(n) { return n + ' B'; }",
        "function applyBundleToStep(id) { calls.push({ kind: 'step', id }); }",
        "function renderProofSource(id) { calls.push({ kind: 'renderSource', id }); }",
        "function renderProofArtefacts(id) { calls.push({ kind: 'renderArtefacts', id }); }",
        "async function refreshBundleFiles() { calls.push({ kind: 'refresh' }); }",
        "const API = { authoritySourceDelete: async (payload) => {",
        "  calls.push({ kind: 'delete', payload });",
        "  if (FAILING) throw new Error('cannot unlink: read-only file system');",
        f"  return {{ ok: true, deleted: {json.dumps(deleted)}, freed_bytes: 2048 }};",
        "} };",
        _js_function("deleteProofSource"),
        "const FAILING = false;",
        "(async () => {",
        "  await deleteProofSource('CL.DOCTRINE.ETCHEBERRY', 'CL.DOCTRINE.ETCHEBERRY__note.pdf');",
        "  console.log(JSON.stringify({ calls, status, state }));",
        "})();",
    ])
    failing_script = script.replace("const FAILING = false;", "const FAILING = true;")
    out = _run_js(script)

    deletes = [c for c in out["calls"] if c.get("kind") == "delete"]
    assert len(deletes) == 1, "the removal must be one request, naming one source"
    assert deletes[0]["payload"] == {
        "violation_id": "CL-900",
        "authority_id": "CL.DOCTRINE.ETCHEBERRY",
        "name": "CL.DOCTRINE.ETCHEBERRY__note.pdf",
    }, "the route was not told which stub, which bundle, and which stored source"
    kinds = [c["kind"] for c in out["calls"]]
    assert "refresh" in kinds and "renderArtefacts" in kinds, (
        "the listing was not re-read, so the removed files stay on screen"
    )
    assert out["state"]["proofSources"] == {}, (
        "a payload read out of the deleted file was kept, so the next verify can "
        "record a source_uri naming a document that is gone"
    )
    assert out["state"]["proofDelete"] is None, "the armed delete was not cleared"
    last = out["status"][-1]
    assert last["isError"] is False and "Removed 3 files" in last["html"]
    assert rel in last["html"], (
        "the stub still cites the removed file and the page did not say so"
    )

    bad = _run_js(failing_script)
    assert bad["status"][-1]["isError"] is True, "a refused unlink was reported as success"
    assert "Could not remove" in bad["status"][-1]["html"]
    assert "CL.DOCTRINE.ETCHEBERRY" in bad["state"]["proofSources"], (
        "a failed removal threw away the payload for a source that is still on disk"
    )
    assert not [c for c in bad["calls"] if c.get("kind") == "refresh"], (
        "a failed removal re-read the listing as though the files were gone"
    )


# ---------------------------------------------------------------------------
# Form fields must be nameable
# ---------------------------------------------------------------------------

def _render_settings_env(settings: dict, secrets: dict | None = None) -> str:
    """The rows the page's own `hydrateSettingsEnv` writes for these settings.

    The host is a stub that keeps the HTML string instead of parsing it — the
    function under test *builds* a string, so asserting on that string is
    asserting on what the browser is handed. `escapeHtml` and `hintRow` are
    pulled from the page as well, so nothing here restates the page's escaping.

    Keys are lowercase because that is what `cfg.settings` carries (the row
    heading is the only uppercased part).
    """
    script = "\n".join([
        "const captured = {};",
        "const document = { getElementById: () => ({ set innerHTML(v) { captured.html = v; } }) };",
        _js_function("escapeHtml"),
        _js_function("hintRow"),
        _js_function("hydrateSettingsEnv"),
        f"hydrateSettingsEnv({json.dumps({'settings': settings, 'secrets': secrets or {}})})",
        "console.log(JSON.stringify(captured.html));",
    ])
    return _run_js(script)


def test_every_effective_setting_row_names_its_field():
    """Chromium's `genericFormEmptyIdAndNameAttributesForInputError` fires once
    per control with neither an `id` nor a `name`; the Issues panel showed one
    per row here.

    These ids cannot come from `associateLabels`. That helper walks `<label>`
    elements and takes the control out of `label.parentElement`, so it needs the
    label and the control to share an immediate parent — a settings row put the
    label text in a `<div>` beside the input, which is why all 15 rows stayed
    anonymous. The host is also rewritten with `innerHTML` on every settings
    refresh, so the builder has to name its own fields.
    """
    html = _render_settings_env({"llm_model": "deepseek-chat", "llm_max_tokens": "16000"})
    inputs = re.findall(r"<input[^>]*>", html)
    assert len(inputs) == 2, f"expected one input per setting, got {html}"
    ids = []
    for tag in inputs:
        found = re.search(r'\bid="([^"]+)"', tag)
        assert found, f"a settings field has no id, so Chromium reports it: {tag}"
        assert re.search(r'\bname="([^"]+)"', tag), f"a settings field has no name: {tag}"
        ids.append(found.group(1))
    assert sorted(ids) == ["env-llm_max_tokens", "env-llm_model"], (
        f"the id is not derived from the setting name: {ids}"
    )


def test_a_settings_label_points_at_its_field():
    """An id alone silences the warning; a `<label for>` is the point of it. The
    label element is what `associateLabels` would have needed to see in the first
    place, so this also guards the row markup from regressing to a `<div>`."""
    html = _render_settings_env({"llm_model": "deepseek-chat"})
    ids = re.findall(r'<input[^>]*\bid="([^"]+)"', html)
    fors = re.findall(r'<label[^>]*\bfor="([^"]+)"', html)
    assert ids and fors == ids, f"the field is not labelled by the row: {html}"


class _StartTags(HTMLParser):
    """Every start tag with its parsed attributes, so an assertion can see the
    attribute *list* the browser will see rather than a regex's view of one.

    A regex capture like ``id="([^"]+)"`` cannot tell a well-formed id from one
    that closed its attribute early: the injected quote just ends the capture and
    the malformed tag reads as correct. Verified with the mutation harness — that
    is the one mutation this test missed before it parsed.
    """

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.tags: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    handle_startendtag = handle_starttag


def _input_attrs(html: str) -> list[dict]:
    parser = _StartTags()
    parser.feed(html)
    return [attrs for tag, attrs in parser.tags if tag == "input"]


def test_a_setting_name_cannot_break_out_of_its_id_attribute():
    """The id is interpolated straight into the tag, so it must be derived from a
    restricted character set: a setting name is server-supplied text, and one
    containing a quote would otherwise close the attribute and add its own."""
    html = _render_settings_env({'EVIL" ONFOCUS="x<y>': "v"})
    attrs = _input_attrs(html)
    assert len(attrs) == 1, html
    assert set(attrs[0]) == {"id", "name", "type", "value", "placeholder", "autocomplete", "readonly"}, (
        f"a setting name closed an attribute and started another: {attrs[0]}"
    )
    assert re.fullmatch(r"env-[A-Za-z0-9_-]*", attrs[0]["id"]), (
        f"a setting name reached the id attribute unsanitised: {attrs[0]['id']!r}"
    )
