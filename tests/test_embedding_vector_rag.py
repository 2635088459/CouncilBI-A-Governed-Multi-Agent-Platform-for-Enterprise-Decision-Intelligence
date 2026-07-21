from time import perf_counter

import pytest

from chatbi.embedding_vector_rag import (
    DocumentRecord,
    DocumentStatus,
    EmbeddingClient,
    EmbeddingVectorRagService,
    EmbeddingRequest,
    EmbeddingResponse,
    EvidenceChunk,
    InMemoryVectorStore,
    MockEmbeddingClient,
    ObservableEmbeddingClient,
    RetryingEmbeddingClient,
    RetryingVectorStore,
    VectorChunk,
    VectorStore,
    build_citation_grounded_answer,
    chunk_document,
    ingest_document,
)
from chatbi.core.runtime_config import RuntimeConfig
from chatbi.embedding_vector_config import (
    OpenAIEmbeddingClient,
    build_embedding_vector_rag_service_from_runtime_config,
    build_knowledge_store_embedding_client,
)
from chatbi.resilience import RetryPolicy
from chatbi.trace_events import TraceEventRecorder, TraceEventStatus


class FlakyEmbeddingClient:
    provider_name = "flaky"

    def __init__(self, delegate: EmbeddingClient) -> None:
        self._delegate = delegate
        self.call_count = 0

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self.call_count += 1
        if self.call_count == 1:
            raise RuntimeError("transient embedding failure")
        return self._delegate.embed(request)


class FlakyVectorStore:
    def __init__(self, delegate: VectorStore) -> None:
        self._delegate = delegate
        self.search_call_count = 0

    def upsert_document(self, document: DocumentRecord) -> None:
        self._delegate.upsert_document(document)

    def upsert_chunks(
        self,
        chunks: tuple[VectorChunk, ...],
        vectors: tuple[tuple[float, ...], ...],
    ) -> None:
        self._delegate.upsert_chunks(chunks, vectors)

    def search(
        self,
        *,
        trace_id: str,
        org_id: str,
        query_vector: tuple[float, ...],
        permission_tags: tuple[str, ...],
        limit: int,
    ) -> tuple[EvidenceChunk, ...]:
        self.search_call_count += 1
        if self.search_call_count == 1:
            raise RuntimeError("transient vector search failure")
        return self._delegate.search(
            trace_id=trace_id,
            org_id=org_id,
            query_vector=query_vector,
            permission_tags=permission_tags,
            limit=limit,
        )


def make_document(
    document_id: str = "doc_revenue_policy",
    org_id: str = "org_a",
    status: DocumentStatus = "active",
) -> DocumentRecord:
    return DocumentRecord(
        document_id=document_id,
        org_id=org_id,
        title="Revenue Policy",
        source_type="policy",
        owner_user_id="u_owner",
        version="v1",
        access_policy={"permission_tags": ("finance",)},
        status=status,
    )


def test_chunker_preserves_document_org_section_and_token_count() -> None:
    document = make_document()

    chunks = chunk_document(
        document,
        "Revenue recognition policy requires approved finance evidence.",
        token_limit=3,
    )

    assert len(chunks) == 3
    assert chunks[0].document_id == "doc_revenue_policy"
    assert chunks[0].org_id == "org_a"
    assert chunks[0].section == "section-1"
    assert chunks[0].token_count == 3
    assert chunks[0].vector_ref == "memory://vector/doc_revenue_policy_chunk_1"


def test_mock_embedding_provider_returns_stable_vectors() -> None:
    client = MockEmbeddingClient(dimensions=8)
    request = EmbeddingRequest(
        trace_id="trc_embed_stable",
        org_id="org_a",
        input_texts=("revenue policy", "revenue policy"),
    )

    first = client.embed(request)
    second = client.embed(request)

    assert first.vectors == second.vectors
    assert first.vectors[0] == first.vectors[1]
    assert first.provider == "mock"
    assert first.dimensions == 8
    assert first.token_count == 4


def test_retrying_embedding_client_retries_transient_failure_with_backoff() -> None:
    sleeps: list[float] = []
    flaky = FlakyEmbeddingClient(MockEmbeddingClient(dimensions=8))
    client = RetryingEmbeddingClient(
        flaky,
        RetryPolicy(max_attempts=2, backoff_seconds=0.1, sleeper=sleeps.append),
    )

    response = client.embed(
        EmbeddingRequest(
            trace_id="trc_retry_embedding",
            org_id="org_a",
            input_texts=("revenue policy",),
        )
    )

    assert flaky.call_count == 2
    assert sleeps == [0.1]
    assert response.provider == "mock"
    assert response.dimensions == 8


def test_ingest_document_embeds_chunks_and_search_returns_evidence() -> None:
    embedding_client = MockEmbeddingClient()
    vector_store = InMemoryVectorStore()
    document = make_document()

    chunks = ingest_document(
        trace_id="trc_vector_ingest",
        document=document,
        text="Revenue recognition depends on signed contracts and finance approval.",
        embedding_client=embedding_client,
        vector_store=vector_store,
        token_limit=20,
    )
    query_vector = embedding_client.embed(
        EmbeddingRequest(
            trace_id="trc_vector_query",
            org_id="org_a",
            input_texts=("finance approval revenue",),
        )
    ).vectors[0]

    evidence = vector_store.search(
        trace_id="trc_vector_search",
        org_id="org_a",
        query_vector=query_vector,
        permission_tags=("finance",),
        limit=3,
    )

    assert len(chunks) == 1
    assert len(evidence) == 1
    assert evidence[0].document_id == document.document_id
    assert evidence[0].citation["chunk_id"] == evidence[0].chunk_id
    assert evidence[0].citation["title"] == "Revenue Policy"


def test_retrying_vector_store_retries_transient_search_failure_with_backoff() -> None:
    sleeps: list[float] = []
    embedding_client = MockEmbeddingClient()
    delegate = InMemoryVectorStore()
    flaky = FlakyVectorStore(delegate)
    vector_store = RetryingVectorStore(
        flaky,
        RetryPolicy(max_attempts=2, backoff_seconds=0.1, sleeper=sleeps.append),
    )
    document = make_document()
    ingest_document(
        trace_id="trc_retry_vector_ingest",
        document=document,
        text="Revenue recognition depends on signed contracts and finance approval.",
        embedding_client=embedding_client,
        vector_store=vector_store,
        token_limit=20,
    )
    query_vector = embedding_client.embed(
        EmbeddingRequest(
            trace_id="trc_retry_vector_query",
            org_id="org_a",
            input_texts=("finance approval revenue",),
        )
    ).vectors[0]

    evidence = vector_store.search(
        trace_id="trc_retry_vector_search",
        org_id="org_a",
        query_vector=query_vector,
        permission_tags=("finance",),
        limit=3,
    )

    assert flaky.search_call_count == 2
    assert sleeps == [0.1]
    assert len(evidence) == 1


def test_tenant_a_search_cannot_return_tenant_b_chunks() -> None:
    embedding_client = MockEmbeddingClient()
    vector_store = InMemoryVectorStore()
    ingest_document(
        trace_id="trc_tenant_a_ingest",
        document=make_document(document_id="doc_a", org_id="org_a"),
        text="Revenue evidence for tenant A.",
        embedding_client=embedding_client,
        vector_store=vector_store,
    )
    ingest_document(
        trace_id="trc_tenant_b_ingest",
        document=make_document(document_id="doc_b", org_id="org_b"),
        text="Revenue evidence for tenant B.",
        embedding_client=embedding_client,
        vector_store=vector_store,
    )
    query_vector = embedding_client.embed(
        EmbeddingRequest(
            trace_id="trc_tenant_query",
            org_id="org_a",
            input_texts=("revenue evidence",),
        )
    ).vectors[0]

    evidence = vector_store.search(
        trace_id="trc_tenant_search",
        org_id="org_a",
        query_vector=query_vector,
        permission_tags=("finance",),
        limit=10,
    )

    assert {chunk.org_id for chunk in evidence} == {"org_a"}
    assert {chunk.document_id for chunk in evidence} == {"doc_a"}


def test_deleted_document_chunks_are_excluded() -> None:
    embedding_client = MockEmbeddingClient()
    vector_store = InMemoryVectorStore()
    ingest_document(
        trace_id="trc_deleted_ingest",
        document=make_document(status="deleted"),
        text="Revenue evidence should not be visible.",
        embedding_client=embedding_client,
        vector_store=vector_store,
    )
    query_vector = embedding_client.embed(
        EmbeddingRequest(
            trace_id="trc_deleted_query",
            org_id="org_a",
            input_texts=("revenue evidence",),
        )
    ).vectors[0]

    evidence = vector_store.search(
        trace_id="trc_deleted_search",
        org_id="org_a",
        query_vector=query_vector,
        permission_tags=("finance",),
        limit=5,
    )

    assert evidence == ()


def test_rag_answer_contains_citations_matching_returned_chunks() -> None:
    embedding_client = MockEmbeddingClient()
    vector_store = InMemoryVectorStore()
    ingest_document(
        trace_id="trc_citation_ingest",
        document=make_document(),
        text="Revenue recognition needs finance approval.",
        embedding_client=embedding_client,
        vector_store=vector_store,
    )
    query_vector = embedding_client.embed(
        EmbeddingRequest(
            trace_id="trc_citation_query",
            org_id="org_a",
            input_texts=("finance approval",),
        )
    ).vectors[0]
    evidence = vector_store.search(
        trace_id="trc_citation_search",
        org_id="org_a",
        query_vector=query_vector,
        permission_tags=("finance",),
        limit=2,
    )

    answer = build_citation_grounded_answer("What supports revenue recognition?", evidence)

    assert answer.missing_evidence_warning is None
    assert answer.evidence_chunks == evidence
    assert answer.citations == tuple(chunk.citation for chunk in evidence)
    assert answer.confidence > 0


def test_no_evidence_returns_missing_evidence_warning_without_citations() -> None:
    answer = build_citation_grounded_answer("What supports revenue recognition?", ())

    assert answer.citations == ()
    assert answer.evidence_chunks == ()
    assert answer.confidence == 0.0
    assert answer.missing_evidence_warning == "missing_evidence"


def test_embedding_and_search_events_include_trace_org_latency_and_provider_metadata() -> None:
    embedding_recorder = TraceEventRecorder(service="embedding-gateway")
    vector_recorder = TraceEventRecorder(service="vector-store")
    embedding_client = ObservableEmbeddingClient(
        MockEmbeddingClient(),
        trace_event_recorder=embedding_recorder,
    )
    vector_store = InMemoryVectorStore(trace_event_recorder=vector_recorder)
    document = make_document()

    ingest_document(
        trace_id="trc_observed_ingest",
        document=document,
        text="Revenue recognition needs finance approval.",
        embedding_client=embedding_client,
        vector_store=vector_store,
    )
    query_response = embedding_client.embed(
        EmbeddingRequest(
            trace_id="trc_observed_query",
            org_id="org_a",
            input_texts=("finance approval",),
        )
    )
    vector_store.search(
        trace_id="trc_observed_search",
        org_id="org_a",
        query_vector=query_response.vectors[0],
        permission_tags=("finance",),
        limit=2,
    )

    embedding_event = embedding_recorder.store.list_by_trace_id("trc_observed_ingest")[-1]
    search_event = vector_recorder.store.list_by_trace_id("trc_observed_search")[-1]

    assert embedding_event.status is TraceEventStatus.SUCCEEDED
    assert embedding_event.metadata["org_id"] == "org_a"
    assert embedding_event.metadata["provider"] == "mock"
    embedding_latency = embedding_event.metadata["latency_ms"]
    assert isinstance(embedding_latency, int)
    assert embedding_latency >= 0
    assert search_event.status is TraceEventStatus.SUCCEEDED
    assert search_event.metadata["org_id"] == "org_a"
    assert search_event.metadata["provider"] == "in-memory"
    search_latency = search_event.metadata["latency_ms"]
    assert isinstance(search_latency, int)
    assert search_latency >= 0


def test_vector_search_p95_over_10000_mock_chunks_is_under_500ms() -> None:
    embedding_client = MockEmbeddingClient()
    vector_store = InMemoryVectorStore()
    document = make_document(document_id="doc_benchmark")
    text = " ".join(f"revenue benchmark chunk {index}" for index in range(10_000))
    ingest_document(
        trace_id="trc_benchmark_ingest",
        document=document,
        text=text,
        embedding_client=embedding_client,
        vector_store=vector_store,
        token_limit=3,
    )
    query_vector = embedding_client.embed(
        EmbeddingRequest(
            trace_id="trc_benchmark_query",
            org_id="org_a",
            input_texts=("revenue benchmark",),
        )
    ).vectors[0]

    latencies_ms: list[float] = []
    for index in range(5):
        started_at = perf_counter()
        evidence = vector_store.search(
            trace_id=f"trc_benchmark_search_{index}",
            org_id="org_a",
            query_vector=query_vector,
            permission_tags=("finance",),
            limit=5,
        )
        latencies_ms.append((perf_counter() - started_at) * 1000)
        assert evidence

    p95_ms = sorted(latencies_ms)[-1]
    assert p95_ms <= 500


def test_embedding_vector_rag_service_indexes_retrieves_and_answers() -> None:
    service = EmbeddingVectorRagService()
    document = make_document(document_id="doc_service")

    chunks = service.index_document(
        trace_id="trc_service_index",
        document=document,
        text="Revenue recognition needs finance approval and signed contracts.",
    )
    evidence = service.retrieve(
        trace_id="trc_service_retrieve",
        org_id="org_a",
        question="What supports revenue recognition?",
        permission_tags=("finance",),
        limit=3,
    )
    answer = service.answer(
        trace_id="trc_service_answer",
        org_id="org_a",
        question="What supports revenue recognition?",
        permission_tags=("finance",),
    )

    assert len(chunks) == 1
    assert len(evidence) == 1
    assert answer.missing_evidence_warning is None
    assert answer.citations == tuple(chunk.citation for chunk in answer.evidence_chunks)


def test_runtime_config_builds_memory_embedding_vector_rag_service() -> None:
    service = build_embedding_vector_rag_service_from_runtime_config(
        RuntimeConfig(
            vector_store_url="memory://local-vector-store",
            embedding_model="mock-embedding-v2",
        )
    )

    assert service is not None
    assert service.embedding_model_name == "mock-embedding-v2"


def test_runtime_config_returns_no_vector_rag_service_when_vector_store_is_missing() -> None:
    assert build_embedding_vector_rag_service_from_runtime_config(RuntimeConfig()) is None


def test_build_knowledge_store_embedding_client_returns_openai_client_for_openai_provider() -> None:
    # TC-FV03-018 / AC-FV03-012: same provider switch, same model value, as
    # the vector-only pipeline's OpenAIEmbeddingClient construction.
    client = build_knowledge_store_embedding_client(
        RuntimeConfig(embedding_provider="openai", embedding_model="text-embedding-3-large")
    )

    assert isinstance(client, OpenAIEmbeddingClient)
    assert client._model == "text-embedding-3-large"  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


def test_build_knowledge_store_embedding_client_returns_none_for_mock_provider() -> None:
    # TC-FV03-019: "mock" means "let embed_text() fall back to
    # text_embedding()", not "construct a client that produces mock vectors".
    assert build_knowledge_store_embedding_client(RuntimeConfig(embedding_provider="mock")) is None


def test_build_knowledge_store_embedding_client_rejects_unsupported_provider() -> None:
    # TC-FV03-020: matches build_embedding_vector_rag_service_from_runtime_config's
    # existing "fail configuration explicitly" convention for an unknown provider.
    with pytest.raises(ValueError, match="Unsupported embedding provider"):
        build_knowledge_store_embedding_client(RuntimeConfig(embedding_provider="unsupported"))
