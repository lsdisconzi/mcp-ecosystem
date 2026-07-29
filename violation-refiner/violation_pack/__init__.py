"""violation_pack — layered enrichment + validation for legal violation files.

Public API (stable):
    Models
        Violation, EvidenceSegment, CachedArticle, CandidateArticle,
        ArticleElementGrid, Element, NexusEntry, Authority,
        OpenQuestion, CrossReference, Incident, ProvenanceEntry,
        ConfidenceDerivation, CheckResult, ValidationReport

    Sources
        HtmlTranscriptSource, MarkdownFrameworkSource,
        TranscriptSource (Protocol), FrameworkSource (Protocol)

    Layers (each is a candidate MCP tool)
        build_evidence_layer        - Layer 1
        build_norms_layer           - Layer 2
        add_element_grid            - Layer 3
        build_nexus_layer           - Layer 4
        add_authority_stub          - Layer 5

    Confidence
        derive_confidence
        attach_confidence

    Validation
        run_pipeline
        DEFAULT_PIPELINE

    Packaging
        write_violation_json
        build_manifest
        zip_bundle
        copy_source_into_bundle

    Extensions (Protocols only — implementations live elsewhere)
        JurisprudenceProvider, VectorIndex, KnowledgeGraph
"""
from .models import (
    Authority,
    ArticleElementGrid,
    CachedArticle,
    CandidateArticle,
    CheckResult,
    ConfidenceDerivation,
    CrossReference,
    Element,
    EvidenceSegment,
    Incident,
    NexusEntry,
    OpenQuestion,
    ProvenanceEntry,
    ValidationReport,
    VerificationProvenance,
    Violation,
)
from .sources import (
    FrameworkSource,
    HtmlTranscriptSource,
    MarkdownFrameworkSource,
    TranscriptSource,
)
from .layers import (
    add_authority_stub,
    add_element_grid,
    build_evidence_layer,
    build_nexus_layer,
    build_norms_layer,
)
from .authority_verification import (
    VerificationError,
    verify_human_attested,
    verify_statute_external_fetch,
    verify_statute_in_bundle,
)
from .confidence import attach_confidence, derive_confidence
from .validation import DEFAULT_PIPELINE, run_pipeline
from .pack import (
    build_manifest,
    copy_source_into_bundle,
    write_violation_json,
    zip_bundle,
)
from .extensions import JurisprudenceProvider, KnowledgeGraph, VectorIndex
from .ingesters import (
    FrameworkIngester,
    IngestStats,
    JurisprudenceIngester,
    TranscriptIngester,
)
from .config import Settings, load_dotenv

__version__ = "0.1.0"


def get_vector_index(settings: Settings | None = None):
    """Construct a `QdrantVectorIndex` from environment settings.
    Raises RuntimeError if QDRANT_URL is not configured. Imports qdrant-client
    lazily, so the function only fails when actually called."""
    s = settings or Settings.from_env()
    if not s.qdrant_url:
        raise RuntimeError(
            "QDRANT_URL is not set. Configure .env or pass a custom Settings."
        )
    from .qdrant_index import QdrantVectorIndex

    return QdrantVectorIndex(
        url=s.qdrant_url,
        api_key=s.qdrant_api_key,
        collection_prefix=s.qdrant_collection_prefix,
    )


def get_knowledge_graph(settings: Settings | None = None):
    """Construct a `Neo4jKnowledgeGraph` from environment settings."""
    s = settings or Settings.from_env()
    if not (s.neo4j_uri and s.neo4j_user and s.neo4j_password):
        raise RuntimeError(
            "NEO4J_LOCAL_URI / NEO4J_LOCAL_USER / NEO4J_LOCAL_PASS must be set."
        )
    from .neo4j_graph import Neo4jKnowledgeGraph

    return Neo4jKnowledgeGraph(
        uri=s.neo4j_uri,
        user=s.neo4j_user,
        password=s.neo4j_password,
        database=s.neo4j_database,
    )


def get_jurisprudence_provider(settings: Settings | None = None):
    """Construct a `QdrantJurisprudenceProvider` from environment settings."""
    from .jurisprudence import QdrantJurisprudenceProvider

    return QdrantJurisprudenceProvider(index=get_vector_index(settings))


__all__ = [
    # models
    "Authority", "ArticleElementGrid", "CachedArticle", "CandidateArticle",
    "CheckResult", "ConfidenceDerivation", "CrossReference", "Element",
    "EvidenceSegment", "Incident", "NexusEntry", "OpenQuestion",
    "ProvenanceEntry", "ValidationReport", "VerificationProvenance", "Violation",
    # authority verification
    "VerificationError", "verify_statute_in_bundle",
    "verify_statute_external_fetch", "verify_human_attested",
    # sources
    "FrameworkSource", "HtmlTranscriptSource", "MarkdownFrameworkSource", "TranscriptSource",
    # layers
    "add_authority_stub", "add_element_grid", "build_evidence_layer",
    "build_nexus_layer", "build_norms_layer",
    # confidence
    "attach_confidence", "derive_confidence",
    # validation
    "DEFAULT_PIPELINE", "run_pipeline",
    # packaging
    "build_manifest", "copy_source_into_bundle", "write_violation_json", "zip_bundle",
    # extensions
    "JurisprudenceProvider", "KnowledgeGraph", "VectorIndex",
    # ingesters
    "FrameworkIngester", "IngestStats", "JurisprudenceIngester", "TranscriptIngester",
    # config / factories
    "Settings", "load_dotenv",
    "get_vector_index", "get_knowledge_graph", "get_jurisprudence_provider",
]
