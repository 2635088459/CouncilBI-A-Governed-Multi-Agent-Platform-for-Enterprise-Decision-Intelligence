import json
from datetime import datetime, timezone
from pathlib import Path

from chatbi.golden_dataset_mining import (
    export_labeling_candidates,
    mine_retrieval_labeling_candidates,
)
from chatbi.knowledge import DocumentChunk, InMemoryKnowledgeStore, KnowledgeDocument
from chatbi.observability import InMemoryObservabilityStore, ObservabilitySpan, TraceSpanName, TraceSpanStatus
from chatbi.observability_logs import InMemoryObservabilityLogStore, LogLevel, ObservabilityLogRecord


def _seeded_store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    store.save_document(
        KnowledgeDocument(
            source_id="doc_refund_policy_2026",
            title="Refund policy",
            doc_type="policy",
            publish_time=datetime(2026, 4, 10, tzinfo=timezone.utc),
        )
    )
    store.save_chunk(
        DocumentChunk(
            chunk_id="doc_refund_policy_2026_chunk_1",
            source_id="doc_refund_policy_2026",
            chunk_index=1,
            chunk_text="Refunds are issued when an order is cancelled within 30 days.",
        )
    )
    return store


def _question_log(trace_id: str, question: str) -> ObservabilityLogRecord:
    return ObservabilityLogRecord(
        trace_id=trace_id,
        level=LogLevel.INFO,
        message=f"Received chat query: {question}",
        endpoint="/api/v1/chat/query",
        user_id="u_001",
        attributes={"question": question},
    )


def _rag_retrieved_span(trace_id: str, evidence_count: int) -> ObservabilitySpan:
    return ObservabilitySpan(
        trace_id=trace_id,
        span_name=TraceSpanName.RAG_RETRIEVED,
        status=TraceSpanStatus.SUCCEEDED,
        attributes={"evidence_count": evidence_count, "evidence_uncertainty": False},
    )


def test_mine_retrieval_labeling_candidates_only_includes_questions_with_rag_evidence() -> None:
    log_store = InMemoryObservabilityLogStore()
    log_store.add(_question_log("trc_with_evidence", "Why were refunds issued this month?"))
    log_store.add(_question_log("trc_no_evidence", "Show monthly revenue."))

    trace_store = InMemoryObservabilityStore()
    trace_store.add_span(_rag_retrieved_span("trc_with_evidence", evidence_count=1))
    # trc_no_evidence never gets a RAG_RETRIEVED span at all (pure SQL path).

    candidates = mine_retrieval_labeling_candidates(log_store, trace_store, _seeded_store())

    assert [candidate.question for candidate in candidates] == ["Why were refunds issued this month?"]


def test_mine_retrieval_labeling_candidates_excludes_zero_evidence_count_spans() -> None:
    log_store = InMemoryObservabilityLogStore()
    log_store.add(_question_log("trc_zero_evidence", "Why did nothing come back?"))

    trace_store = InMemoryObservabilityStore()
    trace_store.add_span(_rag_retrieved_span("trc_zero_evidence", evidence_count=0))

    candidates = mine_retrieval_labeling_candidates(log_store, trace_store, _seeded_store())

    assert candidates == ()


def test_mine_retrieval_labeling_candidates_deduplicates_repeated_questions() -> None:
    log_store = InMemoryObservabilityLogStore()
    log_store.add(_question_log("trc_1", "Why were refunds issued this month?"))
    log_store.add(_question_log("trc_2", "Why were refunds issued this month?"))

    trace_store = InMemoryObservabilityStore()
    trace_store.add_span(_rag_retrieved_span("trc_1", evidence_count=1))
    trace_store.add_span(_rag_retrieved_span("trc_2", evidence_count=1))

    candidates = mine_retrieval_labeling_candidates(log_store, trace_store, _seeded_store())

    assert len(candidates) == 1


def test_mine_retrieval_labeling_candidates_attaches_a_retrieve_shortlist() -> None:
    log_store = InMemoryObservabilityLogStore()
    log_store.add(_question_log("trc_1", "Why were refunds issued this month?"))

    trace_store = InMemoryObservabilityStore()
    trace_store.add_span(_rag_retrieved_span("trc_1", evidence_count=1))

    candidates = mine_retrieval_labeling_candidates(log_store, trace_store, _seeded_store(), top_k=3)

    assert len(candidates) == 1
    assert candidates[0].trace_id == "trc_1"
    assert len(candidates[0].candidate_chunks) == 1
    assert candidates[0].candidate_chunks[0].chunk_id == "doc_refund_policy_2026_chunk_1"
    assert candidates[0].candidate_chunks[0].snippet.startswith("Refunds are issued")


def test_export_labeling_candidates_writes_a_reviewable_json_worksheet(tmp_path: Path) -> None:
    log_store = InMemoryObservabilityLogStore()
    log_store.add(_question_log("trc_1", "Why were refunds issued this month?"))
    trace_store = InMemoryObservabilityStore()
    trace_store.add_span(_rag_retrieved_span("trc_1", evidence_count=1))
    candidates = mine_retrieval_labeling_candidates(log_store, trace_store, _seeded_store())
    output_path = tmp_path / "candidates.json"

    export_labeling_candidates(candidates, output_path)

    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(written) == 1
    assert written[0]["question"] == "Why were refunds issued this month?"
    assert written[0]["candidate_chunks"][0]["chunk_id"] == "doc_refund_policy_2026_chunk_1"
    # A reviewer fills this in by hand — mining never pre-labels a candidate.
    assert written[0]["reviewer_expected_chunk_ids"] == []
