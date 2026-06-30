"""Typed API fixtures for testing the frontend without a real backend.

These fixtures use the same envelope shape that ``FrontendApiClient`` parses.
They are intentionally plain JSON-like dictionaries so component and state
tests can reuse them without spinning up FastAPI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


JsonObject = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class FrontendApiFixture:
    name: str
    method: str
    path: str
    response: JsonObject


def successful_chat_query_fixture() -> FrontendApiFixture:
    return FrontendApiFixture(
        name="successful_chat_query",
        method="POST",
        path="/api/v1/chat/query",
        response=_envelope(
            trace_id="trc_fixture_success",
            request_id="req_fixture_success",
            data={
                "answer_text": "Revenue trend is ready.",
                "sql_text": "SELECT order_month, revenue FROM monthly_revenue",
                "table_result": {
                    "columns": ["order_month", "revenue"],
                    "rows": [
                        {"order_month": "2026-01", "revenue": 1200},
                        {"order_month": "2026-02", "revenue": 1500},
                    ],
                },
                "chart_spec": {
                    "chart_type": "line",
                    "x_field": "order_month",
                    "y_fields": ["revenue"],
                    "title": "Revenue Trend",
                },
                "evidence_list": [
                    {
                        "source_id": "doc_001",
                        "title": "Revenue Review",
                        "citation_anchor": "p3",
                        "snippet": "Revenue increased after the campaign.",
                    }
                ],
                "confidence": 0.92,
            },
        ),
    )


def partial_failure_chat_query_fixture() -> FrontendApiFixture:
    fixture = successful_chat_query_fixture()
    return FrontendApiFixture(
        name="partial_failure_chat_query",
        method=fixture.method,
        path=fixture.path,
        response={
            **fixture.response,
            "trace_id": "trc_fixture_partial",
            "request_id": "req_fixture_partial",
            "warnings": [
                {
                    "code": "AGENT_PARTIAL_FAILURE",
                    "message": "Visualization agent failed; table data is still available.",
                }
            ],
        },
    )


def sql_guardrail_denied_fixture() -> FrontendApiFixture:
    return FrontendApiFixture(
        name="sql_guardrail_denied",
        method="POST",
        path="/api/v1/chat/query",
        response=_envelope(
            trace_id="trc_fixture_denied",
            request_id="req_fixture_denied",
            data=None,
            error={
                "code": "SQL_GUARDRAIL_DENIED",
                "message": "Only read-only SELECT queries are allowed.",
                "retryable": False,
            },
        ),
    )


def chat_history_fixture() -> FrontendApiFixture:
    return FrontendApiFixture(
        name="chat_history",
        method="GET",
        path="/api/v1/chat/history",
        response=_envelope(
            trace_id="trc_fixture_history",
            request_id="req_fixture_history",
            data={
                "items": [
                    {
                        "trace_id": "trc_fixture_success",
                        "session_id": "s_fixture",
                        "question": "Show revenue trend.",
                        "status": "succeeded",
                        "created_at": "2026-06-18T12:00:00Z",
                    }
                ],
                "next_cursor": None,
                "page_size": 20,
            },
        ),
    )


def metric_catalog_fixture() -> FrontendApiFixture:
    return FrontendApiFixture(
        name="metric_catalog",
        method="GET",
        path="/api/v1/metrics/catalog",
        response=_envelope(
            trace_id="trc_fixture_catalog",
            request_id="req_fixture_catalog",
            data={
                "metrics": [
                    {
                        "name": "revenue",
                        "sql_definition": "SUM(order_amount)",
                        "source_tables": ["orders"],
                        "semantic_version": "sem_v1",
                    }
                ]
            },
        ),
    )


def task_status_completed_fixture() -> FrontendApiFixture:
    return FrontendApiFixture(
        name="task_status_completed",
        method="GET",
        path="/api/v1/chat/tasks/task_fixture",
        response=_envelope(
            trace_id="trc_fixture_task_lookup",
            request_id="req_fixture_task_lookup",
            data={
                "task_id": "task_fixture",
                "trace_id": "trc_fixture_task",
                "kind": "indexing",
                "status": "succeeded",
                "payload": {"document_id": "doc_001"},
                "result": {"document_id": "doc_001", "chunk_count": 2},
                "error_message": None,
            },
        ),
    )


def evaluation_run_passed_fixture() -> FrontendApiFixture:
    return FrontendApiFixture(
        name="evaluation_run_passed",
        method="POST",
        path="/api/v1/evals/run",
        response=_envelope(
            trace_id="trc_fixture_eval",
            request_id="req_fixture_eval",
            data={
                "eval_run_id": "eval_fixture",
                "eval_suite_id": "frontend_smoke",
                "total_cases": 1,
                "passed_cases": 1,
                "failed_cases": 0,
                "overall_score": 1.0,
                "average_confidence": 0.92,
                "metric_breakdown": {"sql_safety": 1.0, "answer_success": 1.0},
                "failed_cases_detail": [],
                "release_gate_passed": True,
            },
        ),
    )


def all_frontend_api_fixtures() -> tuple[FrontendApiFixture, ...]:
    return (
        successful_chat_query_fixture(),
        partial_failure_chat_query_fixture(),
        sql_guardrail_denied_fixture(),
        chat_history_fixture(),
        metric_catalog_fixture(),
        task_status_completed_fixture(),
        evaluation_run_passed_fixture(),
    )


def _envelope(
    *,
    trace_id: str,
    request_id: str,
    data: JsonObject | None,
    warnings: list[JsonObject] | None = None,
    error: JsonObject | None = None,
) -> JsonObject:
    return {
        "data": data,
        "warnings": warnings or [],
        "error": error,
        "trace_id": trace_id,
        "request_id": request_id,
    }
