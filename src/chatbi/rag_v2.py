"""Public facade for the RAG v2 architecture slice.

The implementation is split across focused modules so each file stays teachable.
This facade gives callers one stable import path for the complete RAG v2 flow.
"""

from chatbi.rag import (
    DocumentType,
    EmbeddingMetadata,
    EvidenceEvent,
    EvidenceItem,
    EvidenceSearchRequest,
    EvidenceSearchResult,
    IndexDocumentRequest,
    IndexJob,
    IndexJobStatus,
    RagChunk,
    RagDocument,
    RagWarningCode,
    TimeWindow,
    normalize_tags,
    permission_tags_allowed,
)
from chatbi.rag_answering import RagAnswer, RagAnsweringService
from chatbi.rag_benchmark import (
    RagRetrievalBenchmarkResult,
    build_mock_rag_service,
    run_retrieval_benchmark,
)
from chatbi.rag_explanation import (
    DocumentSupportedClaim,
    RagExplanation,
    build_rag_explanation,
    validate_rag_explanation,
)
from chatbi.rag_hydration import RagHydrationResult, hydrate_evidence_store_from_repository
from chatbi.rag_indexing import (
    ChunkSettings,
    IndexArtifacts,
    build_index_artifacts,
    chunk_document_text,
    clean_document_text,
    document_from_request,
)
from chatbi.rag_postgres_rows import RAG_V2_TABLES_SQL
from chatbi.rag_repository import (
    InMemoryRagRepository,
    PostgresRagRepository,
    PsycopgRagConnection,
    RagPostgresConnection,
    RagRepository,
    postgres_rag_repository_from_psycopg,
)
from chatbi.rag_retrieval import InMemoryRagEvidenceStore, StoredChunk
from chatbi.rag_service import InMemoryRagService, RagServiceState
from chatbi.rag_worker import RagIndexWorker, RagIndexWorkerError, RagIndexWorkerResult


__all__ = [
    "ChunkSettings",
    "DocumentSupportedClaim",
    "DocumentType",
    "EmbeddingMetadata",
    "EvidenceEvent",
    "EvidenceItem",
    "EvidenceSearchRequest",
    "EvidenceSearchResult",
    "IndexArtifacts",
    "IndexDocumentRequest",
    "IndexJob",
    "IndexJobStatus",
    "InMemoryRagEvidenceStore",
    "InMemoryRagRepository",
    "InMemoryRagService",
    "PostgresRagRepository",
    "PsycopgRagConnection",
    "RAG_V2_TABLES_SQL",
    "RagAnswer",
    "RagAnsweringService",
    "RagChunk",
    "RagDocument",
    "RagExplanation",
    "RagHydrationResult",
    "RagIndexWorker",
    "RagIndexWorkerError",
    "RagIndexWorkerResult",
    "RagPostgresConnection",
    "RagRepository",
    "RagRetrievalBenchmarkResult",
    "RagServiceState",
    "RagWarningCode",
    "StoredChunk",
    "TimeWindow",
    "build_index_artifacts",
    "build_mock_rag_service",
    "build_rag_explanation",
    "chunk_document_text",
    "clean_document_text",
    "document_from_request",
    "hydrate_evidence_store_from_repository",
    "normalize_tags",
    "permission_tags_allowed",
    "postgres_rag_repository_from_psycopg",
    "run_retrieval_benchmark",
    "validate_rag_explanation",
]
