import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chatbi.api.http import create_app
from chatbi.core.runtime_config import RuntimeConfig
from chatbi.history.request_metadata import connect_psycopg
from chatbi.history.query_results import postgres_runtime_query_result_store_from_psycopg
from chatbi.migrations import BUSINESS_REVENUE_BY_MONTH_TABLE_SQL, READONLY_DATABASE_ROLE_SQL


def test_chat_query_live_uses_readonly_postgres_business_rows() -> None:
    database_url = os.environ.get("DATABASE_URL")
    readonly_database_url = os.environ.get("CHATBI_READONLY_DATABASE_URL")
    if not database_url or not readonly_database_url:
        pytest.skip(
            "DATABASE_URL and CHATBI_READONLY_DATABASE_URL are required for live "
            "chat query read-only PostgreSQL integration."
        )

    writer_connection = connect_psycopg(database_url)
    writer_connection.execute(BUSINESS_REVENUE_BY_MONTH_TABLE_SQL)
    writer_connection.execute(READONLY_DATABASE_ROLE_SQL)
    writer_connection.commit()
    writer_connection.close()

    client: Any = TestClient(
        create_app(
            runtime_config=RuntimeConfig(
                database_url=database_url,
                readonly_database_url=readonly_database_url,
                redis_url=None,
                vector_store_url=None,
            ),
            use_postgres_metadata=True,
        )
    )

    response = client.post(
        "/api/v1/chat/query",
        headers={"Authorization": "Bearer test-token", "X-Trace-Id": "trc_live_readonly_chat"},
        json={
            "user_id": "u_live_http",
            "session_id": "s_live_http",
            "question": "Show revenue trend.",
            "locale": "en",
            "role": "business_user",
        },
    )

    body = response.json()
    table_result = body["data"]["table_result"]

    assert response.status_code == 200
    assert body["code"] == 0
    assert body["trace_id"] == "trc_live_readonly_chat"
    assert body["data"]["sql_text"] == "SELECT month, revenue FROM revenue_by_month LIMIT 100"
    assert table_result["columns"] == ["month", "revenue"]
    assert table_result["rows"][0] == {"month": "2026-01", "revenue": 1000.0}
    assert table_result["rows"][-1] == {"month": "2026-06", "revenue": 1350.0}

    reader_connection = connect_psycopg(database_url)
    query_result_store = postgres_runtime_query_result_store_from_psycopg(reader_connection)
    saved_result = query_result_store.get("trc_live_readonly_chat")
    reader_connection.close()

    assert saved_result is not None
    assert saved_result.session_id == "s_live_http"
    assert saved_result.user_id == "u_live_http"
    assert saved_result.sql_hash is not None
    saved_rows = saved_result.table_result["rows"]
    assert isinstance(saved_rows, list)
    assert saved_rows[0] == {"month": "2026-01", "revenue": 1000.0}


def test_v2_query_result_endpoint_live_replays_postgres_runtime_result() -> None:
    database_url = os.environ.get("DATABASE_URL")
    readonly_database_url = os.environ.get("CHATBI_READONLY_DATABASE_URL")
    if not database_url or not readonly_database_url:
        pytest.skip(
            "DATABASE_URL and CHATBI_READONLY_DATABASE_URL are required for live "
            "query result replay integration."
        )

    writer_connection = connect_psycopg(database_url)
    writer_connection.execute(BUSINESS_REVENUE_BY_MONTH_TABLE_SQL)
    writer_connection.execute(READONLY_DATABASE_ROLE_SQL)
    writer_connection.commit()
    writer_connection.close()

    client: Any = TestClient(
        create_app(
            runtime_config=RuntimeConfig(
                database_url=database_url,
                readonly_database_url=readonly_database_url,
                redis_url=None,
                vector_store_url=None,
            ),
            use_postgres_metadata=True,
        )
    )

    query_response = client.post(
        "/api/v2/chat/query",
        headers={"Authorization": "Bearer test-token"},
        json={
            "request_id": "req_live_result_lookup",
            "user_id": "u_live_http",
            "session_id": "ses_live_result_lookup",
            "question": "Show revenue trend.",
            "locale": "en",
            "role": "business_user",
        },
    )
    query_trace_id = query_response.json()["trace_id"]

    replay_response = client.get(
        f"/api/v2/query-results/{query_trace_id}",
        headers={"Authorization": "Bearer test-token"},
    )

    body = replay_response.json()
    data = body["data"]

    assert replay_response.status_code == 200
    assert data["trace_id"] == query_trace_id
    assert len(data["sql_hash"]) == 64
    assert data["table_result"]["rows"][0] == {"month": "2026-01", "revenue": 1000.0}
    assert "sql_text" not in data
    assert "SELECT month, revenue" not in str(body)

    governance_response = client.get(
        f"/api/v2/governance/traces/{query_trace_id}",
        headers={"Authorization": "Bearer test-token"},
    )
    governance_body = governance_response.json()
    governance_data = governance_body["data"]

    assert governance_response.status_code == 200
    assert governance_data["trace_id"] == query_trace_id
    assert governance_data["request"]["exists"] is True
    assert governance_data["request"]["status"] == "succeeded"
    assert governance_data["query_result"]["exists"] is True
    assert governance_data["query_result"]["row_count"] == 6
    assert governance_data["guardrail"]["exists"] is False
    assert "sql_text" not in str(governance_data)
    assert "SELECT month, revenue" not in str(governance_data)
