from datetime import datetime, timezone

from chatbi.api.models import ApiErrorCode, ChatQueryRequestPayload, EvalRunRequestPayload
from chatbi.application.app import ChatBIApplication
from chatbi.core.contracts import ErrorCode, Locale, UserRole
from chatbi.knowledge import DocumentChunk, InMemoryKnowledgeStore, KnowledgeDocument
from chatbi.observability import TraceSpanName, TraceSpanStatus
from chatbi.orchestration.simple_orchestrator import SimpleOrchestrator
from chatbi.rate_limit import InMemorySlidingWindowRateLimitStore
from chatbi.trace_events import TraceEventStatus


def make_payload(question: str = "Show revenue trend.") -> ChatQueryRequestPayload:
    return ChatQueryRequestPayload(
        user_id="u_001",
        session_id="s_001",
        question=question,
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
    )


def make_payload_for_user(
    user_id: str,
    question: str = "Show revenue trend.",
) -> ChatQueryRequestPayload:
    return ChatQueryRequestPayload(
        user_id=user_id,
        session_id=f"s_{user_id}",
        question=question,
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
    )


def test_close_is_a_no_op_when_no_closeable_resources_are_registered() -> None:
    # The common case every other test in this file exercises — nothing
    # should raise, and there is nothing to actually close.
    app = ChatBIApplication()

    app.close()


def test_close_calls_every_registered_closeable_resource() -> None:
    # Code-review follow-up (Spec 4.7): create_app()'s shutdown lifespan
    # (api/http.py) calls this to release resources _build_default_
    # chatbi_application() constructed but this application does not
    # otherwise own the lifecycle of (e.g. the observability ConnectionPool).
    calls: list[str] = []
    app = ChatBIApplication(
        closeable_resources=(
            lambda: calls.append("first"),
            lambda: calls.append("second"),
        )
    )

    app.close()

    assert calls == ["first", "second"]


def test_handle_chat_query_returns_success_envelope() -> None:
    app = ChatBIApplication()

    envelope = app.handle_chat_query(make_payload())

    assert envelope.code == 0
    assert envelope.message == "ok"
    assert envelope.trace_id.startswith("trc_")
    assert envelope.data is not None
    assert envelope.data["answer_text"] == "Revenue trend is ready."
    assert envelope.data["sql_text"].startswith("SELECT ")
    assert envelope.data["table_result"].columns == ("month", "revenue")
    agent_timeline = envelope.data["agent_timeline"]
    assert [step["agent_name"] for step in agent_timeline] == [
        "orchestrator",
        "sql_agent",
        "rag_agent",
        "analytics_agent",
        "visualization_agent",
        "verifier_agent",
        "answer_synthesis",
    ]
    assert agent_timeline[1]["status"] == "succeeded"
    assert agent_timeline[2]["status"] == "not_planned"
    assert agent_timeline[-1]["summary"] == (
        "Final answer synthesized through the configured LLM gateway from safe SQL rows and evidence context."
    )


def test_handle_chat_query_rejects_unsupported_questions_without_sql_or_llm() -> None:
    app = ChatBIApplication()

    envelope = app.handle_chat_query(make_payload("hello"), trace_id="trc_app_unsupported")

    assert envelope.code is ApiErrorCode.REQ_INVALID_ARGUMENT
    assert envelope.data is not None
    assert envelope.data["sql_text"] == ""
    assert envelope.data["table_result"].rows[0]["status"] == "blocked"
    timeline = envelope.data["agent_timeline"]
    assert timeline[1]["agent_name"] == "sql_agent"
    assert timeline[1]["status"] == "not_planned"
    assert timeline[-1]["agent_name"] == "answer_synthesis"
    assert timeline[-1]["status"] == "not_planned"


def test_handle_chat_query_2012_revenue_uses_filtered_rows_and_provenance() -> None:
    app = ChatBIApplication()

    envelope = app.handle_chat_query(
        make_payload("Which month had the highest revenue in 2012?"),
        trace_id="trc_app_2012_highest",
    )

    assert envelope.code == 0
    assert envelope.data is not None
    rows = envelope.data["table_result"].rows
    assert len(rows) == 12
    assert {row["month"][:4] for row in rows} == {"2012"}
    assert envelope.data["evidence_list"][0].source_id == "dataset_revenue_monthly_2012"


def test_handle_chat_query_persists_request_for_replay() -> None:
    app = ChatBIApplication()
    payload = make_payload("Show monthly revenue.")

    envelope = app.handle_chat_query(payload)
    replayed = app.orchestrator.replay(envelope.trace_id)

    assert replayed is not None
    assert replayed.request.question == "Show monthly revenue."
    assert replayed.answer is not None
    assert replayed.answer.trace_id == envelope.trace_id


def test_handle_chat_query_returns_warning_for_blocked_sql() -> None:
    app = ChatBIApplication()

    envelope = app.handle_chat_query(make_payload("DROP TABLE orders"))

    assert envelope.code is ApiErrorCode.SQL_GUARDRAIL_BLOCKED
    assert envelope.warnings
    assert envelope.warnings[0].code is ErrorCode.SQL_DENY_STATEMENT
    assert envelope.data is not None
    assert envelope.data["answer_text"].startswith("Request was blocked")


def test_handle_chat_query_reuses_idempotency_result_within_window() -> None:
    app = ChatBIApplication()

    first = app.handle_chat_query(
        make_payload("Show revenue trend."),
        trace_id="trc_first",
        idempotency_key="idem_001",
    )
    second = app.handle_chat_query(
        make_payload("Show revenue trend."),
        trace_id="trc_second",
        idempotency_key="idem_001",
    )

    assert second == first
    assert second.trace_id == "trc_first"


def test_handle_chat_history_returns_cursor_page() -> None:
    app = ChatBIApplication()
    app.handle_chat_query(make_payload("Show revenue trend."), trace_id="trc_one")
    app.handle_chat_query(make_payload("Show monthly revenue."), trace_id="trc_two")

    envelope = app.handle_chat_history(
        user_id="u_001",
        trace_id="trc_history",
        page_size=1,
    )

    assert envelope.code == 0
    assert envelope.data is not None
    assert len(envelope.data["items"]) == 1
    assert envelope.data["next_cursor"] == "1"


def test_handle_chat_history_filters_records_by_user_id() -> None:
    app = ChatBIApplication()
    app.handle_chat_query(
        make_payload_for_user("u_001", "Show revenue trend."),
        trace_id="trc_user_one",
    )
    app.handle_chat_query(
        make_payload_for_user("u_002", "Show order count."),
        trace_id="trc_user_two",
    )

    envelope = app.handle_chat_history(
        user_id="u_001",
        trace_id="trc_history_user_one",
        page_size=20,
    )

    assert envelope.code == 0
    assert envelope.data is not None
    assert len(envelope.data["items"]) == 1
    assert envelope.data["items"][0]["question"] == "Show revenue trend."


def test_handle_query_detail_hides_other_users_trace() -> None:
    app = ChatBIApplication()
    app.handle_chat_query(
        make_payload_for_user("u_002", "Show order count."),
        trace_id="trc_user_two_detail",
    )

    envelope = app.handle_query_detail(
        trace_id="trc_user_two_detail",
        user_id="u_001",
    )

    assert envelope.code is ApiErrorCode.REQ_INVALID_ARGUMENT
    assert envelope.message == "Trace id was not found."


def test_handle_chat_query_enforces_user_rate_limit() -> None:
    app = ChatBIApplication(rate_limit_per_minute=1)

    first = app.handle_chat_query(make_payload("Show revenue trend."), trace_id="trc_rate_one")
    second = app.handle_chat_query(make_payload("Show revenue trend."), trace_id="trc_rate_two")

    assert first.code == 0
    assert second.code is ApiErrorCode.RATE_LIMITED
    assert second.data is not None
    assert second.data["retry_after_seconds"] == 60
    assert second.data["scope"] == "user"


def test_handle_chat_query_enforces_org_rate_limit_across_users() -> None:
    app = ChatBIApplication(rate_limit_per_minute=10, org_rate_limit_per_minute=1)

    first = app.handle_chat_query(
        make_payload_for_user("u_001", "Show revenue trend."),
        trace_id="trc_org_rate_one",
        org_id="org_shared",
    )
    second = app.handle_chat_query(
        make_payload_for_user("u_002", "Show order count."),
        trace_id="trc_org_rate_two",
        org_id="org_shared",
    )

    assert first.code == 0
    assert second.code is ApiErrorCode.RATE_LIMITED
    assert second.data is not None
    assert second.data["scope"] == "organization"
    assert second.data["limit_per_minute"] == 1


def test_handle_chat_query_supports_shared_rate_limit_store_across_replicas() -> None:
    shared_user_store = InMemorySlidingWindowRateLimitStore()
    first_replica = ChatBIApplication(
        rate_limit_per_minute=1,
        user_rate_limit_store=shared_user_store,
    )
    second_replica = ChatBIApplication(
        rate_limit_per_minute=1,
        user_rate_limit_store=shared_user_store,
    )

    first = first_replica.handle_chat_query(
        make_payload("Show revenue trend."),
        trace_id="trc_shared_rate_one",
    )
    second = second_replica.handle_chat_query(
        make_payload("Show order count."),
        trace_id="trc_shared_rate_two",
    )

    assert first.code == 0
    assert second.code is ApiErrorCode.RATE_LIMITED
    assert second.data is not None
    assert second.data["scope"] == "user"


def test_blocked_sql_is_persisted_for_replay() -> None:
    app = ChatBIApplication()

    envelope = app.handle_chat_query(make_payload("DROP TABLE orders"))
    replayed = app.orchestrator.replay(envelope.trace_id)

    assert replayed is not None
    assert replayed.request.question == "DROP TABLE orders"
    assert replayed.failed_error_code is ErrorCode.SQL_DENY_STATEMENT


def test_handle_chat_query_writes_standard_observability_trace() -> None:
    app = ChatBIApplication()

    envelope = app.handle_chat_query(
        make_payload("Show revenue trend."),
        trace_id="trc_observable_success",
    )
    replay = app.observability_store.replay(envelope.trace_id)

    assert replay is not None
    assert replay.completed is True
    assert tuple(span.span_name for span in replay.spans) == (
        TraceSpanName.REQUEST_RECEIVED,
        TraceSpanName.ORCHESTRATION_PLANNED,
        TraceSpanName.SQL_GENERATED,
        TraceSpanName.SQL_GUARDRAIL_CHECKED,
        TraceSpanName.RESPONSE_SENT,
    )
    assert replay.spans[2].attributes["sql_text"].startswith("SELECT ")
    assert replay.spans[3].attributes["decision"] == "allow"
    assert replay.spans[-1].attributes["status_code"] == 200


def test_handle_chat_query_writes_spec_trace_events() -> None:
    app = ChatBIApplication()

    envelope = app.handle_chat_query(
        make_payload("Show revenue trend."),
        trace_id="trc_spec_trace_success",
    )
    events = app.trace_event_store.list_by_trace_id(envelope.trace_id)

    assert tuple(event.status for event in events) == (
        TraceEventStatus.STARTED,
        TraceEventStatus.SUCCEEDED,
    )
    assert events[0].service == "backend-api"
    assert events[0].span_name == "request_received"
    assert events[1].latency_ms is not None
    assert events[1].latency_ms >= 0


def test_blocked_sql_writes_failed_guardrail_trace_span() -> None:
    app = ChatBIApplication()

    envelope = app.handle_chat_query(
        make_payload("DROP TABLE orders"),
        trace_id="trc_observable_blocked",
    )
    replay = app.observability_store.replay(envelope.trace_id)

    assert replay is not None
    guardrail_span = next(
        span
        for span in replay.spans
        if span.span_name is TraceSpanName.SQL_GUARDRAIL_CHECKED
    )
    assert guardrail_span.status is TraceSpanStatus.FAILED
    assert guardrail_span.attributes["decision"] == "deny"


def test_blocked_sql_writes_degraded_spec_trace_event() -> None:
    app = ChatBIApplication()

    envelope = app.handle_chat_query(
        make_payload("DROP TABLE orders"),
        trace_id="trc_spec_trace_blocked",
    )
    events = app.trace_event_store.list_by_trace_id(envelope.trace_id)

    assert events[-1].status is TraceEventStatus.DEGRADED
    assert events[-1].ended_at is not None
    assert events[-1].latency_ms is not None


def test_observability_trace_detail_includes_denied_guardrail_audit() -> None:
    app = ChatBIApplication()

    app.handle_chat_query(
        make_payload("DROP TABLE orders"),
        trace_id="trc_guardrail_trace_detail_deny",
    )
    envelope = app.handle_observability_trace_detail(
        trace_id="trc_guardrail_trace_detail_deny",
        user_id="u_001",
    )

    assert envelope.data is not None
    guardrail_audit = envelope.data["guardrail_audit"]
    assert guardrail_audit["decision"] == "deny"
    assert guardrail_audit["original_sql"] == "DROP TABLE orders"
    assert guardrail_audit["error_code"] == "SQL_DENY_STATEMENT"
    assert guardrail_audit["message"] == "Only SELECT statements are allowed."


def test_handle_chat_query_writes_sanitized_observability_logs() -> None:
    app = ChatBIApplication()

    envelope = app.handle_chat_query(
        make_payload("Show revenue for alice@example.com and 408-555-1234."),
        trace_id="trc_log_masking",
    )
    records = app.observability_log_store.list_by_trace_id(envelope.trace_id)

    assert len(records) == 2
    serialized_logs = " ".join(
        f"{record.message} {record.user_id} {record.attributes}"
        for record in records
    )
    assert "alice@example.com" not in serialized_logs
    assert "408-555-1234" not in serialized_logs
    assert "[masked-email]" in serialized_logs
    assert "[masked-phone]" in serialized_logs


def test_handle_eval_run_persists_run_and_scores_by_eval_run_id() -> None:
    app = ChatBIApplication()

    envelope = app.handle_eval_run(
        user_id="u_001",
        trace_id="trc_eval_app",
        payload=EvalRunRequestPayload(
            eval_suite_id="backend_api_smoke",
            questions=("Show revenue trend.", "DROP TABLE orders"),
            locale=Locale.EN,
            role=UserRole.ANALYST,
        ),
    )

    assert envelope.data is not None
    eval_run_id = envelope.data["eval_run_id"]
    assert isinstance(eval_run_id, str)

    saved_run = app.evaluation_repository.run_by_id(eval_run_id)
    saved_scores = app.evaluation_repository.scores_by_run_id(eval_run_id)

    assert saved_run is not None
    assert saved_run.eval_suite_id == "backend_api_smoke"
    assert saved_run.total_cases == 2
    assert saved_run.sql_safety_score == 1.0
    assert saved_run.release_gate_passed is True
    assert tuple(score.case_id for score in saved_scores) == ("case_001", "case_002")


def test_handle_eval_run_computes_retrieval_metrics_against_the_live_knowledge_store() -> None:
    # Code-review fix (Spec FV03.4 gap): score_suite() supported
    # retrieval_metrics from the day it was written, but handle_eval_run()
    # never computed or passed them — this is Golden-Dataset-style
    # retrieval scoring against the real, seeded production chunk id
    # (migrations.py's KNOWLEDGE_RAG_SEED_SQL), not a mock. The question
    # below is one of golden_dataset/cases.json's own canonical questions
    # (golden_revenue_calculation) — _expected_chunk_ids_for_question()
    # looks up an exact match there, not a keyword heuristic.
    knowledge_store = InMemoryKnowledgeStore()
    knowledge_store.save_document(
        KnowledgeDocument(
            source_id="rag_revenue_policy_2026",
            title="Revenue metric policy and anomaly explanation",
            doc_type="policy",
            publish_time=datetime(2026, 6, 25, tzinfo=timezone.utc),
        )
    )
    knowledge_store.save_chunk(
        DocumentChunk(
            chunk_id="rag_revenue_policy_2026_chunk_1",
            source_id="rag_revenue_policy_2026",
            chunk_index=1,
            chunk_text=(
                "Revenue is calculated from paid orders only. A month-over-month "
                "spike should be explained with campaign, refund, and region context."
            ),
        )
    )
    app = ChatBIApplication(orchestrator=SimpleOrchestrator(knowledge_store=knowledge_store))

    envelope = app.handle_eval_run(
        user_id="u_001",
        trace_id="trc_eval_retrieval",
        payload=EvalRunRequestPayload(
            eval_suite_id="retrieval_smoke",
            questions=("How is revenue calculated for the platform?",),
            locale=Locale.EN,
            role=UserRole.ANALYST,
        ),
    )

    assert envelope.data is not None
    metric_breakdown = envelope.data["metric_breakdown"]
    assert metric_breakdown["retrieval_hit_rate"] == 1.0
    assert metric_breakdown["retrieval_mrr"] == 1.0

    eval_run_id = envelope.data["eval_run_id"]
    saved_scores = app.evaluation_repository.scores_by_run_id(eval_run_id)
    assert saved_scores[0].retrieval_hit_at_3 is True
    assert saved_scores[0].retrieval_reciprocal_rank == 1.0


def test_mine_golden_dataset_candidates_surfaces_a_real_answered_question() -> None:
    # Spec 4.6 §3.4 follow-up: a question this process actually answered
    # with real RAG evidence must show up as a labeling candidate, with
    # retrieve()'s own top-K shortlist attached, ready for a human reviewer
    # to confirm before it graduates into golden_dataset/cases.json.
    knowledge_store = InMemoryKnowledgeStore()
    knowledge_store.save_document(
        KnowledgeDocument(
            source_id="rag_revenue_policy_2026",
            title="Revenue metric policy and anomaly explanation",
            doc_type="policy",
            publish_time=datetime(2026, 6, 25, tzinfo=timezone.utc),
        )
    )
    knowledge_store.save_chunk(
        DocumentChunk(
            chunk_id="rag_revenue_policy_2026_chunk_1",
            source_id="rag_revenue_policy_2026",
            chunk_index=1,
            chunk_text="Revenue is calculated from paid orders only.",
        )
    )
    app = ChatBIApplication(orchestrator=SimpleOrchestrator(knowledge_store=knowledge_store))

    app.handle_chat_query(make_payload("Why is revenue calculated from paid orders only?"))

    candidates = app.mine_golden_dataset_candidates()

    assert [candidate.question for candidate in candidates] == [
        "Why is revenue calculated from paid orders only?"
    ]
    assert candidates[0].candidate_chunks[0].chunk_id == "rag_revenue_policy_2026_chunk_1"


def test_mine_golden_dataset_candidates_excludes_questions_with_no_rag_evidence() -> None:
    app = ChatBIApplication()

    app.handle_chat_query(make_payload("Show revenue trend."))

    assert app.mine_golden_dataset_candidates() == ()


def test_handle_eval_run_omits_retrieval_metrics_when_no_case_has_expected_chunk_ids() -> None:
    # FR-FV03-028: observability-only — a suite with no Golden Dataset
    # cases (the default SQL-only smoke questions) must not report a
    # meaningless default retrieval score.
    app = ChatBIApplication()

    envelope = app.handle_eval_run(
        user_id="u_001",
        trace_id="trc_eval_no_retrieval",
        payload=EvalRunRequestPayload(
            eval_suite_id="backend_api_smoke",
            questions=("Show revenue trend.", "DROP TABLE orders"),
            locale=Locale.EN,
            role=UserRole.ANALYST,
        ),
    )

    assert envelope.data is not None
    metric_breakdown = envelope.data["metric_breakdown"]
    assert "retrieval_hit_rate" not in metric_breakdown
    assert "retrieval_mrr" not in metric_breakdown


def test_handle_eval_report_returns_saved_eval_run_report() -> None:
    app = ChatBIApplication()

    run_envelope = app.handle_eval_run(
        user_id="u_001",
        trace_id="trc_eval_report_seed",
        payload=EvalRunRequestPayload(
            eval_suite_id="backend_api_smoke",
            questions=("Show revenue trend.", "DROP TABLE orders"),
            locale=Locale.EN,
            role=UserRole.ANALYST,
        ),
    )
    assert run_envelope.data is not None
    eval_run_id = run_envelope.data["eval_run_id"]
    assert isinstance(eval_run_id, str)

    report_envelope = app.handle_eval_report(
        user_id="u_001",
        trace_id="trc_eval_report_lookup",
        eval_run_id=eval_run_id,
    )

    assert report_envelope.code == 0
    assert report_envelope.data is not None
    assert report_envelope.data["eval_run_id"] == eval_run_id
    assert report_envelope.data["eval_suite_id"] == "backend_api_smoke"
    assert report_envelope.data["total_cases"] == 2
    assert report_envelope.data["overall_score"] == 1.0
    assert report_envelope.data["metric_breakdown"]["sql_safety"] == 1.0
    assert report_envelope.data["failed_cases_detail"] == ()


def test_handle_eval_report_returns_not_found_for_missing_eval_run() -> None:
    app = ChatBIApplication()

    envelope = app.handle_eval_report(
        user_id="u_001",
        trace_id="trc_eval_report_missing",
        eval_run_id="eval_missing",
    )

    assert envelope.code is ApiErrorCode.REQ_INVALID_ARGUMENT
    assert envelope.message == "Eval run id was not found."
    assert envelope.trace_id == "trc_eval_report_missing"
