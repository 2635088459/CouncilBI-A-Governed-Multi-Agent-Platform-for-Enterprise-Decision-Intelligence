from typing import Any

from fastapi.testclient import TestClient

from chatbi.api.models import ApiEnvelope, ApiErrorCode
from chatbi.api.http import create_app
from chatbi.application.app import ChatBIApplication
from chatbi.core.contracts import ErrorCode
from chatbi.core.runtime_config import RuntimeConfig
from chatbi.governance import GuardrailDecisionStatus, InMemoryGuardrailAuditLogV2
from chatbi.history.query_results import RuntimeQueryResultRecord
from chatbi.orchestration.worker import (
    AsyncTaskKind,
    AsyncTaskRequest,
    AsyncTaskStatus,
    InMemoryWorkerHandoffQueue,
)


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
        "request_id",
        "warnings",
        "timestamp",
    }
    assert body["trace_id"] == trace_id
    assert body["request_id"].startswith("req_")
    assert isinstance(body["warnings"], list)
    assert isinstance(body["timestamp"], str)


class FakeReadOnlyCursor:
    description = (("month",), ("revenue",))

    def fetchmany(self, size: int) -> list[tuple[str, float]]:
        return [("2026-07", 1400.0)][:size]


class FakeReadOnlyConnection:
    def __init__(self) -> None:
        self.executed_sql: list[str] = []
        self.closed = False

    def execute(self, sql: str) -> FakeReadOnlyCursor:
        self.executed_sql.append(sql)
        return FakeReadOnlyCursor()

    def close(self) -> None:
        self.closed = True


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
    def handle_metrics_catalog(self, user_id: str, trace_id: str) -> ApiEnvelope:
        raise RuntimeError(
            "database password=super-secret traceback SecretToken should stay private"
        )


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
    assert body["request_id"].startswith("req_")
    assert body["data"]["answer_text"] == "Revenue trend is ready."
    assert body["data"]["sql_text"].startswith("SELECT ")


def test_chat_query_endpoint_saves_runtime_query_result_when_store_is_configured() -> None:
    query_result_store = FakeRuntimeQueryResultStore()
    client: Any = TestClient(create_app(runtime_query_result_store=query_result_store))

    response = client.post(
        "/api/v1/chat/query",
        headers=auth_headers("trc_runtime_result"),
        json={
            "user_id": "u_001",
            "session_id": "s_001",
            "question": "Show revenue trend.",
            "locale": "en",
            "role": "business_user",
        },
    )

    record = query_result_store.get("trc_runtime_result")

    assert response.status_code == 200
    assert record is not None
    assert record.session_id == "s_001"
    assert record.user_id == "u_001"
    assert record.question == "Show revenue trend."
    assert record.sql_text == "SELECT month, revenue FROM revenue_by_month LIMIT 100"
    assert record.table_result["columns"] == ("month", "revenue")


def test_chat_query_endpoint_uses_readonly_database_rows_when_configured() -> None:
    connection = FakeReadOnlyConnection()
    seen_urls: list[str] = []

    def connect(database_url: str) -> FakeReadOnlyConnection:
        seen_urls.append(database_url)
        return connection

    client: Any = TestClient(
        create_app(
            runtime_config=RuntimeConfig(
                database_url=None,
                readonly_database_url="postgresql://chatbi_readonly:test@db:5432/chatbi",
                redis_url=None,
                vector_store_url=None,
            ),
            readonly_query_connect=connect,
        )
    )

    response = client.post(
        "/api/v1/chat/query",
        headers=auth_headers("trc_readonly_rows"),
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
    assert body["data"]["table_result"]["rows"] == [
        {"month": "2026-07", "revenue": 1400.0}
    ]
    assert seen_urls == ["postgresql://chatbi_readonly:test@db:5432/chatbi"]
    assert connection.executed_sql == ["SELECT month, revenue FROM revenue_by_month LIMIT 100"]
    assert connection.closed is True


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
    assert body["request_id"] == "req_no_auth"


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
    assert body["request_id"].startswith("req_")


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


def test_chat_task_status_endpoint_returns_worker_task() -> None:
    queue = InMemoryWorkerHandoffQueue()
    task = queue.enqueue(
        AsyncTaskRequest(
            trace_id="trc_task_source",
            kind=AsyncTaskKind.ANALYTICS,
            payload={"question": "forecast revenue"},
        )
    )
    client: Any = TestClient(create_app(worker_handoff_queue=queue))

    response = client.get(
        f"/api/v1/chat/tasks/{task.task_id}",
        headers=auth_headers("trc_task_lookup"),
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 200
    assert body["trace_id"] == "trc_task_lookup"
    assert body["data"] == {
        "task_id": task.task_id,
        "trace_id": "trc_task_source",
        "kind": "analytics",
        "status": "queued",
        "payload": {"question": "forecast revenue"},
        "result": {},
        "error_message": None,
    }


def test_chat_task_status_endpoint_returns_not_found_for_unknown_task() -> None:
    client: Any = TestClient(create_app(worker_handoff_queue=InMemoryWorkerHandoffQueue()))

    response = client.get(
        "/api/v1/chat/tasks/task_missing",
        headers=auth_headers("trc_task_missing"),
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 404
    assert body["trace_id"] == "trc_task_missing"
    assert body["code"] == "REQ_INVALID_ARGUMENT"
    assert body["data"] is None


def test_document_index_endpoint_enqueues_indexing_task() -> None:
    queue = InMemoryWorkerHandoffQueue()
    client: Any = TestClient(create_app(worker_handoff_queue=queue))

    response = client.post(
        "/api/v1/documents/index",
        headers=auth_headers("trc_index_doc"),
        params={"user_id": "u_001"},
        json={
            "document_id": "doc_release_001",
            "source": "release-notes",
            "title": "June Release Notes",
            "document_type": "release_note",
            "published_at": "2026-06-29T10:00:00Z",
            "business_tags": ["revenue", "release"],
            "permission_tags": ["business_user"],
            "text": "Revenue dashboard drill-down filters were improved.",
        },
    )

    body: dict[str, Any] = response.json()
    task = queue.get(body["data"]["task_id"])

    assert response.status_code == 202
    assert body["trace_id"] == "trc_index_doc"
    assert body["data"]["kind"] == "indexing"
    assert body["data"]["status"] == "queued"
    assert body["data"]["document_id"] == "doc_release_001"
    assert body["data"]["text_length"] == 51
    assert task is not None
    assert task.kind is AsyncTaskKind.INDEXING
    assert task.payload["text"] == "Revenue dashboard drill-down filters were improved."


def test_document_index_endpoint_reuses_task_for_same_idempotency_key() -> None:
    queue = InMemoryWorkerHandoffQueue()
    client: Any = TestClient(create_app(worker_handoff_queue=queue))
    request_body = {
        "document_id": "doc_release_idem",
        "source": "release-notes",
        "title": "June Release Notes",
        "document_type": "release_note",
        "published_at": "2026-06-29T10:00:00Z",
        "business_tags": ["revenue", "release"],
        "permission_tags": ["business_user"],
        "text": "Revenue dashboard drill-down filters were improved.",
    }

    first = client.post(
        "/api/v1/documents/index",
        headers={**auth_headers("trc_index_idem_first"), "Idempotency-Key": "idx_001"},
        params={"user_id": "u_001"},
        json=request_body,
    )
    second = client.post(
        "/api/v1/documents/index",
        headers={**auth_headers("trc_index_idem_second"), "Idempotency-Key": "idx_001"},
        params={"user_id": "u_001"},
        json=request_body,
    )

    first_body: dict[str, Any] = first.json()
    second_body: dict[str, Any] = second.json()

    assert first.status_code == 202
    assert second.status_code == 202
    assert second_body["trace_id"] == "trc_index_idem_second"
    assert second_body["data"]["task_id"] == first_body["data"]["task_id"]
    assert second_body["data"]["trace_id"] == "trc_index_idem_first"
    assert queue.list_by_trace_id("trc_index_idem_first")[0].task_id == first_body["data"]["task_id"]
    assert queue.list_by_trace_id("trc_index_idem_second") == ()


def test_document_index_endpoint_rejects_reused_idempotency_key_with_different_body() -> None:
    queue = InMemoryWorkerHandoffQueue()
    client: Any = TestClient(create_app(worker_handoff_queue=queue))
    request_body = {
        "document_id": "doc_release_idem",
        "source": "release-notes",
        "title": "June Release Notes",
        "document_type": "release_note",
        "published_at": "2026-06-29T10:00:00Z",
        "business_tags": ["revenue", "release"],
        "permission_tags": ["business_user"],
        "text": "Revenue dashboard drill-down filters were improved.",
    }

    client.post(
        "/api/v1/documents/index",
        headers={**auth_headers("trc_index_reuse_first"), "Idempotency-Key": "idx_002"},
        params={"user_id": "u_001"},
        json=request_body,
    )
    request_body["text"] = "A different document body should not reuse the same key."
    response = client.post(
        "/api/v1/documents/index",
        headers={**auth_headers("trc_index_reuse_second"), "Idempotency-Key": "idx_002"},
        params={"user_id": "u_001"},
        json=request_body,
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 400
    assert body["trace_id"] == "trc_index_reuse_second"
    assert body["code"] == "REQ_INVALID_ARGUMENT"
    assert body["message"] == "Idempotency-Key was reused with a different document index request."
    assert queue.list_by_trace_id("trc_index_reuse_second") == ()


def test_document_index_task_status_redacts_document_text() -> None:
    queue = InMemoryWorkerHandoffQueue()
    client: Any = TestClient(create_app(worker_handoff_queue=queue))

    index_response = client.post(
        "/api/v1/documents/index",
        headers=auth_headers("trc_index_redact"),
        params={"user_id": "u_001"},
        json={
            "document_id": "doc_secret_001",
            "source": "incident-system",
            "title": "Incident Note",
            "document_type": "incident",
            "published_at": "2026-06-29T10:00:00Z",
            "business_tags": ["incident"],
            "permission_tags": ["admin"],
            "text": "Internal incident narrative should stay inside the worker payload.",
        },
    )
    task_id = index_response.json()["data"]["task_id"]

    response = client.get(
        f"/api/v1/chat/tasks/{task_id}",
        headers=auth_headers("trc_index_status"),
        params={"user_id": "u_001"},
    )

    payload = response.json()["data"]["payload"]

    assert response.status_code == 200
    assert payload["document_id"] == "doc_secret_001"
    assert payload["text_length"] == 66
    assert payload["text_redacted"] is True
    assert "text" not in payload
    assert "Internal incident narrative" not in str(response.json())


def test_document_index_task_status_returns_final_result() -> None:
    queue = InMemoryWorkerHandoffQueue()
    client: Any = TestClient(create_app(worker_handoff_queue=queue))
    index_response = client.post(
        "/api/v1/documents/index",
        headers=auth_headers("trc_index_done"),
        params={"user_id": "u_001"},
        json={
            "document_id": "doc_done_001",
            "source": "release-notes",
            "title": "Done Doc",
            "document_type": "release_note",
            "published_at": "2026-06-29T10:00:00Z",
            "business_tags": ["release"],
            "permission_tags": ["business_user"],
            "text": "Document indexing completed successfully.",
        },
    )
    task_id = index_response.json()["data"]["task_id"]
    queue.mark_running(task_id)
    queue.mark_succeeded(task_id, result={"document_id": "doc_done_001", "chunk_count": 2})

    response = client.get(
        f"/api/v1/chat/tasks/{task_id}",
        headers=auth_headers("trc_index_done_lookup"),
        params={"user_id": "u_001"},
    )

    data = response.json()["data"]

    assert response.status_code == 200
    assert data["status"] == AsyncTaskStatus.SUCCEEDED.value
    assert data["result"] == {"document_id": "doc_done_001", "chunk_count": 2}
    assert data["error_message"] is None


def test_document_index_task_status_returns_failure_reason() -> None:
    queue = InMemoryWorkerHandoffQueue()
    client: Any = TestClient(create_app(worker_handoff_queue=queue))
    task = queue.enqueue(
        AsyncTaskRequest(
            trace_id="trc_index_failed_source",
            kind=AsyncTaskKind.INDEXING,
            payload={"document_id": "doc_failed_001"},
        )
    )
    queue.mark_failed(task.task_id, error_message="embedding service unavailable")

    response = client.get(
        f"/api/v1/chat/tasks/{task.task_id}",
        headers=auth_headers("trc_index_failed_lookup"),
        params={"user_id": "u_001"},
    )

    data = response.json()["data"]

    assert response.status_code == 200
    assert data["status"] == AsyncTaskStatus.FAILED.value
    assert data["result"] == {}
    assert data["error_message"] == "embedding service unavailable"


def test_document_index_endpoint_rejects_invalid_body() -> None:
    client: Any = TestClient(create_app())

    response = client.post(
        "/api/v1/documents/index",
        headers=auth_headers("trc_index_invalid"),
        params={"user_id": "u_001"},
        json={
            "document_id": "doc_bad",
            "source": "release-notes",
            "title": "Bad Doc",
            "document_type": "unknown",
            "published_at": "2026-06-29T10:00:00Z",
            "business_tags": [],
            "permission_tags": [],
            "text": "",
        },
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 400
    assert body["trace_id"] == "trc_index_invalid"
    assert body["code"] == "REQ_INVALID_ARGUMENT"
    assert "document_type is not supported." in body["data"]["errors"]
    assert "text length must be between 1 and 500000 characters." in body["data"]["errors"]


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


def test_sql_preview_endpoint_returns_non_executing_preview() -> None:
    client: Any = TestClient(create_app())

    response = client.post(
        "/api/v1/sql/preview",
        headers=auth_headers("trc_sql_preview"),
        json={
            "user_id": "u_001",
            "question": "show monthly revenue for 2024",
            "locale": "en",
            "role": "business_user",
        },
    )

    body: dict[str, Any] = response.json()
    preview = body["data"]

    assert response.status_code == 200
    assert body["code"] == 0
    assert body["trace_id"] == "trc_sql_preview"
    assert preview["executes"] is False
    assert preview["semantic_version_id"] == "sem_v1"
    assert len(preview["sql_hash"]) == 64
    assert preview["guardrail_decision"]["decision"] == "allow"
    assert preview["guardrail_decision"]["rewritten_sql"] == preview["sql_text"]
    assert preview["guardrail_decision"]["sql_hash"] == preview["sql_hash"]
    assert preview["guardrail_decision"]["error"] is None
    assert "DATE_TRUNC('month', orders.order_date)::DATE AS order_month" in preview["sql_text"]
    assert "orders.order_date >= DATE '2024-01-01'" in preview["sql_text"]
    assert "orders.order_date <= DATE '2024-12-31'" in preview["sql_text"]


def test_sql_preview_endpoint_writes_v2_guardrail_audit_record() -> None:
    audit_log = InMemoryGuardrailAuditLogV2()
    client: Any = TestClient(create_app(guardrail_audit_log_v2=audit_log))

    response = client.post(
        "/api/v1/sql/preview",
        headers=auth_headers("trc_sql_preview_audit"),
        json={
            "user_id": "u_001",
            "question": "show monthly revenue for 2024",
            "locale": "en",
            "role": "business_user",
        },
    )

    body: dict[str, Any] = response.json()
    record = audit_log.get_v2("trc_sql_preview_audit")

    assert response.status_code == 200
    assert record is not None
    assert record.trace_id == "trc_sql_preview_audit"
    assert record.user_id == "u_001"
    assert record.role == "business_user"
    assert record.sql_hash == body["data"]["sql_hash"]
    assert record.decision is GuardrailDecisionStatus.ALLOW
    assert record.rule_hits == ()
    assert record.latency_ms >= 0


def test_sql_preview_endpoint_denies_high_sensitivity_field_without_sql() -> None:
    client: Any = TestClient(create_app())

    response = client.post(
        "/api/v1/sql/preview",
        headers=auth_headers("trc_sql_preview_denied"),
        json={
            "user_id": "u_001",
            "question": "Show customer id trend.",
            "locale": "en",
            "role": "business_user",
        },
    )

    body: dict[str, Any] = response.json()

    assert response.status_code == 403
    assert body["code"] == ApiErrorCode.AUTH_FORBIDDEN
    assert body["trace_id"] == "trc_sql_preview_denied"
    assert body["data"]["sql_preview"] is None
    assert body["data"]["semantic_resolution"]["status"] == "permission_denied"
    assert body["message"].startswith("Field user_id is high-sensitivity")


def test_sql_guardrail_check_endpoint_returns_masking_plan_for_p1_field() -> None:
    audit_log = InMemoryGuardrailAuditLogV2()
    client: Any = TestClient(create_app(guardrail_audit_log_v2=audit_log))

    response = client.post(
        "/api/v1/sql/guardrail/check",
        headers=auth_headers("trc_guardrail_masking"),
        json={
            "user_id": "u_001",
            "role": "analyst",
            "sql_text": "SELECT customers.user_email FROM customers LIMIT 25",
            "semantic_version_id": "sem_v1",
        },
    )

    body: dict[str, Any] = response.json()
    decision = body["data"]
    record = audit_log.get_v2("trc_guardrail_masking")

    assert response.status_code == 200
    assert body["code"] == 0
    assert body["trace_id"] == "trc_guardrail_masking"
    assert decision["decision"] == "allow"
    assert decision["rewritten_sql"] == "SELECT customers.user_email FROM customers LIMIT 25"
    assert decision["masking_plan"] == [
        {
            "field_name": "customers.user_email",
            "strategy": "partial",
            "reason": "P1 field requires masking before results leave governance.",
        }
    ]
    assert decision["rule_hits"][0]["rule_code"] == "MASKING_REQUIRED"
    assert decision["rule_hits"][0]["object_name"] == "customers.user_email"
    assert record is not None
    assert record.sql_hash == decision["sql_hash"]
    assert record.decision is GuardrailDecisionStatus.ALLOW


def test_sql_guardrail_check_endpoint_denies_write_statement() -> None:
    audit_log = InMemoryGuardrailAuditLogV2()
    client: Any = TestClient(create_app(guardrail_audit_log_v2=audit_log))

    response = client.post(
        "/api/v1/sql/guardrail/check",
        headers=auth_headers("trc_guardrail_drop"),
        json={
            "user_id": "u_001",
            "role": "business_user",
            "sql_text": "DROP TABLE orders",
            "semantic_version_id": "sem_v1",
        },
    )

    body: dict[str, Any] = response.json()
    decision = body["data"]
    record = audit_log.get_v2("trc_guardrail_drop")

    assert response.status_code == 200
    assert body["code"] == 0
    assert body["trace_id"] == "trc_guardrail_drop"
    assert decision["decision"] == "deny"
    assert decision["rewritten_sql"] is None
    assert decision["error"]["code"] == "SQL_DENIED_WRITE_OPERATION"
    assert decision["rule_hits"][0]["rule_code"] == "WRITE_OPERATION"
    assert record is not None
    assert record.sql_hash == decision["sql_hash"]
    assert record.decision is GuardrailDecisionStatus.DENY


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
    revenue = next(metric for metric in body["data"]["metrics"] if metric["name"] == "revenue")
    assert revenue["id"] == "revenue"
    assert revenue["formula"] == "SUM(orders.order_amount) WHERE status='paid'"
    assert revenue["owner"] == "analytics"
    assert revenue["status"] == "active"
    assert revenue["semantic_version_id"] == "sem_v1"


def test_internal_api_error_returns_sanitized_envelope() -> None:
    client: Any = TestClient(
        create_app(ExplodingApplication()),
        raise_server_exceptions=False,
    )

    response = client.get(
        "/api/v1/metrics/catalog",
        headers=auth_headers("trc_internal_error"),
        params={"user_id": "u_001"},
    )

    body: dict[str, Any] = response.json()
    serialized_body = str(body)

    assert response.status_code == 500
    assert body["trace_id"] == "trc_internal_error"
    assert body["code"] == "INTERNAL_ERROR"
    assert body["message"] == "The API could not complete the request."
    assert body["data"] is None
    assert "super-secret" not in serialized_body
    assert "password" not in serialized_body
    assert "SecretToken" not in serialized_body
    assert "traceback" not in serialized_body.lower()


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
