from datetime import datetime, timezone
from typing import Any, Sequence

from chatbi.rag import (
    EmbeddingMetadata,
    EvidenceEvent,
    IndexJob,
    IndexJobStatus,
    RagChunk,
    RagDocument,
)
from chatbi.rag_indexing import IndexArtifacts
from chatbi.rag_postgres_rows import RAG_V2_TABLES_SQL
from chatbi.rag_repository import PostgresRagRepository, RagPostgresConnection


PUBLISHED_AT = datetime(2026, 6, 1, tzinfo=timezone.utc)
RETURNED_AT = datetime(2026, 6, 2, tzinfo=timezone.utc)


class FakeRagPostgresConnection:
    def __init__(
        self,
        fetchone_rows: tuple[Sequence[object] | None, ...] = (),
        fetchall_rows: tuple[Sequence[Sequence[object]], ...] = (),
    ) -> None:
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.commit_count = 0
        self._fetchone_rows = list(fetchone_rows)
        self._fetchall_rows = list(fetchall_rows)

    def execute(self, sql: str, params: Sequence[object] = ()) -> Any:
        self.executed.append((sql, tuple(params)))
        return None

    def fetchone(self) -> Sequence[object] | None:
        if not self._fetchone_rows:
            return None
        return self._fetchone_rows.pop(0)

    def fetchall(self) -> Sequence[Sequence[object]]:
        if not self._fetchall_rows:
            return ()
        return self._fetchall_rows.pop(0)

    def commit(self) -> None:
        self.commit_count += 1


def make_artifacts() -> IndexArtifacts:
    document = RagDocument(
        document_id="doc_001",
        source="release-notes",
        title="Revenue release note",
        document_type="release_note",
        published_at=PUBLISHED_AT,
        business_tags=("revenue", "campaign"),
        permission_tags=("sales",),
        org_id="org_001",
    )
    chunk = RagChunk(
        chunk_id="doc_001_chunk_1",
        document_id="doc_001",
        position=1,
        text="Revenue dropped after campaign spend paused.",
        token_count=6,
        org_id="org_001",
    )
    metadata = EmbeddingMetadata(
        embedding_id="doc_001_chunk_1_embedding",
        chunk_id="doc_001_chunk_1",
        model_name="mock-local-embedding",
        model_version="v1",
        dimensions=16,
        org_id="org_001",
    )
    job = IndexJob(
        job_id="rag_job_doc_001",
        document_id="doc_001",
        status=IndexJobStatus.SUCCEEDED,
        org_id="org_001",
    )
    return IndexArtifacts(
        document=document,
        chunks=(chunk,),
        embedding_metadata=(metadata,),
        job=job,
    )


def test_postgres_rag_repository_initializes_schema() -> None:
    connection: RagPostgresConnection = FakeRagPostgresConnection()
    repository = PostgresRagRepository(connection)

    repository.initialize_schema()

    fake_connection = _fake(connection)
    assert fake_connection.executed == [(RAG_V2_TABLES_SQL, ())]
    assert fake_connection.commit_count == 1


def test_postgres_rag_repository_saves_index_artifacts() -> None:
    connection: RagPostgresConnection = FakeRagPostgresConnection()
    repository = PostgresRagRepository(connection)

    repository.save_index_artifacts(make_artifacts())

    fake_connection = _fake(connection)
    executed_sql = "\n".join(sql for sql, _params in fake_connection.executed)
    assert "INSERT INTO rag.documents" in executed_sql
    assert "INSERT INTO rag.chunks" in executed_sql
    assert "INSERT INTO rag.embedding_metadata" in executed_sql
    assert "INSERT INTO rag.index_jobs" in executed_sql
    assert fake_connection.executed[0][1][0] == "doc_001"
    assert fake_connection.executed[0][1][-1] == "org_001"
    assert fake_connection.executed[1][1][0] == "doc_001_chunk_1"
    assert fake_connection.executed[1][1][-1] == "org_001"
    assert fake_connection.executed[2][1][0] == "doc_001_chunk_1_embedding"
    assert fake_connection.executed[2][1][-1] == "org_001"
    assert fake_connection.executed[3][1][0] == "rag_job_doc_001"
    assert fake_connection.executed[3][1][-1] == "org_001"
    assert fake_connection.commit_count >= 1


def test_postgres_rag_repository_loads_document_chunk_and_job_by_id() -> None:
    connection: RagPostgresConnection = FakeRagPostgresConnection(
        fetchone_rows=(
            (
                "doc_001",
                "release-notes",
                "Revenue release note",
                "release_note",
                PUBLISHED_AT,
                ("revenue", "campaign"),
                ("sales",),
                "org_001",
            ),
            (
                "doc_001_chunk_1",
                "doc_001",
                1,
                "Revenue dropped after campaign spend paused.",
                6,
                "org_001",
            ),
            (
                "rag_job_doc_001",
                "doc_001",
                "succeeded",
                None,
                "org_001",
            ),
        )
    )
    repository = PostgresRagRepository(connection)

    document = repository.document_by_id("doc_001", org_id="org_001")
    chunk = repository.chunk_by_id("doc_001_chunk_1", org_id="org_001")
    job = repository.job_by_id("rag_job_doc_001", org_id="org_001")

    assert document is not None
    assert document.document_id == "doc_001"
    assert chunk is not None
    assert chunk.chunk_id == "doc_001_chunk_1"
    assert job is not None
    assert job.status is IndexJobStatus.SUCCEEDED
    assert connection.executed[0][1] == ("doc_001", "org_001")
    assert connection.executed[1][1] == ("doc_001_chunk_1", "org_001")
    assert connection.executed[2][1] == ("rag_job_doc_001", "org_001")


def test_postgres_rag_repository_lists_embedding_metadata_and_events() -> None:
    event = EvidenceEvent(
        event_id="rag_evt_trc_001_1",
        trace_id="trc_001",
        evidence_id="ev_doc_001_chunk_1",
        document_id="doc_001",
        chunk_id="doc_001_chunk_1",
        returned_at=RETURNED_AT,
    )
    connection: RagPostgresConnection = FakeRagPostgresConnection(
        fetchall_rows=(
            (
                (
                    "doc_001_chunk_1_embedding",
                    "doc_001_chunk_1",
                    "mock-local-embedding",
                    "v1",
                    16,
                    "org_001",
                ),
            ),
            (
                (
                    event.event_id,
                    event.trace_id,
                    event.evidence_id,
                    event.document_id,
                    event.chunk_id,
                    event.returned_at,
                    "org_001",
                ),
            ),
        )
    )
    repository = PostgresRagRepository(connection)

    metadata = repository.list_embedding_metadata(org_id="org_001")
    events = repository.list_evidence_events_by_trace_id("trc_001", org_id="org_001")

    assert metadata[0].embedding_id == "doc_001_chunk_1_embedding"
    assert events == (
        EvidenceEvent(
            event_id=event.event_id,
            trace_id=event.trace_id,
            evidence_id=event.evidence_id,
            document_id=event.document_id,
            chunk_id=event.chunk_id,
            returned_at=event.returned_at,
            org_id="org_001",
        ),
    )
    assert connection.executed[0][1] == ("org_001",)
    assert connection.executed[1][1] == ("trc_001", "org_001")


def test_postgres_rag_repository_saves_evidence_events() -> None:
    event = EvidenceEvent(
        event_id="rag_evt_trc_001_1",
        trace_id="trc_001",
        evidence_id="ev_doc_001_chunk_1",
        document_id="doc_001",
        chunk_id="doc_001_chunk_1",
        returned_at=RETURNED_AT,
        org_id="org_001",
    )
    connection: RagPostgresConnection = FakeRagPostgresConnection()
    repository = PostgresRagRepository(connection)

    repository.save_evidence_events((event,))

    fake_connection = _fake(connection)
    assert "INSERT INTO rag.evidence_events" in fake_connection.executed[0][0]
    assert fake_connection.executed[0][1] == (
        event.event_id,
        event.trace_id,
        event.evidence_id,
        event.document_id,
        event.chunk_id,
        event.returned_at,
        event.org_id,
    )
    assert fake_connection.commit_count == 1


def test_postgres_rag_repository_filters_documents_and_chunks_by_tenant() -> None:
    connection: RagPostgresConnection = FakeRagPostgresConnection(fetchall_rows=((), ()))
    repository = PostgresRagRepository(connection)

    repository.list_documents(org_id="org_001")
    repository.list_chunks(org_id="org_001")

    assert "WHERE org_id = %s" in connection.executed[0][0]
    assert connection.executed[0][1] == ("org_001",)
    assert "WHERE org_id = %s" in connection.executed[1][0]
    assert connection.executed[1][1] == ("org_001",)


def _fake(connection: RagPostgresConnection) -> FakeRagPostgresConnection:
    assert isinstance(connection, FakeRagPostgresConnection)
    return connection
