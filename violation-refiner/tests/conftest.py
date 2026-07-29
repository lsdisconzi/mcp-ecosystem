from __future__ import annotations

from pathlib import Path

import pytest

from violation_pack import HtmlTranscriptSource, MarkdownFrameworkSource

FIXTURE_DIR = Path(__file__).parent.parent / "examples" / "cl005_source"


@pytest.fixture
def transcript():
    return HtmlTranscriptSource(
        path=FIXTURE_DIR / "timeline_aeropuerto_STG_7.html",
        source_id="STG-7",
        bundle_uri="Transcripts/timeline_aeropuerto_STG_7.html",
    )


@pytest.fixture
def framework():
    return MarkdownFrameworkSource(
        path=FIXTURE_DIR / "CHIPENCOD_CP.md",
        framework_code="CHIPENCOD",
        bundle_uri="Legal framework/CHIPENCOD_CP.md",
    )
