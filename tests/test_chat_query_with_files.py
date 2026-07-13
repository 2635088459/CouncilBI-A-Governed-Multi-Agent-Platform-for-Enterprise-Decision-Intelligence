"""TC-FV10-058 to TC-FV10-061: POST /api/v2/chat/query with file_ids attached.

This covers the FileDataAgent-only branch of the ResultMerger strategy (see
src/chatbi/orchestration/result_merger.py): a query that only references
uploaded files, or names no resolvable business table, answers from file
data alone. FederatedQueryAgent for explicit comparison intent
(TC-FV10-064 to 067) is covered separately in
tests/test_chat_query_federated.py, alongside its degrade path.

Spec FV10.6 (TC-FV10-173/174/176) added evidence tagged "📎 " for
uploaded-file content — see the `*_unstructured*`/`*_mixed*` tests below.
Live audit-log verification (TC-FV10-063, which needs a real Postgres
connection since ``active_query_audit_log`` is only wired when
``database_url`` is configured) is still not covered here — see
tests/test_query_audit_file_ids.py for the audit serialization itself.
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
from chatbi.core.contracts import EvidenceItem, RetrievalStats
from chatbi.files import (
    InMemoryFileRepository,
    InMemoryFileVectorSink,
    InMemoryObjectStorageAdapter,
    ParquetWriter,
    SchemaSerializer,
    StructuredFileParser,
    UserUploadedFile,
    parquet_storage_key,
)
from chatbi.files.parser_unstructured import TextChunk
from chatbi.knowledge import RetrievalQuery, RetrievalResult
from chatbi.llm.types import LLMRequest, LLMResponse
from chatbi.orchestration.simple_orchestrator import SimpleOrchestrator


def _admin_auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


@dataclass(slots=True)
class _FixedSqlLLMClient:
    sql_text: str

    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            text=self.sql_text,
            model_name="mock-model",
            provider="mock",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            estimated_cost=0.0,
            latency_ms=1,
            finish_reason="stop",
        )


def _empty_llm_requests() -> list[LLMRequest]:
    return []


@dataclass(slots=True)
class _RecordingSqlLLMClient:
    """Spec FV10.10: records every request it receives, so a test can
    inspect the schema-context string an agent actually sent to the LLM
    (not just the SQL it got back), and can count calls by task_type to
    prove an agent was never invoked at all."""

    sql_text: str
    requests_seen: list[LLMRequest] = field(default_factory=_empty_llm_requests)

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests_seen.append(request)
        return LLMResponse(
            text=self.sql_text,
            model_name="mock-model",
            provider="mock",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            estimated_cost=0.0,
            latency_ms=1,
            finish_reason="stop",
        )


@dataclass(slots=True)
class _FormatAwareSqlLLMClient:
    """Spec FV10.11 TC-FV10-195: a fixed-output fake would pass whether or
    not FR-FV10-081's schema-context change actually reached the model —
    it proves the SQL-generation call happened, nothing about what it was
    given. This fake instead inspects its own received prompt: it only
    returns the literal-correct SQL when the schema-context string reveals
    an ISO-date-shaped sample for the column in question (via either
    sample_values or sample_range), and returns a plausible-but-wrong
    natural-language literal otherwise — the same kind of guess the real
    OpenAI-backed reproduction of this defect produced against the
    unpatched prompt."""

    correct_sql: str
    incorrect_sql: str
    requests_seen: list[LLMRequest] = field(default_factory=_empty_llm_requests)

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests_seen.append(request)
        schema_context = request.messages[0]["content"]
        format_revealed = bool(re.search(r"\d{4}-\d{2}", schema_context))
        text = self.correct_sql if format_revealed else self.incorrect_sql
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


def _build_client(
    repository: InMemoryFileRepository,
    storage: InMemoryObjectStorageAdapter,
    sql_text: str,
    file_vector_sink: InMemoryFileVectorSink | None = None,
) -> Any:
    return TestClient(
        create_app(
            file_repository=repository,
            object_storage_adapter=storage,
            file_query_llm_client=_FixedSqlLLMClient(sql_text),
            file_vector_sink=file_vector_sink or InMemoryFileVectorSink(),
        )
    )


def _ready_csv_file(**overrides: object) -> UserUploadedFile:
    fields: dict[str, object] = dict(
        file_id="ufile_forecast0000000000000001",
        org_id="org_test",
        user_id="u_001",
        original_name="forecast.csv",
        file_type="structured",
        mime_type="text/csv",
        size_bytes=64,
        storage_key="org_test/u_001/ufile_forecast0000000000000001/forecast.csv",
        content_hash="hash_forecast",
        status="ready",
        scope="user",
        file_group_id="fgrp_forecast",
        version_number=1,
        is_latest=True,
        created_at=datetime.now(timezone.utc),
        schema_json={"columns": [{"name": "month", "type": "VARCHAR"}, {"name": "revenue", "type": "DOUBLE"}]},
        row_count=2,
    )
    fields.update(overrides)
    return UserUploadedFile(**fields)  # type: ignore[arg-type]


def _write_parquet_snapshot(storage: InMemoryObjectStorageAdapter, file: UserUploadedFile) -> None:
    table = StructuredFileParser().parse_csv(b"month,revenue\n2026-01,150.0\n2026-02,250.0\n")
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as temp_file:
        temp_path = Path(temp_file.name)
    ParquetWriter().write(table, temp_path)
    storage.put_object(parquet_storage_key(file.storage_key), temp_path.read_bytes())
    temp_path.unlink()


def _query_body(question: str, file_ids: list[str]) -> dict[str, object]:
    return {
        "request_id": "req_12345678",
        "session_id": "ses_12345678",
        "user_id": "u_001",
        "role": "analyst",
        "locale": "en",
        "question": question,
        "file_ids": file_ids,
    }


def test_chat_query_with_valid_file_ids_returns_file_sourced_table_result() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _ready_csv_file()
    repository.save(file)
    _write_parquet_snapshot(storage, file)
    client = _build_client(repository, storage, 'SELECT * FROM "file_ufile_forecast0000000000000001"')

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What is my forecast revenue?", [file.file_id]),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["table_result_source"] == "file"
    assert data["table_result"]["columns"] == ["month", "revenue"]
    assert len(data["table_result"]["rows"]) == 2


def _ready_unstructured_file(**overrides: object) -> UserUploadedFile:
    fields: dict[str, object] = dict(
        file_id="ufile_onepager000000000000001",
        original_name="onepager.pdf",
        file_type="unstructured",
        mime_type="application/pdf",
        storage_key="org_test/u_001/ufile_onepager000000000000001/onepager.pdf",
        content_hash="hash_onepager",
        schema_json=None,
        row_count=None,
        chunk_count=1,
    )
    fields.update(overrides)
    return _ready_csv_file(**fields)


def test_chat_query_with_only_an_unstructured_file_and_no_content_returns_400_not_a_crash() -> None:
    # Regression: selecting a PDF/DOCX/TXT/MD/PPTX file and asking a
    # business question used to crash with an unhandled 500
    # (`assert file.schema_json is not None` inside FileDataAgent) instead
    # of a clear, actionable error. This file has no chunks registered in
    # its vector source at all (Spec FV10.5 §7's durability gap), so Spec
    # FV10.6 FR-FV10-070 applies: FILE_CONTENT_UNAVAILABLE, not the older,
    # less precise "not spreadsheets" message.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _ready_unstructured_file()
    repository.save(file)
    client = _build_client(repository, storage, "SELECT 1")

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("Which product has the worst average resolution time?", [file.file_id]),
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "REQ_INVALID_ARGUMENT"
    assert "not available for search" in body["error"]["message"]


def test_chat_query_with_only_an_unstructured_file_with_irrelevant_content_returns_400() -> None:
    # FR-FV10-066/070: the file has content, but none of it is relevant to
    # the question — this is "searched and found nothing", not "content
    # unavailable", so the reason differs from the test above.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _ready_unstructured_file()
    repository.save(file)
    vector_sink = InMemoryFileVectorSink()
    vector_sink.upsert_chunks(
        (TextChunk(text="zzyzx qqjjkk unrelated gibberish", chunk_index=1, file_id=file.file_id),),
        ((1.0, 0.0),),
    )
    client = _build_client(repository, storage, "SELECT 1", file_vector_sink=vector_sink)

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("Which product has the worst average resolution time?", [file.file_id]),
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "REQ_INVALID_ARGUMENT"
    assert "none of the selected files" in body["error"]["message"].lower()


def test_chat_query_with_only_an_unstructured_file_with_relevant_content_answers_from_evidence() -> None:
    # AC-FV10-062: this used to fail outright under Spec FV10.5 alone
    # (NO_STRUCTURED_FILE_SELECTED) regardless of whether the file's own
    # content could actually answer the question. It now can.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _ready_unstructured_file(original_name="pricing.pdf")
    repository.save(file)
    vector_sink = InMemoryFileVectorSink()
    vector_sink.upsert_chunks(
        (TextChunk(text="The Team tier is priced at $49 per seat per month.", chunk_index=1, file_id=file.file_id),),
        ((1.0, 0.0),),
    )
    client = _build_client(repository, storage, "SELECT 1", file_vector_sink=vector_sink)

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What is the Team tier price?", [file.file_id]),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["table_result_source"] is None
    assert data["table_result"]["rows"] == []
    assert len(data["evidence_list"]) == 1
    assert data["evidence_list"][0]["source_id"] == file.file_id
    assert data["evidence_list"][0]["title"] == "📎 pricing.pdf"


def test_chat_query_with_a_mixed_structured_and_unstructured_selection_answers_from_both() -> None:
    # AC-FV10-061/TC-FV10-173: table_result from the structured file,
    # evidence_list from the unstructured file, both present in one
    # synthesized answer. Also TC-FV10-177 (AC-FV10-063/FR-FV10-068): the
    # unstructured file's evidence title is 📎-prefixed, the structured
    # file's table isn't evidence at all so there's nothing to mislabel.
    # Also TC-FV10-187/AC-FV10-078/NFR-FV10-027 (Spec FV10.10): re-run
    # unchanged after 10.10's per-file structured_ids filter, proving a
    # selection where every structured file is already relevant is
    # byte-identical to before that filter existed.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    structured_file = _ready_csv_file()
    unstructured_file = _ready_unstructured_file(original_name="pricing.pdf")
    repository.save(structured_file)
    repository.save(unstructured_file)
    _write_parquet_snapshot(storage, structured_file)
    vector_sink = InMemoryFileVectorSink()
    vector_sink.upsert_chunks(
        (TextChunk(text="Forecast methodology uses a 3-month rolling average.", chunk_index=1, file_id=unstructured_file.file_id),),
        ((1.0, 0.0),),
    )
    client = _build_client(
        repository, storage, 'SELECT * FROM "file_ufile_forecast0000000000000001"', file_vector_sink=vector_sink
    )

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body(
            "What is my forecast revenue, and what methodology was used?",
            [structured_file.file_id, unstructured_file.file_id],
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["table_result_source"] == "file"
    assert len(data["table_result"]["rows"]) == 2
    assert len(data["evidence_list"]) == 1
    assert data["evidence_list"][0]["source_id"] == unstructured_file.file_id
    assert data["evidence_list"][0]["title"] == "📎 pricing.pdf"


def _ready_irrelevant_csv_file(**overrides: object) -> UserUploadedFile:
    # A structured file whose schema shares no vocabulary with any question
    # used in this module's other fixtures — used to prove Spec FV10.10's
    # per-file filter excludes it from a mixed selection rather than
    # forcing FileDataAgent to query it anyway.
    fields: dict[str, object] = dict(
        file_id="ufile_roster0000000000000001",
        original_name="employee_roster.csv",
        storage_key="org_test/u_001/ufile_roster0000000000000001/employee_roster.csv",
        content_hash="hash_roster",
        file_group_id="fgrp_roster",
        schema_json={
            "columns": [
                {"name": "employee_id", "type": "VARCHAR"},
                {"name": "department", "type": "VARCHAR"},
            ]
        },
    )
    fields.update(overrides)
    return _ready_csv_file(**fields)


def test_mixed_selection_with_an_irrelevant_structured_file_excludes_it_from_sql_generation() -> None:
    # TC-FV10-184 / AC-FV10-075 (Spec FV10.10): a relevant structured file,
    # an irrelevant structured file, and a relevant unstructured file are
    # all attached. The irrelevant file's schema must never reach the SQL-
    # generation prompt, and the table_result must reflect only the
    # relevant file — no Parquet snapshot is written for the irrelevant
    # file at all, so if it were queried anyway this test would fail with
    # a storage lookup error, not just a wrong assertion.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    relevant_file = _ready_csv_file()
    irrelevant_file = _ready_irrelevant_csv_file()
    unstructured_file = _ready_unstructured_file(original_name="pricing.pdf")
    repository.save(relevant_file)
    repository.save(irrelevant_file)
    repository.save(unstructured_file)
    _write_parquet_snapshot(storage, relevant_file)
    vector_sink = InMemoryFileVectorSink()
    vector_sink.upsert_chunks(
        (TextChunk(text="Forecast methodology uses a 3-month rolling average.", chunk_index=1, file_id=unstructured_file.file_id),),
        ((1.0, 0.0),),
    )
    llm_client = _RecordingSqlLLMClient('SELECT * FROM "file_ufile_forecast0000000000000001"')
    client = TestClient(
        create_app(
            file_repository=repository,
            object_storage_adapter=storage,
            file_query_llm_client=llm_client,
            file_vector_sink=vector_sink,
        )
    )

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body(
            "What is my forecast revenue, and what methodology was used?",
            [relevant_file.file_id, irrelevant_file.file_id, unstructured_file.file_id],
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["table_result_source"] == "file"
    assert len(data["table_result"]["rows"]) == 2
    assert len(data["evidence_list"]) == 1

    sql_generation_calls = [r for r in llm_client.requests_seen if r.task_type == "file_data_sql_generation"]
    assert len(sql_generation_calls) == 1
    schema_context = sql_generation_calls[0].messages[0]["content"]
    assert relevant_file.file_id in schema_context
    assert irrelevant_file.file_id not in schema_context


def test_mixed_selection_with_only_irrelevant_structured_files_skips_sql_generation_entirely() -> None:
    # TC-FV10-185 / AC-FV10-076 / FR-FV10-079 (Spec FV10.10): the only
    # structured file is irrelevant; the only unstructured file is
    # relevant. No file_data_sql_generation or federated_query_sql_generation
    # call should happen at all, and the answer must come from evidence
    # alone — proving the filter, not just an empty result, is what kept
    # FileDataAgent from running.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    irrelevant_file = _ready_irrelevant_csv_file()
    unstructured_file = _ready_unstructured_file(original_name="pricing.pdf")
    repository.save(irrelevant_file)
    repository.save(unstructured_file)
    vector_sink = InMemoryFileVectorSink()
    vector_sink.upsert_chunks(
        (TextChunk(text="The Team tier is priced at $49 per seat per month.", chunk_index=1, file_id=unstructured_file.file_id),),
        ((1.0, 0.0),),
    )
    llm_client = _RecordingSqlLLMClient("SELECT 1")
    client = TestClient(
        create_app(
            file_repository=repository,
            object_storage_adapter=storage,
            file_query_llm_client=llm_client,
            file_vector_sink=vector_sink,
        )
    )

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What is the Team tier price?", [irrelevant_file.file_id, unstructured_file.file_id]),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["table_result_source"] is None
    assert data["table_result"]["rows"] == []
    assert len(data["evidence_list"]) == 1
    sql_calls = [
        r
        for r in llm_client.requests_seen
        if r.task_type in ("file_data_sql_generation", "federated_query_sql_generation")
    ]
    assert sql_calls == []


def test_mixed_selection_with_nothing_relevant_returns_the_pre_existing_unanswerable_error() -> None:
    # TC-FV10-186 / AC-FV10-077 (Spec FV10.10): both an irrelevant
    # structured file and an unstructured file with irrelevant content are
    # attached. The pre-existing FR-FV10-066 "none of the selected files"
    # error must fire unchanged — the same case, and the same assertion,
    # as test_chat_query_with_only_an_unstructured_file_with_irrelevant_content_returns_400,
    # with an irrelevant structured file also present to prove it doesn't
    # change the outcome.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    irrelevant_structured = _ready_irrelevant_csv_file()
    irrelevant_unstructured = _ready_unstructured_file(original_name="onepager.pdf")
    repository.save(irrelevant_structured)
    repository.save(irrelevant_unstructured)
    vector_sink = InMemoryFileVectorSink()
    vector_sink.upsert_chunks(
        (TextChunk(text="zzyzx qqjjkk unrelated gibberish", chunk_index=1, file_id=irrelevant_unstructured.file_id),),
        ((1.0, 0.0),),
    )
    client = _build_client(repository, storage, "SELECT 1", file_vector_sink=vector_sink)

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body(
            "Which product has the worst average resolution time?",
            [irrelevant_structured.file_id, irrelevant_unstructured.file_id],
        ),
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "REQ_INVALID_ARGUMENT"
    assert "none of the selected files" in body["error"]["message"].lower()


def test_a_structured_file_filtered_out_of_one_turn_remains_available_to_a_later_relevant_turn() -> None:
    # TC-FV10-188 / AC-FV10-079 / NFR-FV10-027 (Spec FV10.10): turn 1's
    # question is irrelevant to the attached structured file (filtered out
    # of turn 1's structured_ids), but relevant to the attached
    # unstructured file. Turn 2 sends no file_ids (inherits the session's
    # stored selection) and asks a question relevant to that same
    # structured file — it must still find the file attached and query it,
    # proving turn 1's per-turn filtering never touched session state.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    structured_file = _ready_csv_file()
    unstructured_file = _ready_unstructured_file(original_name="pricing.pdf")
    repository.save(structured_file)
    repository.save(unstructured_file)
    _write_parquet_snapshot(storage, structured_file)
    vector_sink = InMemoryFileVectorSink()
    vector_sink.upsert_chunks(
        (TextChunk(text="The Team tier is priced at $49 per seat per month.", chunk_index=1, file_id=unstructured_file.file_id),),
        ((1.0, 0.0),),
    )
    llm_client = _RecordingSqlLLMClient('SELECT * FROM "file_ufile_forecast0000000000000001"')
    client = TestClient(
        create_app(
            file_repository=repository,
            object_storage_adapter=storage,
            file_query_llm_client=llm_client,
            file_vector_sink=vector_sink,
        )
    )

    first = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What is the Team tier price?", [structured_file.file_id, unstructured_file.file_id]),
    )
    second = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What is my forecast revenue?", []),
    )

    assert first.status_code == 200
    assert first.json()["data"]["table_result_source"] is None
    assert second.status_code == 200
    assert second.json()["data"]["table_result_source"] == "file"
    assert len(second.json()["data"]["table_result"]["rows"]) == 2


def test_chat_query_with_an_all_structured_selection_is_unaffected_by_the_unstructured_split() -> None:
    # NFR-FV10-022/AC-FV10-064: byte-identical to Spec FV10.5-only behavior
    # for a request whose file_ids are entirely structured.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _ready_csv_file()
    repository.save(file)
    _write_parquet_snapshot(storage, file)
    client = _build_client(repository, storage, 'SELECT * FROM "file_ufile_forecast0000000000000001"')

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What is my forecast revenue?", [file.file_id]),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["table_result_source"] == "file"
    assert data["table_result"]["columns"] == ["month", "revenue"]
    assert len(data["table_result"]["rows"]) == 2
    assert data["evidence_list"] == []


def test_chat_query_with_another_users_file_id_returns_422_file_not_found() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    other_users_file = _ready_csv_file(
        file_id="ufile_notmine00000000000000001",
        user_id="someone_else",
        storage_key="org_test/someone_else/ufile_notmine00000000000000001/forecast.csv",
    )
    repository.save(other_users_file)
    client = _build_client(repository, storage, "SELECT 1")

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What is my forecast revenue?", [other_users_file.file_id]),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FILE_NOT_FOUND"


def test_chat_query_referencing_a_processing_file_returns_422_file_not_ready() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    processing_file = _ready_csv_file(status="processing", schema_json=None, row_count=None)
    repository.save(processing_file)
    client = _build_client(repository, storage, "SELECT 1")

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What is my forecast revenue?", [processing_file.file_id]),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FILE_NOT_READY"


def test_chat_query_with_write_intent_on_file_is_guardrail_blocked() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _ready_csv_file()
    repository.save(file)
    _write_parquet_snapshot(storage, file)
    client = _build_client(
        repository, storage, 'UPDATE "file_ufile_forecast0000000000000001" SET revenue = 0'
    )

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("Update the revenue column in my file.", [file.file_id]),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["guardrail_blocked"] is True
    assert data["table_result"] is None


def test_chat_query_with_a_structured_file_irrelevant_to_the_question_routes_to_main_orchestrator() -> None:
    # 10-followups/08: a file checked from an earlier turn (or a
    # quick-question button clicked while unrelated to it) must not force
    # FileDataAgent to invent an answer from the wrong columns. The SQL
    # text here would prove the file branch ran if it were reached, so a
    # None table_result_source demonstrates the main orchestrator answered
    # instead, exactly as if no file_ids had been sent at all.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _ready_csv_file()  # forecast.csv: month, revenue
    repository.save(file)
    _write_parquet_snapshot(storage, file)
    client = _build_client(repository, storage, 'SELECT * FROM "file_ufile_forecast0000000000000001"')

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("Compare total ticket count by product in H1 2026.", [file.file_id]),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["table_result_source"] is None


def test_chat_query_phrased_with_synonyms_the_schema_gate_misses_still_reaches_the_file_branch() -> None:
    # 10-followups/09: the token-overlap gate alone would misroute this —
    # "numbers"/"cycle" share no literal token with forecast.csv's own
    # month/revenue columns or filename. The safety net keeps it in the
    # file branch because the question also has no independent
    # business-data-keyword signal (QuestionClassifier.has_data_domain_signal)
    # that would corroborate routing it to the main orchestrator instead.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _ready_csv_file()  # forecast.csv: month, revenue
    repository.save(file)
    _write_parquet_snapshot(storage, file)
    client = _build_client(repository, storage, 'SELECT * FROM "file_ufile_forecast0000000000000001"')

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("Please describe my numbers for this cycle.", [file.file_id]),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["table_result_source"] == "file"


# 10-followups/12 (Spec FV10.12 §8.1/§8.3, TC-FV10-198/205): a hybrid file
# question phrased with an ordinary word like "internal" triggers an
# org-wide knowledge-base search regardless of the file's own relevance —
# whatever comes back must clear a relevance floor before being rendered as
# a "Source," or an unrelated document ends up cited for an answer that
# never used it.
@dataclass(slots=True)
class _FixedScoreKnowledgeStore:
    """Returns exactly the evidence items it was constructed with, at
    exactly the relevance_score each was given — isolates the http.py
    filtering logic (AC-FV10-089) from InMemoryKnowledgeStore's own scoring
    algorithm, which is covered separately in tests/test_knowledge_store.py.
    """

    evidence_list: tuple[EvidenceItem, ...]

    def set_shared_visibility_resolver(self, resolver: object) -> None:
        # create_app() always rewires this hook (Spec FV10.1/FV10.2) once a
        # real FileRepository exists — a no-op here, this fake has no
        # owner-scoped documents to gate.
        return None

    def retrieve(self, query: RetrievalQuery, trace_id: str = "") -> RetrievalResult:
        return RetrievalResult(
            evidence_list=self.evidence_list,
            explanation_text="stub",
            confidence=1.0,
            uncertainty=False,
            retrieval_stats=RetrievalStats(
                candidate_count=len(self.evidence_list),
                filtered_count=len(self.evidence_list),
                reranked_count=len(self.evidence_list),
                selected_count=len(self.evidence_list),
                latency_ms=0.0,
            ),
            trace_id=trace_id,
        )


def test_chat_query_hybrid_comparison_excludes_low_relevance_knowledge_base_sources() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _ready_csv_file()  # forecast.csv: month, revenue
    repository.save(file)
    _write_parquet_snapshot(storage, file)
    knowledge_store = _FixedScoreKnowledgeStore(
        evidence_list=(
            EvidenceItem(
                source_id="doc_relevant",
                title="Relevant Doc",
                citation_anchor="doc_relevant#p1",
                snippet="On-topic content.",
                relevance_score=0.9,
            ),
            EvidenceItem(
                source_id="doc_borderline",
                title="Borderline Doc",
                citation_anchor="doc_borderline#p1",
                snippet="Somewhat related content.",
                relevance_score=0.4,
            ),
            EvidenceItem(
                source_id="doc_unrelated",
                title="Unrelated Doc",
                citation_anchor="doc_unrelated#p1",
                snippet="Completely unrelated content.",
                relevance_score=0.1,
            ),
        )
    )
    application = ChatBIApplication(
        orchestrator=SimpleOrchestrator(knowledge_store=knowledge_store)  # type: ignore[arg-type]
    )
    client: Any = TestClient(
        create_app(
            application=application,
            file_repository=repository,
            object_storage_adapter=storage,
            file_query_llm_client=_FixedSqlLLMClient(
                'SELECT * FROM "file_ufile_forecast0000000000000001"'
            ),
        )
    )

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What is my internal revenue for this file?", [file.file_id]),
    )

    assert response.status_code == 200
    # AC-FV10-089: the 0.35 floor keeps 0.9 and 0.4, excludes only 0.1.
    evidence_source_ids = {item["source_id"] for item in response.json()["data"]["evidence_list"]}
    assert evidence_source_ids == {"doc_relevant", "doc_borderline"}


def test_chat_query_without_file_ids_is_unaffected() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    client = _build_client(repository, storage, "SELECT 1")

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What was total revenue last month?", []),
    )

    assert response.status_code == 200
    assert response.json()["data"]["guardrail_blocked"] is False


def test_a_month_literal_typed_into_the_current_question_uses_the_files_real_format() -> None:
    # TC-FV10-195 / AC-FV10-086 (Spec FV10.11): "What about just June?" is
    # typed directly into this turn, not carried over from an earlier one
    # (Spec FV10.7's fix does not apply here). The file's month column
    # stores '2026-01'..'2026-06', not English month names. Before this
    # spec, build_schema_context() gave the model only "month VARCHAR" —
    # no clue about the stored format — so a real LLM guessed
    # WHERE month = 'June' and matched zero rows. The fix is
    # SchemaSerializer computing a value sample at upload time and
    # build_schema_context() rendering it; this test proves that sample
    # actually reaches the SQL-generation prompt, not just that some SQL
    # came back.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    csv_bytes = (
        b"region,month,revenue\n"
        b"US-West,2026-01,420000\n"
        b"US-West,2026-02,455000\n"
        b"US-West,2026-03,478000\n"
        b"US-West,2026-04,502000\n"
        b"US-West,2026-05,533000\n"
        b"US-West,2026-06,481000\n"
    )
    table = StructuredFileParser().parse_csv(csv_bytes)
    file = _ready_csv_file(schema_json=SchemaSerializer().to_json(table))
    repository.save(file)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as temp_file:
        temp_path = Path(temp_file.name)
    ParquetWriter().write(table, temp_path)
    storage.put_object(parquet_storage_key(file.storage_key), temp_path.read_bytes())
    temp_path.unlink()

    llm_client = _FormatAwareSqlLLMClient(
        correct_sql=(
            f'SELECT region, SUM(revenue) AS total_revenue FROM "file_{file.file_id}" '
            "WHERE month = '2026-06' GROUP BY region"
        ),
        incorrect_sql=(
            f'SELECT region, SUM(revenue) AS total_revenue FROM "file_{file.file_id}" '
            "WHERE month = 'June' GROUP BY region"
        ),
    )
    client = TestClient(
        create_app(file_repository=repository, object_storage_adapter=storage, file_query_llm_client=llm_client)
    )

    first = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What is my revenue by region?", [file.file_id]),
    )
    second = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What about just June?", [file.file_id]),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    rows = second.json()["data"]["table_result"]["rows"]
    assert rows == [{"region": "US-West", "total_revenue": 481000}]
