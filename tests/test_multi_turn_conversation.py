"""Spec FV10.4: Multi-Turn Conversation Memory — HTTP integration tests.

TC-FV10-143/144/145 cover conversation-history context injection via the
main orchestrator path; TC-FV10-150/151 cover session-scoped file_ids
inheritance (FR-FV10-055); TC-FV10-152 proves no extra rewrite call is
inserted for a follow-up question (FR-FV10-056).
"""

import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from chatbi.api.http import create_app
from chatbi.application.app import ChatBIApplication
from chatbi.files import (
    InMemoryFileRepository,
    InMemoryObjectStorageAdapter,
    ParquetWriter,
    StructuredFileParser,
    UserUploadedFile,
    parquet_storage_key,
)
from chatbi.llm.types import LLMRequest, LLMResponse
from chatbi.orchestration.simple_orchestrator import SimpleOrchestrator


def _admin_auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _empty_requests() -> list[LLMRequest]:
    return []


@dataclass(slots=True)
class _RecordingLLMClient:
    response_sql: str = "SELECT month, revenue FROM revenue_by_month LIMIT 10"
    response_text: str = "Synthesized answer."
    requests_seen: list[LLMRequest] = field(default_factory=_empty_requests)

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests_seen.append(request)
        text = self.response_sql if request.task_type == "sql_generation" else self.response_text
        return LLMResponse(
            text=text,
            model_name="mock-model",
            provider="mock",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            estimated_cost=0.0,
            latency_ms=1,
            finish_reason="stop",
        )


def _query_body(
    question: str,
    *,
    session_id: str = "ses_12345678",
    file_ids: list[str] | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "request_id": "req_12345678",
        "session_id": session_id,
        "user_id": "u_001",
        "role": "analyst",
        "locale": "en",
        "question": question,
    }
    if file_ids is not None:
        body["file_ids"] = file_ids
    return body


def test_second_turn_pronoun_question_carries_first_turns_context() -> None:
    # TC-FV10-143 / AC-FV10-044
    llm_client = _RecordingLLMClient()
    application = ChatBIApplication(orchestrator=SimpleOrchestrator(llm_client=llm_client))
    client: Any = TestClient(create_app(application=application))

    first = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("Show me the orders trend.", session_id="ses_shared001"),
    )
    llm_client.requests_seen.clear()
    second = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What about last month?", session_id="ses_shared001"),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    sql_requests = [r for r in llm_client.requests_seen if r.task_type == "sql_generation"]
    assert len(sql_requests) == 1
    contents = [message["content"] for message in sql_requests[0].messages]
    assert "Show me the orders trend." in contents


def test_second_turn_in_a_different_session_gets_no_context() -> None:
    # TC-FV10-144 / AC-FV10-045
    llm_client = _RecordingLLMClient()
    application = ChatBIApplication(orchestrator=SimpleOrchestrator(llm_client=llm_client))
    client: Any = TestClient(create_app(application=application))

    client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("Show me the orders trend.", session_id="ses_session_a"),
    )
    client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("Show me the refunds trend.", session_id="ses_session_b"),
    )
    llm_client.requests_seen.clear()
    client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What about last month?", session_id="ses_session_b"),
    )

    sql_requests = [r for r in llm_client.requests_seen if r.task_type == "sql_generation"]
    assert len(sql_requests) == 1
    contents = [message["content"] for message in sql_requests[0].messages]
    assert "Show me the refunds trend." in contents
    assert "Show me the orders trend." not in contents


def test_context_window_only_injects_the_configured_number_of_turns() -> None:
    # TC-FV10-145 / AC-FV10-046 / NFR-FV10-019
    llm_client = _RecordingLLMClient()
    application = ChatBIApplication(
        orchestrator=SimpleOrchestrator(llm_client=llm_client, conversation_context_turns=2)
    )
    client: Any = TestClient(create_app(application=application))

    for turn in range(1, 4):
        client.post(
            "/api/v2/chat/query",
            headers=_admin_auth_headers(),
            json=_query_body(f"Show me the orders trend, turn {turn}.", session_id="ses_windowed01"),
        )
    llm_client.requests_seen.clear()
    client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("Show me the orders trend, turn 4.", session_id="ses_windowed01"),
    )

    sql_requests = [r for r in llm_client.requests_seen if r.task_type == "sql_generation"]
    contents = [message["content"] for message in sql_requests[0].messages]
    assert "Show me the orders trend, turn 1." not in contents
    assert "Show me the orders trend, turn 2." in contents
    assert "Show me the orders trend, turn 3." in contents


def test_a_first_ever_question_with_empty_file_ids_uses_the_main_orchestrator() -> None:
    # AC-FV10-050: nothing to inherit yet, so this must not route through
    # the file-data branch at all.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    client: Any = TestClient(
        create_app(file_repository=repository, object_storage_adapter=storage)
    )

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("Show revenue trend.", session_id="ses_brand_new01", file_ids=[]),
    )

    assert response.status_code == 200
    assert response.json()["data"]["table_result_source"] is None


@dataclass(slots=True)
class _EchoFileTableLLMClient:
    """Returns SQL against whichever file_* table the schema context names,
    so the same double works regardless of which file is attached.
    """

    def complete(self, request: LLMRequest) -> LLMResponse:
        system_prompt = request.messages[0]["content"]
        match = re.search(r"(file_ufile_\w+)\(", system_prompt)
        table_name = match.group(1) if match else "file_unknown"
        return LLMResponse(
            text=f'SELECT * FROM "{table_name}"',
            model_name="mock-model",
            provider="mock",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            estimated_cost=0.0,
            latency_ms=1,
            finish_reason="stop",
        )


def _ready_csv_file(**overrides: object) -> UserUploadedFile:
    fields: dict[str, object] = dict(
        file_id="ufile_x0000000000000000000000001",
        org_id="org_test",
        user_id="u_001",
        original_name="x.csv",
        file_type="structured",
        mime_type="text/csv",
        size_bytes=64,
        storage_key="org_test/u_001/ufile_x0000000000000000000000001/x.csv",
        content_hash="hash_x",
        status="ready",
        scope="user",
        file_group_id="fgrp_x",
        version_number=1,
        is_latest=True,
        created_at=datetime.now(timezone.utc),
        schema_json={"columns": [{"name": "month", "type": "VARCHAR"}, {"name": "revenue", "type": "DOUBLE"}]},
        row_count=1,
    )
    fields.update(overrides)
    return UserUploadedFile(**fields)  # type: ignore[arg-type]


def _write_parquet_snapshot(storage: InMemoryObjectStorageAdapter, file: UserUploadedFile, csv_bytes: bytes) -> None:
    table = StructuredFileParser().parse_csv(csv_bytes)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as temp_file:
        temp_path = Path(temp_file.name)
    ParquetWriter().write(table, temp_path)
    storage.put_object(parquet_storage_key(file.storage_key), temp_path.read_bytes())
    temp_path.unlink()


def test_second_turn_with_empty_file_ids_inherits_the_first_turns_file() -> None:
    # TC-FV10-150 / AC-FV10-048
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file_x = _ready_csv_file()
    repository.save(file_x)
    _write_parquet_snapshot(storage, file_x, b"month,revenue\n2026-01,111.0\n")
    client: Any = TestClient(
        create_app(
            file_repository=repository,
            object_storage_adapter=storage,
            file_query_llm_client=_EchoFileTableLLMClient(),
        )
    )

    first = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What is my revenue?", session_id="ses_sticky0001", file_ids=[file_x.file_id]),
    )
    second = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What about last month?", session_id="ses_sticky0001", file_ids=[]),
    )

    assert first.status_code == 200
    assert first.json()["data"]["table_result_source"] == "file"
    assert second.status_code == 200
    assert second.json()["data"]["table_result_source"] == "file"
    assert second.json()["data"]["table_result"]["rows"] == [{"month": "2026-01", "revenue": 111.0}]


def test_third_turn_inherits_the_second_turns_explicit_file_not_the_first() -> None:
    # TC-FV10-151 / AC-FV10-049
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file_x = _ready_csv_file()
    file_y = _ready_csv_file(
        file_id="ufile_y0000000000000000000000001",
        original_name="y.csv",
        storage_key="org_test/u_001/ufile_y0000000000000000000000001/y.csv",
        content_hash="hash_y",
        file_group_id="fgrp_y",
    )
    repository.save(file_x)
    repository.save(file_y)
    _write_parquet_snapshot(storage, file_x, b"month,revenue\n2026-01,111.0\n")
    _write_parquet_snapshot(storage, file_y, b"month,revenue\n2026-02,222.0\n")
    client: Any = TestClient(
        create_app(
            file_repository=repository,
            object_storage_adapter=storage,
            file_query_llm_client=_EchoFileTableLLMClient(),
        )
    )

    client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What is my revenue?", session_id="ses_switch0001", file_ids=[file_x.file_id]),
    )
    second = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What about this one?", session_id="ses_switch0001", file_ids=[file_y.file_id]),
    )
    third = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("And last month?", session_id="ses_switch0001", file_ids=[]),
    )

    assert second.json()["data"]["table_result"]["rows"] == [{"month": "2026-02", "revenue": 222.0}]
    assert third.json()["data"]["table_result"]["rows"] == [{"month": "2026-02", "revenue": 222.0}]


def test_followup_question_makes_the_same_number_of_llm_calls_as_a_first_turn_question() -> None:
    # TC-FV10-152 / AC-FV10-051 / FR-FV10-056: no separate rewrite call.
    first_turn_client = _RecordingLLMClient()
    application_a = ChatBIApplication(orchestrator=SimpleOrchestrator(llm_client=first_turn_client))
    client_a: Any = TestClient(create_app(application=application_a))
    client_a.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("Show me the orders trend.", session_id="ses_baseline01"),
    )
    first_turn_call_count = len(first_turn_client.requests_seen)

    followup_client = _RecordingLLMClient()
    application_b = ChatBIApplication(orchestrator=SimpleOrchestrator(llm_client=followup_client))
    client_b: Any = TestClient(create_app(application=application_b))
    client_b.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("Show me the orders trend.", session_id="ses_followup01"),
    )
    followup_client.requests_seen.clear()
    client_b.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What about last month?", session_id="ses_followup01"),
    )
    followup_turn_call_count = len(followup_client.requests_seen)

    assert followup_turn_call_count == first_turn_call_count
    assert {r.task_type for r in followup_client.requests_seen} == {
        r.task_type for r in first_turn_client.requests_seen
    }
