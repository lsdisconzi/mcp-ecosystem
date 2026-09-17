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
    GET  /api/framework-article
                        one cached article's verbatim body + declared ELI id,
                        read from a bundle's `Legal framework/<name>.md`; with
                        no `article` it lists the article numbers that cache
                        holds, which is how a framework staged into the bundle
                        (and so recorded in no `framework_caches` row yet) can
                        still be offered by the S3 picker
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

import asyncio
import json
import hashlib
import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, get_args

from . import progress

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


def contained_workspace_path(path: str = "") -> Path | None:
    """``root/path`` when the **unresolved** path stays inside the workspace.

    Containment is checked lexically, and only the caller then resolves it for
    existence and type. That order matters twice over:

    * It is the check that actually stops user-supplied traversal — ``../../`` is
      normalised and rejected before any filesystem access.
    * Resolving *first* made every out-of-tree symlink unreachable, because
      ``data/law`` and ``data/transcripts/html`` are symlinks that leave this
      workspace **by design**. ``data/law`` was refused silently this way, with no
      test covering it, until the render symlink made it visible.

    A repo-owned symlink is not a traversal vector: passing ``../../etc`` is still
    refused, and anyone able to plant a symlink in the repo can already read those
    files directly.

    Returning the lexical path is the point — the children of a *resolved* path
    are no longer under ``root``, so the walkable form is the one the caller
    needs for listing. Callers that want the file use `resolve_workspace_path`.

    One rule with two callers (``browse_workspace`` and the staging route) rather
    than two containment checks: a second copy of this logic is how a browse that
    refuses a path comes to sit beside a write that accepts it.
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
    return lexical


def resolve_workspace_path(path: str = "", kind: str = "file") -> Path | None:
    """The real path behind a contained workspace reference, or ``None``.

    ``kind`` is what the caller wants to **end up with**, not a claim about the
    current directory: ``kind="file"`` on a directory is a legitimate starting
    state (that is where a picker *opens*), so it is not rejected here. The
    distinction lives in `browse_workspace`, which lists a directory for either
    kind and only ever *resolves* a selection.
    """
    lexical = contained_workspace_path(path)
    if lexical is None:
        return None
    candidate = lexical.resolve()
    if not candidate.exists():
        return None
    if kind == "file" and not candidate.is_file():
        return None
    return candidate


def browse_workspace(path: str = "", kind: str = "directory") -> dict[str, Any] | None:
    """List a safe workspace directory or resolve one safe file selection.

    ``kind`` says what the caller is allowed to **pick**, never what the path
    must already be — so opening a file picker on a directory returns that
    directory's listing, and the caller lists it until the user names a file.
    That is not a convenience: every picker opens somewhere, and the previous
    reading (``kind="file"`` ⇒ the path must be a file) made a file picker
    impossible to open at all. The UI asked for ``path=.``, the workspace root is
    a directory, and the server answered 400 *"Path is outside the workspace or
    does not exist"* — for a path that plainly exists and plainly is inside.

    Containment runs in `contained_workspace_path`; see it for why the check is
    lexical and why that order is load-bearing.
    """
    lexical = contained_workspace_path(path)
    if lexical is None:
        return None
    root = find_workspace_root().resolve()
    candidate = lexical.resolve()
    if not candidate.exists():
        return None
    if candidate.is_dir():
        # List through the lexical path so each entry stays workspace-relative;
        # the children of a resolved path are no longer under ``root``.
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
    if kind != "file":
        return None
    return {"ok": True, "kind": "file", "path": str(lexical.relative_to(root))}


#: Bundle directory names are the violation id verbatim: ``<JURISDICTION>-<local>``,
#: where the jurisdiction is an upper-case alpha code (``CL``, ``BR``, ``INT``) and
#: the local part is alphanumeric and may carry ``_``, ``.`` or ``-`` — see
#: ``CL-f7dd941e`` and ``CL-001__opus46``.
#:
#: This is a *safety* check (no path separator, no ``..``), deliberately **not** a
#: membership test. The previous ``CL-\d+`` filter mirrored a jurisdiction list that
#: drifts silently: it hid all 20 BR bundles, all 19 INT bundles and ``CL-f7dd941e``,
#: so the UI listed 41 of the 81 bundles on disk with no warning.
_BUNDLE_DIR_RE = re.compile(r"(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9._-]*")


def bundle_payload_path(bundle_dir: Path) -> Path | None:
    """``<bundle>/<bundle>.json`` when it exists — the structural bundle marker.

    Every real bundle carries the violation payload under its own directory name,
    so this doubles as the "is this really a bundle?" test.
    """
    named = bundle_dir / f"{bundle_dir.name}.json"
    return named if named.is_file() else None


def is_bundle_dir(path: Path) -> bool:
    """True when ``path`` is a directory carrying its own violation payload."""
    return path.is_dir() and bundle_payload_path(path) is not None


def bundle_jurisdiction(violation_id: str) -> str:
    """The leading jurisdiction code of a bundle id (``CL-001`` -> ``CL``).

    Derived from the id rather than restated in a mapping, so a jurisdiction
    added upstream shows up here without a code change.
    """
    return violation_id.split("-", 1)[0] if "-" in violation_id else ""


def discover_bundles() -> dict[str, Any]:
    """List every real bundle directory under the repository build root.

    Discovery is structural — a directory is a bundle when it carries its own
    ``<dirname>.json`` payload — so all jurisdictions (CL, BR, INT) are listed.
    """
    root = find_workspace_root().resolve()
    build_root = root / "build"
    bundles = []
    if build_root.is_dir():
        for path in sorted(build_root.iterdir(), key=lambda item: item.name):
            if not _BUNDLE_DIR_RE.fullmatch(path.name):
                continue
            if not is_bundle_dir(path):
                continue
            file_count = sum(1 for item in path.rglob("*") if item.is_file())
            if file_count == 0:
                # A bundle-shaped directory with no files is not a bundle — it is
                # the remains of an interrupted run. `build/CL-001/` sat empty and
                # made this function report a phantom bundle.
                continue
            bundles.append({
                "id": path.name,
                "jurisdiction": bundle_jurisdiction(path.name),
                "path": str(path.relative_to(root)),
                "file_count": file_count,
            })
    return {
        "ok": True,
        "root": "build",
        "bundles": bundles,
        "jurisdictions": sorted({bundle["jurisdiction"] for bundle in bundles}),
    }


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


def resolve_bundle_dir(violation_id: str) -> Path | None:
    """``build/<violation_id>/`` when that is a real bundle directory.

    The id must be a bare bundle-directory name that resolves to a real bundle
    under ``build/``, so a traversal attempt, a path-shaped id and an
    off-sequence directory are all refused with ``None`` (the caller answers 400
    without disclosing what actually exists).

    Containment is checked on the raw name and on the *parent's* resolved path,
    and the candidate itself is never resolved: ``build/`` is a real directory,
    but things inside a bundle are symlinks (``Legal framework/*.md``), so a
    resolved containment test would start refusing legitimate bundles.
    """
    if not _BUNDLE_DIR_RE.fullmatch(violation_id or ""):
        return None
    root = find_workspace_root().resolve()
    bundle = root / "build" / violation_id
    # Belt and braces: the name is already separator-free, but confirm the
    # resolved path is still a direct child of build/ before reading anything.
    if bundle.parent.resolve() != (root / "build").resolve():
        return None
    return bundle if is_bundle_dir(bundle) else None


def bundle_target(body: Any) -> tuple[Path | None, str, str, int]:
    """Resolve the ``violation_id`` + ``authority_id`` pair the source routes take.

    Returns ``(bundle, authority_id, error, status)``, with an empty error when the
    pair is good. Shared by both routes rather than repeated, because this is where
    a *safety* decision is made — which bundle, and which stub — and one of those
    routes deletes files from that bundle. Two copies of this check are two chances
    for the two routes to disagree about what a stub is.
    """
    violation_id = body.get("violation_id")
    if not isinstance(violation_id, str) or not _BUNDLE_DIR_RE.fullmatch(violation_id):
        return None, "", "'violation_id' must be a bundle id.", 400
    bundle = resolve_bundle_dir(violation_id)
    if bundle is None:
        return None, "", f"No bundle build/{violation_id}/ on disk.", 404
    authority_id = body.get("authority_id")
    if not isinstance(authority_id, str) or not authority_id.strip():
        return None, "", "'authority_id' is required.", 400
    return bundle, authority_id.strip(), "", 200


def discover_bundle(violation_id: str) -> dict[str, Any] | None:
    """Read one real ``build/<violation_id>/`` bundle for the UI.

    Read-only and filesystem-only: it dispatches no tool and writes nothing.
    """
    root = find_workspace_root().resolve()
    bundle = resolve_bundle_dir(violation_id)
    if bundle is None:
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
    from .pack import BUNDLE_LAYOUT, SOURCE_DIRECTORY_KINDS
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
        # Which of those keys name a folder a source is *copied into*. Published
        # rather than mirrored in the page: the S0 picker has to show where a
        # file will land before it stages it, and a second copy of this list is
        # how the preview comes to disagree with the write.
        "source_directory_kinds": sorted(SOURCE_DIRECTORY_KINDS),
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
    authoritative — per-file symlinks into ``transcription/``, see
    ``docs/data_source_of_truth.md`` §3.2) and ``data/transcripts/html/*.html``
    (a vendored render, real content rather than symlinks — §3.4).

    Containment is checked on the **lexical** path, never on a symlink-resolved
    one. Every ``data/transcripts/json/*.json`` is a symlink, so resolving the
    candidate followed that link straight out of ``data/transcripts/json``, the
    ``relative_to`` test failed, and **every** canonical URI was refused with a
    400 while the HTML render kept working — the whole canonical corpus was
    unreachable and it looked like a UI bug rather than a containment bug.

    Containment has two separate jobs and they are worth keeping apart.

    *Escaping the corpus* is prevented by the join: only ``normalised.name`` —
    a single path component — is ever appended to the corpus directory, and
    ``normpath`` never leaves a trailing ``..``, so no URI can address a file
    outside ``data/transcripts/<kind>/``. No other check is load-bearing there.

    *Refusing traversal-shaped URIs* is the shape test's job, and it must run
    on the **raw** parts. ``Path.parts`` is lexical and keeps ``..``, whereas
    ``os.path.normpath`` collapses ``json/sub/../x.json`` onto ``json/x.json`` —
    so a shape test written against the normalised path compares a tuple with
    itself and passes by construction, accepting the very forms it claims to
    refuse. Requiring the raw URI to be exactly
    ``data/transcripts/<json|html>/<name>`` — four parts, so no subdirectory and
    no ``..`` can exist — is the real check. Without it those URIs resolve to a
    genuine file, i.e. a path that visibly walks out of the corpus quietly reads
    a top-level transcript, which is the same "well-formed but not what it looks
    like" confusion that hid this bug in the first place.
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
    kind = suffix.lstrip(".")
    if candidate.parts != ("data", "transcripts", kind, candidate.name):
        return None
    if candidate.name in {".", ".."}:
        return None
    resolved = data_root / "transcripts" / kind / candidate.name
    return resolved if resolved.is_file() else None


def transcript_uri_reason(uri: str) -> str:
    """Explain *why* ``discover_transcript`` refused ``uri`` (diagnostics only).

    ``discover_transcript`` returns ``None`` for two unrelated situations — the
    URI never resolved to a corpus file, or it resolved but the reader could not
    parse it. Answering both with one opaque message is how a containment bug
    that rejected **every** canonical JSON URI was able to masquerade as a
    broken segment browser instead of a 400 that said what was wrong. The route
    now reports the specific reason.
    """
    if not uri:
        return "no uri was supplied"
    data_root = find_data_root()
    if data_root is None:
        return "no data/ directory holding law/ and transcripts/ was found"
    if _resolve_transcript_uri(uri) is not None:
        return "the transcript was found but its reader could not parse it"
    candidate = Path(uri)
    if candidate.is_absolute():
        return "absolute paths are not accepted"
    if candidate.parts[:2] != ("data", "transcripts"):
        return "uri must start with data/transcripts/"
    suffix = candidate.suffix.lower()
    if suffix not in {".json", ".html"}:
        return f"unsupported transcript extension {candidate.suffix or '(none)'}"
    kind = suffix.lstrip(".")
    # Mirrors `_resolve_transcript_uri`'s raw-parts shape test — a reason string
    # that disagrees with the resolver is worse than no reason at all.
    if candidate.parts != ("data", "transcripts", kind, candidate.name):
        return (
            f"uri must name a file directly inside data/transcripts/{kind}/ "
            "(subdirectories and '..' are refused)"
        )
    return f"data/transcripts/{kind}/{candidate.name} does not exist"


# A framework cache lives inside the bundle that recorded it, at
# `Legal framework/<name>.md` — the exact path listed in
# `violation.framework_caches[].cache_file`. That directory name has a space in
# it, so it is compared as a whole path component and never split.
_FRAMEWORK_CACHE_DIR = "Legal framework"


def _resolve_framework_uri(uri: str) -> Path | None:
    """Resolve a bundle's cached framework Markdown without allowing traversal.

    Only one shape is accepted: ``build/<violation_id>/Legal framework/<name>.md``
    — the cache the bundle itself recorded, which is what ``build_norms_layer_tool``
    validates a verbatim excerpt against. A discovered-but-uncached framework
    under ``data/law/`` is deliberately *not* accepted: filling the excerpt from
    a file the bundle does not carry would produce a quote that cannot pass
    validation, so the picker must not offer it.

    Containment is checked on the raw ``Path.parts`` and the file is **never**
    resolved through ``.resolve()``. Every ``build/<id>/Legal framework/*.md``
    is itself a symlink into ``transcription/data/law/``, so resolving the
    candidate walks out of the bundle and a resolved-containment test would
    refuse every one of them — the same trap that once made the whole canonical
    JSON transcript corpus unreachable (see ``_resolve_transcript_uri``). The
    lexical shape test is what refuses ``..``; the join is what keeps the read
    inside the bundle.
    """
    root = find_workspace_root()
    candidate = Path(uri)
    if candidate.is_absolute():
        return None
    parts = candidate.parts
    if len(parts) != 4 or parts[0] != "build" or parts[2] != _FRAMEWORK_CACHE_DIR:
        return None
    if candidate.suffix.lower() != ".md":
        return None
    if not _BUNDLE_DIR_RE.fullmatch(parts[1]):
        return None
    if parts[3] in {".", ".."}:
        return None
    joined = root / "build" / parts[1] / _FRAMEWORK_CACHE_DIR / parts[3]
    return joined if joined.is_file() else None


def framework_uri_reason(uri: str) -> str:
    """Explain *why* ``_resolve_framework_uri`` refused ``uri`` (diagnostics only).

    Mirrors the resolver's raw-parts test exactly, for the same reason
    ``transcript_uri_reason`` does: a reason that disagrees with the resolver
    sends the reader after the wrong cause.
    """
    if not uri:
        return "no uri was supplied"
    candidate = Path(uri)
    if candidate.is_absolute():
        return "absolute paths are not accepted"
    parts = candidate.parts
    if len(parts) != 4 or parts[0] != "build" or parts[2] != _FRAMEWORK_CACHE_DIR:
        return (
            "uri must name a file directly inside "
            f"build/<violation_id>/{_FRAMEWORK_CACHE_DIR}/ "
            "(subdirectories and '..' are refused)"
        )
    if candidate.suffix.lower() != ".md":
        return f"unsupported framework extension {candidate.suffix or '(none)'}"
    if not _BUNDLE_DIR_RE.fullmatch(parts[1]):
        return f"{parts[1]!r} is not a bundle id"
    return f"build/{parts[1]}/{_FRAMEWORK_CACHE_DIR}/{parts[3]} does not exist"


def discover_framework_article(uri: str, article: str) -> dict[str, Any] | None:
    """Return one cached article's verbatim body plus the id the cache declares.

    The body is the text as it sits in the cache, metadata block stripped, so it
    is a byte-exact substring of the cached framework text — exactly the
    property ``build_norms_layer_tool`` checks a verbatim excerpt for.

    With **no** ``article`` the cache is listed instead: every key it holds and
    nothing else, with the body fields left ``None``. A framework staged into
    the bundle at S0 has no ``framework_caches`` row yet, so its article numbers
    exist nowhere but in the file — and the picker may only offer what this
    route can read back. The two modes are one function on purpose: a second
    reader with its own notion of "the bundle's cache" is how the picker came to
    disagree with the reader in the first place.
    """
    path = _resolve_framework_uri(uri)
    if path is None:
        return None
    from .sources import MarkdownFrameworkSource

    # Same code derivation `/api/sources` publishes, so the picker's code and
    # this reader's code can never disagree (CPCL_CP.md -> CPCL).
    code = path.stem.split("_")[0].upper()
    source = MarkdownFrameworkSource(path, code, uri)
    if not article:
        # Identical keys to the article shape below (asserted by a test), so a
        # caller reads one shape with some fields empty rather than two shapes.
        return {
            "ok": True,
            "uri": uri,
            "name": path.name,
            "framework_code": code,
            "article": None,
            "article_id": None,
            "article_name": None,
            "body": None,
            "body_sha256": None,
            "cache_sha256": source.cache_sha256(),
            "articles": source.articles_cached(),
        }
    body = source.get_article_body(article)
    if body is None:
        return None
    return {
        "ok": True,
        "uri": uri,
        "name": path.name,
        "framework_code": code,
        "article": article,
        # The id and title come from the cache's own metadata, never from a
        # reconstruction of the article number: only the cache knows the
        # hierarchy segments ('C1', 'T2.P6') and whether it declares an ELI id
        # at all.
        "article_id": source.get_article_eli_id(article),
        "article_name": source.get_article_title(article),
        "body": body,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "cache_sha256": source.cache_sha256(),
        "articles": source.articles_cached(),
    }


def framework_article_reason(uri: str, article: str) -> str:
    """Explain *why* ``discover_framework_article`` returned ``None``.

    Two unrelated causes share that ``None`` — an unresolvable cache, and an
    article the cache does not hold — and collapsing them is how a containment
    bug hid inside a generic 400 for the transcripts. The uri is therefore
    resolved first: a request naming no article only ever fails for that reason.
    """
    path = _resolve_framework_uri(uri)
    if path is None:
        return framework_uri_reason(uri)
    if not article:
        # Unreachable through the route — a blank article lists the cache rather
        # than failing — but a direct caller must be told the two are different
        # things instead of being handed an "article '' is missing" sentence.
        return "no article number was supplied"
    from .sources import MarkdownFrameworkSource

    code = path.stem.split("_")[0].upper()
    known = MarkdownFrameworkSource(path, code, uri).articles_cached()
    listed = ", ".join(known[:8]) + ("…" if len(known) > 8 else "")
    return (
        f"article {article!r} is not one of the {len(known)} article(s) "
        f"{path.name} caches ({listed})"
    )


# ---------------------------------------------------------------------------
# Is this candidate's article in the bundle?
# ---------------------------------------------------------------------------

# A candidate id is a *claimed* ELI id, and the hierarchy segments are the part
# the claim gets wrong. Measured on the live corpus: the CL-030 bundle's caches
# declare `CL.CPCL.C1.Art.223` where the candidate says `CL.CPCL.T4.Art.223`, and
# `CL.CONST.T1.C3.P3.Art.19.3` where the candidate says `CL.CPR.Art.19.3`. So a
# lookup keyed on the whole id reports "not here" while the article is sitting in
# the bundle — which is precisely the case a reviewer wants checked. The tail
# after `Art.` is the one segment both spellings agree on, and it is what this
# check matches on.
_ARTICLE_TAIL_PATTERN = re.compile(
    r"(?:^|\.)art\.?\s*([0-9]+(?:[._][A-Za-z0-9]+)*)", re.IGNORECASE
)
# `| **Framework code** | CPCL / CPENAL |` — a cache may declare more than one.
_FRAMEWORK_CODE_LINE_PATTERN = re.compile(
    r"^\|\s*\*\*Framework code\*\*\s*\|([^|]*)\|", re.MULTILINE
)


def _article_tail(reference: str) -> str | None:
    """The article number in an ELI-shaped reference, or ``None`` when it names no article.

    Only the *last* ``Art.`` marker counts: the token can also appear inside a
    title segment, and the operator's reference is the trailing one.
    """
    matches = _ARTICLE_TAIL_PATTERN.findall(reference or "")
    return matches[-1] if matches else None


def _reference_code(reference: str) -> str:
    """The statute a reference names, as ``<JUR>.<CODE>``.

    ELI ids put the hierarchy segments *after* the code, so the first two
    segments name the statute even when the segments that follow are wrong:
    ``CL.CPCL.T4.Art.223`` and ``CL.CPCL.C1.Art.223`` are both the Código Penal.
    """
    parts = [p for p in (reference or "").split(".") if p]
    return ".".join(parts[:2]) if len(parts) >= 2 else (reference or "")


def _declared_eli_ids(source: Any) -> dict[str, str]:
    """The ELI id each cached article declares, keyed by its header identifier."""
    ids: dict[str, str] = {}
    for identifier in source.articles_cached():
        eli = source.get_article_eli_id(identifier)
        if eli:
            ids[identifier] = eli
    return ids


def _framework_codes(path: Path, source: Any, eli_ids: dict[str, str]) -> set[str]:
    """Every name one cache file can be recognized by.

    Three independent declarations, and all three are needed. The file stem is
    what ``discover_framework_article`` uses (``CPCL_CP.md`` -> ``CPCL``), the
    metadata table may name more than one (``CPCL / CPENAL``), and the prefixes
    of the ELI ids its own articles declare are the *only* name a cache without a
    metadata table has — ``build/CL-030/Legal framework/Constitucion.md`` carries
    no table at all and is recognizable only as ``CL.CONST``.
    """
    codes = {path.stem.split("_")[0].upper()}
    match = _FRAMEWORK_CODE_LINE_PATTERN.search(source.raw_text() or "")
    if match:
        for token in re.split(r"[/,]", match.group(1)):
            token = token.strip().upper()
            if token:
                codes.add(token)
    for eli in eli_ids.values():
        parts = [p for p in eli.split(".") if p]
        if len(parts) >= 2:
            codes.add(".".join(parts[:2]))
            codes.add(parts[1].upper())
    return codes


def _match_cached_article(
    source: Any,
    eli_ids: dict[str, str],
    normalized_reference: str,
    article_tail: str | None,
) -> tuple[str, str] | None:
    """Find the cached article a candidate reference names, as ``(identifier, how)``.

    Four attempts, in order, and the order is the finding:

    1. the whole reference equals a declared ELI id (a candidate that is already
       spelled canonically);
    2. the reference's article tail equals a declared ELI id's article tail —
       ``CL.CPCL.T4.Art.223`` finding ``CL.CPCL.C1.Art.223``. This is the attempt
       that matters, because the segments before ``Art.`` are the part the
       candidate gets wrong;
    3. a reference naming no article at all, matched against the whole declared id
       by prefix (``INT.AN9.C3.S44``);
    4. the header identifier, resolved through the reader's own
       ``_resolve_article_key`` — so a candidate number and the excerpt later read
       against it cannot resolve to two different articles.

    Tails are compared for *equality* and never by prefix: ``Art.223`` must not
    be satisfied by ``Art.2234``, which the reader's prefix rule would allow for
    a bare number.
    """
    from .sources import _normalize_article_key

    wanted_tail = _normalize_article_key(article_tail) if article_tail else None
    for identifier, eli in eli_ids.items():
        if _normalize_article_key(eli) == normalized_reference:
            return identifier, "eli_id"
    if wanted_tail is not None:
        for identifier, eli in eli_ids.items():
            declared_tail = _article_tail(eli)
            if declared_tail and _normalize_article_key(declared_tail) == wanted_tail:
                return identifier, "eli_id"
    else:
        for identifier, eli in eli_ids.items():
            if _normalize_article_key(eli).startswith(normalized_reference):
                return identifier, "eli_id_prefix"
    if article_tail:
        key = source._resolve_article_key(article_tail)
        if key is not None:
            return key, "header"
    return None


def discover_candidate_article(violation_id: str, reference: str) -> dict[str, Any] | None:
    """Answer whether a candidate's article is in the bundle, from the files on disk.

    ``None`` means the check *could not run* — no such bundle, or no reference —
    and never "not found". A candidate the bundle does not carry is the answer
    this route exists to give, so it comes back with ``in_bundle: False`` and a
    reason. Collapsing the two would let a typo in a bundle id read as a
    verification that failed.

    The recorded ``framework_cache_status`` on the candidate cannot answer this.
    It is written by the LLM ``candidates`` stage and re-decided only when that
    stage re-runs, so it keeps saying ``not_in_bundle`` for an article staged
    into the bundle afterwards — measured on CL-030: two framework files were
    added under ``Legal framework/`` and the candidate for ``Art. 223`` still
    read ``not_in_bundle``.

    Nothing outside the bundle is read. A statute in ``data/law/`` that the
    bundle does not carry is **not** in the bundle, and answering from there
    would make this check agree with a reader that later refuses to quote the
    text (``_resolve_framework_uri``'s whole rationale).

    Every framework file is reported, not just the match, because the bundle can
    hold the same article twice — ``Art. 269 ter`` is cached in both ``CPCL.md``
    and ``CodigoPenal_269bis_269ter.md`` of CL-030 — and a check that hid the
    second copy would be describing a bundle other than the one on disk.
    """
    from .sources import MarkdownFrameworkSource, _normalize_article_key

    bundle = resolve_bundle_dir(violation_id)
    if bundle is None:
        return None
    reference = (reference or "").strip()
    if not reference:
        return None

    directory = bundle / _FRAMEWORK_CACHE_DIR
    names = sorted(item.name for item in directory.glob("*.md")) if directory.is_dir() else []

    articles_tail = _article_tail(reference)
    code = _reference_code(reference)
    code_bare = code.split(".")[-1]
    normalized_reference = _normalize_article_key(reference)

    files: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []
    for name in names:
        uri = f"build/{violation_id}/{_FRAMEWORK_CACHE_DIR}/{name}"
        # Through the same resolver the reader uses, so this check can only ever
        # speak about files `/api/framework-article` would read back.
        path = _resolve_framework_uri(uri)
        if path is None:
            continue
        stem_code = path.stem.split("_")[0].upper()
        source = MarkdownFrameworkSource(path, stem_code, uri)
        eli_ids = _declared_eli_ids(source)
        codes = _framework_codes(path, source, eli_ids)
        file_entry = {
            "uri": uri,
            "rel": f"{_FRAMEWORK_CACHE_DIR}/{name}",
            "name": name,
            "framework_code": stem_code,
            "codes": sorted(codes),
            # Whether this file is even *about* the statute the candidate names.
            # The bare code is compared too: a cache declares `CPCL`, the
            # candidate writes `CL.CPCL`, and both are the same statute.
            "code_agrees": code in codes or code_bare in codes,
            "articles": source.articles_cached(),
            "eli_ids": [eli_ids[key] for key in source.articles_cached() if key in eli_ids],
        }
        files.append(file_entry)
        found = _match_cached_article(source, eli_ids, normalized_reference, articles_tail)
        if found is None:
            continue
        identifier, how = found
        matches.append({
            "uri": uri,
            "rel": file_entry["rel"],
            "matched_by": how,
            "article": identifier,
            # The declared id, never a reconstruction: the hierarchy segments are
            # this file's to state and nothing else can supply them.
            "article_id": eli_ids.get(identifier),
            "article_name": source.get_article_title(identifier),
            "code_agrees": file_entry["code_agrees"],
            "cache_sha256": source.cache_sha256(),
        })

    agreeing = [m for m in matches if m["code_agrees"]]
    if agreeing:
        verdict = "in_bundle"
    elif matches:
        # Found, but in a file for a different statute — `Art. 6` exists in
        # several codes. Reported as a miss with the near-match named, never as
        # a pass: a check that quietly widened its own scope could not be
        # trusted to be narrow.
        verdict = "in_bundle_other_code"
    else:
        verdict = "not_in_bundle"

    return {
        "ok": True,
        "violation_id": violation_id,
        "reference": reference,
        "framework_code": code,
        "article_tail": articles_tail,
        "in_bundle": verdict == "in_bundle",
        "verdict": verdict,
        "matches": matches,
        "files": files,
    }


def candidate_article_reason(violation_id: str, reference: str) -> str:
    """Explain *why* ``discover_candidate_article`` returned ``None``.

    Mirrors the resolver's two causes exactly. A reason that disagreed with the
    resolver would send the reader after the wrong cause, the same trap
    ``framework_article_reason`` documents.
    """
    if resolve_bundle_dir(violation_id) is None:
        return f"No bundle build/{violation_id}/ on disk."
    if not (reference or "").strip():
        return "no article reference was supplied"
    return f"build/{violation_id}/ could not be read"


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
# Long-running tool calls
# ---------------------------------------------------------------------------
#
# `ToolManager` invokes a *synchronous* tool directly (`mcp/server/fastmcp/
# utilities/func_metadata.py` ends in `return fn(**arguments_parsed_dict)`), so
# awaiting `call_tool` from a request handler runs the whole tool on the event
# loop. Measured against the live server: a `/api/health` poll sent 0.02 s into
# an 8.96 s `enrich_violation_tool` call was answered at 8.98 s — nothing at all
# was served in between. A full eight-stage enrichment is minutes, which is why
# the page could not show that a run was in progress: it could not even ask.
#
# `background: true` on `/api/tool` therefore returns a job id immediately and
# runs the call on a worker thread; the page polls `/api/tool-job`. Two
# consequences worth stating: the HTTP requests are all short (no client-side
# timeout can abort a six-minute call), and the event loop stays free to answer
# both the poll and everything else the page is doing.

_JOB_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
#: Insertion-ordered job ids; the oldest is dropped once `_MAX_JOBS` is reached.
_JOB_ORDER: list[str] = []
_MAX_JOBS = 20


def _call_tool_blocking(tool_manager, name: str, args: dict[str, Any]) -> Any:
    """Run one tool call to completion on the calling thread.

    `call_tool` is a coroutine but calls a synchronous tool inline, so it needs
    a loop to run in — and it must be a *different* loop from the server's, or
    the blocking lands back on the event loop this exists to protect. The tool
    functions are pure sync code, so a private loop per call is safe.
    """
    return asyncio.run(tool_manager.call_tool(name, args))


def _job_claim(tool: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Atomically take the single running-job slot, or name who holds it.

    Claiming and checking in one locked step is what makes "tap twice" safe at
    the protocol level and not merely in the page: two requests that arrive
    together cannot both see an idle server.
    """
    with _JOB_LOCK:
        for job_id in reversed(_JOB_ORDER):
            running = _JOBS.get(job_id)
            if running is not None and running["status"] == "running":
                return None, running
        job: dict[str, Any] = {
            "job_id": uuid.uuid4().hex[:12],
            "tool": tool,
            "status": "running",
            "started": time.time(),
            "finished": None,
            "result": None,
            "error": None,
            "error_type": None,
        }
        _JOBS[job["job_id"]] = job
        _JOB_ORDER.append(job["job_id"])
        while len(_JOB_ORDER) > _MAX_JOBS:
            _JOBS.pop(_JOB_ORDER.pop(0), None)
        return job, None


async def _run_job(job: dict[str, Any], tool_manager, name: str, args: dict[str, Any]) -> None:
    """The background task behind one `/api/tool` call.

    The tool's own exception is the payload, not a crash: it is stored and
    returned by `/api/tool-job` so the page can show the same message it used to
    read out of a 400 response.
    """
    try:
        job["result"] = await asyncio.to_thread(_call_tool_blocking, tool_manager, name, args)
        job["status"] = "done"
    except Exception as exc:  # noqa: BLE001 - the failure is the response
        job["status"] = "error"
        job["error"] = str(exc)
        job["error_type"] = type(exc).__name__
    finally:
        job["finished"] = time.time()


def _job_snapshot(job_id: str) -> dict[str, Any] | None:
    """One job as a JSON-ready dict, plus what the worker last reported."""
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        payload = dict(job) if job is not None else None
    if payload is None:
        return None
    # A job that failed is not an ok payload. The page branches on `status`, but
    # `ok` is the field every other response in this bridge uses for its
    # verdict, and a failure that reports `ok: true` would be the one place the
    # convention lies.
    payload["ok"] = payload["status"] != "error"
    payload["seconds"] = round((payload.get("finished") or time.time()) - payload["started"], 1)
    if payload["status"] == "running":
        live = progress.snapshot()
        if live:
            payload["progress"] = live
    return payload


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

    async def read_json_object(request) -> tuple[dict[str, Any] | None, JSONResponse | None]:
        """Parse a JSON object body, or the refusal to send back.

        Both source routes take the same single-object body, and this bridge has
        exactly one body parser and one error shape on purpose: the upload travels
        as base64 inside JSON rather than as multipart so that there is no second
        way to fail.
        """
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - malformed JSON is a client error
            return None, json_response(
                {"ok": False, "error": "Request body must be JSON."}, status_code=400
            )
        if not isinstance(body, dict):
            return None, json_response(
                {"ok": False, "error": "Request body must be a JSON object."},
                status_code=400,
            )
        return body, None

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
                    "error": f"could not read transcript — {transcript_uri_reason(uri)}",
                    "uri": uri,
                },
                status_code=400,
            )
        return json_response(payload)

    @mcp.custom_route("/api/framework-article", methods=["GET", "OPTIONS"])
    async def api_framework_article(request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)
        uri = request.query_params.get("uri", "")
        article = request.query_params.get("article", "")
        payload = discover_framework_article(uri, article)
        if payload is None:
            return json_response(
                {
                    "ok": False,
                    "error": f"could not read article — {framework_article_reason(uri, article)}",
                    "uri": uri,
                    "article": article,
                },
                status_code=400,
            )
        return json_response(payload)

    @mcp.custom_route("/api/candidate-article", methods=["GET", "OPTIONS"])
    async def api_candidate_article(request) -> Response:
        """Check whether one candidate's article is in the bundle, on disk.

        The S3 candidate rows show ``framework_cache_status``, which is a
        *recorded* field: the LLM ``candidates`` stage writes it and only that
        stage ever re-decides it, so an article staged into the bundle afterwards
        keeps reading ``not_in_bundle`` and the row cannot tell the reviewer
        whether their staging worked. This route answers the same question from
        the files the bundle actually carries, and it is the only thing that can.

        A GET, and read-only: it cannot promote a candidate, cannot rewrite the
        recorded status, and cannot write to the bundle. A check that re-recorded
        its own answer would be a check on its own output.

        Both parameters travel as query strings because the request *names* an
        article; it does not carry one — the same reasoning
        ``/api/authority-source/reading`` gives for its three.

        A miss is a 200. The two failures this route reports as 4xx are "no such
        bundle" and "no reference given", and neither is an answer about the
        article, so neither may be allowed to look like one.
        """
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)
        violation_id = request.query_params.get("violation_id", "")
        reference = request.query_params.get("article", "")
        payload = discover_candidate_article(violation_id, reference)
        if payload is None:
            return json_response(
                {
                    "ok": False,
                    "error": (
                        "could not check the article — "
                        f"{candidate_article_reason(violation_id, reference)}"
                    ),
                    "violation_id": violation_id,
                    "article": reference,
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

    @mcp.custom_route("/api/bundle-source", methods=["POST", "OPTIONS"])
    async def api_bundle_source(request) -> Response:
        """Stage one source-of-truth file into the bundle.

        Two ways in, one destination rule. ``source_path`` names a file already
        in the workspace (what the picker hands back after browsing
        ``data/law`` or ``data/transcripts``), while ``content_base64`` +
        ``filename`` carries bytes the browser holds and the server has never
        seen. Both land through ``pack.staged_source_path``, so a reviewer who
        drags a PDF in and one who picks the same file out of ``data/law`` get
        the same layout — that split is the whole reason this route exists
        rather than the UI calling ``copy_source_into_bundle_tool`` directly.

        The upload travels as base64 inside JSON, not multipart: this bridge has
        exactly one body parser and one error shape, and adding a second one for
        one field would mean two ways to fail.

        Nothing here decides *what* a source is, and nothing here touches the
        violation JSON. It writes the bytes a later tool will hash against, and
        reports the sha256 it wrote so the reviewer can compare it with the
        manifest rather than trust that the copy happened.
        """
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)

        from .authority_source import MAX_UPLOAD_BYTES, SourceError, decode_base64_payload
        from .pack import (
            BUNDLE_LAYOUT,
            copy_source_into_bundle,
            is_layout_kind,
            staged_source_path,
            write_source_into_bundle,
        )

        body, refusal = await read_json_object(request)
        if refusal is not None:
            return refusal

        violation_id = body.get("violation_id")
        if not isinstance(violation_id, str) or not _BUNDLE_DIR_RE.fullmatch(violation_id):
            return json_response({"ok": False, "error": "'violation_id' must be a bundle id."}, status_code=400)
        bundle = resolve_bundle_dir(violation_id)
        if bundle is None:
            return json_response(
                {"ok": False, "error": f"No bundle build/{violation_id}/ on disk."}, status_code=404
            )

        kind = body.get("kind")
        if not is_layout_kind(kind):
            return json_response(
                {
                    "ok": False,
                    "error": "'kind' must be a bundle layout key.",
                    "kinds": sorted(BUNDLE_LAYOUT),
                },
                status_code=400,
            )

        source_path = body.get("source_path")
        content = body.get("content_base64")
        if isinstance(content, str) and content.strip():
            # Upload: the browser holds the only copy, so the name comes from
            # the request — reduced to a basename by `staged_source_path`.
            try:
                data = decode_base64_payload(content)
            except SourceError as exc:
                return json_response({"ok": False, "error": str(exc)}, status_code=400)
            if len(data) > MAX_UPLOAD_BYTES:
                return json_response(
                    {
                        "ok": False,
                        "error": f"upload is {len(data)} bytes; the limit is "
                        f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MiB",
                    },
                    status_code=400,
                )
            allowed_name = body.get("filename")
            if not isinstance(allowed_name, str) or not allowed_name.strip():
                return json_response({"ok": False, "error": "'filename' is required for an upload."}, status_code=400)
            source = "upload"
            stage_name = allowed_name.strip()
            stage = lambda: write_source_into_bundle(bundle, kind, stage_name, data)  # noqa: E731
        elif isinstance(source_path, str) and source_path.strip():
            picked = resolve_workspace_path(source_path.strip(), "file")
            if picked is None:
                return json_response(
                    {"ok": False, "error": f"{source_path!r} is not a file inside the workspace."},
                    status_code=400,
                )
            source = str(source_path.strip())
            stage_name = picked.name
            stage = lambda: copy_source_into_bundle(picked, bundle, kind)  # noqa: E731
        else:
            return json_response(
                {
                    "ok": False,
                    "error": "send either 'source_path' or 'content_base64' + 'filename'.",
                },
                status_code=400,
            )

        # Where it is about to land is computed *before* the write, from the
        # bundle and the layout — not from what the request claimed, and not
        # from where the file happens to be. For a folder kind the destination
        # is `<folder>/<basename>`, so a staging control that reported only the
        # name it was given would be unable to say which of two files it just
        # replaced.
        try:
            predicted = staged_source_path(bundle, kind, stage_name)
        except (KeyError, ValueError) as exc:
            return json_response({"ok": False, "error": f"could not stage the source ({exc})"}, status_code=400)
        overwritten = predicted.is_file()

        try:
            dest = stage()
        except (KeyError, ValueError, OSError) as exc:
            return json_response(
                {"ok": False, "error": f"could not stage the source ({type(exc).__name__}: {exc})"},
                status_code=400,
            )

        staged = dest.read_bytes()
        return json_response({
            "ok": True,
            "violation_id": violation_id,
            "kind": kind,
            "source": source,
            "name": dest.name,
            "destination": dest.relative_to(bundle).as_posix(),
            "path": str(dest),
            "bytes": len(staged),
            "sha256": hashlib.sha256(staged).hexdigest(),
            # Reported so the UI can say a file was replaced rather than added:
            # a staged source is proof, and silently overwriting one is the kind
            # of edit that is only noticed long after the quote it backed.
            "overwritten": overwritten,
        })

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
                        "violation_id must name an existing bundle directory "
                        "under build/ (e.g. CL-005, BR-001, INT-019)."
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

        if body.get("background") is True:
            job, busy = _job_claim(name)
            if job is None:
                return json_response(
                    {
                        "ok": False,
                        "busy": True,
                        "job_id": busy["job_id"],
                        "running_tool": busy["tool"],
                        "error": (
                            f"{busy['tool']} is already running; wait for it to "
                            "finish before starting another tool."
                        ),
                    },
                    status_code=409,
                )
            asyncio.create_task(_run_job(job, tool_manager, name, args))
            return json_response(
                {"ok": True, "job_id": job["job_id"], "tool": name, "status": "running"},
                status_code=202,
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

    @mcp.custom_route("/api/tool-job", methods=["GET", "OPTIONS"])
    async def api_tool_job(request) -> Response:
        """Poll a background tool call started with ``{"background": true}``.

        Answers with ``status`` of ``running`` / ``done`` / ``error``, the tool
        result once there is one, and — while running — whatever the worker last
        published through ``violation_pack.progress``. Polling is deliberately
        cheap: a running job carries no result and only the newest progress.
        """
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)
        job_id = request.query_params.get("id", "")
        payload = _job_snapshot(job_id)
        if payload is None:
            return json_response(
                {"ok": False, "error": f"Unknown job id: {job_id!r}"}, status_code=404
            )
        return json_response(payload)

    # -- authority sources --------------------------------------------------

    @mcp.custom_route("/api/authority-source", methods=["POST", "OPTIONS"])
    async def api_authority_source(request) -> Response:
        """Ingest the official source behind one authority stub.

        Storing and verifying are separate on purpose. This route writes only
        into the bundle's ``Authority sources/`` directory and hands back the
        exact text to match; the ``verified`` flag is still flipped by a
        ``verify_*`` tool through ``/api/tool``, so the one invariant that
        matters — only ``authority_verification.py`` may verify an authority —
        is untouched by this feature.

        The upload travels as base64 inside JSON rather than as multipart: this
        bridge has exactly one body parser and one error shape, and adding a
        second one for one field would mean two ways to fail.
        """
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)

        from .authority_source import SourceError, decode_base64_payload, ingest_source

        body, refusal = await read_json_object(request)
        if refusal is not None:
            return refusal

        bundle, authority_id, error, status_code = bundle_target(body)
        if error:
            return json_response({"ok": False, "error": error}, status_code=status_code)

        data = None
        if isinstance(body.get("content_base64"), str) and body["content_base64"].strip():
            try:
                data = decode_base64_payload(body["content_base64"])
            except SourceError as exc:
                return json_response({"ok": False, "error": str(exc)}, status_code=400)

        def string_arg(key: str) -> str | None:
            value = body.get(key)
            return value if isinstance(value, str) and value.strip() else None

        try:
            result = ingest_source(
                bundle,
                authority_id,
                source_url=string_arg("source_url"),
                filename=string_arg("filename"),
                data=data,
                text=body.get("text") if isinstance(body.get("text"), str) else None,
                do_fetch=body.get("fetch_url") is True,
                collapse=body.get("collapse_whitespace") is True,
            )
        except SourceError as exc:
            return json_response({"ok": False, "error": str(exc)}, status_code=400)

        return json_response(result)

    @mcp.custom_route("/api/authority-source/delete", methods=["POST", "OPTIONS"])
    async def api_authority_source_delete(request) -> Response:
        """Remove one stored source, so a stale document can be replaced.

        The body names *one* file, and which other files belong to it — the
        ``.proof.json`` sidecar and the matched ``.text.txt`` — is decided inside
        the bundle by ``proof_group``, never by the browser. That split is the
        point of the route: deleting proof is irreversible, the bundle may hold the
        only copy of the document, and a client that got the grouping wrong (or
        sent a name on purpose) must not be able to reach a file the reviewer was
        never shown.

        Separate from ``POST /api/authority-source`` rather than a verb inside it,
        because the two do opposite things to the bundle and only one of them can
        destroy proof — a route that reads as a store should never be able to
        unlink because of a field it did not expect.
        """
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)

        from .authority_source import SourceError, delete_source

        body, refusal = await read_json_object(request)
        if refusal is not None:
            return refusal

        bundle, authority_id, error, status_code = bundle_target(body)
        if error:
            return json_response({"ok": False, "error": error}, status_code=status_code)

        try:
            result = delete_source(bundle, authority_id, body.get("name"))
        except SourceError as exc:
            return json_response({"ok": False, "error": str(exc)}, status_code=400)

        return json_response(result)

    @mcp.custom_route("/api/authority-source/reading", methods=["GET", "OPTIONS"])
    async def api_authority_source_reading(request) -> Response:
        """Read back one stored source for a stub that already has proof on disk.

        ``POST /api/authority-source`` answers with the text it has just read, so
        the modal can only ever show a source loaded in this session. A source
        stored yesterday is on disk, is listed under "Proof on disk", and is
        described in its sidecar — and there was no way to ask: the reading, the
        margin citations and the numerals were write-only, legible by opening the
        ``.proof.json`` in an editor and invisible to the page that recorded them.
        That is backwards, because the recorder is where someone goes to check the
        recording.

        A GET, and the only one of the three source routes that cannot change the
        bundle. The three parameters travel as query strings rather than a body
        because that is what the method means: the request *names* a source, it does
        not carry one. ``name`` is the same argument the delete route takes, and is
        resolved by the same rule — the caller has the file listing and does not
        decide which files make up a source.

        The payload is whatever ``read_source`` returns, including its ``warnings``:
        a text file that no longer hashes to its own record is reported there rather
        than raised, because a caller that cannot see the text can do nothing at all
        with the file, and the mismatch is not a reason to withhold it.
        """
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)

        from .authority_source import SourceError, read_source

        bundle, authority_id, error, status_code = bundle_target({
            "violation_id": request.query_params.get("violation_id", ""),
            "authority_id": request.query_params.get("authority_id", ""),
        })
        if error:
            return json_response({"ok": False, "error": error}, status_code=status_code)

        try:
            result = read_source(bundle, authority_id, request.query_params.get("name", ""))
        except SourceError as exc:
            return json_response({"ok": False, "error": str(exc)}, status_code=400)

        return json_response(result)

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
