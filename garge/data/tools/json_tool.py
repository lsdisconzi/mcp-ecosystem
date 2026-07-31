"""JsonTool - wraps a user-defined JSON tool definition.

Expected JSON shape (as written by POST /v1/tools):

    {
      "name": "...",
      "description": "...",
      "parameters": { ... JSON Schema object ... },
      "action": {"type": "python", "code": "result = ..."}
    }

Action types:
  - "python": code string executed with ``params`` (dict) and ``json`` in scope.
              Assign ``result`` in the code to return a value.
  - "http":   performs an HTTP request; ``url`` may contain {param} placeholders.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Any, Dict

logger = logging.getLogger(__name__)


class JsonTool:
    """Tool loaded from a JSON definition file."""

    def __init__(self, data: Dict[str, Any]):
        self.data = data
        fn = data.get("function", {})
        self.name = data.get("name") or fn.get("name")
        if not self.name:
            raise ValueError("Tool definition is missing 'name'")
        self.description = data.get("description") or fn.get("description", "")
        self.parameters = data.get("parameters") or fn.get("parameters", {})
        if not isinstance(self.parameters, dict):
            raise ValueError("Tool 'parameters' must be a JSON Schema object")
        self.action = data.get("action", {"type": "python", "code": "result = None"})

    def to_schema(self) -> Dict[str, Any]:
        """Return the OpenAI-format function schema for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def execute(self, **params: Any) -> Any:
        """Execute the tool action with the given parameters."""
        action_type = self.action.get("type", "python")
        if action_type == "http":
            return self._execute_http(params)
        return self._execute_python(params)

    def _execute_python(self, params: Dict[str, Any]) -> Any:
        code = self.action.get("code", "result = None")
        if not isinstance(code, str):
            raise ValueError("Tool 'python' action requires a 'code' string")
        namespace: Dict[str, Any] = {"params": params, "json": json}
        exec(code, namespace, namespace)
        return namespace.get("result")

    def _execute_http(self, params: Dict[str, Any]) -> Any:
        method = self.action.get("method", "GET").upper()
        url = self.action.get("url", "")
        if not url:
            raise ValueError("Tool 'http' action requires a 'url'")
        for key, value in params.items():
            url = url.replace("{" + key + "}", urllib.parse.quote(str(value)))
        req = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
