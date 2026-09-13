from __future__ import annotations

from pathlib import Path

import pytest

from violation_pack import HtmlTranscriptSource, MarkdownFrameworkSource

DATA_DIR = Path(__file__).parent.parent / "data"
TRANSCRIPT_FIXTURE = DATA_DIR / "transcripts" / "html" / "I-002_05_NAR-07_STG_7_post_removal_investigation.html"
FRAMEWORK_FIXTURE = DATA_DIR / "law" / "CL" / "CHIPENCOD_CP.md"


@pytest.fixture
def transcript():
    return HtmlTranscriptSource(
        path=TRANSCRIPT_FIXTURE,
        source_id="STG-7",
        bundle_uri="Transcripts/timeline_aeropuerto_STG_7.html",
    )


@pytest.fixture
def framework():
    return MarkdownFrameworkSource(
        path=FRAMEWORK_FIXTURE,
        framework_code="CHIPENCOD",
        bundle_uri="Legal framework/CHIPENCOD_CP.md",
    )
