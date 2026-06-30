from datetime import datetime, timezone

from chatbi.rag import (
    EmbeddingMetadata,
    EvidenceEvent,
    EvidenceSearchRequest,
    IndexDocumentRequest,
    IndexJob,
    RagChunk,
    RagDocument,
)
from chatbi.rag_hydration import hydrate_evidence_store_from_repository
from chatbi.rag_indexing import build_index_artifacts
from chatbi.rag_repository import InMemoryRagRepository
from chatbi.rag_retrieval import InMemoryRagEvidenceStore


PUBLISHED_AT = datetime(2026, 6, 1, tzinfo=timezone.utc)


class OrphanChunkRepository:
    def __init__(self, chunks: tuple[RagChunk, ...]) -> None:
        self._chunks = chunks

    def save_index_artifacts(self, artifacts: object) -> None:
        raise NotImplementedError

    def save_job(self, job: IndexJob) -> None:
        raise NotImplementedError

    def document_by_id(self, document_id: str) -> RagDocument | None:
        return None

    def chunk_by_id(self, chunk_id: str) -> RagChunk | None:
        return next((chunk for chunk in self._chunks if chunk.chunk_id == chunk_id), None)

    def job_by_id(self, job_id: str) -> IndexJob | None:
        return None

    def list_documents(self) -> tuple[RagDocument, ...]:
        return ()

    def list_chunks(self) -> tuple[RagChunk, ...]:
        return self._chunks

    def list_embedding_metadata(self) -> tuple[EmbeddingMetadata, ...]:
        return ()

    def save_evidence_events(self, events: tuple[EvidenceEvent, ...]) -> None:
        raise NotImplementedError

    def list_evidence_events_by_trace_id(self, trace_id: str) -> tuple[EvidenceEvent, ...]:
        return ()


def test_rag_hydration_loads_repository_rows_into_evidence_store() -> None:
    repository = InMemoryRagRepository()
    repository.save_index_artifacts(
        build_index_artifacts(
            IndexDocumentRequest(
                document_id="doc_hydrate_001",
                source="release-notes",
                title="Hydration release note",
                document_type="release_note",
                published_at=PUBLISHED_AT,
                business_tags=("revenue",),
                permission_tags=("sales",),
                text="Revenue dropped after campaign spend paused.",
            )
        )
    )
    evidence_store = InMemoryRagEvidenceStore()

    hydration = hydrate_evidence_store_from_repository(repository, evidence_store)
    result = evidence_store.search(
        EvidenceSearchRequest(
            trace_id="trc_hydration",
            query_text="Why did revenue drop?",
            time_window=None,
            business_tags=("revenue",),
            permission_tags=("sales",),
            limit=5,
        )
    )

    assert hydration.document_count == 1
    assert hydration.chunk_count == 1
    assert hydration.skipped_chunk_count == 0
    assert tuple(evidence.document_id for evidence in result.evidence_list) == ("doc_hydrate_001",)


def test_rag_hydration_skips_chunks_without_documents() -> None:
    repository = InMemoryRagRepository()
    artifacts = build_index_artifacts(
        IndexDocumentRequest(
            document_id="doc_missing_later",
            source="release-notes",
            title="Missing document release note",
            document_type="release_note",
            published_at=PUBLISHED_AT,
            business_tags=("revenue",),
            permission_tags=("sales",),
            text="Revenue dropped after campaign spend paused.",
        )
    )
    repository.save_index_artifacts(artifacts)
    orphan_repository = OrphanChunkRepository(repository.list_chunks())

    hydration = hydrate_evidence_store_from_repository(
        orphan_repository,
        InMemoryRagEvidenceStore(),
    )

    assert hydration.document_count == 0
    assert hydration.chunk_count == 0
    assert hydration.skipped_chunk_count == 1
