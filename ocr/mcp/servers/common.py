#!/usr/bin/env python3
"""Shared helpers for MCP servers in this repository."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Union

PROJECT_ROOT = Path(
    os.getenv("OCR_PROJECT_ROOT", Path(__file__).resolve().parents[2])
).resolve()


def _parse_allowed_roots() -> tuple:
    """Roots the MCP servers may read/write.

    ``PROJECT_ROOT`` is always allowed. Additional roots can be granted through
    ``OCR_ALLOWED_ROOTS`` (``os.pathsep``-separated) so that the servers can
    operate on workspace directories without relocating the project root.
    """
    roots = [PROJECT_ROOT]
    for raw in os.getenv("OCR_ALLOWED_ROOTS", "").split(os.pathsep):
        candidate = raw.strip()
        if candidate:
            resolved = Path(candidate).expanduser().resolve()
            if resolved not in roots:
                roots.append(resolved)
    return tuple(roots)


ALLOWED_ROOTS = _parse_allowed_roots()


def add_project_root_to_path() -> None:
    """Ensure project scripts are importable by server wrappers."""
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def resolve_project_path(path_value: str) -> Path:
    """Resolve relative/absolute path and ensure it stays inside an allowed root."""
    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate

    resolved = candidate.resolve()

    for root in ALLOWED_ROOTS:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue

    raise ValueError(
        "Path must be inside an allowed root: "
        f"{[str(root) for root in ALLOWED_ROOTS]}. Got: {resolved}"
    )


def to_relative(path_value: Union[str, Path]) -> str:
    """Convert a path to the shortest allowed-root-relative format possible."""
    path = Path(path_value).resolve()
    for root in ALLOWED_ROOTS:
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return str(path)


def load_json(path_value: Union[str, Path]) -> Dict[str, Any]:
    with open(path_value, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path_value: Union[str, Path], payload: Dict[str, Any]) -> None:
    target = Path(path_value)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def error_payload(error: Exception) -> Dict[str, Any]:
    return {
        "ok": False,
        "error_type": type(error).__name__,
        "error": str(error),
    }


def get_deepseek_api_key() -> str:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY is required in environment variables")
    return api_key


def apply_deepseek_base_url(module: Any) -> None:
    """Override module-level DeepSeek URL for request-based clients when supported."""
    base_url = os.getenv("DEEPSEEK_API_BASE_URL", "").strip()
    if base_url and hasattr(module, "DEEPSEEK_API_URL"):
        module.DEEPSEEK_API_URL = base_url
