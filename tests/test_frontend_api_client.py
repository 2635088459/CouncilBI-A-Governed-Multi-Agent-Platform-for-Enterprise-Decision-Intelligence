from typing import Any, Mapping

import pytest

from chatbi.core.contracts import Locale, UserRole
from chatbi.frontend.api_client import (
    FrontendAnalyticsRequest,
    FrontendApiClient,
    FrontendUserContext,
    parse_api_envelope,
)
from chatbi.frontend.observability import FrontendEventName, FrontendLogger


class FakeTransport:
    def __init__(self) -> None:
        self.last_path: str | None = None
        self.last_headers: Mapping[str, str] | None = None
        self.last_body: Mapping[str, Any] | None = None
        self.last_query: Mapping[str, str] | None = None

    def post_json(
        self,
        path: str,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
        query: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        self.last_path = path
        self.last_headers = headers
        self.last_body = body
        self.last_query = query
        if path == "/api/v2/analytics/analyze":
            return _analytics_envelope(
                trace_id=str(body["trace_id"]),
                request_id=str(headers["X-Request-Id"]),
            )
        if path == "/api/v2/analytics/tasks":
            return {
                "data": {
                    "task_id": "task_analytics_001",
                    "trace_id": body["trace_id"],
                    "kind": "analytics",
                    "status": "queued",
                    "payload": {"request": body},
                    "result": {},
                    "error_message": None,
                },
                "warnings": [],
                "error": None,
                "trace_id": body["trace_id"],
                "request_id": headers["X-Request-Id"],
            }
        return _query_envelope(trace_id=str(headers["X-Trace-Id"]))

    def get_json(
        self,
        path: str,
        headers: Mapping[str, str],
        query: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        self.last_path = path
        self.last_headers = headers
        self.last_query = query
        if path == "/api/v1/chat/history":
            return {
                "code": 0,
                "message": "ok",
                "trace_id": headers["X-Trace-Id"],
                "warnings": [],
                "timestamp": "2026-06-18T12:00:00Z",
                "data": {
                    "items": [{"trace_id": "trc_old", "question": "Show revenue"}],
                    "next_cursor": None,
                    "page_size": 20,
                },
            }
        if path == "/api/v1/metrics/catalog":
            return {
                "code": 0,
                "message": "ok",
                "trace_id": headers["X-Trace-Id"],
                "warnings": [],
                "timestamp": "2026-06-18T12:00:00Z",
                "data": {"metrics": [{"name": "revenue"}]},
            }
        if path.startswith("/api/v1/chat/tasks/"):
            return {
                "data": {
                    "task_id": path.rsplit("/", 1)[-1],
                    "trace_id": "trc_task",
                    "kind": "indexing",
                    "status": "succeeded",
                    "payload": {"document_id": "doc_001"},
                    "result": {"document_id": "doc_001", "chunk_count": 2},
                    "error_message": None,
                },
                "warnings": [],
                "error": None,
                "trace_id": headers["X-Trace-Id"],
                "request_id": headers["X-Request-Id"],
            }
        if path.startswith("/api/v2/analytics/results/"):
            return _analytics_envelope(
                trace_id=path.rsplit("/", 1)[-1],
                request_id=str(headers["X-Request-Id"]),
            )
        return {
            "code": 0,
            "message": "ok",
            "trace_id": headers["X-Trace-Id"],
            "warnings": [],
            "timestamp": "2026-06-18T12:00:00Z",
            "data": {"answer": _query_envelope(trace_id=path.rsplit("/", 1)[-1])["data"]},
        }


def test_submit_question_calls_backend_chat_query() -> None:
    transport = FakeTransport()
    logger = FrontendLogger()
    client = FrontendApiClient(transport, logger=logger)

    view_model = client.submit_question(
        context=_context(),
        question="Show revenue trend.",
        idempotency_key="idem_frontend_001",
    )

    assert transport.last_path == "/api/v1/chat/query"
    assert transport.last_headers is not None
    assert transport.last_headers["Authorization"] == "Bearer test-token"
    assert transport.last_headers["X-Trace-Id"].startswith("trc_")
    assert transport.last_headers["X-Request-Id"].startswith("req_")
    assert transport.last_headers["X-Session-Id"] == "s_001"
    assert transport.last_headers["Idempotency-Key"] == "idem_frontend_001"
    assert transport.last_body is not None
    assert transport.last_body["locale"] == "en"
    assert view_model.answer.text == "Revenue trend is ready."
    records = logger.store.list_all()
    assert len(records) == 2
    assert records[0].event is FrontendEventName.QUERY_SUBMITTED
    assert records[0].request_id == transport.last_headers["X-Request-Id"]
    assert records[0].session_id == "s_001"
    assert records[0].trace_id == transport.last_headers["X-Trace-Id"]
    assert records[1].event is FrontendEventName.API_REQUEST_COMPLETED
    assert records[1].request_id == transport.last_headers["X-Request-Id"]
    assert records[1].session_id == "s_001"
    assert records[1].trace_id == transport.last_headers["X-Trace-Id"]
    assert records[1].route == "/api/v1/chat/query"
    assert records[1].duration_ms is not None
    assert records[1].duration_ms >= 0
    assert records[1].status == "succeeded"


def test_parse_api_envelope_accepts_v2_success_shape() -> None:
    envelope = parse_api_envelope(
        {
            "data": {"answer_text": "ok"},
            "warnings": [{"code": "AGENT_PARTIAL_FAILURE", "message": "RAG skipped."}],
            "error": None,
            "trace_id": "tr_12345678",
            "request_id": "req_12345678",
        }
    )

    assert envelope.data == {"answer_text": "ok"}
    assert envelope.error is None
    assert envelope.trace_id == "tr_12345678"
    assert envelope.request_id == "req_12345678"
    assert envelope.warnings[0]["code"] == "AGENT_PARTIAL_FAILURE"


def test_parse_api_envelope_accepts_v2_error_shape() -> None:
    envelope = parse_api_envelope(
        {
            "data": None,
            "warnings": [],
            "error": {
                "code": "SQL_GUARDRAIL_DENIED",
                "message": "Only read-only SELECT queries are allowed.",
                "retryable": False,
            },
            "trace_id": "tr_12345678",
            "request_id": "req_12345678",
        }
    )

    assert envelope.error is not None
    assert envelope.error.code == "SQL_GUARDRAIL_DENIED"
    assert envelope.error.message == "Only read-only SELECT queries are allowed."
    assert envelope.error.retryable is False


def test_load_history_returns_history_view_model() -> None:
    transport = FakeTransport()
    client = FrontendApiClient(transport)

    history = client.load_history(context=_context())

    assert transport.last_path == "/api/v1/chat/history"
    assert history.items[0]["trace_id"] == "trc_old"
    assert history.next_cursor is None
    assert history.page_size == 20


def test_replay_query_returns_query_result_view_model() -> None:
    client = FrontendApiClient(FakeTransport())

    replay = client.replay_query(context=_context(), trace_id="trc_old")

    assert replay.trace_id == "trc_old"
    assert replay.answer.text == "Revenue trend is ready."


def test_load_metric_catalog_returns_metric_view_model() -> None:
    client = FrontendApiClient(FakeTransport())

    catalog = client.load_metric_catalog(context=_context())

    assert catalog.metrics[0]["name"] == "revenue"


def test_load_task_status_calls_backend_task_endpoint() -> None:
    transport = FakeTransport()
    client = FrontendApiClient(transport)

    status = client.load_task_status(context=_context(), task_id="task_001")

    assert transport.last_path == "/api/v1/chat/tasks/task_001"
    assert transport.last_query == {"user_id": "u_001"}
    assert status.task_id == "task_001"
    assert status.trace_id == "trc_task"
    assert status.status.value == "completed"
    assert status.label == "Completed"
    assert status.result["chunk_count"] == 2


def test_analyze_metric_calls_v2_analytics_endpoint() -> None:
    transport = FakeTransport()
    client = FrontendApiClient(transport)

    result = client.analyze_metric(
        context=_context(),
        request=_analytics_request("tr_frontend_analytics"),
    )

    assert transport.last_path == "/api/v2/analytics/analyze"
    assert transport.last_body is not None
    assert transport.last_body["metric_id"] == "revenue"
    assert transport.last_body["analysis_options"] == {
        "horizon": 2,
        "anomaly_z_threshold": 3.0,
    }
    assert result.trace_id == "tr_frontend_analytics"
    assert result.method == "rolling_zscore_linear_forecast"
    assert len(result.forecast_points) == 2


def test_enqueue_analytics_returns_task_status_view_model() -> None:
    transport = FakeTransport()
    client = FrontendApiClient(transport)

    status = client.enqueue_analytics(
        context=_context(),
        request=_analytics_request("tr_frontend_analytics_task"),
    )

    assert transport.last_path == "/api/v2/analytics/tasks"
    assert status.task_id == "task_analytics_001"
    assert status.kind == "analytics"
    assert status.status.value == "queued"


def test_load_analytics_result_calls_v2_result_endpoint() -> None:
    transport = FakeTransport()
    client = FrontendApiClient(transport)

    result = client.load_analytics_result(
        context=_context(),
        trace_id="tr_frontend_analytics_lookup",
    )

    assert transport.last_path == "/api/v2/analytics/results/tr_frontend_analytics_lookup"
    assert result.trace_id == "tr_frontend_analytics_lookup"
    assert result.model_version == "analytics-v2-rule-based-001"


def test_run_evaluation_calls_backend_eval_run() -> None:
    class EvalTransport(FakeTransport):
        def post_json(
            self,
            path: str,
            headers: Mapping[str, str],
            body: Mapping[str, Any],
            query: Mapping[str, str] | None = None,
        ) -> Mapping[str, Any]:
            self.last_path = path
            self.last_headers = headers
            self.last_body = body
            self.last_query = query
            return {
                "code": 0,
                "message": "ok",
                "trace_id": headers["X-Trace-Id"],
                "warnings": [],
                "timestamp": "2026-06-18T12:00:00Z",
                "data": {
                    "eval_run_id": "eval_001",
                    "eval_suite_id": "frontend_smoke",
                    "total_cases": 2,
                    "passed_cases": 2,
                    "failed_cases": 0,
                    "overall_score": 1.0,
                    "average_confidence": 0.91,
                    "metric_breakdown": {
                        "sql_safety": 1.0,
                        "answer_success": 1.0,
                    },
                    "failed_cases_detail": [],
                    "release_gate_passed": True,
                },
            }

    transport = EvalTransport()
    client = FrontendApiClient(transport)

    report = client.run_evaluation(
        context=_context(),
        eval_suite_id="frontend_smoke",
        questions=("Show revenue trend.",),
    )

    assert transport.last_path == "/api/v1/evals/run"
    assert transport.last_query == {"user_id": "u_001"}
    assert transport.last_body is not None
    assert transport.last_body["eval_suite_id"] == "frontend_smoke"
    assert transport.last_body["questions"] == ("Show revenue trend.",)
    assert report.eval_run_id == "eval_001"
    assert report.release_gate_passed is True


def test_submit_question_raises_on_error_envelope() -> None:
    class ErrorTransport(FakeTransport):
        def post_json(
            self,
            path: str,
            headers: Mapping[str, str],
            body: Mapping[str, Any],
            query: Mapping[str, str] | None = None,
        ) -> Mapping[str, Any]:
            return {
                "code": "AUTH_UNAUTHORIZED",
                "message": "Missing token.",
                "data": None,
                "trace_id": "trc_error",
                "warnings": [],
                "timestamp": "2026-06-18T12:00:00Z",
            }

    logger = FrontendLogger()
    client = FrontendApiClient(ErrorTransport(), logger=logger)

    with pytest.raises(ValueError, match="Missing token"):
        client.submit_question(context=_context(), question="Show revenue.")

    records = logger.store.list_all()
    assert records[1].event is FrontendEventName.API_REQUEST_COMPLETED
    assert records[1].status == "failed"
    assert records[1].error_code == "AUTH_UNAUTHORIZED"


def _context() -> FrontendUserContext:
    return FrontendUserContext(
        user_id="u_001",
        session_id="s_001",
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
        bearer_token="test-token",
    )


def _query_envelope(trace_id: str) -> Mapping[str, Any]:
    return {
        "code": 0,
        "message": "ok",
        "trace_id": trace_id,
        "warnings": [],
        "timestamp": "2026-06-18T12:00:00Z",
        "data": {
            "answer_text": "Revenue trend is ready.",
            "sql_text": "SELECT order_date, revenue FROM daily_revenue",
            "table_result": {
                "columns": ["order_date", "revenue"],
                "rows": [{"order_date": "2026-06-18", "revenue": 1000}],
            },
            "chart_spec": None,
            "evidence_list": [],
            "confidence": 0.9,
        },
    }


def _analytics_request(trace_id: str) -> FrontendAnalyticsRequest:
    return FrontendAnalyticsRequest(
        trace_id=trace_id,
        metric_id="revenue",
        semantic_version_id="sem_v2",
        time_column="date",
        value_column="revenue",
        grain="day",
        rows=(
            {"date": "2026-06-01", "revenue": 100.0},
            {"date": "2026-06-02", "revenue": 105.0},
            {"date": "2026-06-03", "revenue": 110.0},
        ),
        horizon=2,
    )


def _analytics_envelope(trace_id: str, request_id: str) -> Mapping[str, Any]:
    return {
        "data": {
            "trace_id": trace_id,
            "metric_id": "revenue",
            "semantic_version_id": "sem_v2",
            "result": {
                "anomaly_points": [],
                "forecast_points": [
                    {
                        "timestamp": "2026-06-04",
                        "value": 115.0,
                        "lower": 105.0,
                        "upper": 125.0,
                    },
                    {
                        "timestamp": "2026-06-05",
                        "value": 120.0,
                        "lower": 110.0,
                        "upper": 130.0,
                    },
                ],
                "confidence_interval": {"lower": 105.0, "upper": 130.0},
                "quality_warnings": [],
                "method": "rolling_zscore_linear_forecast",
                "model_version": "analytics-v2-rule-based-001",
                "explanation": "Deterministic analytics result.",
            },
        },
        "warnings": [],
        "error": None,
        "trace_id": trace_id,
        "request_id": request_id,
    }
