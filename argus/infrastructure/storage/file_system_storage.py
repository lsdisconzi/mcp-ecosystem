# -*- coding: utf-8 -*-
"""
infrastructure/storage/file_system_storage.py

Concrete IStorageAdapter backed by the local file system.
"""
import json
import os
from typing import Any, Dict

from domain.interfaces.i_storage_adapter import IStorageAdapter


class FileSystemStorage(IStorageAdapter):
    """Reads and writes files on the local file system."""

    def write_text(self, path: str, content: str, encoding: str = "utf-8") -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
        with open(path, "w", encoding=encoding) as f:
            f.write(content)

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        with open(path, "r", encoding=encoding) as f:
            return f.read()

    def write_json(self, path: str, data: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def read_json(self, path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def exists(self, path: str) -> bool:
        return os.path.exists(path)
