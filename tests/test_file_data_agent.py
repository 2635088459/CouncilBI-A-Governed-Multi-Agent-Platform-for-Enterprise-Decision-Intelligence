import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from chatbi.agents import (
    FileDataAgent,
    FileDataGuardrailResult,
    FileNotReadyError,
    FileOwnershipError,
)
from chatbi.files import (
    FileDataAgentInput,
    InMemoryFileRepository,
    InMemoryObjectStorageAdapter,
    ParquetWriter,
    StructuredFileParser,
    UserUploadedFile,
    parquet_storage_key,
)
from chatbi.llm.types import LLMRequest, LLMResponse


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _file(**overrides: object) -> UserUploadedFile:
    fields: dict[str, object] = dict(
        file_id="ufile_abc123",
        org_id="org_1",
        user_id="user_1",
        original_name="revenue.csv",
        file_type="structured",
        mime_type="text/csv",
        size_bytes=1024,
        storage_key="org_1/user_1/ufile_abc123/revenue.csv",
        content_hash="hash_abc123",
        status="ready",
        scope="user",
        file_group_id="fgrp_1",
        version_number=1,
        is_latest=True,
        created_at=_now(),
        schema_json={
            "columns": [
                {"name": "month", "type": "VARCHAR"},
                {"name": "revenue", "type": "DOUBLE"},
            ]
        },
        row_count=2,
    )
    fields.update(overrides)
    return UserUploadedFile(**fields)  # type: ignore[arg-type]


@dataclass(slots=True)
class _FixedSqlLLMClient:
    sql_text: str
    requests_seen: list[LLMRequest]

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


def _llm_client(sql_text: str) -> _FixedSqlLLMClient:
    return _FixedSqlLLMClient(sql_text=sql_text, requests_seen=[])


def _agent(
    repository: InMemoryFileRepository,
    storage: InMemoryObjectStorageAdapter,
    llm_client: _FixedSqlLLMClient,
) -> FileDataAgent:
    return FileDataAgent(repository=repository, storage=storage, llm_client=llm_client)


def _make_input(file_ids: tuple[str, ...], user_id: str = "user_1") -> FileDataAgentInput:
    return FileDataAgentInput(
        file_ids=file_ids,
        user_id=user_id,
        question="what is total revenue?",
        role="analyst",
        trace_id="trc_1",
    )


def test_run_raises_ownership_error_for_a_different_users_file() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    repository.save(_file(user_id="user_b"))
    agent = _agent(repository, storage, _llm_client("SELECT * FROM file_ufile_abc123"))

    with pytest.raises(FileOwnershipError):
        agent.run(_make_input(("ufile_abc123",), user_id="user_a"))


def test_run_raises_not_ready_error_when_file_is_still_processing() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    repository.save(_file(status="processing", schema_json=None, row_count=None))
    agent = _agent(repository, storage, _llm_client("SELECT * FROM file_ufile_abc123"))

    with pytest.raises(FileNotReadyError):
        agent.run(_make_input(("ufile_abc123",)))


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
    # An unstructured file (PDF/DOCX/...) has no schema_json and was never
    # converted to Parquet — selecting only unstructured files must not
    # reach SQL generation or DuckDB execution (previously an
    # unconditional `assert file.schema_json is not None` crashed here).
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    repository.save(_unstructured_file())
    llm_client = _llm_client("SELECT 1")
    agent = _agent(repository, storage, llm_client)

    output = agent.run(_make_input(("ufile_doc789",)))

    assert output.error_code == "NO_STRUCTURED_FILE_SELECTED"
    assert output.guardrail_blocked is False
    assert output.table_result is None
    assert llm_client.requests_seen == []


def test_run_queries_only_the_structured_file_in_a_mixed_selection() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    structured = _file()
    repository.save(structured)
    repository.save(_unstructured_file())

    table = StructuredFileParser().parse_csv(b"month,revenue\n2026-01,100.0\n")
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as temp_file:
        temp_path = Path(temp_file.name)
    ParquetWriter().write(table, temp_path)
    storage.put_object(parquet_storage_key(structured.storage_key), temp_path.read_bytes())
    temp_path.unlink()

    llm_client = _llm_client('SELECT * FROM "file_ufile_abc123"')
    agent = _agent(repository, storage, llm_client)

    output = agent.run(_make_input(("ufile_abc123", "ufile_doc789")))

    assert output.error_code is None
    assert output.table_result is not None
    assert "file_ufile_abc123" in llm_client.requests_seen[0].messages[0]["content"]
    assert "ufile_doc789" not in llm_client.requests_seen[0].messages[0]["content"]


@pytest.mark.parametrize(
    "sql_text",
    [
        "SELECT * FROM t",
        "select month, revenue from file_ufile_abc123",
    ],
)
def test_guardrail_check_allows_select_statements(sql_text: str) -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    agent = _agent(repository, storage, _llm_client(sql_text))

    outcome = agent._guardrail_check(sql_text)  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    assert outcome.result == FileDataGuardrailResult.ALLOWED
    assert outcome.blocked_statement is None


@pytest.mark.parametrize(
    ("sql_text", "expected_statement"),
    [
        ("UPDATE t SET x=1", "UPDATE"),
        ("DELETE FROM t", "DELETE"),
        ("CREATE TABLE y AS SELECT 1", "CREATE"),
        ("DROP TABLE t", "DROP"),
        ("INSERT INTO t VALUES (1)", "INSERT"),
        ("ALTER TABLE t ADD COLUMN y INT", "ALTER"),
        ("TRUNCATE TABLE t", "TRUNCATE"),
    ],
)
def test_guardrail_check_blocks_write_statements(sql_text: str, expected_statement: str) -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    agent = _agent(repository, storage, _llm_client(sql_text))

    outcome = agent._guardrail_check(sql_text)  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    assert outcome.result == FileDataGuardrailResult.BLOCKED
    assert outcome.blocked_statement == expected_statement


def test_build_schema_context_reflects_schema_json() -> None:
    # Also TC-FV10-194 / AC-FV10-085 (Spec FV10.11): _file()'s default
    # schema_json has neither sample_values nor sample_range on any column
    # — the shape of every file uploaded before that spec — so this proves
    # build_schema_context() renders it unchanged.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    agent = _agent(repository, storage, _llm_client("SELECT 1"))
    file = _file()

    context = agent.build_schema_context((file,))

    assert context == "file_ufile_abc123(month VARCHAR, revenue DOUBLE)"


def test_build_schema_context_renders_a_sample_values_suffix() -> None:
    # TC-FV10-192 / AC-FV10-083
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    agent = _agent(repository, storage, _llm_client("SELECT 1"))
    file = _file(
        schema_json={
            "columns": [
                {"name": "region", "type": "VARCHAR", "sample_values": ["US-East", "US-West"]},
                {"name": "revenue", "type": "DOUBLE"},
            ]
        }
    )

    context = agent.build_schema_context((file,))

    assert context == "file_ufile_abc123(region VARCHAR [e.g. 'US-East', 'US-West'], revenue DOUBLE)"


def test_build_schema_context_renders_a_sample_range_suffix() -> None:
    # TC-FV10-193 / AC-FV10-084
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    agent = _agent(repository, storage, _llm_client("SELECT 1"))
    file = _file(
        schema_json={
            "columns": [
                {"name": "month", "type": "VARCHAR", "sample_range": ["2026-01", "2026-06"]},
                {"name": "revenue", "type": "DOUBLE"},
            ]
        }
    )

    context = agent.build_schema_context((file,))

    assert context == "file_ufile_abc123(month VARCHAR ['2026-01'..'2026-06'], revenue DOUBLE)"


def test_run_blocked_query_returns_guardrail_blocked_output_without_touching_duckdb() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    repository.save(_file())
    # Deliberately do not put any Parquet snapshot into storage: if the
    # blocked path ever tried to touch DuckDB it would fail trying to
    # download a snapshot that does not exist.
    agent = _agent(repository, storage, _llm_client("UPDATE file_ufile_abc123 SET revenue = 0"))

    output = agent.run(_make_input(("ufile_abc123",)))

    assert output.guardrail_blocked is True
    assert output.error_code == "FileDataGuardrailBlocked"
    assert output.table_result is None
    assert output.file_ids_queried == ("ufile_abc123",)


def test_run_allowed_query_executes_against_the_parquet_snapshot() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _file()
    repository.save(file)

    table = StructuredFileParser().parse_csv(b"month,revenue\n2026-01,100.0\n2026-02,200.0\n")
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as temp_file:
        temp_path = Path(temp_file.name)
    ParquetWriter().write(table, temp_path)
    storage.put_object(parquet_storage_key(file.storage_key), temp_path.read_bytes())
    temp_path.unlink()

    agent = _agent(
        repository,
        storage,
        _llm_client('SELECT * FROM "file_ufile_abc123" ORDER BY month'),
    )

    output = agent.run(_make_input(("ufile_abc123",)))

    assert output.guardrail_blocked is False
    assert output.error_code is None
    assert output.table_result is not None
    assert output.table_result.columns == ("month", "revenue")
    assert output.table_result.rows == (
        {"month": "2026-01", "revenue": 100.0},
        {"month": "2026-02", "revenue": 200.0},
    )


def test_generate_sql_prepends_conversation_context_before_the_current_question() -> None:
    # Spec FV10.4 FR-FV10-052/056
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _file()
    repository.save(file)
    table = StructuredFileParser().parse_csv(b"month,revenue\n2026-01,100.0\n")
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as temp_file:
        temp_path = Path(temp_file.name)
    ParquetWriter().write(table, temp_path)
    storage.put_object(parquet_storage_key(file.storage_key), temp_path.read_bytes())
    temp_path.unlink()

    llm_client = _llm_client('SELECT * FROM "file_ufile_abc123"')
    agent = _agent(repository, storage, llm_client)
    request = FileDataAgentInput(
        file_ids=("ufile_abc123",),
        user_id="user_1",
        question="What about last month?",
        role="analyst",
        trace_id="trc_1",
        conversation_context=(
            {"role": "user", "content": "What was total revenue?"},
            {"role": "assistant", "content": "Total revenue was 100."},
        ),
    )

    agent.run(request)

    assert len(llm_client.requests_seen) == 1
    messages = llm_client.requests_seen[0].messages
    contents = [message["content"] for message in messages]
    assert contents == [
        messages[0]["content"],
        "What was total revenue?",
        "Total revenue was 100.",
        "What about last month?",
    ]
