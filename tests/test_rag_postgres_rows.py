from datetime import datetime, timezone

from chatbi.rag import (
    EmbeddingMetadata,
    EvidenceEvent,
    IndexJob,
    IndexJobStatus,
    RagChunk,
    RagDocument,
)
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


PUBLISHED_AT = datetime(2026, 6, 1, tzinfo=timezone.utc)
RETURNED_AT = datetime(2026, 6, 2, tzinfo=timezone.utc)


def test_rag_v2_table_sql_declares_required_tables() -> None:
    assert "CREATE TABLE IF NOT EXISTS rag.documents" in RAG_V2_TABLES_SQL
    assert "CREATE TABLE IF NOT EXISTS rag.chunks" in RAG_V2_TABLES_SQL
    assert "CREATE TABLE IF NOT EXISTS rag.embedding_metadata" in RAG_V2_TABLES_SQL
    assert "CREATE TABLE IF NOT EXISTS rag.index_jobs" in RAG_V2_TABLES_SQL
    assert "CREATE TABLE IF NOT EXISTS rag.evidence_events" in RAG_V2_TABLES_SQL
    assert "org_id TEXT NOT NULL DEFAULT 'org_legacy'" in RAG_V2_TABLES_SQL
    assert "idx_rag_documents_org_id" in RAG_V2_TABLES_SQL
    assert "idx_rag_evidence_events_org_trace_id" in RAG_V2_TABLES_SQL
    assert "idx_rag_evidence_events_trace_id" in RAG_V2_TABLES_SQL


def test_rag_document_round_trips_through_postgres_row() -> None:
    document = RagDocument(
        document_id="doc_001",
        source="release-notes",
        title="Revenue release note",
        document_type="release_note",
        published_at=PUBLISHED_AT,
        business_tags=("Campaign", "revenue"),
        permission_tags=("Sales",),
        org_id="org_001",
    )

    row = document_to_row(document)
    restored = document_from_row(row)

    assert row["document_id"] == "doc_001"
    assert row["org_id"] == "org_001"
    assert restored.document_id == document.document_id
    assert restored.org_id == "org_001"
    assert restored.document_type == document.document_type
    assert restored.business_tags == ("campaign", "revenue")
    assert restored.permission_tags == ("sales",)


def test_rag_chunk_round_trips_through_postgres_row() -> None:
    chunk = RagChunk(
        chunk_id="doc_001_chunk_1",
        document_id="doc_001",
        position=1,
        text="Revenue dropped after campaign spend paused.",
        token_count=6,
        org_id="org_001",
    )

    row = chunk_to_row(chunk)
    restored = chunk_from_row(row)

    assert row["chunk_text"] == chunk.text
    assert row["org_id"] == "org_001"
    assert restored == chunk


def test_embedding_metadata_round_trips_through_postgres_row() -> None:
    metadata = EmbeddingMetadata(
        embedding_id="doc_001_chunk_1_embedding",
        chunk_id="doc_001_chunk_1",
        model_name="mock-local-embedding",
        model_version="v1",
        dimensions=16,
        org_id="org_001",
    )

    row = embedding_metadata_to_row(metadata)
    restored = embedding_metadata_from_row(row)

    assert row["model_version"] == "v1"
    assert row["org_id"] == "org_001"
    assert restored == metadata


def test_index_job_round_trips_through_postgres_row() -> None:
    job = IndexJob(
        job_id="rag_job_doc_001",
        document_id="doc_001",
        status=IndexJobStatus.FAILED,
        error_message="bad chunk settings",
        org_id="org_001",
    )

    row = index_job_to_row(job)
    restored = index_job_from_row(row)

    assert row["status"] == "failed"
    assert row["org_id"] == "org_001"
    assert restored == job


def test_evidence_event_round_trips_through_postgres_row() -> None:
    event = EvidenceEvent(
        event_id="rag_evt_trc_001_1",
        trace_id="trc_001",
        evidence_id="ev_doc_001_chunk_1",
        document_id="doc_001",
        chunk_id="doc_001_chunk_1",
        returned_at=RETURNED_AT,
        org_id="org_001",
    )

    row = evidence_event_to_row(event)
    restored = evidence_event_from_row(row)

    assert row["trace_id"] == "trc_001"
    assert row["org_id"] == "org_001"
    assert restored == event


def test_postgres_row_mapper_rejects_invalid_required_field() -> None:
    row = {
        "document_id": "",
        "source": "release-notes",
        "title": "Revenue release note",
        "document_type": "release_note",
        "published_at": PUBLISHED_AT,
        "business_tags": ("revenue",),
        "permission_tags": ("sales",),
    }

    try:
        document_from_row(row)
    except ValueError as exc:
        assert "document_id must be a non-empty string" in str(exc)
    else:
        raise AssertionError("Expected invalid document_id to raise ValueError")
