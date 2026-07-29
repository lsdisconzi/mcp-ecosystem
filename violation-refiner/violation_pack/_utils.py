"""Shared utilities for the violation_pack package."""
from __future__ import annotations

import hashlib


def sha256_text(s: str) -> str:
    """Return the SHA-256 hex digest of a string."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()
