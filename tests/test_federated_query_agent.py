import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import duckdb
import pytest

from chatbi.agents import (
    FederatedQueryAgent,
    FederatedQueryGuardrailResult,
    RowCapExceeded,
)
from chatbi.files import (
    FederatedQueryAgentInput,
    InMemoryFileRepository,
    InMemoryObjectStorageAdapter,
    ParquetWriter,
    PostgresQueryContext,
    StructuredFileParser,
    UserUploadedFile,
    parquet_storage_key,
)
from chatbi.llm.types import LLMRequest, LLMResponse


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _empty_requests_seen() -> list[LLMRequest]:
    return []


def _file(**overrides: object) -> UserUploadedFile:
    fields: dict[str, object] = dict(
        file_id="ufile_forecast",
        org_id="org_1",
        user_id="user_1",
        original_name="forecast.csv",
        file_type="structured",
        mime_type="text/csv",
        size_bytes=1024,
        storage_key="org_1/user_1/ufile_forecast/forecast.csv",
        content_hash="hash_forecast",
        status="ready",
        scope="user",
        file_group_id="fgrp_1",
        version_number=1,
        is_latest=True,
        created_at=_now(),
        schema_json={
            "columns": [
                {"name": "month", "type": "VARCHAR"},
                {"name": "forecast_revenue", "type": "DOUBLE"},
            ]
        },
        row_count=2,
    )
    fields.update(overrides)
    return UserUploadedFile(**fields)  # type: ignore[arg-type]


@dataclass(slots=True)
class _FixedSqlLLMClient:
    sql_text: str
    requests_seen: list[LLMRequest] = field(default_factory=_empty_requests_seen)

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests_seen.append(request)
        return LLMResponse(
            text=self.sql_text,
            model_name="mock-model",
            provider="mock",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            estimated_cost=0.0,
            latency_ms=1,
            finish_reason="stop",
        )


@dataclass(slots=True)
class _FixedPostgresRowSource:
    rows: tuple[Mapping[str, Any], ...]

    def fetch_rows(self, context: PostgresQueryContext) -> tuple[Mapping[str, Any], ...]:
        return self.rows


def _pg_context(max_rows: int = 200_000) -> PostgresQueryContext:
    return PostgresQueryContext(
        table_name="revenue", columns=("month", "actual_revenue"), max_rows=max_rows
    )


def _make_input(
    file_ids: tuple[str, ...] = ("ufile_forecast",),
    pg_context: PostgresQueryContext | None = None,
) -> FederatedQueryAgentInput:
    return FederatedQueryAgentInput(
        file_ids=file_ids,
        user_id="user_1",
        pg_context=pg_context or _pg_context(),
        question="compare my forecast with actual revenue",
        role="analyst",
        trace_id="trc_1",
    )


def _agent(
    repository: InMemoryFileRepository,
    storage: InMemoryObjectStorageAdapter,
    llm_client: _FixedSqlLLMClient,
    pg_row_source: _FixedPostgresRowSource,
) -> FederatedQueryAgent:
    return FederatedQueryAgent(
        repository=repository,
        storage=storage,
        llm_client=llm_client,
        pg_row_source=pg_row_source,
    )


def _write_parquet_snapshot(storage: InMemoryObjectStorageAdapter, file: UserUploadedFile) -> None:
    table = StructuredFileParser().parse_csv(
        b"month,forecast_revenue\n2026-01,150.0\n2026-02,250.0\n"
    )
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as temp_file:
        temp_path = Path(temp_file.name)
    ParquetWriter().write(table, temp_path)
    storage.put_object(parquet_storage_key(file.storage_key), temp_path.read_bytes())
    temp_path.unlink()


def _unstructured_file(**overrides: object) -> UserUploadedFile:
    fields: dict[str, object] = dict(
        file_id="ufile_doc789",
        original_name="onepager.pdf",
        file_type="unstructured",
        mime_type="application/pdf",
        storage_key="org_1/user_1/ufile_doc789/onepager.pdf",
        content_hash="hash_doc789",
        schema_json=None,
        row_count=None,
        chunk_count=1,
    )
    fields.update(overrides)
    return _file(**fields)


def test_run_returns_no_structured_file_selected_for_an_unstructured_only_selection() -> None:
    # Same constraint as FileDataAgent (tests/test_file_data_agent.py): an
    # unstructured file has no Parquet snapshot to register a DuckDB view
    # over — selecting only unstructured files must not reach view
    # registration or SQL generation.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    repository.save(_unstructured_file())
    llm_client = _FixedSqlLLMClient(sql_text="SELECT 1")
    pg_row_source = _FixedPostgresRowSource(rows=({"month": "2026-01", "actual_revenue": 100.0},))
    agent = _agent(repository, storage, llm_client, pg_row_source)

    output = agent.run(_make_input(file_ids=("ufile_doc789",)))

    assert output.error_code == "NO_STRUCTURED_FILE_SELECTED"
    assert output.degraded is False
    assert output.table_result is None
    assert llm_client.requests_seen == []


def test_materialize_pg_result_raises_row_cap_exceeded_over_the_limit() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    agent = _agent(
        repository, storage, _FixedSqlLLMClient("SELECT 1"), _FixedPostgresRowSource(())
    )
    context = _pg_context(max_rows=200_000)
    oversized_rows = tuple({"month": str(i), "actual_revenue": 1.0} for i in range(200_001))
    connection = duckdb.connect(":memory:")

    with pytest.raises(RowCapExceeded) as excinfo:
        agent._materialize_pg_result(connection, context, oversized_rows)  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    connection.close()
    assert excinfo.value.row_count == 200_001


def test_register_views_creates_db_and_file_views_in_the_session() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _file()
    _write_parquet_snapshot(storage, file)
    agent = _agent(
        repository, storage, _FixedSqlLLMClient("SELECT 1"), _FixedPostgresRowSource(())
    )
    context = _pg_context()
    pg_rows = ({"month": "2026-01", "actual_revenue": 120.0},)
    connection = duckdb.connect(":memory:")
    temp_paths: list[Path] = []

    try:
        agent._register_views(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
            connection,
            pg_context=context,
            pg_rows=pg_rows,
            files=(file,),
            temp_paths=temp_paths,
        )

        db_rows = connection.sql('SELECT * FROM "db_revenue"').fetchall()
        file_rows = connection.sql('SELECT * FROM "file_ufile_forecast"').fetchall()
    finally:
        connection.close()
        for temp_path in temp_paths:
            temp_path.unlink(missing_ok=True)

    assert db_rows == [("2026-01", 120.0)]
    assert file_rows == [("2026-01", 150.0), ("2026-02", 250.0)]


def test_run_degrades_when_postgres_result_exceeds_row_cap() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _file()
    repository.save(file)
    _write_parquet_snapshot(storage, file)
    oversized_rows = tuple({"month": str(i), "actual_revenue": 1.0} for i in range(200_001))
    agent = _agent(
        repository,
        storage,
        _FixedSqlLLMClient("SELECT * FROM file_ufile_forecast"),
        _FixedPostgresRowSource(oversized_rows),
    )

    output = agent.run(_make_input())

    assert output.degraded is True
    assert output.degradation_reason == "POSTGRES_ROW_CAP_EXCEEDED"
    assert output.table_result is not None
    assert len(output.table_result.rows) == 2
    assert output.error_code is None


def test_generate_sql_prepends_conversation_context_before_the_current_question() -> None:
    # Spec FV10.4 FR-FV10-052/056
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _file()
    repository.save(file)
    _write_parquet_snapshot(storage, file)
    llm_client = _FixedSqlLLMClient("SELECT * FROM file_ufile_forecast")
    agent = _agent(repository, storage, llm_client, _FixedPostgresRowSource(()))
    request = FederatedQueryAgentInput(
        file_ids=("ufile_forecast",),
        user_id="user_1",
        pg_context=_pg_context(),
        question="What about last month?",
        role="analyst",
        trace_id="trc_1",
        conversation_context=(
            {"role": "user", "content": "How does my forecast compare to actuals?"},
            {"role": "assistant", "content": "Forecast tracked actuals closely."},
        ),
    )

    agent.run(request)

    assert len(llm_client.requests_seen) == 1
    messages = llm_client.requests_seen[0].messages
    contents = [message["content"] for message in messages]
    assert contents == [
        messages[0]["content"],
        "How does my forecast compare to actuals?",
        "Forecast tracked actuals closely.",
        "What about last month?",
    ]


def test_guardrail_check_blocks_write_statements_in_a_join() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    agent = _agent(
        repository, storage, _FixedSqlLLMClient("SELECT 1"), _FixedPostgresRowSource(())
    )

    outcome = agent._guardrail_check(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        'UPDATE "db_revenue" SET actual_revenue = 0'
    )

    assert outcome.result == FederatedQueryGuardrailResult.BLOCKED
    assert outcome.blocked_statement == "UPDATE"


def test_run_blocked_join_returns_no_table_result() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _file()
    repository.save(file)
    _write_parquet_snapshot(storage, file)
    agent = _agent(
        repository,
        storage,
        _FixedSqlLLMClient('DELETE FROM "db_revenue"'),
        _FixedPostgresRowSource(({"month": "2026-01", "actual_revenue": 120.0},)),
    )

    output = agent.run(_make_input())

    assert output.degraded is False
    assert output.error_code == "FederatedQueryGuardrailBlocked"
    assert output.table_result is None


def test_run_allowed_join_returns_columns_from_both_sources() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _file()
    repository.save(file)
    _write_parquet_snapshot(storage, file)
    sql_text = (
        'SELECT d.month, d.actual_revenue, f.forecast_revenue '
        'FROM "db_revenue" d JOIN "file_ufile_forecast" f ON d.month = f.month '
        "ORDER BY d.month"
    )
    agent = _agent(
        repository,
        storage,
        _FixedSqlLLMClient(sql_text),
        _FixedPostgresRowSource(
            (
                {"month": "2026-01", "actual_revenue": 120.0},
                {"month": "2026-02", "actual_revenue": 240.0},
            )
        ),
    )

    output = agent.run(_make_input())

    assert output.degraded is False
    assert output.table_result is not None
    assert output.table_result.columns == ("month", "actual_revenue", "forecast_revenue")
    assert output.table_result.rows == (
        {"month": "2026-01", "actual_revenue": 120.0, "forecast_revenue": 150.0},
        {"month": "2026-02", "actual_revenue": 240.0, "forecast_revenue": 250.0},
    )


def test_business_table_schema_line_is_unaffected_by_a_files_value_samples() -> None:
    # TC-FV10-196 / AC-FV10-087 (Spec FV10.11): the db_{table_name}(...)
    # line built from PostgresQueryContext.columns must render identically
    # whether or not the attached file's schema_json also carries
    # sample_values/sample_range — those samples must only ever reach the
    # file side of the schema context, never the business-table side.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    plain_file = _file()
    sampled_file = _file(
        file_id="ufile_forecast_sampled",
        storage_key="org_1/user_1/ufile_forecast_sampled/forecast.csv",
        schema_json={
            "columns": [
                {"name": "month", "type": "VARCHAR", "sample_range": ["2026-01", "2026-12"]},
                {"name": "forecast_revenue", "type": "DOUBLE"},
            ]
        },
    )
    repository.save(plain_file)
    repository.save(sampled_file)
    _write_parquet_snapshot(storage, plain_file)
    _write_parquet_snapshot(storage, sampled_file)
    row_source = _FixedPostgresRowSource(rows=({"month": "2026-01", "actual_revenue": 150.0},))

    plain_llm = _FixedSqlLLMClient(sql_text="SELECT 1")
    sampled_llm = _FixedSqlLLMClient(sql_text="SELECT 1")
    _agent(repository, storage, plain_llm, row_source).run(_make_input(file_ids=(plain_file.file_id,)))
    _agent(repository, storage, sampled_llm, row_source).run(_make_input(file_ids=(sampled_file.file_id,)))

    plain_prompt = plain_llm.requests_seen[0].messages[0]["content"]
    sampled_prompt = sampled_llm.requests_seen[0].messages[0]["content"]
    plain_db_line = next(line for line in plain_prompt.splitlines() if line.startswith("db_revenue("))
    sampled_db_line = next(line for line in sampled_prompt.splitlines() if line.startswith("db_revenue("))
    assert plain_db_line == sampled_db_line


# 10-followups/12 (Spec FV10.12 §8.2, TC-FV10-200..203): a JOIN that
# matches nothing produces the same empty TableResult as a comparison that
# genuinely found no rows passing a threshold. zero_row_join_caveat must
# distinguish "join key mismatch" from "sources agree, nothing exceeded the
# filter" and from "a source itself was empty."
def test_zero_row_join_caveat_true_when_join_keys_do_not_match_and_sources_are_non_empty() -> None:
    # AC-FV10-091: both sides have data, but no month value overlaps, so the
    # JOIN's ON clause never matches — a join-key mismatch, not "no variance."
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _file()
    repository.save(file)
    _write_parquet_snapshot(storage, file)  # months 2026-01, 2026-02
    sql_text = (
        'SELECT d.month, d.actual_revenue, f.forecast_revenue '
        'FROM "db_revenue" d JOIN "file_ufile_forecast" f ON d.month = f.month'
    )
    agent = _agent(
        repository,
        storage,
        _FixedSqlLLMClient(sql_text),
        _FixedPostgresRowSource(
            (
                {"month": "2026-03", "actual_revenue": 120.0},
                {"month": "2026-04", "actual_revenue": 240.0},
            )
        ),
    )

    output = agent.run(_make_input())

    assert output.table_result is not None
    assert output.table_result.rows == ()
    assert output.zero_row_join_caveat is True


def test_zero_row_join_caveat_true_for_an_except_comparison_with_no_literal_join_keyword() -> None:
    # 10-followups/14: reproduces a live-reported case — "compare my file
    # against revenue_by_month and flag differences" — where the model wrote
    # a genuine cross-source comparison using EXCEPT instead of JOIN. Both
    # sides cover the same months, so comparing month values alone (ignoring
    # the revenue column entirely) returns zero rows even though every
    # month's revenue actually differs by orders of magnitude. The original
    # "join" substring check missed this; the fixed check instead looks for
    # both source views being referenced at all.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _file()
    repository.save(file)
    _write_parquet_snapshot(storage, file)  # months 2026-01, 2026-02
    sql_text = (
        'SELECT month FROM "file_ufile_forecast" '
        'EXCEPT SELECT month FROM "db_revenue"'
    )
    agent = _agent(
        repository,
        storage,
        _FixedSqlLLMClient(sql_text),
        _FixedPostgresRowSource(
            (
                {"month": "2026-01", "actual_revenue": 1000.0},
                {"month": "2026-02", "actual_revenue": 1120.0},
            )
        ),
    )

    output = agent.run(_make_input())

    assert output.table_result is not None
    assert output.table_result.rows == ()
    assert output.zero_row_join_caveat is True


def test_zero_row_join_caveat_false_when_join_keys_match() -> None:
    # AC-FV10-092: the same query shape as
    # test_run_allowed_join_returns_columns_from_both_sources, which already
    # produces a non-empty result — the caveat must not fire for a real,
    # successful comparison.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _file()
    repository.save(file)
    _write_parquet_snapshot(storage, file)
    sql_text = (
        'SELECT d.month, d.actual_revenue, f.forecast_revenue '
        'FROM "db_revenue" d JOIN "file_ufile_forecast" f ON d.month = f.month '
        "ORDER BY d.month"
    )
    agent = _agent(
        repository,
        storage,
        _FixedSqlLLMClient(sql_text),
        _FixedPostgresRowSource(
            (
                {"month": "2026-01", "actual_revenue": 120.0},
                {"month": "2026-02", "actual_revenue": 240.0},
            )
        ),
    )

    output = agent.run(_make_input())

    assert len(output.table_result.rows) == 2  # type: ignore[union-attr]
    assert output.zero_row_join_caveat is False


def test_zero_row_join_caveat_false_when_the_postgres_side_is_empty() -> None:
    # AC-FV10-093: an empty *source* — not a join-key mismatch — explains the
    # empty result on its own; raising the caveat here would be misleading.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _file()
    repository.save(file)
    _write_parquet_snapshot(storage, file)
    sql_text = (
        'SELECT d.month, d.actual_revenue, f.forecast_revenue '
        'FROM "db_revenue" d JOIN "file_ufile_forecast" f ON d.month = f.month'
    )
    agent = _agent(
        repository,
        storage,
        _FixedSqlLLMClient(sql_text),
        _FixedPostgresRowSource(()),
    )

    output = agent.run(_make_input())

    assert output.table_result is not None
    assert output.table_result.rows == ()
    assert output.zero_row_join_caveat is False


def test_zero_row_join_caveat_false_when_the_query_only_references_one_source() -> None:
    # AC-FV10-093-adjacent (§8.2 TC-FV10-203, revised per 10-followups/14): a
    # single-table query that only references the business-table view (never
    # any file view) is not a cross-source comparison at all — an ordinary
    # empty result, not a comparison-key mismatch. The caveat now checks for
    # both source views being referenced, not a literal "join" keyword.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _file()
    repository.save(file)
    _write_parquet_snapshot(storage, file)
    agent = _agent(
        repository,
        storage,
        _FixedSqlLLMClient('SELECT * FROM "db_revenue" WHERE month = \'2099-01\''),
        _FixedPostgresRowSource(({"month": "2026-01", "actual_revenue": 120.0},)),
    )

    output = agent.run(_make_input())

    assert output.table_result is not None
    assert output.table_result.rows == ()
    assert output.zero_row_join_caveat is False


def test_query_exceeding_memory_limit_returns_resource_exceeded_in_an_isolated_subprocess() -> None:
    probe_path = Path(__file__).parent / "_federated_query_agent_memory_probe.py"

    result = subprocess.run(
        [sys.executable, str(probe_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, f"probe process crashed: {result.stderr}"
    assert "RESOURCE_EXCEEDED_OK" in result.stdout, result.stdout + result.stderr
