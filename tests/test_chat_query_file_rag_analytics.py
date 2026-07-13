"""POST /api/v2/chat/query with file_ids: RAG evidence and Analytics results
layered onto a file/federated table result.

The file_ids branch used to be FileDataAgent/FederatedQueryAgent only —
RAG_agent and Analytics_agent never ran (they only exist inside the main
SimpleOrchestrator pipeline, which file_ids bypasses entirely). These tests
cover the two additions: knowledge-base RAG evidence layered onto a file
answer when the question also reads as a why/explain question, and an
AnalyticsService forecast/anomaly result computed directly from the file's
own table when the question also reads as a forecast/anomaly question.
"""

import tempfile
from dataclasses import dataclass
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
from chatbi.knowledge import InMemoryKnowledgeStore, KnowledgeDocument
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
        row_count=4,
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


def test_file_query_layers_in_knowledge_base_rag_evidence_for_a_why_question() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _ready_csv_file()
    repository.save(file)
    _write_parquet_snapshot(
        storage, file, b"month,revenue\n2026-01,150.0\n2026-02,250.0\n2026-03,890.0\n2026-04,910.0\n"
    )

    knowledge_store = InMemoryKnowledgeStore()
    knowledge_store.ingest_document(
        KnowledgeDocument(
            source_id="doc_policy",
            title="Revenue Policy",
            doc_type="policy",
            publish_time=datetime.now(timezone.utc),
        ),
        "Revenue dropped in March because a marketing campaign was paused for three weeks.",
    )
    application = ChatBIApplication(orchestrator=SimpleOrchestrator(knowledge_store=knowledge_store))

    client = TestClient(
        create_app(
            application=application,
            file_repository=repository,
            object_storage_adapter=storage,
            file_query_llm_client=_FixedSqlLLMClient('SELECT * FROM "file_ufile_forecast0000000000000001"'),
        )
    )

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("Why did my revenue change? Please explain the reason.", [file.file_id]),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["table_result_source"] == "file"
    assert len(data["evidence_list"]) == 1
    assert data["evidence_list"][0]["source_id"] == "doc_policy"


def test_file_query_does_not_add_evidence_for_a_plain_data_question() -> None:
    """No 'why/explain' keyword in the question -> no RAG call at all."""

    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _ready_csv_file()
    repository.save(file)
    _write_parquet_snapshot(storage, file, b"month,revenue\n2026-01,150.0\n2026-02,250.0\n")

    knowledge_store = InMemoryKnowledgeStore()
    knowledge_store.ingest_document(
        KnowledgeDocument(
            source_id="doc_policy",
            title="Revenue Policy",
            doc_type="policy",
            publish_time=datetime.now(timezone.utc),
        ),
        "Revenue dropped in March because a marketing campaign was paused.",
    )
    application = ChatBIApplication(orchestrator=SimpleOrchestrator(knowledge_store=knowledge_store))

    client = TestClient(
        create_app(
            application=application,
            file_repository=repository,
            object_storage_adapter=storage,
            file_query_llm_client=_FixedSqlLLMClient('SELECT * FROM "file_ufile_forecast0000000000000001"'),
        )
    )

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What is my revenue?", [file.file_id]),
    )

    assert response.status_code == 200
    assert response.json()["data"]["evidence_list"] == []


def test_file_query_computes_analytics_result_for_a_forecast_question() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _ready_csv_file()
    repository.save(file)
    _write_parquet_snapshot(
        storage,
        file,
        b"month,revenue\n2026-01,100.0\n2026-02,120.0\n2026-03,140.0\n2026-04,160.0\n",
    )

    client = TestClient(
        create_app(
            file_repository=repository,
            object_storage_adapter=storage,
            file_query_llm_client=_FixedSqlLLMClient('SELECT * FROM "file_ufile_forecast0000000000000001"'),
        )
    )

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("Forecast my revenue for the next few months.", [file.file_id]),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    analytics_result = data["analytics_result"]
    assert analytics_result is not None
    assert analytics_result["metric_id"] == "file_upload:revenue"
    assert len(analytics_result["forecast_result"]["forecast_series"]) > 0


def test_file_query_skips_analytics_when_no_time_column_is_recognizable() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _ready_csv_file(
        schema_json={"columns": [{"name": "region", "type": "VARCHAR"}, {"name": "revenue", "type": "DOUBLE"}]}
    )
    repository.save(file)
    _write_parquet_snapshot(storage, file, b"region,revenue\nUS-West,150.0\nUS-East,250.0\n")

    client = TestClient(
        create_app(
            file_repository=repository,
            object_storage_adapter=storage,
            file_query_llm_client=_FixedSqlLLMClient('SELECT * FROM "file_ufile_forecast0000000000000001"'),
        )
    )

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("Forecast my revenue for the next few months.", [file.file_id]),
    )

    assert response.status_code == 200
    assert response.json()["data"]["analytics_result"] is None
