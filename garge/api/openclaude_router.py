"""
OpenClaude Agent Integration Router
Bridges the Garage assistant system with OpenClaude's markdown-based agent format.

Agents are stored as .md files in .claude/agents/ with YAML frontmatter:
---
name: my-agent
description: When to use this agent
tools: Read, Grep, Glob
model: haiku
---
System prompt body (markdown content after frontmatter).
"""

import os
import re
import json
import yaml
import logging
import subprocess
import asyncio
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Body, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/openclaude", tags=["OpenClaude"])

# ── Configuration ──────────────────────────────────────────────────────────
# Primary agent directories to scan (first one that exists wins for writes)
_AGENT_DIRS = [
    Path(os.path.dirname(os.path.abspath(__file__))).parent / "openclaude" / ".claude" / "agents",
    Path(os.path.dirname(os.path.abspath(__file__))).parent / ".claude" / "agents",
]

def _get_agent_dirs() -> List[Path]:
    """Return existing agent directories (create primary if needed)."""
    dirs = []
    for d in _AGENT_DIRS:
        try:
            d.mkdir(parents=True, exist_ok=True)
            dirs.append(d)
        except Exception:
            pass
    if not dirs:
        raise HTTPException(status_code=500, detail="Cannot access agent directories")
    return dirs

def _get_write_dir() -> Path:
    """Return the primary directory for writing new agent files."""
    return _get_agent_dirs()[0]


# ── YAML Frontmatter Parsing ───────────────────────────────────────────────
FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)---\s*\n?', re.DOTALL)

def parse_agent_markdown(content: str) -> Dict[str, Any]:
    """Parse agent markdown into frontmatter dict + body string."""
    match = FRONTMATTER_RE.match(content)
    if not match:
        return {"frontmatter": {}, "body": content.strip()}

    try:
        frontmatter = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML frontmatter: {e}")

    body = content[match.end():].strip()
    return {"frontmatter": frontmatter, "body": body}

def serialize_agent_markdown(frontmatter: Dict[str, Any], body: str) -> str:
    """Serialize frontmatter + body back to markdown string."""
    yaml_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True, sort_keys=False).strip()
    body = body.strip()
    return f"---\n{yaml_str}\n---\n\n{body}\n"

# ── Helper: list all agent files ───────────────────────────────────────────
def _list_agent_files() -> List[Path]:
    """Find all .md agent files across all agent directories."""
    files = []
    seen = set()
    for d in _get_agent_dirs():
        if not d.exists():
            continue
        for md_file in sorted(d.rglob("*.md")):
            # Use filename as dedup key (first found wins)
            rel = str(md_file.relative_to(d))
            if rel not in seen:
                seen.add(rel)
                files.append(md_file)
    return files

def _find_agent_file(name: str) -> Optional[Path]:
    """Find a specific agent .md file by name (without .md extension)."""
    filename = f"{name}.md" if not name.endswith(".md") else name
    requested = name[:-3] if name.endswith(".md") else name
    requested_lc = requested.strip().lower()

    def _norm(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")

    requested_norm = _norm(requested)

    for d in _get_agent_dirs():
        for md_file in d.rglob("*.md"):
            if md_file.name == filename:
                return md_file

            # Also match by subfolder/file pattern (category/name.md)
            rel = str(md_file.relative_to(d))
            if rel == filename or rel.replace("/", "-") == filename:
                return md_file

            # Match stem variations (e.g. pretty name vs slugged filename)
            stem = md_file.stem
            if stem.lower() == requested_lc or _norm(stem) == requested_norm:
                return md_file

            # Fallback: match frontmatter `name` for files whose filenames are slugified.
            try:
                parsed = parse_agent_markdown(md_file.read_text(encoding="utf-8"))
                fm_name = str((parsed.get("frontmatter") or {}).get("name") or "").strip()
                if not fm_name:
                    continue
                if fm_name.lower() == requested_lc or _norm(fm_name) == requested_norm:
                    return md_file
            except Exception:
                continue
    return None

def _get_agent_relpath(filepath: Path) -> str:
    """Get relative path for an agent file from its base dir."""
    for d in _get_agent_dirs():
        try:
            return str(filepath.relative_to(d))
        except ValueError:
            continue
    return filepath.name


def _get_assistant_storage_dir() -> Path:
    """Return assistants storage directory, creating it if needed."""
    assistants_dir = Path(os.path.dirname(os.path.abspath(__file__))).parent / "data" / "assistants"
    assistants_dir.mkdir(parents=True, exist_ok=True)
    return assistants_dir


def _agent_tools_to_assistant_tools(agent_tools: Any) -> List[Dict[str, Any]]:
    """Normalize OpenClaude agent tools to assistant tool objects."""
    tool_names: List[str] = []

    if isinstance(agent_tools, str):
        # Accept either comma-separated strings or single tool names.
        parts = [p.strip() for p in agent_tools.split(",")] if "," in agent_tools else [agent_tools.strip()]
        tool_names.extend([p for p in parts if p])
    elif isinstance(agent_tools, list):
        for item in agent_tools:
            if isinstance(item, str):
                name = item.strip()
                if name:
                    tool_names.append(name)
            elif isinstance(item, dict):
                fn = item.get("function") if isinstance(item.get("function"), dict) else {}
                candidate = fn.get("name") or item.get("name")
                if isinstance(candidate, str) and candidate.strip():
                    tool_names.append(candidate.strip())
    elif isinstance(agent_tools, dict):
        candidate = agent_tools.get("name")
        if isinstance(candidate, str) and candidate.strip():
            tool_names.append(candidate.strip())

    # Deduplicate while preserving order.
    seen = set()
    unique_names = []
    for name in tool_names:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        unique_names.append(name)

    return [
        {
            "type": "function",
            "function": {"name": name}
        }
        for name in unique_names
    ]


# ── Models ─────────────────────────────────────────────────────────────────
class AgentSummary(BaseModel):
    name: str
    description: Optional[str] = ""
    model: Optional[str] = None
    tools: Optional[Any] = None
    path: str = ""
    source_dir: str = ""

class AgentDetail(BaseModel):
    name: str
    description: Optional[str] = ""
    model: Optional[str] = None
    tools: Optional[Any] = None
    disallowedTools: Optional[Any] = None
    permissionMode: Optional[str] = None
    maxTurns: Optional[int] = None
    skills: Optional[Any] = None
    hooks: Optional[Dict] = None
    memory: Optional[str] = None
    background: Optional[bool] = False
    color: Optional[str] = None
    isolation: Optional[str] = None
    paths: Optional[Any] = None
    effort: Optional[Any] = None
    mcpServers: Optional[Any] = None
    initialPrompt: Optional[str] = None
    body: str = ""
    path: str = ""
    source_dir: str = ""

class AgentCreateRequest(BaseModel):
    name: str
    description: str = ""
    model: Optional[str] = None
    tools: Optional[Any] = None
    disallowedTools: Optional[Any] = None
    permissionMode: Optional[str] = None
    maxTurns: Optional[int] = None
    skills: Optional[Any] = None
    hooks: Optional[Dict] = None
    memory: Optional[str] = None
    background: Optional[bool] = False
    color: Optional[str] = None
    isolation: Optional[str] = None
    paths: Optional[Any] = None
    effort: Optional[Any] = None
    mcpServers: Optional[Any] = None
    initialPrompt: Optional[str] = None
    body: str = ""

class AgentRunRequest(BaseModel):
    prompt: str
    model: Optional[str] = None
    max_turns: Optional[int] = None

class AgentValidateRequest(BaseModel):
    content: str


# ── ROUTES ─────────────────────────────────────────────────────────────────

@router.get("/agents")
async def list_agents():
    """List all agent markdown files with parsed frontmatter summaries."""
    agents = []
    for f in _list_agent_files():
        try:
            content = f.read_text(encoding="utf-8")
            parsed = parse_agent_markdown(content)
            fm = parsed["frontmatter"]

            name = fm.get("name") or f.stem
            base_dir = ""
            for d in _get_agent_dirs():
                try:
                    f.relative_to(d)
                    base_dir = str(d)
                    break
                except ValueError:
                    continue

            agents.append(AgentSummary(
                name=name,
                description=fm.get("description", ""),
                model=fm.get("model"),
                tools=fm.get("tools"),
                path=_get_agent_relpath(f),
                source_dir=base_dir,
            ).model_dump())
        except Exception as e:
            logger.warning(f"Error parsing agent file {f}: {e}")

    return {"agents": agents, "count": len(agents)}


@router.get("/agents/{name}")
async def get_agent(name: str):
    """Get full agent details including body content."""
    f = _find_agent_file(name)
    if not f:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    content = f.read_text(encoding="utf-8")
    parsed = parse_agent_markdown(content)
    fm = parsed["frontmatter"]

    agent_name = fm.get("name") or f.stem
    if name != agent_name and not name.endswith(".md"):
        # Try matching by frontmatter name
        pass

    base_dir = ""
    for d in _get_agent_dirs():
        try:
            f.relative_to(d)
            base_dir = str(d)
            break
        except ValueError:
            continue

    return AgentDetail(
        name=agent_name,
        description=fm.get("description", ""),
        model=fm.get("model"),
        tools=fm.get("tools"),
        disallowedTools=fm.get("disallowedTools"),
        permissionMode=fm.get("permissionMode"),
        maxTurns=fm.get("maxTurns"),
        skills=fm.get("skills"),
        hooks=fm.get("hooks"),
        memory=fm.get("memory"),
        background=fm.get("background", False),
        color=fm.get("color"),
        isolation=fm.get("isolation"),
        paths=fm.get("paths"),
        effort=fm.get("effort"),
        mcpServers=fm.get("mcpServers"),
        initialPrompt=fm.get("initialPrompt"),
        body=parsed["body"],
        path=_get_agent_relpath(f),
        source_dir=base_dir,
    ).model_dump()


@router.post("/agents")
async def create_agent(request: AgentCreateRequest):
    """Create a new agent markdown file."""
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="Agent name is required")

    # Build frontmatter
    fm = {"name": request.name.strip()}
    if request.description:
        fm["description"] = request.description
    if request.model:
        fm["model"] = request.model
    if request.tools is not None:
        fm["tools"] = request.tools
    if request.disallowedTools is not None:
        fm["disallowedTools"] = request.disallowedTools
    if request.permissionMode:
        fm["permissionMode"] = request.permissionMode
    if request.maxTurns:
        fm["maxTurns"] = request.maxTurns
    if request.skills is not None:
        fm["skills"] = request.skills
    if request.hooks:
        fm["hooks"] = request.hooks
    if request.memory:
        fm["memory"] = request.memory
    if request.background:
        fm["background"] = True
    if request.color:
        fm["color"] = request.color
    if request.isolation:
        fm["isolation"] = request.isolation
    if request.paths is not None:
        fm["paths"] = request.paths
    if request.effort is not None:
        fm["effort"] = request.effort
    if request.mcpServers is not None:
        fm["mcpServers"] = request.mcpServers
    if request.initialPrompt:
        fm["initialPrompt"] = request.initialPrompt

    # Build markdown content
    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '-', request.name.strip().lower()).strip("-") or "agent"
    write_dir = _get_write_dir()
    filepath = write_dir / f"{safe_name}.md"

    if filepath.exists():
        raise HTTPException(status_code=409, detail=f"Agent file already exists: {filepath.name}")

    content = serialize_agent_markdown(fm, request.body)
    filepath.write_text(content, encoding="utf-8")

    logger.info(f"Created agent: {filepath}")
    return {"success": True, "name": request.name.strip(), "file": str(filepath), "path": _get_agent_relpath(filepath)}


@router.put("/agents/{name}")
async def update_agent(name: str, request: AgentCreateRequest):
    """Update an existing agent markdown file. Merges with existing frontmatter to preserve unedited fields."""
    f = _find_agent_file(name)
    if not f:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    # Load existing frontmatter to preserve advanced fields not in the edit UI
    existing_content = f.read_text(encoding="utf-8")
    existing_parsed = parse_agent_markdown(existing_content)
    existing_fm = existing_parsed.get("frontmatter", {})

    # Merge: incoming fields take precedence, existing fields preserved for anything not sent
    merged = dict(existing_fm)

    # Always update name if provided
    if request.name and request.name.strip():
        merged["name"] = request.name.strip()
    if request.description:
        merged["description"] = request.description
    elif request.description == "" and "description" in merged:
        pass  # keep existing

    if request.model:
        merged["model"] = request.model
    elif request.model == "":
        merged.pop("model", None)

    if request.tools is not None:
        merged["tools"] = request.tools
    if request.disallowedTools is not None:
        merged["disallowedTools"] = request.disallowedTools
    if request.permissionMode:
        merged["permissionMode"] = request.permissionMode
    elif request.permissionMode == "":
        merged.pop("permissionMode", None)
    if request.maxTurns:
        merged["maxTurns"] = request.maxTurns
    if request.skills is not None:
        merged["skills"] = request.skills
    if request.hooks:
        merged["hooks"] = request.hooks
    if request.memory:
        merged["memory"] = request.memory
    elif request.memory == "":
        merged.pop("memory", None)
    if request.background:
        merged["background"] = True
    if request.color:
        merged["color"] = request.color
    elif request.color == "":
        merged.pop("color", None)
    if request.isolation:
        merged["isolation"] = request.isolation
    elif request.isolation == "":
        merged.pop("isolation", None)
    if request.paths is not None:
        merged["paths"] = request.paths
    if request.effort is not None:
        merged["effort"] = request.effort
    if request.mcpServers is not None:
        merged["mcpServers"] = request.mcpServers
    if request.initialPrompt:
        merged["initialPrompt"] = request.initialPrompt
    elif request.initialPrompt == "":
        merged.pop("initialPrompt", None)

    # Use incoming body if provided; otherwise preserve existing
    body = request.body if request.body is not None and request.body != "" else existing_parsed.get("body", "")

    content = serialize_agent_markdown(merged, body)
    f.write_text(content, encoding="utf-8")

    logger.info(f"Updated agent: {f}")
    return {"success": True, "name": merged.get("name", name), "file": str(f)}


@router.delete("/agents/{name}")
async def delete_agent(name: str):
    """Delete an agent markdown file."""
    f = _find_agent_file(name)
    if not f:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    f.unlink()
    logger.info(f"Deleted agent: {f}")
    return {"success": True, "deleted": str(f)}


@router.post("/agents/{name}/run")
async def run_agent(name: str, request: AgentRunRequest):
    """Execute an agent via the openclaude CLI and stream output."""
    f = _find_agent_file(name)
    if not f:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    openclaude_dir = Path(os.path.dirname(os.path.abspath(__file__))).parent / "openclaude"
    if not openclaude_dir.exists():
        raise HTTPException(status_code=500, detail="OpenClaude directory not found")

    # Build the CLI command
    cli_entry = openclaude_dir / "dist" / "cli.mjs"
    if not cli_entry.exists():
        raise HTTPException(status_code=500, detail=f"OpenClaude CLI not found at {cli_entry}")

    prompt = request.prompt
    agent_name = name

    # Construct a prompt that uses the agent
    full_prompt = f"Use the agent '{agent_name}' to: {prompt}"

    cmd = [
        "node", str(cli_entry),
        "-p", full_prompt,
        "--output-format", "text",
    ]

    if request.model:
        cmd.extend(["--model", request.model])

    logger.info(f"Running agent '{name}': {' '.join(cmd[:6])}...")

    async def stream_output():
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(openclaude_dir),
            )
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                yield line.decode("utf-8", errors="replace")

            stderr_data = await proc.stderr.read()
            if stderr_data:
                yield f"\n[stderr]\n{stderr_data.decode('utf-8', errors='replace')}"

            await proc.wait()
            yield f"\n\n[Process exited with code {proc.returncode}]"
        except FileNotFoundError:
            yield "\n[Error: node runtime not found]"
        except Exception as e:
            yield f"\n[Error: {str(e)}]"

    return StreamingResponse(stream_output(), media_type="text/plain")


@router.post("/agents/validate")
async def validate_agent(request: AgentValidateRequest):
    """Validate agent markdown content without saving."""
    errors = []
    warnings = []

    try:
        parsed = parse_agent_markdown(request.content)
        fm = parsed["frontmatter"]

        if not fm.get("name"):
            errors.append("Missing required field: 'name'")
        if not fm.get("description") and not parsed.get("body"):
            warnings.append("No 'description' frontmatter field and no body content")

        # Validate known fields
        valid_fields = {
            "name", "description", "tools", "disallowedTools", "model",
            "permissionMode", "maxTurns", "skills", "hooks", "memory",
            "background", "color", "isolation", "paths", "effort",
            "mcpServers", "initialPrompt",
        }
        unknown = set(fm.keys()) - valid_fields
        if unknown:
            warnings.append(f"Unknown frontmatter fields: {', '.join(sorted(unknown))}")

    except HTTPException as e:
        errors.append(str(e.detail))
    except Exception as e:
        errors.append(f"Parse error: {str(e)}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


@router.post("/agents/import-from-assistant/{assistant_id}")
async def import_from_assistant(assistant_id: str, request: Request):
    """Convert an existing garage assistant (JSON) to an OpenClaude agent markdown file."""
    # Try to load the assistant through the assistants API
    try:
        assistant_path = Path(os.path.dirname(os.path.abspath(__file__))).parent / "data" / "assistants" / f"{assistant_id}.json"
        if not assistant_path.exists():
            raise HTTPException(status_code=404, detail=f"Assistant '{assistant_id}' not found")

        with open(assistant_path, "r") as f:
            assistant = json.load(f)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading assistant: {e}")

    # Convert to agent frontmatter
    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '-', (assistant.get("name") or assistant_id).lower())
    safe_name = safe_name.strip("-")

    fm = {
        "name": safe_name,
        "description": assistant.get("description", f"Imported from garage assistant {assistant_id}"),
    }

    if assistant.get("model"):
        fm["model"] = assistant["model"]
    if assistant.get("tools"):
        fm["tools"] = [t.get("function", {}).get("name", str(t)) if isinstance(t, dict) else str(t) for t in assistant["tools"]]

    # Build system prompt body from instructions
    body_parts = []
    instructions = assistant.get("instructions", "").strip()
    if instructions:
        body_parts.append(instructions)

    if assistant.get("collections"):
        body_parts.append(f"\n## Knowledge Collections\n{', '.join(assistant['collections'])}")

    body = "\n\n".join(body_parts) if body_parts else "You are a helpful assistant."

    # Write the markdown file
    content = serialize_agent_markdown(fm, body)
    write_dir = _get_write_dir()
    filepath = write_dir / f"{safe_name}.md"

    if filepath.exists():
        # Append timestamp to avoid collision
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        filepath = write_dir / f"{safe_name}-{ts}.md"

    filepath.write_text(content, encoding="utf-8")

    logger.info(f"Imported assistant '{assistant_id}' -> agent '{filepath}'")
    return {
        "success": True,
        "name": safe_name,
        "file": str(filepath),
        "path": _get_agent_relpath(filepath),
        "source_assistant": assistant_id,
    }


@router.post("/agents/export-to-assistant/{name}")
async def export_to_assistant(name: str):
    """Convert an OpenClaude markdown agent into a Garage assistant JSON file."""
    f = _find_agent_file(name)
    if not f:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    try:
        content = f.read_text(encoding="utf-8")
        parsed = parse_agent_markdown(content)
        fm = parsed.get("frontmatter") or {}
        body = (parsed.get("body") or "").strip()

        assistant_name = str(fm.get("name") or f.stem).strip() or f.stem
        assistant_description = str(
            fm.get("description") or f"Imported from OpenClaude agent '{assistant_name}'"
        ).strip()

        raw_model = fm.get("model")
        assistant_model = str(raw_model).strip() if isinstance(raw_model, str) and raw_model.strip() else "llama3.1:8b"

        assistant_id = f"asst_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        rel_path = _get_agent_relpath(f)

        metadata: Dict[str, Any] = {
            "source": "openclaude",
            "source_agent_name": assistant_name,
            "source_agent_path": rel_path,
        }
        for key in ("permissionMode", "maxTurns", "memory", "isolation", "skills", "paths"):
            if fm.get(key) is not None:
                metadata[key] = fm.get(key)

        assistant_data = {
            "id": assistant_id,
            "object": "assistant",
            "created_at": int(datetime.now().timestamp()),
            "name": assistant_name,
            "description": assistant_description,
            "model": assistant_model,
            "instructions": body or "You are a helpful assistant.",
            "tools": _agent_tools_to_assistant_tools(fm.get("tools")),
            "file_ids": [],
            "metadata": metadata,
            "language": "en",
            "collections": [],
            "temperature": 0.7,
            "top_p": 1.0,
            "max_tokens": 500,
        }

        assistants_dir = _get_assistant_storage_dir()
        assistant_file = assistants_dir / f"{assistant_id}.json"
        assistant_file.write_text(json.dumps(assistant_data, indent=2), encoding="utf-8")

        logger.info(f"Exported OpenClaude agent '{assistant_name}' -> assistant '{assistant_id}'")
        return {
            "success": True,
            "assistant_id": assistant_id,
            "assistant_name": assistant_name,
            "file": str(assistant_file),
            "source_agent": assistant_name,
            "source_agent_path": rel_path,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to export agent to assistant: {str(e)}")


# ── Import from Markdown content ───────────────────────────────────────────

class AgentImportMarkdownRequest(BaseModel):
    content: str           # raw markdown string (frontmatter + body)
    overwrite: bool = False


@router.post("/agents/import-markdown")
async def import_from_markdown(request: AgentImportMarkdownRequest):
    """Save an agent from raw markdown content (uploaded .md / .agent.md file)."""
    content = request.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Markdown content is required")

    parsed = parse_agent_markdown(content)
    fm = parsed["frontmatter"]
    body = parsed["body"]

    name = fm.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Markdown frontmatter must include a 'name' field")

    # Strip extra fields not part of the canonical openclaude spec so they
    # don't break downstream tooling — preserve them in body comment instead.
    _KNOWN_FM_FIELDS = {
        "name", "description", "tools", "disallowedTools", "model",
        "permissionMode", "maxTurns", "skills", "hooks", "memory",
        "background", "color", "isolation", "paths", "effort",
        "mcpServers", "initialPrompt",
    }
    extra_fields = {k: v for k, v in fm.items() if k not in _KNOWN_FM_FIELDS}
    clean_fm = {k: v for k, v in fm.items() if k in _KNOWN_FM_FIELDS}

    if extra_fields and not body:
        body = ""
    if extra_fields:
        extra_comment = "\n<!-- imported extra frontmatter fields: " + json.dumps(extra_fields) + " -->"
        body = body + extra_comment if body else extra_comment

    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '-', name.strip().lower())
    safe_name = safe_name.strip("-") or "imported-agent"

    write_dir = _get_write_dir()
    filepath = write_dir / f"{safe_name}.md"

    if filepath.exists() and not request.overwrite:
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        filepath = write_dir / f"{safe_name}-{ts}.md"

    out_content = serialize_agent_markdown(clean_fm, body)
    filepath.write_text(out_content, encoding="utf-8")

    logger.info(f"Imported agent from markdown: {filepath}")
    return {
        "success": True,
        "name": clean_fm.get("name", safe_name),
        "file": str(filepath),
        "path": _get_agent_relpath(filepath),
    }


# ── Remote Catalog Proxy (port 8120) ──────────────────────────────────────

_CATALOG_BASE_URL = os.getenv("OPENCLAUDE_CATALOG_BASE_URL", "http://34.44.115.131:8120")
_CATALOG_TIMEOUT = 8  # seconds


def _catalog_url(path: str) -> str:
    clean = "/" + str(path or "").lstrip("/")
    quoted = urllib.parse.quote(clean, safe="/:?=&%.-_")
    return f"{_CATALOG_BASE_URL.rstrip('/')}{quoted}"


def _catalog_fetch(path: str) -> Any:
    """Fetch JSON from remote catalog service."""
    url = _catalog_url(path)
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=_CATALOG_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Catalog HTTP {e.code} for {path}")
    except urllib.error.URLError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Cannot reach catalog at {_CATALOG_BASE_URL}: {e.reason if hasattr(e, 'reason') else str(e)}"
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Catalog fetch error: {str(e)}")


def _catalog_fetch_text(path: str) -> str:
    """Fetch raw text (e.g. .agent.md) from remote catalog service."""
    url = _catalog_url(path)
    try:
        req = urllib.request.Request(url, headers={"Accept": "text/markdown,text/plain,*/*"})
        with urllib.request.urlopen(req, timeout=_CATALOG_TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Catalog HTTP {e.code} for {path}")
    except urllib.error.URLError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Cannot reach catalog at {_CATALOG_BASE_URL}: {e.reason if hasattr(e, 'reason') else str(e)}"
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Catalog text fetch error: {str(e)}")


def _group_agents_from_openclaude_api(agents: list) -> dict:
    """Group OpenClaude native API agents by path prefix/name prefix."""
    groups: dict[str, list] = {}
    for agent in agents:
        path = agent.get("path", "")
        parts = path.replace("\\", "/").split("/")
        if len(parts) > 1:
            group_key = parts[0]
        else:
            name_parts = re.split(r"[-_]", agent.get("name", "unknown"))
            group_key = name_parts[0] if name_parts else "default"
        group_key = group_key.strip() or "default"
        groups.setdefault(group_key, []).append(agent)

    group_list = [
        {"id": k, "name": k.replace("-", " ").replace("_", " ").title(), "agents": v, "count": len(v)}
        for k, v in sorted(groups.items())
    ]
    return {
        "groups": group_list,
        "total_agents": len(agents),
        "source": _CATALOG_BASE_URL,
        "mode": "openclaude-api",
    }


def _catalog_static_groups() -> dict:
    """
    Build catalog using static files from the Agent Architecture workspace.
    This supports deployments where 8120 serves static assets instead of FastAPI.

    Returns an empty (but well-formed) catalog if the remote index is
    unreachable, so callers can fall through to another source instead of 502ing.
    """
    try:
        idx = _catalog_fetch("/agents-groups/_meta/groups.index.json")
    except HTTPException:
        return {
            "groups": [],
            "total_agents": 0,
            "source": _CATALOG_BASE_URL,
            "mode": "static-groups",
        }
    idx = idx if isinstance(idx, dict) else {}
    group_defs = idx.get("groups", [])

    groups_out: list = []
    total = 0

    # Optional meta orchestrator entry in groups.index.json
    meta = idx.get("meta_orchestrator") if isinstance(idx, dict) else None
    if isinstance(meta, dict) and meta.get("agent_file"):
        meta_agent = {
            "name": meta.get("name") or meta.get("slug") or "Meta Orchestrator",
            "slug": meta.get("slug"),
            "description": "Meta orchestration control plane",
            "path": meta.get("agent_file", ""),
            "agent_file": meta.get("agent_file", ""),
            "source_dir": _CATALOG_BASE_URL,
            "group": "meta",
            "role": "orchestrator",
        }
        groups_out.append({
            "id": "meta",
            "name": "Meta",
            "agents": [meta_agent],
            "count": 1,
        })
        total += 1

    for g in group_defs:
        group_id = (g.get("group") or "default").strip() or "default"
        group_name = g.get("label") or group_id.replace("-", " ").replace("_", " ").title()
        manifest_rel = g.get("manifest")
        if not manifest_rel:
            continue

        try:
            manifest = _catalog_fetch(f"/{manifest_rel}")
        except HTTPException as e:
            logger.warning(f"Catalog static manifest load failed for {group_id}: {e.detail}")
            continue

        agents_raw = manifest.get("agents", []) if isinstance(manifest, dict) else []
        mapped: list = []
        for a in agents_raw:
            name = a.get("name") or a.get("slug") or "Unnamed Agent"
            description = a.get("description") or a.get("specialty") or manifest.get("description", "")
            agent_file = a.get("agent_file") or ""
            mapped.append({
                "name": name,
                "slug": a.get("slug"),
                "description": description,
                "path": agent_file,
                "agent_file": agent_file,
                "bundle_file": a.get("bundle_file"),
                "role": a.get("role"),
                "source_dir": _CATALOG_BASE_URL,
                "group": group_id,
            })

        groups_out.append({
            "id": group_id,
            "name": group_name,
            "agents": mapped,
            "count": len(mapped),
        })
        total += len(mapped)

    return {
        "groups": groups_out,
        "total_agents": total,
        "source": _CATALOG_BASE_URL,
        "mode": "static-groups",
    }


def _catalog_resolve_agent(name: str) -> dict:
    """Resolve a catalog agent detail by name/slug from API first, then static fallback."""
    encoded = urllib.parse.quote(str(name), safe="")

    # 1) Preferred: remote OpenClaude API
    try:
        return _catalog_fetch(f"/v1/openclaude/agents/{encoded}")
    except HTTPException:
        pass

    # 2) Fallback: static group manifests + markdown files
    static = _catalog_static_groups()
    needle = str(name).strip().lower()
    for group in static.get("groups", []):
        for agent in group.get("agents", []):
            nm = str(agent.get("name", "")).strip().lower()
            slug = str(agent.get("slug", "")).strip().lower()
            if needle not in {nm, slug}:
                continue

            detail = {
                "name": agent.get("name") or agent.get("slug") or name,
                "description": agent.get("description", ""),
                "model": None,
                "tools": None,
                "disallowedTools": None,
                "permissionMode": None,
                "maxTurns": None,
                "skills": None,
                "hooks": None,
                "memory": None,
                "background": False,
                "color": None,
                "isolation": None,
                "paths": None,
                "effort": None,
                "mcpServers": None,
                "initialPrompt": None,
                "body": "",
                "path": agent.get("agent_file") or agent.get("path") or "",
                "source_dir": _CATALOG_BASE_URL,
            }

            rel_path = detail["path"]
            if rel_path:
                try:
                    md = _catalog_fetch_text(f"/{rel_path}")
                    parsed = parse_agent_markdown(md)
                    fm = parsed.get("frontmatter", {})
                    detail.update({
                        "name": fm.get("name", detail["name"]),
                        "description": fm.get("description", detail["description"]),
                        "model": fm.get("model"),
                        "tools": fm.get("tools"),
                        "disallowedTools": fm.get("disallowedTools"),
                        "permissionMode": fm.get("permissionMode"),
                        "maxTurns": fm.get("maxTurns"),
                        "skills": fm.get("skills"),
                        "hooks": fm.get("hooks"),
                        "memory": fm.get("memory"),
                        "background": fm.get("background", False),
                        "color": fm.get("color"),
                        "isolation": fm.get("isolation"),
                        "paths": fm.get("paths"),
                        "effort": fm.get("effort"),
                        "mcpServers": fm.get("mcpServers"),
                        "initialPrompt": fm.get("initialPrompt"),
                        "body": parsed.get("body", ""),
                    })
                except HTTPException as e:
                    logger.warning(f"Catalog static markdown load failed for {rel_path}: {e.detail}")

            return detail

    raise HTTPException(status_code=404, detail=f"Agent '{name}' not found in catalog")


def _catalog_local_groups() -> dict:
    """
    Build a catalog from locally stored .claude/agents markdown files.
    Used as a last-resort fallback when the remote catalog (port 8120) is
    unreachable, so the endpoint returns local agents instead of a 502.
    """
    groups: dict[str, list] = {}
    for f in _list_agent_files():
        try:
            content = f.read_text(encoding="utf-8")
            parsed = parse_agent_markdown(content)
            fm = parsed.get("frontmatter", {}) or {}
            rel = _get_agent_relpath(f)
            # Derive a group key from the subdirectory (if any), else "local".
            group_key = rel.split("/", 1)[0] if "/" in rel else "local"
            groups.setdefault(group_key, []).append({
                "name": fm.get("name") or f.stem,
                "slug": fm.get("name") or f.stem,
                "description": fm.get("description", ""),
                "path": rel,
                "agent_file": rel,
                "source_dir": "local",
                "group": group_key,
            })
        except Exception as e:
            logger.warning(f"Error parsing local catalog agent {f}: {e}")

    group_list = [
        {"id": k, "name": k.replace("-", " ").replace("_", " ").title(), "agents": v, "count": len(v)}
        for k, v in sorted(groups.items())
    ]
    return {
        "groups": group_list,
        "total_agents": sum(len(v) for v in groups.values()),
        "source": "local",
        "mode": "local",
    }


@router.get("/catalog/agents")
async def catalog_list_agents():
    """
    List all agents available in the catalog.
    Resolution order (graceful degradation, never 502s on network failure):
      1. Remote OpenClaude API (port 8120)
      2. Static Agent Architecture manifests (port 8120)
      3. Locally stored .claude/agents markdown files
    """
    try:
        data = _catalog_fetch("/v1/openclaude/agents")
        agents: list = data.get("agents", []) if isinstance(data, dict) else []
        return _group_agents_from_openclaude_api(agents)
    except HTTPException as api_err:
        logger.info(f"Catalog API mode unavailable, trying static fallback: {api_err.detail}")

    static = _catalog_static_groups()
    if static.get("total_agents"):
        return static

    logger.info("Remote catalog unavailable; serving local agents as fallback.")
    return _catalog_local_groups()


@router.get("/catalog/agents/{name}")
async def catalog_get_agent(name: str):
    """Proxy: fetch full agent detail from remote catalog (API first, static fallback second)."""
    return _catalog_resolve_agent(name)


@router.post("/agents/import-from-catalog/{name}")
async def import_from_catalog(name: str):
    """Fetch a specific agent from the remote catalog and save it locally."""
    agent = _catalog_resolve_agent(name)

    # Re-use import-markdown logic
    fm: dict = {}
    _FIELDS = [
        "name", "description", "model", "tools", "disallowedTools",
        "permissionMode", "maxTurns", "skills", "hooks", "memory",
        "background", "color", "isolation", "paths", "effort",
        "mcpServers", "initialPrompt",
    ]
    for field in _FIELDS:
        val = agent.get(field)
        if val is not None and val != "" and val is not False:
            fm[field] = val
    if not fm.get("name"):
        fm["name"] = name

    body = agent.get("body", "")

    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '-', fm["name"].strip().lower()).strip("-") or "catalog-agent"
    write_dir = _get_write_dir()
    filepath = write_dir / f"{safe_name}.md"
    if filepath.exists():
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        filepath = write_dir / f"{safe_name}-{ts}.md"

    content = serialize_agent_markdown(fm, body)
    filepath.write_text(content, encoding="utf-8")

    logger.info(f"Imported agent '{name}' from catalog -> {filepath}")
    return {
        "success": True,
        "name": fm["name"],
        "file": str(filepath),
        "path": _get_agent_relpath(filepath),
        "source_catalog": _CATALOG_BASE_URL,
    }

