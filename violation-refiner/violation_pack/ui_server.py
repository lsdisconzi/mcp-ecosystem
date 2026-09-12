"""Browser bridge for the ViolationRefiner UI.

The UI (`ui/violation_refiner.html`) is a single static page. This module makes
it *live* by mounting a small JSON API onto the same FastMCP app that serves
the MCP protocol, so `./start.sh` gives you both on one port:

    GET  /              the UI itself (same origin as the API — no CORS dance)
    GET  /api/health    runtime probe: interpreter, extras, tool count
    GET  /api/tools     all registered tools with their JSON Schemas
    POST /api/tool      invoke one tool: {"name": ..., "args": {...}}
    GET  /api/catalog   the mcp_catalog payload
    GET  /api/sources   rendered transcripts and law caches under data/
    GET  /health        (already present — unchanged)

Design notes
------------
* **No duplicated dispatch.** Every call routes through the live FastMCP
  ``ToolManager`` built by :func:`violation_pack.mcp_server.build_server`. Add a
  tool to the server and it appears in the UI automatically; there is no second
  list to keep in sync.
* **Structure is preserved.** ``call_tool`` returns the tool's real return value
  (a plain JSON-safe dict), not an MCP content envelope, so the UI receives the
  same shapes the library produces.
* **Destructive tools stay gated.** Anything whose catalog tags include
  ``destructive`` must be invoked with ``"confirm": true``; the bridge refuses
  otherwise and the UI's typed-confirmation box is what supplies it.
* **Optional by construction.** Needs ``starlette`` + ``mcp`` (both from the
  ``[mcp]`` extra). Import is lazy so the core package stays Pydantic-only.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# UI asset resolution
# ---------------------------------------------------------------------------

UI_FILENAME = "violation_refiner.html"

#: Extra env var a UI build may rely on that is *not* read by `config.py`, so it
#: is deliberately not advertised in `.env.example`.
UI_ENV_VAR = "VIOLATION_PACK_UI"


def find_ui_path() -> Path | None:
    """Locate the UI HTML, in priority order:

    1. ``VIOLATION_PACK_UI`` (explicit override — a path to the file or its dir)
    2. ``<repo root>/ui/violation_refiner.html``, walking up from the package
    3. ``<package dir>/ui/violation_refiner.html``

    Returns ``None`` when the file is absent, which is not an error: the MCP
    server still works, and ``/api/health`` reports ``ui.present = false``.
    """
    override = os.environ.get(UI_ENV_VAR)
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_dir():
            candidate = candidate / UI_FILENAME
        if candidate.is_file():
            return candidate

    here = Path(__file__).resolve().parent
    for base in (here, *here.parents):
        candidate = base / "ui" / UI_FILENAME
        if candidate.is_file():
            return candidate
    return None


def find_data_root() -> Path | None:
    """Locate the workspace data directory next to the UI repository."""
    here = Path(__file__).resolve().parent
    for base in (here, *here.parents):
        candidate = base / "data"
        if (candidate / "transcripts" / "html").is_dir() and (candidate / "law").is_dir():
            return candidate
    return None


def _resolve_transcript_uri(uri: str) -> Path | None:
    """Resolve a discovered transcript URI without allowing path traversal."""
    data_root = find_data_root()
    if data_root is None:
        return None
    candidate = Path(uri)
    if candidate.is_absolute():
        return None
    if candidate.parts[:2] != ("data", "transcripts") or candidate.suffix.lower() != ".html":
        return None
    resolved = (data_root.parent / candidate).resolve()
    transcript_root = (data_root / "transcripts" / "html").resolve()
    try:
        resolved.relative_to(transcript_root)
    except ValueError:
        return None
    return resolved if resolved.is_file() else None


def discover_transcript(uri: str) -> dict[str, Any] | None:
    """Return parsed segment data for one safe, discovered transcript URI."""
    path = _resolve_transcript_uri(uri)
    if path is None:
        return None
    match = re.search(r"(?:^|_)STG[_-](\d+)(?:_|$)", path.stem)
    source_id = f"STG-{match.group(1)}" if match else path.stem
    from .sources import HtmlTranscriptSource

    source = HtmlTranscriptSource(path, source_id, uri)
    segments = [
        {
            "segment_id": segment["segment_id"],
            "audio_offset_start": segment["audio_offset_start"],
            "audio_offset_end": segment["audio_offset_end"],
            "speaker": segment["speaker"],
            "verbatim": segment["verbatim"],
        }
        for segment in source.all_segments()
    ]
    return {
        "ok": True,
        "name": path.name,
        "uri": uri,
        "source_id": source_id,
        "segment_count": len(segments),
        "segments": segments,
    }


def discover_sources() -> dict[str, Any]:
    """Describe source files the browser can use for evidence and norms."""
    data_root = find_data_root()
    if data_root is None:
        return {"ok": True, "root": None, "transcripts": [], "frameworks": []}

    from .sources import HtmlTranscriptSource, MarkdownFrameworkSource

    transcript_root = data_root / "transcripts" / "html"
    transcripts: list[dict[str, Any]] = []
    for path in sorted(transcript_root.glob("*.html")):
        source_id = path.stem
        match = re.search(r"(?:^|_)STG[_-](\d+)(?:_|$)", path.stem)
        if match:
            source_id = f"STG-{match.group(1)}"
        source = HtmlTranscriptSource(path, source_id, str(path.relative_to(data_root.parent)))
        transcripts.append({
            "name": path.name,
            "path": str(path.relative_to(data_root.parent)),
            "uri": str(path.relative_to(data_root.parent)),
            "source_id": source_id,
            "segment_count": len(source.all_segments()),
        })

    framework_root = data_root / "law"
    frameworks: list[dict[str, Any]] = []
    for path in sorted(framework_root.rglob("*.md")):
        if path.parts[-2:] == ("_mapping", path.name):
            continue
        code = path.stem.split("_")[0].upper()
        source = MarkdownFrameworkSource(path, code, str(path.relative_to(data_root.parent)))
        frameworks.append({
            "name": path.name,
            "path": str(path.relative_to(data_root.parent)),
            "uri": str(path.relative_to(data_root.parent)),
            "jurisdiction": path.parent.relative_to(framework_root).as_posix(),
            "framework_code": code,
            "article_count": len(source.articles_cached()),
        })

    return {
        "ok": True,
        "root": str(data_root),
        "transcripts": transcripts,
        "frameworks": frameworks,
    }


# ---------------------------------------------------------------------------
# Runtime probe
# ---------------------------------------------------------------------------

#: Optional extras surfaced in the UI's "Runtime health" panel, with the exact
#: install hint to show when they are missing.
_EXTRAS: tuple[tuple[str, str, str], ...] = (
    ("mcp", "mcp", "pip install -e '.[mcp]'"),
    ("httpx", "llm", "pip install -e '.[llm]'"),
    ("qdrant_client", "qdrant", "pip install -e '.[qdrant]'"),
    ("neo4j", "neo4j", "pip install -e '.[neo4j]'"),
)


def _probe_module(module_name: str) -> dict[str, Any]:
    """Import-and-report for an optional dependency. Never raises."""
    import importlib
    import importlib.metadata as md

    try:
        importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001 - any failure means "not usable"
        return {"present": False, "error": type(exc).__name__}

    version: str | None = None
    for dist in (module_name, module_name.replace("_", "-")):
        try:
            version = md.version(dist)
            break
        except md.PackageNotFoundError:
            continue
    return {"present": True, "version": version}


def probe_runtime(tool_count: int | None = None) -> dict[str, Any]:
    """Describe the runtime so the UI can render real health rows."""
    major, minor = sys.version_info[:2]
    core = _probe_module("pydantic")

    extras: list[dict[str, Any]] = []
    for module_name, extra, fix in _EXTRAS:
        info = _probe_module(module_name)
        extras.append(
            {
                "module": module_name,
                "extra": extra,
                "present": info["present"],
                "version": info.get("version"),
                "fix": fix,
            }
        )

    ui_path = find_ui_path()
    return {
        "status": "ok",
        "service": "violation-pack",
        "python": {
            "version": f"{major}.{minor}.{sys.version_info[2]}",
            "executable": sys.executable,
            "ok": (major, minor) >= (3, 10),
            "required": ">=3.10",
        },
        "packages": {
            "pydantic": {"present": core["present"], "version": core.get("version"), "fix": "pip install pydantic>=2.5"},
            "extras": extras,
        },
        "tools": {"count": tool_count},
        "ui": {
            "present": ui_path is not None,
            "path": str(ui_path) if ui_path else None,
        },
    }


# ---------------------------------------------------------------------------
# Tool introspection
# ---------------------------------------------------------------------------

def _tool_catalog_tags() -> dict[str, list[str]]:
    """Tool name -> catalog tags, so the bridge can find destructive tools.

    `mcp_catalog.py` is the declared source for tags; the AST drift test keeps it
    honest. A missing/failed import degrades to "no tools are tagged", which is
    safe: unknown tools simply require explicit confirmation.
    """
    try:
        from .mcp_catalog import catalog
    except Exception:  # noqa: BLE001 - catalog is advisory, not load-bearing
        return {}
    try:
        entry = catalog()["servers"][0]
        return {t["name"]: list(t.get("tags") or []) for t in entry["tools"]}
    except Exception:  # noqa: BLE001
        return {}


def describe_tools(tool_manager) -> list[dict[str, Any]]:
    """Every registered tool, with the JSON Schema the UI needs for forms."""
    tags = _tool_catalog_tags()
    described: list[dict[str, Any]] = []
    for tool in tool_manager.list_tools():
        schema = tool.parameters or {}
        tool_tags = tags.get(tool.name, [])
        required = list(schema.get("required") or [])
        described.append(
            {
                "name": tool.name,
                "description": (tool.description or "").strip(),
                "parameters": schema,
                "required": required,
                "optional": [k for k in (schema.get("properties") or {}) if k not in required],
                "tags": tool_tags,
                "destructive": "destructive" in tool_tags,
            }
        )
    described.sort(key=lambda t: t["name"])
    return described


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

def build_ui_routes(mcp):
    """Mount the UI + JSON API onto an already-built FastMCP instance.

    Called by `mcp_server.build_server()`; returns the FastMCP instance so it can
    be used inline. All handlers are self-contained, so nothing here can break
    the MCP protocol surface.
    """
    from starlette.responses import HTMLResponse, JSONResponse, Response

    tool_manager = mcp._tool_manager

    # Permissive CORS: these are localhost dev endpoints, and allowing `*` means
    # a copy of the HTML opened straight off disk (`file://`) also works.
    CORS = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Cache-Control": "no-store",
    }

    def json_response(payload: Any, status_code: int = 200) -> JSONResponse:
        return JSONResponse(payload, status_code=status_code, headers=CORS)

    # -- the UI itself ------------------------------------------------------

    @mcp.custom_route("/", methods=["GET"])
    async def ui_index(request) -> Response:  # noqa: ARG001 - Starlette signature
        ui_path = find_ui_path()
        if ui_path is None:
            return HTMLResponse(
                "<h1>ViolationRefiner UI not found</h1>"
                f"<p>Looked for <code>ui/{UI_FILENAME}</code> next to the package. "
                f"Set <code>{UI_ENV_VAR}</code> to override.</p>",
                status_code=404,
                headers=CORS,
            )
        return HTMLResponse(ui_path.read_text(encoding="utf-8"), headers=CORS)

    # -- runtime probe ------------------------------------------------------

    @mcp.custom_route("/api/health", methods=["GET", "OPTIONS"])
    async def api_health(request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)
        payload = probe_runtime(tool_count=len(tool_manager.list_tools()))
        return json_response(payload)

    # -- tool discovery -----------------------------------------------------

    @mcp.custom_route("/api/tools", methods=["GET", "OPTIONS"])
    async def api_tools(request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)
        tools = describe_tools(tool_manager)
        return json_response({"count": len(tools), "tools": tools})

    # -- source discovery ---------------------------------------------------

    @mcp.custom_route("/api/sources", methods=["GET", "OPTIONS"])
    async def api_sources(request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)
        return json_response(discover_sources())

    @mcp.custom_route("/api/source-transcript", methods=["GET", "OPTIONS"])
    async def api_source_transcript(request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)
        uri = request.query_params.get("uri", "")
        payload = discover_transcript(uri)
        if payload is None:
            return json_response(
                {"ok": False, "error": "uri must reference a discovered data/transcripts/html/*.html file."},
                status_code=400,
            )
        return json_response(payload)

    # -- tool invocation ----------------------------------------------------

    @mcp.custom_route("/api/tool", methods=["POST", "OPTIONS"])
    async def api_tool(request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)

        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - malformed JSON is a client error
            return json_response(
                {"ok": False, "error": "Request body must be JSON."}, status_code=400
            )
        if not isinstance(body, dict):
            return json_response(
                {"ok": False, "error": "Request body must be a JSON object."},
                status_code=400,
            )

        name = body.get("name")
        args = body.get("args") or {}
        confirm = body.get("confirm") is True

        if not isinstance(name, str) or not name:
            return json_response(
                {"ok": False, "error": "Missing 'name' (tool name)."}, status_code=400
            )
        if not isinstance(args, dict):
            return json_response(
                {"ok": False, "error": "'args' must be a JSON object."}, status_code=400
            )

        known = {t.name for t in tool_manager.list_tools()}
        if name not in known:
            return json_response(
                {"ok": False, "error": f"Unknown tool: {name}"}, status_code=404
            )

        if name == "build_evidence_layer_tool" and "transcript_path" in args:
            transcript_path = args["transcript_path"]
            if not isinstance(transcript_path, str):
                return json_response(
                    {"ok": False, "error": "'transcript_path' must be a discovered data URI."},
                    status_code=400,
                )
            resolved = _resolve_transcript_uri(transcript_path)
            if resolved is None:
                return json_response(
                    {"ok": False, "error": "transcript_path must reference data/transcripts/html/*.html."},
                    status_code=400,
                )
            args = {**args, "transcript_path": str(resolved)}

        tags = _tool_catalog_tags().get(name, [])
        if "destructive" in tags and not confirm:
            return json_response(
                {
                    "ok": False,
                    "error": (
                        f"{name} is destructive and requires explicit confirmation. "
                        'Send {"confirm": true} to proceed.'
                    ),
                    "destructive": True,
                    "requires_confirmation": True,
                },
                status_code=409,
            )

        try:
            result = await tool_manager.call_tool(name, args)
        except Exception as exc:  # noqa: BLE001 - surface the real message to the UI
            return json_response(
                {
                    "ok": False,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "tool": name,
                },
                status_code=400,
            )

        return json_response({"ok": True, "tool": name, "result": result})

    # -- catalog ------------------------------------------------------------

    @mcp.custom_route("/api/catalog", methods=["GET", "OPTIONS"])
    async def api_catalog(request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)
        try:
            from .mcp_catalog import catalog
        except Exception as exc:  # noqa: BLE001
            return json_response(
                {"ok": False, "error": f"Catalog unavailable: {exc}"}, status_code=500
            )
        return json_response(catalog())

    return mcp


# ---------------------------------------------------------------------------
# Standalone launcher (UI only, no MCP protocol surface)
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Serve just the UI + API, for UI development against an idle backend."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="violation-pack-ui",
        description="Serve the ViolationRefiner UI and its JSON tool bridge.",
    )
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("UI_PORT", "8125")))
    parser.add_argument("--no-mcp", action="store_true",
                        help="Skip mounting the MCP protocol endpoint.")
    opts = parser.parse_args(argv)

    from .mcp_server import build_server

    mcp = build_server(include_ui=False) if opts.no_mcp else build_server()
    if opts.no_mcp:
        build_ui_routes(mcp)

    import uvicorn  # provided by the `mcp` extra (via starlette/uvicorn)

    probe = probe_runtime(tool_count=len(mcp._tool_manager.list_tools()))
    ui_path = find_ui_path()
    print(f"ViolationRefiner UI  →  http://{opts.host}:{opts.port}/")
    print(f"  UI file : {ui_path or 'NOT FOUND'}")
    print(f"  Tools   : {probe['tools']['count']}")
    print(f"  Python  : {probe['python']['version']}")
    uvicorn.run(mcp.streamable_http_app(), host=opts.host, port=opts.port, log_level="warning")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
