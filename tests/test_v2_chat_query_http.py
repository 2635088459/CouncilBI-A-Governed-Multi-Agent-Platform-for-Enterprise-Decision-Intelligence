from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient

from chatbi.analytics import AnalyticsService
from chatbi.analytics_repository import InMemoryAnalyticsRepository
from chatbi.api.http import create_app
from chatbi.api.http import database_readiness_checker_from_env
from chatbi.api.http import public_trace_id_from_legacy
from chatbi.api.http import readonly_database_probe_from_env
from chatbi.api.http import use_postgres_metadata_from_env
from chatbi.api.models import ApiEnvelope, ChatQueryRequestPayload
from chatbi.application.app import ChatBIApplication
from chatbi.core.contracts import Locale, UserRole
from chatbi.core.runtime_config import RuntimeConfig
from chatbi.history.request_metadata import (
    InMemoryRequestMetadataStore,
    REQUEST_METADATA_TABLE_SQL,
    RequestFinalStatus,
    RequestMetadataRecord,
)
from chatbi.history.query_results import RuntimeQueryResultRecord
from chatbi.governance import (
    GuardrailAuditRecordV2,
    GuardrailDecisionStatus,
    GuardrailRuleCode,
    InMemoryGuardrailAuditLogV2,
    RuleHit,
)
from chatbi.observability_logs import InMemoryObservabilityLogStore, ObservabilityLogger
from chatbi.orchestration.worker import AsyncTaskKind, AsyncTaskRequest, InMemoryWorkerHandoffQueue


class FakePsycopgCursor:
    def fetchone(self) -> None:
        return None


class FakePsycopgConnection:
    def __init__(self) -> None:
        self.commands: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> FakePsycopgCursor:
        self.commands.append((sql, params))
        return FakePsycopgCursor()

    def commit(self) -> None:
        self.commits += 1


class FakeRuntimeQueryResultStore:
    def __init__(self) -> None:
        self.records: list[RuntimeQueryResultRecord] = []

    def initialize_schema(self) -> None:
        return

    def save(self, record: RuntimeQueryResultRecord) -> None:
        self.records.append(record)

    def get(self, trace_id: str) -> RuntimeQueryResultRecord | None:
        for record in self.records:
            if record.trace_id == trace_id:
                return record
        return None


class ExplodingApplication(ChatBIApplication):
    def handle_chat_query(
        self,
        payload: ChatQueryRequestPayload,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ApiEnvelope:
        raise RuntimeError(
            "database password=super-secret traceback SecretToken should stay private"
        )


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def valid_request_body() -> dict[str, str]:
    return {
        "request_id": "req_12345678",
        "session_id": "ses_12345678",
        "user_id": "u_001",
        "role": "business_user",
        "locale": "en",
        "question": "Show revenue trend.",
    }


def valid_document_index_body() -> dict[str, object]:
    return {
        "document_id": "doc_v2_release_001",
        "source": "release-notes",
        "title": "June Release Notes",
        "document_type": "release_note",
        "published_at": "2026-06-29T10:00:00Z",
        "business_tags": ["revenue", "release"],
        "permission_tags": ["business_user"],
        "text": "Revenue dashboard drill-down filters were improved.",
    }


def valid_analytics_body(trace_id: str = "tr_analytics_http") -> dict[str, object]:
    return {
        "trace_id": trace_id,
        "metric_id": "revenue",
        "semantic_version_id": "sem_v2",
        "time_column": "date",
        "value_column": "revenue",
        "grain": "day",
        "rows": [
            {"date": "2026-06-01", "revenue": 100.0},
            {"date": "2026-06-02", "revenue": 105.0},
            {"date": "2026-06-03", "revenue": 110.0},
            {"date": "2026-06-04", "revenue": 115.0},
        ],
        "analysis_options": {"horizon": 2, "anomaly_z_threshold": 3.0},
    }


def test_public_trace_id_from_legacy_maps_internal_prefix_only() -> None:
    assert public_trace_id_from_legacy("trc_history_001") == "tr_history_001"
    assert public_trace_id_from_legacy("tr_public_001") == "tr_public_001"


def test_v2_chat_query_returns_version2_response_contract() -> None:
    client: Any = TestClient(create_app())

    response = client.post(
        "/api/v2/chat/query",
        headers=auth_headers(),
        json=valid_request_body(),
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 200
    assert set(body) == {"trace_id", "request_id", "data", "warnings", "error"}
    assert body["trace_id"].startswith("tr_")
    assert body["request_id"] == "req_12345678"
    assert body["error"] is None
    assert body["warnings"] == []
    assert body["data"]["answer_text"] == "Revenue trend is ready."
    assert body["data"]["table_result"]["columns"] == ["month", "revenue"]
    assert body["data"]["chart_spec"]["chart_type"] == "line"
    assert body["data"]["evidence_list"] == []
    assert 0.0 <= body["data"]["confidence"] <= 1.0


def test_use_postgres_metadata_from_env_accepts_explicit_truthy_values() -> None:
    assert use_postgres_metadata_from_env({"CHATBI_USE_POSTGRES_METADATA": "1"}) is True
    assert use_postgres_metadata_from_env({"CHATBI_USE_POSTGRES_METADATA": "true"}) is True
    assert use_postgres_metadata_from_env({"CHATBI_USE_POSTGRES_METADATA": "yes"}) is True
    assert use_postgres_metadata_from_env({}) is False


def test_database_readiness_checker_from_env_follows_postgres_metadata_switch() -> None:
    assert database_readiness_checker_from_env({}) is None
    assert database_readiness_checker_from_env({"CHATBI_USE_POSTGRES_METADATA": "1"}) is not None


def test_readonly_database_probe_from_env_follows_readonly_database_url() -> None:
    assert readonly_database_probe_from_env({}) is None
    assert (
        readonly_database_probe_from_env(
            {
                "CHATBI_READONLY_DATABASE_URL": (
                    "postgresql://chatbi_readonly:test@localhost:5432/chatbi"
                )
            }
        )
        is not None
    )


def test_create_app_can_wire_postgres_metadata_store_from_runtime_config() -> None:
    raw_connection = FakePsycopgConnection()
    seen_urls: list[str] = []

    def connect(database_url: str) -> FakePsycopgConnection:
        seen_urls.append(database_url)
        return raw_connection

    create_app(
        runtime_config=RuntimeConfig(
            database_url="postgresql://chatbi:test@localhost:5432/chatbi",
            redis_url=None,
            vector_store_url=None,
        ),
        request_metadata_connect=connect,
        use_postgres_metadata=True,
    )

    assert seen_urls == [
        "postgresql://chatbi:test@localhost:5432/chatbi",
        "postgresql://chatbi:test@localhost:5432/chatbi",
    ]
    command_sql = " ".join(sql for sql, _params in raw_connection.commands)
    assert REQUEST_METADATA_TABLE_SQL in command_sql
    assert "CREATE TABLE IF NOT EXISTS runtime.query_results" in command_sql
    assert raw_connection.commits == 2


def test_create_app_can_wire_postgres_guardrail_audit_store_from_runtime_config() -> None:
    raw_connection = FakePsycopgConnection()
    seen_urls: list[str] = []

    def connect(database_url: str) -> FakePsycopgConnection:
        seen_urls.append(database_url)
        return raw_connection

    client: Any = TestClient(
        create_app(
            runtime_config=RuntimeConfig(
                database_url="postgresql://chatbi:test@localhost:5432/chatbi",
                redis_url=None,
                vector_store_url=None,
            ),
            request_metadata_store=InMemoryRequestMetadataStore(),
            guardrail_audit_connect=connect,
            use_postgres_metadata=True,
        )
    )

    response = client.post(
        "/api/v1/sql/guardrail/check",
        headers={"Authorization": "Bearer test-token", "X-Trace-Id": "trc_pg_guardrail"},
        json={
            "user_id": "u_001",
            "role": "business_user",
            "sql_text": "DROP TABLE orders",
            "semantic_version_id": "sem_v1",
        },
    )

    command_sql = " ".join(sql for sql, _params in raw_connection.commands)
    assert response.status_code == 200
    assert seen_urls == ["postgresql://chatbi:test@localhost:5432/chatbi"]
    assert "CREATE TABLE IF NOT EXISTS query_audit_events" in command_sql
    assert "CREATE TABLE IF NOT EXISTS sql_rule_hits" in command_sql
    assert "INSERT INTO query_audit_events" in command_sql
    assert "INSERT INTO sql_rule_hits" in command_sql
    assert raw_connection.commits == 2


def test_v2_chat_query_persists_successful_request_metadata() -> None:
    metadata_store = InMemoryRequestMetadataStore()
    client: Any = TestClient(create_app(request_metadata_store=metadata_store))

    response = client.post(
        "/api/v2/chat/query",
        headers=auth_headers(),
        json=valid_request_body(),
    )
    trace_id = response.json()["trace_id"]

    record = metadata_store.get(trace_id)
    assert record is not None
    assert record.trace_id == trace_id
    assert record.request_id == "req_12345678"
    assert record.session_id == "ses_12345678"
    assert record.user_id == "u_001"
    assert record.question == "Show revenue trend."
    assert record.status is RequestFinalStatus.SUCCEEDED
    assert record.finished_at is not None
    assert record.error_code is None


def test_v2_chat_query_persists_runtime_query_result_with_public_trace_id() -> None:
    metadata_store = InMemoryRequestMetadataStore()
    query_result_store = FakeRuntimeQueryResultStore()
    client: Any = TestClient(
        create_app(
            request_metadata_store=metadata_store,
            runtime_query_result_store=query_result_store,
        )
    )

    response = client.post(
        "/api/v2/chat/query",
        headers=auth_headers(),
        json=valid_request_body(),
    )
    trace_id = response.json()["trace_id"]

    record = query_result_store.get(trace_id)
    assert record is not None
    assert trace_id.startswith("tr_")
    assert record.trace_id == trace_id
    assert record.session_id == "ses_12345678"
    assert record.user_id == "u_001"
    assert record.sql_text == "SELECT month, revenue FROM revenue_by_month LIMIT 100"
    assert record.table_result["columns"] == ("month", "revenue")


def test_v2_query_result_endpoint_returns_persisted_result_without_plaintext_sql() -> None:
    query_result_store = FakeRuntimeQueryResultStore()
    query_result_store.save(
        RuntimeQueryResultRecord(
            trace_id="tr_result_lookup",
            session_id="ses_12345678",
            user_id="u_001",
            question="Show revenue trend.",
            sql_text="SELECT month, revenue FROM revenue_by_month LIMIT 100",
            sql_hash="abc123",
            table_result={
                "columns": ["month", "revenue"],
                "rows": [{"month": "2026-01", "revenue": 1000.0}],
            },
            chart_spec={"chart_type": "line"},
            created_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
        )
    )
    client: Any = TestClient(create_app(runtime_query_result_store=query_result_store))

    response = client.get(
        "/api/v2/query-results/tr_result_lookup",
        headers={**auth_headers(), "X-Request-Id": "req_result_12345678"},
    )

    body: dict[str, Any] = response.json()
    data = body["data"]

    assert response.status_code == 200
    assert body["request_id"] == "req_result_12345678"
    assert body["error"] is None
    assert data["trace_id"] == "tr_result_lookup"
    assert data["sql_hash"] == "abc123"
    assert data["table_result"]["rows"] == [{"month": "2026-01", "revenue": 1000.0}]
    assert data["chart_spec"] == {"chart_type": "line"}
    assert data["created_at"] == "2026-06-26T00:00:00+00:00"
    assert "sql_text" not in data
    assert "SELECT month, revenue" not in str(body)


def test_v2_query_result_endpoint_returns_not_found_for_unknown_trace_id() -> None:
    client: Any = TestClient(create_app(runtime_query_result_store=FakeRuntimeQueryResultStore()))

    response = client.get(
        "/api/v2/query-results/tr_missing",
        headers={**auth_headers(), "X-Request-Id": "req_result_missing"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 404
    assert body["request_id"] == "req_result_missing"
    assert body["error"]["code"] == "QUERY_RESULT_NOT_FOUND"
    assert body["data"] is None


def test_v2_query_result_endpoint_requires_bearer_token() -> None:
    client: Any = TestClient(create_app(runtime_query_result_store=FakeRuntimeQueryResultStore()))

    response = client.get(
        "/api/v2/query-results/tr_result_lookup",
        headers={"X-Request-Id": "req_result_auth"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 401
    assert body["request_id"] == "req_result_auth"
    assert body["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_v2_governance_trace_endpoint_returns_request_result_and_guardrail_summary() -> None:
    metadata_store = InMemoryRequestMetadataStore()
    metadata_store.save_accepted(
        RequestMetadataRecord(
            trace_id="tr_governance_lookup",
            request_id="req_governance_lookup",
            session_id="ses_governance_lookup",
            user_id="u_001",
            role=UserRole.BUSINESS_USER,
            locale=Locale.EN,
            question="Show revenue trend.",
        )
    )
    metadata_store.mark_succeeded("tr_governance_lookup")

    query_result_store = FakeRuntimeQueryResultStore()
    query_result_store.save(
        RuntimeQueryResultRecord(
            trace_id="tr_governance_lookup",
            session_id="ses_governance_lookup",
            user_id="u_001",
            question="Show revenue trend.",
            sql_text="SELECT month, revenue FROM revenue_by_month LIMIT 100",
            sql_hash="hash_governance",
            table_result={
                "columns": ["month", "revenue"],
                "rows": [
                    {"month": "2026-01", "revenue": 1000.0},
                    {"month": "2026-02", "revenue": 1120.0},
                ],
            },
            chart_spec={"chart_type": "line"},
            created_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
        )
    )

    audit_log = InMemoryGuardrailAuditLogV2()
    audit_log.save_v2(
        GuardrailAuditRecordV2(
            trace_id="tr_governance_lookup",
            user_id="u_001",
            role="business_user",
            sql_hash="hash_governance",
            decision=GuardrailDecisionStatus.ALLOW,
            latency_ms=8,
            rule_hits=(
                RuleHit(
                    rule_code=GuardrailRuleCode.ROW_LIMIT_REWRITE,
                    message="A row limit was added to the SQL.",
                ),
            ),
            occurred_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
        )
    )
    client: Any = TestClient(
        create_app(
            request_metadata_store=metadata_store,
            runtime_query_result_store=query_result_store,
            guardrail_audit_log_v2=audit_log,
        )
    )

    response = client.get(
        "/api/v2/governance/traces/tr_governance_lookup",
        headers={**auth_headers(), "X-Request-Id": "req_governance_12345678"},
    )

    body: dict[str, Any] = response.json()
    data = body["data"]

    assert response.status_code == 200
    assert body["request_id"] == "req_governance_12345678"
    assert data["trace_id"] == "tr_governance_lookup"
    assert data["request"]["exists"] is True
    assert data["request"]["status"] == "succeeded"
    assert data["query_result"]["exists"] is True
    assert data["query_result"]["sql_hash"] == "hash_governance"
    assert data["query_result"]["row_count"] == 2
    assert data["query_result"]["has_chart"] is True
    assert data["guardrail"]["exists"] is True
    assert data["guardrail"]["decision"] == "allow"
    assert data["guardrail"]["latency_ms"] == 8
    assert data["guardrail"]["rule_hits"][0]["rule_code"] == "ROW_LIMIT_REWRITE"
    assert "sql_text" not in str(data)
    assert "SELECT month, revenue" not in str(data)


def test_v2_governance_trace_endpoint_returns_not_found_when_no_evidence_exists() -> None:
    client: Any = TestClient(create_app(runtime_query_result_store=FakeRuntimeQueryResultStore()))

    response = client.get(
        "/api/v2/governance/traces/tr_missing",
        headers={**auth_headers(), "X-Request-Id": "req_governance_missing"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 404
    assert body["request_id"] == "req_governance_missing"
    assert body["error"]["code"] == "GOVERNANCE_TRACE_NOT_FOUND"


def test_v2_governance_trace_endpoint_requires_bearer_token() -> None:
    client: Any = TestClient(create_app(runtime_query_result_store=FakeRuntimeQueryResultStore()))

    response = client.get(
        "/api/v2/governance/traces/tr_governance_lookup",
        headers={"X-Request-Id": "req_governance_auth"},
    )

    body: dict[str, Any] = response.json()
    assert response.status_code == 401
    assert body["request_id"] == "req_governance_auth"
    assert body["data"] is None
    assert body["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_v2_chat_query_writes_required_structured_logs() -> None:
    log_store = InMemoryObservabilityLogStore()
    logger = ObservabilityLogger(store=log_store)
    client: Any = TestClient(create_app(observability_logger=logger))

    response = client.post(
        "/api/v2/chat/query",
        headers=auth_headers(),
        json=valid_request_body(),
    )
    trace_id = response.json()["trace_id"]

    records = log_store.list_by_trace_id(trace_id)

    assert [record.event for record in records] == [
        "chat_query_accepted",
        "chat_query_succeeded",
    ]
    for record in records:
        assert record.trace_id == trace_id
        assert record.request_id == "req_12345678"
        assert record.service == "chatbi-api"
        assert record.event
        assert record.level.value in {"info", "warning", "error"}


def test_v2_chat_query_persists_failed_final_status_for_blocked_sql() -> None:
    metadata_store = InMemoryRequestMetadataStore()
    client: Any = TestClient(create_app(request_metadata_store=metadata_store))
    request_body = valid_request_body()
    request_body["question"] = "DROP TABLE orders"

    response = client.post(
        "/api/v2/chat/query",
        headers=auth_headers(),
        json=request_body,
    )
    trace_id = response.json()["trace_id"]

    record = metadata_store.get(trace_id)
    assert record is not None
    assert record.status is RequestFinalStatus.FAILED
    assert record.finished_at is not None
    assert record.error_code == "SQL_GUARDRAIL_BLOCKED"


def test_v2_chat_history_endpoint_returns_paginated_history_envelope() -> None:
    client: Any = TestClient(create_app())
    first_request = valid_request_body()
    first_request["request_id"] = "req_history_0001"
    first_request["question"] = "Show revenue trend."
    second_request = valid_request_body()
    second_request["request_id"] = "req_history_0002"
    second_request["question"] = "Show order count."
    client.post("/api/v2/chat/query", headers=auth_headers(), json=first_request)
    client.post("/api/v2/chat/query", headers=auth_headers(), json=second_request)

    response = client.get(
        "/api/v2/chat/history",
        headers={**auth_headers(), "X-Request-Id": "req_history_lookup"},
        params={"user_id": "u_001", "page_size": 1},
    )

    body: dict[str, Any] = response.json()
    data = body["data"]

    assert response.status_code == 200
    assert set(body) == {"trace_id", "request_id", "data", "warnings", "error"}
    assert body["trace_id"].startswith("tr_")
    assert body["request_id"] == "req_history_lookup"
    assert body["warnings"] == []
    assert body["error"] is None
    assert data["page_size"] == 1
    assert data["next_cursor"] == "1"
    assert len(data["items"]) == 1
    assert data["items"][0]["question"] == "Show order count."
    assert data["items"][0]["trace_id"].startswith("tr_")
    assert not data["items"][0]["trace_id"].startswith("trc_")


def test_v2_chat_history_endpoint_requires_bearer_token() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v2/chat/history",
        headers={"X-Request-Id": "req_history_auth"},
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 401
    assert body["request_id"] == "req_history_auth"
    assert body["data"] is None
    assert body["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_v2_fastapi_validation_error_uses_v2_envelope() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v2/chat/history",
        headers={**auth_headers(), "X-Request-Id": "req_history_missing_user"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 400
    assert set(body) == {"trace_id", "request_id", "data", "warnings", "error"}
    assert body["trace_id"].startswith("tr_")
    assert body["request_id"] == "req_history_missing_user"
    assert body["data"] is None
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["retryable"] is False
    assert "code" not in body
    assert "timestamp" not in body


def test_v2_metrics_catalog_endpoint_returns_metric_definitions() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v2/metrics/catalog",
        headers={**auth_headers(), "X-Request-Id": "req_metrics_12345678"},
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()
    data = body["data"]
    revenue = next(metric for metric in data["metrics"] if metric["name"] == "revenue")

    assert response.status_code == 200
    assert set(body) == {"trace_id", "request_id", "data", "warnings", "error"}
    assert body["trace_id"].startswith("tr_")
    assert body["request_id"] == "req_metrics_12345678"
    assert body["warnings"] == []
    assert body["error"] is None
    assert {metric["name"] for metric in data["metrics"]} >= {"revenue", "order_count"}
    assert revenue["id"] == "revenue"
    assert revenue["formula"] == "SUM(orders.order_amount) WHERE status='paid'"
    assert revenue["owner"] == "analytics"
    assert revenue["status"] == "active"
    assert revenue["semantic_version_id"] == "sem_v1"


def test_v2_metrics_catalog_endpoint_requires_bearer_token() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v2/metrics/catalog",
        headers={"X-Request-Id": "req_metrics_auth"},
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 401
    assert body["request_id"] == "req_metrics_auth"
    assert body["data"] is None
    assert body["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_v2_datasets_catalog_endpoint_returns_dataset_metadata() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v2/datasets/catalog",
        headers={**auth_headers(), "X-Request-Id": "req_datasets_12345678"},
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()
    datasets = {dataset["name"]: dataset for dataset in body["data"]["datasets"]}
    customer_columns = {
        column["name"]: column
        for column in datasets["customers"]["columns"]
    }

    assert response.status_code == 200
    assert set(body) == {"trace_id", "request_id", "data", "warnings", "error"}
    assert body["trace_id"].startswith("tr_")
    assert body["request_id"] == "req_datasets_12345678"
    assert body["warnings"] == []
    assert body["error"] is None
    assert {"orders", "customers"} <= set(datasets)
    assert datasets["orders"]["domain"] == "business_analytics"
    assert datasets["orders"]["partition_column"] == "order_date"
    assert customer_columns["user_email"]["sensitivity"] == "P1"
    assert customer_columns["customer_id"]["is_primary_key"] is True


def test_v2_datasets_catalog_endpoint_requires_bearer_token() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v2/datasets/catalog",
        headers={"X-Request-Id": "req_datasets_auth"},
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 401
    assert body["request_id"] == "req_datasets_auth"
    assert body["data"] is None
    assert body["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_v2_health_endpoint_returns_service_status() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v2/health",
        headers={**auth_headers(), "X-Request-Id": "req_health_12345678"},
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 200
    assert set(body) == {"trace_id", "request_id", "data", "warnings", "error"}
    assert body["trace_id"].startswith("tr_")
    assert body["request_id"] == "req_health_12345678"
    assert body["warnings"] == []
    assert body["error"] is None
    assert body["data"] == {
        "status": "ok",
        "service": "chatbi-api",
    }


def test_v2_health_endpoint_requires_bearer_token() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v2/health",
        headers={"X-Request-Id": "req_health_auth"},
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 401
    assert body["request_id"] == "req_health_auth"
    assert body["data"] is None
    assert body["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_v2_query_detail_endpoint_replays_public_trace_id() -> None:
    client: Any = TestClient(create_app())
    query_response = client.post(
        "/api/v2/chat/query",
        headers=auth_headers(),
        json=valid_request_body(),
    )
    public_trace_id = query_response.json()["trace_id"]

    response = client.get(
        f"/api/v2/query/{public_trace_id}",
        headers={**auth_headers(), "X-Request-Id": "req_querydetail_001"},
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()
    data = body["data"]

    assert response.status_code == 200
    assert set(body) == {"trace_id", "request_id", "data", "warnings", "error"}
    assert body["trace_id"].startswith("tr_")
    assert body["request_id"] == "req_querydetail_001"
    assert body["error"] is None
    assert data["trace_id"] == public_trace_id
    assert data["request"]["question"] == "Show revenue trend."
    assert data["answer"]["answer_text"] == "Revenue trend is ready."


def test_v2_query_detail_endpoint_returns_not_found_for_unknown_trace() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v2/query/tr_missing_12345678",
        headers={**auth_headers(), "X-Request-Id": "req_querydetail_missing"},
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 404
    assert body["request_id"] == "req_querydetail_missing"
    assert body["data"] is None
    assert body["error"]["code"] == "QUERY_NOT_FOUND"


def test_v2_query_detail_endpoint_requires_bearer_token() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v2/query/tr_missing_12345678",
        headers={"X-Request-Id": "req_querydetail_auth"},
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 401
    assert body["request_id"] == "req_querydetail_auth"
    assert body["data"] is None
    assert body["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_v2_request_metadata_endpoint_returns_saved_record() -> None:
    metadata_store = InMemoryRequestMetadataStore()
    client: Any = TestClient(create_app(request_metadata_store=metadata_store))
    query_response = client.post(
        "/api/v2/chat/query",
        headers=auth_headers(),
        json=valid_request_body(),
    )
    saved_trace_id = query_response.json()["trace_id"]

    response = client.get(
        f"/api/v2/requests/{saved_trace_id}",
        headers={**auth_headers(), "X-Request-Id": "req_metadata_12345678"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 200
    assert body["trace_id"].startswith("tr_")
    assert body["request_id"] == "req_metadata_12345678"
    assert body["error"] is None
    assert body["data"]["trace_id"] == saved_trace_id
    assert body["data"]["request_id"] == "req_12345678"
    assert body["data"]["status"] == "succeeded"
    assert body["data"]["accepted_at"]
    assert body["data"]["finished_at"]


def test_v2_request_metadata_endpoint_returns_not_found() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v2/requests/tr_missing12345678",
        headers={**auth_headers(), "X-Request-Id": "req_metadata_missing"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 404
    assert body["request_id"] == "req_metadata_missing"
    assert body["error"]["code"] == "REQUEST_NOT_FOUND"
    assert body["data"] is None


def test_v2_request_metadata_endpoint_requires_bearer_token() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v2/requests/tr_missing12345678",
        headers={"X-Request-Id": "req_metadata_auth"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 401
    assert body["request_id"] == "req_metadata_auth"
    assert body["error"]["code"] == "AUTH_UNAUTHORIZED"
    assert body["data"] is None


def test_v2_chat_task_status_endpoint_returns_task_envelope() -> None:
    queue = InMemoryWorkerHandoffQueue()
    task = queue.enqueue(
        AsyncTaskRequest(
            trace_id="tr_index_task_source",
            kind=AsyncTaskKind.INDEXING,
            payload={
                "document_id": "doc_v2_task",
                "text": "Document body should not be returned.",
                "text_length": 37,
            },
        )
    )
    queue.mark_succeeded(task.task_id, result={"document_id": "doc_v2_task", "chunk_count": 4})
    client: Any = TestClient(create_app(worker_handoff_queue=queue))

    response = client.get(
        f"/api/v2/chat/tasks/{task.task_id}",
        headers={**auth_headers(), "X-Request-Id": "req_task_12345678"},
    )

    body: dict[str, Any] = response.json()
    data = body["data"]

    assert response.status_code == 200
    assert set(body) == {"trace_id", "request_id", "data", "warnings", "error"}
    assert body["trace_id"].startswith("tr_")
    assert body["request_id"] == "req_task_12345678"
    assert body["warnings"] == []
    assert body["error"] is None
    assert data["task_id"] == task.task_id
    assert data["trace_id"] == "tr_index_task_source"
    assert data["kind"] == "indexing"
    assert data["status"] == "succeeded"
    assert data["payload"]["document_id"] == "doc_v2_task"
    assert data["payload"]["text_redacted"] is True
    assert "text" not in data["payload"]
    assert data["result"] == {"document_id": "doc_v2_task", "chunk_count": 4}
    assert "Document body should not be returned" not in str(body)


def test_v2_chat_task_status_endpoint_returns_not_found() -> None:
    client: Any = TestClient(create_app(worker_handoff_queue=InMemoryWorkerHandoffQueue()))

    response = client.get(
        "/api/v2/chat/tasks/task_missing",
        headers=auth_headers(),
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 404
    assert body["request_id"] == "req_task_lookup"
    assert body["data"] is None
    assert body["error"]["code"] == "TASK_NOT_FOUND"


def test_v2_chat_task_status_endpoint_requires_bearer_token() -> None:
    client: Any = TestClient(create_app(worker_handoff_queue=InMemoryWorkerHandoffQueue()))

    response = client.get("/api/v2/chat/tasks/task_missing")

    body: dict[str, Any] = response.json()

    assert response.status_code == 401
    assert body["data"] is None
    assert body["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_v2_document_index_endpoint_enqueues_task_envelope() -> None:
    queue = InMemoryWorkerHandoffQueue()
    client: Any = TestClient(create_app(worker_handoff_queue=queue))

    response = client.post(
        "/api/v2/documents/index",
        headers={**auth_headers(), "X-Request-Id": "req_docindex_001"},
        json=valid_document_index_body(),
    )

    body: dict[str, Any] = response.json()
    data = body["data"]
    task = queue.get(data["task_id"])

    assert response.status_code == 202
    assert set(body) == {"trace_id", "request_id", "data", "warnings", "error"}
    assert body["trace_id"].startswith("tr_")
    assert body["request_id"] == "req_docindex_001"
    assert body["warnings"] == []
    assert body["error"] is None
    assert data["kind"] == "indexing"
    assert data["status"] == "queued"
    assert data["document_id"] == "doc_v2_release_001"
    assert data["text_length"] == 51
    assert task is not None
    assert task.kind is AsyncTaskKind.INDEXING
    assert task.payload["text"] == "Revenue dashboard drill-down filters were improved."


def test_v2_document_index_endpoint_reuses_task_for_same_idempotency_key() -> None:
    queue = InMemoryWorkerHandoffQueue()
    client: Any = TestClient(create_app(worker_handoff_queue=queue))
    request_body = valid_document_index_body()

    first = client.post(
        "/api/v2/documents/index",
        headers={
            **auth_headers(),
            "X-Request-Id": "req_docindex_idem",
            "Idempotency-Key": "idx_v2_001",
        },
        json=request_body,
    )
    second = client.post(
        "/api/v2/documents/index",
        headers={
            **auth_headers(),
            "X-Request-Id": "req_docindex_retry",
            "Idempotency-Key": "idx_v2_001",
        },
        json=request_body,
    )

    first_body: dict[str, Any] = first.json()
    second_body: dict[str, Any] = second.json()

    assert first.status_code == 202
    assert second.status_code == 202
    assert second_body["request_id"] == "req_docindex_retry"
    assert second_body["data"]["task_id"] == first_body["data"]["task_id"]
    assert second_body["data"]["trace_id"] == first_body["data"]["trace_id"]
    assert len(queue.list_by_trace_id(first_body["data"]["trace_id"])) == 1


def test_v2_document_index_endpoint_rejects_reused_idempotency_key_with_different_body() -> None:
    queue = InMemoryWorkerHandoffQueue()
    client: Any = TestClient(create_app(worker_handoff_queue=queue))
    request_body = valid_document_index_body()

    client.post(
        "/api/v2/documents/index",
        headers={
            **auth_headers(),
            "X-Request-Id": "req_docindex_reuse",
            "Idempotency-Key": "idx_v2_002",
        },
        json=request_body,
    )
    request_body["text"] = "A different body must not reuse the same idempotency key."
    response = client.post(
        "/api/v2/documents/index",
        headers={
            **auth_headers(),
            "X-Request-Id": "req_docindex_reuse_retry",
            "Idempotency-Key": "idx_v2_002",
        },
        json=request_body,
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 400
    assert body["request_id"] == "req_docindex_reuse_retry"
    assert body["data"] is None
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == (
        "Idempotency-Key was reused with a different document index request."
    )


def test_v2_document_index_endpoint_rejects_invalid_document_body() -> None:
    request_body = valid_document_index_body()
    request_body["document_type"] = "unknown"
    request_body["text"] = ""
    client: Any = TestClient(create_app())

    response = client.post(
        "/api/v2/documents/index",
        headers={**auth_headers(), "X-Request-Id": "req_docindex_bad"},
        json=request_body,
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 400
    assert body["request_id"] == "req_docindex_bad"
    assert body["data"] is None
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_v2_document_index_endpoint_requires_bearer_token() -> None:
    client: Any = TestClient(create_app())

    response = client.post(
        "/api/v2/documents/index",
        headers={"X-Request-Id": "req_docindex_auth"},
        json=valid_document_index_body(),
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 401
    assert body["request_id"] == "req_docindex_auth"
    assert body["data"] is None
    assert body["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_v2_chat_query_rejects_missing_required_question() -> None:
    client: Any = TestClient(create_app())
    request_body = valid_request_body()
    request_body.pop("question")

    response = client.post(
        "/api/v2/chat/query",
        headers=auth_headers(),
        json=request_body,
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 400
    assert body["trace_id"].startswith("tr_")
    assert body["request_id"] == "req_12345678"
    assert body["data"] is None
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["retryable"] is False
    assert body["warnings"][0]["field"] == "question"


def test_v2_chat_query_rejects_invalid_request_id_shape() -> None:
    client: Any = TestClient(create_app())
    request_body = valid_request_body()
    request_body["request_id"] = "bad"

    response = client.post(
        "/api/v2/chat/query",
        headers=auth_headers(),
        json=request_body,
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 400
    assert body["request_id"] == "req_invalid_request"
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["warnings"][0]["field"] == "request_id"


def test_v2_chat_query_rejects_missing_bearer_token() -> None:
    client: Any = TestClient(create_app())

    response = client.post(
        "/api/v2/chat/query",
        json=valid_request_body(),
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 401
    assert body["trace_id"].startswith("tr_")
    assert body["request_id"] == "req_12345678"
    assert body["data"] is None
    assert body["error"]["code"] == "AUTH_UNAUTHORIZED"
    assert body["warnings"][0]["code"] == "AUTH_UNAUTHORIZED"


def test_v2_analytics_analyze_persists_result_and_result_endpoint_reads_it() -> None:
    repository = InMemoryAnalyticsRepository()
    service = AnalyticsService(repository)
    client: Any = TestClient(create_app(analytics_service=service))

    analyze_response = client.post(
        "/api/v2/analytics/analyze",
        headers={**auth_headers(), "X-Request-Id": "req_analytics_sync"},
        json=valid_analytics_body("tr_analytics_sync"),
    )
    result_response = client.get(
        "/api/v2/analytics/results/tr_analytics_sync",
        headers={**auth_headers(), "X-Request-Id": "req_analytics_lookup"},
    )

    analyze_body: dict[str, Any] = analyze_response.json()
    result_body: dict[str, Any] = result_response.json()

    assert analyze_response.status_code == 200
    assert analyze_body["request_id"] == "req_analytics_sync"
    assert analyze_body["data"]["result"]["method"] == "rolling_zscore_linear_forecast"
    assert len(analyze_body["data"]["result"]["forecast_points"]) == 2
    assert result_response.status_code == 200
    assert result_body["request_id"] == "req_analytics_lookup"
    assert result_body["data"]["trace_id"] == "tr_analytics_sync"
    assert result_body["data"]["parameters"]["horizon"] == 2
    assert repository.result_by_trace_id("tr_analytics_sync") is not None


def test_v2_analytics_analyze_returns_invalid_time_series_error() -> None:
    client: Any = TestClient(create_app())
    body = valid_analytics_body("tr_analytics_bad_time")
    body["rows"] = [
        {"date": "not-a-date", "revenue": 100.0},
        {"date": "2026-06-02", "revenue": 105.0},
        {"date": "2026-06-03", "revenue": 110.0},
    ]

    response = client.post(
        "/api/v2/analytics/analyze",
        headers={**auth_headers(), "X-Request-Id": "req_analytics_bad_time"},
        json=body,
    )

    response_body: dict[str, Any] = response.json()

    assert response.status_code == 400
    assert response_body["trace_id"] == "tr_analytics_bad_time"
    assert response_body["error"]["code"] == "ANALYTICS_INVALID_TIME_SERIES"


def test_v2_analytics_task_endpoint_enqueues_analytics_task() -> None:
    queue = InMemoryWorkerHandoffQueue()
    client: Any = TestClient(create_app(worker_handoff_queue=queue))

    response = client.post(
        "/api/v2/analytics/tasks",
        headers={**auth_headers(), "X-Request-Id": "req_analytics_task"},
        json=valid_analytics_body("tr_analytics_task"),
    )

    body: dict[str, Any] = response.json()
    task = queue.get(body["data"]["task_id"])

    assert response.status_code == 202
    assert body["request_id"] == "req_analytics_task"
    assert body["data"]["kind"] == "analytics"
    assert body["data"]["status"] == "queued"
    assert body["data"]["payload"]["request"]["metric_id"] == "revenue"
    assert task is not None
    assert task.kind is AsyncTaskKind.ANALYTICS


def test_v2_analytics_result_endpoint_returns_not_found() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v2/analytics/results/tr_missing_analytics",
        headers={**auth_headers(), "X-Request-Id": "req_analytics_missing"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 404
    assert body["request_id"] == "req_analytics_missing"
    assert body["error"]["code"] == "ANALYTICS_RESULT_NOT_FOUND"


def test_v2_internal_api_error_returns_sanitized_envelope() -> None:
    client: Any = TestClient(
        create_app(ExplodingApplication()),
        raise_server_exceptions=False,
    )

    response = client.post(
        "/api/v2/chat/query",
        headers=auth_headers(),
        json=valid_request_body(),
    )

    body: dict[str, Any] = response.json()
    serialized_body = str(body)

    assert response.status_code == 500
    assert set(body) == {"trace_id", "request_id", "data", "warnings", "error"}
    assert body["trace_id"].startswith("tr_")
    assert body["request_id"] == "req_internal_error"
    assert body["data"] is None
    assert body["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "The API could not complete the request.",
        "retryable": False,
    }
    assert "super-secret" not in serialized_body
    assert "password" not in serialized_body
    assert "SecretToken" not in serialized_body
    assert "traceback" not in serialized_body.lower()
