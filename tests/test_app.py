from chatbi.api.models import ApiErrorCode, ChatQueryRequestPayload
from chatbi.application.app import ChatBIApplication
from chatbi.core.contracts import ErrorCode, Locale, UserRole
from chatbi.observability import TraceSpanName, TraceSpanStatus


def make_payload(question: str = "Show revenue trend.") -> ChatQueryRequestPayload:
    return ChatQueryRequestPayload(
        user_id="u_001",
        session_id="s_001",
        question=question,
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
    )


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


def test_handle_chat_query_enforces_user_rate_limit() -> None:
    app = ChatBIApplication(rate_limit_per_minute=1)

    first = app.handle_chat_query(make_payload("Show revenue trend."), trace_id="trc_rate_one")
    second = app.handle_chat_query(make_payload("Show revenue trend."), trace_id="trc_rate_two")

    assert first.code == 0
    assert second.code is ApiErrorCode.RATE_LIMITED
    assert second.data is not None
    assert second.data["retry_after_seconds"] == 60


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
