"""PostgreSQL row mapping for RAG v2.

This module is deliberately database-driver free. It defines the table DDL and
the conversion between typed Python contracts and PostgreSQL-shaped rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, cast

from chatbi.rag import (
    DocumentType,
    EmbeddingMetadata,
    EvidenceEvent,
    IndexJob,
    IndexJobStatus,
    RagChunk,
    RagDocument,
    normalize_tags,
)


RAG_V2_TABLES_SQL = """
CREATE SCHEMA IF NOT EXISTS rag;

CREATE TABLE IF NOT EXISTS rag.documents (
    document_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    document_type TEXT NOT NULL CHECK (
        document_type IN (
            'weekly_report',
            'release_note',
            'campaign',
            'ticket',
            'incident',
            'finance_report'
        )
    ),
    published_at TIMESTAMPTZ NOT NULL,
    business_tags TEXT[] NOT NULL DEFAULT '{}',
    permission_tags TEXT[] NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS rag.chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES rag.documents(document_id),
    position INTEGER NOT NULL CHECK (position > 0),
    chunk_text TEXT NOT NULL,
    token_count INTEGER NOT NULL CHECK (token_count > 0)
);

CREATE TABLE IF NOT EXISTS rag.embedding_metadata (
    embedding_id TEXT PRIMARY KEY,
    chunk_id TEXT NOT NULL REFERENCES rag.chunks(chunk_id),
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    dimensions INTEGER NOT NULL CHECK (dimensions > 0)
);

CREATE TABLE IF NOT EXISTS rag.index_jobs (
    job_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed')
    ),
    error_message TEXT NULL
);

CREATE TABLE IF NOT EXISTS rag.evidence_events (
    event_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    returned_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rag_documents_published_at
    ON rag.documents(published_at DESC);

CREATE INDEX IF NOT EXISTS idx_rag_documents_business_tags
    ON rag.documents USING GIN (business_tags);

CREATE INDEX IF NOT EXISTS idx_rag_documents_permission_tags
    ON rag.documents USING GIN (permission_tags);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_document_id_position
    ON rag.chunks(document_id, position);

CREATE INDEX IF NOT EXISTS idx_rag_evidence_events_trace_id
    ON rag.evidence_events(trace_id);
""".strip()


def document_to_row(document: RagDocument) -> Mapping[str, object]:
    return {
        "document_id": document.document_id,
        "source": document.source,
        "title": document.title,
        "document_type": document.document_type,
        "published_at": document.published_at,
        "business_tags": document.business_tags,
        "permission_tags": document.permission_tags,
    }


def document_from_row(row: Mapping[str, object]) -> RagDocument:
    return RagDocument(
        document_id=_string(row, "document_id"),
        source=_string(row, "source"),
        title=_string(row, "title"),
        document_type=cast(DocumentType, _string(row, "document_type")),
        published_at=_datetime(row, "published_at"),
        business_tags=_tags(row, "business_tags"),
        permission_tags=_tags(row, "permission_tags"),
    )


def chunk_to_row(chunk: RagChunk) -> Mapping[str, object]:
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "position": chunk.position,
        "chunk_text": chunk.text,
        "token_count": chunk.token_count,
    }


def chunk_from_row(row: Mapping[str, object]) -> RagChunk:
    return RagChunk(
        chunk_id=_string(row, "chunk_id"),
        document_id=_string(row, "document_id"),
        position=_integer(row, "position"),
        text=_string(row, "chunk_text"),
        token_count=_integer(row, "token_count"),
    )


def embedding_metadata_to_row(metadata: EmbeddingMetadata) -> Mapping[str, object]:
    return {
        "embedding_id": metadata.embedding_id,
        "chunk_id": metadata.chunk_id,
        "model_name": metadata.model_name,
        "model_version": metadata.model_version,
        "dimensions": metadata.dimensions,
    }


def embedding_metadata_from_row(row: Mapping[str, object]) -> EmbeddingMetadata:
    return EmbeddingMetadata(
        embedding_id=_string(row, "embedding_id"),
        chunk_id=_string(row, "chunk_id"),
        model_name=_string(row, "model_name"),
        model_version=_string(row, "model_version"),
        dimensions=_integer(row, "dimensions"),
    )


def index_job_to_row(job: IndexJob) -> Mapping[str, object | None]:
    return {
        "job_id": job.job_id,
        "document_id": job.document_id,
        "status": job.status.value,
        "error_message": job.error_message,
    }


def index_job_from_row(row: Mapping[str, object]) -> IndexJob:
    return IndexJob(
        job_id=_string(row, "job_id"),
        document_id=_string(row, "document_id"),
        status=IndexJobStatus(_string(row, "status")),
        error_message=_optional_string(row, "error_message"),
    )


def evidence_event_to_row(event: EvidenceEvent) -> Mapping[str, object]:
    return {
        "event_id": event.event_id,
        "trace_id": event.trace_id,
        "evidence_id": event.evidence_id,
        "document_id": event.document_id,
        "chunk_id": event.chunk_id,
        "returned_at": event.returned_at,
    }


def evidence_event_from_row(row: Mapping[str, object]) -> EvidenceEvent:
    return EvidenceEvent(
        event_id=_string(row, "event_id"),
        trace_id=_string(row, "trace_id"),
        evidence_id=_string(row, "evidence_id"),
        document_id=_string(row, "document_id"),
        chunk_id=_string(row, "chunk_id"),
        returned_at=_datetime(row, "returned_at"),
    )


def _string(row: Mapping[str, object], field_name: str) -> str:
    value = row.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(row: Mapping[str, object], field_name: str) -> str | None:
    value = row.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or None")
    return value


def _integer(row: Mapping[str, object], field_name: str) -> int:
    value = row.get(field_name)
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _datetime(row: Mapping[str, object], field_name: str) -> datetime:
    value = row.get(field_name)
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime")
    return value


def _tags(row: Mapping[str, object], field_name: str) -> tuple[str, ...]:
    value = row.get(field_name)
    if value is None:
        return ()
    if isinstance(value, str):
        raise ValueError(f"{field_name} must be a sequence of strings")
    return normalize_tags(tuple(cast(tuple[str, ...], tuple(cast(Any, value)))))
