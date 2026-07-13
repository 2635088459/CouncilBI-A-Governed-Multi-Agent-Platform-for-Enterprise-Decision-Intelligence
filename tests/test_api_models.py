from datetime import datetime, timezone

import pytest

from chatbi.api.models import (
    ApiErrorCode,
    EvalRunResultPayload,
    ChatQueryRequestPayload,
    api_error_for_warning,
    observability_span_payload,
    quality_dashboard_payload,
    success_envelope,
    trace_event_payload,
    to_chat_query_response,
)
from chatbi.core.contracts import (
    ErrorCode,
    Locale,
    QueryAnswer,
    RetrievalStats,
    TableResult,
    UserRole,
    WarningMessage,
    new_trace_id,
)
from chatbi.observability import (
    AlertRuleId,
    ObservabilitySpan,
    SloStatus,
    TraceSpanName,
    TraceSpanStatus,
)
from chatbi.trace_events import TraceEvent, TraceEventStatus


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
        analytics_result={"forecast_result": {"model_used": "moving_average"}},
        evidence_uncertainty=True,
        retrieval_stats=RetrievalStats(
            candidate_count=3,
            filtered_count=2,
            reranked_count=1,
            selected_count=1,
            latency_ms=12.5,
        ),
        confidence=0.9,
    )

    response = to_chat_query_response(
        answer,
        agent_timeline=(
            {
                "agent_name": "sql_agent",
                "status": "succeeded",
                "duration_ms": 1,
                "summary": "SQL generated.",
            },
        ),
    )

    assert response.answer_text == answer.answer_text
    assert response.sql_text == answer.sql_text
    assert response.table_result == answer.table_result
    assert response.trace_id == trace_id
    assert response.analytics_result == answer.analytics_result
    assert response.evidence_uncertainty is True
    assert response.retrieval_stats == answer.retrieval_stats
    assert response.agent_timeline[0]["agent_name"] == "sql_agent"
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
        analytics_result={"anomaly_result": {"anomaly_level": "none"}},
    )

    envelope = success_envelope(to_chat_query_response(answer))

    assert envelope.code == 0
    assert envelope.message == "ok"
    assert envelope.trace_id == answer.trace_id
    assert envelope.data is not None
    assert envelope.data["answer_text"] == answer.answer_text
    assert envelope.data["sql_text"] == answer.sql_text
    assert envelope.data["table_result"] == answer.table_result
    assert envelope.data["analytics_result"] == answer.analytics_result
    assert envelope.data["agent_timeline"] == ()
    assert envelope.data["evidence_uncertainty"] is False
    assert envelope.data["retrieval_stats"] is None


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


# 10-followups/13 (Spec FV10.13 §8.3, TC-FV10-212/213): SQL_DENY_UNRECOGNIZED_OUTPUT
# must map to a distinct ApiErrorCode, and the three pre-existing guardrail
# denial codes must keep mapping to SQL_GUARDRAIL_BLOCKED unchanged.
def test_api_error_for_warning_maps_unrecognized_output_to_sql_not_queryable() -> None:
    warning = WarningMessage(
        code=ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT,
        message="The model's output was not a single read-only query.",
    )

    assert api_error_for_warning(warning) is ApiErrorCode.SQL_NOT_QUERYABLE


@pytest.mark.parametrize(
    "error_code",
    (ErrorCode.SQL_DENY_STATEMENT, ErrorCode.SQL_DENY_OBJECT, ErrorCode.SQL_DENY_FUNCTION),
)
def test_api_error_for_warning_still_maps_guardrail_denials_to_sql_guardrail_blocked(
    error_code: ErrorCode,
) -> None:
    warning = WarningMessage(code=error_code, message="denied")

    assert api_error_for_warning(warning) is ApiErrorCode.SQL_GUARDRAIL_BLOCKED


def test_observability_span_payload_is_json_friendly() -> None:
    span = ObservabilitySpan(
        trace_id="trc_payload",
        span_name=TraceSpanName.SQL_GENERATED,
        status=TraceSpanStatus.SUCCEEDED,
        duration_ms=3,
        attributes={"sql_text": "SELECT 1"},
    )

    payload = observability_span_payload(span)

    assert payload.trace_id == "trc_payload"
    assert payload.span_name == "sql_generated"
    assert payload.status == "succeeded"
    assert isinstance(payload.occurred_at, str)
    assert payload.duration_ms == 3
    assert payload.attributes["sql_text"] == "SELECT 1"


def test_trace_event_payload_is_json_friendly() -> None:
    started_at = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    event = TraceEvent(
        trace_id="trc_event_payload",
        service="backend-api",
        span_name="request_received",
        status=TraceEventStatus.SUCCEEDED,
        started_at=started_at,
        ended_at=started_at,
        latency_ms=0,
    )

    payload = trace_event_payload(event)

    assert payload.trace_id == "trc_event_payload"
    assert payload.service == "backend-api"
    assert payload.status == "succeeded"
    assert payload.started_at == "2026-07-01T12:00:00+00:00"
    assert payload.ended_at == "2026-07-01T12:00:00+00:00"
    assert payload.latency_ms == 0


def test_quality_dashboard_payload_includes_slo_and_release_gate_summary() -> None:
    dashboard = quality_dashboard_payload(
        slo_statuses=(
            SloStatus(
                rule_id=AlertRuleId.E2E_ERROR_RATE,
                endpoint="/api/v1/chat/query",
                target=0.02,
                observed_value=0.0,
                passing=True,
                sample_count=20,
            ),
        ),
        alerts=(),
        latest_eval_result=EvalRunResultPayload(
            eval_run_id="eval_001",
            eval_suite_id="backend_api_smoke",
            total_cases=2,
            passed_cases=2,
            failed_cases=0,
            overall_score=1.0,
            average_confidence=0.9,
            metric_breakdown={"sql_safety": 1.0},
            failed_cases_detail=(),
            release_gate_passed=True,
        ),
    )

    assert dashboard.active_slo_count == 1
    assert dashboard.slo_statuses[0]["rule_id"] == "e2e_error_rate"
    assert dashboard.slo_statuses[0]["passing"] is True
    assert dashboard.alerts == ()
    assert dashboard.release_gate is not None
    assert dashboard.release_gate["eval_run_id"] == "eval_001"
    assert dashboard.release_gate["total_cases"] == 2
    assert dashboard.release_gate["failed_cases"] == 0
    assert dashboard.release_gate["release_gate_passed"] is True
    assert dashboard.release_gate["eval_report_path"] == "/api/v1/evals/eval_001"
