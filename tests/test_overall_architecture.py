from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chatbi.core.contracts import (
    ErrorCode,
    GuardrailDecision,
    GuardrailResult,
    Locale,
    QueryAnswer,
    QueryHistoryRecord,
    QueryHistoryStatus,
    QueryRequest,
    TableResult,
    UserRole,
    ensure_required_answer_fields,
    low_confidence_warning,
    new_trace_id,
)


def test_new_trace_id_uses_required_prefix() -> None:
    trace_id = new_trace_id()

    assert trace_id.startswith("trc_")
    assert len(trace_id) > len("trc_")


def test_query_answer_contains_required_architecture_fields() -> None:
    answer = QueryAnswer(
        answer_text="Revenue increased by 12%.",
        sql_text="SELECT month, revenue FROM revenue_by_month LIMIT 100",
        table_result=TableResult(
            columns=("month", "revenue"),
            rows=({"month": "2026-01", "revenue": 1000},),
        ),
        trace_id=new_trace_id(),
    )

    ensure_required_answer_fields(answer)


def test_query_answer_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError, match="confidence"):
        QueryAnswer(
            answer_text="Invalid confidence.",
            sql_text="SELECT 1",
            table_result=TableResult(columns=("value",), rows=({"value": 1},)),
            trace_id=new_trace_id(),
            confidence=1.5,
        )


def test_query_answer_rejects_missing_trace_prefix() -> None:
    with pytest.raises(ValueError, match="trace_id"):
        QueryAnswer(
            answer_text="Missing trace prefix.",
            sql_text="SELECT 1",
            table_result=TableResult(columns=("value",), rows=({"value": 1},)),
            trace_id="wrong-prefix",
        )


def test_required_answer_fields_reject_empty_sql() -> None:
    answer = QueryAnswer(
        answer_text="Answer exists.",
        sql_text=" ",
        table_result=TableResult(columns=("value",), rows=({"value": 1},)),
        trace_id=new_trace_id(),
    )

    with pytest.raises(ValueError, match="sql_text"):
        ensure_required_answer_fields(answer)


def test_guardrail_allow_result_requires_safe_sql() -> None:
    with pytest.raises(ValueError, match="safe_sql"):
        GuardrailResult(
            decision=GuardrailDecision.ALLOW,
            trace_id=new_trace_id(),
        )


def test_guardrail_deny_result_requires_error_code() -> None:
    with pytest.raises(ValueError, match="error_code"):
        GuardrailResult(
            decision=GuardrailDecision.DENY,
            trace_id=new_trace_id(),
            message="SQL was denied.",
        )


def test_drop_table_can_be_represented_as_statement_denial() -> None:
    result = GuardrailResult(
        decision=GuardrailDecision.DENY,
        trace_id=new_trace_id(),
        error_code=ErrorCode.SQL_DENY_STATEMENT,
        message="Only SELECT statements are allowed.",
    )

    assert result.decision is GuardrailDecision.DENY
    assert result.error_code is ErrorCode.SQL_DENY_STATEMENT


def test_low_confidence_warning_starts_below_threshold() -> None:
    warning = low_confidence_warning(0.59)

    assert warning is not None
    assert warning.code is ErrorCode.LOW_CONFIDENCE


def test_low_confidence_warning_is_absent_at_threshold() -> None:
    assert low_confidence_warning(0.60) is None


def test_query_history_record_preserves_failed_request_for_replay() -> None:
    request = QueryRequest(
        user_id="u_001",
        session_id="s_001",
        question="Show revenue trend.",
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
    )
    trace_id = new_trace_id()

    record = QueryHistoryRecord(
        trace_id=trace_id,
        request=request,
        answer=None,
        failed_error_code=ErrorCode.SQL_DENY_STATEMENT,
    )

    assert record.trace_id == trace_id
    assert record.request == request
    assert record.failed_error_code is ErrorCode.SQL_DENY_STATEMENT
    assert record.status is QueryHistoryStatus.FAILED
    assert record.sql_text is None


def test_query_history_record_derives_success_status_and_sql_text() -> None:
    trace_id = new_trace_id()
    request = QueryRequest(
        user_id="u_001",
        session_id="s_001",
        question="Show revenue trend.",
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
    )
    answer = QueryAnswer(
        answer_text="Revenue trend is ready.",
        sql_text="SELECT month, revenue FROM revenue_by_month LIMIT 100",
        table_result=TableResult(columns=("month", "revenue"), rows=()),
        trace_id=trace_id,
    )

    record = QueryHistoryRecord(
        trace_id=trace_id,
        request=request,
        answer=answer,
    )

    assert record.status is QueryHistoryStatus.SUCCEEDED
    assert record.sql_text == "SELECT month, revenue FROM revenue_by_month LIMIT 100"
