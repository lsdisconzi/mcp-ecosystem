"""
Backward-compatibility shim for api:app.

New code should import from modules.* directly.
This module re-exports `app` plus internal symbols consumed
by test_integration.py and any other legacy importers.
"""

from main import app  # noqa: F401

# Re-export symbols that legacy code imports from `api`
from modules.courts import (  # noqa: F401
    _resolve_court,
    _get_scraper_class,
    COURT_NAMES,
    SUPPORTED_COURTS,
)
from modules.system_prompt import _build_system_prompt  # noqa: F401
