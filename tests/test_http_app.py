from typing import Any

from fastapi.testclient import TestClient

from chatbi.api.models import ApiErrorCode
from chatbi.api.http import create_app
from chatbi.application.app import ChatBIApplication
from chatbi.core.contracts import ErrorCode


def auth_headers(trace_id: str = "trc_http") -> dict[str, str]:
    return {
        "Authorization": "Bearer test-token",
        "X-Trace-Id": trace_id,
    }


def assert_unified_envelope(body: dict[str, Any], trace_id: str) -> None:
    assert set(body) == {
        "code",
        "message",
        "data",
        "trace_id",
        "warnings",
        "timestamp",
    }
    assert body["trace_id"] == trace_id
    assert isinstance(body["warnings"], list)
    assert isinstance(body["timestamp"], str)


def test_chat_query_endpoint_returns_success_envelope() -> None:
    client: Any = TestClient(create_app())

    response = client.post(
        "/api/v1/chat/query",
        headers=auth_headers(),
        json={
            "user_id": "u_001",
            "session_id": "s_001",
            "question": "Show revenue trend.",
            "locale": "en",
            "role": "business_user",
        },
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 200
    assert body["code"] == 0
    assert body["message"] == "ok"
    assert body["trace_id"].startswith("trc_")
    assert body["data"]["answer_text"] == "Revenue trend is ready."
    assert body["data"]["sql_text"].startswith("SELECT ")


def test_chat_query_endpoint_blocks_dangerous_sql() -> None:
    client: Any = TestClient(create_app())

    response = client.post(
        "/api/v1/chat/query",
        headers=auth_headers("trc_blocked"),
        json={
            "user_id": "u_001",
            "session_id": "s_001",
            "question": "DROP TABLE orders",
            "locale": "en",
            "role": "business_user",
        },
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 200
    assert body["code"] == ApiErrorCode.SQL_GUARDRAIL_BLOCKED
    assert body["warnings"][0]["code"] == ErrorCode.SQL_DENY_STATEMENT
    assert body["data"]["answer_text"].startswith("Request was blocked")


def test_chat_query_without_authorization_returns_auth_error_envelope() -> None:
    client: Any = TestClient(create_app())

    response = client.post(
        "/api/v1/chat/query",
        headers={"X-Trace-Id": "trc_no_auth"},
        json={
            "user_id": "u_001",
            "session_id": "s_001",
            "question": "Show revenue trend.",
            "locale": "en",
            "role": "business_user",
        },
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 401
    assert body["code"] == ApiErrorCode.AUTH_UNAUTHORIZED
    assert body["trace_id"] == "trc_no_auth"


def test_chat_query_without_trace_header_returns_invalid_argument_envelope() -> None:
    client: Any = TestClient(create_app())

    response = client.post(
        "/api/v1/chat/query",
        headers={"Authorization": "Bearer test-token"},
        json={
            "user_id": "u_001",
            "session_id": "s_001",
            "question": "Show revenue trend.",
            "locale": "en",
            "role": "business_user",
        },
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 400
    assert body["code"] == ApiErrorCode.REQ_INVALID_ARGUMENT
    assert body["trace_id"].startswith("trc_")


def test_chat_query_idempotency_key_returns_same_response() -> None:
    client: Any = TestClient(create_app())
    request_body = {
        "user_id": "u_001",
        "session_id": "s_001",
        "question": "Show revenue trend.",
        "locale": "en",
        "role": "business_user",
    }

    first = client.post(
        "/api/v1/chat/query",
        headers={**auth_headers("trc_idem_first"), "Idempotency-Key": "idem_http_001"},
        json=request_body,
    )
    second = client.post(
        "/api/v1/chat/query",
        headers={**auth_headers("trc_idem_second"), "Idempotency-Key": "idem_http_001"},
        json=request_body,
    )

    assert second.json() == first.json()
    assert second.json()["trace_id"] == "trc_idem_first"


def test_chat_history_endpoint_returns_paginated_items() -> None:
    client: Any = TestClient(create_app())
    client.post(
        "/api/v1/chat/query",
        headers=auth_headers("trc_history_seed"),
        json={
            "user_id": "u_001",
            "session_id": "s_001",
            "question": "Show revenue trend.",
            "locale": "en",
            "role": "business_user",
        },
    )

    response = client.get(
        "/api/v1/chat/history",
        headers=auth_headers("trc_history"),
        params={"user_id": "u_001", "page_size": 1},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 200
    assert body["code"] == 0
    assert body["trace_id"] == "trc_history"
    assert body["data"]["items"][0]["trace_id"] == "trc_history_seed"
    assert body["data"]["page_size"] == 1


def test_query_detail_endpoint_returns_trace_record() -> None:
    client: Any = TestClient(create_app())
    client.post(
        "/api/v1/chat/query",
        headers=auth_headers("trc_detail_seed"),
        json={
            "user_id": "u_001",
            "session_id": "s_001",
            "question": "Show revenue trend.",
            "locale": "en",
            "role": "business_user",
        },
    )

    response = client.get(
        "/api/v1/query/trc_detail_seed",
        headers=auth_headers("trc_detail_lookup"),
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 200
    assert body["data"]["trace_id"] == "trc_detail_seed"
    assert body["data"]["request"]["question"] == "Show revenue trend."


def test_metrics_catalog_endpoint_returns_metric_definitions() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v1/metrics/catalog",
        headers=auth_headers("trc_metrics"),
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 200
    assert body["code"] == 0
    assert {metric["name"] for metric in body["data"]["metrics"]} >= {"revenue", "order_count"}


def test_datasets_catalog_endpoint_returns_table_and_column_metadata() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v1/datasets/catalog",
        headers=auth_headers("trc_datasets"),
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()
    datasets = {dataset["name"]: dataset for dataset in body["data"]["datasets"]}
    customer_columns = {
        column["name"]: column
        for column in datasets["customers"]["columns"]
    }

    assert response.status_code == 200
    assert body["code"] == 0
    assert body["trace_id"] == "trc_datasets"
    assert {"orders", "customers"} <= set(datasets)
    assert datasets["orders"]["domain"] == "business_analytics"
    assert datasets["orders"]["partition_column"] == "order_date"
    assert customer_columns["customer_id"]["sensitivity"] == "P0"
    assert customer_columns["customer_id"]["is_primary_key"] is True


def test_audit_endpoint_returns_records_for_trace_id() -> None:
    client: Any = TestClient(create_app())
    client.post(
        "/api/v1/chat/query",
        headers=auth_headers("trc_audit_seed"),
        json={
            "user_id": "u_001",
            "session_id": "s_001",
            "question": "Show revenue trend.",
            "locale": "en",
            "role": "business_user",
        },
    )

    response = client.get(
        "/api/v1/audit/trc_audit_seed",
        headers=auth_headers("trc_audit_lookup"),
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 200
    assert body["code"] == 0
    assert body["data"]["trace_id"] == "trc_audit_seed"
    assert body["data"]["count"] == 1
    assert body["data"]["items"][0]["endpoint"] == "/api/v1/chat/query"
    assert body["data"]["items"][0]["status_code"] == 200


def test_audit_endpoint_returns_not_found_for_unknown_trace_id() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v1/audit/trc_missing_audit",
        headers=auth_headers("trc_audit_lookup_missing"),
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 404
    assert body["code"] == ApiErrorCode.REQ_INVALID_ARGUMENT
    assert body["trace_id"] == "trc_missing_audit"


def test_observability_trace_endpoint_returns_standard_spans() -> None:
    client: Any = TestClient(create_app())
    client.post(
        "/api/v1/chat/query",
        headers=auth_headers("trc_observability_seed"),
        json={
            "user_id": "u_001",
            "session_id": "s_001",
            "question": "Show revenue trend.",
            "locale": "en",
            "role": "business_user",
        },
    )

    response = client.get(
        "/api/v1/observability/traces/trc_observability_seed",
        headers=auth_headers("trc_observability_lookup"),
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()
    spans = body["data"]["spans"]

    assert response.status_code == 200
    assert body["code"] == 0
    assert body["trace_id"] == "trc_observability_seed"
    assert body["data"]["completed"] is True
    assert [span["span_name"] for span in spans] == [
        "request_received",
        "orchestration_planned",
        "sql_generated",
        "sql_guardrail_checked",
        "response_sent",
    ]
    assert spans[2]["attributes"]["sql_text"].startswith("SELECT ")
    assert spans[3]["attributes"]["decision"] == "allow"


def test_observability_trace_endpoint_returns_not_found_for_unknown_trace_id() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v1/observability/traces/trc_missing_observability",
        headers=auth_headers("trc_observability_lookup_missing"),
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 404
    assert body["code"] == ApiErrorCode.REQ_INVALID_ARGUMENT
    assert body["trace_id"] == "trc_missing_observability"


def test_quality_dashboard_endpoint_returns_active_slo_statuses() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v1/quality/dashboard",
        headers=auth_headers("trc_quality_dashboard"),
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()
    slo_statuses = body["data"]["slo_statuses"]

    assert response.status_code == 200
    assert body["code"] == 0
    assert body["trace_id"] == "trc_quality_dashboard"
    assert body["data"]["active_slo_count"] == 2
    assert {status["rule_id"] for status in slo_statuses} == {
        "e2e_error_rate",
        "chat_query_p95_latency",
    }
    assert body["data"]["alerts"] == []
    assert body["data"]["release_gate"] is None


def test_quality_dashboard_endpoint_includes_latest_release_gate_result() -> None:
    client: Any = TestClient(create_app())
    client.post(
        "/api/v1/evals/run",
        headers=auth_headers("trc_quality_eval"),
        params={"user_id": "u_001"},
        json={
            "eval_suite_id": "backend_api_smoke",
            "questions": ["Show revenue trend.", "DROP TABLE orders"],
            "locale": "en",
            "role": "analyst",
        },
    )

    response = client.get(
        "/api/v1/quality/dashboard",
        headers=auth_headers("trc_quality_after_eval"),
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()
    release_gate = body["data"]["release_gate"]

    assert response.status_code == 200
    assert release_gate["eval_suite_id"] == "backend_api_smoke"
    assert release_gate["overall_score"] == 1.0
    assert release_gate["release_gate_passed"] is True


def test_quality_dashboard_endpoint_uses_recorded_chat_query_samples() -> None:
    client: Any = TestClient(create_app(ChatBIApplication(rate_limit_per_minute=200)))
    request_body = {
        "user_id": "u_001",
        "session_id": "s_001",
        "question": "Show revenue trend.",
        "locale": "en",
        "role": "business_user",
    }
    for index in range(20):
        client.post(
            "/api/v1/chat/query",
            headers=auth_headers(f"trc_quality_sample_{index}"),
            json=request_body,
        )

    response = client.get(
        "/api/v1/quality/dashboard",
        headers=auth_headers("trc_quality_samples"),
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()
    statuses = {
        status["rule_id"]: status
        for status in body["data"]["slo_statuses"]
    }

    assert response.status_code == 200
    assert statuses["e2e_error_rate"]["sample_count"] == 20
    assert statuses["e2e_error_rate"]["observed_value"] == 0.0
    assert statuses["e2e_error_rate"]["passing"] is True
    assert statuses["chat_query_p95_latency"]["sample_count"] == 20


def test_eval_run_endpoint_returns_quality_report() -> None:
    client: Any = TestClient(create_app())

    response = client.post(
        "/api/v1/evals/run",
        headers=auth_headers("trc_eval_run"),
        params={"user_id": "u_001"},
        json={
            "eval_suite_id": "backend_api_smoke",
            "questions": [
                "Show revenue trend.",
                "DROP TABLE orders",
            ],
            "locale": "en",
            "role": "analyst",
        },
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 200
    assert body["code"] == 0
    assert body["trace_id"] == "trc_eval_run"
    assert body["data"]["eval_run_id"].startswith("eval_")
    assert body["data"]["eval_suite_id"] == "backend_api_smoke"
    assert body["data"]["total_cases"] == 2
    assert body["data"]["passed_cases"] == 2
    assert body["data"]["failed_cases"] == 0
    assert body["data"]["overall_score"] == 1.0
    assert body["data"]["metric_breakdown"]["sql_safety"] == 1.0
    assert body["data"]["release_gate_passed"] is True


def test_health_endpoint_returns_unified_envelope() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v1/health",
        headers=auth_headers("trc_health"),
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 200
    assert body["code"] == 0
    assert body["trace_id"] == "trc_health"
    assert body["data"] == {
        "status": "ok",
        "service": "chatbi-api",
    }


def test_health_endpoint_without_authorization_returns_auth_error_envelope() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v1/health",
        headers={"X-Trace-Id": "trc_health_no_auth"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 401
    assert body["code"] == ApiErrorCode.AUTH_UNAUTHORIZED
    assert body["trace_id"] == "trc_health_no_auth"


def test_core_endpoints_use_unified_envelope_shape() -> None:
    client: Any = TestClient(create_app())
    query_body = {
        "user_id": "u_001",
        "session_id": "s_001",
        "question": "Show revenue trend.",
        "locale": "en",
        "role": "business_user",
    }
    eval_body = {
        "eval_suite_id": "backend_api_smoke",
        "questions": ["Show revenue trend."],
        "locale": "en",
        "role": "analyst",
    }

    query_response = client.post(
        "/api/v1/chat/query",
        headers=auth_headers("trc_shape_query"),
        json=query_body,
    )
    endpoint_responses = (
        ("trc_shape_query", query_response),
        (
            "trc_shape_history",
            client.get(
                "/api/v1/chat/history",
                headers=auth_headers("trc_shape_history"),
                params={"user_id": "u_001"},
            ),
        ),
        (
            "trc_shape_query",
            client.get(
                "/api/v1/query/trc_shape_query",
                headers=auth_headers("trc_shape_detail"),
                params={"user_id": "u_001"},
            ),
        ),
        (
            "trc_shape_metrics",
            client.get(
                "/api/v1/metrics/catalog",
                headers=auth_headers("trc_shape_metrics"),
                params={"user_id": "u_001"},
            ),
        ),
        (
            "trc_shape_datasets",
            client.get(
                "/api/v1/datasets/catalog",
                headers=auth_headers("trc_shape_datasets"),
                params={"user_id": "u_001"},
            ),
        ),
        (
            "trc_shape_query",
            client.get(
                "/api/v1/audit/trc_shape_query",
                headers=auth_headers("trc_shape_audit"),
                params={"user_id": "u_001"},
            ),
        ),
        (
            "trc_shape_query",
            client.get(
                "/api/v1/observability/traces/trc_shape_query",
                headers=auth_headers("trc_shape_observability"),
                params={"user_id": "u_001"},
            ),
        ),
        (
            "trc_shape_eval",
            client.post(
                "/api/v1/evals/run",
                headers=auth_headers("trc_shape_eval"),
                params={"user_id": "u_001"},
                json=eval_body,
            ),
        ),
        (
            "trc_shape_quality",
            client.get(
                "/api/v1/quality/dashboard",
                headers=auth_headers("trc_shape_quality"),
                params={"user_id": "u_001"},
            ),
        ),
        (
            "trc_shape_health",
            client.get(
                "/api/v1/health",
                headers=auth_headers("trc_shape_health"),
                params={"user_id": "u_001"},
            ),
        ),
    )

    for expected_trace_id, response in endpoint_responses:
        assert response.status_code == 200
        assert_unified_envelope(response.json(), expected_trace_id)


def test_chat_query_rate_limit_returns_429_envelope() -> None:
    client: Any = TestClient(create_app(ChatBIApplication(rate_limit_per_minute=1)))
    request_body = {
        "user_id": "u_001",
        "session_id": "s_001",
        "question": "Show revenue trend.",
        "locale": "en",
        "role": "business_user",
    }

    client.post(
        "/api/v1/chat/query",
        headers=auth_headers("trc_rate_one"),
        json=request_body,
    )
    response = client.post(
        "/api/v1/chat/query",
        headers=auth_headers("trc_rate_two"),
        json=request_body,
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 429
    assert body["code"] == ApiErrorCode.RATE_LIMITED
    assert body["trace_id"] == "trc_rate_two"
