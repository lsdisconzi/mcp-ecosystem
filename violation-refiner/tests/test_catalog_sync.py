"""Guards against drift in the hand-maintained MCP catalog.

`violation_pack/mcp_catalog.py` lists server/tool/env metadata by hand. This
module turns that maintenance burden into a test failure by deriving the truth
from the source instead:

  * tool names are read from `mcp_server.py` via AST (no `mcp` dependency,
    no async event loop, no import side effects),
  * env var names are read from `config.py` via AST.

If a tool is added to the server without being catalogued, or the catalog
advertises a tool that no longer exists, these tests fail.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from violation_pack.mcp_catalog import (
    catalog,
    to_claude_desktop_snippet,
    to_vscode_mcp_snippet,
)

PKG_DIR = Path(__file__).parent.parent / "violation_pack"
SERVER_PATH = PKG_DIR / "mcp_server.py"
CONFIG_PATH = PKG_DIR / "config.py"

EXPECTED_TOOL_COUNT = 39

# Read by `mcp_server.main()` rather than by `Settings.from_env()`.
TRANSPORT_ENV = {"MCP_TRANSPORT", "MCP_HOST", "MCP_PORT"}


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _is_mcp_tool_decorator(node: ast.expr) -> bool:
    """Match `@mcp.tool()` (with or without arguments)."""
    target = node.func if isinstance(node, ast.Call) else node
    return (
        isinstance(target, ast.Attribute)
        and target.attr == "tool"
        and isinstance(target.value, ast.Name)
        and target.value.id == "mcp"
    )


def _server_tool_names() -> list[str]:
    names: list[str] = []
    for node in ast.walk(_parse(SERVER_PATH)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(_is_mcp_tool_decorator(d) for d in node.decorator_list):
                names.append(node.name)
    return names


def _string_literals(path: Path) -> set[str]:
    """Every all-caps-ish string literal in the file (env var names)."""
    out: set[str] = set()
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if value and value.replace("_", "").isalnum() and value.upper() == value:
                out.add(value)
    return out


# ---------------------------------------------------------------------------
# Tool list
# ---------------------------------------------------------------------------

def test_catalog_tool_names_match_server():
    catalogued = {t["name"] for t in catalog()["servers"][0]["tools"]}
    server = set(_server_tool_names())

    missing = server - catalogued
    extra = catalogued - server

    assert not missing, f"tools exist in mcp_server.py but not in the catalog: {sorted(missing)}"
    assert not extra, f"catalog advertises tools absent from mcp_server.py: {sorted(extra)}"


def test_catalog_tool_count():
    tools = catalog()["servers"][0]["tools"]
    assert len(tools) == EXPECTED_TOOL_COUNT
    assert len(_server_tool_names()) == EXPECTED_TOOL_COUNT


def test_catalog_tool_names_are_unique():
    names = [t["name"] for t in catalog()["servers"][0]["tools"]]
    assert len(names) == len(set(names))


def test_every_catalogued_tool_has_description_and_tags():
    for tool in catalog()["servers"][0]["tools"]:
        assert tool["description"].strip(), f"{tool['name']} has no description"
        assert tool["tags"], f"{tool['name']} has no tags"


def test_destructive_tools_are_tagged():
    destructive = {"qdrant_reset_collections_tool", "neo4j_reset_database_tool"}
    tagged = {
        t["name"]
        for t in catalog()["servers"][0]["tools"]
        if "destructive" in t["tags"]
    }
    assert tagged == destructive


# ---------------------------------------------------------------------------
# Environment surface
# ---------------------------------------------------------------------------

def test_catalog_env_vars_are_real():
    """Every env var the catalog advertises must actually be read by the code.

    This is the check that would have caught the stale `EMBEDDING_MODEL` /
    `EMBEDDING_DIM` entries, which no module ever read.
    """
    known = _string_literals(CONFIG_PATH) | TRANSPORT_ENV
    entry = catalog()["servers"][0]

    advertised = set(entry["env"]) | set(entry["optional_env"])
    unknown = {v for v in advertised if v not in known}

    assert not unknown, f"catalog advertises env vars no module reads: {sorted(unknown)}"


def test_catalog_env_vars_are_unique():
    entry = catalog()["servers"][0]
    optional = entry["optional_env"]
    assert len(optional) == len(set(optional))

    # A var should be either required-ish or optional, not listed twice over.
    overlap = set(entry["env"]) & set(optional)
    assert not overlap, f"env vars listed as both required and optional: {sorted(overlap)}"


def test_catalog_covers_all_credentials():
    """Provider keys and store credentials must be discoverable from the catalog."""
    advertised = set(catalog()["servers"][0]["optional_env"])
    for var in [
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "QDRANT_URL",
        "NEO4J_URI",
        "AUTHORITY_VERIFICATION_FLOOR",
    ]:
        assert var in advertised, f"{var} missing from the catalog"


# ---------------------------------------------------------------------------
# .env.example
# ---------------------------------------------------------------------------

ENV_EXAMPLE = Path(__file__).parent.parent / ".env.example"

# 31 `Settings.from_env()` variables + MCP_TRANSPORT / MCP_HOST / MCP_PORT.
EXPECTED_ENV_EXAMPLE_COUNT = 34


def _env_example_keys() -> list[str]:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    return re.findall(r"^([A-Z][A-Z0-9_]*)=", text, flags=re.MULTILINE)


def test_env_example_exists():
    assert ENV_EXAMPLE.is_file(), ".env.example is whitelisted in .gitignore but missing"


def test_env_example_vars_are_real():
    """No documented variable may be one the code never reads."""
    known = _string_literals(CONFIG_PATH) | TRANSPORT_ENV
    unknown = [k for k in _env_example_keys() if k not in known]
    assert not unknown, f".env.example documents vars no module reads: {unknown}"


def test_env_example_has_no_duplicates():
    keys = _env_example_keys()
    assert len(keys) == len(set(keys))


def test_env_example_count():
    assert len(_env_example_keys()) == EXPECTED_ENV_EXAMPLE_COUNT


# ---------------------------------------------------------------------------
# Snippet generators
# ---------------------------------------------------------------------------

def test_vscode_snippet_shape():
    snippet = to_vscode_mcp_snippet(python="/usr/bin/python3")
    server = snippet["mcp"]["servers"]["violation-pack"]

    assert server["type"] == "stdio"
    assert server["command"] == "/usr/bin/python3"
    assert server["args"] == ["-m", "violation_pack.mcp_server"]
    assert "env" in server


def test_claude_snippet_shape():
    snippet = to_claude_desktop_snippet(python="/usr/bin/python3")
    server = snippet["mcpServers"]["violation-pack"]

    assert server["command"] == "/usr/bin/python3"
    assert server["args"] == ["-m", "violation_pack.mcp_server"]
    assert "env" in server


def test_catalog_is_json_serializable():
    import json

    json.dumps(catalog())


def test_catalog_cli_formats(capsys):
    from violation_pack.mcp_catalog import main

    for fmt in ("catalog", "vscode", "claude"):
        assert main(["--format", fmt]) == 0
        assert capsys.readouterr().out.strip()

    with pytest.raises(SystemExit):
        main(["--format", "not-a-format"])
