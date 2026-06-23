from typing import Any, Mapping

import pytest

from chatbi.core.contracts import Locale, UserRole
from chatbi.frontend.api_client import FrontendApiClient, FrontendUserContext


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
    client = FrontendApiClient(transport)

    view_model = client.submit_question(
        context=_context(),
        question="Show revenue trend.",
        idempotency_key="idem_frontend_001",
    )

    assert transport.last_path == "/api/v1/chat/query"
    assert transport.last_headers is not None
    assert transport.last_headers["Authorization"] == "Bearer test-token"
    assert transport.last_headers["X-Trace-Id"].startswith("trc_")
    assert transport.last_headers["Idempotency-Key"] == "idem_frontend_001"
    assert transport.last_body is not None
    assert transport.last_body["locale"] == "en"
    assert view_model.answer.text == "Revenue trend is ready."


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

    client = FrontendApiClient(ErrorTransport())

    with pytest.raises(ValueError, match="Missing token"):
        client.submit_question(context=_context(), question="Show revenue.")


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
