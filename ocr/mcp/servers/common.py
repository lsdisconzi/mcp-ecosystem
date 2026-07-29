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


def add_project_root_to_path() -> None:
    """Ensure project scripts are importable by server wrappers."""
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def resolve_project_path(path_value: str) -> Path:
    """Resolve relative/absolute path and ensure it stays inside project root."""
    candidate = Path(path_value)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate

    resolved = candidate.resolve()

    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(
            f"Path must be inside project root: {PROJECT_ROOT}. Got: {resolved}"
        ) from exc

    return resolved


def to_relative(path_value: Union[str, Path]) -> str:
    """Convert a path to project-relative format when possible."""
    path = Path(path_value).resolve()
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
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
