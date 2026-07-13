"""Final-version embedding, vector search, and citation-grounded RAG contracts."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from time import perf_counter
from typing import Literal, Mapping, Protocol, TypeGuard, cast
import hashlib
import re

from chatbi.resilience import RetryPolicy, run_with_retry
from chatbi.trace_events import TraceEventRecorder, TraceEventStatus


DocumentStatus = Literal["active", "deleted", "disabled"]


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    document_id: str
    org_id: str
    title: str
    source_type: str
    owner_user_id: str
    version: str
    access_policy: Mapping[str, object]
    status: DocumentStatus = "active"

    def __post_init__(self) -> None:
        _require_text(self.document_id, "document_id")
        _require_text(self.org_id, "org_id")
        _require_text(self.title, "title")
        _require_text(self.source_type, "source_type")
        _require_text(self.owner_user_id, "owner_user_id")
        _require_text(self.version, "version")


@dataclass(frozen=True, slots=True)
class VectorChunk:
    chunk_id: str
    document_id: str
    org_id: str
    text: str
    token_count: int
    vector_ref: str
    section: str = "body"

    def __post_init__(self) -> None:
        _require_text(self.chunk_id, "chunk_id")
        _require_text(self.document_id, "document_id")
        _require_text(self.org_id, "org_id")
        _require_text(self.text, "text")
        _require_text(self.vector_ref, "vector_ref")
        _require_text(self.section, "section")
        if self.token_count <= 0:
            raise ValueError("token_count must be greater than 0")


@dataclass(frozen=True, slots=True)
class EvidenceChunk:
    chunk_id: str
    document_id: str
    org_id: str
    text: str
    score: float
    citation: Mapping[str, object]

    def __post_init__(self) -> None:
        _require_text(self.chunk_id, "chunk_id")
        _require_text(self.document_id, "document_id")
        _require_text(self.org_id, "org_id")
        _require_text(self.text, "text")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be between 0.0 and 1.0")


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    trace_id: str
    org_id: str
    input_texts: tuple[str, ...]
    model_name: str = "mock-local-embedding"

    def __post_init__(self) -> None:
        if not self.trace_id.startswith("trc_"):
            raise ValueError("trace_id must start with 'trc_'")
        _require_text(self.org_id, "org_id")
        _require_text(self.model_name, "model_name")
        if not self.input_texts:
            raise ValueError("input_texts are required")
        for input_text in self.input_texts:
            _require_text(input_text, "input_text")


@dataclass(frozen=True, slots=True)
class EmbeddingResponse:
    vectors: tuple[tuple[float, ...], ...]
    provider: str
    model_name: str
    dimensions: int
    token_count: int
    estimated_cost: float
    latency_ms: int

    def __post_init__(self) -> None:
        if not self.vectors:
            raise ValueError("vectors are required")
        _require_text(self.provider, "provider")
        _require_text(self.model_name, "model_name")
        if self.dimensions <= 0:
            raise ValueError("dimensions must be greater than 0")
        if any(len(vector) != self.dimensions for vector in self.vectors):
            raise ValueError("all vectors must match dimensions")
        if self.token_count < 0:
            raise ValueError("token_count must be greater than or equal to 0")
        if self.estimated_cost < 0:
            raise ValueError("estimated_cost must be greater than or equal to 0")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be greater than or equal to 0")


class EmbeddingClient(Protocol):
    @property
    def provider_name(self) -> str:
        ...

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        ...


class VectorStore(Protocol):
    def upsert_document(self, document: DocumentRecord) -> None:
        ...

    def get_document(self, document_id: str) -> DocumentRecord | None:
        ...

    def upsert_chunks(
        self,
        chunks: tuple[VectorChunk, ...],
        vectors: tuple[tuple[float, ...], ...],
    ) -> None:
        ...

    def search(
        self,
        *,
        trace_id: str,
        org_id: str,
        query_vector: tuple[float, ...],
        permission_tags: tuple[str, ...],
        limit: int,
    ) -> tuple[EvidenceChunk, ...]:
        ...


@dataclass(slots=True)
class MockEmbeddingClient:
    provider_name: str = "mock"
    dimensions: int = 16
    token_cost_per_1k: float = 0.0

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        started_at = perf_counter()
        vectors = tuple(_text_embedding(text, self.dimensions) for text in request.input_texts)
        token_count = sum(_token_count(text) for text in request.input_texts)
        return EmbeddingResponse(
            vectors=vectors,
            provider=self.provider_name,
            model_name=request.model_name,
            dimensions=self.dimensions,
            token_count=token_count,
            estimated_cost=round(token_count / 1000.0 * self.token_cost_per_1k, 8),
            latency_ms=max(0, int((perf_counter() - started_at) * 1000)),
        )


class ObservableEmbeddingClient:
    def __init__(
        self,
        client: EmbeddingClient,
        trace_event_recorder: TraceEventRecorder | None = None,
    ) -> None:
        self._client = client
        self._trace_event_recorder = trace_event_recorder or TraceEventRecorder(
            service="embedding-gateway"
        )

    @property
    def provider_name(self) -> str:
        return self._client.provider_name

    @property
    def trace_event_recorder(self) -> TraceEventRecorder:
        return self._trace_event_recorder

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        started_event = self._trace_event_recorder.start(
            trace_id=request.trace_id,
            span_name="embedding.embed",
        )
        response = self._client.embed(request)
        self._trace_event_recorder.complete(
            started_event,
            status=TraceEventStatus.SUCCEEDED,
            metadata={
                "org_id": request.org_id,
                "provider": response.provider,
                "model": response.model_name,
                "latency_ms": response.latency_ms,
                "token_count": response.token_count,
                "estimated_cost": response.estimated_cost,
                "input_count": len(request.input_texts),
            },
        )
        return response


class RetryingEmbeddingClient:
    def __init__(
        self,
        client: EmbeddingClient,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._client = client
        self._retry_policy = retry_policy or RetryPolicy()

    @property
    def provider_name(self) -> str:
        return self._client.provider_name

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        return run_with_retry(lambda: self._client.embed(request), self._retry_policy)


class RetryingVectorStore:
    def __init__(
        self,
        vector_store: VectorStore,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._vector_store = vector_store
        self._retry_policy = retry_policy or RetryPolicy()

    def upsert_document(self, document: DocumentRecord) -> None:
        self._vector_store.upsert_document(document)

    def get_document(self, document_id: str) -> DocumentRecord | None:
        return self._vector_store.get_document(document_id)

    def upsert_chunks(
        self,
        chunks: tuple[VectorChunk, ...],
        vectors: tuple[tuple[float, ...], ...],
    ) -> None:
        self._vector_store.upsert_chunks(chunks, vectors)

    def search(
        self,
        *,
        trace_id: str,
        org_id: str,
        query_vector: tuple[float, ...],
        permission_tags: tuple[str, ...],
        limit: int,
    ) -> tuple[EvidenceChunk, ...]:
        return run_with_retry(
            lambda: self._vector_store.search(
                trace_id=trace_id,
                org_id=org_id,
                query_vector=query_vector,
                permission_tags=permission_tags,
                limit=limit,
            ),
            self._retry_policy,
        )


class InMemoryVectorStore:
    def __init__(self, trace_event_recorder: TraceEventRecorder | None = None) -> None:
        self._documents_by_id: dict[str, DocumentRecord] = {}
        self._chunks_by_id: dict[str, VectorChunk] = {}
        self._vectors_by_chunk_id: dict[str, tuple[float, ...]] = {}
        self._trace_event_recorder = trace_event_recorder or TraceEventRecorder(
            service="vector-store"
        )

    @property
    def trace_event_recorder(self) -> TraceEventRecorder:
        return self._trace_event_recorder

    def upsert_document(self, document: DocumentRecord) -> None:
        self._documents_by_id[document.document_id] = document

    def get_document(self, document_id: str) -> DocumentRecord | None:
        return self._documents_by_id.get(document_id)

    def upsert_chunks(
        self,
        chunks: tuple[VectorChunk, ...],
        vectors: tuple[tuple[float, ...], ...],
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        for chunk, vector in zip(chunks, vectors, strict=True):
            document = self._documents_by_id.get(chunk.document_id)
            if document is None:
                raise ValueError(f"Unknown document_id {chunk.document_id}")
            if document.org_id != chunk.org_id:
                raise ValueError("chunk org_id must match document org_id")
            self._chunks_by_id[chunk.chunk_id] = chunk
            self._vectors_by_chunk_id[chunk.chunk_id] = vector

    def search(
        self,
        *,
        trace_id: str,
        org_id: str,
        query_vector: tuple[float, ...],
        permission_tags: tuple[str, ...],
        limit: int,
    ) -> tuple[EvidenceChunk, ...]:
        if not trace_id.startswith("trc_"):
            raise ValueError("trace_id must start with 'trc_'")
        _require_text(org_id, "org_id")
        if not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")

        started_at = perf_counter()
        started_event = self._trace_event_recorder.start(
            trace_id=trace_id,
            span_name="vector.search",
        )
        candidates = tuple(
            chunk
            for chunk in self._chunks_by_id.values()
            if self._allowed_chunk(chunk, org_id=org_id, permission_tags=permission_tags)
        )
        ranked = sorted(
            (
                (
                    chunk,
                    _cosine_similarity(
                        query_vector,
                        self._vectors_by_chunk_id.get(chunk.chunk_id, ()),
                    ),
                )
                for chunk in candidates
            ),
            key=lambda item: (item[1], item[0].document_id, item[0].chunk_id),
            reverse=True,
        )
        evidence = tuple(
            self._to_evidence(chunk, score)
            for chunk, score in ranked[:limit]
            if score > 0.0
        )
        latency_ms = max(0, int((perf_counter() - started_at) * 1000))
        self._trace_event_recorder.complete(
            started_event,
            status=TraceEventStatus.SUCCEEDED,
            metadata={
                "org_id": org_id,
                "provider": "in-memory",
                "latency_ms": latency_ms,
                "candidate_count": len(candidates),
                "returned_count": len(evidence),
            },
        )
        return evidence

    def _allowed_chunk(
        self,
        chunk: VectorChunk,
        *,
        org_id: str,
        permission_tags: tuple[str, ...],
    ) -> bool:
        document = self._documents_by_id.get(chunk.document_id)
        if document is None:
            return False
        if document.org_id != org_id or chunk.org_id != org_id:
            return False
        if document.status != "active":
            return False
        required_tags = _policy_tags(document.access_policy)
        return required_tags.issubset(set(_normalize_tags(permission_tags)))

    def _to_evidence(self, chunk: VectorChunk, score: float) -> EvidenceChunk:
        document = self._documents_by_id[chunk.document_id]
        return EvidenceChunk(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            org_id=chunk.org_id,
            text=chunk.text,
            score=round(score, 4),
            citation={
                "document_id": document.document_id,
                "title": document.title,
                "source_type": document.source_type,
                "version": document.version,
                "section": chunk.section,
                "chunk_id": chunk.chunk_id,
            },
        )


@dataclass(frozen=True, slots=True)
class RagAnswer:
    answer: str
    citations: tuple[Mapping[str, object], ...]
    evidence_chunks: tuple[EvidenceChunk, ...]
    confidence: float
    missing_evidence_warning: str | None = None


class EmbeddingVectorRagService:
    def __init__(
        self,
        embedding_client: EmbeddingClient | None = None,
        vector_store: VectorStore | None = None,
        embedding_model_name: str = "mock-local-embedding",
    ) -> None:
        self._embedding_client = embedding_client or MockEmbeddingClient()
        self._vector_store = vector_store or InMemoryVectorStore()
        self._embedding_model_name = embedding_model_name

    @property
    def embedding_client(self) -> EmbeddingClient:
        return self._embedding_client

    @property
    def vector_store(self) -> VectorStore:
        return self._vector_store

    @property
    def embedding_model_name(self) -> str:
        return self._embedding_model_name

    def index_document(
        self,
        *,
        trace_id: str,
        document: DocumentRecord,
        text: str,
        token_limit: int = 120,
    ) -> tuple[VectorChunk, ...]:
        return ingest_document(
            trace_id=trace_id,
            document=document,
            text=text,
            embedding_client=self._embedding_client,
            vector_store=self._vector_store,
            token_limit=token_limit,
            embedding_model_name=self._embedding_model_name,
        )

    def retrieve(
        self,
        *,
        trace_id: str,
        org_id: str,
        question: str,
        permission_tags: tuple[str, ...],
        limit: int,
    ) -> tuple[EvidenceChunk, ...]:
        query_response = self._embedding_client.embed(
            EmbeddingRequest(
            trace_id=trace_id,
            org_id=org_id,
            input_texts=(question,),
            model_name=self._embedding_model_name,
        )
        )
        return self._vector_store.search(
            trace_id=trace_id,
            org_id=org_id,
            query_vector=query_response.vectors[0],
            permission_tags=permission_tags,
            limit=limit,
        )

    def answer(
        self,
        *,
        trace_id: str,
        org_id: str,
        question: str,
        permission_tags: tuple[str, ...],
        limit: int = 5,
    ) -> RagAnswer:
        evidence = self.retrieve(
            trace_id=trace_id,
            org_id=org_id,
            question=question,
            permission_tags=permission_tags,
            limit=limit,
        )
        return build_citation_grounded_answer(question, evidence)


def build_citation_grounded_answer(
    question: str,
    evidence_chunks: tuple[EvidenceChunk, ...],
) -> RagAnswer:
    _require_text(question, "question")
    if not evidence_chunks:
        return RagAnswer(
            answer="I do not have enough retrieved evidence to answer this question.",
            citations=(),
            evidence_chunks=(),
            confidence=0.0,
            missing_evidence_warning="missing_evidence",
        )

    citations = tuple(chunk.citation for chunk in evidence_chunks)
    answer_parts = tuple(_snippet(chunk.text) for chunk in evidence_chunks)
    return RagAnswer(
        answer=" ".join(answer_parts),
        citations=citations,
        evidence_chunks=evidence_chunks,
        confidence=min(1.0, sum(chunk.score for chunk in evidence_chunks) / len(evidence_chunks)),
    )


def chunk_document(
    document: DocumentRecord,
    text: str,
    *,
    token_limit: int = 120,
) -> tuple[VectorChunk, ...]:
    if token_limit <= 0:
        raise ValueError("token_limit must be greater than 0")
    words = _tokens(text)
    if not words:
        return ()
    chunks: list[VectorChunk] = []
    position = 1
    for start in range(0, len(words), token_limit):
        chunk_words = words[start : start + token_limit]
        chunk_id = f"{document.document_id}_chunk_{position}"
        chunks.append(
            VectorChunk(
                chunk_id=chunk_id,
                document_id=document.document_id,
                org_id=document.org_id,
                text=" ".join(chunk_words),
                token_count=len(chunk_words),
                vector_ref=f"memory://vector/{chunk_id}",
                section=f"section-{position}",
            )
        )
        position += 1
    return tuple(chunks)


def ingest_document(
    *,
    trace_id: str,
    document: DocumentRecord,
    text: str,
    embedding_client: EmbeddingClient,
    vector_store: VectorStore,
    token_limit: int = 120,
    embedding_model_name: str = "mock-local-embedding",
) -> tuple[VectorChunk, ...]:
    chunks = chunk_document(document, text, token_limit=token_limit)
    vector_store.upsert_document(document)
    if not chunks:
        return ()
    response = embedding_client.embed(
        EmbeddingRequest(
            trace_id=trace_id,
            org_id=document.org_id,
            input_texts=tuple(chunk.text for chunk in chunks),
            model_name=embedding_model_name,
        )
    )
    vector_store.upsert_chunks(chunks, response.vectors)
    return chunks


def _text_embedding(text: str, dimensions: int) -> tuple[float, ...]:
    vector = [0.0] * dimensions
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = digest[0] % dimensions
        vector[bucket] += 1.0
    magnitude = sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return tuple(vector)
    return tuple(value / magnitude for value in vector)


def _cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    left_magnitude = sqrt(sum(value * value for value in left))
    right_magnitude = sqrt(sum(value * value for value in right))
    if left_magnitude == 0 or right_magnitude == 0:
        return 0.0
    return max(0.0, sum(a * b for a, b in zip(left, right, strict=True)) / (left_magnitude * right_magnitude))


def _token_count(text: str) -> int:
    return len(_tokens(text))


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9]+", text.lower()))


def _normalize_tags(tags: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({tag.strip().lower() for tag in tags if tag.strip()}))


def _policy_tags(access_policy: Mapping[str, object]) -> set[str]:
    raw_tags = access_policy.get("permission_tags", ())
    if not _is_str_tuple(raw_tags):
        return set()
    return set(_normalize_tags(raw_tags))


def _is_str_tuple(value: object) -> TypeGuard[tuple[str, ...]]:
    if not isinstance(value, tuple):
        return False
    values = cast(tuple[object, ...], value)
    return all(isinstance(item, str) for item in values)


def _snippet(text: str, max_length: int = 240) -> str:
    clean = " ".join(text.split())
    if len(clean) <= max_length:
        return clean
    return f"{clean[: max_length - 3].rstrip()}..."


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} is required")
