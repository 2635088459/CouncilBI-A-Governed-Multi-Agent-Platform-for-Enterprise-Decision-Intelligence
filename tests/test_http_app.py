from typing import Any

from fastapi.testclient import TestClient

from chatbi.api.http import create_app
from chatbi.core.contracts import ErrorCode


def test_chat_query_endpoint_returns_success_envelope() -> None:
    client: Any = TestClient(create_app())

    response = client.post(
        "/api/v1/chat/query",
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
    assert body["warnings"][0]["code"] == ErrorCode.SQL_DENY_STATEMENT
    assert body["data"]["answer_text"].startswith("Request was blocked")
