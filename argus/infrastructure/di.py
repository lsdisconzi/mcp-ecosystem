# -*- coding: utf-8 -*-
"""
infrastructure/di.py

Dependency injection factory.
Constructs and wires infrastructure implementations to application services.
Import from here in app.py rather than instantiating things directly in routes.
"""
from application.services.analyzer_pack_builder import AnalyzerPackBuilder
from application.services.framework_build_service import FrameworkBuildService
from infrastructure.ai.deepseek_proxy_client import DeepseekProxyClient
from infrastructure.law.law_registry import LawRegistry
from infrastructure.parsers.integrated_parser_adapter import IntegratedParserAdapter
from infrastructure.pdf.pdf_extractor import PdfExtractor
from infrastructure.storage.file_system_storage import FileSystemStorage


def build_law_registry() -> LawRegistry:
    """Return a LawRegistry backed by data/law/."""
    return LawRegistry()


def build_framework_build_service() -> FrameworkBuildService:
    """Return a fully wired FrameworkBuildService."""
    parser = IntegratedParserAdapter()
    return FrameworkBuildService(parser=parser)


def build_pdf_extractor() -> PdfExtractor:
    return PdfExtractor()


def build_deepseek_client(endpoint: str = None) -> DeepseekProxyClient:
    kwargs = {}
    if endpoint:
        kwargs["endpoint"] = endpoint
    return DeepseekProxyClient(**kwargs)


def build_storage() -> FileSystemStorage:
    return FileSystemStorage()


def build_analyzer_pack_builder() -> AnalyzerPackBuilder:
    """Return an AnalyzerPackBuilder backed by the canonical law registry."""
    return AnalyzerPackBuilder(law_registry=build_law_registry())
