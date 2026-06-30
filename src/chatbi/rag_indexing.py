"""Deterministic document indexing helpers for RAG v2.

The real production version will persist documents, chunks, and embedding
metadata to PostgreSQL. This module keeps the same shape in memory so the
indexing behavior is easy to test and understand first.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from chatbi.rag import (
    EmbeddingMetadata,
    IndexDocumentRequest,
    IndexJob,
    IndexJobStatus,
    RagChunk,
    RagDocument,
    normalize_tags,
)


DEFAULT_CHUNK_TOKEN_LIMIT = 120
DEFAULT_CHUNK_OVERLAP = 20
DEFAULT_EMBEDDING_DIMENSIONS = 16
DEFAULT_EMBEDDING_MODEL_NAME = "mock-local-embedding"
DEFAULT_EMBEDDING_MODEL_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class ChunkSettings:
    token_limit: int = DEFAULT_CHUNK_TOKEN_LIMIT
    overlap: int = DEFAULT_CHUNK_OVERLAP

    def __post_init__(self) -> None:
        if self.token_limit < 1:
            raise ValueError("token_limit must be greater than or equal to 1")
        if self.overlap < 0:
            raise ValueError("overlap must be greater than or equal to 0")
        if self.overlap >= self.token_limit:
            raise ValueError("overlap must be smaller than token_limit")


@dataclass(frozen=True, slots=True)
class IndexArtifacts:
    document: RagDocument
    chunks: tuple[RagChunk, ...]
    embedding_metadata: tuple[EmbeddingMetadata, ...]
    job: IndexJob


def build_index_artifacts(
    request: IndexDocumentRequest,
    chunk_settings: ChunkSettings = ChunkSettings(),
) -> IndexArtifacts:
    """Build deterministic indexing artifacts for one document.

    For short documents we create chunks immediately and mark the job
    ``succeeded``. For documents above the spec's 50,000 character boundary we
    only create a queued job, because those must be picked up by a worker.
    """

    document = document_from_request(request)
    if request.requires_async_indexing:
        return IndexArtifacts(
            document=document,
            chunks=(),
            embedding_metadata=(),
            job=IndexJob.queued(request.document_id),
        )

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
    job = IndexJob(
        job_id=f"rag_job_{request.document_id}",
        document_id=request.document_id,
        status=IndexJobStatus.SUCCEEDED,
    )
    return IndexArtifacts(
        document=document,
        chunks=chunks,
        embedding_metadata=embeddings,
        job=job,
    )


def document_from_request(request: IndexDocumentRequest) -> RagDocument:
    return RagDocument(
        document_id=request.document_id,
        source=request.source,
        title=request.title,
        document_type=request.document_type,
        published_at=request.published_at,
        business_tags=normalize_tags(request.business_tags),
        permission_tags=normalize_tags(request.permission_tags),
    )


def chunk_document_text(
    document_id: str,
    text: str,
    chunk_settings: ChunkSettings = ChunkSettings(),
) -> tuple[RagChunk, ...]:
    words = clean_document_text(text).split()
    if not words:
        return ()

    chunks: list[RagChunk] = []
    start = 0
    position = 1
    while start < len(words):
        end = min(start + chunk_settings.token_limit, len(words))
        chunk_words = tuple(words[start:end])
        chunks.append(
            RagChunk(
                chunk_id=f"{document_id}_chunk_{position}",
                document_id=document_id,
                position=position,
                text=" ".join(chunk_words),
                token_count=len(chunk_words),
            )
        )
        if end == len(words):
            break
        start = end - chunk_settings.overlap
        position += 1

    return tuple(chunks)


def clean_document_text(text: str) -> str:
    """Make whitespace stable while preserving the document's words."""

    return re.sub(r"\s+", " ", text).strip()
