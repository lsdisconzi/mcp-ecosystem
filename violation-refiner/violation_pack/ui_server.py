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
    GET  /api/bundle    one bundle's real artifacts (violation JSON, contract,
                        Validation/checks.json, segments_manifest.json, files)
    GET  /api/schema    every option list the UI renders, read off the live
                        model Literals + bundle layout (no hardcoded enums)
    GET  /api/settings  effective config.Settings values (secrets masked) and
                        the resolved workspace paths
    GET  /api/shared-collections
                        owner/dim/payload contracts for the shared Qdrant
                        collections (``?live=1`` adds a live drift check)
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
from typing import Any, get_args

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
    """Locate the workspace data directory next to the UI repository.

    A candidate must contain ``law/`` and a transcript directory — either
    ``transcripts/json/`` (the canonical, symlinked corpus) or
    ``transcripts/html/`` (the vendored render). The JSON corpus is the
    authoritative one, so requiring HTML here would couple source discovery to
    a snapshot directory that the ownership contract intends to retire.
    """
    here = Path(__file__).resolve().parent
    for base in (here, *here.parents):
        candidate = base / "data"
        transcripts = candidate / "transcripts"
        if not (candidate / "law").is_dir():
            continue
        if (transcripts / "json").is_dir() or (transcripts / "html").is_dir():
            return candidate
    return None


def find_workspace_root() -> Path:
    """Return the repository root used to constrain browser selections."""
    here = Path(__file__).resolve().parent
    for base in (here, *here.parents):
        if (base / "pyproject.toml").is_file() and (base / "violation_pack").is_dir():
            return base
    return here.parent


def browse_workspace(path: str = "", kind: str = "directory") -> dict[str, Any] | None:
    """List a safe workspace directory or resolve one safe file selection.

    Containment is checked **lexically**, on the unresolved path, and only then is
    the path resolved for existence and type. That order matters twice over:

    * It is the check that actually stops user-supplied traversal — ``../../`` is
      normalised and rejected before any filesystem access.
    * Resolving *first* made every out-of-tree symlink unreachable, because
      ``data/law`` and ``data/transcripts/html`` are symlinks that leave this
      workspace **by design**. ``data/law`` was refused silently this way, with no
      test covering it, until the render symlink made it visible.

    A repo-owned symlink is not a traversal vector: passing ``../../etc`` is still
    refused, and anyone able to plant a symlink in the repo can already read those
    files directly.
    """
    root = find_workspace_root().resolve()
    requested = Path(path or ".")
    if requested.is_absolute():
        return None
    lexical = Path(os.path.normpath(root / requested))
    try:
        lexical.relative_to(root)
    except ValueError:
        return None
    candidate = lexical.resolve()
    if not candidate.exists() or (kind == "file" and not candidate.is_file()):
        return None
    if kind == "file":
        return {"ok": True, "kind": "file", "path": str(lexical.relative_to(root))}
    if not candidate.is_dir():
        return None
    # List through the lexical path so each entry stays workspace-relative; the
    # children of a resolved path are no longer under ``root``.
    entries = []
    for entry in sorted(lexical.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
        if entry.name.startswith("."):
            continue
        entries.append({
            "name": entry.name,
            "kind": "directory" if entry.is_dir() else "file",
            "path": str(entry.relative_to(root)),
        })
    rel = str(lexical.relative_to(root)) if lexical != root else "."
    parent = str(lexical.parent.relative_to(root)) if lexical != root else None
    return {"ok": True, "kind": "directory", "path": rel, "parent": parent, "entries": entries}


def discover_bundles() -> dict[str, Any]:
    """List real CL-* bundle directories under the repository build root."""
    root = find_workspace_root().resolve()
    build_root = root / "build"
    bundles = []
    if build_root.is_dir():
        for path in sorted(build_root.iterdir(), key=lambda item: item.name):
            if not path.is_dir() or not re.fullmatch(r"CL-\d+", path.name):
                continue
            file_count = sum(1 for item in path.rglob("*") if item.is_file())
            if file_count == 0:
                # A CL-* directory with no files is not a bundle — it is the
                # remains of an interrupted run. `build/CL-001/` sat empty and
                # made this function report a phantom bundle.
                continue
            bundles.append({
                "id": path.name,
                "path": str(path.relative_to(root)),
                "file_count": file_count,
            })
    return {"ok": True, "root": "build", "bundles": bundles}


#: Bundle-relative artifacts the UI reads. Every entry is optional on disk: a
#: bundle mid-run legitimately lacks some, and a missing artifact must degrade
#: to an empty panel rather than a failed request.
BUNDLE_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("violation", "{violation_id}.json"),
    ("contract", "contract.json"),
    ("validation", "Validation/checks.json"),
    ("manifest", "segments_manifest.json"),
    ("warnings", "conversion_warnings.json"),
)


def _read_json_file(path: Path) -> Any | None:
    """Parse a JSON artifact, or return ``None`` when absent/unreadable.

    A malformed artifact is treated exactly like a missing one: the UI renders
    every other panel instead of losing the request to a 500.
    """
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _validation_summary(report: Any) -> dict[str, int]:
    """Count check statuses. ``checks.json`` carries no summary key, so the
    UI would otherwise have to recompute the tallies itself."""
    summary = {"total": 0, "pass": 0, "warn": 0, "fail": 0}
    checks = (report or {}).get("checks") if isinstance(report, dict) else None
    for check in checks or []:
        summary["total"] += 1
        status = str(check.get("status") or "").lower()
        if status in summary:
            summary[status] += 1
    return summary


def discover_bundle(violation_id: str) -> dict[str, Any] | None:
    """Read one real ``build/<violation_id>/`` bundle for the UI.

    Read-only and filesystem-only: it dispatches no tool and writes nothing. The
    id is validated against the same ``CL-<digits>`` shape ``discover_bundles()``
    lists, so a traversal attempt and an off-sequence directory are both refused
    with ``None`` (the caller answers 400 without disclosing what exists).
    """
    if not re.fullmatch(r"CL-\d+", violation_id or ""):
        return None
    root = find_workspace_root().resolve()
    bundle = root / "build" / violation_id
    if not bundle.is_dir():
        return None

    artifacts: dict[str, Any] = {}
    present: dict[str, bool] = {}
    for key, template in BUNDLE_ARTIFACTS:
        payload = _read_json_file(bundle / template.format(violation_id=violation_id))
        artifacts[key] = payload
        present[key] = payload is not None

    files = [
        {
            "name": item.name,
            "path": str(item.relative_to(root)),
            "kind": "directory" if item.is_dir() else "file",
            "size": item.stat().st_size if item.is_file() else None,
        }
        for item in sorted(bundle.rglob("*"), key=lambda p: str(p))
        if not item.name.startswith(".")
    ]
    return {
        "ok": True,
        "violation_id": violation_id,
        "root": "build",
        "path": f"build/{violation_id}",
        "artifacts_present": present,
        "violation": artifacts["violation"],
        "contract": artifacts["contract"],
        "validation": artifacts["validation"],
        "validation_summary": _validation_summary(artifacts["validation"]),
        "manifest": artifacts["manifest"],
        "warnings": artifacts["warnings"],
        "files": files,
        "file_count": sum(1 for f in files if f["kind"] == "file"),
    }


def describe_schema() -> dict[str, Any]:
    """Every option list the UI needs, read off the live registries.

    The frontend used to hardcode these as literal ``<option>``/chip markup, so
    adding a status to a ``Literal`` in ``models.py`` silently produced a UI that
    could not display it. Deriving them here keeps one source of truth; a new
    member of any enum shows up in the browser with no HTML change.
    """
    from . import models
    from .enrich import ENRICHMENT_STAGES
    from .pack import BUNDLE_LAYOUT
    from .validation import DEFAULT_PIPELINE

    def literal(name: str, field: str) -> list[str]:
        annotation = models.__dict__[name].model_fields[field].annotation
        return [str(item) for item in get_args(annotation)]

    def union(*literals: Any) -> list[str]:
        seen: list[str] = []
        for literal in literals:
            for value in literal:
                if value not in seen:
                    seen.append(value)
        return seen

    return {
        "ok": True,
        "severity": literal("Violation", "severity"),
        "clock_time_confidence": literal("Incident", "clock_time_confidence"),
        "norm_type": literal("CachedArticle", "norm_type"),
        "applicability": literal("CachedArticle", "applicability"),
        "article_cache_status": union(
            literal("CachedArticle", "framework_cache_status"),
            literal("CandidateArticle", "framework_cache_status"),
        ),
        "proof_status": literal("Element", "proof_status"),
        "proof_weights": models.PROOF_WEIGHTS,
        "nexus_strength": literal("NexusEntry", "strength"),
        "authority_type": literal("Authority", "type"),
        "authority_protocol": literal("VerificationProvenance", "protocol"),
        "open_question_priority": literal("OpenQuestion", "priority"),
        "check_status": literal("CheckResult", "status"),
        # Layer-0 staging destinations come from the bundle layout itself, so the
        # ``kind`` a user picks always matches a key pack.py can resolve.
        "bundle_layout": {kind: rel for kind, rel in BUNDLE_LAYOUT.items()},
        # S9's stage chips and S10's check rows are the registry order, so a new
        # stage or a new V-check appears in the UI without an HTML change.
        "enrichment_stages": list(ENRICHMENT_STAGES),
        "validation_pipeline": [
            {"check_id": check_id, "name": name} for check_id, name, _ in DEFAULT_PIPELINE
        ],
    }


#: Settings fields whose value must never round-trip to the browser.
SECRET_SETTINGS: frozenset[str] = frozenset({
    "qdrant_api_key", "neo4j_password", "llm_api_key",
})


def describe_settings() -> dict[str, Any]:
    """The *effective* configuration plus every resolved workspace path.

    The Settings panel previously printed hand-written literals (``bge-m3``,
    ``violationrefiner_v1``, ``.venv/bin/python``) that silently drifted from
    ``config.Settings``. Here the defaults are read from the class that actually
    applies them, secrets are replaced by a ``configured`` boolean, and the
    paths are the ones this process really resolved.
    """
    from .config import Settings

    try:
        settings = Settings.from_env()
    except Exception as exc:  # noqa: BLE001 - a broken .env must not kill the UI
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    values: dict[str, Any] = {}
    secrets: dict[str, bool] = {}
    for name in Settings.__dataclass_fields__:
        value = getattr(settings, name)
        if name in SECRET_SETTINGS:
            secrets[name] = bool(value)
            continue
        values[name] = value

    root = find_workspace_root().resolve()
    venv_python = root / ".venv" / "bin" / "python"
    data_root = find_data_root()
    ui_path = find_ui_path()
    paths = {
        "workspaceRoot": str(root),
        "buildRoot": str(root / "build"),
        "dataRoot": str(data_root) if data_root else None,
        "envFile": str(root / ".env") if (root / ".env").is_file() else None,
        "python": str(venv_python) if venv_python.is_file() else sys.executable,
        "logRoot": str(root / ".dev-logs" / "violation-refiner"),
        "uiFile": str(ui_path) if ui_path else None,
    }
    return {"ok": True, "settings": values, "secrets": secrets, "paths": paths}


def _resolve_transcript_uri(uri: str) -> Path | None:
    """Resolve a discovered transcript URI without allowing path traversal.

    Accepts both corpus forms: ``data/transcripts/json/*.json`` (canonical,
    authoritative) and ``data/transcripts/html/*.html`` (a render, symlinked to
    the OliviaLegal render tree — see ``docs/data_source_of_truth.md`` §8).
    """
    data_root = find_data_root()
    if data_root is None:
        return None
    candidate = Path(uri)
    if candidate.is_absolute():
        return None
    if candidate.parts[:2] != ("data", "transcripts"):
        return None
    suffix = candidate.suffix.lower()
    if suffix not in {".json", ".html"}:
        return None
    transcript_root = (data_root / "transcripts" / suffix.lstrip(".")).resolve()
    resolved = (data_root.parent / candidate).resolve()
    try:
        resolved.relative_to(transcript_root)
    except ValueError:
        return None
    return resolved if resolved.is_file() else None


def _source_id_from_stem(stem: str) -> str:
    """Derive a display source id from a filename stem (HTML corpus convention)."""
    match = re.search(r"(?:^|_)STG[_-](\d+)(?:_|$)", stem)
    return f"STG-{match.group(1)}" if match else stem


def discover_transcript(uri: str) -> dict[str, Any] | None:
    """Return parsed segment data for one safe, discovered transcript URI."""
    path = _resolve_transcript_uri(uri)
    if path is None:
        return None

    if path.suffix.lower() == ".json":
        from .sources_json import JsonTranscriptSchemaError, JsonTranscriptSource

        try:
            source = JsonTranscriptSource(path, bundle_uri=uri)
        except (JsonTranscriptSchemaError, OSError):
            return None
        segments = [
            {
                "segment_id": segment["segment_id"],
                "audio_offset_start": segment["audio_offset_start"],
                "audio_offset_end": segment["audio_offset_end"],
                "speaker": segment["speaker"],
                "speaker_id": segment.get("speaker_id"),
                "verbatim": segment["verbatim"],
                "reviewed": segment.get("reviewed", False),
            }
            for segment in source.all_segments()
        ]
        return {
            "ok": True,
            "name": path.name,
            "uri": uri,
            "kind": "json",
            "authoritative": True,
            "source_id": source.source_id(),
            "transcript_id": source.transcript_id,
            "segment_count": len(segments),
            "reviewed_count": len(source.reviewed_segments()),
            "sha256": source.source_sha256(),
            "metadata": {
                key: source.get(key)
                for key in (
                    "title", "subtitle", "case_id", "narrative_id",
                    "language", "location", "recording_datetime",
                    "source_file", "chronological_order", "prior_stage",
                    "next_stage", "violations_cited", "tags",
                )
            },
            "participants": source.participants(),
            "segments": segments,
        }

    source_id = _source_id_from_stem(path.stem)
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
        "kind": "html",
        "authoritative": False,
        "source_id": source_id,
        "segment_count": len(segments),
        "segments": segments,
    }


def discover_sources() -> dict[str, Any]:
    """Describe source files the browser can use for evidence and norms.

    Returns both transcript corpora when present:

    ``transcripts``
        The vendored ``data/transcripts/html/*.html`` render. Kept first for
        backward compatibility with existing callers.
    ``transcripts_json``
        The canonical ``data/transcripts/json/*.json`` corpus, keyed by
        ``transcript_id``. This is the *authoritative* form: ``layers.py``
        composes ``f"{source_id()}.{segment_id}"``, and only this corpus yields
        ids byte-identical to ``reviewed_transcripts.segment_id``.
    ``shared_collections``
        The declared owner/dim/payload contract for the Qdrant collections
        violation-refiner reads but never writes.
    """
    data_root = find_data_root()
    if data_root is None:
        return {
            "ok": True,
            "root": None,
            "transcripts_root": None,
            "frameworks_root": None,
            "transcripts": [],
            "transcripts_json": [],
            "frameworks": [],
            "shared_collections": _declared_contracts(),
        }

    from .sources import HtmlTranscriptSource, MarkdownFrameworkSource

    transcript_root = data_root / "transcripts" / "html"
    transcripts: list[dict[str, Any]] = []
    for path in sorted(transcript_root.glob("*.html")):
        source_id = _source_id_from_stem(path.stem)
        source = HtmlTranscriptSource(path, source_id, str(path.relative_to(data_root.parent)))
        transcripts.append({
            "name": path.name,
            "path": str(path.relative_to(data_root.parent)),
            "uri": str(path.relative_to(data_root.parent)),
            "source_id": source_id,
            "segment_count": len(source.all_segments()),
        })

    transcripts_json: list[dict[str, Any]] = []
    json_root = data_root / "transcripts" / "json"
    if json_root.is_dir():
        from .sources_json import JsonTranscriptSource

        speaker_index = data_root / "speaker_index.json"
        for path in sorted(json_root.glob("*.json")):
            try:
                source = JsonTranscriptSource(
                    path,
                    bundle_uri=str(path.relative_to(data_root.parent)),
                    speaker_index_path=speaker_index if speaker_index.is_file() else None,
                )
            except Exception:  # pragma: no cover - a bad file must not kill discovery
                continue
            first = source.get_segment("seg-0")
            transcripts_json.append({
                "name": path.name,
                "path": str(path.relative_to(data_root.parent)),
                "uri": str(path.relative_to(data_root.parent)),
                "transcript_id": source.transcript_id,
                "segment_count": source.segment_count(),
                "reviewed_count": len(source.reviewed_segments()),
                "segment_id_example": first["segment_id"] if first else None,
                "participants": source.participants(),
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
        # The roots the two corpora were actually discovered under, relative to
        # the workspace. The UI uses these for its directory pickers instead of
        # hardcoding "data/transcripts/html" / "data/law" and drifting.
        "transcripts_root": str(transcript_root.relative_to(data_root.parent)),
        "frameworks_root": str(framework_root.relative_to(data_root.parent)),
        "transcripts": transcripts,
        "transcripts_json": transcripts_json,
        "frameworks": frameworks,
        "shared_collections": _declared_contracts(),
        "precedence": {
            "evidence": "transcripts_json",
            "evidence_reason": (
                "segment ids compose to the same form stored in "
                "reviewed_transcripts.segment_id; the html render only carries "
                "bare speaker labels and stale snapshots"
            ),
            "fallback": "transcripts",
        },
    }


def _declared_contracts() -> list[dict[str, Any]]:
    """Offline description of the shared collections (no network access)."""
    from .shared_corpora import SHARED_COLLECTIONS

    return [
        {
            "name": contract.name,
            "owner": contract.owner,
            "dim": contract.dim,
            "embed_model": contract.embed_model,
            "keyed_by": contract.keyed_by,
            "point_id": contract.point_id_description,
            "required_payload_keys": list(contract.required_payload_keys),
            "notes": contract.notes,
            "violation_refiner_access": "read-only",
        }
        for contract in SHARED_COLLECTIONS.values()
    ]


def discover_shared_collections(live: bool = False) -> dict[str, Any]:
    """Report the shared-collection contracts, optionally against live Qdrant.

    ``live=False`` (the default) is a pure offline description, so the UI and
    tests never need credentials. ``live=True`` adds a ``check`` block and is
    skipped with an explanatory ``reason`` when ``QDRANT_URL`` is unset.
    """
    contracts = _declared_contracts()
    payload: dict[str, Any] = {"ok": True, "live": False, "collections": contracts}
    if not live:
        return payload

    if not os.environ.get("QDRANT_URL"):
        payload["reason"] = "QDRANT_URL is not set; live contract check skipped."
        return payload

    from .shared_corpora import SharedCorpusReader

    try:
        reader = SharedCorpusReader()
        payload["check"] = reader.verify_contract()
        payload["live"] = True
    except Exception as exc:  # pragma: no cover - network/permission failure
        payload["ok"] = False
        payload["reason"] = f"{type(exc).__name__}: {exc}"
    return payload


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
                {
                    "ok": False,
                    "error": (
                        "uri must reference a discovered transcript under "
                        "data/transcripts/json/*.json (canonical) or "
                        "data/transcripts/html/*.html (vendored render)."
                    ),
                },
                status_code=400,
            )
        return json_response(payload)

    @mcp.custom_route("/api/shared-collections", methods=["GET", "OPTIONS"])
    async def api_shared_collections(request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)
        live = request.query_params.get("live", "") in {"1", "true", "yes"}
        return json_response(discover_shared_collections(live=live))

    @mcp.custom_route("/api/browse", methods=["GET", "OPTIONS"])
    async def api_browse(request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)
        path = request.query_params.get("path", "")
        kind = request.query_params.get("kind", "directory")
        if kind not in {"directory", "file"}:
            return json_response({"ok": False, "error": "kind must be directory or file."}, status_code=400)
        payload = browse_workspace(path, kind)
        if payload is None:
            return json_response({"ok": False, "error": "Path is outside the workspace or does not exist."}, status_code=400)
        return json_response(payload)

    @mcp.custom_route("/api/bundles", methods=["GET", "OPTIONS"])
    async def api_bundles(request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)
        return json_response(discover_bundles())

    @mcp.custom_route("/api/bundle", methods=["GET", "OPTIONS"])
    async def api_bundle(request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)
        violation_id = request.query_params.get("violation_id", "")
        payload = discover_bundle(violation_id)
        if payload is None:
            return json_response(
                {
                    "ok": False,
                    "error": (
                        "violation_id must name a CL-<digits> bundle directory "
                        "under build/."
                    ),
                },
                status_code=400,
            )
        return json_response(payload)

    @mcp.custom_route("/api/schema", methods=["GET", "OPTIONS"])
    async def api_schema(request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)
        return json_response(describe_schema())

    @mcp.custom_route("/api/settings", methods=["GET", "OPTIONS"])
    async def api_settings(request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)
        return json_response(describe_settings())

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
