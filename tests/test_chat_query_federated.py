"""POST /api/v2/chat/query wiring for FederatedQueryAgent (FR-FV10-021).

Covers the branch tests/test_chat_query_with_files.py's module docstring
explicitly left out: a question that names a real business table gets
answered by a live DuckDB join of the uploaded file and that table, tagged
``table_result_source: "federated"``. business_table_catalog and
federated_query_agent are injected as fakes here so this stays a fast,
offline test — no live Postgres needed.
"""

import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from fastapi.testclient import TestClient

from chatbi.agents import FederatedQueryAgent
from chatbi.api.http import create_app
from chatbi.files import (
    InMemoryFileRepository,
    InMemoryObjectStorageAdapter,
    ParquetWriter,
    PostgresQueryContext,
    StructuredFileParser,
    UserUploadedFile,
    parquet_storage_key,
)
from chatbi.governance.business_table_catalog import BusinessTableCatalog
from chatbi.llm.types import LLMRequest, LLMResponse


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


@dataclass(slots=True)
class _FixedRowSource:
    rows: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    def fetch_rows(self, context: PostgresQueryContext) -> tuple[Mapping[str, Any], ...]:
        return self.rows


class _FakeCursor:
    def __init__(self, connection: "_FakeCatalogConnection") -> None:
        self._connection = connection
        self._rows: list[tuple[object, ...]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        if "information_schema.tables" in sql:
            self._rows = [("revenue_by_month",)]
        elif "information_schema.columns" in sql:
            self._rows = [("month",), ("revenue",)] if params[0] == "revenue_by_month" else []
        else:
            self._rows = []  # no access_policies rows: every column stays visible

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class _FakeCatalogConnection:
    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)


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
        schema_json={"columns": [{"name": "month", "type": "VARCHAR"}, {"name": "forecast_revenue", "type": "DOUBLE"}]},
        row_count=2,
    )
    fields.update(overrides)
    return UserUploadedFile(**fields)  # type: ignore[arg-type]


def _write_parquet_snapshot(storage: InMemoryObjectStorageAdapter, file: UserUploadedFile) -> None:
    table = StructuredFileParser().parse_csv(b"month,forecast_revenue\n2026-01,150.0\n2026-02,250.0\n")
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


def test_question_naming_a_real_business_table_answers_via_federated_join() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _ready_csv_file()
    repository.save(file)
    _write_parquet_snapshot(storage, file)

    join_sql = (
        'SELECT f.month, f.forecast_revenue, d.revenue AS actual_revenue '
        'FROM "file_ufile_forecast0000000000000001" f '
        'JOIN "db_revenue_by_month" d ON f.month = d.month'
    )
    federated_agent = FederatedQueryAgent(
        repository=repository,
        storage=storage,
        llm_client=_FixedSqlLLMClient(join_sql),
        pg_row_source=_FixedRowSource(
            rows=(
                {"month": "2026-01", "revenue": 150.0},
                {"month": "2026-02", "revenue": 260.0},
            )
        ),
    )
    client = TestClient(
        create_app(
            file_repository=repository,
            object_storage_adapter=storage,
            file_query_llm_client=_FixedSqlLLMClient(join_sql),
            business_table_catalog=BusinessTableCatalog(_FakeCatalogConnection()),
            federated_query_agent=federated_agent,
        )
    )

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("Compare my file to revenue_by_month", [file.file_id]),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["table_result_source"] == "federated"
    assert data["table_result"]["columns"] == ["month", "forecast_revenue", "actual_revenue"]
    assert data["table_result"]["rows"] == [
        {"month": "2026-01", "forecast_revenue": 150.0, "actual_revenue": 150.0},
        {"month": "2026-02", "forecast_revenue": 250.0, "actual_revenue": 260.0},
    ]


def test_question_naming_no_business_table_falls_back_to_file_only() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _ready_csv_file()
    repository.save(file)
    _write_parquet_snapshot(storage, file)

    client = TestClient(
        create_app(
            file_repository=repository,
            object_storage_adapter=storage,
            file_query_llm_client=_FixedSqlLLMClient(
                'SELECT * FROM "file_ufile_forecast0000000000000001"'
            ),
            business_table_catalog=BusinessTableCatalog(_FakeCatalogConnection()),
            federated_query_agent=FederatedQueryAgent(
                repository=repository,
                storage=storage,
                llm_client=_FixedSqlLLMClient("SELECT 1"),
                pg_row_source=_FixedRowSource(),
            ),
        )
    )

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("What is my forecast revenue?", [file.file_id]),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["table_result_source"] == "file"


# 10-followups/12 (Spec FV10.12 §8.3, TC-FV10-204): a JOIN that matches
# zero rows because of a join-key mismatch must not be narrated as a
# confirmed "no variance" result — the answer-synthesis request must carry
# an explicit caveat instruction whenever FederatedQueryAgentOutput flags
# zero_row_join_caveat.
@dataclass(slots=True)
class _CaveatDetectingLLMClient:
    """Used as file_query_llm_client, which backs file_answer_synthesizer
    (not the federated join's own SQL-generation client, which is wired
    separately on the injected FederatedQueryAgent). Reports whether the
    zero-row-join caveat instruction reached the answer-synthesis prompt,
    without asserting on its exact wording.
    """

    def complete(self, request: LLMRequest) -> LLMResponse:
        system_content = request.messages[0]["content"]
        text = "CAVEAT_PRESENT" if "join key" in system_content.lower() else "NO_CAVEAT"
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


def test_federated_join_key_mismatch_flags_zero_row_join_caveat_in_answer_synthesis() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _ready_csv_file()  # forecast.csv: months 2026-01, 2026-02
    repository.save(file)
    _write_parquet_snapshot(storage, file)

    join_sql = (
        'SELECT f.month, f.forecast_revenue, d.revenue AS actual_revenue '
        'FROM "file_ufile_forecast0000000000000001" f '
        'JOIN "db_revenue_by_month" d ON f.month = d.month'
    )
    federated_agent = FederatedQueryAgent(
        repository=repository,
        storage=storage,
        llm_client=_FixedSqlLLMClient(join_sql),
        # Non-overlapping months: both sides have data, but the join key
        # never matches — a mismatch, not "no variance."
        pg_row_source=_FixedRowSource(
            rows=(
                {"month": "2026-03", "revenue": 150.0},
                {"month": "2026-04", "revenue": 260.0},
            )
        ),
    )
    client = TestClient(
        create_app(
            file_repository=repository,
            object_storage_adapter=storage,
            file_query_llm_client=_CaveatDetectingLLMClient(),
            business_table_catalog=BusinessTableCatalog(_FakeCatalogConnection()),
            federated_query_agent=federated_agent,
        )
    )

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("Compare my file to revenue_by_month", [file.file_id]),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["table_result_source"] == "federated"
    assert data["table_result"]["rows"] == []
    assert data["answer_text"] == "CAVEAT_PRESENT"


def test_federated_query_degrading_on_row_cap_is_tagged_file_and_warns() -> None:
    """resolve_federated_pg_context's default max_rows is 500 (see
    business_table_catalog.py); returning 501 Postgres rows here forces
    FederatedQueryAgent's real NFR-FV10-007 degrade path — no LLM/join SQL
    involved at all in that branch, matching how ``_degrade`` re-runs
    FileDataAgent alone.
    """

    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _ready_csv_file()
    repository.save(file)
    _write_parquet_snapshot(storage, file)

    oversized_rows = tuple({"month": f"2026-{i:04d}", "revenue": float(i)} for i in range(501))
    federated_agent = FederatedQueryAgent(
        repository=repository,
        storage=storage,
        llm_client=_FixedSqlLLMClient('SELECT * FROM "file_ufile_forecast0000000000000001"'),
        pg_row_source=_FixedRowSource(rows=oversized_rows),
    )

    client = TestClient(
        create_app(
            file_repository=repository,
            object_storage_adapter=storage,
            file_query_llm_client=_FixedSqlLLMClient(
                'SELECT * FROM "file_ufile_forecast0000000000000001"'
            ),
            business_table_catalog=BusinessTableCatalog(_FakeCatalogConnection()),
            federated_query_agent=federated_agent,
        )
    )

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_query_body("Compare my file to revenue_by_month", [file.file_id]),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["table_result_source"] == "file"
    assert data["table_result"]["columns"] == ["month", "forecast_revenue"]
    assert any(w.get("code") == "AGENT_PARTIAL_FAILURE" for w in response.json()["warnings"])
