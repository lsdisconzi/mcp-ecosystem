"""Tool registry — single source of truth for registered tools.

Exposes the ``registry`` singleton used by the API and assistant layers
(``garge/api/tools.py``, ``garge/main.py``, ``garge/core/assistant.py``,
``garge/api/chat.py``).

User-defined tools are persisted as JSON files under ``data/tools/user_defined``
and loaded on startup. The registry exposes OpenAI-style function schemas so
LLM tool calling can discover and execute them.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from data.tools.json_tool import JsonTool

logger = logging.getLogger(__name__)

USER_TOOLS_DIR = Path(__file__).resolve().parent / "user_defined"


class ToolResult:
    """Result wrapper returned by registry.execute()."""

    def __init__(self, success: bool, data: Any = None, error: str = ""):
        self.success = success
        self.data = data
        self.error = error

    def __repr__(self) -> str:
        return (
            f"<ToolResult success={self.success} "
            f"data={self.data!r} error={self.error!r}>"
        )


class ToolRegistry:
    """In-memory registry backed by user-defined JSON tool files."""

    def __init__(self, tools_dir: Path = USER_TOOLS_DIR):
        self._tools: Dict[str, JsonTool] = {}
        self._tools_dir = tools_dir
        self._load_user_tools()

    # -- lifecycle ---------------------------------------------------
    def _load_user_tools(self) -> None:
        self._tools_dir.mkdir(parents=True, exist_ok=True)
        loaded = 0
        for path in sorted(self._tools_dir.glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                tool = JsonTool(data)
                self._tools[tool.name] = tool
                loaded += 1
            except Exception as exc:  # noqa: BLE001 - keep registry resilient
                logger.warning("Skipping tool file %s: %s", path, exc)
        if loaded:
            logger.info(
                "Loaded %d user-defined tool(s) from %s", loaded, self._tools_dir
            )

    # -- queries -----------------------------------------------------
    def list_tools(self) -> List[str]:
        """Return sorted tool names."""
        return sorted(self._tools)

    def get(self, tool_name: str) -> Optional[JsonTool]:
        """Return the tool by name, or None."""
        return self._tools.get(tool_name)

    def get_schemas(self) -> List[Dict[str, Any]]:
        """Return all tools as OpenAI-format function schemas."""
        return [tool.to_schema() for tool in self._tools.values()]

    # -- mutations ---------------------------------------------------
    def register(self, tool: JsonTool) -> None:
        """Register (or replace) a tool in memory."""
        self._tools[tool.name] = tool
        logger.info("Registered tool '%s'", tool.name)

    def unregister(self, tool_name: str) -> None:
        """Remove a tool from memory (does not delete its JSON file)."""
        self._tools.pop(tool_name, None)

    # -- execution ---------------------------------------------------
    async def execute(self, tool_name: str, **parameters: Any) -> ToolResult:
        """Execute a registered tool with the given parameters."""
        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(False, error=f"Tool '{tool_name}' not found")
        try:
            data = await tool.execute(**parameters)
            return ToolResult(True, data=data)
        except Exception as exc:  # noqa: BLE001 - surface errors to caller
            logger.exception("Tool '%s' execution failed", tool_name)
            return ToolResult(False, error=str(exc))


# Singleton used across the API and assistant layers.
registry = ToolRegistry()
