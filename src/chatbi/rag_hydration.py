"""Hydrate RAG retrieval state from repository rows.

Repositories persist documents and chunks. The in-memory evidence store is the
fast local retrieval view. This module bridges the two so a service can rebuild
that retrieval view from already-persisted rows.
"""

from __future__ import annotations

from dataclasses import dataclass

from chatbi.rag import IndexJob, IndexJobStatus, RagChunk, RagDocument
from chatbi.rag_indexing import IndexArtifacts
from chatbi.rag_repository import RagRepository
from chatbi.rag_retrieval import InMemoryRagEvidenceStore


@dataclass(frozen=True, slots=True)
class RagHydrationResult:
    document_count: int
    chunk_count: int
    skipped_chunk_count: int


def hydrate_evidence_store_from_repository(
    repository: RagRepository,
    evidence_store: InMemoryRagEvidenceStore,
) -> RagHydrationResult:
    """Load persisted documents and chunks into an evidence store."""

    documents_by_id = {
        document.document_id: document
        for document in repository.list_documents()
    }
    chunks_by_document_id = _group_chunks_by_document_id(repository.list_chunks())

    loaded_chunk_count = 0
    skipped_chunk_count = 0
    for document_id, chunks in chunks_by_document_id.items():
        document = documents_by_id.get(document_id)
        if document is None:
            skipped_chunk_count += len(chunks)
            continue
        evidence_store.add_artifacts(_artifacts_for_hydration(document, chunks))
        loaded_chunk_count += len(chunks)

    return RagHydrationResult(
        document_count=len(documents_by_id),
        chunk_count=loaded_chunk_count,
        skipped_chunk_count=skipped_chunk_count,
    )


def _group_chunks_by_document_id(chunks: tuple[RagChunk, ...]) -> dict[str, tuple[RagChunk, ...]]:
    grouped: dict[str, list[RagChunk]] = {}
    for chunk in chunks:
        grouped.setdefault(chunk.document_id, []).append(chunk)
    return {
        document_id: tuple(sorted(document_chunks, key=lambda chunk: chunk.position))
        for document_id, document_chunks in grouped.items()
    }


def _artifacts_for_hydration(
    document: RagDocument,
    chunks: tuple[RagChunk, ...],
) -> IndexArtifacts:
    return IndexArtifacts(
        document=document,
        chunks=chunks,
        embedding_metadata=(),
        job=IndexJob(
            job_id=f"rag_hydration_{document.document_id}",
            document_id=document.document_id,
            status=IndexJobStatus.SUCCEEDED,
        ),
    )
