from chatbi.api.models import ChatQueryRequestPayload
from chatbi.application.app import ChatBIApplication
from chatbi.core.contracts import ErrorCode, Locale, UserRole


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

    assert envelope.code == 0
    assert envelope.warnings
    assert envelope.warnings[0].code is ErrorCode.SQL_DENY_STATEMENT
    assert envelope.data is not None
    assert envelope.data["answer_text"].startswith("Request was blocked")


def test_blocked_sql_is_persisted_for_replay() -> None:
    app = ChatBIApplication()

    envelope = app.handle_chat_query(make_payload("DROP TABLE orders"))
    replayed = app.orchestrator.replay(envelope.trace_id)

    assert replayed is not None
    assert replayed.request.question == "DROP TABLE orders"
    assert replayed.failed_error_code is ErrorCode.SQL_DENY_STATEMENT
