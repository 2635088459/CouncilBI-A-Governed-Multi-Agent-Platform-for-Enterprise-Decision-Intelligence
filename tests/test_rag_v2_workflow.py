from datetime import datetime, timezone

from chatbi.rag import (
    EvidenceSearchRequest,
    IndexDocumentRequest,
    IndexJobStatus,
    RagWarningCode,
)
from chatbi.rag_answering import RagAnsweringService
from chatbi.rag_indexing import ChunkSettings, build_index_artifacts, chunk_document_text
from chatbi.rag_service import InMemoryRagService


PUBLISHED_AT = datetime(2026, 6, 1, tzinfo=timezone.utc)


def make_index_request(
    document_id: str = "doc_release_001",
    text: str = "Revenue dropped after campaign spend paused.",
    permission_tags: tuple[str, ...] = ("sales",),
    business_tags: tuple[str, ...] = ("revenue", "campaign"),
) -> IndexDocumentRequest:
    return IndexDocumentRequest(
        document_id=document_id,
        source="release-notes",
        title="Revenue release note",
        document_type="release_note",
        published_at=PUBLISHED_AT,
        business_tags=business_tags,
        permission_tags=permission_tags,
        text=text,
    )


def test_rag_v2_index_artifacts_create_document_chunks_and_embedding_metadata() -> None:
    artifacts = build_index_artifacts(
        make_index_request(text="alpha beta gamma delta epsilon"),
        chunk_settings=ChunkSettings(token_limit=3, overlap=1),
    )

    assert artifacts.document.document_id == "doc_release_001"
    assert artifacts.job.status is IndexJobStatus.SUCCEEDED
    assert tuple(chunk.text for chunk in artifacts.chunks) == (
        "alpha beta gamma",
        "gamma delta epsilon",
    )
    assert tuple(chunk.token_count for chunk in artifacts.chunks) == (3, 3)
    assert len(artifacts.embedding_metadata) == 2
    assert artifacts.embedding_metadata[0].model_name == "mock-local-embedding"


def test_rag_v2_chunking_is_deterministic_for_same_text_and_settings() -> None:
    settings = ChunkSettings(token_limit=4, overlap=2)
    text = "alpha beta gamma delta epsilon zeta eta theta"

    first_chunks = chunk_document_text("doc_001", text, settings)
    second_chunks = chunk_document_text("doc_001", text, settings)

    assert first_chunks == second_chunks


def test_rag_v2_retrieval_filters_out_disallowed_permission_tags() -> None:
    service = InMemoryRagService()
    service.index_document(
        make_index_request(
            document_id="doc_public",
            text="Revenue dropped after campaign spend paused.",
            permission_tags=("sales",),
        )
    )
    service.index_document(
        make_index_request(
            document_id="doc_restricted",
            text="Revenue dropped because of a confidential acquisition plan.",
            permission_tags=("executive",),
        )
    )

    result = service.search_evidence(
        EvidenceSearchRequest(
            trace_id="trc_permission",
            query_text="Why did revenue drop?",
            time_window=None,
            business_tags=("revenue",),
            permission_tags=("sales",),
            limit=10,
        )
    )

    assert tuple(evidence.document_id for evidence in result.evidence_list) == ("doc_public",)


def test_rag_v2_empty_recall_returns_no_evidence_warning() -> None:
    service = InMemoryRagService()
    service.index_document(make_index_request())

    result = service.search_evidence(
        EvidenceSearchRequest(
            trace_id="trc_no_evidence",
            query_text="customer churn forecast",
            time_window=None,
            business_tags=("support",),
            permission_tags=("sales",),
            limit=5,
        )
    )

    assert result.evidence_list == ()
    assert result.warnings == (RagWarningCode.NO_EVIDENCE,)
    assert service.evidence_events_by_trace_id("trc_no_evidence") == ()


def test_rag_v2_answer_cites_returned_evidence_and_records_trace_events() -> None:
    service = InMemoryRagService()
    service.index_document(make_index_request())
    answering_service = RagAnsweringService(service)

    answer = answering_service.answer(
        EvidenceSearchRequest(
            trace_id="trc_answer",
            query_text="Why did revenue drop?",
            time_window=None,
            business_tags=("revenue",),
            permission_tags=("sales",),
            limit=5,
        )
    )

    assert answer.has_evidence is True
    assert len(answer.explanation.claims) == 1
    evidence_id = answer.search_result.evidence_list[0].evidence_id
    assert answer.explanation.claims[0].evidence_ids == (evidence_id,)
    assert f"[{evidence_id}]" in answer.explanation.answer_text
    assert tuple(event.evidence_id for event in answer.evidence_events) == (evidence_id,)


def test_rag_v2_long_document_is_queued_then_worker_succeeds() -> None:
    service = InMemoryRagService()
    request = make_index_request(text="x" * 50_001)

    queued_job = service.index_document(request)
    assert queued_job.status is IndexJobStatus.QUEUED
    assert service.state().indexed_chunk_count == 0

    succeeded_job = service.run_index_job(
        queued_job.job_id,
        chunk_settings=ChunkSettings(token_limit=1000, overlap=0),
    )

    assert succeeded_job.status is IndexJobStatus.SUCCEEDED
    assert service.state().indexed_chunk_count == 1


def test_rag_v2_rejects_invalid_search_limit() -> None:
    try:
        EvidenceSearchRequest(
            trace_id="trc_bad_limit",
            query_text="Why did revenue drop?",
            time_window=None,
            business_tags=(),
            permission_tags=("sales",),
            limit=0,
        )
    except ValueError as exc:
        assert "limit must be between 1 and 10" in str(exc)
    else:
        raise AssertionError("Expected invalid search limit to raise ValueError")
