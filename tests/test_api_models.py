from chatbi.api.models import (
    ChatQueryRequestPayload,
    success_envelope,
    to_chat_query_response,
)
from chatbi.core.contracts import (
    ErrorCode,
    Locale,
    QueryAnswer,
    TableResult,
    UserRole,
    WarningMessage,
    new_trace_id,
)


def test_chat_query_request_payload_converts_to_domain_request() -> None:
    payload = ChatQueryRequestPayload(
        user_id="u_001",
        session_id="s_001",
        question="Show revenue trend.",
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
    )

    request = payload.to_domain()

    assert request.user_id == "u_001"
    assert request.session_id == "s_001"
    assert request.question == "Show revenue trend."
    assert request.locale is Locale.EN
    assert request.role is UserRole.BUSINESS_USER


def test_query_answer_converts_to_chat_query_response_payload() -> None:
    trace_id = new_trace_id()
    answer = QueryAnswer(
        answer_text="Revenue trend is ready.",
        sql_text="SELECT month, revenue FROM revenue_by_month LIMIT 100",
        table_result=TableResult(
            columns=("month", "revenue"),
            rows=({"month": "2026-01", "revenue": 1000},),
        ),
        trace_id=trace_id,
        confidence=0.9,
    )

    response = to_chat_query_response(answer)

    assert response.answer_text == answer.answer_text
    assert response.sql_text == answer.sql_text
    assert response.table_result == answer.table_result
    assert response.trace_id == trace_id
    assert response.confidence == 0.9


def test_success_envelope_contains_trace_id_and_required_answer_fields() -> None:
    answer = QueryAnswer(
        answer_text="Revenue trend is ready.",
        sql_text="SELECT month, revenue FROM revenue_by_month LIMIT 100",
        table_result=TableResult(
            columns=("month", "revenue"),
            rows=({"month": "2026-01", "revenue": 1000},),
        ),
        trace_id=new_trace_id(),
    )

    envelope = success_envelope(to_chat_query_response(answer))

    assert envelope.code == 0
    assert envelope.message == "ok"
    assert envelope.trace_id == answer.trace_id
    assert envelope.data is not None
    assert envelope.data["answer_text"] == answer.answer_text
    assert envelope.data["sql_text"] == answer.sql_text
    assert envelope.data["table_result"] == answer.table_result


def test_success_envelope_preserves_warnings() -> None:
    warning = WarningMessage(
        code=ErrorCode.SQL_DENY_STATEMENT,
        message="Only SELECT statements are allowed.",
    )
    answer = QueryAnswer(
        answer_text="Request was blocked.",
        sql_text="DROP TABLE orders",
        table_result=TableResult(
            columns=("status",),
            rows=({"status": "blocked"},),
        ),
        trace_id=new_trace_id(),
        confidence=0.0,
        warnings=(warning,),
    )

    envelope = success_envelope(to_chat_query_response(answer))

    assert envelope.warnings == (warning,)
    assert envelope.trace_id == answer.trace_id
