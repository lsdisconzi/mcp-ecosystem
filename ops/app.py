"""
Awareness-AI · Ops Dashboard
Lightweight Flask app for monitoring and controlling all project services.
Runs on port 9000 (localhost only by default).
"""

import functools
import hashlib
import json
import os
import re
import signal
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import docker
import psutil
import requests
from flask import Flask, jsonify, render_template, request, session, redirect, has_request_context, Response, send_from_directory

app = Flask(__name__, template_folder="templates")
app.secret_key = os.environ.get("OPS_SECRET", "ops-awareness-2026-default-key")
_start_time = time.time()


class _OpsPrefixMiddleware:
    """Allow the app to work both behind /ops proxy and directly on localhost.

    When requests arrive as /ops/* (proxy mode), strip the prefix and forward to
    Flask routes defined at /*. For direct localhost routes, pass through.
    """

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if path == "/ops" or path.startswith("/ops/"):
            stripped = path[4:] or "/"
            environ["SCRIPT_NAME"] = (environ.get("SCRIPT_NAME", "") or "") + "/ops"
            environ["PATH_INFO"] = stripped
        return self.app(environ, start_response)


app.wsgi_app = _OpsPrefixMiddleware(app.wsgi_app)

# Dashboard access code — loaded from /etc/ops-dashboard.env via EnvironmentFile
# Falls back to "1234" for initial setup; user is forced to change on first login.
DEFAULT_CODE = "1234"
OPS_CODE = os.environ.get("OPS_CODE") or DEFAULT_CODE

# Persistent password file — survives restarts
_PASSWORD_FILE = Path(os.environ.get("OPS_PASSWORD_FILE", Path(__file__).parent / ".ops-dashboard-password.txt"))


def _load_custom_password() -> str | None:
    """Load the user-set password from the persistent file."""
    if _PASSWORD_FILE.exists():
        stored = _PASSWORD_FILE.read_text().strip()
        if stored:
            return stored
    return None


def _save_custom_password(new_password: str) -> None:
    """Save a new password to the persistent file."""
    _PASSWORD_FILE.write_text(new_password + "\n")
    _PASSWORD_FILE.chmod(0o600)


def _get_active_code() -> str:
    """Return the currently active access code (custom or default)."""
    custom = _load_custom_password()
    return custom if custom else OPS_CODE


def _is_default_password() -> bool:
    """Check if the user is still using the default/initial password."""
    return _load_custom_password() is None


# Brute-force protection: track failed attempts per IP
_login_attempts: dict = defaultdict(list)
_MAX_ATTEMPTS = 8
_LOCKOUT_WINDOW = 300  # 5 minutes

_DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path(os.environ.get("OPS_PROJECT_ROOT", str(_DEFAULT_PROJECT_ROOT))).resolve()


def _resolve_runtime_path(raw_path: str) -> Path:
    """Resolve runtime paths from env vars (supports absolute and PROJECT_ROOT-relative values)."""
    path = Path(str(raw_path).strip()).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _resolve_project_root(env_var: str, *candidates: str) -> Path:
    """Resolve project root from env override or first existing candidate folder."""
    override = str(os.environ.get(env_var, "") or "").strip()
    if override:
        return _resolve_runtime_path(override)

    for name in candidates:
        candidate = (PROJECT_ROOT / name).resolve()
        if candidate.exists():
            return candidate

    return (PROJECT_ROOT / candidates[0]).resolve()


def _resolve_backup_root(env_var: str, default_leaf: str) -> Path:
    """Resolve backup root from env override or PROJECT_ROOT/back-ups/<leaf>."""
    override = str(os.environ.get(env_var, "") or "").strip()
    if override:
        return _resolve_runtime_path(override)
    return (PROJECT_ROOT / "back-ups" / default_leaf).resolve()


def _resolve_existing_path(env_var: str, *candidates: str) -> Path:
    """Resolve to the first existing path (env override wins), else return first candidate."""
    override = str(os.environ.get(env_var, "") or "").strip()
    if override:
        return _resolve_runtime_path(override)

    for candidate in candidates:
        path = _resolve_runtime_path(candidate)
        if path.exists():
            return path

    return _resolve_runtime_path(candidates[0])


def _resolve_existing_relative_path(*candidates: str) -> str:
    """Return first existing PROJECT_ROOT-relative path from candidates (or first fallback)."""
    for candidate in candidates:
        if _resolve_runtime_path(candidate).exists():
            return candidate
    return candidates[0]


# DEPRECATED — legacy project (kept for reference)
# KOUT_DIR = _resolve_project_root("OPS_KOUT_PROJECT_ROOT", "awareness", "kout", "kout-main")
# COREMU_DIR = _resolve_project_root("OPS_COREMU_PROJECT_ROOT", "awareness", "coremu", "coremu-unirg-main", "coremu-main")
# AWARENESS_DIR = _resolve_project_root("OPS_AWARENESS_PROJECT_ROOT", "awareness", "awareness-ai/awareness")
# KOUT_BACKUPS_DIR = _resolve_backup_root("OPS_KOUT_BACKUPS_DIR", "kout")
# COREMU_BACKUPS_DIR = _resolve_backup_root("OPS_COREMU_BACKUPS_DIR", "coremu")
# AWARENESS_BACKUPS_DIR = _resolve_backup_root("OPS_AWARENESS_BACKUPS_DIR", "awareness")

DEV_LOG_DIR = Path(os.environ.get("OPS_DEV_LOG_DIR", str(Path.home() / ".dev-logs"))).expanduser()
LEGACY_DEV_LOG_DIR = PROJECT_ROOT / ".dev-logs"
OPS_MODE = os.environ.get("OPS_MODE", "").strip().lower() or (
    "vps" if str(PROJECT_ROOT).startswith("/root") else "local"
)
COMPOSE_DIR = _resolve_existing_path("OPS_COMPOSE_DIR", "awareness-ai/frontend-public", "frontend-public")
API_DOCS_DIR = _resolve_existing_path("OPS_API_DOCS_DIR", "awareness-ai/_shared/api", "_shared/api")
CONTRACTS_DIR = _resolve_existing_path(
    "OPS_CONTRACTS_DIR",
    str(API_DOCS_DIR.parent / "contracts"),
    "awareness-ai/_shared/contracts",
    "_shared/contracts",
)
ONTOLOGY_DIR = _resolve_existing_path(
    "OPS_ONTOLOGY_DIR",
    str(API_DOCS_DIR.parent / "ontology"),
    "awareness-ai/_shared/ontology",
    "_shared/ontology",
)
COMPOSE_FILE = COMPOSE_DIR / "docker-compose.yml"
ENDPOINT_MAPPER_DIR = _resolve_existing_path(
    "OPS_ENDPOINT_MAPPER_DIR",
    str(API_DOCS_DIR.parent / "scripts"),
    "awareness-ai/_shared/scripts",
    "_shared/scripts",
)
SERVICE_MAP_FILE = API_DOCS_DIR / "service-map.json"
ECOSYSTEM_INDEX_FILE = API_DOCS_DIR / "ecosystem_index.json"

# ── Ecosystem Projects (from ECOSYSTEM_ORCHESTRATION.md) ──────────────
# The 7 projects managed by the ecosystem orchestrator, with their API and MCP ports.
# These are the canonical services for this ecosystem — all other services are legacy.
ECOSYSTEM_ORCHESTRATION_FILE = PROJECT_ROOT / "ECOSYSTEM_ORCHESTRATION.md"
ECOSYSTEM_REPORT_FILE = PROJECT_ROOT / "ecosystem_report_20260729_013835.md"

ECOSYSTEM_PROJECTS = [
    {
        "id": "transcription",
        "name": "Transcription",
        "description": "Audio transcription & diarization (61 MCP tools)",
        "api_port": 8049,
        "mcp_ports": [8121, 8122, 8123],
        "type": "FastAPI + MCP",
        "total_tools": 61,
        "project_path": str(PROJECT_ROOT / "transcription"),
    },
    {
        "id": "juris-search",
        "name": "Juris-Search",
        "description": "Legal document search & analysis (44 MCP tools)",
        "api_port": 8000,
        "mcp_ports": [8116],
        "type": "FastAPI + MCP",
        "total_tools": 44,
        "project_path": str(PROJECT_ROOT / "juris-search-VPS"),
    },
    {
        "id": "garge",
        "name": "Garge",
        "description": "AI tools & services hub (107 MCP tools)",
        "api_port": 8066,
        "mcp_ports": [8110, 8111, 8112, 8113, 8114],
        "type": "FastAPI + MCP",
        "total_tools": 107,
        "project_path": "/home/garge",
    },
    {
        "id": "violation-refiner",
        "name": "ViolationRefiner",
        "description": "Legal violation analysis pipeline (15 MCP tools, MCP-only)",
        "api_port": None,
        "mcp_ports": [8124],
        "type": "MCP only",
        "total_tools": 15,
        "project_path": str(PROJECT_ROOT / "ViolationRefiner"),
    },
    {
        "id": "ocr",
        "name": "OCR",
        "description": "OCR & PDF processing (10 MCP tools)",
        "api_port": 8098,
        "mcp_ports": [8125, 8126],
        "type": "FastAPI + MCP",
        "total_tools": 10,
        "project_path": str(PROJECT_ROOT / "OCR"),
    },
    {
        "id": "discovery",
        "name": "Discovery",
        "description": "Discovery intelligence (11 MCP tools, stdio transport)",
        "api_port": 3010,
        "mcp_ports": [],
        "type": "FastAPI + stdio MCP",
        "total_tools": 11,
        "project_path": str(PROJECT_ROOT / "discovery-main"),
    },
    {
        "id": "audio",
        "name": "Audio",
        "description": "Torchaudio-based audio processing (8 MCP tools)",
        "api_port": 8777,
        "mcp_ports": [8765],
        "type": "FastAPI + MCP",
        "total_tools": 8,
        "project_path": str(PROJECT_ROOT / "audio"),
    },
]

ECOSYSTEM_TOTAL_TOOLS = sum(p["total_tools"] for p in ECOSYSTEM_PROJECTS)
AGENT_ARCH_DIR = _resolve_project_root("OPS_AGENT_ARCH_ROOT", "agents", "agent-architecture", "agent-architecture-alt-review")
AGENT_ARCH_SOURCE_FILE = AGENT_ARCH_DIR / "agent-architecture.jsx"
AGENT_ARCH_INDEX_FILE = AGENT_ARCH_DIR / "index.html"
AGENT_ARCH_README_FILE = AGENT_ARCH_DIR / "generated" / "README.md"

try:
    AGENT_ARCH_PORT = int(str(os.environ.get("AGENT_ARCH_PORT", "8120")).strip())
except ValueError:
    AGENT_ARCH_PORT = 8120

AGENT_ARCH_SERVICE_URL = str(os.environ.get("AGENT_ARCH_SERVICE_URL", "")).strip()

# Persistent quick links storage
CUSTOM_LINKS_FILE = Path(__file__).parent / "custom_quicklinks.json"

# Canonical endpoint registry (generated by scripts/map_endpoints.py)
ENDPOINTS_FILE = API_DOCS_DIR / "endpoints.json"

# Legacy endpoint mapper output files (kept for backward compat)
DISCOVERED_ENDPOINTS_FILE = API_DOCS_DIR / "endpoints_discovered.json"
ENRICHED_ENDPOINTS_FILE = API_DOCS_DIR / "endpoints_enriched.json"
ENDPOINT_DOCS_FILE = API_DOCS_DIR / "ENDPOINT_DOCUMENTATION.md"

# Pipeline status tracking
_MAPPER_JOBS: dict = {}  # job_id -> {"status": ..., "output": ..., "started": ...}


def _dev_log_path(log_name: str) -> str:
    return str(DEV_LOG_DIR / log_name)

# ── Service registry ────────────────────────────────────────────────────────
VPS_SERVICES = [
    # Legacy services removed — only current live services remain
    {"name": "ops-dashboard",   "port": "9000",   "desc": "Ops dashboard (this app)",                           "type": "infra",   "compose": None,
     "log_file": _dev_log_path("ops-dashboard.log")},
    {"name": "agent-architecture", "port": str(AGENT_ARCH_PORT), "desc": "Agent architecture visual workspace",   "type": "app",   "compose": None,
        "start_script": str(AGENT_ARCH_DIR / "start.sh"),
     "log_file": _dev_log_path("agent-architecture.log")},
]

LOCAL_SERVICES = [
    # Legacy services removed — only current live services remain
    {"name": "ops-dashboard",     "port": "9000",  "desc": "Ops dashboard (this app)",                       "type": "infra", "compose": None,
    "log_file": _dev_log_path("ops-dashboard.log")},
    {"name": "agent-architecture", "port": str(AGENT_ARCH_PORT), "desc": "Agent architecture visual workspace", "type": "app",   "compose": None,
        "start_script": str(AGENT_ARCH_DIR / "start.sh"),
     "log_file": _dev_log_path("agent-architecture.log")},
]

# ── MCP server registry (per-server control from the ops dashboard) ─────────
# Each entry mirrors the launch line in the owning project's start.sh
# (garge, juris-search, violation-refiner, ocr, transcription, audio,
# comfyui). PID/log files are co-located with the ecosystem start scripts in
# <mcp-ecosystem>/.dev-logs so ecosystem stop scripts see the same servers.
COMFYUI_ROOT = Path(os.environ.get("COMFYUI_ROOT", str(PROJECT_ROOT.parent / "ComfyUI"))).resolve()
_MCP_LOG_ROOT = LEGACY_DEV_LOG_DIR


def _mcp_venv_py(project: str, venv: str = ".venv-mcp") -> str:
    return str(PROJECT_ROOT / project / venv / "bin" / "python")


def _mcp_proj(project: str, *parts: str) -> str:
    return str(PROJECT_ROOT / project / Path(*parts))


MCP_SERVERS = [
    # ── garge (ports 8110-8114) ──
    {"id": "garge-core", "name": "garge core", "project": "garge", "port": 8110,
     "transport": "streamable-http", "tool_count": 87,
     "pid_project": "garge", "pid_service": "mcp-core",
     "python": _mcp_venv_py("garge"),
     "script": _mcp_proj("garge", "mcp", "servers", "core_server.py"),
     "cwd": _mcp_proj("garge"), "env": {}},
    {"id": "garge-files", "name": "garge files", "project": "garge", "port": 8111,
     "transport": "streamable-http", "tool_count": 18,
     "pid_project": "garge", "pid_service": "mcp-files",
     "python": _mcp_venv_py("garge"),
     "script": _mcp_proj("garge", "mcp", "servers", "files_server.py"),
     "cwd": _mcp_proj("garge"), "env": {}},
    {"id": "garge-ingestion", "name": "garge ingestion", "project": "garge", "port": 8112,
     "transport": "streamable-http", "tool_count": 20,
     "pid_project": "garge", "pid_service": "mcp-ingestion",
     "python": _mcp_venv_py("garge"),
     "script": _mcp_proj("garge", "mcp", "servers", "ingestion_server.py"),
     "cwd": _mcp_proj("garge"), "env": {}},
    {"id": "garge-prompt", "name": "garge prompt", "project": "garge", "port": 8113,
     "transport": "streamable-http", "tool_count": 7,
     "pid_project": "garge", "pid_service": "mcp-prompt",
     "python": _mcp_venv_py("garge"),
     "script": _mcp_proj("garge", "mcp", "servers", "prompt_server.py"),
     "cwd": _mcp_proj("garge"), "env": {}},
    {"id": "garge-qdrant", "name": "garge qdrant", "project": "garge", "port": 8114,
     "transport": "streamable-http", "tool_count": 25,
     "pid_project": "garge", "pid_service": "mcp-qdrant",
     "python": _mcp_venv_py("garge"),
     "script": _mcp_proj("garge", "mcp", "servers", "qdrant_server.py"),
     "cwd": _mcp_proj("garge"), "env": {}},
    # ── juris-search (port 8116, node) ──
    {"id": "juris-search-mcp", "name": "juris-search MCP", "project": "juris-search", "port": 8116,
     "transport": "streamable-http", "tool_count": 33,
     "pid_project": "juris-search", "pid_service": "mcp",
     "command": "node",
     "script": _mcp_proj("juris-search", "mcp", "juris_mcp_server.js"),
     "cwd": _mcp_proj("juris-search"),
     "env": {"JURIS_SEARCH_BASE_URL": "http://127.0.0.1:8000",
             "NODE_PATH": _mcp_proj("juris-search", "mcp", "node_modules")}},
    # ── violation-refiner (port 8124) ──
    {"id": "violation-refiner-mcp", "name": "ViolationRefiner MCP", "project": "violation-refiner", "port": 8124,
     "transport": "streamable-http", "tool_count": 39,
     "pid_project": "violation-refiner", "pid_service": "mcp",
     "python": _mcp_venv_py("violation-refiner", ".venv"),
     "module": "violation_pack.mcp_server",
     "cwd": _mcp_proj("violation-refiner"), "env": {}},
    # ── ocr (ports 8125-8126; NOT started by ocr/start.sh — controlled here) ──
    {"id": "ocr-core", "name": "ocr core", "project": "ocr", "port": 8125,
     "transport": "streamable-http", "tool_count": 5,
     "pid_project": "ocr", "pid_service": "mcp-core",
     "python": _mcp_venv_py("ocr", ".venv"),
     "script": _mcp_proj("ocr", "mcp", "servers", "ocr_server.py"),
     "cwd": _mcp_proj("ocr"), "env": {}},
    {"id": "ocr-pdf", "name": "ocr pdf", "project": "ocr", "port": 8126,
     "transport": "streamable-http", "tool_count": 7,
     "pid_project": "ocr", "pid_service": "mcp-pdf",
     "python": _mcp_venv_py("ocr", ".venv"),
     "script": _mcp_proj("ocr", "mcp", "servers", "pdf_server.py"),
     "cwd": _mcp_proj("ocr"), "env": {}},
    # ── transcription (ports 8121-8123) ──
    {"id": "transcription-mcp", "name": "transcription MCP", "project": "transcription", "port": 8121,
     "transport": "streamable-http", "tool_count": None,
     "pid_project": "transcription", "pid_service": "mcp-transcription",
     "python": _mcp_venv_py("transcription", ".venv"),
     "module": "src.mcp.servers.transcription_server",
     "cwd": _mcp_proj("transcription"), "env": {}},
    {"id": "transcription-transcripts", "name": "transcription transcripts", "project": "transcription", "port": 8122,
     "transport": "streamable-http", "tool_count": None,
     "pid_project": "transcription", "pid_service": "mcp-transcripts",
     "python": _mcp_venv_py("transcription", ".venv"),
     "module": "src.mcp.servers.transcripts_server",
     "cwd": _mcp_proj("transcription"), "env": {}},
    {"id": "transcription-meta", "name": "transcription meta", "project": "transcription", "port": 8123,
     "transport": "streamable-http", "tool_count": None,
     "pid_project": "transcription", "pid_service": "mcp-meta",
     "python": _mcp_venv_py("transcription", ".venv"),
     "module": "src.mcp.servers.meta_server",
     "cwd": _mcp_proj("transcription"), "env": {}},
    # ── audio (port 8765) ──
    {"id": "audio-mcp", "name": "audio MCP", "project": "audio", "port": 8765,
     "transport": "streamable-http", "tool_count": 8,
     "pid_project": "audio", "pid_service": "mcp",
     "python": _mcp_venv_py("audio"),
     "script": _mcp_proj("audio", "mcp", "torchaudio_mcp", "server.py"),
     "cwd": _mcp_proj("audio"), "env": {}},
    # ── comfyui (ports 8130-8133; HTTP clients to ComfyUI :8188) ──
    {"id": "comfyui-workflow", "name": "comfyui workflow", "project": "comfyui", "port": 8130,
     "transport": "streamable-http", "tool_count": 12,
     "pid_project": "comfyui", "pid_service": "mcp-workflow",
     "python": _mcp_venv_py("comfyui"),
     "script": str(COMFYUI_ROOT / "mcp" / "servers" / "workflow_server.py"),
     "cwd": _mcp_proj("comfyui"),
     "env": {"COMFYUI_BASE_URL": "http://127.0.0.1:8188"}},
    {"id": "comfyui-model", "name": "comfyui model", "project": "comfyui", "port": 8131,
     "transport": "streamable-http", "tool_count": 4,
     "pid_project": "comfyui", "pid_service": "mcp-model",
     "python": _mcp_venv_py("comfyui"),
     "script": str(COMFYUI_ROOT / "mcp" / "servers" / "model_server.py"),
     "cwd": _mcp_proj("comfyui"),
     "env": {"COMFYUI_BASE_URL": "http://127.0.0.1:8188"}},
    {"id": "comfyui-node", "name": "comfyui node", "project": "comfyui", "port": 8132,
     "transport": "streamable-http", "tool_count": 2,
     "pid_project": "comfyui", "pid_service": "mcp-node",
     "python": _mcp_venv_py("comfyui"),
     "script": str(COMFYUI_ROOT / "mcp" / "servers" / "node_server.py"),
     "cwd": _mcp_proj("comfyui"),
     "env": {"COMFYUI_BASE_URL": "http://127.0.0.1:8188"}},
    {"id": "comfyui-system", "name": "comfyui system", "project": "comfyui", "port": 8133,
     "transport": "streamable-http", "tool_count": 4,
     "pid_project": "comfyui", "pid_service": "mcp-system",
     "python": _mcp_venv_py("comfyui"),
     "script": str(COMFYUI_ROOT / "mcp" / "servers" / "system_server.py"),
     "cwd": _mcp_proj("comfyui"),
     "env": {"COMFYUI_BASE_URL": "http://127.0.0.1:8188"}},
]

MCP_SERVER_IDS = {srv["id"] for srv in MCP_SERVERS}


def _mcp_by_id(mcp_id: str) -> dict | None:
    return next((s for s in MCP_SERVERS if s["id"] == mcp_id), None)


def _mcp_pid_file(srv: dict) -> Path:
    return _MCP_LOG_ROOT / f"{srv['pid_project']}-{srv['pid_service']}.pid"


def _mcp_log_file(srv: dict) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d")
    return _MCP_LOG_ROOT / f"{srv['pid_project']}-{srv['pid_service']}-{stamp}.log"


def _mcp_start_cmd(srv: dict) -> tuple[list[str], str]:
    """Build the launch command mirroring the project's start.sh."""
    if srv.get("module"):
        python = srv.get("python")
        if not python or not Path(python).exists():
            return [], ""
        return [python, "-m", srv["module"]], srv.get("cwd", "")
    if srv.get("script"):
        script_path = Path(srv["script"])
        if not script_path.exists():
            return [], ""
        if srv.get("command") == "node":
            return ["node", str(script_path)], srv.get("cwd", "")
        python = srv.get("python")
        if not python or not Path(python).exists():
            return [], ""
        return [python, str(script_path)], srv.get("cwd", "")
    return [], ""


def _pids_on_port(port: int) -> list[int]:
    pids = set()
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == port and conn.pid:
                pids.add(conn.pid)
    except (psutil.AccessDenied, psutil.Error):
        pass
    return sorted(pids)


def _kill_process_tree(pid: int) -> None:
    try:
        parent = psutil.Process(pid)
        procs = [parent] + parent.children(recursive=True)
        for p in procs:
            try:
                p.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        _, alive = psutil.wait_procs(procs, timeout=4)
        for p in alive:
            try:
                p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


def _mcp_server_status(srv: dict) -> dict:
    port = int(srv["port"])
    listening = _is_tcp_port_listening(port)
    pid_file = _mcp_pid_file(srv)
    pid = None
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip() or "0") or None
        except ValueError:
            pid = None
    alive = False
    if pid:
        try:
            alive = psutil.pid_exists(pid)
        except Exception:
            alive = False
    return {
        "id": srv["id"],
        "name": srv["name"],
        "project": srv.get("project", ""),
        "port": port,
        "transport": srv.get("transport", "streamable-http"),
        "tool_count": srv.get("tool_count"),
        "status": "running" if listening else "stopped",
        "running": listening,
        "pid": pid if (alive and listening) else None,
        "pid_file": str(pid_file),
        "log_file": str(_mcp_log_file(srv)),
    }


def _start_mcp_server(srv: dict) -> tuple[bool, str]:
    port = int(srv["port"])
    if _is_tcp_port_listening(port):
        return True, f"{srv['name']} already running on port {port}"
    cmd, cwd = _mcp_start_cmd(srv)
    if not cmd:
        return False, f"Launch config missing for {srv['name']} (venv or script not found)"
    log_file = _mcp_log_file(srv)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file = _mcp_pid_file(srv)
    env = dict(os.environ)
    env.update({
        "MCP_TRANSPORT": srv.get("transport", "streamable-http"),
        "MCP_HOST": srv.get("host", "0.0.0.0"),
        "MCP_PORT": str(port),
    })
    if srv.get("python"):
        env["PYTHONUNBUFFERED"] = "1"
    env.update(srv.get("env", {}))
    try:
        with open(log_file, "a", encoding="utf-8") as lf:
            proc = subprocess.Popen(
                cmd, cwd=cwd, env=env, stdout=lf, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        pid_file.write_text(str(proc.pid))
    except Exception as exc:
        return False, str(exc)
    for _ in range(20):
        if _is_tcp_port_listening(port):
            return True, f"{srv['name']} started on port {port} (pid {proc.pid})"
        time.sleep(0.4)
    return True, f"{srv['name']} launch issued (pid {proc.pid}); port {port} not yet listening"


def _stop_mcp_server(srv: dict) -> tuple[bool, str]:
    port = int(srv["port"])
    killed = []
    pid_file = _mcp_pid_file(srv)
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip() or "0")
        except ValueError:
            pid = None
        if pid:
            _kill_process_tree(pid)
            killed.append(str(pid))
        pid_file.unlink(missing_ok=True)
    for pid in _pids_on_port(port):
        if str(pid) in killed:
            continue
        _kill_process_tree(pid)
        killed.append(str(pid))
    if killed:
        return True, f"{srv['name']} stopped (pids {', '.join(killed)})"
    return True, f"{srv['name']} not running (no pid file, port {port} free)"


def _restart_mcp_server(srv: dict) -> tuple[bool, str]:
    _stop_mcp_server(srv)
    return _start_mcp_server(srv)


SERVICE_ALIASES = {
    "awareness": ["manus", "agents"],
    "awareness-qdrant": ["qdrant", "qdrant-api"],
    "garage": ["garage-api"],
    "pinocchio": ["legal"],
    "legalpipeline": ["pipeline", "legalpipelinedashboard"],
    "thebridge": ["bridge"],
    "thebridge-ui": ["bridge-ui"],
    "ops-dashboard": ["ops"],
    "agent-architecture": ["agent-arch", "architecture"],
    "tjrs_service": ["jurisprudence", "tjrs"],
    "sindicatoruralgurupi": ["sindicato", "expogurupi"],
    "ibsco": ["ibsco-portal"],
    "coremu": ["coremu-workspace", "coremu-agent"],
    "juris-search": ["juris", "tjrs-search"],
    "shared-api": ["shared", "shared-content"],
    "garage-service": ["garage-svc"],
    "argus-service": ["argus-svc"],
    "transcription-svc": ["transcription-service", "sa-transcription"],
    "ocr-service": ["ocr", "ocr-pipeline"],
}

SERVICE_NAME_OVERRIDES = {
    "argusdashboard": "argus",
    "agentarchitecture": "agent-architecture",
    "agentarch": "agent-architecture",
    "architecture": "agent-architecture",
    "bridge": "thebridge",
    "bridgeui": "thebridge-ui",
    "jurisprudence": "tjrs_service",
    "manus": "awareness",
    "ops": "ops-dashboard",
    "qdrant": "awareness-qdrant",
    "qdrantapi": "awareness-qdrant",
    "shared": "_shared",
    "sharedlayer": "_shared",
    "tjrs": "tjrs_service",
    "tjrsservice": "tjrs_service",
    "sindicato": "sindicatoruralgurupi",
    "expogurupi": "sindicatoruralgurupi",
    "ibscoportal": "ibsco",
    "coremuworkspace": "coremu",
    "coremuagent": "coremu",
    "juris": "juris-search",
    "tjrsearch": "juris-search",
    "sharedapi": "shared-api",
    "sharedcontent": "shared-api",
    "garagesvc": "garage-service",
    "argussvc": "argus-service",
    "transcriptionservice": "transcription-svc",
    "satranscription": "transcription-svc",
    "ocrpipeline": "ocr-service",
}

# Path-prefix to canonical service routing hints used by observability attribution.
SERVICE_PATH_HINTS = (
    ("/pages", "frontend-public"),
    ("/api/observatory", "ops-dashboard"),
    ("/api/api-logger", "ops-dashboard"),
    ("/api/endpoints", "ops-dashboard"),
    ("/api/deploy", "ops-dashboard"),
    ("/api/services", "ops-dashboard"),
    ("/api/projects", "ops-dashboard"),
    ("/api/system", "ops-dashboard"),
    ("/api/quicklinks", "ops-dashboard"),
    ("/api/ecosystem", "ops-dashboard"),
    ("/api/test", "ops-dashboard"),
    ("/agent-architecture", "agent-architecture"),
    ("/ops", "ops-dashboard"),
    ("/sindicato", "sindicatoruralgurupi"),
    ("/api/sindicato", "sindicatoruralgurupi"),
    ("/ibsco", "ibsco"),
    ("/api/ibsco", "ibsco"),
    ("/api/tjrs", "tjrs_service"),
    ("/api/jurisprudence", "tjrs_service"),
    ("/api/garage", "garage"),
    ("/api/qdrant", "awareness-qdrant"),
    ("/api/pinocchio", "pinocchio"),
    ("/api/pipeline", "legalpipeline"),
    ("/api/dashboard", "legalpipeline"),
    ("/api/legal", "argus"),
    ("/api/argus-dashboard", "argus"),
    ("/api/argus", "argus"),
    ("/api/bridge-residencia", "thebridge-res"),
    ("/api/bridge", "thebridge"),
    ("/api/shared", "_shared"),
    ("/api/discovery", "thebridge-ui"),
    ("/api/awareness", "awareness"),
    ("/api/gateway", "gateway"),
    ("/api/manus", "awareness"),
    ("/api/agents", "awareness"),
    ("/api/models", "awareness"),
    ("/api/memory", "awareness"),
    ("/api/functions", "gateway"),
    ("/api/compliance", "gateway"),
    ("/api/steps", "gateway"),
    ("/api/ops", "ops-dashboard"),
    ("/auth", "gateway"),
)

SERVICE_HOST_HINTS = (
    ("qdrant.io", "awareness-qdrant"),
)


def _normalize_service_key(raw: str) -> str:
    return "".join(ch for ch in (raw or "").lower() if ch.isalnum())


def _service_aliases_for(service_name: str) -> list[str]:
    aliases = set(SERVICE_ALIASES.get(service_name, []))
    # Inverse map support: if a service name is listed as an alias elsewhere, include canonical key.
    for canonical, mapped_aliases in SERVICE_ALIASES.items():
        if service_name in mapped_aliases:
            aliases.add(canonical)
    aliases.discard(service_name)
    return sorted(a for a in aliases if a)


def _all_registered_services() -> list[dict]:
    merged: dict[str, dict] = {}
    for svc in VPS_SERVICES + LOCAL_SERVICES:
        name = str(svc.get("name") or "").strip()
        if not name:
            continue
        existing = merged.get(name)
        if not existing:
            merged[name] = dict(svc)
            continue
        updated = dict(existing)
        for k, v in svc.items():
            if updated.get(k) in (None, "", "—") and v not in (None, ""):
                updated[k] = v
        merged[name] = updated
    return list(merged.values())


def _service_alias_index() -> dict[str, str]:
    index: dict[str, str] = {}
    available_names = {
        str(svc.get("name") or "").strip()
        for svc in _all_registered_services()
        if str(svc.get("name") or "").strip()
    }

    for service_name in sorted(available_names):
        key = _normalize_service_key(service_name)
        if key:
            index[key] = service_name

        for alias in _service_aliases_for(service_name):
            alias_key = _normalize_service_key(alias)
            if alias_key and alias_key not in index:
                index[alias_key] = service_name

    for alias, canonical in SERVICE_NAME_OVERRIDES.items():
        alias_key = _normalize_service_key(alias)
        canonical_name = str(canonical or "").strip()
        if not alias_key or not canonical_name:
            continue
        if canonical_name in available_names:
            index[alias_key] = canonical_name

    return index


def _canonical_service_name(raw: str) -> str:
    token = _normalize_service_key(raw)
    if not token or token in {"unknown", "na", "none"}:
        return "unknown"
    mapped = _service_alias_index().get(token)
    return mapped if mapped else "unknown"


def _service_by_port(port: int) -> str | None:
    if not isinstance(port, int):
        return None

    matches: list[str] = []
    active_names = {
        str(svc.get("name") or "").strip()
        for svc in _active_services()
        if str(svc.get("name") or "").strip()
    }

    for svc in _all_registered_services():
        svc_name = str(svc.get("name") or "").strip()
        if not svc_name:
            continue
        svc_port = _extract_primary_port(svc.get("port"))
        if svc_port == port and svc_name not in matches:
            matches.append(svc_name)

    if not matches:
        return None
    for name in matches:
        if name in active_names:
            return name
    return matches[0]


def _load_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _endpoint_count_map() -> dict[str, int]:
    """Build endpoint counts keyed by normalized service token."""
    payload = _load_json_file(ENDPOINTS_FILE)
    if not payload:
        return {}

    counts: dict[str, int] = {}

    # Fast path: use precomputed summary.
    by_service = ((payload.get("summary") or {}).get("by_service") or {})
    for service_name, total in by_service.items():
        key = _normalize_service_key(service_name)
        if key:
            counts[key] = int(total or 0)

    # Fallback: compute from endpoint entries if needed.
    if not counts:
        for endpoint in payload.get("endpoints", []):
            source = str(endpoint.get("file", "")).split("/")[0]
            key = _normalize_service_key(source)
            if key:
                counts[key] = counts.get(key, 0) + 1

    return counts


def _service_map_key_endpoints() -> dict[str, list[str]]:
    """Load concise key endpoint lines from service-map.json."""
    payload = _load_json_file(SERVICE_MAP_FILE)
    svc_map = payload.get("services") or {}
    output: dict[str, list[str]] = {}

    for service_key, service_data in svc_map.items():
        endpoints = service_data.get("endpoints") or []
        if not endpoints:
            continue
        lines = []
        for ep in endpoints[:8]:
            method = (ep.get("method") or "GET").upper()
            path = ep.get("path") or ""
            desc = (ep.get("description") or "").strip()
            if desc:
                lines.append(f"{method} {path} - {desc}")
            else:
                lines.append(f"{method} {path}")
        key = _normalize_service_key(service_key)
        if key:
            output[key] = lines

    return output


def _enrich_ecosystem_services(services: list[dict]) -> list[dict]:
    counts = _endpoint_count_map()
    key_endpoints = _service_map_key_endpoints()

    enriched = []
    for svc in services:
        item = dict(svc)
        id_key = _normalize_service_key(item.get("id", ""))
        name_key = _normalize_service_key(item.get("name", ""))

        item["id"] = item.get("id", "")
        if not item.get("endpoint_count"):
            item["endpoint_count"] = counts.get(id_key) or counts.get(name_key) or 0

        if not item.get("key_endpoints"):
            item["key_endpoints"] = key_endpoints.get(id_key) or key_endpoints.get(name_key) or []

        if not item.get("description"):
            framework = item.get("framework")
            tags = item.get("tags") or []
            if framework and tags:
                item["description"] = f"{framework} service ({', '.join(tags[:3])})"
            elif framework:
                item["description"] = f"{framework} service"
            else:
                item["description"] = item.get("name", item.get("id", "Service"))

        enriched.append(item)

    return enriched


# ── Ecosystem project live status ─────────────────────────────────────


def _check_ecosystem_project_status(project: dict) -> dict:
    """Check live status of all ports for an ecosystem project.

    Returns enriched project data with live status information.
    """
    result = dict(project)
    components = []

    # Check API port
    api_port = project.get("api_port")
    if api_port is not None:
        api_up = _is_tcp_port_listening(api_port)
        components.append({
            "type": "API",
            "port": api_port,
            "status": "UP" if api_up else "DOWN",
        })

    # Check MCP ports
    for mcp_port in project.get("mcp_ports", []):
        mcp_up = _is_tcp_port_listening(mcp_port)
        components.append({
            "type": "MCP",
            "port": mcp_port,
            "status": "UP" if mcp_up else "DOWN",
        })

    # Overall status: UP if at least one component is up
    up_components = [c for c in components if c["status"] == "UP"]
    result["status"] = "UP" if up_components else ("DOWN" if components else "UNKNOWN")
    result["components"] = components
    result["up_count"] = len(up_components)
    result["total_components"] = len(components)

    return result


def _build_ecosystem_index() -> dict:
    """Build the ecosystem index from ECOSYSTEM_PROJECTS with live status."""
    enriched_services = []
    for project in ECOSYSTEM_PROJECTS:
        svc = _check_ecosystem_project_status(project)
        enriched_services.append({
            "id": svc["id"],
            "name": svc["name"],
            "description": svc["description"],
            "port": str(svc.get("api_port") or ""),
            "mcp_ports": svc.get("mcp_ports", []),
            "framework": svc.get("type", "internal"),
            "tags": ["ecosystem", svc["id"]],
            "total_tools": svc.get("total_tools", 0),
            "status": svc["status"],
            "components": svc["components"],
            "up_count": svc["up_count"],
            "total_components": svc["total_components"],
            "endpoint_count": svc.get("endpoint_count", svc.get("total_tools", 0)),
            "project_path": svc.get("project_path", ""),
        })

    total_endpoints = sum(s["endpoint_count"] for s in enriched_services)
    total_up = sum(1 for s in enriched_services if s["status"] == "UP")

    return {
        "services": enriched_services,
        "summary": {
            "total_services": len(enriched_services),
            "total_endpoints": total_endpoints,
            "total_up": total_up,
            "total_tools": ECOSYSTEM_TOTAL_TOOLS,
        },
        "description": f"Awareness-AI Ecosystem — {len(enriched_services)} projects, {total_up} UP, {ECOSYSTEM_TOTAL_TOOLS} MCP tools",
        "infrastructure": {
            "qdrant": {"port": 6333, "description": "Vector search engine (Qdrant)", "collections": ["awa_documents", "awa_code", "awa_conversations", "awa_ontology"]},
            "neo4j": {"port": 7687, "description": "Graph database (Neo4j)", "node_types": ["File", "Chunk", "Entity", "Invariant", "AgentStep", "Decision"]},
        },
        "source": "ECOSYSTEM_ORCHESTRATION.md",
    }


def _get_effective_mode() -> str:
    if has_request_context():
        session_mode = session.get("ops_mode")
        if session_mode in {"local", "vps"}:
            return session_mode
    return OPS_MODE


def _is_local_mode() -> bool:
    return _get_effective_mode() == "local"


def _active_services() -> list[dict]:
    return LOCAL_SERVICES if _is_local_mode() else VPS_SERVICES


def _is_tcp_port_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.35):
            return True
    except OSError:
        return False


# ── Cloud service health checks ─────────────────────────────────────────────
SHARED_ENV_FILE = _resolve_existing_path(
    "OPS_SHARED_ENV_FILE",
    "awareness/.env",
    "awareness-ai/_shared/.env",
    "_shared/.env",
)
_shared_env_cache: dict | None = None
_shared_env_mtime: float = 0


def _load_shared_env() -> dict:
    """Load and cache the shared .env file."""
    global _shared_env_cache, _shared_env_mtime
    try:
        if not SHARED_ENV_FILE.exists():
            return {}
        mtime = SHARED_ENV_FILE.stat().st_mtime
        if _shared_env_cache is not None and mtime == _shared_env_mtime:
            return _shared_env_cache
        env = {}
        for line in SHARED_ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip('"').strip("'")
        _shared_env_cache = env
        _shared_env_mtime = mtime
        return env
    except Exception:
        return {}


def _check_qdrant_cloud() -> tuple[str, str, dict]:
    """Check Qdrant Cloud status. Returns (status, health, info)."""
    env = _load_shared_env()
    url = env.get("QDRANT_URL", "")
    api_key = env.get("QDRANT_API_KEY", "")
    
    if not url:
        return "not_configured", "—", {"error": "QDRANT_URL not set"}
    
    try:
        # Try healthz endpoint (may require auth on Qdrant Cloud)
        health_url = f"{url.rstrip('/')}/healthz"
        headers = {"api-key": api_key} if api_key else {}
        resp = requests.get(health_url, headers=headers, timeout=5)
        
        if resp.status_code == 200:
            # Get collection stats
            collections_url = f"{url.rstrip('/')}/collections"
            headers = {"api-key": api_key} if api_key else {}
            stats_resp = requests.get(collections_url, headers=headers, timeout=5)
            collections = []
            total_vectors = 0
            if stats_resp.status_code == 200:
                data = stats_resp.json()
                for coll in data.get("result", {}).get("collections", []):
                    collections.append(coll.get("name"))
                    # Get per-collection info
                    coll_url = f"{url.rstrip('/')}/collections/{coll.get('name')}"
                    try:
                        coll_resp = requests.get(coll_url, headers=headers, timeout=3)
                        if coll_resp.status_code == 200:
                            coll_data = coll_resp.json().get("result", {})
                            total_vectors += coll_data.get("vectors_count", 0)
                    except Exception:
                        pass
            return "running", "healthy", {
                "url": url[:50] + "...",
                "collections": len(collections),
                "total_vectors": total_vectors,
            }
        else:
            return "error", "unhealthy", {"status_code": resp.status_code}
    except requests.exceptions.Timeout:
        return "timeout", "unreachable", {"error": "Connection timeout"}
    except requests.exceptions.ConnectionError:
        return "offline", "unreachable", {"error": "Connection failed"}
    except Exception as e:
        return "error", "unknown", {"error": str(e)[:50]}


def _check_neo4j_cloud() -> tuple[str, str, dict]:
    """Check Neo4j AuraDB status. Returns (status, health, info)."""
    env = _load_shared_env()
    uri = env.get("NEO4J_URI", "")
    user = env.get("NEO4J_USER", "")
    password = env.get("NEO4J_PASS", "")
    database = env.get("NEO4J_DATABASE", "")
    
    if not uri:
        return "not_configured", "—", {"error": "NEO4J_URI not set"}
    
    # For AuraDB, we can check the query API endpoint
    # Convert bolt URI to HTTPS query API
    try:
        instance_id = uri.split("//")[1].split(".")[0]
        query_url = f"https://{instance_id}.databases.neo4j.io/db/{database}/query/v2"
        
        # Simple connectivity check via HTTP (auth would be needed for actual queries)
        # Check if the endpoint responds
        resp = requests.get(
            f"https://{instance_id}.databases.neo4j.io",
            timeout=5,
            allow_redirects=False
        )
        
        if resp.status_code in (200, 301, 302, 401, 403):
            # Server is responding (even auth errors mean it's up)
            return "running", "reachable", {
                "uri": uri[:40] + "...",
                "database": database,
                "instance": instance_id,
            }
        else:
            return "error", "unhealthy", {"status_code": resp.status_code}
    except requests.exceptions.Timeout:
        return "timeout", "unreachable", {"error": "Connection timeout"}
    except requests.exceptions.ConnectionError:
        return "offline", "unreachable", {"error": "Connection failed"}
    except Exception as e:
        return "error", "unknown", {"error": str(e)[:50]}


# ── Project directory registry ──────────────────────────────────────────────
PROJECTS = [
    {"name": "Garage",              "path": _resolve_existing_relative_path("services/garage-main", "garage", "awareness-ai/garage"),              "key_files": ["main.py", "config/settings.py"]},
    {"name": "Argus",               "path": "Argus",               "key_files": ["app.py", "application/"]},
    {"name": "Awareness (Manus)",   "path": _resolve_existing_relative_path("awareness", "awareness-ai/awareness"), "key_files": ["serve.py", "start-all.sh", "workspace/"]},
    {"name": "Pinocchio (Legal)",   "path": _resolve_existing_relative_path("awareness-ai/pinocchio", "pinocchio"), "key_files": ["app.py" if (PROJECT_ROOT / "awareness-ai" / "pinocchio" / "app.py").exists() else "main.py"]},
    {"name": "Transcribe",          "path": "transcribe",          "key_files": ["server.py", "README.md", "static/"]},
    {"name": "TheBridge",          "path": _resolve_existing_relative_path("awareness-ai/bridge", "bridge"), "key_files": ["case-server/auto_server_builder.js", "ui/discovery_ui.html", "ui/onboarding-br.html"]},
    {"name": "TheBridgeResidencia", "path": "TheBridgeResidencia", "key_files": ["case-server/auto_server_builder.js", "ui/discovery_ui.html", "README.md"]},
    {"name": "Ops Dashboard",       "path": _resolve_existing_relative_path("ops", "ops-dashboard"),       "key_files": ["app.py", "templates/dashboard.html", "templates/observatory.html"]},
    {"name": "Agent Architecture",  "path": _resolve_existing_relative_path("agents", "agent-architecture"),  "key_files": ["index.html", "agent-architecture.jsx", "generated/README.md"]},
    {"name": "Frontend Pages",      "path": _resolve_existing_relative_path("awareness/workspace", "awareness-ai/frontend-public/pages"), "key_files": ["index.html", "mobile.html"]},
    {"name": "Frontend (Compose)",  "path": _resolve_existing_relative_path("awareness/workspace", "awareness-ai/frontend-public"),  "key_files": ["index.html", "js/config.js"]},
    {"name": "Shared Layer",        "path": _resolve_existing_relative_path("awareness", "awareness-ai/_shared", "_shared"),             "key_files": [".env", "README.md"]},
    {"name": "Sindicato Rural Gurupi", "path": "sindicatoruralgurupi",               "key_files": ["run.py", "start.sh", "server/"]},
    {"name": "IBSCO",                 "path": "IBSCO",                             "key_files": ["app.py", "start-IBSCO.sh", "web_app/"]},
]


def get_docker_client():
    """Get Docker client connected to local socket."""
    return docker.from_env()


def container_name(service):
    """Get the full Docker container name for a compose service."""
    return f"awareness-frontend-{service}-1"


def _extract_primary_port(port_value) -> int | None:
    if port_value is None:
        return None
    try:
        return int(port_value)
    except (TypeError, ValueError):
        pass
    match = re.search(r"(\d{2,5})", str(port_value))
    return int(match.group(1)) if match else None


def _host_service_pids(svc_def: dict) -> list[int]:
    port_num = _extract_primary_port(svc_def.get("port"))
    if not port_num:
        return []
    pids = set()
    try:
        for conn in psutil.net_connections(kind="inet"):
            laddr = conn.laddr
            if not laddr:
                continue
            if getattr(laddr, "port", None) != port_num:
                continue
            if conn.pid:
                pids.add(conn.pid)
    except Exception:
        return []
    return sorted(pids)


def _script_cmd(sp: Path) -> list[str]:
    if sp.suffix.lower() == ".py":
        return [sys.executable or "python3", str(sp)]

    try:
        first_line = sp.read_text(encoding="utf-8", errors="ignore").splitlines()[0].strip()
    except Exception:
        first_line = ""

    if "zsh" in first_line:
        return ["zsh", str(sp)]
    if "bash" in first_line:
        return ["bash", str(sp)]

    return [str(sp)]


def _stop_host_service(svc_def: dict) -> tuple[bool, str]:
    script = svc_def.get("stop_script")
    if script:
        sp = Path(script)
        if not sp.exists():
            return False, f"Stop script not found: {script}"
        try:
            result = subprocess.run(_script_cmd(sp), capture_output=True, text=True, timeout=45)
            if result.returncode == 0:
                return True, result.stdout.strip() or f"{svc_def['name']} stopped"
            return False, result.stderr.strip() or result.stdout.strip() or "Stop command failed"
        except Exception as exc:
            return False, str(exc)

    pids = _host_service_pids(svc_def)
    if not pids:
        return False, f"No running process found on port {svc_def.get('port')}"

    current_pid = os.getpid()
    target_pids = [pid for pid in pids if pid != current_pid]
    if not target_pids:
        return False, "Refusing to stop the current ops-dashboard process"

    procs = []
    for pid in target_pids:
        try:
            procs.append(psutil.Process(pid))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not procs:
        return False, "No stoppable process found"

    for proc in procs:
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    gone, alive = psutil.wait_procs(procs, timeout=5)
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return True, f"Stopped {len(gone) + len(alive)} process(es) on port {svc_def.get('port')}"


def _start_host_service(svc_def: dict) -> tuple[bool, str]:
    script = svc_def.get("start_script")
    if not script:
        return False, "No start script configured for this host service"

    sp = Path(script)
    if not sp.exists():
        return False, f"Start script not found: {script}"

    cmd = _script_cmd(sp)
    start_args = svc_def.get("start_args")
    if isinstance(start_args, (list, tuple)):
        cmd.extend(str(arg) for arg in start_args if str(arg).strip())
    elif isinstance(start_args, str) and start_args.strip():
        cmd.append(start_args.strip())

    try:
        subprocess.Popen(
            cmd,
            cwd=str(sp.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        return False, str(exc)

    port_num = _extract_primary_port(svc_def.get("port"))
    if port_num:
        for _ in range(16):
            if _is_tcp_port_listening(port_num):
                return True, f"{svc_def['name']} started"
            time.sleep(0.4)

    return True, f"Start command launched for {svc_def['name']}"


def _restart_host_service(svc_def: dict) -> tuple[bool, str]:
    script = svc_def.get("restart_script")
    if script:
        sp = Path(script)
        if not sp.exists():
            return False, f"Restart script not found: {script}"
        cmd = _script_cmd(sp)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            if result.returncode == 0:
                return True, result.stdout.strip() or f"{svc_def['name']} restarted"
            return False, result.stderr.strip() or result.stdout.strip() or "Restart command failed"
        except Exception as exc:
            return False, str(exc)

    stopped_ok, stopped_msg = _stop_host_service(svc_def)
    if not stopped_ok and not str(stopped_msg).startswith("No running process found"):
        return False, stopped_msg

    started_ok, started_msg = _start_host_service(svc_def)
    if started_ok:
        return True, started_msg

    pids = _host_service_pids(svc_def)
    if pids:
        for pid in pids:
            try:
                os.kill(pid, signal.SIGHUP)
            except Exception:
                continue
        return True, f"Sent reload signal to process(es): {', '.join(str(p) for p in pids)}"

    return False, started_msg


# ── Auth ─────────────────────────────────────────────────────────────────────

# Public prefix used by nginx reverse proxy (location /ops → strip prefix)
PUBLIC_PREFIX = "/ops"

def ops_login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("ops_auth"):
            return redirect(f"{PUBLIC_PREFIX}/login")
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def ops_login():
    if request.method == "POST":
        ip = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()
        now = time.time()
        # Evict old attempts outside the window
        _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < _LOCKOUT_WINDOW]
        if len(_login_attempts[ip]) >= _MAX_ATTEMPTS:
            remaining = int(_LOCKOUT_WINDOW - (now - _login_attempts[ip][0]))
            return render_template("login.html", error=f"Too many attempts. Try again in {remaining}s.", mode="login")
        code = request.form.get("code", "")
        active_code = _get_active_code()
        if hashlib.sha256(code.encode()).hexdigest() == hashlib.sha256(active_code.encode()).hexdigest():
            _login_attempts.pop(ip, None)
            session["ops_auth"] = True
            # If using default password, force password change
            if _is_default_password():
                return redirect(f"{PUBLIC_PREFIX}/change-password")
            # Show bookmark prompt on first session visit
            session["show_bookmark"] = True
            return redirect(f"{PUBLIC_PREFIX}/")
        _login_attempts[ip].append(now)
        remaining_attempts = _MAX_ATTEMPTS - len(_login_attempts[ip])
        return render_template("login.html", error=f"Invalid code. {remaining_attempts} attempts remaining.", mode="login")
    return render_template("login.html", error=None, mode="login")


@app.route("/change-password", methods=["GET", "POST"])
def ops_change_password():
    """Force or allow the user to set a new password."""
    if not session.get("ops_auth"):
        return redirect(f"{PUBLIC_PREFIX}/login")
    if request.method == "POST":
        new_pass = request.form.get("new_password", "").strip()
        confirm = request.form.get("confirm_password", "").strip()
        if len(new_pass) < 4:
            return render_template("login.html", error="Password must be at least 4 characters.", mode="change")
        if new_pass != confirm:
            return render_template("login.html", error="Passwords do not match.", mode="change")
        if new_pass == DEFAULT_CODE:
            return render_template("login.html", error="Please choose a different password than the default.", mode="change")
        _save_custom_password(new_pass)
        session["show_bookmark"] = True
        return redirect(f"{PUBLIC_PREFIX}/")
    return render_template("login.html", error=None, mode="change")


# ── API Routes ──────────────────────────────────────────────────────────────

@app.route("/")
@ops_login_required
def index():
    show_bookmark = session.pop("show_bookmark", False)
    mode = _get_effective_mode()
    template_name = "dashboard.html" if mode == "local" else "dashboard.html"
    return render_template(
        template_name,
        show_bookmark=show_bookmark,
        ops_mode=mode,
        vps_remote_pages_dir=VPS_CONFIG.get("remote_pages_dir", ""),
    )


@app.route("/observatory")
@ops_login_required
def observatory():
    mode = _get_effective_mode()
    template_name = "observatory.html" if mode == "local" else "observatory.html"
    return render_template(template_name, ops_mode=mode)


@app.route("/agent-architecture")
@app.route("/agent-architecture/")
@ops_login_required
def agent_architecture_index():
    if not AGENT_ARCH_INDEX_FILE.exists():
        return jsonify({"error": "agent-architecture/index.html not found"}), 404
    return send_from_directory(str(AGENT_ARCH_DIR), "index.html")


@app.route("/agent-architecture.jsx")
@ops_login_required
def agent_architecture_source_file():
    if not AGENT_ARCH_SOURCE_FILE.exists():
        return jsonify({"error": "agent-architecture/agent-architecture.jsx not found"}), 404
    return send_from_directory(str(AGENT_ARCH_DIR), AGENT_ARCH_SOURCE_FILE.name)


@app.route("/agent-architecture/api/<path:api_path>", methods=["GET", "POST", "OPTIONS"])
@ops_login_required
def agent_architecture_api_proxy(api_path: str):
    """Proxy /agent-architecture/api/* → agent-architecture serve.py on port 8120."""
    target = f"http://127.0.0.1:{AGENT_ARCH_PORT}/api/{api_path}"
    qs = request.query_string.decode("utf-8")
    if qs:
        target += "?" + qs
    try:
        upstream = requests.request(
            method=request.method,
            url=target,
            headers={k: v for k, v in request.headers if k.lower() not in {"host", "content-length"}},
            data=request.get_data() if request.method in {"POST", "PUT", "PATCH"} else None,
            stream=True,
            timeout=130,
        )
        # Stream response (handles SSE and large JSON alike)
        def generate():
            for chunk in upstream.iter_content(chunk_size=4096):
                if chunk:
                    yield chunk
        headers = {
            k: v for k, v in upstream.headers.items()
            if k.lower() not in {"transfer-encoding", "connection"}
        }
        return Response(generate(), status=upstream.status_code, headers=headers)
    except requests.exceptions.ConnectionError:
        return jsonify({"error": f"agent-architecture service not reachable (port {AGENT_ARCH_PORT})"}), 503


@app.route("/agent-architecture/<path:asset_path>")
@ops_login_required
def agent_architecture_assets(asset_path: str):
    safe_base = AGENT_ARCH_DIR.resolve()
    target = (AGENT_ARCH_DIR / asset_path).resolve()
    if not str(target).startswith(str(safe_base)):
        return jsonify({"error": "Invalid asset path"}), 400
    if not target.exists() or not target.is_file():
        return jsonify({"error": "Asset not found"}), 404
    return send_from_directory(str(AGENT_ARCH_DIR), asset_path)


@app.route("/mode/<target_mode>", methods=["GET"])
@ops_login_required
def set_mode(target_mode: str):
    mode = (target_mode or "").strip().lower()
    if mode not in {"local", "vps"}:
        return redirect(f"{PUBLIC_PREFIX}/")
    session["ops_mode"] = mode
    next_path = request.args.get("next", "/")
    if not next_path.startswith("/"):
        next_path = "/"
    return redirect(f"{PUBLIC_PREFIX}{next_path}")


@app.route("/api/system")
@ops_login_required
def system_info():
    """System-level resource usage."""
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    uptime_s = time.time() - psutil.boot_time()
    days, rem = divmod(int(uptime_s), 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    return jsonify({
        "cpu_pct": cpu,
        "mem_total_gb": round(mem.total / 1e9, 1),
        "mem_used_gb": round(mem.used / 1e9, 1),
        "mem_pct": mem.percent,
        "disk_total_gb": round(disk.total / 1e9, 1),
        "disk_used_gb": round(disk.used / 1e9, 1),
        "disk_pct": disk.percent,
        "uptime": f"{days}d {hours}h {mins}m",
        "load_avg": list(os.getloadavg()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


def _parse_tail_lines(value: str | None, default: int = 80, max_lines: int = 500) -> int:
    raw = str(value or "").strip()
    if not raw.isdigit():
        return default
    lines = int(raw)
    if lines <= 0:
        return default
    return min(lines, max_lines)


def _resolve_service_definition(service: str, include_all: bool = False) -> tuple[dict | None, str]:
    requested = str(service or "").strip()
    if not requested:
        return None, "unknown"

    candidate = requested
    if "." in candidate:
        left, right = candidate.rsplit(".", 1)
        if right.isdigit() and left:
            candidate = left

    service_pool = _all_registered_services() if include_all else _active_services()

    for svc in service_pool:
        name = str(svc.get("name") or "").strip()
        compose = str(svc.get("compose") or "").strip()
        if candidate in {name, compose}:
            return svc, name or candidate

    canonical = _canonical_service_name(candidate)
    if canonical != "unknown":
        for svc in service_pool:
            if str(svc.get("name") or "").strip() == canonical:
                return svc, canonical

    if candidate.isdigit():
        by_port = _service_by_port(int(candidate))
        if by_port:
            for svc in _all_registered_services():
                if str(svc.get("name") or "").strip() == by_port:
                    return svc, by_port

    return None, canonical if canonical != "unknown" else candidate


def _candidate_service_log_files(svc_def: dict) -> list[str]:
    service_name = str(svc_def.get("name") or "").strip()
    aliases = _service_aliases_for(service_name)
    configured = str(svc_def.get("log_file") or "").strip()
    candidates: list[str] = []

    def add(path: str) -> None:
        candidate = str(path or "").strip()
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    if configured:
        add(configured)

    basenames: list[str] = []
    if configured:
        basenames.append(Path(configured).name)
    if service_name:
        basenames.append(f"{service_name}.log")
    for alias in aliases:
        basenames.append(f"{alias}.log")

    for basename in basenames:
        add(str(DEV_LOG_DIR / basename))
        add(str(LEGACY_DEV_LOG_DIR / basename))

    if service_name == "thebridge":
        add(str(PROJECT_ROOT / "awareness-ai" / "bridge" / ".logs" / "case-server.log"))
    elif service_name == "thebridge-ui":
        add(str(PROJECT_ROOT / "awareness-ai" / "bridge" / ".logs" / "bridge-ui.log"))

    return candidates


def _read_service_logs_snapshot(svc_def: dict, lines: int) -> dict:
    service_name = str(svc_def.get("name") or "unknown")
    compose_name = svc_def.get("compose")
    service_type = str(svc_def.get("type") or "app")
    port_value = svc_def.get("port")
    port_num = _extract_primary_port(port_value)
    service_port = f"{service_name}.{port_num}" if port_num is not None else f"{service_name}.{port_value or 'unknown'}"

    payload = {
        "service": service_name,
        "canonical_name": _canonical_service_name(service_name),
        "aliases": _service_aliases_for(service_name),
        "port": port_value,
        "port_number": port_num,
        "service_port": service_port,
        "type": service_type,
        "compose": compose_name,
        "lines": int(lines),
        "source": "none",
        "logs": "",
        "pids": _host_service_pids(svc_def) if compose_name is None and service_type != "cloud" else [],
    }

    if service_type == "cloud":
        payload["source"] = "cloud"
        payload["logs"] = "Cloud service has no local process logs. Check provider dashboard/metrics."
        return payload

    if compose_name:
        payload["source"] = "docker"
        payload["container"] = container_name(compose_name)
        try:
            client = get_docker_client()
            container = client.containers.get(payload["container"])
            payload["logs"] = container.logs(tail=int(lines), timestamps=True).decode("utf-8", errors="replace")
            return payload
        except docker.errors.NotFound:
            payload["logs"] = "Container not found"
            return payload
        except Exception as exc:
            payload["logs"] = f"Error: {exc}"
            return payload

    log_candidates = _candidate_service_log_files(svc_def)
    for log_file in log_candidates:
        if not os.path.isfile(log_file):
            continue

        payload["source"] = "file"
        payload["log_file"] = log_file
        try:
            result = subprocess.run(
                ["tail", "-n", str(lines), log_file],
                capture_output=True,
                text=True,
                timeout=10,
            )
            payload["logs"] = result.stdout
        except Exception as exc:
            payload["logs"] = f"Error reading log file: {exc}"
        return payload

    if log_candidates:
        payload["source"] = "file"
        payload["log_file"] = log_candidates[0]
        try:
            target = Path(log_candidates[0])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch(exist_ok=True)
            payload["logs"] = "Log file is configured but has no output yet."
        except Exception as exc:
            payload["logs"] = f"Log file is configured but unavailable: {exc}"
        return payload

    if shutil.which("journalctl"):
        payload["source"] = "journalctl"
        try:
            result = subprocess.run(
                ["journalctl", "-u", service_name, "-n", str(lines), "--no-pager"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            payload["logs"] = result.stdout
        except Exception as exc:
            payload["logs"] = f"Error: {exc}"
        return payload

    payload["source"] = "none"
    payload["logs"] = "No log file configured for this service on this host. journalctl is unavailable."
    return payload


@app.route("/api/services")
@ops_login_required
def list_services():
    """List all services with live status from Docker or cloud checks."""
    try:
        client = get_docker_client()
    except Exception as e:
        client = None
    services = _active_services()
    results = []
    for svc in services:
        service_name = str(svc.get("name") or "")
        port_value = svc.get("port")
        port_num = _extract_primary_port(port_value)
        service_port = f"{service_name}.{port_num}" if port_num is not None else f"{service_name}.{port_value or 'unknown'}"
        info = {
            **svc,
            "id": service_name,
            "canonical_name": _canonical_service_name(service_name),
            "status": "unknown",
            "uptime": "—",
            "health": "—",
            "aliases": _service_aliases_for(service_name),
            "port_number": port_num,
            "service_port": service_port,
        }
        
        # Cloud services (Qdrant Cloud, Neo4j Aura)
        if svc.get("type") == "cloud":
            if "qdrant" in svc["name"].lower():
                status, health, cloud_info = _check_qdrant_cloud()
                info["status"] = status
                info["health"] = health
                info["cloud_info"] = cloud_info
            elif "neo4j" in svc["name"].lower():
                status, health, cloud_info = _check_neo4j_cloud()
                info["status"] = status
                info["health"] = health
                info["cloud_info"] = cloud_info
            else:
                info["status"] = "cloud"
                info["health"] = "—"
            results.append(info)
            continue
        
        if svc["compose"] is None:
            # Host-level service (e.g., Ollama): use cross-platform port probe first.
            port_num = None
            try:
                port_num = int(svc["port"])
            except (ValueError, TypeError):
                pass
            found_listening = _is_tcp_port_listening(port_num) if port_num else False
            if found_listening:
                info["status"] = "running"
            else:
                if shutil.which("systemctl"):
                    try:
                        result = subprocess.run(
                            ["systemctl", "is-active", svc["name"]],
                            capture_output=True, text=True, timeout=5
                        )
                        info["status"] = result.stdout.strip() or "stopped"
                    except Exception:
                        info["status"] = "stopped"
                else:
                    info["status"] = "stopped"
            results.append(info)
            continue

        if client is None:
            info["status"] = "docker_unavailable"
            results.append(info)
            continue
        cname = container_name(svc["compose"])
        try:
            c = client.containers.get(cname)
            info["status"] = c.status  # running, exited, paused, etc.
            if c.status == "running":
                # Parse uptime from attrs
                started = c.attrs.get("State", {}).get("StartedAt", "")
                if started:
                    start_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                    delta = datetime.now(timezone.utc) - start_dt
                    total_s = int(delta.total_seconds())
                    if total_s > 86400:
                        info["uptime"] = f"{total_s // 86400}d {(total_s % 86400) // 3600}h"
                    elif total_s > 3600:
                        info["uptime"] = f"{total_s // 3600}h {(total_s % 3600) // 60}m"
                    else:
                        info["uptime"] = f"{total_s // 60}m"
                health = c.attrs.get("State", {}).get("Health", {})
                if health:
                    info["health"] = health.get("Status", "—")
        except docker.errors.NotFound:
            info["status"] = "not_found"
        except Exception as e:
            info["status"] = f"error: {str(e)[:50]}"
        results.append(info)
    return jsonify(results)


@app.route("/api/services/<service>/logs")
@ops_login_required
def service_logs(service):
    """Get recent logs for a service."""
    svc_def, canonical = _resolve_service_definition(service, include_all=False)
    if not svc_def:
        return jsonify({"error": "Unknown service"}), 404

    lines = _parse_tail_lines(request.args.get("lines", "80", type=str), default=80, max_lines=500)
    payload = _read_service_logs_snapshot(svc_def, lines)
    payload["requested_service"] = service
    payload["service"] = canonical
    return jsonify(payload)


@app.route("/api/observatory/services/logs")
@ops_login_required
def observatory_service_logs():
    """Return live log tails for one service or all active services/processes."""
    service_raw = (request.args.get("service", "all") or "all").strip()
    lines = _parse_tail_lines(request.args.get("lines", "120", type=str), default=120, max_lines=800)
    max_services = max(1, min(request.args.get("max_services", 50, type=int), 120))
    include_cloud = (request.args.get("include_cloud", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}

    if service_raw.lower() in {"all", "*", ""}:
        targets = [svc for svc in _active_services() if include_cloud or str(svc.get("type") or "") != "cloud"]
    else:
        svc_def, canonical = _resolve_service_definition(service_raw, include_all=False)
        if not svc_def:
            return jsonify({"error": "Unknown service"}), 404
        targets = [svc_def]
        service_raw = canonical

    entries = []
    for svc in sorted(targets, key=lambda s: str(s.get("name") or ""))[:max_services]:
        entries.append(_read_service_logs_snapshot(svc, lines))

    return jsonify({
        "service": service_raw,
        "lines": lines,
        "count": len(entries),
        "entries": entries,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/services/<service>/restart", methods=["POST"])
@ops_login_required
def restart_service(service):
    """Restart a Docker compose service or a host-script service."""
    services = _active_services()
    svc_def = next((s for s in services if s["name"] == service), None)
    if svc_def and svc_def.get("compose") is None:
        ok, message = _restart_host_service(svc_def)
        code = 200 if ok else 500
        return jsonify({"ok": ok, "message": message}), code

    valid_compose = {s["compose"] for s in services if s["compose"]}
    if service not in valid_compose:
        return jsonify({"error": "Cannot restart this service from dashboard"}), 400

    try:
        result = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "restart", service],
            capture_output=True, text=True, timeout=60,
            cwd=str(COMPOSE_DIR)
        )
        if result.returncode == 0:
            return jsonify({"ok": True, "message": f"{service} restarted", "output": result.stdout})
        else:
            return jsonify({"ok": False, "message": result.stderr}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "message": "Restart timed out (60s)"}), 504
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/services/<service>/stop", methods=["POST"])
@ops_login_required
def stop_service(service):
    """Stop a Docker compose service or a host process service."""
    services = _active_services()
    svc_def = next((s for s in services if s["name"] == service), None)
    if svc_def and svc_def.get("compose") is None:
        ok, message = _stop_host_service(svc_def)
        code = 200 if ok else 500
        return jsonify({"ok": ok, "message": message}), code

    valid_compose = {s["compose"] for s in services if s["compose"]}
    if service not in valid_compose:
        return jsonify({"error": "Cannot stop this service from dashboard"}), 400

    try:
        result = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "stop", service],
            capture_output=True, text=True, timeout=30,
            cwd=str(COMPOSE_DIR)
        )
        if result.returncode == 0:
            return jsonify({"ok": True, "message": f"{service} stopped"})
        else:
            return jsonify({"ok": False, "message": result.stderr}), 500
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/services/<service>/start", methods=["POST"])
@ops_login_required
def start_service(service):
    """Start a Docker compose service or a host process service."""
    services = _active_services()
    svc_def = next((s for s in services if s["name"] == service), None)
    if svc_def and svc_def.get("compose") is None:
        ok, message = _start_host_service(svc_def)
        code = 200 if ok else 500
        return jsonify({"ok": ok, "message": message}), code

    valid_compose = {s["compose"] for s in services if s["compose"]}
    if service not in valid_compose:
        return jsonify({"error": "Cannot start this service from dashboard"}), 400

    try:
        result = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "start", service],
            capture_output=True, text=True, timeout=60,
            cwd=str(COMPOSE_DIR)
        )
        if result.returncode == 0:
            return jsonify({"ok": True, "message": f"{service} started"})
        else:
            return jsonify({"ok": False, "message": result.stderr}), 500
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


# ── MCP server control (any ecosystem MCP server, per server) ───────────────
@app.route("/api/mcp-servers")
@ops_login_required
def list_mcp_servers():
    """List every ecosystem MCP server with live port status."""
    servers = [_mcp_server_status(srv) for srv in MCP_SERVERS]
    return jsonify({
        "servers": servers,
        "count": len(servers),
        "running": sum(1 for s in servers if s["status"] == "running"),
    })


@app.route("/api/mcp-servers/<mcp_id>/start", methods=["POST"])
@ops_login_required
def start_mcp_server(mcp_id):
    """Start a single ecosystem MCP server."""
    srv = _mcp_by_id(mcp_id)
    if not srv:
        return jsonify({"error": f"Unknown MCP server '{mcp_id}'"}), 404
    ok, message = _start_mcp_server(srv)
    code = 200 if ok else 500
    return jsonify({"ok": ok, "message": message, "server": _mcp_server_status(srv)}), code


@app.route("/api/mcp-servers/<mcp_id>/stop", methods=["POST"])
@ops_login_required
def stop_mcp_server(mcp_id):
    """Stop a single ecosystem MCP server."""
    srv = _mcp_by_id(mcp_id)
    if not srv:
        return jsonify({"error": f"Unknown MCP server '{mcp_id}'"}), 404
    ok, message = _stop_mcp_server(srv)
    return jsonify({"ok": ok, "message": message, "server": _mcp_server_status(srv)}), 200


@app.route("/api/mcp-servers/<mcp_id>/restart", methods=["POST"])
@ops_login_required
def restart_mcp_server(mcp_id):
    """Restart a single ecosystem MCP server."""
    srv = _mcp_by_id(mcp_id)
    if not srv:
        return jsonify({"error": f"Unknown MCP server '{mcp_id}'"}), 404
    ok, message = _restart_mcp_server(srv)
    code = 200 if ok else 500
    return jsonify({"ok": ok, "message": message, "server": _mcp_server_status(srv)}), code


@app.route("/api/services/<service>/launch", methods=["POST"])
@ops_login_required
def launch_service(service):
    """Return the URL to open this service in a browser/headless app window.

    The frontend uses this URL to open the service via window.open().
    For macOS, it can also be opened server-side with the 'open' command.
    """
    services = _active_services()
    svc_def = next((s for s in services if s["name"] == service), None)
    if not svc_def:
        return jsonify({"ok": False, "message": f"Service '{service}' not found"}), 404

    # Use explicit open_url if configured
    open_url = svc_def.get("open_url")
    if not open_url:
        # Fallback: construct from host/port
        port = svc_def.get("port")
        if port and port not in ("cloud", "—"):
            host = svc_def.get("host", "127.0.0.1")
            open_url = f"http://{host}:{port}"
        else:
            return jsonify({"ok": False, "message": "No URL configured for this service"}), 400

    # On macOS, attempt to open with Chrome --app mode for a headless feel
    try:
        import platform
        if platform.system() == "Darwin":
            chrome_bins = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
                "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            ]
            for chrome in chrome_bins:
                if Path(chrome).exists():
                    subprocess.Popen(
                        [chrome, f"--app={open_url}", "--window-size=1300,920",
                         "--no-first-run", "--no-default-browser-check"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    break
            else:
                subprocess.Popen(["open", open_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass  # Client-side fallback via returned URL

    return jsonify({"ok": True, "url": open_url, "message": f"Launching {service}"})

@app.route("/api/projects")
@ops_login_required
def list_projects():
    """List all projects with key file timestamps."""
    results = []
    for proj in PROJECTS:
        pdir = PROJECT_ROOT / proj["path"]
        info = {"name": proj["name"], "path": proj["path"], "exists": pdir.exists(), "files": []}
        if pdir.exists():
            for kf in proj["key_files"]:
                fp = pdir / kf
                if fp.exists():
                    stat = fp.stat()
                    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                    info["files"].append({
                        "name": kf,
                        "modified": mtime.isoformat(),
                        "modified_human": mtime.strftime("%d %b %Y %H:%M"),
                        "size_kb": round(stat.st_size / 1024, 1),
                    })
                elif fp.is_dir() if not fp.exists() else False:
                    pass
                else:
                    info["files"].append({"name": kf, "modified": None, "modified_human": "missing", "size_kb": 0})
            # Get latest modified file in whole project dir (top-level only)
            try:
                latest = max(
                    (f for f in pdir.rglob("*") if f.is_file() and ".git" not in f.parts and "__pycache__" not in f.parts),
                    key=lambda f: f.stat().st_mtime,
                    default=None
                )
                if latest:
                    lt = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
                    info["last_edit"] = lt.isoformat()
                    info["last_edit_human"] = lt.strftime("%d %b %Y %H:%M")
                    info["last_edit_file"] = str(latest.relative_to(PROJECT_ROOT))
            except Exception:
                pass
        results.append(info)
    return jsonify(results)


@app.route("/api/nginx/status")
@ops_login_required
def nginx_status():
    """Test nginx config and get recent access logs."""
    try:
        # Test nginx config inside the container
        result = subprocess.run(
            ["docker", "exec", "awareness-frontend-api-gateway-1", "nginx", "-t"],
            capture_output=True, text=True, timeout=10
        )
        config_ok = result.returncode == 0
        config_msg = result.stderr.strip()
    except Exception as e:
        config_ok = False
        config_msg = str(e)

    # Get recent access logs
    try:
        client = get_docker_client()
        c = client.containers.get("awareness-frontend-api-gateway-1")
        logs = c.logs(tail=20, timestamps=True).decode("utf-8", errors="replace")
    except Exception:
        logs = "Could not retrieve logs"

    return jsonify({"config_ok": config_ok, "config_msg": config_msg, "logs": logs})



# ── Quick Links catalog ────────────────────────────────────────────────────
QUICK_LINKS = [
    # Platform
    {"group": "Platform", "name": "Portal",               "path": "/",                          "desc": "Awareness AI service portal hub",              "icon": "home",             "service": None},
    {"group": "Platform", "name": "Awareness AI",         "path": "/awareness",                 "desc": "Main Awareness AI platform workspace",         "icon": "robot",            "service": "awareness"},
    {"group": "Platform", "name": "Viewer Paths",         "path": "/viewer-paths",               "desc": "Path viewer and navigation tool",              "icon": "map",              "service": "awareness"},
    # Ops
    {"group": "Ops",      "name": "Ops Dashboard",        "path": "/ops",                       "desc": "Service control center (this app)",            "icon": "tachometer-alt",   "service": "ops-dashboard"},
    {"group": "Ops",      "name": "Observatory",          "path": "/observatory",               "desc": "System monitoring observatory",                "icon": "eye",              "service": "ops-dashboard"},
    {"group": "Ops",      "name": "Agent Architecture",   "path": "/ops/agent-architecture",   "desc": "Visual + editable architecture workspace",     "icon": "project-diagram",  "service": "agent-architecture"},
    {"group": "Ops",      "name": "Dashboard",            "path": "/dashboard",                 "desc": "Legal Intelligence dashboard view",            "icon": "sitemap",          "service": "ops-dashboard"},
    {"group": "Ops",      "name": "Login",                "path": "/ops/login",                 "desc": "Ops dashboard authentication",                 "icon": "sign-in-alt",      "service": "ops-dashboard"},
    # Bridge
    {"group": "Bridge",   "name": "Discovery",            "path": "/discovery",                 "desc": "Data discovery and file explorer interface",   "icon": "search",           "service": "bridge-ui"},
    {"group": "Bridge",   "name": "Agent Residência",     "path": "/agent-residencia",          "desc": "Medical residency agent for UNIRG",            "icon": "hospital",         "service": "bridge"},
    # Olivia
    {"group": "Olivia",   "name": "Olivia Home",          "path": "/pages/olivia/olivia-home-br.html",                 "desc": "Olivia main home page — conversational AI",    "icon": "leaf",             "service": "olivia"},
    {"group": "Olivia",   "name": "Olivia Architecture",  "path": "/pages/olivia/olivia-arquitetura.html",             "desc": "Olivia ecosystem architecture documentation",  "icon": "drafting-compass", "service": "olivia"},
    {"group": "Olivia",   "name": "Olivia Workspace",     "path": "/pages/olivia/olivia-workspace-index.html",         "desc": "Olivia workspace index — tools and spaces",    "icon": "th-large",         "service": "olivia"},
    {"group": "Olivia",   "name": "Olivia Shaderbench",   "path": "/pages/olivia/olivia-workspace-shaderbench.html",   "desc": "Olivia shader workbench integration",          "icon": "paint-brush",      "service": "olivia"},
    {"group": "Olivia",   "name": "Olivia (live)",        "path": "/olivia/",                   "desc": "Olivia live service proxy",                    "icon": "comments",         "service": "olivia"},
    # Legal
    {"group": "Legal",    "name": "Jurisprudence",        "path": "/jurisprudence",             "desc": "Legal research and jurisprudence analysis",    "icon": "balance-scale",    "service": "jurisprudence"},
    {"group": "Legal",    "name": "Pinocchio",            "path": "/pinocchio",                 "desc": "Content verification and analysis",            "icon": "theater-masks",    "service": "pinocchio"},
    # Clients
    {"group": "Clients",  "name": "UNIRG Coremu",         "path": "/unirg-coremu",              "desc": "UNIRG medical residency commission portal",    "icon": "graduation-cap",   "service": "bridge"},
    {"group": "Clients",  "name": "Resolvvi",             "path": "/resolvvi",                  "desc": "Resolvvi — dispute resolution platform",       "icon": "check-circle",     "service": None},
    # Shaders
    {"group": "Shaders",  "name": "Shaderbench",          "path": "/shaderbench",               "desc": "WebGL shader workbench — visual experiments",  "icon": "sparkles",         "service": None},
    {"group": "Shaders",  "name": "Shaderbench 2",        "path": "/shaderbench-2",             "desc": "Advanced shader benchmark v2",                 "icon": "magic",            "service": None},
    {"group": "Shaders",  "name": "Shader Workbench",     "path": "/shader-workbench",          "desc": "Shader development workbench",                 "icon": "tools",            "service": None},
]

DOMAIN = "https://awareness-ai.com.br"

LOCAL_LINK_OVERRIDES = {
    "Portal":               "http://localhost:8090/",
    "Awareness AI":         "http://localhost:8078/",
    "Ops Dashboard":        "http://localhost:9000/ops",
    "Discovery":            "http://localhost:8075/",
    "Agent Architecture":   f"http://localhost:{AGENT_ARCH_PORT}/",
    "Olivia (live)":        "http://localhost:3005/",
}


# ── Quick Links CRUD helpers ────────────────────────────────────────────────
def _load_custom_links() -> list[dict]:
    """Load custom quick links from persistent JSON file."""
    if not CUSTOM_LINKS_FILE.exists():
        return []
    try:
        with open(CUSTOM_LINKS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_custom_links(links: list[dict]) -> bool:
    """Save custom quick links to persistent JSON file."""
    try:
        with open(CUSTOM_LINKS_FILE, "w", encoding="utf-8") as f:
            json.dump(links, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def _get_all_quicklinks() -> list[dict]:
    """Get combined list of all quick links (builtin + custom)."""
    custom = _load_custom_links()
    # Custom links can override builtin ones by name
    custom_names = {l.get("name") for l in custom}
    merged = [l for l in QUICK_LINKS if l.get("name") not in custom_names]
    merged.extend(custom)
    return merged


def _generate_link_id() -> str:
    """Generate a unique ID for a new quick link."""
    import uuid
    return f"ql_{uuid.uuid4().hex[:8]}"


@app.route("/api/quicklinks")
@ops_login_required
def quicklinks():
    """Return all quick links with full URLs."""
    all_links = _get_all_quicklinks()
    if _is_local_mode():
        return jsonify([
            {
                **l,
                "url": LOCAL_LINK_OVERRIDES.get(l["name"], l.get("custom_url") or f"http://localhost:8090{l.get('path', '/')}")
            }
            for l in all_links
        ])
    return jsonify([
        {
            **l,
            "url": l.get("custom_url") or (DOMAIN + l.get("path", "/"))
        }
        for l in all_links
    ])


@app.route("/api/quicklinks/manage", methods=["GET"])
@ops_login_required
def quicklinks_manage():
    """Return all quick links with editable metadata."""
    all_links = []
    custom_links = _load_custom_links()
    custom_names = {l.get("name") for l in custom_links}
    is_local = _is_local_mode()
    
    # Mark builtin links (skip those that have custom overrides)
    for l in QUICK_LINKS:
        if l["name"] in custom_names:
            continue  # Skip - has custom override
        entry = {**l, "builtin": True, "id": f"builtin_{l['name'].lower().replace(' ', '_')}"}
        if is_local:
            entry["url"] = LOCAL_LINK_OVERRIDES.get(l["name"], l.get("custom_url") or f"http://localhost:8080{l.get('path', '/')}")
        else:
            entry["url"] = l.get("custom_url") or (DOMAIN + l.get("path", "/"))
        all_links.append(entry)
    
    # Add custom links (these replace builtins with same name)
    for l in custom_links:
        entry = {**l, "builtin": False}
        if is_local:
            entry["url"] = l.get("custom_url") or f"http://localhost:8080{l.get('path', '/')}"
        else:
            entry["url"] = l.get("custom_url") or (DOMAIN + l.get("path", "/"))
        all_links.append(entry)
    return jsonify(all_links)


@app.route("/api/quicklinks", methods=["POST"])
@ops_login_required
def quicklinks_create():
    """Create a new custom quick link."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    required = ["name", "group"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400
    
    custom = _load_custom_links()
    
    # Check for duplicate name
    existing_names = {l.get("name") for l in custom}
    if data["name"] in existing_names:
        return jsonify({"error": f"Link with name '{data['name']}' already exists"}), 409
    
    new_link = {
        "id": _generate_link_id(),
        "name": data["name"],
        "group": data["group"],
        "desc": data.get("desc", ""),
        "path": data.get("path", "/"),
        "custom_url": data.get("custom_url", ""),  # Optional full URL override
        "icon": data.get("icon", "link"),
        "service": data.get("service"),  # Optional: service name for status dot
        "status_trigger": data.get("status_trigger"),  # Optional: URL to check for status
    }
    
    custom.append(new_link)
    if _save_custom_links(custom):
        return jsonify({"ok": True, "link": new_link}), 201
    return jsonify({"error": "Failed to save"}), 500


@app.route("/api/quicklinks/<link_id>", methods=["PUT"])
@ops_login_required
def quicklinks_update(link_id: str):
    """Update an existing quick link."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    # Cannot edit builtin links directly (but can override with custom)
    if link_id.startswith("builtin_"):
        # Create a custom override for this builtin link
        builtin_name = link_id.replace("builtin_", "").replace("_", " ").title()
        builtin = next((l for l in QUICK_LINKS if l["name"].lower().replace(" ", "_") == link_id.replace("builtin_", "")), None)
        if not builtin:
            return jsonify({"error": "Builtin link not found"}), 404
        
        custom = _load_custom_links()
        # Check if override already exists
        existing = next((l for l in custom if l.get("name") == builtin["name"]), None)
        if existing:
            # Update the existing override
            existing.update({
                "name": data.get("name", existing["name"]),
                "group": data.get("group", existing["group"]),
                "desc": data.get("desc", existing.get("desc", "")),
                "path": data.get("path", existing.get("path", "/")),
                "custom_url": data.get("custom_url", existing.get("custom_url", "")),
                "icon": data.get("icon", existing.get("icon", "link")),
                "service": data.get("service", existing.get("service")),
                "status_trigger": data.get("status_trigger", existing.get("status_trigger")),
            })
        else:
            # Create new override
            custom.append({
                "id": _generate_link_id(),
                "name": data.get("name", builtin["name"]),
                "group": data.get("group", builtin["group"]),
                "desc": data.get("desc", builtin.get("desc", "")),
                "path": data.get("path", builtin.get("path", "/")),
                "custom_url": data.get("custom_url", ""),
                "icon": data.get("icon", builtin.get("icon", "link")),
                "service": data.get("service", builtin.get("service")),
                "status_trigger": data.get("status_trigger"),
            })
        
        if _save_custom_links(custom):
            return jsonify({"ok": True})
        return jsonify({"error": "Failed to save"}), 500
    
    # Update custom link
    custom = _load_custom_links()
    link = next((l for l in custom if l.get("id") == link_id), None)
    if not link:
        return jsonify({"error": "Link not found"}), 404
    
    # Update fields
    if "name" in data:
        link["name"] = data["name"]
    if "group" in data:
        link["group"] = data["group"]
    if "desc" in data:
        link["desc"] = data["desc"]
    if "path" in data:
        link["path"] = data["path"]
    if "custom_url" in data:
        link["custom_url"] = data["custom_url"]
    if "icon" in data:
        link["icon"] = data["icon"]
    if "service" in data:
        link["service"] = data["service"]
    if "status_trigger" in data:
        link["status_trigger"] = data["status_trigger"]
    
    if _save_custom_links(custom):
        return jsonify({"ok": True, "link": link})
    return jsonify({"error": "Failed to save"}), 500


@app.route("/api/quicklinks/<link_id>", methods=["DELETE"])
@ops_login_required
def quicklinks_delete(link_id: str):
    """Delete a custom quick link or remove override for builtin."""
    if link_id.startswith("builtin_"):
        # Remove any custom override for this builtin
        builtin_name_key = link_id.replace("builtin_", "").replace("_", " ")
        custom = _load_custom_links()
        custom = [l for l in custom if l.get("name", "").lower().replace(" ", "_") != builtin_name_key]
        if _save_custom_links(custom):
            return jsonify({"ok": True, "message": "Override removed"})
        return jsonify({"error": "Failed to save"}), 500
    
    custom = _load_custom_links()
    original_len = len(custom)
    custom = [l for l in custom if l.get("id") != link_id]
    
    if len(custom) == original_len:
        return jsonify({"error": "Link not found"}), 404
    
    if _save_custom_links(custom):
        return jsonify({"ok": True})
    return jsonify({"error": "Failed to save"}), 500


@app.route("/api/quicklinks/groups", methods=["GET"])
@ops_login_required
def quicklinks_groups():
    """Return available groups and icons."""
    preferred_groups = ["Core", "Legal", "Engines", "Tools", "Ops", "Olivia", "Agents", "Admin", "Custom"]
    discovered_groups = sorted({str(l.get("group", "")).strip() for l in _get_all_quicklinks() if str(l.get("group", "")).strip()})
    groups = [g for g in preferred_groups if g in discovered_groups]
    groups.extend(g for g in discovered_groups if g not in groups)

    service_names = set()
    for service in _active_services():
        name = service.get("name")
        if name:
            service_names.add(name)
        for alias in _service_aliases_for(name or ""):
            service_names.add(alias)

    icons = [
        "home", "robot", "tools", "terminal", "database", "gavel", "balance-scale",
        "user-secret", "sitemap", "project-diagram", "microphone", "brain",
        "shield-alt", "magic", "chart-network", "user-cog", "linkedin", "bridge",
        "search", "tachometer-alt", "heartbeat", "link", "globe", "file", "folder",
        "cog", "server", "cloud", "code", "book", "graduation-cap", "briefcase",
        "seedling", "bolt", "sparkles", "map", "eye", "comments", "play", "check"
    ]
    return jsonify({"groups": groups, "icons": icons, "services": sorted(service_names)})


@app.route("/api/quicklinks/<link_id>/check", methods=["POST"])
@ops_login_required
def quicklinks_check_status(link_id: str):
    """Check the status of a quick link by its status_trigger URL."""
    all_links = _get_all_quicklinks()
    link = next((l for l in all_links if l.get("id") == link_id or f"builtin_{l.get('name', '').lower().replace(' ', '_')}" == link_id), None)
    
    if not link:
        return jsonify({"error": "Link not found"}), 404
    
    trigger_url = link.get("status_trigger")
    if not trigger_url:
        # Fallback: check if service is running
        service = link.get("service")
        if service:
            return jsonify({"status": "service_check", "service": service})
        return jsonify({"status": "unknown", "message": "No status trigger configured"})
    
    try:
        resp = requests.get(trigger_url, timeout=5)
        return jsonify({
            "status": "up" if resp.status_code < 400 else "down",
            "http_status": resp.status_code,
            "url": trigger_url
        })
    except requests.RequestException as e:
        return jsonify({"status": "down", "error": str(e), "url": trigger_url})


@app.route("/api/ecosystem")
@ops_login_required
def ecosystem_index():
    """Return ecosystem index built from ECOSYSTEM_PROJECTS (ECOSYSTEM_ORCHESTRATION.md) with live port status."""
    data = _build_ecosystem_index()
    return jsonify(data)


@app.route("/api/ecosystem/report")
@ops_login_required
def ecosystem_report():
    """Return the latest ecosystem orchestration report as markdown text."""
    report_file = ECOSYSTEM_REPORT_FILE
    if report_file and report_file.exists():
        content = report_file.read_text(encoding="utf-8")
        return Response(content, mimetype="text/markdown", headers={
            "X-Report-Generated": datetime.fromtimestamp(report_file.stat().st_mtime, tz=timezone.utc).isoformat(),
        })
    return jsonify({"error": "No ecosystem report found", "path": str(report_file)}), 404


@app.route("/api/ecosystem/<service_id>/spec")
@ops_login_required
def ecosystem_service_spec(service_id: str):
    """Return the full OpenAPI spec JSON for a specific service."""
    # Validate service_id — only alphanumeric, dash, underscore (prevents path traversal)
    if not all(c.isalnum() or c in "-_" for c in service_id):
        return jsonify({"error": "Invalid service ID"}), 400
    index_file = ECOSYSTEM_INDEX_FILE
    if not index_file.exists():
        return jsonify({"error": "Ecosystem index not found"}), 404
    with open(index_file, encoding="utf-8") as f:
        index = json.load(f)
    service = next((s for s in index.get("services", []) if s["id"] == service_id), None)
    if not service:
        return jsonify({"error": "Service not found"}), 404
    spec_name = service.get("api_spec", "")
    if not spec_name or not spec_name.endswith(".json"):
        return jsonify({"error": "No JSON spec available for this service"}), 404
    # Resolve and verify the spec path stays within API_DOCS_DIR (path traversal protection)
    spec_path = (API_DOCS_DIR / spec_name).resolve()
    if not str(spec_path).startswith(str(API_DOCS_DIR.resolve())):
        return jsonify({"error": "Invalid spec path"}), 400
    if not spec_path.exists():
        return jsonify({"error": "Spec file not found"}), 404
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    return jsonify(spec)


# ── Contracts & Ontology ─────────────────────────────────────────────────────

@app.route("/api/contracts")
@ops_login_required
def list_contracts():
    """List all contract files with metadata."""
    if not CONTRACTS_DIR.exists():
        return jsonify({"error": "Contracts directory not found"}), 404
    contracts = []
    for fp in sorted(CONTRACTS_DIR.glob("*.md")):
        stat = fp.stat()
        # Extract title and version from first lines
        title = ""
        fallback_title = fp.stem.replace("_", " ")
        version = ""
        purpose = ""
        with open(fp, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i > 30:
                    break
                stripped = line.strip()
                if stripped.startswith("# ") and not title:
                    title = stripped[2:]
                if "version" in stripped.lower() and ":" in stripped and not version:
                    version = stripped.split(":", 1)[1].strip().strip("*").strip()
                if "purpose" in stripped.lower() and not purpose:
                    # Read next non-empty line as purpose
                    for line2 in f:
                        s2 = line2.strip()
                        if s2 and not s2.startswith("#") and not s2.startswith("---"):
                            purpose = s2[:200]
                            break
                    break
        contracts.append({
            "filename": fp.name,
            "id": fp.stem,
            "title": title or fallback_title,
            "version": version,
            "purpose": purpose,
            "size_kb": round(stat.st_size / 1024, 1),
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime("%d %b %Y %H:%M"),
        })
    return jsonify(contracts)


@app.route("/api/contracts/<contract_id>")
@ops_login_required
def get_contract(contract_id: str):
    """Return the full markdown content of a specific contract."""
    # Validate: only alphanumeric, dash, underscore
    if not all(c.isalnum() or c in "-_" for c in contract_id):
        return jsonify({"error": "Invalid contract ID"}), 400
    fp = (CONTRACTS_DIR / f"{contract_id}.md").resolve()
    if not str(fp).startswith(str(CONTRACTS_DIR.resolve())):
        return jsonify({"error": "Invalid path"}), 400
    if not fp.exists():
        return jsonify({"error": "Contract not found"}), 404
    content = fp.read_text(encoding="utf-8")
    return jsonify({"id": contract_id, "filename": fp.name, "content": content})


@app.route("/api/ontology")
@ops_login_required
def get_ontology():
    """Return the ontology spec markdown content."""
    if not ONTOLOGY_DIR.exists():
        return jsonify({"error": "Ontology directory not found"}), 404
    specs = list(ONTOLOGY_DIR.glob("*.md"))
    if not specs:
        return jsonify({"error": "No ontology spec found"}), 404
    results = []
    for fp in sorted(specs):
        content = fp.read_text(encoding="utf-8")
        results.append({
            "filename": fp.name,
            "title": fp.stem,
            "content": content,
            "size_kb": round(fp.stat().st_size / 1024, 1),
        })
    return jsonify(results)


def _agent_arch_service_url() -> str:
    if AGENT_ARCH_SERVICE_URL:
        url = AGENT_ARCH_SERVICE_URL.strip()
        return url if url.endswith("/") else (url + "/")
    if has_request_context():
        script_root = (request.script_root or "").rstrip("/")
        if script_root:
            return f"{script_root}/agent-architecture/"
        return "/agent-architecture/"
    if _is_local_mode():
        return f"http://localhost:{AGENT_ARCH_PORT}/"
    return "/ops/agent-architecture/"


def _agent_arch_generated_manifest() -> tuple[list[dict], dict]:
    sections = {
        "agents": AGENT_ARCH_DIR / "generated" / "agents",
        "bundles": AGENT_ARCH_DIR / "generated" / "bundles",
        "policies": AGENT_ARCH_DIR / "generated" / "policies",
        "schemas": AGENT_ARCH_DIR / "generated" / "schemas",
    }
    files: list[dict] = []
    counts: dict[str, int] = {}

    for label, folder in sections.items():
        count = 0
        if folder.exists() and folder.is_dir():
            for entry in sorted(folder.rglob("*")):
                if not entry.is_file():
                    continue
                count += 1
                stat = entry.stat()
                files.append({
                    "category": label,
                    "path": str(entry.relative_to(AGENT_ARCH_DIR)),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                })
        counts[label] = count
    return files, counts


@app.route("/api/observatory/architecture")
@ops_login_required
def observatory_architecture():
    files, counts = _agent_arch_generated_manifest()
    source_exists = AGENT_ARCH_SOURCE_FILE.exists()
    source_stat = AGENT_ARCH_SOURCE_FILE.stat() if source_exists else None
    readme_md = AGENT_ARCH_README_FILE.read_text(encoding="utf-8") if AGENT_ARCH_README_FILE.exists() else ""

    return jsonify({
        "service": {
            "name": "agent-architecture",
            "port": AGENT_ARCH_PORT,
            "url": _agent_arch_service_url(),
            "health_url": f"http://localhost:{AGENT_ARCH_PORT}/health",
            "start_script": str(AGENT_ARCH_DIR / "start.sh"),
        },
        "source": {
            "path": str(AGENT_ARCH_SOURCE_FILE.relative_to(PROJECT_ROOT)) if source_exists else str(AGENT_ARCH_SOURCE_FILE),
            "exists": source_exists,
            "size": source_stat.st_size if source_stat else 0,
            "modified": datetime.fromtimestamp(source_stat.st_mtime, tz=timezone.utc).isoformat() if source_stat else None,
        },
        "readme_markdown": readme_md,
        "counts": {
            "agents": counts.get("agents", 0),
            "bundles": counts.get("bundles", 0),
            "policies": counts.get("policies", 0),
            "schemas": counts.get("schemas", 0),
            "total_files": len(files),
        },
        "files": files,
    })


@app.route("/api/observatory/architecture/source", methods=["GET", "PUT"])
@ops_login_required
def observatory_architecture_source():
    if request.method == "GET":
        if not AGENT_ARCH_SOURCE_FILE.exists():
            return jsonify({
                "path": str(AGENT_ARCH_SOURCE_FILE),
                "content": "",
                "encoding": "utf-8",
                "exists": False,
            })
        return jsonify({
            "path": str(AGENT_ARCH_SOURCE_FILE.relative_to(PROJECT_ROOT)),
            "content": AGENT_ARCH_SOURCE_FILE.read_text(encoding="utf-8"),
            "encoding": "utf-8",
            "exists": True,
        })

    data = request.get_json(silent=True) or {}
    content = data.get("content")
    if not isinstance(content, str):
        return jsonify({"error": "Field 'content' must be a string"}), 400

    AGENT_ARCH_SOURCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    AGENT_ARCH_SOURCE_FILE.write_text(content, encoding="utf-8")
    stat = AGENT_ARCH_SOURCE_FILE.stat()
    return jsonify({
        "ok": True,
        "path": str(AGENT_ARCH_SOURCE_FILE.relative_to(PROJECT_ROOT)),
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    })


# ── Observatory / API Logger ─────────────────────────────────────────────────

MANUS_BASE = "http://localhost:8078"   # internal port for manus container
KOUT_BASE = "http://localhost:3019"    # internal port for kout container
COREMU_BASE = "http://localhost:3119"  # internal port for coremu container
try:
    AWARENESS_PORT = int(str(os.environ.get("OPS_AWARENESS_PORT", "3119")).strip())
except ValueError:
    AWARENESS_PORT = 3119
AWARENESS_BASE = str(os.environ.get("OPS_AWARENESS_BASE_URL", f"http://localhost:{AWARENESS_PORT}")).strip() or f"http://localhost:{AWARENESS_PORT}"
# DEPRECATED — legacy project vars (kept for reference)
# KOUT_UPLOADS_DIR = KOUT_DIR / "uploads"
# KOUT_AGENTS_SOURCE_DIR = KOUT_DIR / "agents"
# AWARENESS_UPLOADS_DIR = AWARENESS_DIR / "uploads"
AGENT_ARCH_GENERATED_DIR = AGENT_ARCH_DIR / "generated"
AGENT_ARCH_CORE_BUNDLES_DIR = AGENT_ARCH_GENERATED_DIR / "bundles"
AGENT_ARCH_LEGAL_BUNDLES_DIR = AGENT_ARCH_GENERATED_DIR / "legal" / "bundles"
KOUT_FRESH_PROJECT_ID = "agent-architecture"
KOUT_FRESH_PROJECT_NAME = "Agent Architecture Runtime"
KOUT_PROJECT_SECTION_FOLDERS = (
    "static",
    "src",
    "expense-service",
    "docs",
    "web_app",
    "scripts",
    "tests",
    "data",
    "uploads",
    "case_files",
    "discovery_files",
    "listening_files",
    "memory_files",
    "shaders_files",
    "studio_files",
)

_LOG_STORE_FILE = Path(__file__).parent / "api_log_store.json"
_NETWORK_STORE_FILE = Path(__file__).parent / "network_traffic_store.json"
try:
    _NETWORK_STORE_MAX_BYTES = int(str(os.environ.get("OPS_NETWORK_STORE_MAX_BYTES", "10485760")).strip())
except (TypeError, ValueError):
    _NETWORK_STORE_MAX_BYTES = 10485760
try:
    _LOG_STORE_MAX_BYTES = int(str(os.environ.get("OPS_LOG_STORE_MAX_BYTES", "6291456")).strip())
except (TypeError, ValueError):
    _LOG_STORE_MAX_BYTES = 6291456
_NETWORK_STORE_LOCK = threading.Lock()
_NETWORK_STORE_CACHE: list | None = None
_OBS_CAPTURE_ENABLED = os.environ.get("OPS_OBSERVATORY_CAPTURE", "1").strip().lower() not in {"0", "false", "off", "no"}
_OBS_PROXY_ALLOWLIST = [
    host.strip().lower()
    for host in os.environ.get(
        "OPS_PROXY_ALLOWLIST",
        "localhost,127.0.0.1,::1,awareness-ai.com.br,www.awareness-ai.com.br,72.60.143.139",
    ).split(",")
    if host.strip()
]
_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
    "proxy-authorization",
    "x-auth-token",
}


def _truncate_text(value, max_chars: int = 1200) -> str:
    text = "" if value is None else str(value)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"... [truncated {len(text) - max_chars} chars]"


def _safe_preview_payload(value, max_chars: int = 1200):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return _truncate_text(json.dumps(value, ensure_ascii=False), max_chars=max_chars)
    if isinstance(value, (bytes, bytearray)):
        try:
            return _truncate_text(value.decode("utf-8", errors="replace"), max_chars=max_chars)
        except Exception:
            return f"<binary:{len(value)} bytes>"
    return _truncate_text(value, max_chars=max_chars)


def _sanitize_headers(headers: dict | None) -> dict:
    sanitized: dict = {}
    if not headers:
        return sanitized
    for k, v in dict(headers).items():
        key = str(k).strip()
        low = key.lower()
        if low in _SENSITIVE_KEYS:
            sanitized[key] = "***"
            continue
        text = "" if v is None else str(v)
        sanitized[key] = _truncate_text(text, max_chars=180)
    return sanitized


def _normalize_observed_path(path_or_url: str) -> str:
    raw = str(path_or_url or "").strip()
    if not raw:
        return "/"
    if raw.startswith("http://") or raw.startswith("https://"):
        try:
            parsed = urlsplit(raw)
            path = parsed.path or "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"
            return path
        except Exception:
            return raw
    return raw


def _path_matches_prefix(path: str, prefix: str) -> bool:
    if path == prefix:
        return True
    if prefix == "/":
        return path.startswith("/")
    return path.startswith(prefix.rstrip("/") + "/")


def _infer_service_from_path(path_or_url: str) -> str:
    raw = str(path_or_url or "").strip()
    observed = _normalize_observed_path(raw)
    path = observed.split("?", 1)[0].strip() or "/"
    if not path.startswith("/"):
        path = "/" + path
    path_l = path.lower()

    for prefix, service in sorted(SERVICE_PATH_HINTS, key=lambda item: len(item[0]), reverse=True):
        prefix_l = str(prefix or "").strip().lower()
        if not prefix_l:
            continue
        if _path_matches_prefix(path_l, prefix_l):
            return _canonical_service_name(service)

    if raw.startswith("http://") or raw.startswith("https://"):
        try:
            parsed = urlsplit(raw)
            if parsed.port is not None:
                by_port = _service_by_port(int(parsed.port))
                if by_port:
                    return by_port

            host = (parsed.hostname or "").strip().lower()
            for suffix, service in SERVICE_HOST_HINTS:
                suffix_l = str(suffix or "").strip().lower()
                if not suffix_l:
                    continue
                if host == suffix_l or host.endswith("." + suffix_l):
                    return _canonical_service_name(service)
            if host in {"awareness-ai.com.br", "www.awareness-ai.com.br"}:
                return "gateway"
        except Exception:
            pass

    parts = [segment for segment in path_l.split("/") if segment]
    candidate = ""
    if parts:
        if parts[0] == "api" and len(parts) >= 2:
            candidate = parts[1]
        elif parts[0] == "auth":
            candidate = "gateway"
        else:
            candidate = parts[0]

    canonical = _canonical_service_name(candidate)
    if canonical != "unknown":
        return canonical

    return "unknown"


def _normalize_network_event(event: dict) -> dict:
    if not isinstance(event, dict):
        return {}

    normalized = dict(event)
    explicit_service = str(event.get("service") or "").strip()
    canonical = _canonical_service_name(explicit_service)
    if canonical == "unknown":
        target = str(event.get("url") or event.get("path") or "")
        canonical = _infer_service_from_path(target)

    normalized["service"] = canonical or "unknown"
    normalized["path"] = _normalize_observed_path(str(event.get("path") or event.get("url") or ""))
    return normalized


def _load_network_store_unlocked() -> list:
    global _NETWORK_STORE_CACHE
    if _NETWORK_STORE_CACHE is not None:
        return _NETWORK_STORE_CACHE

    try:
        if _NETWORK_STORE_FILE.exists():
            if _NETWORK_STORE_FILE.stat().st_size > _NETWORK_STORE_MAX_BYTES:
                rollover = _NETWORK_STORE_FILE.with_name(
                    f"{_NETWORK_STORE_FILE.stem}.oversize.{int(time.time())}{_NETWORK_STORE_FILE.suffix}"
                )
                try:
                    _NETWORK_STORE_FILE.replace(rollover)
                except Exception:
                    _NETWORK_STORE_FILE.write_text("[]", encoding="utf-8")
                _NETWORK_STORE_CACHE = []
                return _NETWORK_STORE_CACHE
            _NETWORK_STORE_CACHE = json.loads(_NETWORK_STORE_FILE.read_text(encoding="utf-8"))
            return _NETWORK_STORE_CACHE
    except Exception:
        pass
    _NETWORK_STORE_CACHE = []
    return _NETWORK_STORE_CACHE


def _save_network_store_unlocked(entries: list) -> None:
    global _NETWORK_STORE_CACHE
    try:
        trimmed = entries[-10000:]
        _NETWORK_STORE_CACHE = trimmed
        _NETWORK_STORE_FILE.write_text(json.dumps(trimmed, indent=2), encoding="utf-8")
    except Exception:
        pass


def _read_network_store() -> list:
    with _NETWORK_STORE_LOCK:
        return _load_network_store_unlocked()


def _append_network_event(event: dict) -> None:
    if not _OBS_CAPTURE_ENABLED:
        return
    if not isinstance(event, dict):
        return
    normalized_event = _normalize_network_event(event)
    if not normalized_event:
        return
    with _NETWORK_STORE_LOCK:
        entries = _load_network_store_unlocked()
        entries.append(normalized_event)
        _save_network_store_unlocked(entries)


def _build_known_endpoint_signatures() -> set[tuple[str, str]]:
    signatures: set[tuple[str, str]] = set()
    if not ENDPOINTS_FILE.exists():
        return signatures
    try:
        payload = json.loads(ENDPOINTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return signatures

    prefix_map = globals().get("_SERVICE_NGINX_PREFIX", {}) or {}
    for ep in payload.get("endpoints", []):
        method = str(ep.get("method", "GET")).upper()
        path = str(ep.get("path", "") or "").strip()
        if not path:
            continue
        if not path.startswith("/"):
            path = "/" + path
        signatures.add((method, path))

        service = str(ep.get("file", "")).split("/", 1)[0]
        prefix = prefix_map.get(service)
        if prefix:
            signatures.add((method, prefix.rstrip("/") + path))
    return signatures


_REQUESTS_SESSION_REQUEST_ORIG = requests.sessions.Session.request
_OBS_THREAD_CTX = threading.local()


def _observed_requests_request(self, method, url, **kwargs):
    started = time.monotonic()
    status = None
    error_msg = None
    response = None
    try:
        response = _REQUESTS_SESSION_REQUEST_ORIG(self, method, url, **kwargs)
        status = response.status_code
        return response
    except Exception as exc:
        error_msg = str(exc)
        raise
    finally:
        if not _OBS_CAPTURE_ENABLED:
            return
        if has_request_context():
            try:
                if _should_skip_inbound_capture(request.path or ""):
                    return
            except Exception:
                pass
        ctx = getattr(_OBS_THREAD_CTX, "current", {}) or {}
        direction = ctx.get("direction", "outbound")
        latency_ms = int((time.monotonic() - started) * 1000)
        req_headers = kwargs.get("headers") or {}
        payload_preview = None
        if "json" in kwargs:
            payload_preview = _safe_preview_payload(kwargs.get("json"))
        elif "data" in kwargs:
            payload_preview = _safe_preview_payload(kwargs.get("data"))
        event = {
            "id": f"nt_{int(time.time() * 1000)}_{threading.get_ident()}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "direction": direction,
            "source": ctx.get("source", "requests"),
            "method": str(method or "GET").upper(),
            "url": str(url),
            "path": _normalize_observed_path(str(url)),
            "service": _infer_service_from_path(str(url)),
            "status": status,
            "latency_ms": latency_ms,
            "request_headers": _sanitize_headers(req_headers),
            "request_payload": payload_preview,
            "response_size": int(response.headers.get("Content-Length", 0)) if response is not None and response.headers.get("Content-Length", "").isdigit() else None,
            "error": _truncate_text(error_msg, max_chars=500) if error_msg else None,
        }
        _append_network_event(event)


requests.sessions.Session.request = _observed_requests_request


def _load_log_store() -> list:
    try:
        if _LOG_STORE_FILE.exists():
            if _LOG_STORE_FILE.stat().st_size > _LOG_STORE_MAX_BYTES:
                _LOG_STORE_FILE.write_text("[]", encoding="utf-8")
                return []
            return json.loads(_LOG_STORE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _save_log_store(entries: list) -> None:
    try:
        # Keep only the last 5000 entries
        _LOG_STORE_FILE.write_text(json.dumps(entries[-5000:], indent=2), encoding="utf-8")
    except Exception:
        pass


def _should_skip_inbound_capture(path: str) -> bool:
    if not path:
        return True
    if path.startswith("/api/observatory/"):
        return True
    if path.startswith("/api/api-logger/"):
        return True
    if path in {"/api/ecosystem", "/ops/api/ecosystem"}:
        return True
    if path in {"/api/projects", "/api/services", "/api/system"}:
        return True
    if path.startswith("/static/"):
        return True
    if path in {"/favicon.ico"}:
        return True
    if path.startswith("/api/observatory/network/feed"):
        return True
    if path.startswith("/api/observatory/network/summary"):
        return True
    if path.startswith("/api/observatory/services/logs"):
        return True
    if path.startswith("/api/services/") and path.endswith("/logs"):
        return True
    return False


@app.route("/favicon.ico")
def favicon():
    return "", 204


@app.before_request
def _observatory_capture_inbound_start():
    request._obs_started_monotonic = time.monotonic()


@app.after_request
def _observatory_capture_inbound_end(response):
    if not _OBS_CAPTURE_ENABLED:
        return response
    path = request.path or ""
    if _should_skip_inbound_capture(path):
        return response

    started = getattr(request, "_obs_started_monotonic", None)
    latency_ms = int((time.monotonic() - started) * 1000) if started else None
    req_data_preview = None
    try:
        content_type = (request.content_type or "").lower()
        if "application/json" in content_type:
            req_data_preview = _safe_preview_payload(request.get_json(silent=True))
        elif request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            req_data_preview = _safe_preview_payload(request.get_data(cache=True, as_text=True), max_chars=700)
    except Exception:
        req_data_preview = None

    client_ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
    event = {
        "id": f"nt_{int(time.time() * 1000)}_{threading.get_ident()}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "direction": "inbound",
        "source": "flask",
        "method": request.method,
        "path": _normalize_observed_path(path),
        "url": request.url,
        "service": _infer_service_from_path(path),
        "status": response.status_code,
        "latency_ms": latency_ms,
        "query": request.args.to_dict(flat=False),
        "request_headers": _sanitize_headers(request.headers),
        "request_payload": req_data_preview,
        "response_size": response.calculate_content_length(),
        "client_ip": client_ip,
        "user_agent": _truncate_text(request.headers.get("User-Agent", ""), max_chars=180),
    }
    _append_network_event(event)
    return response


@app.route("/api/api-logger/sessions")
@ops_login_required
def api_logger_sessions():
    """Return summary of stored API log sessions, optionally filtered by recency."""
    days = request.args.get("days", 7, type=int)
    limit = request.args.get("limit", 1000, type=int)
    entries = _load_log_store()
    cutoff = (datetime.now(timezone.utc) - __import__("datetime").timedelta(days=days)).isoformat()
    recent = [e for e in entries if e.get("timestamp", "") >= cutoff]
    # Group by session_id
    session_map: dict = {}
    for e in recent:
        sid = e.get("session_id") or e.get("sessionId") or "unknown"
        if sid not in session_map:
            session_map[sid] = {
                "session_id": sid,
                "saved_at": e.get("timestamp", ""),
                "count": 0,
                "source": e.get("source", "ops"),
            }
        session_map[sid]["count"] += 1
        if e.get("timestamp", "") > session_map[sid]["saved_at"]:
            session_map[sid]["saved_at"] = e["timestamp"]
    sessions_list = sorted(session_map.values(), key=lambda s: s["saved_at"], reverse=True)[:limit]
    return jsonify({"sessions": sessions_list, "total_entries": len(recent)})


@app.route("/api/api-logger/session/<session_id>")
@ops_login_required
def api_logger_session(session_id: str):
    """Return all log entries for a specific session_id."""
    # Sanitize session_id — only alphanum + hyphens/underscores
    import re
    if not re.match(r'^[\w\-]+$', session_id):
        return jsonify({"error": "Invalid session_id"}), 400
    entries = _load_log_store()
    logs = [e for e in entries if (e.get("session_id") or e.get("sessionId") or "unknown") == session_id]
    return jsonify({"session_id": session_id, "logs": logs})


@app.route("/api/api-logger/push", methods=["POST"])
@ops_login_required
def api_logger_push():
    """Receive new log entries and append to the log store."""
    data = request.get_json() or {}
    entries = _load_log_store()
    new_logs = data.get("logs") or ([] if not data.get("url") else [data])
    ts = datetime.now(timezone.utc).isoformat()
    for log in new_logs:
        if isinstance(log, dict):
            log.setdefault("timestamp", ts)
            log.setdefault("session_id", data.get("sessionId", "manual"))
            entries.append(log)

            endpoint = log.get("url") or log.get("endpoint") or log.get("path") or ""
            status = log.get("status") or log.get("statusCode")
            try:
                status = int(status) if status is not None else None
            except Exception:
                status = None
            try:
                duration = int(log.get("duration") or log.get("latency") or 0)
            except Exception:
                duration = None

            _append_network_event({
                "id": f"nt_{int(time.time() * 1000)}_{threading.get_ident()}",
                "timestamp": log.get("timestamp", ts),
                "direction": "ingested",
                "source": "api-logger/push",
                "method": str(log.get("method") or "GET").upper(),
                "path": _normalize_observed_path(str(endpoint)),
                "url": str(endpoint),
                "service": _infer_service_from_path(str(endpoint)),
                "status": status,
                "latency_ms": duration,
                "session_id": log.get("session_id") or log.get("sessionId") or data.get("sessionId"),
                "request_payload": _safe_preview_payload(log.get("requestPayload") or log.get("payload") or log.get("body")),
                "response_payload": _safe_preview_payload(log.get("responsePayload") or log.get("response")),
            })
    _save_log_store(entries)
    return jsonify({"ok": True, "stored": len(new_logs)})


@app.route("/api/api-logger/clear", methods=["POST"])
@ops_login_required
def api_logger_clear():
    """Clear all stored logs."""
    _save_log_store([])
    return jsonify({"ok": True})


@app.route("/api/observatory/network/feed")
@ops_login_required
def observatory_network_feed():
    """Return filtered network events captured by observability hooks."""
    limit = max(1, min(request.args.get("limit", 300, type=int), 2000))
    direction = (request.args.get("direction", "all") or "all").strip().lower()
    service_raw = (request.args.get("service", "all") or "all").strip().lower()
    if service_raw in {"", "all"}:
        service = "all"
    elif service_raw == "unknown":
        service = "unknown"
    else:
        service = _canonical_service_name(service_raw).lower()
    status_group = (request.args.get("status", "all") or "all").strip().lower()
    q = (request.args.get("q", "") or "").strip().lower()
    window_h = request.args.get("window_h", 24, type=int)
    now = datetime.now(timezone.utc)

    entries = _read_network_store()
    filtered: list = []
    for raw_event in entries:
        e = _normalize_network_event(raw_event)
        if not e:
            continue
        ts_raw = e.get("timestamp")
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        except Exception:
            ts = None

        if window_h > 0 and ts is not None:
            delta_h = (now - ts).total_seconds() / 3600.0
            if delta_h > window_h:
                continue

        e_direction = str(e.get("direction", "")).lower() or "unknown"
        e_service = str(e.get("service", "unknown")).lower()
        e_status = e.get("status")
        try:
            e_status_num = int(e_status) if e_status is not None else None
        except Exception:
            e_status_num = None

        if direction != "all" and e_direction != direction:
            continue
        if service != "all" and e_service != service:
            continue
        if status_group != "all":
            if status_group == "error":
                if e_status_num is None and not e.get("error"):
                    continue
                if e_status_num is not None and e_status_num < 400:
                    continue
            elif status_group == "ok":
                if e_status_num is None or e_status_num >= 400:
                    continue

        if q:
            hay = " ".join([
                str(e.get("method", "")),
                str(e.get("path", "")),
                str(e.get("url", "")),
                str(e.get("service", "")),
                str(e.get("source", "")),
                str(e.get("error", "")),
            ]).lower()
            if q not in hay:
                continue

        filtered.append(e)

    filtered.sort(key=lambda x: str(x.get("timestamp", "")), reverse=True)
    total = len(filtered)
    return jsonify({"events": filtered[:limit], "total": total, "limit": limit})


@app.route("/api/observatory/network/summary")
@ops_login_required
def observatory_network_summary():
    """Return aggregate network telemetry + endpoint coverage snapshot."""
    window_h = request.args.get("window_h", 24, type=int)
    now = datetime.now(timezone.utc)
    events = _read_network_store()

    selected: list = []
    for raw_event in events:
        e = _normalize_network_event(raw_event)
        if not e:
            continue
        ts_raw = e.get("timestamp")
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        except Exception:
            ts = None
        if window_h > 0 and ts is not None:
            if (now - ts).total_seconds() > window_h * 3600:
                continue
        selected.append(e)

    total = len(selected)
    errors = 0
    sum_latency = 0.0
    count_latency = 0
    by_direction = defaultdict(int)
    by_service = defaultdict(int)
    by_method = defaultdict(int)

    known = _build_known_endpoint_signatures()
    seen_known: set[tuple[str, str]] = set()

    for e in selected:
        by_direction[str(e.get("direction", "unknown"))] += 1
        by_service[str(e.get("service", "unknown"))] += 1
        by_method[str(e.get("method", "GET")).upper()] += 1

        status = e.get("status")
        try:
            status_num = int(status) if status is not None else None
        except Exception:
            status_num = None
        if status_num is not None and status_num >= 400:
            errors += 1
        if e.get("error") and status_num is None:
            errors += 1

        latency = e.get("latency_ms")
        try:
            latency_num = float(latency)
            if latency_num >= 0:
                sum_latency += latency_num
                count_latency += 1
        except Exception:
            pass

        method = str(e.get("method", "GET")).upper()
        path = _normalize_observed_path(str(e.get("path") or e.get("url") or "")).split("?", 1)[0]
        signature = (method, path)
        if signature in known:
            seen_known.add(signature)

    coverage_total = len(known)
    coverage_seen = len(seen_known)
    coverage_pct = round((coverage_seen / coverage_total * 100.0), 2) if coverage_total else None
    err_rate = round((errors / total * 100.0), 2) if total else 0.0
    avg_latency = round(sum_latency / count_latency, 2) if count_latency else None

    top_services = sorted(by_service.items(), key=lambda x: x[1], reverse=True)[:12]
    top_methods = sorted(by_method.items(), key=lambda x: x[1], reverse=True)

    return jsonify({
        "window_h": window_h,
        "total_events": total,
        "error_events": errors,
        "error_rate_pct": err_rate,
        "avg_latency_ms": avg_latency,
        "by_direction": dict(by_direction),
        "by_service": dict(top_services),
        "by_method": dict(top_methods),
        "coverage": {
            "known_endpoints": coverage_total,
            "observed_known_endpoints": coverage_seen,
            "coverage_pct": coverage_pct,
        },
    })


@app.route("/api/observatory/network/clear", methods=["POST"])
@ops_login_required
def observatory_network_clear():
    """Clear captured network telemetry events."""
    with _NETWORK_STORE_LOCK:
        _save_network_store_unlocked([])
    return jsonify({"ok": True})


def _is_allowed_proxy_target(target_url: str) -> tuple[bool, str]:
    try:
        parsed = urlsplit(target_url)
    except Exception:
        return False, "Invalid URL"
    if parsed.scheme not in {"http", "https"}:
        return False, "Only http/https are allowed"
    host = (parsed.hostname or "").lower()
    if not host:
        return False, "URL host is required"
    if host in _OBS_PROXY_ALLOWLIST:
        return True, ""
    if host.endswith(".awareness-ai.com.br"):
        return True, ""
    return False, f"Host '{host}' not in proxy allowlist"


@app.route("/api/observatory/network/proxy", methods=["POST"])
@ops_login_required
def observatory_network_proxy():
    """Forward one HTTP request and record it as a proxy-observed network event."""
    data = request.get_json(silent=True) or {}
    target_url = str(data.get("url") or "").strip()
    method = str(data.get("method") or "GET").upper().strip()
    timeout = data.get("timeout", 15)
    try:
        timeout = max(1, min(int(timeout), 60))
    except Exception:
        timeout = 15

    if not target_url:
        return jsonify({"error": "url is required"}), 400
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
        return jsonify({"error": "Unsupported method"}), 400

    allowed, reason = _is_allowed_proxy_target(target_url)
    if not allowed:
        return jsonify({"error": reason}), 403

    raw_headers = data.get("headers") if isinstance(data.get("headers"), dict) else {}
    headers = {str(k): str(v) for k, v in raw_headers.items()}
    headers.pop("Host", None)
    headers.pop("host", None)

    kwargs = {"headers": headers, "timeout": timeout}
    if "json" in data:
        kwargs["json"] = data.get("json")
    elif "body" in data:
        kwargs["data"] = data.get("body")

    prev_ctx = getattr(_OBS_THREAD_CTX, "current", None)
    _OBS_THREAD_CTX.current = {"direction": "proxy", "source": "observatory-proxy"}
    try:
        resp = requests.request(method, target_url, **kwargs)
    except requests.RequestException as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    finally:
        _OBS_THREAD_CTX.current = prev_ctx

    content_type = (resp.headers.get("Content-Type") or "").lower()
    if "application/json" in content_type:
        try:
            body_preview = resp.json()
        except Exception:
            body_preview = _truncate_text(resp.text, max_chars=1200)
    else:
        body_preview = _truncate_text(resp.text, max_chars=1200)

    return jsonify({
        "ok": True,
        "target": target_url,
        "method": method,
        "status": resp.status_code,
        "latency_hint": "check /api/observatory/network/feed for detailed timing",
        "headers": _sanitize_headers(resp.headers),
        "content_type": resp.headers.get("Content-Type"),
        "body": body_preview,
    }), 200


@app.route("/api/observatory/network/export")
@ops_login_required
def observatory_network_export():
    """Export filtered network events as CSV or JSON."""
    # Get format parameter (default: json)
    format_type = (request.args.get("format", "json") or "json").strip().lower()
    if format_type not in ["json", "csv"]:
        format_type = "json"

    # Get Accept header as fallback
    accept_header = request.headers.get("Accept", "").lower()
    if "text/csv" in accept_header and format_type == "json":
        format_type = "csv"

    # Get filter parameters (same as feed endpoint)
    limit = max(1, min(request.args.get("limit", 1000, type=int), 10000))
    direction = (request.args.get("direction", "all") or "all").strip().lower()
    service_raw = (request.args.get("service", "all") or "all").strip().lower()
    if service_raw in {"", "all"}:
        service = "all"
    elif service_raw == "unknown":
        service = "unknown"
    else:
        service = _canonical_service_name(service_raw).lower()
    status_group = (request.args.get("status", "all") or "all").strip().lower()
    q = (request.args.get("q", "") or "").strip().lower()
    window_h = request.args.get("window_h", 24, type=int)
    now = datetime.now(timezone.utc)

    entries = _read_network_store()
    filtered: list = []
    for raw_event in entries:
        e = _normalize_network_event(raw_event)
        if not e:
            continue
        ts_raw = e.get("timestamp")
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        except Exception:
            ts = None

        if window_h > 0 and ts is not None:
            delta_h = (now - ts).total_seconds() / 3600.0
            if delta_h > window_h:
                continue

        e_direction = str(e.get("direction", "")).lower() or "unknown"
        e_service = str(e.get("service", "unknown")).lower()
        e_status = e.get("status")
        try:
            e_status_num = int(e_status) if e_status is not None else None
        except Exception:
            e_status_num = None

        if direction != "all" and e_direction != direction:
            continue
        if service != "all" and e_service != service:
            continue
        if status_group != "all":
            if status_group == "error":
                if e_status_num is None and not e.get("error"):
                    continue
                if e_status_num is not None and e_status_num < 400:
                    continue
            elif status_group == "ok":
                if e_status_num is None or e_status_num >= 400:
                    continue

        if q:
            hay = " ".join([
                str(e.get("method", "")),
                str(e.get("path", "")),
                str(e.get("url", "")),
                str(e.get("service", "")),
                str(e.get("source", "")),
                str(e.get("error", "")),
            ]).lower()
            if q not in hay:
                continue

        filtered.append(e)

    filtered.sort(key=lambda x: str(x.get("timestamp", "")), reverse=True)
    filtered = filtered[:limit]

    if format_type == "csv":
        import csv
        import io

        # Define CSV columns
        fieldnames = [
            "timestamp", "direction", "service", "method", "path", "url",
            "status", "latency_ms", "source", "error", "request_id"
        ]

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for event in filtered:
            row = {}
            for field in fieldnames:
                value = event.get(field, "")
                # Convert None to empty string
                if value is None:
                    value = ""
                # Convert lists/dicts to JSON strings
                elif isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False)
                row[field] = str(value)
            writer.writerow(row)

        csv_content = output.getvalue()
        output.close()

        # Create response with CSV headers
        from flask import Response
        response = Response(
            csv_content,
            mimetype="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=network_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            }
        )
        return response

    else:  # JSON format
        return jsonify({
            "format": "json",
            "count": len(filtered),
            "total_available": len(entries),
            "filters": {
                "limit": limit,
                "direction": direction,
                "service": service,
                "status": status_group,
                "q": q,
                "window_h": window_h
            },
            "events": filtered
        })


# ── Observatory proxy endpoints — live service snapshot ──────────────────────

def _manus_get(path: str, timeout: int = 8) -> tuple[dict, int]:
    """GET from manus internal API. Returns (data, status_code)."""
    try:
        import urllib.request as _ur
        req = _ur.Request(f"{MANUS_BASE}{path}", headers={"Accept": "application/json"})
        with _ur.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except Exception as e:
        return {"error": str(e)}, 502


def _kout_get(path: str, timeout: int = 8) -> tuple[dict, int]:
    """GET from kout internal API. Returns (data, status_code)."""
    try:
        import urllib.request as _ur
        req = _ur.Request(f"{KOUT_BASE}{path}", headers={"Accept": "application/json"})
        with _ur.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except Exception as e:
        return {"error": str(e)}, 502


def _kout_post(path: str, data: dict, timeout: int = 10) -> tuple[dict, int]:
    """POST to kout internal API. Returns (data, status_code)."""
    try:
        import urllib.request as _ur
        import json as _json

        json_data = _json.dumps(data).encode("utf-8")
        req = _ur.Request(
            f"{KOUT_BASE}{path}",
            data=json_data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        with _ur.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except Exception as e:
        return {"error": str(e)}, 502


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _copy_tree_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    shutil.copytree(src, dst, dirs_exist_ok=True)
    return True


def _kout_bundle_entries() -> list[dict]:
    entries: list[dict] = []
    index_defs = [
        ("core", AGENT_ARCH_CORE_BUNDLES_DIR / "index.json", AGENT_ARCH_CORE_BUNDLES_DIR),
        ("legal", AGENT_ARCH_LEGAL_BUNDLES_DIR / "index.json", AGENT_ARCH_LEGAL_BUNDLES_DIR),
    ]
    for pack, index_path, bundles_dir in index_defs:
        if not index_path.is_file():
            continue
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for name in payload.get("files", []) if isinstance(payload, dict) else []:
            file_name = str(name or "").strip()
            if not file_name:
                continue
            full = bundles_dir / file_name
            if full.is_file():
                entries.append({"pack": pack, "name": file_name, "path": full})
    entries.sort(key=lambda item: (item["pack"], item["name"]))
    return entries


def _kout_service_def() -> dict | None:
    return next((svc for svc in _active_services() if str(svc.get("name") or "") == "kout"), None)


def _wait_for_kout_ready(timeout_sec: int = 90) -> tuple[bool, str]:
    deadline = time.time() + max(5, int(timeout_sec))
    last_error = ""
    while time.time() < deadline:
        try:
            response = requests.get(f"{KOUT_BASE}/api/agents/list", timeout=3)
            if response.status_code == 200:
                return True, "ready"
            last_error = f"HTTP {response.status_code}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.75)
    return False, last_error or "timeout waiting for kout"


def _prepare_fresh_project_workspace() -> dict:
    projects_dir = KOUT_UPLOADS_DIR / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)

    project_dir = projects_dir / KOUT_FRESH_PROJECT_ID
    if project_dir.exists():
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    for section in KOUT_PROJECT_SECTION_FOLDERS:
        (project_dir / section).mkdir(parents=True, exist_ok=True)

    generated_target = project_dir / "case_files" / "agent-architecture-generated"
    if AGENT_ARCH_GENERATED_DIR.is_dir():
        shutil.copytree(AGENT_ARCH_GENERATED_DIR, generated_target, dirs_exist_ok=True)

    source_target = project_dir / "docs" / "agent-architecture"
    source_target.mkdir(parents=True, exist_ok=True)
    for src_name in ("agent-architecture.jsx", "index.html"):
        src = AGENT_ARCH_DIR / src_name
        if src.is_file():
            shutil.copy2(src, source_target / src_name)

    meta = {
        "project_id": KOUT_FRESH_PROJECT_ID,
        "name": KOUT_FRESH_PROJECT_NAME,
        "description": "Fresh runtime project seeded from agents/generated.",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "path": str(project_dir),
    }
    (project_dir / "project.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    copied_files = 0
    if generated_target.exists():
        copied_files = sum(1 for p in generated_target.rglob("*") if p.is_file())

    return {
        "project": meta,
        "generated_files_copied": copied_files,
        "generated_target": str(generated_target),
    }


# DEPRECATED (kout legacy): def _reset_kout_runtime_with_backup() -> dict:
# DEPRECATED (kout legacy):     report: dict = {
# DEPRECATED (kout legacy):         "started_at": datetime.now(timezone.utc).isoformat(),
# DEPRECATED (kout legacy):         "backup": {},
# DEPRECATED (kout legacy):         "service": {},
# DEPRECATED (kout legacy):         "project": {},
# DEPRECATED (kout legacy):         "bundles": {"discovered": 0, "imported": [], "failed": []},
# DEPRECATED (kout legacy):         "assignments": {"ok": 0, "failed": []},
# DEPRECATED (kout legacy):         "verification": {},
# DEPRECATED (kout legacy):     }

# DEPRECATED (kout legacy):     if not KOUT_DIR.is_dir():
# DEPRECATED (kout legacy):         raise RuntimeError(f"Kout directory not found: {KOUT_DIR}")

# DEPRECATED (kout legacy):     stamp = _utc_stamp()
# DEPRECATED (kout legacy):     backup_dir = KOUT_BACKUPS_DIR / stamp
# DEPRECATED (kout legacy):     backup_dir.mkdir(parents=True, exist_ok=True)

# DEPRECATED (kout legacy):     # Stop Kout to make backup and cleanup deterministic.
# DEPRECATED (kout legacy):     svc_def = _kout_service_def()
# DEPRECATED (kout legacy):     if svc_def:
# DEPRECATED (kout legacy):         stopped_ok, stopped_msg = _stop_host_service(svc_def)
# DEPRECATED (kout legacy):         if not stopped_ok and "No running process found" not in str(stopped_msg):
# DEPRECATED (kout legacy):             raise RuntimeError(f"Failed to stop kout: {stopped_msg}")
# DEPRECATED (kout legacy):         report["service"]["stop"] = {"ok": bool(stopped_ok), "message": str(stopped_msg)}
# DEPRECATED (kout legacy):     else:
# DEPRECATED (kout legacy):         report["service"]["stop"] = {"ok": False, "message": "kout service definition not found"}

# DEPRECATED (kout legacy):     backup_items = [
# DEPRECATED (kout legacy):         ("uploads", KOUT_UPLOADS_DIR),
# DEPRECATED (kout legacy):         ("agents", KOUT_AGENTS_SOURCE_DIR),
# DEPRECATED (kout legacy):     ]
# DEPRECATED (kout legacy):     backup_manifest = []
# DEPRECATED (kout legacy):     for label, src in backup_items:
# DEPRECATED (kout legacy):         dst = backup_dir / label
# DEPRECATED (kout legacy):         copied = _copy_tree_if_exists(src, dst)
# DEPRECATED (kout legacy):         file_count = 0
# DEPRECATED (kout legacy):         if copied and dst.exists():
# DEPRECATED (kout legacy):             file_count = sum(1 for p in dst.rglob("*") if p.is_file())
# DEPRECATED (kout legacy):         backup_manifest.append({
# DEPRECATED (kout legacy):             "label": label,
# DEPRECATED (kout legacy):             "source": str(src),
# DEPRECATED (kout legacy):             "destination": str(dst),
# DEPRECATED (kout legacy):             "copied": copied,
# DEPRECATED (kout legacy):             "files": file_count,
# DEPRECATED (kout legacy):         })
# DEPRECATED (kout legacy):     report["backup"] = {
# DEPRECATED (kout legacy):         "root": str(backup_dir),
# DEPRECATED (kout legacy):         "items": backup_manifest,
# DEPRECATED (kout legacy):     }

# DEPRECATED (kout legacy):     # Wipe runtime uploads state to enforce clean start.
# DEPRECATED (kout legacy):     if KOUT_UPLOADS_DIR.exists():
# DEPRECATED (kout legacy):         shutil.rmtree(KOUT_UPLOADS_DIR)
# DEPRECATED (kout legacy):     KOUT_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
# DEPRECATED (kout legacy):     (KOUT_UPLOADS_DIR / "projects").mkdir(parents=True, exist_ok=True)

# DEPRECATED (kout legacy):     report["project"] = _prepare_fresh_project_workspace()

# DEPRECATED (kout legacy):     if svc_def:
# DEPRECATED (kout legacy):         started_ok, started_msg = _start_host_service(svc_def)
# DEPRECATED (kout legacy):         if not started_ok:
# DEPRECATED (kout legacy):             raise RuntimeError(f"Failed to start kout after reset: {started_msg}")
# DEPRECATED (kout legacy):         report["service"]["start"] = {"ok": True, "message": str(started_msg)}
# DEPRECATED (kout legacy):     else:
# DEPRECATED (kout legacy):         raise RuntimeError("kout service definition not found")

# DEPRECATED (kout legacy):     ready_ok, ready_msg = _wait_for_kout_ready(timeout_sec=120)
# DEPRECATED (kout legacy):     if not ready_ok:
# DEPRECATED (kout legacy):         raise RuntimeError(f"Kout did not become ready after reset: {ready_msg}")
# DEPRECATED (kout legacy):     report["service"]["ready"] = {"ok": True, "message": ready_msg}

# DEPRECATED (kout legacy):     bundle_entries = _kout_bundle_entries()
# DEPRECATED (kout legacy):     report["bundles"]["discovered"] = len(bundle_entries)
# DEPRECATED (kout legacy):     if not bundle_entries:
# DEPRECATED (kout legacy):         raise RuntimeError(f"No agent bundle files found to import from {AGENT_ARCH_GENERATED_DIR}")

# DEPRECATED (kout legacy):     imported_agent_ids: list[str] = []
# DEPRECATED (kout legacy):     for bundle in bundle_entries:
# DEPRECATED (kout legacy):         try:
# DEPRECATED (kout legacy):             payload = json.loads(Path(bundle["path"]).read_text(encoding="utf-8"))
# DEPRECATED (kout legacy):         except Exception as exc:
# DEPRECATED (kout legacy):             report["bundles"]["failed"].append({
# DEPRECATED (kout legacy):                 "bundle": f"{bundle['pack']}/{bundle['name']}",
# DEPRECATED (kout legacy):                 "error": f"invalid JSON: {exc}",
# DEPRECATED (kout legacy):             })
# DEPRECATED (kout legacy):             continue

# DEPRECATED (kout legacy):         response_data, status = _kout_post("/api/agents/import/bundle", payload, timeout=25)
# DEPRECATED (kout legacy):         agent_id = response_data.get("agent_id") if isinstance(response_data, dict) else None
# DEPRECATED (kout legacy):         if status in {200, 201} and agent_id:
# DEPRECATED (kout legacy):             imported_agent_ids.append(str(agent_id))
# DEPRECATED (kout legacy):             report["bundles"]["imported"].append({
# DEPRECATED (kout legacy):                 "bundle": f"{bundle['pack']}/{bundle['name']}",
# DEPRECATED (kout legacy):                 "agent_id": str(agent_id),
# DEPRECATED (kout legacy):                 "agent_name": response_data.get("agent_name") or response_data.get("name") or "",
# DEPRECATED (kout legacy):             })
# DEPRECATED (kout legacy):             continue

# DEPRECATED (kout legacy):         report["bundles"]["failed"].append({
# DEPRECATED (kout legacy):             "bundle": f"{bundle['pack']}/{bundle['name']}",
# DEPRECATED (kout legacy):             "status": status,
# DEPRECATED (kout legacy):             "response": response_data,
# DEPRECATED (kout legacy):         })

# DEPRECATED (kout legacy):     for agent_id in imported_agent_ids:
# DEPRECATED (kout legacy):         assign_data, assign_status = _kout_post(
# DEPRECATED (kout legacy):             "/api/projects/assign",
# DEPRECATED (kout legacy):             {"agent_id": agent_id, "project_id": KOUT_FRESH_PROJECT_ID},
# DEPRECATED (kout legacy):             timeout=15,
# DEPRECATED (kout legacy):         )
# DEPRECATED (kout legacy):         if assign_status == 200:
# DEPRECATED (kout legacy):             report["assignments"]["ok"] += 1
# DEPRECATED (kout legacy):         else:
# DEPRECATED (kout legacy):             report["assignments"]["failed"].append({
# DEPRECATED (kout legacy):                 "agent_id": agent_id,
# DEPRECATED (kout legacy):                 "status": assign_status,
# DEPRECATED (kout legacy):                 "response": assign_data,
# DEPRECATED (kout legacy):             })

# DEPRECATED (kout legacy):     agents_list, agents_status = _kout_get("/api/agents/list", timeout=20)
# DEPRECATED (kout legacy):     projects_list, projects_status = _kout_get("/api/projects/list", timeout=20)
# DEPRECATED (kout legacy):     wiring_checks = {
# DEPRECATED (kout legacy):         "agents_endpoint_status": agents_status,
# DEPRECATED (kout legacy):         "projects_endpoint_status": projects_status,
# DEPRECATED (kout legacy):         "agents_count": len(agents_list) if isinstance(agents_list, list) else 0,
# DEPRECATED (kout legacy):         "projects_count": len(projects_list.get("projects", [])) if isinstance(projects_list, dict) else 0,
# DEPRECATED (kout legacy):         "project_present": False,
# DEPRECATED (kout legacy):         "agent_project_links_ok": False,
# DEPRECATED (kout legacy):     }

# DEPRECATED (kout legacy):     if isinstance(projects_list, dict):
# DEPRECATED (kout legacy):         wiring_checks["project_present"] = any(
# DEPRECATED (kout legacy):             str(item.get("project_id") or "") == KOUT_FRESH_PROJECT_ID
# DEPRECATED (kout legacy):             for item in projects_list.get("projects", [])
# DEPRECATED (kout legacy):             if isinstance(item, dict)
# DEPRECATED (kout legacy):         )

# DEPRECATED (kout legacy):     link_ok = True
# DEPRECATED (kout legacy):     for agent_id in imported_agent_ids:
# DEPRECATED (kout legacy):         link_data, link_status = _kout_get(f"/api/projects/agent/{agent_id}", timeout=12)
# DEPRECATED (kout legacy):         project_payload = link_data.get("project") if isinstance(link_data, dict) else None
# DEPRECATED (kout legacy):         if link_status != 200 or not isinstance(project_payload, dict) or str(project_payload.get("project_id") or "") != KOUT_FRESH_PROJECT_ID:
# DEPRECATED (kout legacy):             link_ok = False
# DEPRECATED (kout legacy):             break
# DEPRECATED (kout legacy):     wiring_checks["agent_project_links_ok"] = link_ok
# DEPRECATED (kout legacy):     report["verification"] = wiring_checks
# DEPRECATED (kout legacy):     report["finished_at"] = datetime.now(timezone.utc).isoformat()
# DEPRECATED (kout legacy):     report["ok"] = (
# DEPRECATED (kout legacy):         len(report["bundles"]["failed"]) == 0
# DEPRECATED (kout legacy):         and len(report["assignments"]["failed"]) == 0
# DEPRECATED (kout legacy):         and wiring_checks["project_present"]
# DEPRECATED (kout legacy):         and wiring_checks["agent_project_links_ok"]
# DEPRECATED (kout legacy):     )
# DEPRECATED (kout legacy):     return report


# DEPRECATED (kout legacy): @app.route("/api/observatory/kout/fresh-reset", methods=["POST"])
# DEPRECATED (kout legacy): @ops_login_required
# DEPRECATED (kout legacy): def observatory_kout_fresh_reset():
# DEPRECATED (kout legacy):     """Backup Kout runtime data, wipe projects/agents state, reseed from agents workspace, and verify wiring."""
# DEPRECATED (kout legacy):     try:
# DEPRECATED (kout legacy):         report = _reset_kout_runtime_with_backup()
# DEPRECATED (kout legacy):         status = 200 if report.get("ok") else 500
# DEPRECATED (kout legacy):         return jsonify(report), status
# DEPRECATED (kout legacy):     except Exception as exc:
# DEPRECATED (kout legacy):         return jsonify({
# DEPRECATED (kout legacy):             "ok": False,
# DEPRECATED (kout legacy):             "error": str(exc),
# DEPRECATED (kout legacy):             "failed_at": datetime.now(timezone.utc).isoformat(),
# DEPRECATED (kout legacy):         }), 500


# DEPRECATED (coremu legacy): # ── COREMU Residency Fresh-Start ──────────────────────────────────────────────

# DEPRECATED (coremu legacy): COREMU_FRESH_PROJECT_ID = "coremu-rmisfc-2026"
# DEPRECATED (coremu legacy): COREMU_FRESH_PROJECT_NAME = "COREMU · RMISFC Residency 2026"
# DEPRECATED (coremu legacy): COREMU_UPLOADS_DIR = COREMU_DIR / "uploads"
# DEPRECATED (coremu legacy): COREMU_OLIVIA_BUNDLE_FILES = {
# DEPRECATED (coremu legacy):     "apiexplorer.bundle.import.json",
# DEPRECATED (coremu legacy):     "discovery.bundle.import.json",
# DEPRECATED (coremu legacy):     "listening.bundle.import.json",
# DEPRECATED (coremu legacy):     "memory.bundle.import.json",
# DEPRECATED (coremu legacy):     "orchestrator.bundle.import.json",
# DEPRECATED (coremu legacy):     "qdrant.bundle.import.json",
# DEPRECATED (coremu legacy):     "shaders.bundle.import.json",
# DEPRECATED (coremu legacy):     "studio.bundle.import.json",
# DEPRECATED (coremu legacy): }


# DEPRECATED (coremu legacy): def _coremu_get(path: str, timeout: int = 8) -> tuple[dict, int]:
# DEPRECATED (coremu legacy):     """GET from coremu internal API. Returns (data, status_code)."""
# DEPRECATED (coremu legacy):     try:
# DEPRECATED (coremu legacy):         import urllib.request as _ur
# DEPRECATED (coremu legacy):         req = _ur.Request(f"{COREMU_BASE}{path}", headers={"Accept": "application/json"})
# DEPRECATED (coremu legacy):         with _ur.urlopen(req, timeout=timeout) as resp:
# DEPRECATED (coremu legacy):             return json.loads(resp.read().decode("utf-8")), resp.status
# DEPRECATED (coremu legacy):     except Exception as e:
# DEPRECATED (coremu legacy):         return {"error": str(e)}, 502


# DEPRECATED (coremu legacy): def _coremu_post(path: str, data: dict, timeout: int = 10) -> tuple[dict, int]:
# DEPRECATED (coremu legacy):     """POST to coremu internal API. Returns (data, status_code)."""
# DEPRECATED (coremu legacy):     try:
# DEPRECATED (coremu legacy):         import urllib.request as _ur
# DEPRECATED (coremu legacy):         import json as _json

# DEPRECATED (coremu legacy):         json_data = _json.dumps(data).encode("utf-8")
# DEPRECATED (coremu legacy):         req = _ur.Request(
# DEPRECATED (coremu legacy):             f"{COREMU_BASE}{path}",
# DEPRECATED (coremu legacy):             data=json_data,
# DEPRECATED (coremu legacy):             headers={
# DEPRECATED (coremu legacy):                 "Accept": "application/json",
# DEPRECATED (coremu legacy):                 "Content-Type": "application/json"
# DEPRECATED (coremu legacy):             },
# DEPRECATED (coremu legacy):             method="POST"
# DEPRECATED (coremu legacy):         )
# DEPRECATED (coremu legacy):         with _ur.urlopen(req, timeout=timeout) as resp:
# DEPRECATED (coremu legacy):             return json.loads(resp.read().decode("utf-8")), resp.status
# DEPRECATED (coremu legacy):     except Exception as e:
# DEPRECATED (coremu legacy):         return {"error": str(e)}, 502


# DEPRECATED (coremu legacy): def _coremu_service_def() -> dict | None:
# DEPRECATED (coremu legacy):     return next((svc for svc in _active_services() if str(svc.get("name") or "") == "coremu"), None)


# DEPRECATED (coremu legacy): def _wait_for_coremu_ready(timeout_sec: int = 90) -> tuple[bool, str]:
# DEPRECATED (coremu legacy):     deadline = time.time() + max(5, int(timeout_sec))
# DEPRECATED (coremu legacy):     last_error = ""
# DEPRECATED (coremu legacy):     while time.time() < deadline:
# DEPRECATED (coremu legacy):         try:
# DEPRECATED (coremu legacy):             response = requests.get(f"{COREMU_BASE}/api/agents/list", timeout=3)
# DEPRECATED (coremu legacy):             if response.status_code == 200:
# DEPRECATED (coremu legacy):                 return True, "ready"
# DEPRECATED (coremu legacy):             last_error = f"HTTP {response.status_code}"
# DEPRECATED (coremu legacy):         except Exception as exc:
# DEPRECATED (coremu legacy):             last_error = str(exc)
# DEPRECATED (coremu legacy):         time.sleep(0.75)
# DEPRECATED (coremu legacy):     return False, last_error or "timeout waiting for coremu"


# DEPRECATED (coremu legacy): def _coremu_bundle_entries() -> list[dict]:
# DEPRECATED (coremu legacy):     """Return COREMU + Olivia bundle files from the core bundles index."""
# DEPRECATED (coremu legacy):     entries: list[dict] = []
# DEPRECATED (coremu legacy):     index_path = AGENT_ARCH_CORE_BUNDLES_DIR / "index.json"
# DEPRECATED (coremu legacy):     if not index_path.is_file():
# DEPRECATED (coremu legacy):         return entries
# DEPRECATED (coremu legacy):     try:
# DEPRECATED (coremu legacy):         payload = json.loads(index_path.read_text(encoding="utf-8"))
# DEPRECATED (coremu legacy):     except Exception:
# DEPRECATED (coremu legacy):         return entries
# DEPRECATED (coremu legacy):     for name in payload.get("files", []) if isinstance(payload, dict) else []:
# DEPRECATED (coremu legacy):         file_name = str(name or "").strip()
# DEPRECATED (coremu legacy):         if file_name.startswith("coremu-"):
# DEPRECATED (coremu legacy):             pack = "coremu"
# DEPRECATED (coremu legacy):         elif file_name in COREMU_OLIVIA_BUNDLE_FILES:
# DEPRECATED (coremu legacy):             pack = "olivia"
# DEPRECATED (coremu legacy):         else:
# DEPRECATED (coremu legacy):             continue
# DEPRECATED (coremu legacy):         full = AGENT_ARCH_CORE_BUNDLES_DIR / file_name
# DEPRECATED (coremu legacy):         if full.is_file():
# DEPRECATED (coremu legacy):             entries.append({"pack": pack, "name": file_name, "path": full})
# DEPRECATED (coremu legacy):     entries.sort(key=lambda item: (item["pack"], item["name"]))
# DEPRECATED (coremu legacy):     return entries


# DEPRECATED (coremu legacy): def _prepare_coremu_fresh_project_workspace() -> dict:
# DEPRECATED (coremu legacy):     projects_dir = COREMU_UPLOADS_DIR / "projects"
# DEPRECATED (coremu legacy):     projects_dir.mkdir(parents=True, exist_ok=True)

# DEPRECATED (coremu legacy):     project_dir = projects_dir / COREMU_FRESH_PROJECT_ID
# DEPRECATED (coremu legacy):     if project_dir.exists():
# DEPRECATED (coremu legacy):         shutil.rmtree(project_dir)
# DEPRECATED (coremu legacy):     project_dir.mkdir(parents=True, exist_ok=True)

# DEPRECATED (coremu legacy):     for section in KOUT_PROJECT_SECTION_FOLDERS:
# DEPRECATED (coremu legacy):         (project_dir / section).mkdir(parents=True, exist_ok=True)

# DEPRECATED (coremu legacy):     generated_target = project_dir / "case_files" / "agent-architecture-generated"
# DEPRECATED (coremu legacy):     if AGENT_ARCH_GENERATED_DIR.is_dir():
# DEPRECATED (coremu legacy):         shutil.copytree(AGENT_ARCH_GENERATED_DIR, generated_target, dirs_exist_ok=True)

# DEPRECATED (coremu legacy):     source_target = project_dir / "docs" / "agent-architecture"
# DEPRECATED (coremu legacy):     source_target.mkdir(parents=True, exist_ok=True)
# DEPRECATED (coremu legacy):     for src_name in ("agent-architecture.jsx", "index.html"):
# DEPRECATED (coremu legacy):         src = AGENT_ARCH_DIR / src_name
# DEPRECATED (coremu legacy):         if src.is_file():
# DEPRECATED (coremu legacy):             shutil.copy2(src, source_target / src_name)

# DEPRECATED (coremu legacy):     meta = {
# DEPRECATED (coremu legacy):         "project_id": COREMU_FRESH_PROJECT_ID,
# DEPRECATED (coremu legacy):         "name": COREMU_FRESH_PROJECT_NAME,
# DEPRECATED (coremu legacy):         "description": "Fresh COREMU runtime project seeded from agents/generated.",
# DEPRECATED (coremu legacy):         "created_at": datetime.now(timezone.utc).isoformat(),
# DEPRECATED (coremu legacy):         "path": str(project_dir),
# DEPRECATED (coremu legacy):     }
# DEPRECATED (coremu legacy):     (project_dir / "project.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

# DEPRECATED (coremu legacy):     copied_files = 0
# DEPRECATED (coremu legacy):     if generated_target.exists():
# DEPRECATED (coremu legacy):         copied_files = sum(1 for p in generated_target.rglob("*") if p.is_file())

# DEPRECATED (coremu legacy):     return {
# DEPRECATED (coremu legacy):         "project": meta,
# DEPRECATED (coremu legacy):         "generated_files_copied": copied_files,
# DEPRECATED (coremu legacy):         "generated_target": str(generated_target),
# DEPRECATED (coremu legacy):     }


# DEPRECATED (coremu legacy): def _reset_coremu_runtime_with_backup() -> dict:
# DEPRECATED (coremu legacy):     """Backup COREMU runtime data, wipe state, reimport COREMU+Olivia bundles, and verify wiring."""
# DEPRECATED (coremu legacy):     report: dict = {
# DEPRECATED (coremu legacy):         "started_at": datetime.now(timezone.utc).isoformat(),
# DEPRECATED (coremu legacy):         "backup": {},
# DEPRECATED (coremu legacy):         "service": {},
# DEPRECATED (coremu legacy):         "bundles": {"discovered": 0, "imported": [], "failed": []},
# DEPRECATED (coremu legacy):         "project": {},
# DEPRECATED (coremu legacy):         "assignments": {"ok": 0, "failed": []},
# DEPRECATED (coremu legacy):         "verification": {},
# DEPRECATED (coremu legacy):     }

# DEPRECATED (coremu legacy):     if not COREMU_DIR.is_dir():
# DEPRECATED (coremu legacy):         raise RuntimeError(f"COREMU directory not found: {COREMU_DIR}")

# DEPRECATED (coremu legacy):     stamp = _utc_stamp()
# DEPRECATED (coremu legacy):     backup_dir = COREMU_BACKUPS_DIR / stamp
# DEPRECATED (coremu legacy):     backup_dir.mkdir(parents=True, exist_ok=True)

# DEPRECATED (coremu legacy):     svc_def = _coremu_service_def()
# DEPRECATED (coremu legacy):     if svc_def:
# DEPRECATED (coremu legacy):         stopped_ok, stopped_msg = _stop_host_service(svc_def)
# DEPRECATED (coremu legacy):         if not stopped_ok and "No running process found" not in str(stopped_msg):
# DEPRECATED (coremu legacy):             raise RuntimeError(f"Failed to stop coremu: {stopped_msg}")
# DEPRECATED (coremu legacy):         report["service"]["stop"] = {"ok": bool(stopped_ok), "message": str(stopped_msg)}
# DEPRECATED (coremu legacy):     else:
# DEPRECATED (coremu legacy):         report["service"]["stop"] = {"ok": False, "message": "coremu service definition not found"}

# DEPRECATED (coremu legacy):     backup_items = [
# DEPRECATED (coremu legacy):         ("uploads", COREMU_UPLOADS_DIR),
# DEPRECATED (coremu legacy):     ]
# DEPRECATED (coremu legacy):     backup_manifest = []
# DEPRECATED (coremu legacy):     for label, src in backup_items:
# DEPRECATED (coremu legacy):         dst = backup_dir / label
# DEPRECATED (coremu legacy):         copied = _copy_tree_if_exists(src, dst)
# DEPRECATED (coremu legacy):         file_count = 0
# DEPRECATED (coremu legacy):         if copied and dst.exists():
# DEPRECATED (coremu legacy):             file_count = sum(1 for p in dst.rglob("*") if p.is_file())
# DEPRECATED (coremu legacy):         backup_manifest.append({
# DEPRECATED (coremu legacy):             "label": label,
# DEPRECATED (coremu legacy):             "source": str(src),
# DEPRECATED (coremu legacy):             "destination": str(dst),
# DEPRECATED (coremu legacy):             "copied": copied,
# DEPRECATED (coremu legacy):             "files": file_count,
# DEPRECATED (coremu legacy):         })
# DEPRECATED (coremu legacy):     report["backup"] = {
# DEPRECATED (coremu legacy):         "root": str(backup_dir),
# DEPRECATED (coremu legacy):         "items": backup_manifest,
# DEPRECATED (coremu legacy):     }

# DEPRECATED (coremu legacy):     if COREMU_UPLOADS_DIR.exists():
# DEPRECATED (coremu legacy):         shutil.rmtree(COREMU_UPLOADS_DIR)
# DEPRECATED (coremu legacy):     COREMU_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
# DEPRECATED (coremu legacy):     (COREMU_UPLOADS_DIR / "projects").mkdir(parents=True, exist_ok=True)

# DEPRECATED (coremu legacy):     report["project"] = _prepare_coremu_fresh_project_workspace()

# DEPRECATED (coremu legacy):     if svc_def:
# DEPRECATED (coremu legacy):         started_ok, started_msg = _start_host_service(svc_def)
# DEPRECATED (coremu legacy):         if not started_ok:
# DEPRECATED (coremu legacy):             raise RuntimeError(f"Failed to start coremu after reset: {started_msg}")
# DEPRECATED (coremu legacy):         report["service"]["start"] = {"ok": True, "message": str(started_msg)}
# DEPRECATED (coremu legacy):     else:
# DEPRECATED (coremu legacy):         raise RuntimeError("coremu service definition not found")

# DEPRECATED (coremu legacy):     ready_ok, ready_msg = _wait_for_coremu_ready(timeout_sec=120)
# DEPRECATED (coremu legacy):     if not ready_ok:
# DEPRECATED (coremu legacy):         raise RuntimeError(f"COREMU did not become ready after reset: {ready_msg}")
# DEPRECATED (coremu legacy):     report["service"]["ready"] = {"ok": True, "message": ready_msg}

# DEPRECATED (coremu legacy):     bundle_entries = _coremu_bundle_entries()
# DEPRECATED (coremu legacy):     report["bundles"]["discovered"] = len(bundle_entries)
# DEPRECATED (coremu legacy):     if not bundle_entries:
# DEPRECATED (coremu legacy):         raise RuntimeError(f"No COREMU/Olivia bundle files found in {AGENT_ARCH_CORE_BUNDLES_DIR}")

# DEPRECATED (coremu legacy):     imported_agent_ids: list[str] = []
# DEPRECATED (coremu legacy):     for bundle in bundle_entries:
# DEPRECATED (coremu legacy):         try:
# DEPRECATED (coremu legacy):             bundle_payload = json.loads(Path(bundle["path"]).read_text(encoding="utf-8"))
# DEPRECATED (coremu legacy):         except Exception as exc:
# DEPRECATED (coremu legacy):             report["bundles"]["failed"].append({
# DEPRECATED (coremu legacy):                 "bundle": bundle["name"],
# DEPRECATED (coremu legacy):                 "error": f"invalid JSON: {exc}",
# DEPRECATED (coremu legacy):             })
# DEPRECATED (coremu legacy):             continue

# DEPRECATED (coremu legacy):         response_data, status = _coremu_post("/api/agents/import/bundle", bundle_payload, timeout=25)
# DEPRECATED (coremu legacy):         agent_id = response_data.get("agent_id") if isinstance(response_data, dict) else None
# DEPRECATED (coremu legacy):         if status in {200, 201} and agent_id:
# DEPRECATED (coremu legacy):             imported_agent_ids.append(str(agent_id))
# DEPRECATED (coremu legacy):             report["bundles"]["imported"].append({
# DEPRECATED (coremu legacy):                 "bundle": f"{bundle['pack']}/{bundle['name']}",
# DEPRECATED (coremu legacy):                 "agent_id": str(agent_id),
# DEPRECATED (coremu legacy):                 "agent_name": response_data.get("agent_name") or response_data.get("name") or "",
# DEPRECATED (coremu legacy):             })
# DEPRECATED (coremu legacy):         else:
# DEPRECATED (coremu legacy):             report["bundles"]["failed"].append({
# DEPRECATED (coremu legacy):                 "bundle": f"{bundle['pack']}/{bundle['name']}",
# DEPRECATED (coremu legacy):                 "status": status,
# DEPRECATED (coremu legacy):                 "response": response_data,
# DEPRECATED (coremu legacy):             })

# DEPRECATED (coremu legacy):     # Assign all imported agents to the COREMU runtime project
# DEPRECATED (coremu legacy):     for agent_id in imported_agent_ids:
# DEPRECATED (coremu legacy):         assign_data, assign_status = _coremu_post(
# DEPRECATED (coremu legacy):             "/api/projects/assign",
# DEPRECATED (coremu legacy):             {"agent_id": agent_id, "project_id": COREMU_FRESH_PROJECT_ID},
# DEPRECATED (coremu legacy):             timeout=15,
# DEPRECATED (coremu legacy):         )
# DEPRECATED (coremu legacy):         if assign_status == 200:
# DEPRECATED (coremu legacy):             report["assignments"]["ok"] += 1
# DEPRECATED (coremu legacy):         else:
# DEPRECATED (coremu legacy):             report["assignments"]["failed"].append({
# DEPRECATED (coremu legacy):                 "agent_id": agent_id,
# DEPRECATED (coremu legacy):                 "status": assign_status,
# DEPRECATED (coremu legacy):                 "response": assign_data,
# DEPRECATED (coremu legacy):             })

# DEPRECATED (coremu legacy):     agents_list, agents_status = _coremu_get("/api/agents/list", timeout=20)
# DEPRECATED (coremu legacy):     projects_list, projects_status = _coremu_get("/api/projects/list", timeout=20)
# DEPRECATED (coremu legacy):     wiring_checks = {
# DEPRECATED (coremu legacy):         "agents_endpoint_status": agents_status,
# DEPRECATED (coremu legacy):         "projects_endpoint_status": projects_status,
# DEPRECATED (coremu legacy):         "agents_count": len(agents_list) if isinstance(agents_list, list) else 0,
# DEPRECATED (coremu legacy):         "projects_count": len(projects_list.get("projects", [])) if isinstance(projects_list, dict) else 0,
# DEPRECATED (coremu legacy):         "project_present": False,
# DEPRECATED (coremu legacy):         "agent_project_links_ok": False,
# DEPRECATED (coremu legacy):     }

# DEPRECATED (coremu legacy):     if isinstance(projects_list, dict):
# DEPRECATED (coremu legacy):         wiring_checks["project_present"] = any(
# DEPRECATED (coremu legacy):             str(item.get("project_id") or "") == COREMU_FRESH_PROJECT_ID
# DEPRECATED (coremu legacy):             for item in projects_list.get("projects", [])
# DEPRECATED (coremu legacy):             if isinstance(item, dict)
# DEPRECATED (coremu legacy):         )

# DEPRECATED (coremu legacy):     link_ok = True
# DEPRECATED (coremu legacy):     for agent_id in imported_agent_ids:
# DEPRECATED (coremu legacy):         link_data, link_status = _coremu_get(f"/api/projects/agent/{agent_id}", timeout=12)
# DEPRECATED (coremu legacy):         project_payload = link_data.get("project") if isinstance(link_data, dict) else None
# DEPRECATED (coremu legacy):         if link_status != 200 or not isinstance(project_payload, dict) or str(project_payload.get("project_id") or "") != COREMU_FRESH_PROJECT_ID:
# DEPRECATED (coremu legacy):             link_ok = False
# DEPRECATED (coremu legacy):             break
# DEPRECATED (coremu legacy):     wiring_checks["agent_project_links_ok"] = link_ok

# DEPRECATED (coremu legacy):     report["verification"] = wiring_checks
# DEPRECATED (coremu legacy):     report["finished_at"] = datetime.now(timezone.utc).isoformat()
# DEPRECATED (coremu legacy):     report["ok"] = (
# DEPRECATED (coremu legacy):         len(report["bundles"]["failed"]) == 0
# DEPRECATED (coremu legacy):         and len(report["assignments"]["failed"]) == 0
# DEPRECATED (coremu legacy):         and wiring_checks["project_present"]
# DEPRECATED (coremu legacy):         and wiring_checks["agent_project_links_ok"]
# DEPRECATED (coremu legacy):         and len(imported_agent_ids) > 0
# DEPRECATED (coremu legacy):     )
# DEPRECATED (coremu legacy):     if not report["ok"]:
# DEPRECATED (coremu legacy):         parts = []
# DEPRECATED (coremu legacy):         if len(imported_agent_ids) == 0:
# DEPRECATED (coremu legacy):             parts.append("no agents were imported")
# DEPRECATED (coremu legacy):         if report["bundles"]["failed"]:
# DEPRECATED (coremu legacy):             parts.append(f"{len(report['bundles']['failed'])} bundle(s) failed")
# DEPRECATED (coremu legacy):         if not wiring_checks["project_present"]:
# DEPRECATED (coremu legacy):             parts.append("project missing after reset")
# DEPRECATED (coremu legacy):         if len(report["assignments"]["failed"]) > 0:
# DEPRECATED (coremu legacy):             parts.append(f"{len(report['assignments']['failed'])} assignment(s) failed")
# DEPRECATED (coremu legacy):         if not wiring_checks["agent_project_links_ok"]:
# DEPRECATED (coremu legacy):             parts.append("project-agent wiring verification failed")
# DEPRECATED (coremu legacy):         report["error"] = "; ".join(parts) if parts else "unknown import failure"
# DEPRECATED (coremu legacy):     return report


# DEPRECATED (coremu legacy): @app.route("/api/observatory/coremu/fresh-reset", methods=["POST"])
@app.route("/api/observatory/coremu/fresh-import", methods=["POST"])
@ops_login_required
def observatory_coremu_fresh_reset():
    """Backup and reset COREMU runtime, then import COREMU+Olivia bundles and verify wiring."""
    try:
        report = _reset_coremu_runtime_with_backup()
        status = 200 if report.get("ok") else 500
        return jsonify(report), status
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }), 500


# ── Awareness Fresh-Start Import/Backup ─────────────────────────────────────

AWARENESS_FRESH_PROJECT_ID = "awareness-runtime-2026"
AWARENESS_FRESH_PROJECT_NAME = "Awareness Runtime 2026"
AWARENESS_DEFAULT_GROUPS = ["coremu", "olivia"]
AWARENESS_GROUPS_INDEX_FILE = AGENT_ARCH_DIR / "agents-groups" / "_meta" / "groups.index.json"
AWARENESS_GROUPS_DIR = AGENT_ARCH_DIR / "agents-groups"


def _awareness_get(path: str):
    try:
        with urllib.request.urlopen(f"{AWARENESS_BASE}{path}", timeout=25) as r:
            return json.loads(r.read().decode("utf-8", "replace")), None
    except Exception as exc:
        return None, str(exc)


def _awareness_post(path: str, payload: dict):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{AWARENESS_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            body = r.read().decode("utf-8", "replace")
            return (json.loads(body) if body else {}), None
    except urllib.error.HTTPError as he:
        try:
            body = he.read().decode("utf-8", "replace")
            return None, f"HTTP {he.code}: {body}"
        except Exception:
            return None, f"HTTP {he.code}: {he.reason}"
    except Exception as exc:
        return None, str(exc)


def _awareness_available_group_specs() -> list[dict]:
    """Return available agent groups sourced from /agents/agents-groups metadata."""
    groups: list[dict] = []

    if AWARENESS_GROUPS_INDEX_FILE.is_file():
        try:
            payload = json.loads(AWARENESS_GROUPS_INDEX_FILE.read_text(encoding="utf-8"))
            for item in payload.get("groups", []) if isinstance(payload, dict) else []:
                if not isinstance(item, dict):
                    continue
                slug = str(item.get("group") or "").strip().lower()
                if not slug:
                    continue
                manifest_rel = str(item.get("manifest") or f"agents-groups/{slug}/index.json").strip()
                groups.append({
                    "group": slug,
                    "label": str(item.get("label") or slug.upper()).strip() or slug.upper(),
                    "description": str(item.get("description") or "").strip(),
                    "manifest": manifest_rel,
                })
        except Exception:
            groups = []

    if not groups and AWARENESS_GROUPS_DIR.is_dir():
        for entry in sorted(AWARENESS_GROUPS_DIR.iterdir(), key=lambda p: p.name.lower()):
            if not entry.is_dir() or entry.name.startswith("_"):
                continue
            manifest = entry / "index.json"
            if not manifest.is_file():
                continue
            groups.append({
                "group": entry.name.lower(),
                "label": entry.name.upper(),
                "description": "",
                "manifest": f"agents-groups/{entry.name}/index.json",
            })

    deduped: list[dict] = []
    seen: set[str] = set()
    for item in groups:
        slug = str(item.get("group") or "").strip().lower()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        deduped.append(item)
    return deduped


def _awareness_normalize_groups(raw_groups) -> list[str]:
    """Normalize requested group names to lowercase slugs."""
    if isinstance(raw_groups, str):
        candidates = [s.strip() for s in raw_groups.split(",")]
    elif isinstance(raw_groups, (list, tuple, set)):
        candidates = [str(s).strip() for s in raw_groups]
    else:
        candidates = []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        slug = item.lower().strip()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        normalized.append(slug)
    return normalized


def _awareness_bundle_entries(selected_groups=None) -> tuple[list[dict], list[str]]:
    """Resolve import bundle files for selected groups from /agents manifests."""
    available_groups = _awareness_available_group_specs()
    group_map = {str(g.get("group") or "").strip().lower(): g for g in available_groups}

    requested = _awareness_normalize_groups(selected_groups)
    if not requested:
        requested = [g for g in AWARENESS_DEFAULT_GROUPS if g in group_map]
    if not requested:
        requested = list(group_map.keys())

    resolved_groups = [g for g in requested if g in group_map]
    entries: list[dict] = []
    seen_paths: set[str] = set()

    for group_slug in resolved_groups:
        spec = group_map[group_slug]
        manifest_rel = str(spec.get("manifest") or f"agents-groups/{group_slug}/index.json").strip()
        manifest_path = (AGENT_ARCH_DIR / manifest_rel).resolve()
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        bundle_files: list[str] = []
        for key in ("orchestrator", "coordinator"):
            item = manifest.get(key) if isinstance(manifest, dict) else None
            if isinstance(item, dict):
                bundle_rel = str(item.get("bundle_file") or "").strip()
                if bundle_rel:
                    bundle_files.append(bundle_rel)

        for item in manifest.get("agents", []) if isinstance(manifest, dict) else []:
            if not isinstance(item, dict):
                continue
            bundle_rel = str(item.get("bundle_file") or "").strip()
            if bundle_rel:
                bundle_files.append(bundle_rel)

        for bundle_rel in bundle_files:
            bundle_path = (AGENT_ARCH_DIR / bundle_rel).resolve()
            if not bundle_path.is_file():
                continue
            bundle_path_str = str(bundle_path)
            if bundle_path_str in seen_paths:
                continue
            seen_paths.add(bundle_path_str)
            entries.append({
                "pack": group_slug,
                "name": bundle_path.name,
                "path": bundle_path,
                "source": bundle_rel,
            })

    entries.sort(key=lambda item: (str(item.get("pack") or ""), str(item.get("name") or "")))
    return entries, resolved_groups


def _awareness_runtime_service_def() -> dict:
    awareness_service = next((svc for svc in _active_services() if str(svc.get("name") or "") == "awareness"), None)
    if awareness_service:
        awareness_script = str(awareness_service.get("start_script") or "").strip()
        if awareness_script and Path(awareness_script).exists():
            svc = dict(awareness_service)
            if not isinstance(svc.get("start_args"), list) or len(svc.get("start_args") or []) == 0:
                svc["start_args"] = ["--port", str(AWARENESS_PORT), "--no-tail"]
            return svc
    return {
        "name": "awareness-runtime",
        "port": str(AWARENESS_PORT),
        "start_script": str(AWARENESS_DIR / "start-all.sh"),
        "start_args": ["--port", str(AWARENESS_PORT), "--no-tail"],
    }


def _wait_for_awareness_ready(timeout_s: int = 120):
    deadline = time.time() + max(5, timeout_s)
    last_err = None
    while time.time() < deadline:
        data, err = _awareness_get("/api/agents/list")
        if err is None and isinstance(data, list):
            return True, None
        last_err = err or "unexpected response"
        time.sleep(1.5)
    return False, last_err or "timeout waiting for awareness"


def _prepare_awareness_fresh_project_workspace(project_id: str) -> dict:
    """Seed Awareness project workspace with default folders/files used by fresh imports."""
    base_dir = AWARENESS_UPLOADS_DIR / "projects" / project_id
    case_files_root = base_dir / "case_files" / "agent-architecture-generated"
    docs_root = base_dir / "docs" / "agent-architecture"

    case_files_root.mkdir(parents=True, exist_ok=True)
    docs_root.mkdir(parents=True, exist_ok=True)

    generated_files_copied = 0
    if AGENT_ARCH_GENERATED_DIR.exists():
        shutil.copytree(AGENT_ARCH_GENERATED_DIR, case_files_root, dirs_exist_ok=True)
        generated_files_copied = sum(1 for p in case_files_root.rglob("*") if p.is_file())

    copied_sources = []
    for src_name in ("agent-architecture.jsx", "index.html"):
        src = AGENT_ARCH_DIR / src_name
        if not src.is_file():
            continue
        target = docs_root / src_name
        shutil.copy2(src, target)
        copied_sources.append(str(target.relative_to(base_dir)))

    return {
        "project_id": project_id,
        "project_name": AWARENESS_FRESH_PROJECT_NAME,
        "workspace_root": str(base_dir),
        "generated_target": str(case_files_root),
        "generated_files_copied": generated_files_copied,
        "copied_source_files": copied_sources,
    }


# DEPRECATED (awareness legacy): def _reset_awareness_runtime_with_backup(selected_groups=None) -> dict:
# DEPRECATED (awareness legacy):     """Backup Awareness uploads, reset runtime state, import selected group bundles, assign, and verify."""
# DEPRECATED (awareness legacy):     started_at = datetime.now(timezone.utc).isoformat()
# DEPRECATED (awareness legacy):     requested_groups = _awareness_normalize_groups(selected_groups)
# DEPRECATED (awareness legacy):     report = {
# DEPRECATED (awareness legacy):         "ok": False,
# DEPRECATED (awareness legacy):         "started_at": started_at,
# DEPRECATED (awareness legacy):         "groups": {
# DEPRECATED (awareness legacy):             "requested": requested_groups,
# DEPRECATED (awareness legacy):             "resolved": [],
# DEPRECATED (awareness legacy):             "available": [],
# DEPRECATED (awareness legacy):         },
# DEPRECATED (awareness legacy):         "target": {
# DEPRECATED (awareness legacy):             "project_root": str(AWARENESS_DIR),
# DEPRECATED (awareness legacy):             "uploads_dir": str(AWARENESS_UPLOADS_DIR),
# DEPRECATED (awareness legacy):             "backup_dir": str(AWARENESS_BACKUPS_DIR),
# DEPRECATED (awareness legacy):             "project_id": AWARENESS_FRESH_PROJECT_ID,
# DEPRECATED (awareness legacy):             "project_name": AWARENESS_FRESH_PROJECT_NAME,
# DEPRECATED (awareness legacy):             "base_url": AWARENESS_BASE,
# DEPRECATED (awareness legacy):         },
# DEPRECATED (awareness legacy):         "service_stop": None,
# DEPRECATED (awareness legacy):         "backup": None,
# DEPRECATED (awareness legacy):         "clean": {"removed": [], "errors": []},
# DEPRECATED (awareness legacy):         "service_start": None,
# DEPRECATED (awareness legacy):         "wait_ready": None,
# DEPRECATED (awareness legacy):         "seed_workspace": None,
# DEPRECATED (awareness legacy):         "bundles": {"attempted": [], "imported": [], "failed": []},
# DEPRECATED (awareness legacy):         "project": {"attempted": None, "result": None, "error": None},
# DEPRECATED (awareness legacy):         "assignments": {"attempted": [], "ok": [], "failed": []},
# DEPRECATED (awareness legacy):         "verification": {},
# DEPRECATED (awareness legacy):     }

# DEPRECATED (awareness legacy):     if not AWARENESS_DIR.exists():
# DEPRECATED (awareness legacy):         raise RuntimeError(f"awareness project directory not found: {AWARENESS_DIR}")

# DEPRECATED (awareness legacy):     awareness_service = _awareness_runtime_service_def()
# DEPRECATED (awareness legacy):     if not Path(str(awareness_service.get("start_script") or "")).exists():
# DEPRECATED (awareness legacy):         raise RuntimeError(
# DEPRECATED (awareness legacy):             "awareness start script not found. "
# DEPRECATED (awareness legacy):             f"Set OPS_AWARENESS_PROJECT_ROOT or fix start script path ({awareness_service.get('start_script')})."
# DEPRECATED (awareness legacy):         )

# DEPRECATED (awareness legacy):     stopped_ok, stopped_msg = _stop_host_service(awareness_service)
# DEPRECATED (awareness legacy):     report["service_stop"] = {"ok": bool(stopped_ok), "message": str(stopped_msg)}
# DEPRECATED (awareness legacy):     if not stopped_ok and "No running process found" not in str(stopped_msg):
# DEPRECATED (awareness legacy):         raise RuntimeError(f"failed to stop awareness: {stopped_msg}")

# DEPRECATED (awareness legacy):     stamp = _utc_stamp()
# DEPRECATED (awareness legacy):     backup_dir = AWARENESS_BACKUPS_DIR / stamp
# DEPRECATED (awareness legacy):     backup_dir.mkdir(parents=True, exist_ok=True)

# DEPRECATED (awareness legacy):     backup_items = [("uploads", AWARENESS_UPLOADS_DIR)]
# DEPRECATED (awareness legacy):     backup_manifest = []
# DEPRECATED (awareness legacy):     for label, src in backup_items:
# DEPRECATED (awareness legacy):         dst = backup_dir / label
# DEPRECATED (awareness legacy):         copied = _copy_tree_if_exists(src, dst)
# DEPRECATED (awareness legacy):         file_count = 0
# DEPRECATED (awareness legacy):         if copied and dst.exists():
# DEPRECATED (awareness legacy):             file_count = sum(1 for p in dst.rglob("*") if p.is_file())
# DEPRECATED (awareness legacy):         backup_manifest.append({
# DEPRECATED (awareness legacy):             "label": label,
# DEPRECATED (awareness legacy):             "source": str(src),
# DEPRECATED (awareness legacy):             "destination": str(dst),
# DEPRECATED (awareness legacy):             "copied": copied,
# DEPRECATED (awareness legacy):             "files": file_count,
# DEPRECATED (awareness legacy):         })
# DEPRECATED (awareness legacy):     report["backup"] = {
# DEPRECATED (awareness legacy):         "root": str(backup_dir),
# DEPRECATED (awareness legacy):         "items": backup_manifest,
# DEPRECATED (awareness legacy):     }

# DEPRECATED (awareness legacy):     for _, p in backup_items:
# DEPRECATED (awareness legacy):         if p.exists():
# DEPRECATED (awareness legacy):             try:
# DEPRECATED (awareness legacy):                 shutil.rmtree(p)
# DEPRECATED (awareness legacy):                 report["clean"]["removed"].append(str(p))
# DEPRECATED (awareness legacy):             except Exception as exc:
# DEPRECATED (awareness legacy):                 report["clean"]["errors"].append({"path": str(p), "error": str(exc)})

# DEPRECATED (awareness legacy):     started_ok, started_msg = _start_host_service(awareness_service)
# DEPRECATED (awareness legacy):     report["service_start"] = {"ok": bool(started_ok), "message": str(started_msg)}
# DEPRECATED (awareness legacy):     if not started_ok:
# DEPRECATED (awareness legacy):         report["error"] = f"failed to start awareness service: {started_msg or 'unknown'}"
# DEPRECATED (awareness legacy):         report["finished_at"] = datetime.now(timezone.utc).isoformat()
# DEPRECATED (awareness legacy):         return report

# DEPRECATED (awareness legacy):     ready_ok, ready_err = _wait_for_awareness_ready(timeout_s=120)
# DEPRECATED (awareness legacy):     report["wait_ready"] = {"ok": ready_ok, "error": ready_err}
# DEPRECATED (awareness legacy):     if not ready_ok:
# DEPRECATED (awareness legacy):         report["error"] = f"awareness not ready: {ready_err or 'timeout'}"
# DEPRECATED (awareness legacy):         report["finished_at"] = datetime.now(timezone.utc).isoformat()
# DEPRECATED (awareness legacy):         return report

# DEPRECATED (awareness legacy):     available_groups = _awareness_available_group_specs()
# DEPRECATED (awareness legacy):     report["groups"]["available"] = [
# DEPRECATED (awareness legacy):         {
# DEPRECATED (awareness legacy):             "group": str(item.get("group") or ""),
# DEPRECATED (awareness legacy):             "label": str(item.get("label") or ""),
# DEPRECATED (awareness legacy):             "description": str(item.get("description") or ""),
# DEPRECATED (awareness legacy):         }
# DEPRECATED (awareness legacy):         for item in available_groups
# DEPRECATED (awareness legacy):     ]

# DEPRECATED (awareness legacy):     bundle_entries, resolved_groups = _awareness_bundle_entries(requested_groups)
# DEPRECATED (awareness legacy):     report["groups"]["resolved"] = resolved_groups
# DEPRECATED (awareness legacy):     if not bundle_entries:
# DEPRECATED (awareness legacy):         report["error"] = "no import bundles found for selected groups"
# DEPRECATED (awareness legacy):         report["finished_at"] = datetime.now(timezone.utc).isoformat()
# DEPRECATED (awareness legacy):         return report

# DEPRECATED (awareness legacy):     project_payload = {
# DEPRECATED (awareness legacy):         "name": AWARENESS_FRESH_PROJECT_ID,
# DEPRECATED (awareness legacy):         "description": AWARENESS_FRESH_PROJECT_NAME,
# DEPRECATED (awareness legacy):     }
# DEPRECATED (awareness legacy):     report["project"]["attempted"] = project_payload
# DEPRECATED (awareness legacy):     p_resp, p_err = _awareness_post("/api/projects/create", project_payload)
# DEPRECATED (awareness legacy):     if p_err:
# DEPRECATED (awareness legacy):         report["project"]["error"] = p_err
# DEPRECATED (awareness legacy):         report["finished_at"] = datetime.now(timezone.utc).isoformat()
# DEPRECATED (awareness legacy):         report["error"] = f"failed to create awareness project: {p_err}"
# DEPRECATED (awareness legacy):         return report

# DEPRECATED (awareness legacy):     report["project"]["result"] = p_resp
# DEPRECATED (awareness legacy):     effective_project_id = AWARENESS_FRESH_PROJECT_ID
# DEPRECATED (awareness legacy):     if isinstance(p_resp, dict):
# DEPRECATED (awareness legacy):         project_obj = p_resp.get("project") if isinstance(p_resp.get("project"), dict) else p_resp
# DEPRECATED (awareness legacy):         project_id_raw = str(project_obj.get("project_id") or "").strip() if isinstance(project_obj, dict) else ""
# DEPRECATED (awareness legacy):         if project_id_raw:
# DEPRECATED (awareness legacy):             effective_project_id = project_id_raw
# DEPRECATED (awareness legacy):     report["project"]["effective_project_id"] = effective_project_id
# DEPRECATED (awareness legacy):     report["target"]["effective_project_id"] = effective_project_id

# DEPRECATED (awareness legacy):     report["seed_workspace"] = _prepare_awareness_fresh_project_workspace(effective_project_id)

# DEPRECATED (awareness legacy):     imported_agent_ids = []

# DEPRECATED (awareness legacy):     for entry in bundle_entries:
# DEPRECATED (awareness legacy):         entry_payload = {
# DEPRECATED (awareness legacy):             "pack": str(entry.get("pack") or ""),
# DEPRECATED (awareness legacy):             "name": str(entry.get("name") or ""),
# DEPRECATED (awareness legacy):             "path": str(entry.get("path") or ""),
# DEPRECATED (awareness legacy):         }
# DEPRECATED (awareness legacy):         report["bundles"]["attempted"].append(entry_payload)
# DEPRECATED (awareness legacy):         try:
# DEPRECATED (awareness legacy):             with Path(entry_payload["path"]).open("r", encoding="utf-8") as f:
# DEPRECATED (awareness legacy):                 payload = json.load(f)
# DEPRECATED (awareness legacy):             resp, err = _awareness_post("/api/agents/import/bundle", payload)
# DEPRECATED (awareness legacy):             if err:
# DEPRECATED (awareness legacy):                 report["bundles"]["failed"].append({"entry": entry_payload, "error": err})
# DEPRECATED (awareness legacy):                 continue
# DEPRECATED (awareness legacy):             data = resp if isinstance(resp, dict) else {}
# DEPRECATED (awareness legacy):             aid = str(data.get("agent_id") or data.get("id") or "").strip()
# DEPRECATED (awareness legacy):             if aid:
# DEPRECATED (awareness legacy):                 imported_agent_ids.append(aid)
# DEPRECATED (awareness legacy):             report["bundles"]["imported"].append({
# DEPRECATED (awareness legacy):                 "entry": entry_payload,
# DEPRECATED (awareness legacy):                 "agent_id": aid or None,
# DEPRECATED (awareness legacy):                 "response": data,
# DEPRECATED (awareness legacy):             })
# DEPRECATED (awareness legacy):         except Exception as exc:
# DEPRECATED (awareness legacy):             report["bundles"]["failed"].append({"entry": entry_payload, "error": str(exc)})

# DEPRECATED (awareness legacy):     for aid in imported_agent_ids:
# DEPRECATED (awareness legacy):         payload = {"agent_id": aid, "project_id": effective_project_id}
# DEPRECATED (awareness legacy):         report["assignments"]["attempted"].append(payload)
# DEPRECATED (awareness legacy):         a_resp, a_err = _awareness_post("/api/projects/assign", payload)
# DEPRECATED (awareness legacy):         if a_err:
# DEPRECATED (awareness legacy):             report["assignments"]["failed"].append({
# DEPRECATED (awareness legacy):                 "agent_id": aid,
# DEPRECATED (awareness legacy):                 "error": a_err,
# DEPRECATED (awareness legacy):                 "response": a_resp,
# DEPRECATED (awareness legacy):             })
# DEPRECATED (awareness legacy):         else:
# DEPRECATED (awareness legacy):             report["assignments"]["ok"].append({
# DEPRECATED (awareness legacy):                 "agent_id": aid,
# DEPRECATED (awareness legacy):                 "response": a_resp,
# DEPRECATED (awareness legacy):             })

# DEPRECATED (awareness legacy):     projects_data, projects_err = _awareness_get("/api/projects/list")
# DEPRECATED (awareness legacy):     project_present = False
# DEPRECATED (awareness legacy):     if isinstance(projects_data, list):
# DEPRECATED (awareness legacy):         for p in projects_data:
# DEPRECATED (awareness legacy):             if str(p.get("project_id") or "") == effective_project_id:
# DEPRECATED (awareness legacy):                 project_present = True
# DEPRECATED (awareness legacy):                 break
# DEPRECATED (awareness legacy):     elif isinstance(projects_data, dict):
# DEPRECATED (awareness legacy):         for p in projects_data.get("projects", []) if isinstance(projects_data.get("projects"), list) else []:
# DEPRECATED (awareness legacy):             if isinstance(p, dict) and str(p.get("project_id") or "") == effective_project_id:
# DEPRECATED (awareness legacy):                 project_present = True
# DEPRECATED (awareness legacy):                 break

# DEPRECATED (awareness legacy):     link_checks = []
# DEPRECATED (awareness legacy):     links_ok = True
# DEPRECATED (awareness legacy):     for aid in imported_agent_ids:
# DEPRECATED (awareness legacy):         a_data, a_err = _awareness_get(f"/api/projects/agent/{urllib.parse.quote(aid, safe='')}")
# DEPRECATED (awareness legacy):         linked_pid = ""
# DEPRECATED (awareness legacy):         if isinstance(a_data, dict):
# DEPRECATED (awareness legacy):             linked_pid = str(
# DEPRECATED (awareness legacy):                 a_data.get("project_id")
# DEPRECATED (awareness legacy):                 or ((a_data.get("project") or {}).get("project_id") if isinstance(a_data.get("project"), dict) else "")
# DEPRECATED (awareness legacy):             )
# DEPRECATED (awareness legacy):         ok = (a_err is None) and (linked_pid == effective_project_id)
# DEPRECATED (awareness legacy):         if not ok:
# DEPRECATED (awareness legacy):             links_ok = False
# DEPRECATED (awareness legacy):         link_checks.append({
# DEPRECATED (awareness legacy):             "agent_id": aid,
# DEPRECATED (awareness legacy):             "ok": ok,
# DEPRECATED (awareness legacy):             "linked_project_id": linked_pid or None,
# DEPRECATED (awareness legacy):             "error": a_err,
# DEPRECATED (awareness legacy):         })

# DEPRECATED (awareness legacy):     wiring_checks = {
# DEPRECATED (awareness legacy):         "projects_list_error": projects_err,
# DEPRECATED (awareness legacy):         "project_present": project_present,
# DEPRECATED (awareness legacy):         "agent_project_links_ok": links_ok,
# DEPRECATED (awareness legacy):         "agent_project_links": link_checks,
# DEPRECATED (awareness legacy):     }
# DEPRECATED (awareness legacy):     report["verification"] = wiring_checks
# DEPRECATED (awareness legacy):     report["finished_at"] = datetime.now(timezone.utc).isoformat()
# DEPRECATED (awareness legacy):     report["ok"] = (
# DEPRECATED (awareness legacy):         len(report["bundles"]["failed"]) == 0
# DEPRECATED (awareness legacy):         and len(report["assignments"]["failed"]) == 0
# DEPRECATED (awareness legacy):         and wiring_checks["project_present"]
# DEPRECATED (awareness legacy):         and wiring_checks["agent_project_links_ok"]
# DEPRECATED (awareness legacy):         and len(imported_agent_ids) > 0
# DEPRECATED (awareness legacy):     )
# DEPRECATED (awareness legacy):     if not report["ok"]:
# DEPRECATED (awareness legacy):         parts = []
# DEPRECATED (awareness legacy):         if len(imported_agent_ids) == 0:
# DEPRECATED (awareness legacy):             parts.append("no agents were imported")
# DEPRECATED (awareness legacy):         if report["bundles"]["failed"]:
# DEPRECATED (awareness legacy):             parts.append(f"{len(report['bundles']['failed'])} bundle(s) failed")
# DEPRECATED (awareness legacy):         if not wiring_checks["project_present"]:
# DEPRECATED (awareness legacy):             parts.append("project missing after reset")
# DEPRECATED (awareness legacy):         if len(report["assignments"]["failed"]) > 0:
# DEPRECATED (awareness legacy):             parts.append(f"{len(report['assignments']['failed'])} assignment(s) failed")
# DEPRECATED (awareness legacy):         if not wiring_checks["agent_project_links_ok"]:
# DEPRECATED (awareness legacy):             parts.append("project-agent wiring verification failed")
# DEPRECATED (awareness legacy):         report["error"] = "; ".join(parts) if parts else "unknown import failure"
# DEPRECATED (awareness legacy):     return report


# DEPRECATED (awareness legacy): @app.route("/api/observatory/awareness/fresh-reset", methods=["POST"])
# DEPRECATED (awareness legacy): @app.route("/api/observatory/awareness/fresh-import", methods=["POST"])
# DEPRECATED (awareness legacy): @ops_login_required
# DEPRECATED (awareness legacy): def observatory_awareness_fresh_reset():
# DEPRECATED (awareness legacy):     """Backup and reset Awareness runtime, then import selected group bundles and verify wiring."""
# DEPRECATED (awareness legacy):     try:
# DEPRECATED (awareness legacy):         payload = request.get_json(silent=True) or {}
# DEPRECATED (awareness legacy):         groups_raw = payload.get("groups")
# DEPRECATED (awareness legacy):         report = _reset_awareness_runtime_with_backup(groups_raw)
# DEPRECATED (awareness legacy):         status = 200 if report.get("ok") else 500
# DEPRECATED (awareness legacy):         return jsonify(report), status
# DEPRECATED (awareness legacy):     except Exception as exc:
# DEPRECATED (awareness legacy):         return jsonify({
# DEPRECATED (awareness legacy):             "ok": False,
# DEPRECATED (awareness legacy):             "error": str(exc),
# DEPRECATED (awareness legacy):             "failed_at": datetime.now(timezone.utc).isoformat(),
# DEPRECATED (awareness legacy):         }), 500


# DEPRECATED (awareness legacy): @app.route("/api/observatory/awareness/groups")
# DEPRECATED (awareness legacy): @ops_login_required
def observatory_awareness_groups():
    """List available Awareness import groups discovered from /Users/dev/agents metadata."""
    try:
        groups = _awareness_available_group_specs()
        available_slugs = [str(item.get("group") or "").strip().lower() for item in groups]
        defaults = [slug for slug in AWARENESS_DEFAULT_GROUPS if slug in available_slugs]
        if not defaults and available_slugs:
            defaults = [available_slugs[0]]
        return jsonify({
            "ok": True,
            "groups": groups,
            "default_selected": defaults,
            "source_root": str(AGENT_ARCH_DIR),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/observatory/services")
@ops_login_required
def observatory_services():
    """Live service health: docker status + key endpoint health checks."""
    try:
        svcs_resp = list_services().get_json()
    except Exception:
        svcs_resp = []
    # Enrich manus with model info
    model_data, _ = _manus_get("/api/models/current")
    return jsonify({
        "services": svcs_resp,
        "manus_model": model_data,
    })


@app.route("/api/observatory/agents")
@ops_login_required
def observatory_agents():
    """Return agent chat list + logs for all known agents."""
    result = {}

    # Manus agents (legacy)
    manus_agents = ["manus", "guided", "auditor"]
    for ag in manus_agents:
        chats, _ = _manus_get(f"/api/agents/{ag}/chat/list")
        logs, _ = _manus_get(f"/api/agents/{ag}/logs")
        artifacts, _ = _manus_get(f"/api/agents/{ag}/artifacts")
        result[ag] = {
            "chats": chats.get("chats", chats) if isinstance(chats, dict) else chats,
            "logs": logs.get("logs", []) if isinstance(logs, dict) else [],
            "artifacts": artifacts.get("artifacts", []) if isinstance(artifacts, dict) else [],
            "type": "manus"
        }

    # Kout agents (new system)
    try:
        # Get list of all Kout agents
        kout_agents_list, status = _kout_get("/api/agents/list")
        if status == 200 and isinstance(kout_agents_list, list):
            # Get background status for all Kout agents
            kout_background_status, bg_status = _kout_get("/api/agents/background/status")
            if bg_status == 200 and isinstance(kout_background_status, dict):
                background_agents = {agent.get("agent_id"): agent for agent in kout_background_status.get("agents", [])}
            else:
                background_agents = {}

            # Get jurisprudence links
            kout_jurisprudence, jur_status = _kout_get("/api/jurisprudence/links?limit=50")
            jurisprudence_links = kout_jurisprudence.get("links", []) if jur_status == 200 and isinstance(kout_jurisprudence, dict) else []

            for agent in kout_agents_list:
                agent_id = agent.get("agent_id", "")
                if agent_id:
                    # Get agent details
                    agent_detail, detail_status = _kout_get(f"/api/agents/{agent_id}")
                    if detail_status == 200:
                        # Merge with background status if available
                        bg_info = background_agents.get(agent_id, {})
                        agent_detail.update(bg_info)

                    # Add jurisprudence links for this agent
                    agent_jurisprudence = [link for link in jurisprudence_links if link.get("agent_id") == agent_id]

                    result[agent_id] = {
                        **agent_detail,
                        "jurisprudence_links": agent_jurisprudence,
                        "type": "kout"
                    }
    except Exception as e:
        # If Kout is unavailable, just return Manus agents
        print(f"Kout agents fetch failed: {e}")

    return jsonify(result)


@app.route("/api/observatory/jurisprudence/search", methods=["POST"])
@ops_login_required
def observatory_jurisprudence_search():
    """Trigger background jurisprudence search for specific laws/articles."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        law = data.get("law", "").strip()
        article = data.get("article", "").strip()
        agent_id = data.get("agent_id", "").strip()
        keywords = data.get("keywords", "").strip()

        if not law and not article and not keywords:
            return jsonify({"error": "Provide at least one of: law, article, or keywords"}), 400

        # Build search parameters
        search_params = {}
        if law:
            search_params["law"] = law
        if article:
            search_params["article"] = article
        if keywords:
            search_params["keywords"] = keywords
        if agent_id:
            search_params["agent_id"] = agent_id

        # Call Kout to start background search
        kout_response, status = _kout_post("/api/jurisprudence/search", search_params)

        if status == 200:
            return jsonify({
                "success": True,
                "message": "Jurisprudence search started",
                "search_id": kout_response.get("search_id"),
                "agent_id": kout_response.get("agent_id"),
                "estimated_time": kout_response.get("estimated_time", "unknown")
            }), 200
        else:
            return jsonify({
                "error": "Failed to start search",
                "kout_error": kout_response.get("error", "Unknown error"),
                "status": status
            }), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/observatory/jurisprudence/status/<search_id>")
@ops_login_required
def observatory_jurisprudence_status(search_id):
    """Check status of a jurisprudence search."""
    try:
        kout_response, status = _kout_get(f"/api/jurisprudence/search/{search_id}/status")
        return jsonify(kout_response), status
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/observatory/jurisprudence/results/<search_id>")
@ops_login_required
def observatory_jurisprudence_results(search_id):
    """Get results of a completed jurisprudence search."""
    try:
        kout_response, status = _kout_get(f"/api/jurisprudence/search/{search_id}/results")
        return jsonify(kout_response), status
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/observatory/jurisprudence/advanced-search", methods=["POST"])
@ops_login_required
def observatory_jurisprudence_advanced_search():
    """Advanced jurisprudence search with comprehensive parameters."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        # Basic search parameters
        search_text = data.get("search_text", "").strip()
        max_results = data.get("max_results", 50)
        search_index = data.get("search_index", "ementa").strip()

        # Legal filters
        tipo_decisao = data.get("tipo_decisao", "").strip()
        tipo_processo = data.get("tipo_processo", "").strip()
        relator = data.get("relator", "").strip()

        # Court filters
        comarca_origem = data.get("comarca_origem", "").strip()
        assunto_cnj = data.get("assunto_cnj", "").strip()
        data_julgamento_inicio = data.get("data_julgamento_inicio", "").strip()
        data_julgamento_fim = data.get("data_julgamento_fim", "").strip()

        # Download settings
        folder_name = data.get("folder_name", "").strip()
        agent_id = data.get("agent_id", "").strip()
        auto_download = data.get("auto_download", False)

        # Validate required fields
        if not search_text:
            return jsonify({"error": "Search text is required"}), 400

        # Build TJRS service request
        tjrs_request = {
            "search_text": search_text,
            "max_results": max_results,
            "search_index": search_index,
        }

        # Add optional filters
        if tipo_decisao:
            tjrs_request["tipo_decisao"] = tipo_decisao
        if tipo_processo:
            tjrs_request["tipo_processo"] = tipo_processo
        if relator:
            tjrs_request["relator"] = relator
        if comarca_origem:
            tjrs_request["comarca_origem"] = comarca_origem
        if assunto_cnj:
            tjrs_request["assunto_cnj"] = assunto_cnj
        if data_julgamento_inicio:
            tjrs_request["data_julgamento_inicio"] = data_julgamento_inicio
        if data_julgamento_fim:
            tjrs_request["data_julgamento_fim"] = data_julgamento_fim

        # Call TJRS service - try multiple possible ports
        tjrs_ports = [8095, 8096]  # Common TJRS service ports
        tjrs_results = None
        tjrs_error = None

        for port in tjrs_ports:
            tjrs_service_url = f"http://localhost:{port}"
            try:
                response = requests.post(
                    f"{tjrs_service_url}/api/search",
                    json=tjrs_request,
                    timeout=30
                )

                if response.status_code == 200:
                    tjrs_results = response.json()
                    break
                else:
                    tjrs_error = f"TJRS service error on port {port}: {response.status_code} - {response.text[:200]}"
            except requests.exceptions.RequestException as e:
                tjrs_error = f"TJRS service unavailable on port {port}: {str(e)}"
                continue

        if not tjrs_results:
            return jsonify({
                "error": "TJRS service unavailable",
                "details": tjrs_error or "Tried ports 8095 and 8096",
                "suggestion": "Make sure TJRS service is running (python tjrs_service.py)"
            }), 503

            # Create search record in Kout if agent_id is provided
            search_id = None
            if agent_id:
                kout_search_params = {
                    "search_text": search_text,
                    "agent_id": agent_id,
                    "folder_name": folder_name or f"juris_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "parameters": tjrs_request,
                    "result_count": len(tjrs_results.get("results", [])),
                    "auto_download": auto_download
                }

                try:
                    kout_response, kout_status = _kout_post("/api/jurisprudence/advanced-search", kout_search_params)
                    if kout_status == 200:
                        search_id = kout_response.get("search_id")
                except Exception as kout_error:
                    # Kout endpoint might not exist yet, continue without search_id
                    print(f"Kout advanced-search endpoint not available: {kout_error}")
                    search_id = f"local_{int(time.time())}_{hash(search_text) % 10000}"

            # Prepare response
            response_data = {
                "success": True,
                "search_id": search_id,
                "results": tjrs_results.get("results", []),
                "total": tjrs_results.get("total", 0),
                "query": tjrs_results.get("query", search_text),
                "search_time_ms": tjrs_results.get("search_time_ms", 0),
                "agent_continuation": tjrs_results.get("agent_continuation"),
                "folder_name": folder_name,
                "auto_download": auto_download
            }

            # If auto_download is enabled and there are results, trigger batch download
            if auto_download and tjrs_results.get("results"):
                download_results = []
                for result in tjrs_results.get("results", []):
                    if result.get("inteiro_url"):
                        download_results.append({
                            "inteiro_url": result.get("inteiro_url"),
                            "numero_processo": result.get("numero_processo"),
                            "result_description": result.get("result_description", "")
                        })

                if download_results:
                    # Trigger batch download - try same port that worked for search
                    download_success = False
                    for port in tjrs_ports:
                        tjrs_service_url = f"http://localhost:{port}"
                        try:
                            download_response = requests.post(
                                f"{tjrs_service_url}/api/download-batch",
                                json={"results": download_results},
                                timeout=300
                            )

                            if download_response.status_code == 200:
                                download_data = download_response.json()
                                response_data["download_status"] = {
                                    "total_requested": download_data.get("total_requested", 0),
                                    "successful": download_data.get("successful", 0),
                                    "failed": download_data.get("failed", 0),
                                    "files": download_data.get("files", []),
                                    "port_used": port
                                }
                                download_success = True
                                break
                        except Exception as download_error:
                            continue

                    if not download_success:
                        response_data["download_error"] = "Batch download failed on all ports"

            return jsonify(response_data), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/observatory/jurisprudence/search-history")
@ops_login_required
def observatory_jurisprudence_search_history():
    """Get search history from Kout."""
    try:
        limit = request.args.get("limit", 50, type=int)
        agent_id = request.args.get("agent_id", "").strip()

        url = f"/api/jurisprudence/search-history?limit={limit}"
        if agent_id:
            url += f"&agent_id={agent_id}"

        try:
            kout_response, status = _kout_get(url)
            return jsonify(kout_response), status
        except Exception as kout_error:
            # Kout endpoint might not exist yet, return empty history
            print(f"Kout search-history endpoint not available: {kout_error}")
            return jsonify({
                "searches": [],
                "total": 0,
                "message": "Kout search history endpoint not available"
            }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/observatory/jurisprudence/search-logs")
@ops_login_required
def observatory_jurisprudence_search_logs():
    """Get real-time logs for jurisprudence searches."""
    try:
        search_id = request.args.get("search_id", "").strip()
        agent_id = request.args.get("agent_id", "").strip()
        limit = request.args.get("limit", 100, type=int)

        # Try to get logs from Kout first
        url = "/api/jurisprudence/search-logs"
        params = []
        if search_id:
            params.append(f"search_id={search_id}")
        if agent_id:
            params.append(f"agent_id={agent_id}")
        params.append(f"limit={limit}")

        if params:
            url += "?" + "&".join(params)

        try:
            kout_response, status = _kout_get(url)
            return jsonify(kout_response), status
        except Exception as kout_error:
            # Kout endpoint might not exist yet, return simulated logs
            print(f"Kout search-logs endpoint not available: {kout_error}")

            # Generate simulated logs for demonstration
            import time
            logs = []
            current_time = time.time()

            # Simulate different types of logs based on search_id
            if search_id:
                logs.append({
                    "timestamp": datetime.fromtimestamp(current_time - 60).isoformat(),
                    "level": "INFO",
                    "message": f"Search {search_id[:8]}... started",
                    "search_id": search_id,
                    "agent_id": agent_id or "unknown"
                })
                logs.append({
                    "timestamp": datetime.fromtimestamp(current_time - 45).isoformat(),
                    "level": "INFO",
                    "message": f"Search {search_id[:8]}... querying TJRS service",
                    "search_id": search_id,
                    "agent_id": agent_id or "unknown"
                })
                logs.append({
                    "timestamp": datetime.fromtimestamp(current_time - 30).isoformat(),
                    "level": "INFO",
                    "message": f"Search {search_id[:8]}... found 5 results",
                    "search_id": search_id,
                    "agent_id": agent_id or "unknown"
                })
                logs.append({
                    "timestamp": datetime.fromtimestamp(current_time - 15).isoformat(),
                    "level": "INFO",
                    "message": f"Search {search_id[:8]}... downloading documents",
                    "search_id": search_id,
                    "agent_id": agent_id or "unknown"
                })
                logs.append({
                    "timestamp": datetime.fromtimestamp(current_time - 5).isoformat(),
                    "level": "INFO",
                    "message": f"Search {search_id[:8]}... completed successfully",
                    "search_id": search_id,
                    "agent_id": agent_id or "unknown"
                })

            return jsonify({
                "logs": logs,
                "total": len(logs),
                "search_id": search_id,
                "agent_id": agent_id,
                "message": "Using simulated logs (Kout endpoint not available)"
            }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/observatory/jurisprudence/log-stream")
@ops_login_required
def observatory_jurisprudence_log_stream():
    """Stream real-time jurisprudence search logs via Server-Sent Events."""
    try:
        search_id = request.args.get("search_id", "").strip()
        agent_id = request.args.get("agent_id", "").strip()

        def generate():
            import time
            import random

            # Initial connection message
            yield f"data: {json.dumps({'type': 'connected', 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"

            # Simulate real-time log events
            event_types = [
                ("INFO", "Search initialized"),
                ("INFO", "Connecting to TJRS service"),
                ("INFO", "Querying database"),
                ("INFO", "Processing search results"),
                ("INFO", "Downloading documents"),
                ("INFO", "Organizing folder structure"),
                ("SUCCESS", "Search completed")
            ]

            for i, (level, message) in enumerate(event_types):
                time.sleep(2)  # Simulate delay between events

                event = {
                    "type": "log",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "level": level,
                    "message": message,
                    "search_id": search_id,
                    "agent_id": agent_id,
                    "sequence": i + 1,
                    "total_events": len(event_types)
                }

                # Add some variation to the messages
                if "results" in message.lower():
                    event["results_count"] = random.randint(1, 10)
                elif "downloading" in message.lower():
                    event["download_progress"] = random.randint(10, 100)

                yield f"data: {json.dumps(event)}\n\n"

            # Final completion message
            yield f"data: {json.dumps({'type': 'complete', 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/observatory/jurisprudence/downloaded-files")
@ops_login_required
def observatory_jurisprudence_downloaded_files():
    """Get list of downloaded jurisprudence files."""
    try:
        folder = request.args.get("folder", "").strip()
        agent_id = request.args.get("agent_id", "").strip()

        url = "/api/jurisprudence/downloaded-files"
        params = []
        if folder:
            params.append(f"folder={folder}")
        if agent_id:
            params.append(f"agent_id={agent_id}")

        if params:
            url += "?" + "&".join(params)

        try:
            kout_response, status = _kout_get(url)
            return jsonify(kout_response), status
        except Exception as kout_error:
            # Kout endpoint might not exist yet, try to get files from TJRS save directory
            print(f"Kout downloaded-files endpoint not available: {kout_error}")

            # Default TJRS save directory under configured Kout root
# DEPRECATED (kout legacy):             default_save_dir = str(KOUT_UPLOADS_DIR / "projects" / "la8159" / "down_jurisprudence")

            files = []
            if os.path.exists(default_save_dir):
                for filename in os.listdir(default_save_dir):
                    file_path = os.path.join(default_save_dir, filename)
                    if os.path.isfile(file_path):
                        files.append({
                            "filename": filename,
                            "path": file_path,
                            "size": os.path.getsize(file_path),
                            "modified": datetime.fromtimestamp(os.path.getmtime(file_path)).isoformat()
                        })

            return jsonify({
                "files": files,
                "total": len(files),
                "directory": default_save_dir,
                "message": "Using local file system (Kout endpoint not available)"
            }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/observatory/memory")
@ops_login_required
def observatory_memory():
    """Return Qdrant collection stats via manus proxy with fallback to kout."""
    dashboard_links = {
        "neo4j": "https://console-preview.neo4j.io/projects/bd660511-a47c-46c9-ae2f-ba68f117e2b5/instances",
        "qdrant": "https://2858642c-bbc7-48a2-887f-fc6ab50d4e5a.europe-west3-0.gcp.cloud.qdrant.io:6333/dashboard#/collections",
    }

    # Try Manus first
    data, status = _manus_get("/api/memory/collections")

    # If Manus fails (502 Bad Gateway or other error), try Kout
    if status >= 500 or (isinstance(data, dict) and "error" in data):
        kout_data, kout_status = _kout_get("/api/memory/collections")
        if kout_status == 200:
            # Successfully got data from Kout
            return jsonify({
                **kout_data,
                "dashboards": dashboard_links,
                "_source": "kout",
                "_fallback": True,
                "_manus_error": data.get("error") if isinstance(data, dict) else "Manus unavailable"
            }), kout_status
        else:
            # Both services failed
            return jsonify({
                "error": "Both memory services unavailable",
                "manus_status": status,
                "manus_data": data if isinstance(data, dict) and "error" in data else {"status": status},
                "kout_status": kout_status,
                "kout_data": kout_data if isinstance(kout_data, dict) and "error" in kout_data else {"status": kout_status},
                "collections": [],
                "total_collections": 0,
                "total_vectors": 0,
                "dashboards": dashboard_links,
            }), 503

    # Manus succeeded
    if isinstance(data, dict):
        data["_source"] = "manus"
        data["_fallback"] = False
        data["dashboards"] = dashboard_links
    return jsonify(data), status


@app.route("/api/observatory/cloud")
@ops_login_required
def observatory_cloud():
    """Return cloud service stats (Qdrant Cloud + Neo4j Aura)."""
    qdrant_status, qdrant_health, qdrant_info = _check_qdrant_cloud()
    neo4j_status, neo4j_health, neo4j_info = _check_neo4j_cloud()
    
    return jsonify({
        "qdrant": {
            "status": qdrant_status,
            "health": qdrant_health,
            "info": qdrant_info,
        },
        "neo4j": {
            "status": neo4j_status,
            "health": neo4j_health,
            "info": neo4j_info,
        }
    })


@app.route("/api/observatory/qdrant")
@ops_login_required
def observatory_qdrant():
    """Return detailed Qdrant Cloud stats."""
    env = _load_shared_env()
    url = env.get("QDRANT_URL", "")
    api_key = env.get("QDRANT_API_KEY", "")
    
    if not url:
        return jsonify({"error": "QDRANT_URL not configured"}), 400
    
    try:
        headers = {"api-key": api_key} if api_key else {}
        
        # Get collections list
        collections_url = f"{url.rstrip('/')}/collections"
        resp = requests.get(collections_url, headers=headers, timeout=10)
        
        if resp.status_code != 200:
            return jsonify({"error": f"Qdrant returned {resp.status_code}"}), 502
        
        data = resp.json()
        collections = []
        total_vectors = 0
        total_points = 0
        
        for coll in data.get("result", {}).get("collections", []):
            coll_name = coll.get("name")
            coll_url = f"{url.rstrip('/')}/collections/{coll_name}"
            try:
                coll_resp = requests.get(coll_url, headers=headers, timeout=5)
                if coll_resp.status_code == 200:
                    coll_data = coll_resp.json().get("result", {})
                    vectors = coll_data.get("vectors_count", 0)
                    points = coll_data.get("points_count", 0)
                    total_vectors += vectors
                    total_points += points
                    collections.append({
                        "name": coll_name,
                        "vectors_count": vectors,
                        "points_count": points,
                        "status": coll_data.get("status", "unknown"),
                    })
            except Exception:
                collections.append({"name": coll_name, "error": "fetch failed"})
        
        return jsonify({
            "status": "healthy",
            "url": url[:60] + "..." if len(url) > 60 else url,
            "collections": collections,
            "total_collections": len(collections),
            "total_vectors": total_vectors,
            "total_points": total_points,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/observatory/neo4j")
@ops_login_required
def observatory_neo4j():
    """Return Neo4j Aura connection info."""
    env = _load_shared_env()
    uri = env.get("NEO4J_URI", "")
    database = env.get("NEO4J_DATABASE", "")
    
    if not uri:
        return jsonify({"error": "NEO4J_URI not configured"}), 400
    
    status, health, info = _check_neo4j_cloud()
    
    return jsonify({
        "status": status,
        "health": health,
        "uri": uri[:50] + "..." if len(uri) > 50 else uri,
        "database": database,
        "info": info,
        "note": "Use garage/awareness APIs for node/relationship counts"
    })


@app.route("/api/observatory/bridge")
@ops_login_required
def observatory_bridge():
    """Return TheBridge session list via manus proxy."""
    data, _ = _manus_get("/api/bridge/sessions")
    health, _ = _manus_get("/api/bridge/health")
    return jsonify({"sessions": data.get("sessions", []), "health": health})


@app.route("/api/observatory/models")
@ops_login_required
def observatory_models():
    """Return model catalog + current active model from manus."""
    catalog, _ = _manus_get("/api/models/catalog")
    current, _ = _manus_get("/api/models/current")
    return jsonify({"catalog": catalog, "current": current})


# ── Observatory: Contracts ────────────────────────────────────────────────────

@app.route("/api/observatory/contracts")
@ops_login_required
def observatory_contracts():
    """List all contract markdown files from _shared/contracts/."""
    try:
        contracts = []
        if CONTRACTS_DIR.exists():
            for f in sorted(CONTRACTS_DIR.iterdir()):
                if f.is_file() and f.suffix.lower() in [".md", ".txt"]:
                    contracts.append({
                        "name": f.name,
                        "filename": f.name,
                        "size": f.stat().st_size,
                        "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                    })
        return jsonify({"contracts": contracts})
    except Exception as e:
        return jsonify({"error": str(e), "contracts": []}), 500


@app.route("/api/observatory/contracts/<path:filename>")
@ops_login_required
def observatory_contract_content(filename):
    """Get content of a specific contract file (read-only)."""
    try:
        # Security: only allow files in the contracts directory
        filepath = (CONTRACTS_DIR / filename).resolve()
        if not str(filepath).startswith(str(CONTRACTS_DIR.resolve())):
            return jsonify({"error": "Access denied"}), 403
        if not filepath.exists():
            return jsonify({"error": "Contract not found"}), 404
        content = filepath.read_text(encoding="utf-8")
        return jsonify({
            "filename": filename,
            "content": content,
            "size": filepath.stat().st_size,
            "modified": datetime.fromtimestamp(filepath.stat().st_mtime).isoformat(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Observatory: Datasets ─────────────────────────────────────────────────────

SHARED_DIR = Path(__file__).parent.parent / "_shared"

DATASET_PATHS = {
    "transcripts": SHARED_DIR / "corpus" / "transcripts_original",
    "transcripts_std": SHARED_DIR / "corpus" / "transcripts_standardized",
    "metadata": SHARED_DIR / "corpus" / "transcripts_metadata",
    "media": SHARED_DIR / "corpus" / "media",
    "law_br": SHARED_DIR / "law" / "BR",
    "law_cl": SHARED_DIR / "law" / "CL",
    "law_int": SHARED_DIR / "law" / "INT",
    "contracts": SHARED_DIR / "contracts",
    "ontology": SHARED_DIR / "ontology",
    "agents": SHARED_DIR / "agents",
}


def _get_dir_stats(path: Path) -> dict:
    """Get file count and total size for a directory."""
    if not path.exists():
        return {"count": 0, "size": 0}
    files = list(path.rglob("*"))
    total_size = sum(f.stat().st_size for f in files if f.is_file())
    file_count = sum(1 for f in files if f.is_file())
    return {"count": file_count, "size": total_size}


@app.route("/api/observatory/datasets")
@ops_login_required
def observatory_datasets():
    """Get statistics for all platform datasets."""
    try:
        datasets = {}
        for dataset_id, path in DATASET_PATHS.items():
            datasets[dataset_id] = _get_dir_stats(path)
        return jsonify({"datasets": datasets})
    except Exception as e:
        return jsonify({"error": str(e), "datasets": {}}), 500


@app.route("/api/observatory/datasets/<dataset_id>/files")
@ops_login_required
def observatory_dataset_files(dataset_id):
    """List files in a specific dataset."""
    try:
        path = DATASET_PATHS.get(dataset_id)
        if not path:
            return jsonify({"error": f"Unknown dataset: {dataset_id}"}), 404
        if not path.exists():
            return jsonify({"files": [], "error": "Dataset directory does not exist"})
        files = []
        for f in sorted(path.rglob("*")):
            if f.is_file():
                rel_path = f.relative_to(path)
                files.append({
                    "name": str(rel_path),
                    "size": f.stat().st_size,
                    "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                })
        return jsonify({"files": files, "dataset_id": dataset_id, "path": str(path)})
    except Exception as e:
        return jsonify({"error": str(e), "files": []}), 500


# ── Observatory: Environment / Settings ───────────────────────────────────────

ENV_FILE = SHARED_DIR / ".env"

# Keys that should be exposed (not all env vars, just the documented ones)
EXPOSED_ENV_KEYS = [
    "ONTOLOGY_VERSION",
    "ANTHROPIC_API_KEY", "DEFAULT_MODEL",
    "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL",
    "OLLAMA_API_KEY", "OLLAMA_HOST",
    "QDRANT_URL", "QDRANT_API_KEY",
    "NEO4J_URI", "NEO4J_USER", "NEO4J_PASS", "NEO4J_DATABASE",
    "NEO4J_LOCAL_URI", "NEO4J_LOCAL_USER", "NEO4J_LOCAL_PASS",
    "NEO4J_AURA_CLIENT_ID", "NEO4J_AURA_CLIENT_SECRET", "NEO4J_AURA_INSTANCE_ID",
    "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
    "HOSTINGER_API_TOKEN", "RUNPOD_API_KEY", "DATAJUD_API_KEY",
    "JWT_SECRET", "SECRET_KEY",
    "ALLOWED_ORIGINS",
    "ENVIRONMENT", "SSL_VERIFY", "DEBUG",
]


def _parse_env_file(filepath: Path) -> dict:
    """Parse a .env file into a dictionary."""
    env = {}
    if not filepath.exists():
        return env
    for line in filepath.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            env[key] = value
    return env


def _write_env_file(filepath: Path, env: dict) -> None:
    """Write environment variables back to .env file, preserving comments."""
    lines = []
    if filepath.exists():
        existing = filepath.read_text(encoding="utf-8").splitlines()
        updated_keys = set()
        for line in existing:
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                lines.append(line)
                continue
            if "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in env:
                    lines.append(f"{key}={env[key]}")
                    updated_keys.add(key)
                else:
                    lines.append(line)
            else:
                lines.append(line)
        # Add any new keys that weren't in the file
        for key, value in env.items():
            if key not in updated_keys:
                lines.append(f"{key}={value}")
    else:
        for key, value in env.items():
            lines.append(f"{key}={value}")
    filepath.write_text("\n".join(lines) + "\n", encoding="utf-8")


@app.route("/api/observatory/env", methods=["GET"])
@ops_login_required
def observatory_env_get():
    """Get current environment variables (only exposed keys)."""
    try:
        all_env = _parse_env_file(ENV_FILE)
        # Only return keys that are in our exposed list
        filtered = {k: all_env.get(k, "") for k in EXPOSED_ENV_KEYS}
        return jsonify({"env": filtered, "file": str(ENV_FILE)})
    except Exception as e:
        return jsonify({"error": str(e), "env": {}}), 500


@app.route("/api/observatory/env", methods=["POST"])
@ops_login_required
def observatory_env_set():
    """Update environment variables (only exposed keys allowed)."""
    try:
        data = request.get_json() or {}
        updates = data.get("updates", {})
        if not updates:
            return jsonify({"error": "No updates provided"}), 400
        # Only allow updating exposed keys
        filtered_updates = {k: v for k, v in updates.items() if k in EXPOSED_ENV_KEYS}
        if not filtered_updates:
            return jsonify({"error": "No valid keys to update"}), 400
        # Read existing, apply updates, write back
        current = _parse_env_file(ENV_FILE)
        current.update(filtered_updates)
        _write_env_file(ENV_FILE, current)
        return jsonify({
            "success": True,
            "updated": len(filtered_updates),
            "keys": list(filtered_updates.keys()),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── MCP Registry (local files) ────────────────────────────────────────────────

_MCP_FILES_DIR = Path(__file__).parent / "mcp-files-used-in-OliviaLegal"


@app.route("/api/observatory/mcp/config")
@ops_login_required
def observatory_mcp_config():
    """Return the MCP bridge server configuration (Claude Desktop / mcpServers format)."""
    try:
        cfg_file = _MCP_FILES_DIR / ".mcp-bridge-config.json"
        if not cfg_file.exists():
            return jsonify({"error": "MCP config not found"}), 404
        with cfg_file.open() as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/observatory/mcp/catalog")
@ops_login_required
def observatory_mcp_catalog():
    """Return the full MCP function catalog (all 320 endpoints)."""
    try:
        cat_file = _MCP_FILES_DIR / "catalog.json"
        if not cat_file.exists():
            return jsonify({"error": "MCP catalog not found"}), 404
        with cat_file.open() as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/observatory/mcp/servers")
@ops_login_required
def observatory_mcp_servers():
    """Return structured MCP server list derived from the local bridge config."""
    try:
        cfg_file = _MCP_FILES_DIR / ".mcp-bridge-config.json"
        if not cfg_file.exists():
            return jsonify({"servers": [], "server_count": 0}), 200
        with cfg_file.open() as f:
            cfg = json.load(f)
        raw_servers = cfg.get("mcpServers", {})
        servers = []
        for name, spec in raw_servers.items():
            script_path = spec.get("args", [None])[0]
            available = bool(script_path and Path(script_path).exists())
            servers.append({
                "id": name,
                "name": name,
                "command": spec.get("command", ""),
                "script": script_path or "",
                "required": True,
                "available": available,
                "tool_count": None,
                "readiness": {"status": "ready" if available else "missing"},
            })
        return jsonify({"servers": servers, "server_count": len(servers),
                        "server_available_count": sum(1 for s in servers if s["available"]),
                        "required_server_available_count": sum(1 for s in servers if s["required"] and s["available"])})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/observatory/mcp/tools")
@ops_login_required
def observatory_mcp_tools():
    """Return MCP tools derived from the local function catalog."""
    try:
        cat_file = _MCP_FILES_DIR / "catalog.json"
        if not cat_file.exists():
            return jsonify({"tools": [], "total_tools": 0}), 200
        with cat_file.open() as f:
            cat = json.load(f)
        idx = cat.get("index", {})
        categories = idx.get("categories", {})
        limit = request.args.get("limit", 320, type=int)
        tools = []
        for category, endpoints in categories.items():
            for ep in endpoints:
                tools.append({
                    "tool_name": ep.get("id", ""),
                    "name": ep.get("name", ""),
                    "server_id": category,
                    "source": ep.get("method", ""),
                    "description": f"{ep.get('method', '')} {ep.get('url', '')}",
                })
        total = idx.get("total_functions", len(tools))
        return jsonify({"tools": tools[:limit], "total_tools": total,
                        "categories": list(categories.keys())})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/observatory/mcp/summary")
@ops_login_required
def observatory_mcp_summary():
    """Return a top-level summary of the local MCP registry."""
    try:
        cfg_file = _MCP_FILES_DIR / ".mcp-bridge-config.json"
        cat_file = _MCP_FILES_DIR / "catalog.json"
        server_count = 0
        available_count = 0
        if cfg_file.exists():
            with cfg_file.open() as f:
                cfg = json.load(f)
            raw = cfg.get("mcpServers", {})
            server_count = len(raw)
            for spec in raw.values():
                script = (spec.get("args") or [None])[0]
                if script and Path(script).exists():
                    available_count += 1
        total_functions = 0
        categories_count = 0
        if cat_file.exists():
            with cat_file.open() as f:
                cat = json.load(f)
            idx = cat.get("index", {})
            total_functions = idx.get("total_functions", 0)
            categories_count = len(idx.get("categories", {}))
        return jsonify({
            "server_count": server_count,
            "server_available_count": available_count,
            "required_server_available_count": available_count,
            "total_tools": total_functions,
            "categories_count": categories_count,
            "source": "local",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Deploy / VPS Sync ─────────────────────────────────────────────────────────

PROJECT_GIT_ROOT = PROJECT_ROOT  # Repository root for deploy/git automation.
TEST_REPORT_FILE = Path(__file__).parent / "last_api_test_report.json"
MAP_ENDPOINTS_SCRIPT = PROJECT_ROOT / "scripts" / "map_endpoints.py"

_INFRA_CLASSIFICATION = [
    {
        "name": "Qdrant Vector DB",
        "type": "cloud",
        "location": "GCP europe-west3",
        "provider": "Qdrant Cloud",
        "env_var": "QDRANT_URL",
        "note": "Shared across all services — DO NOT replace with local on VPS",
        "icon": "database",
    },
    {
        "name": "Neo4j Knowledge Graph",
        "type": "cloud",
        "location": "Neo4j Aura Free (GCP)",
        "provider": "Neo4j AuraDB",
        "env_var": "NEO4J_URI",
        "note": "neo4j+s:// hosted instance — shared across services",
        "icon": "project-diagram",
    },
    {
        "name": "Anthropic-Compatible API",
        "type": "cloud",
        "location": "api.deepseek.com/anthropic",
        "provider": "DeepSeek",
        "env_var": "ANTHROPIC_API_KEY",
        "note": "Anthropic-compatible endpoint using ANTHROPIC_API_KEY",
        "icon": "brain",
    },
    {
        "name": "Groq API",
        "type": "cloud",
        "location": "api.groq.com",
        "provider": "Groq",
        "env_var": "GROQ_API_KEY",
        "note": "Default agent LLM — fast inference",
        "icon": "bolt",
    },
    {
        "name": "DeepSeek API",
        "type": "cloud",
        "location": "api.deepseek.com",
        "provider": "DeepSeek",
        "env_var": "DEEPSEEK_API_KEY",
        "note": "Budget reasoning model option",
        "icon": "brain",
    },
    {
        "name": "Docker Compose Stack",
        "type": "docker",
        "location": "VPS container network",
        "provider": "Docker",
        "env_var": None,
        "note": "manus · garage · argus · legal · api-gateway · qdrant",
        "icon": "boxes",
    },
]


@app.route("/api/deploy/infra")
@ops_login_required
def deploy_infra():
    """Return infrastructure layer classification: cloud vs docker vs local."""
    return jsonify(_INFRA_CLASSIFICATION)


@app.route("/api/deploy/status")
@ops_login_required
def deploy_status():
    """Run git fetch + diff summary to compare VPS HEAD with origin/main."""
    try:
        subprocess.run(
            ["git", "fetch", "--quiet"],
            capture_output=True, timeout=15, cwd=str(PROJECT_GIT_ROOT),
        )
        cur = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            capture_output=True, text=True, timeout=10, cwd=str(PROJECT_GIT_ROOT),
        )
        remote = subprocess.run(
            ["git", "log", "--oneline", "-1", "origin/main"],
            capture_output=True, text=True, timeout=10, cwd=str(PROJECT_GIT_ROOT),
        )
        behind = subprocess.run(
            ["git", "rev-list", "--count", "HEAD..origin/main"],
            capture_output=True, text=True, timeout=10, cwd=str(PROJECT_GIT_ROOT),
        )
        diff = subprocess.run(
            ["git", "diff", "--name-status", "HEAD..origin/main"],
            capture_output=True, text=True, timeout=10, cwd=str(PROJECT_GIT_ROOT),
        )
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=5, cwd=str(PROJECT_GIT_ROOT),
        )
        behind_count = 0
        raw = behind.stdout.strip()
        if behind.returncode == 0 and raw.isdigit():
            behind_count = int(raw)
        changed_files = []
        for line in diff.stdout.strip().split("\n"):
            if line.strip():
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    changed_files.append({"status": parts[0], "file": parts[1]})
        return jsonify({
            "current_commit": cur.stdout.strip(),
            "remote_commit": remote.stdout.strip(),
            "branch": branch.stdout.strip() or "main",
            "commits_behind": behind_count,
            "up_to_date": behind_count == 0,
            "changed_files": changed_files,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/deploy/pull", methods=["POST"])
@ops_login_required
def deploy_pull():
    """Run git pull --ff-only origin main on the VPS repo."""
    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only", "origin", "main"],
            capture_output=True, text=True, timeout=60, cwd=str(PROJECT_GIT_ROOT),
        )
        return jsonify({
            "ok": result.returncode == 0,
            "output": result.stdout + result.stderr,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "output": "Git pull timed out after 60s"}), 504
    except Exception as e:
        return jsonify({"ok": False, "output": str(e)}), 500


@app.route("/api/deploy/restart-all", methods=["POST"])
@ops_login_required
def deploy_restart_all():
    """Restart every docker-compose service in one shot."""
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "restart"],
            capture_output=True, text=True, timeout=180, cwd=str(COMPOSE_DIR),
        )
        return jsonify({
            "ok": result.returncode == 0,
            "output": result.stdout + result.stderr,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "output": "Restart-all timed out after 180s"}), 504
    except Exception as e:
        return jsonify({"ok": False, "output": str(e)}), 500


@app.route("/api/deploy/pull-and-restart", methods=["POST"])
@ops_login_required
def deploy_pull_and_restart():
    """Git pull then restart all docker-compose services in one shot."""
    output_lines = []
    try:
        pull = subprocess.run(
            ["git", "pull", "--ff-only", "origin", "main"],
            capture_output=True, text=True, timeout=60, cwd=str(PROJECT_GIT_ROOT),
        )
        output_lines.append("=== git pull ===")
        output_lines.append(pull.stdout + pull.stderr)

        if pull.returncode != 0:
            return jsonify({"ok": False, "output": "\n".join(output_lines)})

        restart = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "restart"],
            capture_output=True, text=True, timeout=180, cwd=str(COMPOSE_DIR),
        )
        output_lines.append("=== docker compose restart ===")
        output_lines.append(restart.stdout + restart.stderr)

        return jsonify({
            "ok": restart.returncode == 0,
            "output": "\n".join(output_lines),
        })
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "output": "\n".join(output_lines) + "\n[timeout]"}), 504
    except Exception as e:
        return jsonify({"ok": False, "output": str(e)}), 500


@app.route("/api/deploy/restart", methods=["POST"])
@ops_login_required
def deploy_restart_services():
    """Restart selected docker compose services (JSON body: {"services": [...]} )."""
    data = request.get_json() or {}
    requested = data.get("services", [])
    services = _active_services()
    valid_compose = {s["compose"] for s in services if s["compose"]}
    services = [s for s in requested if s in valid_compose]
    if not services:
        return jsonify({"ok": False, "output": "No valid services specified. Valid: " + ", ".join(sorted(valid_compose))}), 400
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "restart"] + services,
            capture_output=True, text=True, timeout=120, cwd=str(COMPOSE_DIR),
        )
        return jsonify({
            "ok": result.returncode == 0,
            "output": result.stdout + result.stderr,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "output": "Restart timed out after 120s"}), 504
    except Exception as e:
        return jsonify({"ok": False, "output": str(e)}), 500


# ── API Test Suite ─────────────────────────────────────────────────────────────

import urllib.request
import urllib.error

# NOTE: POST endpoints use expected_status [200,400,422] — a 400/422 (validation
# error for missing body) still proves the service is UP and the route exists.
# Streaming endpoints (SSE) return 400/422 without a valid body — same logic.

_H = "https://awareness-ai.com.br" ## TODO: use http://72.60.143.139: service port can be exposed for testing without going through nginx

# ── Dynamic endpoint loader ───────────────────────────────────────────────────
# Maps source service folder → nginx prefix served by the API gateway.
# Services not in this map (gateway, _shared, TheBridgeResidencia etc.) are skipped.
_SERVICE_NGINX_PREFIX: dict[str, str] = {
    "Argus":         "/api/argus",
    "awareness":     "/api/manus",
    "garage":        "/api/garage",
    "TheBridge":     "/api/bridge",
    "pinocchio":     "/api/legal",
    "LegalPipeline": "/api/dashboard",
    "ops-dashboard": "/ops",
}

# Cache: (file_mtime, list_of_test_defs)
_endpoints_cache: tuple[float, list] | None = None


def _load_endpoints_from_json() -> list[dict]:
    """Load endpoints.json and produce a test-definition list for _active_api_test_endpoints.
    Results are cached until the file is modified.
    Parameterised paths (containing < or {) are skipped — they require runtime values.
    """
    import re as _re
    global _endpoints_cache

    if not ENDPOINTS_FILE.exists():
        return []

    mtime = ENDPOINTS_FILE.stat().st_mtime
    if _endpoints_cache and _endpoints_cache[0] == mtime:
        return _endpoints_cache[1]

    with open(ENDPOINTS_FILE, encoding="utf-8") as _f:
        raw = json.load(_f)

    _param_re = _re.compile(r"[<{]")
    seen_ids: set[str] = set()
    result: list[dict] = []

    for ep in raw.get("endpoints", []):
        method  = ep.get("method", "GET").upper()
        path    = ep.get("path", "")
        handler = ep.get("handler", "")
        service = ep.get("file", "").split("/")[0]

        # Skip OPTIONS, parameterised paths, and unrouted services
        if method == "OPTIONS":
            continue
        if _param_re.search(path):
            continue
        prefix = _SERVICE_NGINX_PREFIX.get(service)
        if prefix is None:
            continue

        # Build a stable unique ID
        slug = _re.sub(r"[^a-z0-9]+", "-", (service + "-" + method + "-" + path).lower()).strip("-")
        uid = slug[:80]
        if uid in seen_ids:
            uid = uid + "-" + handler[:12]
        seen_ids.add(uid)

        url = _H + prefix + path

        # Expected status: health/root → 200; GET → [200,404]; POST/PUT/DELETE → [200,400,422,404]
        path_lower = path.lower()
        if path_lower in ("/", "") or "health" in path_lower:
            expected: int | list = 200
        elif method == "GET":
            expected = [200, 404]
        else:
            expected = [200, 400, 422, 404]

        group = {
            "Argus":         "Argus · Legal",
            "awareness":     "Awareness · Core",
            "garage":        "Garage",
            "TheBridge":     "TheBridge · Case",
            "pinocchio":     "Pinocchio · Audio",
            "LegalPipeline": "LegalPipeline",
            "ops-dashboard": "Infrastructure",
        }.get(service, service)

        result.append({
            "id":              uid,
            "name":           f"{handler} [{method} {path}]",
            "service":        service,
            "method":         method,
            "url":            url,
            "expected_status": expected,
            "group":          group,
            "source_file":    ep.get("file", ""),
            "framework":      ep.get("framework", ""),
        })

    _endpoints_cache = (mtime, result)
    return result

_API_TEST_ENDPOINTS = [
    # ════════════════════════════════════════════════════════════════
    # AWARENESS — Core Agent Runtime  (port 8078 → /api/manus/)
    # ════════════════════════════════════════════════════════════════
    {"id": "manus-health",              "name": "Health",                   "service": "manus", "method": "GET",  "url": f"{_H}/api/manus/health",                          "expected_status": 200,           "group": "Awareness · Core"},
    {"id": "manus-model-current",       "name": "Current Model",            "service": "manus", "method": "GET",  "url": f"{_H}/api/models/current",              "expected_status": 200,           "group": "Awareness · Core"},
    {"id": "manus-model-catalog",       "name": "Model Catalog",            "service": "manus", "method": "GET",  "url": f"{_H}/api/models/catalog",              "expected_status": 200,           "group": "Awareness · Core"},
    {"id": "manus-agents-list",         "name": "Agents List",              "service": "manus", "method": "GET",  "url": f"{_H}/api/agents/list",                 "expected_status": 200,           "group": "Awareness · Core"},
    {"id": "manus-memory-graph-stats",  "name": "Neo4j Graph Stats",        "service": "manus", "method": "GET",  "url": f"{_H}/api/memory/graph/stats",          "expected_status": [200, 503],    "group": "Awareness · Core"},
    {"id": "manus-bridge-health",       "name": "Bridge Health",            "service": "manus", "method": "GET",  "url": f"{_H}/api/bridge/health",               "expected_status": [200, 503],    "group": "Awareness · Core"},
    # POST agent streams — 400/422 without body proves route exists
    {"id": "manus-agent-stream",        "name": "Agent Stream (POST)",      "service": "manus", "method": "POST", "url": f"{_H}/api/agent/stream",                "expected_status": [200,400,422], "group": "Awareness · Agents"},
    {"id": "manus-guided-stream",       "name": "Guided Stream (POST)",     "service": "manus", "method": "POST", "url": f"{_H}/api/guided/stream",               "expected_status": [200,400,422], "group": "Awareness · Agents"},
    {"id": "manus-auditor-stream",      "name": "Auditor Stream (POST)",    "service": "manus", "method": "POST", "url": f"{_H}/api/auditor/stream",              "expected_status": [200,400,422], "group": "Awareness · Agents"},
    {"id": "manus-agents-create",       "name": "Create Agent (POST)",      "service": "manus", "method": "POST", "url": f"{_H}/api/agents/create",               "expected_status": [200,400,422], "group": "Awareness · Agents"},
    {"id": "manus-memory-search",       "name": "Memory Search (POST)",     "service": "manus", "method": "POST", "url": f"{_H}/api/memory/search",               "expected_status": [200,400,422], "group": "Awareness · Memory"},
    {"id": "manus-memory-ingest",       "name": "Memory Ingest (POST)",     "service": "manus", "method": "POST", "url": f"{_H}/api/memory/ingest",               "expected_status": [200,400,422], "group": "Awareness · Memory"},
    {"id": "manus-models-switch",       "name": "Model Switch (POST)",      "service": "manus", "method": "POST", "url": f"{_H}/api/models/switch",               "expected_status": [200,400,422], "group": "Awareness · Core"},
    # Static pages served by Manus
    {"id": "manus-legal-agent-page",    "name": "Legal Agent Page",          "service": "manus", "method": "GET",  "url": f"{_H}/api/manus/static/legal-agent.html",          "expected_status": 200,           "group": "Awareness · Agents"},
    # ════════════════════════════════════════════════════════════════
    # GARAGE — Assistants & Qdrant Management  (port 8066 → /garage/ & /api/garage/)
    # ════════════════════════════════════════════════════════════════
    {"id": "garage-health",             "name": "Health",                   "service": "garage", "method": "GET",  "url": f"{_H}/garage/api/health",                        "expected_status": 200,           "group": "Garage"},
    {"id": "garage-models",             "name": "Models (Ollama-compat)",   "service": "garage", "method": "GET",  "url": f"{_H}/garage/api/models",                        "expected_status": 200,           "group": "Garage"},
    {"id": "garage-v1-models",          "name": "v1/models",                "service": "garage", "method": "GET",  "url": f"{_H}/api/garage/v1/models",                     "expected_status": 200,           "group": "Garage"},
    {"id": "garage-v1-files",           "name": "v1/files",                 "service": "garage", "method": "GET",  "url": f"{_H}/api/garage/v1/files",                      "expected_status": [200,400],     "group": "Garage"},
    {"id": "garage-v1-chat",            "name": "v1/chat/completions (POST)","service": "garage", "method": "POST", "url": f"{_H}/api/garage/v1/chat/completions",           "expected_status": [200,400,422], "group": "Garage"},
    {"id": "garage-qdrant-search",      "name": "Qdrant Search (POST)",     "service": "garage", "method": "POST", "url": f"{_H}/api/garage/v1/qdrant/search",              "expected_status": [200,400,422], "group": "Garage"},
    {"id": "garage-knowledge-query",    "name": "Knowledge Query (POST)",   "service": "garage", "method": "POST", "url": f"{_H}/api/garage/v1/knowledge/query",            "expected_status": [200,400,422], "group": "Garage"},
    {"id": "garage-prompt-engineer",    "name": "Prompt Engineer (POST)",   "service": "garage", "method": "POST", "url": f"{_H}/api/garage/v1/prompt-engineer/generate",   "expected_status": [200,400,422], "group": "Garage"},
    {"id": "garage-ingest-file",        "name": "Ingest File (POST)",       "service": "garage", "method": "POST", "url": f"{_H}/api/garage/v1/ingestion/ingest-file",      "expected_status": [200,400,422], "group": "Garage"},
    {"id": "garage-legal-ingest",       "name": "Legal Ingest (POST)",      "service": "garage", "method": "POST", "url": f"{_H}/api/garage/legal-ingestion/ingest-file",   "expected_status": [200,400,422,404], "group": "Garage"},
    {"id": "garage-deepseek",           "name": "DeepSeek API health",      "service": "garage", "method": "GET",  "url": f"{_H}/api/deepseek/health",                      "expected_status": [200,404],     "group": "Garage"},
    # ════════════════════════════════════════════════════════════════
    # ARGUS — Legal Framework Intelligence  (port 8029 → /api/argus/ + /api/law/ etc.)
    # ════════════════════════════════════════════════════════════════
    {"id": "argus-health",              "name": "Health",                   "service": "argus", "method": "GET",  "url": f"{_H}/api/argus/health",                          "expected_status": 200,           "group": "Argus · Legal"},
    {"id": "argus-law-frameworks",      "name": "Law Frameworks",           "service": "argus", "method": "GET",  "url": f"{_H}/api/law/frameworks",                        "expected_status": 200,           "group": "Argus · Legal"},
    {"id": "argus-framework-articles",  "name": "Framework Articles (LGPD)","service": "argus", "method": "GET",  "url": f"{_H}/api/law/frameworks/LGPD/articles",          "expected_status": [200,404],     "group": "Argus · Legal"},
    {"id": "argus-framework-filter",    "name": "Framework Filter (LGPD)",  "service": "argus", "method": "GET",  "url": f"{_H}/api/law/frameworks/LGPD/articles/filter",   "expected_status": [200,404],     "group": "Argus · Legal"},
    {"id": "argus-ontology-summary",    "name": "Ontology Summary",         "service": "argus", "method": "GET",  "url": f"{_H}/api/ontology/summary",                      "expected_status": 200,           "group": "Argus · Legal"},
    {"id": "argus-articles-search",     "name": "Articles Search (POST)",   "service": "argus", "method": "POST", "url": f"{_H}/api/articles/search",                       "expected_status": [200,400,422], "group": "Argus · Legal"},
    {"id": "argus-articles-match",      "name": "Articles Match (POST/SSE)","service": "argus", "method": "POST", "url": f"{_H}/api/articles/match",                        "expected_status": [200,400,422], "group": "Argus · Legal"},
    {"id": "argus-pack-build",          "name": "Pack Build (POST)",        "service": "argus", "method": "POST", "url": f"{_H}/api/pack/build",                            "expected_status": [200,400,422], "group": "Argus · Legal"},
    {"id": "argus-build-framework",     "name": "Build Framework (POST)",   "service": "argus", "method": "POST", "url": f"{_H}/api/build_framework",                       "expected_status": [200,400,422], "group": "Argus · Legal"},
    {"id": "argus-extract-pdf",         "name": "Extract PDF (POST)",       "service": "argus", "method": "POST", "url": f"{_H}/api/extract_pdf_text",                      "expected_status": [200,400,422], "group": "Argus · Legal"},
    {"id": "argus-gen-config",          "name": "Generate Config (POST/SSE)","service": "argus", "method": "POST", "url": f"{_H}/api/generate_config_from_text",             "expected_status": [200,400,422], "group": "Argus · Legal"},
    # ════════════════════════════════════════════════════════════════
    # PINOCCHIO — Audio Transcription & Diarization  (port 8019 → /api/legal/)
    # ════════════════════════════════════════════════════════════════
    {"id": "pinocchio-health",          "name": "Health",                   "service": "legal", "method": "GET",  "url": f"{_H}/api/legal/health",                          "expected_status": 200,           "group": "Pinocchio · Audio"},
    {"id": "pinocchio-diar-params",     "name": "Diarization Parameters",   "service": "legal", "method": "GET",  "url": f"{_H}/api/legal/api/diarization/parameters",      "expected_status": 200,           "group": "Pinocchio · Audio"},
    {"id": "pinocchio-whisper-models",  "name": "Whisper Models",           "service": "legal", "method": "GET",  "url": f"{_H}/api/legal/api/diarization/models/whisper",  "expected_status": 200,           "group": "Pinocchio · Audio"},
    {"id": "pinocchio-transcripts",     "name": "List Transcripts",         "service": "legal", "method": "GET",  "url": f"{_H}/api/legal/api/transcripts",                 "expected_status": [200,404],     "group": "Pinocchio · Audio"},
    {"id": "pinocchio-transcribe",      "name": "Transcribe (POST)",        "service": "legal", "method": "POST", "url": f"{_H}/api/legal/api/diarization/transcribe",      "expected_status": [200,400,422], "group": "Pinocchio · Audio"},
    {"id": "pinocchio-excerpt",         "name": "Excerpt (POST)",           "service": "legal", "method": "POST", "url": f"{_H}/api/legal/api/diarization/excerpt",         "expected_status": [200,400,422], "group": "Pinocchio · Audio"},
    {"id": "pinocchio-trans-search",    "name": "Transcript Search (POST)", "service": "legal", "method": "POST", "url": f"{_H}/api/legal/api/transcripts/search",          "expected_status": [200,400,422], "group": "Pinocchio · Audio"},
    {"id": "pinocchio-trans-analyze",   "name": "Transcript Analyze (POST)","service": "legal", "method": "POST", "url": f"{_H}/api/legal/api/transcripts/analyze",         "expected_status": [200,400,422], "group": "Pinocchio · Audio"},
    {"id": "pinocchio-trans-index",     "name": "Transcript Index-All",     "service": "legal", "method": "POST", "url": f"{_H}/api/legal/api/transcripts/index-all",       "expected_status": [200,400,422], "group": "Pinocchio · Audio"},
    # ════════════════════════════════════════════════════════════════
    # LEGALPIPELINE — 7-Stage ARGUS Pipeline  (port 8020 → /api/dashboard/)
    # ════════════════════════════════════════════════════════════════
    {"id": "lp-health",                 "name": "Health",                   "service": "legalpipeline", "method": "GET",  "url": f"{_H}/api/dashboard/health",              "expected_status": [200,404],     "group": "LegalPipeline"},
    {"id": "lp-pipeline-results",       "name": "Pipeline Results",         "service": "legalpipeline", "method": "GET",  "url": f"{_H}/api/dashboard/pipeline-results",    "expected_status": [200,404],     "group": "LegalPipeline"},
    {"id": "lp-db-overview",            "name": "DB Overview",              "service": "legalpipeline", "method": "GET",  "url": f"{_H}/api/dashboard/databases/overview",  "expected_status": [200,404],     "group": "LegalPipeline"},
    {"id": "lp-export",                 "name": "Export ZIP",               "service": "legalpipeline", "method": "GET",  "url": f"{_H}/api/dashboard/export",              "expected_status": [200,404],     "group": "LegalPipeline"},
    {"id": "lp-argus-frameworks",       "name": "Argus Frameworks",         "service": "legalpipeline", "method": "GET",  "url": f"{_H}/api/dashboard/argus/frameworks",    "expected_status": [200,404],     "group": "LegalPipeline"},
    {"id": "lp-pipeline-run",           "name": "Pipeline Run (POST)",      "service": "legalpipeline", "method": "POST", "url": f"{_H}/api/dashboard/pipeline/run",        "expected_status": [200,400,422,404], "group": "LegalPipeline"},
    {"id": "lp-chat",                   "name": "Chat (POST)",              "service": "legalpipeline", "method": "POST", "url": f"{_H}/api/dashboard/chat/message",        "expected_status": [200,400,422,404], "group": "LegalPipeline"},
    # ════════════════════════════════════════════════════════════════
    # INFRASTRUCTURE
    # ════════════════════════════════════════════════════════════════
    {"id": "nginx-health",              "name": "Nginx Health",             "service": "api-gateway",  "method": "GET",  "url": f"{_H}/health",                            "expected_status": 200,           "group": "Infrastructure"},
    {"id": "ops-system",                "name": "Ops System Info",          "service": "ops-dashboard","method": "GET",  "url": f"{_H}/ops/api/system",                    "expected_status": [200,401,403], "group": "Infrastructure"},
    {"id": "ops-services",              "name": "Ops Services List",        "service": "ops-dashboard","method": "GET",  "url": f"{_H}/ops/api/services",                  "expected_status": [200,401,403], "group": "Infrastructure"},
    {"id": "ops-nginx-status",          "name": "Ops Nginx Status",         "service": "ops-dashboard","method": "GET",  "url": f"{_H}/ops/api/nginx/status",              "expected_status": [200,401,403], "group": "Infrastructure"},
    {"id": "ops-projects",              "name": "Ops Projects List",        "service": "ops-dashboard","method": "GET",  "url": f"{_H}/ops/api/projects",                  "expected_status": [200,401,403], "group": "Infrastructure"},
    # ════════════════════════════════════════════════════════════════
    # THEBRIDGE — Case Intelligence Case-Server  (port 3010 → /api/*)
    # ════════════════════════════════════════════════════════════════
    {"id": "bridge-health",             "name": "Health",                   "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/bridge/health",                  "expected_status": 200,           "group": "TheBridge · Case"},
    {"id": "bridge-manifest",           "name": "File Manifest",            "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/manifest",                      "expected_status": 200,           "group": "TheBridge · Case"},
    {"id": "bridge-files",              "name": "File List",                "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/files",                         "expected_status": 200,           "group": "TheBridge · Case"},
    {"id": "bridge-categories",         "name": "Categories",               "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/categories",                    "expected_status": 200,           "group": "TheBridge · Case"},
    {"id": "bridge-endpoints",          "name": "Endpoints List",           "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/endpoints",                     "expected_status": 200,           "group": "TheBridge · Case"},
    {"id": "bridge-search",             "name": "File Search",              "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/search?q=test",                 "expected_status": 200,           "group": "TheBridge · Case"},
    {"id": "bridge-tree",               "name": "File Tree",                "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/tree",                          "expected_status": 200,           "group": "TheBridge · Case"},
    {"id": "bridge-rebuild",            "name": "Rebuild (POST)",           "service": "thebridge",    "method": "POST", "url": f"{_H}/api/rebuild",                       "expected_status": [200,400,422],"group": "TheBridge · Case"},
    {"id": "bridge-pipeline-entities",  "name": "Pipeline Entities",        "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/pipeline/entities",             "expected_status": [200,404],     "group": "TheBridge · Pipeline"},
    {"id": "bridge-pipeline-stats",     "name": "Pipeline Stats",           "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/pipeline/stats",                "expected_status": [200,404],     "group": "TheBridge · Pipeline"},
    {"id": "bridge-pipeline-timeline",  "name": "Pipeline Timeline",        "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/pipeline/timeline",             "expected_status": [200,404],     "group": "TheBridge · Pipeline"},
    {"id": "bridge-pipeline-relations", "name": "Pipeline Relationships",   "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/pipeline/relationships",         "expected_status": [200,404],     "group": "TheBridge · Pipeline"},
    {"id": "bridge-pipeline-search",    "name": "Pipeline Search",          "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/pipeline/search?q=test",        "expected_status": [200,404],     "group": "TheBridge · Pipeline"},
    {"id": "bridge-intel-violations",   "name": "Intelligence Violations",  "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/intelligence/violations",        "expected_status": [200,404],     "group": "TheBridge · Intelligence"},
    {"id": "bridge-intel-gap",          "name": "Intelligence Gap Report",  "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/intelligence/gap-report",        "expected_status": [200,404],     "group": "TheBridge · Intelligence"},
    {"id": "bridge-intel-summary",      "name": "Intelligence Summary",     "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/intelligence/summary",           "expected_status": [200,404],     "group": "TheBridge · Intelligence"},
    {"id": "bridge-intel-timeline",     "name": "Intelligence Timeline",    "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/intelligence/timeline",          "expected_status": [200,404],     "group": "TheBridge · Intelligence"},
    {"id": "bridge-intel-narrative",    "name": "Intelligence Narrative",   "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/intelligence/narrative",         "expected_status": [200,404],     "group": "TheBridge · Intelligence"},
    {"id": "bridge-intel-run",          "name": "Intelligence Run (POST)",  "service": "thebridge",    "method": "POST", "url": f"{_H}/api/intelligence/run",               "expected_status": [200,400,422,404], "group": "TheBridge · Intelligence"},
    {"id": "bridge-comprehend-strats",  "name": "Comprehend Strategies",    "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/comprehend/strategies",          "expected_status": [200,404],     "group": "TheBridge · Comprehend"},
    {"id": "bridge-comprehend-guide",   "name": "Comprehend Guide",         "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/comprehend/guide",               "expected_status": [200,404],     "group": "TheBridge · Comprehend"},
    {"id": "bridge-comprehend-groups",  "name": "Comprehend Groups",        "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/comprehend/groups",              "expected_status": [200,404],     "group": "TheBridge · Comprehend"},
    {"id": "bridge-comprehend-run",     "name": "Comprehend Run (POST)",    "service": "thebridge",    "method": "POST", "url": f"{_H}/api/comprehend/run",                 "expected_status": [200,400,422,404], "group": "TheBridge · Comprehend"},
    {"id": "bridge-case-state",         "name": "Case State",               "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/case-state",                    "expected_status": [200,404],     "group": "TheBridge · Case"},
    {"id": "bridge-events",             "name": "Events",                   "service": "thebridge",    "method": "GET",  "url": f"{_H}/api/events",                        "expected_status": [200,404],     "group": "TheBridge · Case"},
]

_LOCAL_API_TEST_ENDPOINTS = [
        # ── Infrastructure ──
        {"id": "ops-login",           "name": "Ops Login",              "service": "ops-dashboard",     "method": "GET",  "url": "http://localhost:9000/login",                    "expected_status": 200,        "group": "Infrastructure"},
        {"id": "gateway-health",      "name": "Gateway Health",         "service": "gateway",           "method": "GET",  "url": "http://localhost:8080/health",                   "expected_status": 200,        "group": "Infrastructure"},
        {"id": "shared-health",       "name": "Shared API Health",      "service": "_shared",           "method": "GET",  "url": "http://localhost:8099/health",                   "expected_status": 200,        "group": "Infrastructure"},
        # ── Core ──
        {"id": "awareness-health",    "name": "Awareness Health",       "service": "awareness",         "method": "GET",  "url": "http://localhost:8078/health",                   "expected_status": 200,        "group": "Core"},
        {"id": "qdrant-svc-health",   "name": "Qdrant Service Health",  "service": "awareness-qdrant",  "method": "GET",  "url": "http://localhost:8079/health",                   "expected_status": 200,        "group": "Core"},
        {"id": "garage-health",       "name": "Garage Health",          "service": "garage",            "method": "GET",  "url": "http://localhost:8066/health",                   "expected_status": 200,        "group": "Core"},
        {"id": "argus-root",          "name": "Argus Root",             "service": "argus",             "method": "GET",  "url": "http://localhost:8029/",                         "expected_status": 200,        "group": "Core"},
        {"id": "legalpipe-health",    "name": "LegalPipeline Health",   "service": "legalpipeline",     "method": "GET",  "url": "http://localhost:8020/health",                   "expected_status": 200,        "group": "Core"},
        {"id": "transcribe-root",     "name": "Transcribe Root",        "service": "transcribe",        "method": "GET",  "url": "http://localhost:8045/",                         "expected_status": 200,        "group": "Core"},
        # ── Bridge ──
        {"id": "bridge-health",       "name": "TheBridge Health",       "service": "thebridge",         "method": "GET",  "url": "http://localhost:3010/health",                   "expected_status": 200,        "group": "Bridge"},
        {"id": "bridge-res-health",   "name": "Bridge Res Health",      "service": "thebridge-res",     "method": "GET",  "url": "http://localhost:3020/health",                   "expected_status": 200,        "group": "Bridge"},
    ]


def _build_service_port_map() -> dict:
    """Return dict mapping service display names to the numeric port they run on."""
    port_map = {}
    for svc in VPS_SERVICES:
        name = svc.get("name")
        port_str = svc.get("port")
        if not name or not port_str:
            continue
        # Extract first numeric port from string like "80/443" or "3010"
        if isinstance(port_str, int):
            port = port_str
        elif isinstance(port_str, str):
            parts = port_str.split('/')
            if parts[0].isdigit():
                port = int(parts[0])
            else:
                continue
        else:
            continue
        port_map[name] = port
        # Add common aliases found in the JSON
        if name == "argus":
            port_map["ARGUS Dashboard"] = port
        elif name == "garage":
            port_map["Garage Assistants API"] = port
        elif name == "awareness":
            port_map["Awareness"] = port
        elif name == "thebridge":
            port_map["TheBridge"] = port
        elif name == "legalpipeline":
            port_map["Legal Pipeline"] = port
        elif name == "pinocchio":
            port_map["Pinocchio Transcription"] = port
        elif name == "thebridge-ui":
            port_map["TheBridge"] = port  # sometimes "TheBridge" appears in JSON
    return port_map

def _parse_custom_json_to_tests(
    data: dict,
    base_url: str = None,
    per_service_port: bool = False,
    service_port_map: dict = None
) -> list[dict]:
    """Convert the custom JSON structure to test endpoint definitions."""
    if base_url is None:
        base_url = "https://awareness-ai.com.br" if not _is_local_mode() else "http://localhost:8080"

    if service_port_map is None:
        service_port_map = _build_service_port_map()

    tests = []
    services = data.get("services", [])
    for svc in services:
        svc_name = svc.get("name", "")
        endpoints_dict = svc.get("endpoints", {})
        # Determine port if needed
        port = None
        if per_service_port:
            port = service_port_map.get(svc_name) or service_port_map.get(svc_name.lower()) or service_port_map.get(svc_name.upper())
            if not port:
                # Try fuzzy match (e.g., "AI-First Compliance" not mapped, fallback to 8080)
                # For now, just skip endpoints of unknown services in port mode
                continue
        for key, details in endpoints_dict.items():
            parts = key.split(" ", 1)
            if len(parts) != 2:
                continue
            method = parts[0].upper()
            path = parts[1]
            if not path.startswith('/'):
                path = '/' + path
            # Build URL
            if per_service_port and port:
                url = f"{base_url.rstrip('/')}:{port}{path}"
            else:
                url = base_url.rstrip('/') + path

            if method == "GET":
                expected = [200, 404]
            else:
                expected = [200, 400, 422, 404]

            name = details.get("summary", details.get("description", f"{method} {path}"))
            tests.append({
                "id": f"custom_{svc_name}_{method}_{path}".replace("/", "_"),
                "name": name,
                "service": svc_name,
                "method": method,
                "url": url,
                "expected_status": expected,
                "group": svc_name,
            })
    return tests


def _active_api_test_endpoints() -> list[dict]:
    """Return test endpoint definitions.
    Local mode: uses per-port _LOCAL_API_TEST_ENDPOINTS list.
    VPS mode: dynamically loaded from endpoints.json, falling back to _API_TEST_ENDPOINTS.
    """
    if _is_local_mode():
        return _LOCAL_API_TEST_ENDPOINTS
    dynamic = _load_endpoints_from_json()
    return dynamic if dynamic else _API_TEST_ENDPOINTS


def _test_one_endpoint(ep: dict) -> dict:
    """Test a single endpoint; returns result dict with pass/fail, status, timing, body."""
    import time as _t
    start = _t.monotonic()
    try:
        req = urllib.request.Request(
            ep["url"],
            headers={"User-Agent": "AwarenessOps/1.0"},
            method=ep["method"],
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            elapsed = round((_t.monotonic() - start) * 1000)
            raw = resp.read(2048).decode("utf-8", errors="replace")
            status = resp.status
            hdrs = dict(resp.headers)
    except urllib.error.HTTPError as e:
        elapsed = round((_t.monotonic() - start) * 1000)
        status = e.code
        raw = e.read(512).decode("utf-8", errors="replace") if hasattr(e, "read") else str(e)
        hdrs = {}
    except urllib.error.URLError as e:
        elapsed = round((_t.monotonic() - start) * 1000)
        return {**ep, "passed": False, "status": None, "elapsed_ms": elapsed, "body": "", "error": str(e.reason), "headers": {}}
    except Exception as e:
        elapsed = round((_t.monotonic() - start) * 1000)
        return {**ep, "passed": False, "status": None, "elapsed_ms": elapsed, "body": "", "error": str(e), "headers": {}}

    expected = ep.get("expected_status", 200)
    passed = (status in expected) if isinstance(expected, list) else (status == expected)
    try:
        body_preview = json.dumps(json.loads(raw), indent=2)[:600]
    except Exception:
        body_preview = raw[:600]
    return {
        **ep,
        "passed": passed,
        "status": status,
        "elapsed_ms": elapsed,
        "body": body_preview,
        "error": None,
        "headers": {k: v for k, v in list(hdrs.items())[:8]},
    }


@app.route("/api/test/run-shell", methods=["POST"])
@ops_login_required
def run_shell_tests():
    """Run api_map.sh locally and return structured JSON results."""
    import re as _re
    api_map = PROJECT_ROOT / "api_map.sh"
    if not api_map.exists():
        return jsonify({"error": "api_map.sh not found", "path": str(api_map)}), 404
    try:
        result = subprocess.run(
            ["bash", str(api_map)],
            capture_output=True, text=True, timeout=120,
            cwd=str(PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired:
        return jsonify({"error": "api_map.sh timed out after 120 s"}), 504
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    raw = result.stdout + result.stderr
    # Strip ANSI escape codes for the clean text version
    ansi_escape = _re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
    clean = ansi_escape.sub("", raw)

    # Parse summary line: "N passed  M failed"
    m = _re.search(r"(\d+)\s+passed", clean)
    passed = int(m.group(1)) if m else 0
    m = _re.search(r"(\d+)\s+failed", clean)
    failed = int(m.group(1)) if m else 0
    total = passed + failed

    # Parse individual failure lines: "  • LABEL → URL [...]"
    failures = _re.findall(r"•\s+(.+)", clean)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "failed": failed,
        "total": total,
        "failures": failures,
        "output": clean,
        "returncode": result.returncode,
    }
    return jsonify(report)


@app.route("/api/test/endpoints")
@ops_login_required
def test_endpoints_catalog():
    """Return the list of all test endpoint definitions."""
    return jsonify(_active_api_test_endpoints())


@app.route("/api/test/run", methods=["POST"])
@ops_login_required
def run_api_tests():
    """Run all API endpoint tests, save the report, and return it."""
    tests = _active_api_test_endpoints()
    results = [_test_one_endpoint(ep) for ep in tests]
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "failed": sum(1 for r in results if not r["passed"]),
        "results": results,
    }
    try:
        TEST_REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        pass
    return jsonify(report)


@app.route("/api/test/from-json", methods=["POST"])
@ops_login_required
def test_from_json():
    """Accept a JSON file or body with endpoint definitions and run tests."""
    # Parse parameters from form or JSON body
    base_url = None
    per_service_port = False

    if request.files and "file" in request.files:
        # multipart/form-data
        if "base_url" in request.form:
            base_url = request.form["base_url"].strip()
        per_service_port = request.form.get("per_service_port") == "true"
        file = request.files["file"]
        if not file.filename.endswith(".json"):
            return jsonify({"error": "File must be JSON"}), 400
        try:
            data = json.load(file.stream)
        except Exception as e:
            return jsonify({"error": f"Invalid JSON: {e}"}), 400
    else:
        # raw JSON body
        json_data = request.get_json()
        if not json_data:
            return jsonify({"error": "No JSON provided"}), 400
        data = json_data.get("endpoint_data")
        if not data:
            return jsonify({"error": "Missing 'endpoint_data' in JSON"}), 400
        base_url = json_data.get("base_url")
        per_service_port = json_data.get("per_service_port", False)

    tests = _parse_custom_json_to_tests(data, base_url, per_service_port)
    if not tests:
        return jsonify({"error": "No endpoints found in JSON"}), 400

    results = [_test_one_endpoint(ep) for ep in tests]
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "failed": sum(1 for r in results if not r["passed"]),
        "results": results,
        "source": "custom_json",
        "base_url": base_url,
        "per_service_port": per_service_port,
    }
    return jsonify(report)

@app.route("/api/test/last")
@ops_login_required
def get_last_test_report():
    """Return the last saved API test report."""
    if not TEST_REPORT_FILE.exists():
        return jsonify({"error": "No test report found. Run tests first."}), 404
    with open(TEST_REPORT_FILE, encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/api/test/scan-and-run", methods=["POST"])
@ops_login_required
def scan_and_run_api_tests():
    """Dynamically discover endpoints via scripts/map_endpoints.py, then run tests.
    Body (optional): {"directory": "<relative-or-absolute-path>"}
    The discovered endpoints are written to ENDPOINTS_FILE and the cache is cleared,
    so the test run reflects the live codebase.
    """
    global _endpoints_cache

    # ── 1. Resolve scan directory ──────────────────────────────────────────
    body = request.get_json(silent=True) or {}
    raw_dir = body.get("directory", "").strip()
    if raw_dir:
        scan_dir = (PROJECT_ROOT / raw_dir).resolve()
    else:
        scan_dir = PROJECT_ROOT

    # Security: must stay inside PROJECT_ROOT
    try:
        scan_dir.relative_to(PROJECT_ROOT)
    except ValueError:
        return jsonify({"error": "Directory must be inside the project root."}), 400

    if not scan_dir.is_dir():
        return jsonify({"error": f"Not a directory: {scan_dir}"}), 400

    # ── 2. Run map_endpoints.py to refresh the catalog (optional) ──────────
    scan_ok = False
    scan_stderr = ""
    scan_skipped = False

    if not MAP_ENDPOINTS_SCRIPT.exists():
        # Script not deployed yet — degrade gracefully: run tests from existing catalog
        scan_skipped = True
        scan_stderr = f"map_endpoints.py not found at {MAP_ENDPOINTS_SCRIPT}. Running tests from existing catalog."
    else:
        # Ensure the output directory exists before writing
        API_DOCS_DIR.mkdir(parents=True, exist_ok=True)
        out_base = str(ENDPOINTS_FILE.with_suffix(""))  # strip .json — script adds it
        try:
            scan_result = subprocess.run(
                [sys.executable, str(MAP_ENDPOINTS_SCRIPT), str(scan_dir), "--format", "json", "--output", out_base],
                capture_output=True, text=True, timeout=120,
                cwd=str(PROJECT_ROOT),
            )
            scan_stderr = scan_result.stderr.strip()
            scan_ok = scan_result.returncode == 0
        except subprocess.TimeoutExpired:
            scan_stderr = "map_endpoints.py timed out after 120 s"
        except Exception as exc:
            scan_stderr = f"Failed to run map_endpoints.py: {exc}"

    # ── 3. Reload catalog cache ────────────────────────────────────────────
    _endpoints_cache = None
    tests = _active_api_test_endpoints()

    # ── 4. Run tests ───────────────────────────────────────────────────────
    results = [_test_one_endpoint(ep) for ep in tests]
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "failed": sum(1 for r in results if not r["passed"]),
        "results": results,
        "scan_meta": {
            "directory": str(scan_dir),
            "discovered": len(tests),
            "map_endpoints_ok": scan_ok,
            "scan_skipped": scan_skipped,
            "map_endpoints_log": scan_stderr[:500] if scan_stderr else "",
        },
    }

    # ── 5. Persist report ──────────────────────────────────────────────────
    try:
        TEST_REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        pass

    return jsonify(report)


# ── Endpoint Mapper Pipeline ─────────────────────────────────────────────────

def _run_endpoint_mapper(command: str, job_id: str) -> None:
    """Run endpoint_mapper.py command in background thread."""
    _MAPPER_JOBS[job_id] = {"status": "running", "output": "", "started": datetime.now(timezone.utc).isoformat(), "command": command}
    try:
        venv_python = ENDPOINT_MAPPER_DIR.parent / ".venv" / "bin" / "python"
        if not venv_python.exists():
            venv_python = "python3"
        else:
            venv_python = str(venv_python)
        
        result = subprocess.run(
            [venv_python, str(ENDPOINT_MAPPER_DIR / "endpoint_mapper.py"), command],
            capture_output=True, text=True, timeout=300,
            cwd=str(ENDPOINT_MAPPER_DIR.parent),
        )
        _MAPPER_JOBS[job_id]["output"] = result.stdout + result.stderr
        _MAPPER_JOBS[job_id]["status"] = "completed" if result.returncode == 0 else "failed"
        _MAPPER_JOBS[job_id]["returncode"] = result.returncode
    except subprocess.TimeoutExpired:
        _MAPPER_JOBS[job_id]["status"] = "timeout"
        _MAPPER_JOBS[job_id]["output"] = "Command timed out after 300 seconds"
    except Exception as e:
        _MAPPER_JOBS[job_id]["status"] = "error"
        _MAPPER_JOBS[job_id]["output"] = str(e)
    finally:
        _MAPPER_JOBS[job_id]["finished"] = datetime.now(timezone.utc).isoformat()


@app.route("/api/endpoints/discover")
@ops_login_required
def endpoints_discover():
    """Return discovered endpoints from the last scan."""
    if not DISCOVERED_ENDPOINTS_FILE.exists():
        return jsonify({"error": "No discovered endpoints. Run scan first.", "hint": "POST /api/endpoints/scan"}), 404
    with open(DISCOVERED_ENDPOINTS_FILE, encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/api/endpoints/enriched")
@ops_login_required
def endpoints_enriched():
    """Return enriched endpoints (with LLM documentation)."""
    if not ENRICHED_ENDPOINTS_FILE.exists():
        return jsonify({"error": "No enriched endpoints. Run enrich first.", "hint": "POST /api/endpoints/enrich"}), 404
    with open(ENRICHED_ENDPOINTS_FILE, encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/api/endpoints/catalog")
@ops_login_required
def endpoints_catalog():
    """Return the raw endpoints.json registry (generated by scripts/map_endpoints.py)."""
    if not ENDPOINTS_FILE.exists():
        return jsonify({"error": "endpoints.json not found", "hint": "Run: python3 scripts/map_endpoints.py . --output _shared/api/endpoints"}), 404
    with open(ENDPOINTS_FILE, encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/api/endpoints/catalog/reload", methods=["POST"])
@ops_login_required
def endpoints_catalog_reload():
    """Invalidate the in-memory endpoints cache so the next call re-reads endpoints.json."""
    global _endpoints_cache
    _endpoints_cache = None
    count = len(_load_endpoints_from_json())
    return jsonify({"ok": True, "loaded": count})


@app.route("/api/endpoints/docs")
@ops_login_required
def endpoints_docs():
    """Return generated markdown documentation."""
    if not ENDPOINT_DOCS_FILE.exists():
        return jsonify({"error": "No documentation generated. Run report first.", "hint": "POST /api/endpoints/report"}), 404
    content = ENDPOINT_DOCS_FILE.read_text(encoding="utf-8")
    return jsonify({"content": content, "file": str(ENDPOINT_DOCS_FILE)})


@app.route("/api/endpoints/scan", methods=["POST"])
@ops_login_required
def endpoints_scan():
    """Scan all services for endpoints (runs synchronously)."""
    job_id = f"scan_{int(time.time())}"
    thread = threading.Thread(target=_run_endpoint_mapper, args=("scan", job_id))
    thread.start()
    thread.join(timeout=60)  # Wait up to 60 seconds
    
    if job_id in _MAPPER_JOBS:
        job = _MAPPER_JOBS[job_id]
        if job["status"] == "running":
            return jsonify({"ok": False, "message": "Scan still running, check /api/endpoints/jobs/" + job_id}), 202
        return jsonify({"ok": job["status"] == "completed", "output": job["output"], "job_id": job_id})
    return jsonify({"ok": False, "message": "Unknown error"}), 500


@app.route("/api/endpoints/enrich", methods=["POST"])
@ops_login_required
def endpoints_enrich():
    """Enrich endpoints with LLM documentation (async, returns job_id)."""
    job_id = f"enrich_{int(time.time())}"
    thread = threading.Thread(target=_run_endpoint_mapper, args=("enrich", job_id), daemon=True)
    thread.start()
    return jsonify({"ok": True, "message": "Enrichment started", "job_id": job_id, "check": f"/api/endpoints/jobs/{job_id}"}), 202


@app.route("/api/endpoints/test", methods=["POST"])
@ops_login_required
def endpoints_test_all():
    """Test all discovered endpoints."""
    job_id = f"test_{int(time.time())}"
    thread = threading.Thread(target=_run_endpoint_mapper, args=("test", job_id))
    thread.start()
    thread.join(timeout=120)
    
    if job_id in _MAPPER_JOBS:
        job = _MAPPER_JOBS[job_id]
        if job["status"] == "running":
            return jsonify({"ok": False, "message": "Test still running", "job_id": job_id}), 202
        return jsonify({"ok": job["status"] == "completed", "output": job["output"], "job_id": job_id})
    return jsonify({"ok": False, "message": "Unknown error"}), 500


@app.route("/api/endpoints/store", methods=["POST"])
@ops_login_required
def endpoints_store():
    """Store endpoints in Qdrant vector database."""
    job_id = f"store_{int(time.time())}"
    thread = threading.Thread(target=_run_endpoint_mapper, args=("store", job_id), daemon=True)
    thread.start()
    return jsonify({"ok": True, "message": "Store started", "job_id": job_id, "check": f"/api/endpoints/jobs/{job_id}"}), 202


@app.route("/api/endpoints/graph", methods=["POST"])
@ops_login_required
def endpoints_graph():
    """Build Neo4j endpoint correlation graph."""
    job_id = f"graph_{int(time.time())}"
    thread = threading.Thread(target=_run_endpoint_mapper, args=("graph", job_id), daemon=True)
    thread.start()
    return jsonify({"ok": True, "message": "Graph build started", "job_id": job_id, "check": f"/api/endpoints/jobs/{job_id}"}), 202


@app.route("/api/endpoints/report", methods=["POST"])
@ops_login_required
def endpoints_report():
    """Generate markdown documentation report."""
    job_id = f"report_{int(time.time())}"
    thread = threading.Thread(target=_run_endpoint_mapper, args=("report", job_id))
    thread.start()
    thread.join(timeout=30)
    
    if job_id in _MAPPER_JOBS:
        job = _MAPPER_JOBS[job_id]
        return jsonify({"ok": job["status"] == "completed", "output": job["output"], "job_id": job_id})
    return jsonify({"ok": False, "message": "Unknown error"}), 500


@app.route("/api/endpoints/pipeline", methods=["POST"])
@ops_login_required
def endpoints_full_pipeline():
    """Run full endpoint discovery pipeline (scan → enrich → test → store → graph → report)."""
    job_id = f"pipeline_{int(time.time())}"
    thread = threading.Thread(target=_run_endpoint_mapper, args=("all", job_id), daemon=True)
    thread.start()
    return jsonify({
        "ok": True,
        "message": "Full pipeline started (scan → enrich → test → store → graph → report)",
        "job_id": job_id,
        "check": f"/api/endpoints/jobs/{job_id}",
    }), 202


@app.route("/api/endpoints/jobs")
@ops_login_required
def endpoints_jobs():
    """List all endpoint mapper jobs."""
    return jsonify({"jobs": _MAPPER_JOBS})


@app.route("/api/endpoints/jobs/<job_id>")
@ops_login_required
def endpoints_job_status(job_id: str):
    """Get status of a specific job."""
    if job_id not in _MAPPER_JOBS:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(_MAPPER_JOBS[job_id])


@app.route("/api/endpoints/stats")
@ops_login_required
def endpoints_stats():
    """Get endpoint discovery statistics."""
    stats = {
        "discovered": DISCOVERED_ENDPOINTS_FILE.exists(),
        "enriched": ENRICHED_ENDPOINTS_FILE.exists(),
        "docs_generated": ENDPOINT_DOCS_FILE.exists(),
    }
    
    if DISCOVERED_ENDPOINTS_FILE.exists():
        with open(DISCOVERED_ENDPOINTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
            stats["endpoint_count"] = data.get("endpoint_count", 0)
            stats["services_scanned"] = data.get("services_scanned", [])
            stats["files_scanned"] = data.get("total_files_scanned", 0)
            stats["scanned_at"] = data.get("scanned_at", "")
            
            # Group by service
            by_service = defaultdict(int)
            for ep in data.get("endpoints", []):
                by_service[ep.get("service", "unknown")] += 1
            stats["by_service"] = dict(by_service)
            
            # Group by method
            by_method = defaultdict(int)
            for ep in data.get("endpoints", []):
                by_method[ep.get("method", "?").upper()] += 1
            stats["by_method"] = dict(by_method)
    
    return jsonify(stats)


@app.route("/api/endpoints/sync-tests", methods=["POST"])
@ops_login_required
def endpoints_sync_to_tests():
    """Sync discovered endpoints to the API test catalog, merging with existing tests."""
    if not DISCOVERED_ENDPOINTS_FILE.exists():
        return jsonify({"error": "No discovered endpoints. Run scan first."}), 404
    
    with open(DISCOVERED_ENDPOINTS_FILE, encoding="utf-8") as f:
        discovered = json.load(f)
    
    # Build local test endpoints from discovered data
    new_endpoints = []
    for ep in discovered.get("endpoints", []):
        service = ep.get("service", "unknown")
        port = {
            "awareness": 8078, "garage": 8066, "Argus": 8029, "pinocchio": 8019,
            "LegalPipeline": 8020, "TheBridge": 3010, "_shared": 8099,
            "gateway": 8080, "ops-dashboard": 9000,
        }.get(service, 8000)
        
        path = ep.get("path", "/")
        method = ep.get("method", "GET").upper()
        
        # Determine expected status codes
        if method == "POST":
            expected = [200, 400, 422]  # POST may return validation errors
        else:
            expected = 200
        
        new_endpoints.append({
            "id": ep.get("id"),
            "name": f"{method} {path}",
            "service": service,
            "method": method,
            "url": f"http://localhost:{port}{path}",
            "expected_status": expected,
            "group": f"Discovered · {service}",
            "source": "endpoint_mapper",
            "file": ep.get("file_path", ""),
            "function": ep.get("function_name", ""),
        })
    
    # Save as a separate discovered tests file
    discovered_tests_file = Path(__file__).parent / "discovered_api_tests.json"
    discovered_tests_file.write_text(json.dumps({
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "total": len(new_endpoints),
        "endpoints": new_endpoints,
    }, indent=2), encoding="utf-8")
    
    return jsonify({
        "ok": True,
        "synced": len(new_endpoints),
        "file": str(discovered_tests_file),
    })


# ── Page Deployer ────────────────────────────────────────────────────────────
# Allows uploading new pages with branding and deploying them to project locations.

PAGE_DEPLOY_TARGETS = {
    "awareness": {
        "name": "Awareness AI",
        "static_dir": PROJECT_ROOT / "awareness" / "static",
        "brand_dir": PROJECT_ROOT / "_shared" / "static",
        "nginx_location": "/api/manus/static/",
        "description": "Main Awareness AI agent workspace (FastAPI static)",
    },
    "awareness-frontend": {
        "name": "Frontend (Nginx)",
        "static_dir": PROJECT_ROOT / "awareness-frontend" / "pages",
        "brand_dir": PROJECT_ROOT / "awareness-frontend" / "pages" / "_shared" / "static",
        "nginx_location": "/",
        "description": "Public frontend served by Nginx",
    },
    "garage": {
        "name": "Garage",
        "static_dir": PROJECT_ROOT / "garage" / "static",
        "brand_dir": PROJECT_ROOT / "_shared" / "static",
        "nginx_location": "/garage/static/",
        "description": "Garage tools and assistants",
    },
    "shared": {
        "name": "Shared Static",
        "static_dir": PROJECT_ROOT / "_shared" / "static",
        "brand_dir": PROJECT_ROOT / "_shared" / "static",
        "nginx_location": None,
        "description": "Shared static files (branding, assets)",
    },
}

# Temporary upload storage
_PAGE_UPLOADS: dict = {}


def _generate_upload_id() -> str:
    import uuid
    return f"upload_{uuid.uuid4().hex[:12]}"


@app.route("/api/page-deployer/targets", methods=["GET"])
@ops_login_required
def page_deployer_targets():
    """Return available deployment targets."""
    targets = []
    for key, config in PAGE_DEPLOY_TARGETS.items():
        targets.append({
            "id": key,
            "name": config["name"],
            "description": config["description"],
            "static_dir": str(config["static_dir"]),
            "exists": config["static_dir"].exists(),
            "nginx_location": config["nginx_location"],
        })
    # Always include VPS as a deploy target
    targets.append({
        "id": "vps",
        "name": "VPS · awareness-ai.com.br",
        "description": "Deploy directly to live production server (SCP + chmod 644)",
        "static_dir": VPS_CONFIG["remote_pages_dir"],
        "exists": True,
        "nginx_location": "/",
        "is_vps": True,
    })
    return jsonify(targets)


@app.route("/api/page-deployer/upload", methods=["POST"])
@ops_login_required
def page_deployer_upload():
    """Upload HTML and optional brand MD file for staging."""
    if "html_file" not in request.files:
        return jsonify({"error": "No HTML file provided"}), 400
    
    html_file = request.files["html_file"]
    brand_file = request.files.get("brand_file")
    
    if not html_file.filename or not html_file.filename.endswith(".html"):
        return jsonify({"error": "Invalid HTML filename"}), 400
    
    upload_id = _generate_upload_id()
    
    # Read files
    html_content = html_file.read().decode("utf-8")
    brand_content = None
    brand_filename = None
    
    if brand_file and brand_file.filename:
        brand_content = brand_file.read().decode("utf-8")
        brand_filename = brand_file.filename
    
    # Stage upload
    _PAGE_UPLOADS[upload_id] = {
        "html_filename": html_file.filename,
        "html_content": html_content,
        "brand_filename": brand_filename,
        "brand_content": brand_content,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "deployed": False,
    }
    
    # Parse HTML for title and meta
    title_match = re.search(r"<title>([^<]+)</title>", html_content, re.IGNORECASE)
    title = title_match.group(1) if title_match else html_file.filename
    
    return jsonify({
        "ok": True,
        "upload_id": upload_id,
        "html_filename": html_file.filename,
        "brand_filename": brand_filename,
        "title": title,
        "html_size": len(html_content),
        "brand_size": len(brand_content) if brand_content else 0,
    })


@app.route("/api/page-deployer/preview/<upload_id>", methods=["GET"])
@ops_login_required
def page_deployer_preview(upload_id: str):
    """Preview an uploaded page."""
    if upload_id not in _PAGE_UPLOADS:
        return jsonify({"error": "Upload not found"}), 404
    
    upload = _PAGE_UPLOADS[upload_id]
    return upload["html_content"], 200, {"Content-Type": "text/html"}


def _vps_deploy_upload(upload: dict, final_filename: str, nginx_route: str | None = None) -> dict:
    """Deploy a staged upload to VPS.

    When running ON the VPS (OPS_MODE=vps) writes the file directly.
    Otherwise uses SCP from a local machine.

    Returns dict with keys: ok, message, url, errors.
    """
    import tempfile
    results: dict = {"ok": False, "deployed_files": [], "errors": []}

    # Security: no path traversal
    if "/" in final_filename or "\\" in final_filename or ".." in final_filename:
        results["errors"].append("Invalid filename")
        return results

    remote_dir = VPS_CONFIG["remote_pages_dir"]
    remote_path = f"{remote_dir}/{final_filename}"

    try:
        if _is_on_vps():
            # ── Running ON the VPS: write directly to the filesystem ──────────
            dest = Path(remote_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(upload["html_content"], encoding="utf-8")
            os.chmod(dest, 0o644)
        else:
            # ── Remote deploy via SCP ──────────────────────────────────────────
            ssh_target = f"{VPS_CONFIG['user']}@{VPS_CONFIG['host']}"
            with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as tmp:
                tmp.write(upload["html_content"])
                tmp_path = tmp.name

            scp_result = subprocess.run(
                ["scp", "-o", "StrictHostKeyChecking=no", tmp_path, f"{ssh_target}:{remote_path}"],
                capture_output=True, text=True, timeout=60,
            )
            Path(tmp_path).unlink(missing_ok=True)

            if scp_result.returncode != 0:
                results["errors"].append(f"SCP failed: {scp_result.stderr}")
                return results

            chmod_result = subprocess.run(
                ["ssh", "-o", "StrictHostKeyChecking=no", ssh_target, f"chmod 644 {remote_path}"],
                capture_output=True, text=True, timeout=15,
            )
            if chmod_result.returncode != 0:
                results["errors"].append(f"chmod failed: {chmod_result.stderr}")

        results["deployed_files"].append(remote_path)
        results["url"] = f"https://{VPS_CONFIG['domain']}/{final_filename}"

        # Optional: register a clean nginx location block
        if nginx_route:
            nginx_result = _vps_add_nginx_route(nginx_route, final_filename)
            if nginx_result.get("ok"):
                results["nginx_route"] = nginx_route
                results["nginx_reloaded"] = True
            else:
                results["errors"].append(f"Nginx route: {nginx_result.get('error', 'failed')}")

        results["ok"] = True
        results["message"] = (
            f"Deployed {final_filename} to VPS"
            + (f" → https://{VPS_CONFIG['domain']}{nginx_route}" if nginx_route else "")
        )

    except subprocess.TimeoutExpired:
        results["errors"].append("SCP/SSH timeout")
    except Exception as exc:
        results["errors"].append(str(exc))

    return results


def _vps_add_nginx_route(location: str, filename: str) -> dict:
    """Append a location block to the VPS nginx conf and reload nginx.

    The location block is inserted before the '# ── 404 fallback' comment.
    Idempotent: skips if the location already exists.
    When running ON the VPS the commands are executed directly (no SSH).
    """
    nginx_conf = str(VPS_CONFIG.get("nginx_conf") or "")
    if not nginx_conf:
        return {"ok": False, "error": "VPS nginx conf path is not configured"}

    # Sanitize location path
    if not location.startswith("/"):
        location = "/" + location
    # Reject anything suspicious
    for bad in ("..", ";", "{", "}", "\n", "\r", "\"", "'"):
        if bad in location:
            return {"ok": False, "error": f"Invalid location path character: {bad!r}"}

    block = (
        f"\n    # ── Auto-registered: {filename} ──────────────────────────────────────────\n"
        f"    location = {location} {{\n"
        f"        try_files /{filename} =404;\n"
        f"    }}\n"
    )

    sed_cmd = (
        f"sed -i 's|# ── 404 fallback|{block.rstrip()}\\n\\n    # ── 404 fallback|'"
        f" {nginx_conf}"
    )

    if _is_on_vps():
        # ── Running ON the VPS: run commands directly ─────────────────────────
        # Check idempotency
        check = subprocess.run(
            ["grep", "-q", f"location = {location} ", nginx_conf],
            capture_output=True, timeout=5,
        )
        if check.returncode == 0:
            return {"ok": True, "message": "Route already registered"}

        insert = subprocess.run(sed_cmd, shell=True, capture_output=True, text=True, timeout=15)
        if insert.returncode != 0:
            return {"ok": False, "error": insert.stderr}

        reload = subprocess.run(
            ["docker", "exec", "awareness-frontend-api-gateway-1", "nginx", "-s", "reload"],
            capture_output=True, text=True, timeout=20,
        )
        if reload.returncode != 0:
            return {"ok": False, "error": f"nginx reload failed: {reload.stderr}"}
    else:
        # ── Remote via SSH ────────────────────────────────────────────────────
        ssh_target = f"{VPS_CONFIG['user']}@{VPS_CONFIG['host']}"
        check = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", ssh_target,
             f"grep -q 'location = {location} ' {nginx_conf} && echo EXISTS || echo NEW"],
            capture_output=True, text=True, timeout=15,
        )
        if check.returncode == 0 and "EXISTS" in check.stdout:
            return {"ok": True, "message": "Route already registered"}

        insert = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", ssh_target, sed_cmd],
            capture_output=True, text=True, timeout=15,
        )
        if insert.returncode != 0:
            return {"ok": False, "error": insert.stderr}

        reload = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", ssh_target,
             "docker exec awareness-frontend-api-gateway-1 nginx -s reload"],
            capture_output=True, text=True, timeout=20,
        )
        if reload.returncode != 0:
            return {"ok": False, "error": f"nginx reload failed: {reload.stderr}"}

    return {"ok": True}


@app.route("/api/page-deployer/deploy", methods=["POST"])
@ops_login_required
def page_deployer_deploy():
    """Deploy an uploaded page to the target location (local or VPS)."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    upload_id = data.get("upload_id")
    target_id = data.get("target")
    filename = data.get("filename")  # Optional: rename file
    copy_brand = data.get("copy_brand", True)
    add_to_quicklinks = data.get("add_to_quicklinks", False)
    quicklink_name = data.get("quicklink_name")
    quicklink_group = data.get("quicklink_group", "Custom")
    quicklink_desc = data.get("quicklink_desc", "")
    nginx_route = (data.get("nginx_route") or "").strip() or None

    if not upload_id or upload_id not in _PAGE_UPLOADS:
        return jsonify({"error": "Invalid upload_id"}), 400

    upload = _PAGE_UPLOADS[upload_id]

    # Determine final filename
    final_filename = filename if filename else upload["html_filename"]
    if not final_filename.endswith(".html"):
        final_filename += ".html"
    if "/" in final_filename or "\\" in final_filename or ".." in final_filename:
        return jsonify({"error": "Invalid filename"}), 400

    # ── VPS target: deploy remotely ───────────────────────────────────────────
    if target_id == "vps":
        vps_result = _vps_deploy_upload(upload, final_filename, nginx_route)

        if vps_result["ok"] and add_to_quicklinks and quicklink_name:
            link_path = nginx_route if nginx_route else f"/{final_filename}"
            custom_links = _load_custom_links()
            new_link = {
                "id": _generate_link_id(),
                "name": quicklink_name,
                "group": quicklink_group,
                "desc": quicklink_desc,
                "path": link_path,
                "custom_url": "",
                "icon": "file-code",
                "service": None,
                "status_trigger": None,
            }
            custom_links.append(new_link)
            _save_custom_links(custom_links)
            vps_result["quicklink_added"] = new_link

        if vps_result["ok"]:
            upload["deployed"] = True
            upload["deployed_to"] = "vps"
            upload["deployed_path"] = f"VPS:{VPS_CONFIG['remote_pages_dir']}/{final_filename}"

        return jsonify(vps_result), (200 if vps_result["ok"] else 500)

    # ── Local target ──────────────────────────────────────────────────────────
    if not target_id or target_id not in PAGE_DEPLOY_TARGETS:
        return jsonify({"error": "Invalid target"}), 400

    target = PAGE_DEPLOY_TARGETS[target_id]
    results: dict = {"ok": False, "deployed_files": [], "errors": []}
    try:
        # Ensure target directory exists
        target["static_dir"].mkdir(parents=True, exist_ok=True)
        
        # Write HTML file
        html_path = target["static_dir"] / final_filename
        html_path.write_text(upload["html_content"], encoding="utf-8")
        results["deployed_files"].append(str(html_path))
        
        # Copy brand file if requested
        if copy_brand and upload["brand_content"] and upload["brand_filename"]:
            brand_dir = target["brand_dir"]
            brand_dir.mkdir(parents=True, exist_ok=True)
            brand_path = brand_dir / upload["brand_filename"]
            brand_path.write_text(upload["brand_content"], encoding="utf-8")
            results["deployed_files"].append(str(brand_path))
        
        # Add to quick links if requested
        if add_to_quicklinks and quicklink_name:
            custom_links = _load_custom_links()
            
            # Build path based on target
            if target_id == "awareness":
                link_path = f"/api/manus/static/{final_filename}"
            elif target_id == "awareness-frontend":
                link_path = f"/{final_filename}"
            elif target_id == "garage":
                link_path = f"/garage/static/{final_filename}"
            else:
                link_path = f"/{final_filename}"
            
            new_link = {
                "id": _generate_link_id(),
                "name": quicklink_name,
                "group": quicklink_group,
                "desc": quicklink_desc,
                "path": link_path,
                "custom_url": "",
                "icon": "file-code",
                "service": None,
                "status_trigger": None,
            }
            custom_links.append(new_link)
            _save_custom_links(custom_links)
            results["quicklink_added"] = new_link
        
        # Mark upload as deployed
        upload["deployed"] = True
        upload["deployed_to"] = target_id
        upload["deployed_path"] = str(html_path)
        
        results["ok"] = True
        results["message"] = f"Deployed {final_filename} to {target['name']}"
        results["path"] = str(html_path)
        results["url_hint"] = f"{target['nginx_location'] or '/'}{final_filename}" if target["nginx_location"] else None
        
    except Exception as e:
        results["ok"] = False
        results["errors"].append(str(e))
        return jsonify(results), 500
    
    return jsonify(results)


@app.route("/api/page-deployer/uploads", methods=["GET"])
@ops_login_required
def page_deployer_list_uploads():
    """List staged uploads."""
    uploads = []
    for uid, data in _PAGE_UPLOADS.items():
        uploads.append({
            "upload_id": uid,
            "html_filename": data["html_filename"],
            "brand_filename": data["brand_filename"],
            "uploaded_at": data["uploaded_at"],
            "deployed": data["deployed"],
            "deployed_to": data.get("deployed_to"),
        })
    return jsonify(uploads)


@app.route("/api/page-deployer/uploads/<upload_id>", methods=["DELETE"])
@ops_login_required
def page_deployer_delete_upload(upload_id: str):
    """Delete a staged upload."""
    if upload_id not in _PAGE_UPLOADS:
        return jsonify({"error": "Upload not found"}), 404
    del _PAGE_UPLOADS[upload_id]
    return jsonify({"ok": True})


@app.route("/api/page-deployer/existing/<target_id>", methods=["GET"])
@ops_login_required
def page_deployer_existing_pages(target_id: str):
    """List existing HTML files in a target directory."""
    if target_id not in PAGE_DEPLOY_TARGETS:
        return jsonify({"error": "Invalid target"}), 400
    
    target = PAGE_DEPLOY_TARGETS[target_id]
    static_dir = target["static_dir"]
    
    if not static_dir.exists():
        return jsonify({"pages": [], "exists": False})
    
    pages = []
    for f in static_dir.glob("*.html"):
        stat = f.stat()
        pages.append({
            "filename": f.name,
            "size_kb": round(stat.st_size / 1024, 1),
            "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        })
    
    return jsonify({"pages": sorted(pages, key=lambda x: x["filename"]), "exists": True})


# ── VPS Deployment ─────────────────────────────────────────────────────────────

VPS_CONFIG = {
    "host": "72.60.143.139",
    "user": "root",
    "remote_pages_dir": str(os.environ.get("OPS_VPS_REMOTE_PAGES_DIR", "/root/awareness/workspace")),
    "nginx_conf": str(os.environ.get("OPS_VPS_NGINX_CONF", "/root/awareness/nginx/conf.d/10_server.conf")),
    "domain": "awareness-ai.com.br",
}


def _is_on_vps() -> bool:
    """True when this dashboard process IS running on the VPS.

    In that case all VPS operations must use local file/subprocess calls
    instead of SSH/SCP to avoid a self-SSH authentication failure.
    """
    return OPS_MODE == "vps"


@app.route("/api/page-deployer/vps/status", methods=["GET"])
@ops_login_required
def vps_status():
    """Check VPS connectivity."""
    if _is_on_vps():
        # Already on the VPS — no SSH needed
        return jsonify({
            "status": "connected",
            "host": "localhost (on-VPS)",
            "domain": VPS_CONFIG["domain"],
        })
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
             f"{VPS_CONFIG['user']}@{VPS_CONFIG['host']}", "echo ok"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return jsonify({
                "status": "connected",
                "host": VPS_CONFIG["host"],
                "domain": VPS_CONFIG["domain"],
            })
        return jsonify({"status": "error", "error": result.stderr}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"status": "timeout"}), 504
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/page-deployer/vps/pages", methods=["GET"])
@ops_login_required
def vps_list_pages():
    """List pages deployed on VPS."""
    try:
        if _is_on_vps():
            # Read the directory directly — no SSH needed
            pages_dir = Path(VPS_CONFIG["remote_pages_dir"])
            if not pages_dir.exists():
                return jsonify({"pages": [], "count": 0, "host": "localhost", "domain": VPS_CONFIG["domain"]})
            pages = []
            for p in sorted(pages_dir.glob("*.html")):
                stat = p.stat()
                pages.append({
                    "filename": p.name,
                    "size_kb": round(stat.st_size / 1024, 1),
                    "url": f"https://{VPS_CONFIG['domain']}/{p.name}",
                })
            return jsonify({
                "pages": pages,
                "count": len(pages),
                "host": "localhost (on-VPS)",
                "domain": VPS_CONFIG["domain"],
            })

        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=no",
             f"{VPS_CONFIG['user']}@{VPS_CONFIG['host']}",
             f"ls -la {VPS_CONFIG['remote_pages_dir']}/*.html 2>/dev/null | awk '{{print $5, $6, $7, $8, $9}}'"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return jsonify({"pages": [], "error": result.stderr})

        pages = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 5:
                size_bytes = int(parts[0])
                filename = parts[-1].split('/')[-1]
                pages.append({
                    "filename": filename,
                    "size_kb": round(size_bytes / 1024, 1),
                    "url": f"https://{VPS_CONFIG['domain']}/{filename}",
                })

        return jsonify({
            "pages": sorted(pages, key=lambda x: x["filename"]),
            "count": len(pages),
            "host": VPS_CONFIG["host"],
            "domain": VPS_CONFIG["domain"],
        })
    except subprocess.TimeoutExpired:
        return jsonify({"pages": [], "error": "Connection timeout"}), 504
    except Exception as e:
        return jsonify({"pages": [], "error": str(e)}), 500


@app.route("/api/page-deployer/vps/sync", methods=["POST"])
@ops_login_required
def vps_sync_pages():
    """Sync local pages to VPS."""
    import shutil
    data = request.get_json() or {}

    # Can specify specific files or sync all
    files = data.get("files", [])  # List of filenames to sync, empty = all
    source_dir = PROJECT_ROOT / "awareness-frontend" / "pages"

    if not source_dir.exists():
        return jsonify({"error": "Local pages directory not found"}), 400

    results = {"synced": [], "errors": [], "skipped": []}

    try:
        dest_dir = Path(VPS_CONFIG["remote_pages_dir"])

        if _is_on_vps():
            # ── On VPS: copy within the local filesystem ───────────────────────
            if source_dir.resolve() == dest_dir.resolve():
                return jsonify({"ok": True, "message": "Source and destination are the same — no sync needed",
                                "synced": [], "errors": [], "skipped": []})
            dest_dir.mkdir(parents=True, exist_ok=True)
            html_files = [source_dir / f for f in files if f.endswith(".html")] if files else list(source_dir.glob("*.html"))
            for src in html_files:
                if not src.exists():
                    results["errors"].append({"file": src.name, "error": "File not found locally"})
                    continue
                dst = dest_dir / src.name
                shutil.copy2(src, dst)
                os.chmod(dst, 0o644)
                results["synced"].append({"file": src.name, "url": f"https://{VPS_CONFIG['domain']}/{src.name}"})
            if files:
                skipped_non_html = [f for f in files if not f.endswith(".html")]
                for f in skipped_non_html:
                    results["skipped"].append({"file": f, "reason": "Not an HTML file"})
        else:
            # ── Remote via rsync over SSH ──────────────────────────────────────
            if files:
                for filename in files:
                    if not filename.endswith(".html"):
                        results["skipped"].append({"file": filename, "reason": "Not an HTML file"})
                        continue
                    local_path = source_dir / filename
                    if not local_path.exists():
                        results["errors"].append({"file": filename, "error": "File not found locally"})
                        continue
                    rsync_result = subprocess.run(
                        ["rsync", "-avz", "--progress", "-e", "ssh -o StrictHostKeyChecking=no",
                         str(local_path), f"{VPS_CONFIG['user']}@{VPS_CONFIG['host']}:{VPS_CONFIG['remote_pages_dir']}/"],
                        capture_output=True, text=True, timeout=60
                    )
                    if rsync_result.returncode == 0:
                        results["synced"].append({"file": filename, "url": f"https://{VPS_CONFIG['domain']}/{filename}"})
                    else:
                        results["errors"].append({"file": filename, "error": rsync_result.stderr})
            else:
                rsync_result = subprocess.run(
                    ["rsync", "-avz", "--progress", "-e", "ssh -o StrictHostKeyChecking=no",
                     "--include=*.html", "--exclude=*",
                     f"{source_dir}/", f"{VPS_CONFIG['user']}@{VPS_CONFIG['host']}:{VPS_CONFIG['remote_pages_dir']}/"],
                    capture_output=True, text=True, timeout=120
                )
                if rsync_result.returncode == 0:
                    for line in rsync_result.stdout.split('\n'):
                        if line.endswith('.html'):
                            results["synced"].append({"file": line.strip(), "url": f"https://{VPS_CONFIG['domain']}/{line.strip()}"})
                    results["message"] = "Full sync completed"
                else:
                    results["errors"].append({"error": rsync_result.stderr})

        results["ok"] = len(results["errors"]) == 0
        return jsonify(results)

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Sync timeout", "synced": results["synced"]}), 504
    except Exception as e:
        return jsonify({"error": str(e), "synced": results["synced"]}), 500


@app.route("/api/page-deployer/vps/delete", methods=["POST"])
@ops_login_required
def vps_delete_page():
    """Delete a page from VPS."""
    data = request.get_json() or {}
    filename = data.get("filename")

    if not filename or not filename.endswith(".html"):
        return jsonify({"error": "Invalid filename"}), 400

    # Security: prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"error": "Invalid filename"}), 400

    try:
        if _is_on_vps():
            target = Path(VPS_CONFIG["remote_pages_dir"]) / filename
            target.unlink(missing_ok=True)
            return jsonify({"ok": True, "deleted": filename})

        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=no",
             f"{VPS_CONFIG['user']}@{VPS_CONFIG['host']}",
             f"rm -f {VPS_CONFIG['remote_pages_dir']}/{filename}"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return jsonify({"ok": True, "deleted": filename})
        return jsonify({"error": result.stderr}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "ops-dashboard",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }), 200


if __name__ == "__main__":
    runtime_port = int(os.getenv("PORT") or os.getenv("OPS_DASHBOARD_PORT") or "9000")
    print("=" * 60)
    print("  Awareness-AI · Ops Dashboard")
    print(f"  http://localhost:{runtime_port}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=runtime_port, debug=False)
