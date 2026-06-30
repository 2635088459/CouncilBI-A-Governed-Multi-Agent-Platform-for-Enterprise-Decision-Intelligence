"""Repository boundary for RAG v2 persistence.

The spec says RAG metadata should be persisted in PostgreSQL. This file defines
that persistence boundary first, then provides an in-memory implementation for
local tests and teaching.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence, cast

from chatbi.rag import (
    EmbeddingMetadata,
    EvidenceEvent,
    IndexJob,
    RagChunk,
    RagDocument,
)
from chatbi.rag_indexing import IndexArtifacts
from chatbi.rag_postgres_rows import (
    RAG_V2_TABLES_SQL,
    chunk_from_row,
    chunk_to_row,
    document_from_row,
    document_to_row,
    embedding_metadata_from_row,
    embedding_metadata_to_row,
    evidence_event_from_row,
    evidence_event_to_row,
    index_job_from_row,
    index_job_to_row,
)


class RagRepository(Protocol):
    """Storage port for indexed RAG metadata and evidence events."""

    def save_index_artifacts(self, artifacts: IndexArtifacts) -> None:
        """Persist one document, its chunks, embedding metadata, and job."""
        ...

    def save_job(self, job: IndexJob) -> None:
        """Persist the latest state of an index job."""
        ...

    def document_by_id(self, document_id: str) -> RagDocument | None:
        """Return one indexed document by id."""
        ...

    def chunk_by_id(self, chunk_id: str) -> RagChunk | None:
        """Return one indexed chunk by id."""
        ...

    def job_by_id(self, job_id: str) -> IndexJob | None:
        """Return one index job by id."""
        ...

    def list_documents(self) -> tuple[RagDocument, ...]:
        """Return all indexed document rows."""
        ...

    def list_chunks(self) -> tuple[RagChunk, ...]:
        """Return all indexed chunk rows."""
        ...

    def list_embedding_metadata(self) -> tuple[EmbeddingMetadata, ...]:
        """Return all embedding metadata rows."""
        ...

    def save_evidence_events(self, events: tuple[EvidenceEvent, ...]) -> None:
        """Persist evidence events produced by retrieval."""
        ...

    def list_evidence_events_by_trace_id(self, trace_id: str) -> tuple[EvidenceEvent, ...]:
        """Return evidence events for one request trace."""
        ...


class InMemoryRagRepository:
    """Simple repository implementation with PostgreSQL-shaped collections."""

    def __init__(self) -> None:
        self._documents_by_id: dict[str, RagDocument] = {}
        self._chunks_by_id: dict[str, RagChunk] = {}
        self._embedding_metadata_by_id: dict[str, EmbeddingMetadata] = {}
        self._jobs_by_id: dict[str, IndexJob] = {}
        self._events_by_trace_id: dict[str, tuple[EvidenceEvent, ...]] = {}

    def save_index_artifacts(self, artifacts: IndexArtifacts) -> None:
        self._documents_by_id[artifacts.document.document_id] = artifacts.document
        self._jobs_by_id[artifacts.job.job_id] = artifacts.job
        for chunk in artifacts.chunks:
            self._chunks_by_id[chunk.chunk_id] = chunk
        for metadata in artifacts.embedding_metadata:
            self._embedding_metadata_by_id[metadata.embedding_id] = metadata

    def save_job(self, job: IndexJob) -> None:
        self._jobs_by_id[job.job_id] = job

    def document_by_id(self, document_id: str) -> RagDocument | None:
        return self._documents_by_id.get(document_id)

    def chunk_by_id(self, chunk_id: str) -> RagChunk | None:
        return self._chunks_by_id.get(chunk_id)

    def job_by_id(self, job_id: str) -> IndexJob | None:
        return self._jobs_by_id.get(job_id)

    def list_documents(self) -> tuple[RagDocument, ...]:
        return tuple(
            self._documents_by_id[document_id]
            for document_id in sorted(self._documents_by_id)
        )

    def list_chunks(self) -> tuple[RagChunk, ...]:
        return tuple(
            sorted(
                self._chunks_by_id.values(),
                key=lambda chunk: (chunk.document_id, chunk.position),
            )
        )

    def list_embedding_metadata(self) -> tuple[EmbeddingMetadata, ...]:
        return tuple(
            self._embedding_metadata_by_id[embedding_id]
            for embedding_id in sorted(self._embedding_metadata_by_id)
        )

    def save_evidence_events(self, events: tuple[EvidenceEvent, ...]) -> None:
        for event in events:
            current_events = self._events_by_trace_id.get(event.trace_id, ())
            self._events_by_trace_id[event.trace_id] = current_events + (event,)

    def list_evidence_events_by_trace_id(self, trace_id: str) -> tuple[EvidenceEvent, ...]:
        return self._events_by_trace_id.get(trace_id, ())


class RagPostgresConnection(Protocol):
    """Tiny DB-API style connection shape used by PostgresRagRepository."""

    def execute(self, sql: str, params: Sequence[object] = ()) -> Any:
        ...

    def fetchone(self) -> Sequence[object] | None:
        ...

    def fetchall(self) -> Sequence[Sequence[object]]:
        ...

    def commit(self) -> None:
        ...


class PsycopgRagConnection:
    """Adapt a psycopg-style connection to the tiny repository protocol."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._latest_cursor: Any | None = None

    def execute(self, sql: str, params: Sequence[object] = ()) -> Any:
        self._latest_cursor = self._connection.execute(sql, params)
        return self._latest_cursor

    def fetchone(self) -> Sequence[object] | None:
        if self._latest_cursor is None:
            return None
        row = self._latest_cursor.fetchone()
        return cast(Sequence[object] | None, row)

    def fetchall(self) -> Sequence[Sequence[object]]:
        if self._latest_cursor is None:
            return ()
        rows = self._latest_cursor.fetchall()
        return cast(Sequence[Sequence[object]], rows)

    def commit(self) -> None:
        self._connection.commit()


class PostgresRagRepository:
    """PostgreSQL implementation of the RAG repository boundary."""

    _document_columns = (
        "document_id",
        "source",
        "title",
        "document_type",
        "published_at",
        "business_tags",
        "permission_tags",
    )
    _chunk_columns = (
        "chunk_id",
        "document_id",
        "position",
        "chunk_text",
        "token_count",
    )
    _embedding_columns = (
        "embedding_id",
        "chunk_id",
        "model_name",
        "model_version",
        "dimensions",
    )
    _job_columns = (
        "job_id",
        "document_id",
        "status",
        "error_message",
    )
    _event_columns = (
        "event_id",
        "trace_id",
        "evidence_id",
        "document_id",
        "chunk_id",
        "returned_at",
    )

    def __init__(self, connection: RagPostgresConnection) -> None:
        self._connection = connection

    def initialize_schema(self) -> None:
        self._connection.execute(RAG_V2_TABLES_SQL)
        self._connection.commit()

    def save_index_artifacts(self, artifacts: IndexArtifacts) -> None:
        self._save_document(artifacts.document)
        for chunk in artifacts.chunks:
            self._save_chunk(chunk)
        for metadata in artifacts.embedding_metadata:
            self._save_embedding_metadata(metadata)
        self.save_job(artifacts.job)
        self._connection.commit()

    def save_job(self, job: IndexJob) -> None:
        row = index_job_to_row(job)
        self._connection.execute(
            """
            INSERT INTO rag.index_jobs (
                job_id,
                document_id,
                status,
                error_message
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (job_id) DO UPDATE SET
                document_id = EXCLUDED.document_id,
                status = EXCLUDED.status,
                error_message = EXCLUDED.error_message
            """,
            (
                row["job_id"],
                row["document_id"],
                row["status"],
                row["error_message"],
            ),
        )
        self._connection.commit()

    def document_by_id(self, document_id: str) -> RagDocument | None:
        self._connection.execute(
            f"""
            SELECT {", ".join(self._document_columns)}
            FROM rag.documents
            WHERE document_id = %s
            """,
            (document_id,),
        )
        row = self._connection.fetchone()
        if row is None:
            return None
        return document_from_row(_row_mapping(self._document_columns, row))

    def chunk_by_id(self, chunk_id: str) -> RagChunk | None:
        self._connection.execute(
            f"""
            SELECT {", ".join(self._chunk_columns)}
            FROM rag.chunks
            WHERE chunk_id = %s
            """,
            (chunk_id,),
        )
        row = self._connection.fetchone()
        if row is None:
            return None
        return chunk_from_row(_row_mapping(self._chunk_columns, row))

    def job_by_id(self, job_id: str) -> IndexJob | None:
        self._connection.execute(
            f"""
            SELECT {", ".join(self._job_columns)}
            FROM rag.index_jobs
            WHERE job_id = %s
            """,
            (job_id,),
        )
        row = self._connection.fetchone()
        if row is None:
            return None
        return index_job_from_row(_row_mapping(self._job_columns, row))

    def list_documents(self) -> tuple[RagDocument, ...]:
        self._connection.execute(
            f"""
            SELECT {", ".join(self._document_columns)}
            FROM rag.documents
            ORDER BY document_id ASC
            """
        )
        return tuple(
            document_from_row(_row_mapping(self._document_columns, row))
            for row in self._connection.fetchall()
        )

    def list_chunks(self) -> tuple[RagChunk, ...]:
        self._connection.execute(
            f"""
            SELECT {", ".join(self._chunk_columns)}
            FROM rag.chunks
            ORDER BY document_id ASC, position ASC
            """
        )
        return tuple(
            chunk_from_row(_row_mapping(self._chunk_columns, row))
            for row in self._connection.fetchall()
        )

    def list_embedding_metadata(self) -> tuple[EmbeddingMetadata, ...]:
        self._connection.execute(
            f"""
            SELECT {", ".join(self._embedding_columns)}
            FROM rag.embedding_metadata
            ORDER BY embedding_id ASC
            """
        )
        return tuple(
            embedding_metadata_from_row(_row_mapping(self._embedding_columns, row))
            for row in self._connection.fetchall()
        )

    def save_evidence_events(self, events: tuple[EvidenceEvent, ...]) -> None:
        for event in events:
            row = evidence_event_to_row(event)
            self._connection.execute(
                """
                INSERT INTO rag.evidence_events (
                    event_id,
                    trace_id,
                    evidence_id,
                    document_id,
                    chunk_id,
                    returned_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO UPDATE SET
                    trace_id = EXCLUDED.trace_id,
                    evidence_id = EXCLUDED.evidence_id,
                    document_id = EXCLUDED.document_id,
                    chunk_id = EXCLUDED.chunk_id,
                    returned_at = EXCLUDED.returned_at
                """,
                (
                    row["event_id"],
                    row["trace_id"],
                    row["evidence_id"],
                    row["document_id"],
                    row["chunk_id"],
                    row["returned_at"],
                ),
            )
        self._connection.commit()

    def list_evidence_events_by_trace_id(self, trace_id: str) -> tuple[EvidenceEvent, ...]:
        self._connection.execute(
            f"""
            SELECT {", ".join(self._event_columns)}
            FROM rag.evidence_events
            WHERE trace_id = %s
            ORDER BY returned_at ASC, event_id ASC
            """,
            (trace_id,),
        )
        return tuple(
            evidence_event_from_row(_row_mapping(self._event_columns, row))
            for row in self._connection.fetchall()
        )

    def _save_document(self, document: RagDocument) -> None:
        row = document_to_row(document)
        self._connection.execute(
            """
            INSERT INTO rag.documents (
                document_id,
                source,
                title,
                document_type,
                published_at,
                business_tags,
                permission_tags
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (document_id) DO UPDATE SET
                source = EXCLUDED.source,
                title = EXCLUDED.title,
                document_type = EXCLUDED.document_type,
                published_at = EXCLUDED.published_at,
                business_tags = EXCLUDED.business_tags,
                permission_tags = EXCLUDED.permission_tags
            """,
            (
                row["document_id"],
                row["source"],
                row["title"],
                row["document_type"],
                row["published_at"],
                row["business_tags"],
                row["permission_tags"],
            ),
        )

    def _save_chunk(self, chunk: RagChunk) -> None:
        row = chunk_to_row(chunk)
        self._connection.execute(
            """
            INSERT INTO rag.chunks (
                chunk_id,
                document_id,
                position,
                chunk_text,
                token_count
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (chunk_id) DO UPDATE SET
                document_id = EXCLUDED.document_id,
                position = EXCLUDED.position,
                chunk_text = EXCLUDED.chunk_text,
                token_count = EXCLUDED.token_count
            """,
            (
                row["chunk_id"],
                row["document_id"],
                row["position"],
                row["chunk_text"],
                row["token_count"],
            ),
        )

    def _save_embedding_metadata(self, metadata: EmbeddingMetadata) -> None:
        row = embedding_metadata_to_row(metadata)
        self._connection.execute(
            """
            INSERT INTO rag.embedding_metadata (
                embedding_id,
                chunk_id,
                model_name,
                model_version,
                dimensions
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (embedding_id) DO UPDATE SET
                chunk_id = EXCLUDED.chunk_id,
                model_name = EXCLUDED.model_name,
                model_version = EXCLUDED.model_version,
                dimensions = EXCLUDED.dimensions
            """,
            (
                row["embedding_id"],
                row["chunk_id"],
                row["model_name"],
                row["model_version"],
                row["dimensions"],
            ),
        )


def postgres_rag_repository_from_psycopg(connection: Any) -> PostgresRagRepository:
    """Build a PostgreSQL RAG repository from a psycopg-style connection."""

    return PostgresRagRepository(PsycopgRagConnection(connection))


def _row_mapping(columns: tuple[str, ...], row: Sequence[object]) -> dict[str, object]:
    if len(row) != len(columns):
        raise ValueError("RAG PostgreSQL row has unexpected column count.")
    return dict(zip(columns, row, strict=True))
