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
EXPECTED_API_ROUTES = {"/", "/api/health", "/api/tools", "/api/tool", "/api/catalog", "/api/sources", "/api/source-transcript", "/api/framework-article", "/api/browse", "/api/bundles", "/api/bundle", "/api/schema", "/api/settings", "/api/authority-source"}


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
    opening = html.index("{", match.start())
    depth = 0
    for i in range(opening, len(html)):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                return html[match.start() : i + 1]
    raise AssertionError(f"unbalanced braces in {name}()")


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


def _render_proof_source(source: dict, quote: str) -> dict:
    """Run `renderProofSource` under node against a fake document.

    The status line is the only place the page says which copy of the source was
    searched, so it cannot be asserted with a regex over its own source: the
    branch that runs is chosen at runtime by whether the quote was found.
    """
    script = "\n".join([
        "const els = {};",
        "function fakeEl(id) { return els[id] || (els[id] = { id, innerHTML: '',"
        " style: {}, value: '', textContent: '' }); }",
        "const document = { getElementById: (id) => fakeEl(id) };",
        "const state = { proofSources: { 'AUTH-1': JSON.parse("
        + json.dumps(json.dumps(source)) + ") } };",
        _js_function("escapeHtml"),
        _js_function("inputValue"),
        _js_function("proofStatus"),
        _js_function("highlightQuote"),
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


def _render_proof_modal(authority: dict, disk_authority: dict | None) -> dict:
    """Run `openProofModal` under node against a fake document.

    Which of the two states the modal is in is decided at runtime by comparing the
    in-memory stub with the one on disk, so neither a regex over the source nor a
    scan of the template can say whether the reviewer is shown "in this page only"
    or "already written" — the body has to be rendered.
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
        _js_function("highlightQuote"),
        _js_function("renderProofSource"),
        _js_function("openProofModal"),
        "openProofModal('CL.DOCTRINE.ETCHEBERRY');",
        "console.log(JSON.stringify({",
        "  body: fakeEl('modalBody').innerHTML,",
        "  onDisk: proofIsOnDisk(state.violation.authorities[0]),",
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
