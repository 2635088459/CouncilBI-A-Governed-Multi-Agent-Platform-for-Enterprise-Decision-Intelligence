"""Small service facade for the RAG v2 workflow.

The lower-level modules each do one job:
- ``rag.py`` defines the data contracts;
- ``rag_indexing.py`` turns document text into index artifacts;
- ``rag_retrieval.py`` searches permitted evidence.

This service wires those pieces together so callers can use one simple API.
"""

from __future__ import annotations

from dataclasses import dataclass

from chatbi.rag import (
    EmbeddingMetadata,
    EvidenceEvent,
    EvidenceSearchRequest,
    EvidenceSearchResult,
    IndexDocumentRequest,
    IndexJob,
    IndexJobStatus,
)
from chatbi.rag_indexing import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_EMBEDDING_MODEL_NAME,
    DEFAULT_EMBEDDING_MODEL_VERSION,
    ChunkSettings,
    IndexArtifacts,
    build_index_artifacts,
    chunk_document_text,
    document_from_request,
)
from chatbi.rag_repository import InMemoryRagRepository, RagRepository
from chatbi.rag_retrieval import InMemoryRagEvidenceStore


@dataclass(frozen=True, slots=True)
class RagServiceState:
    indexed_document_count: int
    indexed_chunk_count: int
    job_count: int


class InMemoryRagService:
    """Coordinate document indexing, worker completion, and evidence search."""

    def __init__(self, repository: RagRepository | None = None) -> None:
        self._evidence_store = InMemoryRagEvidenceStore()
        self._repository = repository or InMemoryRagRepository()
        self._artifacts_by_document_id: dict[str, IndexArtifacts] = {}
        self._queued_requests_by_job_id: dict[str, IndexDocumentRequest] = {}

    @property
    def repository(self) -> RagRepository:
        return self._repository

    def index_document(
        self,
        request: IndexDocumentRequest,
        chunk_settings: ChunkSettings = ChunkSettings(),
    ) -> IndexJob:
        artifacts = build_index_artifacts(request, chunk_settings)

        if artifacts.job.status is IndexJobStatus.QUEUED:
            self._queued_requests_by_job_id[artifacts.job.job_id] = request
            self._artifacts_by_document_id[request.document_id] = artifacts
            self._repository.save_index_artifacts(artifacts)
            return artifacts.job

        self._artifacts_by_document_id[request.document_id] = artifacts
        self._repository.save_index_artifacts(artifacts)
        self._evidence_store.add_artifacts(artifacts)
        return artifacts.job

    def run_index_job(
        self,
        job_id: str,
        chunk_settings: ChunkSettings = ChunkSettings(),
    ) -> IndexJob:
        job = self._require_job(job_id)
        if job.status is not IndexJobStatus.QUEUED:
            return job

        running_job = IndexJob(
            job_id=job.job_id,
            document_id=job.document_id,
            status=IndexJobStatus.RUNNING,
        )
        self._repository.save_job(running_job)

        request = self._queued_requests_by_job_id[job_id]
        try:
            artifacts = self._build_worker_artifacts(
                request=request,
                job_id=job_id,
                chunk_settings=chunk_settings,
            )
        except ValueError as exc:
            failed_job = IndexJob(
                job_id=job.job_id,
                document_id=job.document_id,
                status=IndexJobStatus.FAILED,
                error_message=str(exc),
            )
            self._repository.save_job(failed_job)
            return failed_job

        self._artifacts_by_document_id[request.document_id] = artifacts
        self._repository.save_index_artifacts(artifacts)
        self._queued_requests_by_job_id.pop(job_id, None)
        self._evidence_store.add_artifacts(artifacts)
        return artifacts.job

    def search_evidence(self, request: EvidenceSearchRequest) -> EvidenceSearchResult:
        result = self._evidence_store.search(request)
        self._repository.save_evidence_events(
            self._evidence_store.evidence_events_by_trace_id(request.trace_id)
        )
        return result

    def evidence_events_by_trace_id(self, trace_id: str) -> tuple[EvidenceEvent, ...]:
        return self._repository.list_evidence_events_by_trace_id(trace_id)

    def job_by_id(self, job_id: str) -> IndexJob:
        return self._require_job(job_id)

    def state(self) -> RagServiceState:
        return RagServiceState(
            indexed_document_count=len(self._repository.list_documents()),
            indexed_chunk_count=len(self._repository.list_chunks()),
            job_count=len(tuple(artifacts.job for artifacts in self._artifacts_by_document_id.values())),
        )

    def _require_job(self, job_id: str) -> IndexJob:
        job = self._repository.job_by_id(job_id)
        if job is None:
            raise ValueError(f"Unknown RAG index job {job_id}")
        return job

    def _build_worker_artifacts(
        self,
        request: IndexDocumentRequest,
        job_id: str,
        chunk_settings: ChunkSettings,
    ) -> IndexArtifacts:
        document = document_from_request(request)
        chunks = chunk_document_text(
            document_id=request.document_id,
            text=request.text,
            chunk_settings=chunk_settings,
        )
        embeddings = tuple(
            EmbeddingMetadata(
                embedding_id=f"{chunk.chunk_id}_embedding",
                chunk_id=chunk.chunk_id,
                model_name=DEFAULT_EMBEDDING_MODEL_NAME,
                model_version=DEFAULT_EMBEDDING_MODEL_VERSION,
                dimensions=DEFAULT_EMBEDDING_DIMENSIONS,
            )
            for chunk in chunks
        )
        succeeded_job = IndexJob(
            job_id=job_id,
            document_id=request.document_id,
            status=IndexJobStatus.SUCCEEDED,
        )
        return IndexArtifacts(
            document=document,
            chunks=chunks,
            embedding_metadata=embeddings,
            job=succeeded_job,
        )
