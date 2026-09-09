# -*- coding: utf-8 -*-
"""
domain/interfaces/i_storage_adapter.py

Abstract interface for storage operations.
Allows swapping file system, S3, or database storage without
changing domain or application code.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict


class IStorageAdapter(ABC):
    """Storage contract used by the application layer."""

    @abstractmethod
    def write_text(self, path: str, content: str, encoding: str = "utf-8") -> None:
        """Write text content to the given path."""
        ...

    @abstractmethod
    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        """Read text content from the given path."""
        ...

    @abstractmethod
    def write_json(self, path: str, data: Dict[str, Any]) -> None:
        """Serialize data as JSON and write to path."""
        ...

    @abstractmethod
    def read_json(self, path: str) -> Dict[str, Any]:
        """Read and parse a JSON file from path."""
        ...

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Return True if the path exists."""
        ...
