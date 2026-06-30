from chatbi.rag_v2 import (
    EvidenceSearchRequest,
    InMemoryRagService,
    IndexDocumentRequest,
    IndexJobStatus,
    RagAnsweringService,
    RagHydrationResult,
    RagIndexWorker,
    RagIndexWorkerError,
    RagIndexWorkerResult,
    RagRetrievalBenchmarkResult,
    RagWarningCode,
    build_index_artifacts,
    build_mock_rag_service,
    hydrate_evidence_store_from_repository,
    permission_tags_allowed,
    run_retrieval_benchmark,
)


def test_rag_v2_public_facade_exports_core_workflow_objects() -> None:
    assert EvidenceSearchRequest.__name__ == "EvidenceSearchRequest"
    assert IndexDocumentRequest.__name__ == "IndexDocumentRequest"
    assert InMemoryRagService.__name__ == "InMemoryRagService"
    assert RagAnsweringService.__name__ == "RagAnsweringService"
    assert RagHydrationResult.__name__ == "RagHydrationResult"
    assert RagIndexWorker.__name__ == "RagIndexWorker"
    assert RagIndexWorkerError.__name__ == "RagIndexWorkerError"
    assert RagIndexWorkerResult.__name__ == "RagIndexWorkerResult"
    assert RagRetrievalBenchmarkResult.__name__ == "RagRetrievalBenchmarkResult"
    assert IndexJobStatus.QUEUED.value == "queued"
    assert RagWarningCode.NO_EVIDENCE.value == "RAG_NO_EVIDENCE"
    assert build_index_artifacts.__name__ == "build_index_artifacts"
    assert build_mock_rag_service.__name__ == "build_mock_rag_service"
    assert hydrate_evidence_store_from_repository.__name__ == "hydrate_evidence_store_from_repository"
    assert run_retrieval_benchmark.__name__ == "run_retrieval_benchmark"
    assert permission_tags_allowed(("sales",), ("sales", "admin")) is True
