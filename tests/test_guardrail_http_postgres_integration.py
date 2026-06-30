import os
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from chatbi.api.http import create_app
from chatbi.core.runtime_config import RuntimeConfig
from chatbi.governance import GuardrailDecisionStatus, postgres_guardrail_audit_log_v2_from_psycopg
from chatbi.history.request_metadata import InMemoryRequestMetadataStore, connect_psycopg


def test_sql_guardrail_check_endpoint_live_writes_postgres_audit_record() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for live guardrail HTTP integration.")

    trace_id = f"tr_http_guardrail_{uuid4().hex[:16]}"
    client: Any = TestClient(
        create_app(
            runtime_config=RuntimeConfig(
                database_url=database_url,
                redis_url=None,
                vector_store_url=None,
            ),
            request_metadata_store=InMemoryRequestMetadataStore(),
            use_postgres_metadata=True,
        )
    )

    response = client.post(
        "/api/v1/sql/guardrail/check",
        headers={"Authorization": "Bearer test-token", "X-Trace-Id": trace_id},
        json={
            "user_id": "u_live_http",
            "role": "business_user",
            "sql_text": "DROP TABLE orders",
            "semantic_version_id": "sem_v1",
        },
    )

    body = response.json()
    decision = body["data"]

    connection = connect_psycopg(database_url)
    audit_log = postgres_guardrail_audit_log_v2_from_psycopg(connection)
    record = audit_log.get_v2(trace_id)
    connection.close()

    assert response.status_code == 200
    assert body["trace_id"] == trace_id
    assert decision["decision"] == "deny"
    assert decision["error"]["code"] == "SQL_DENIED_WRITE_OPERATION"
    assert record is not None
    assert record.trace_id == trace_id
    assert record.user_id == "u_live_http"
    assert record.decision is GuardrailDecisionStatus.DENY
    assert record.sql_hash == decision["sql_hash"]
    assert record.rule_hits[0].rule_code.value == "WRITE_OPERATION"
