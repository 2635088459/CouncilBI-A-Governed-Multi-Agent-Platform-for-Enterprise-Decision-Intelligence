"""FederatedQueryAgent: JOIN a user's Parquet file(s) with materialized Postgres rows.

FR-FV10-021: materialize the relevant Postgres result (<= pg_context.max_rows)
and the user's Parquet file(s) into one DuckDB session as ``db_{table}`` and
``file_{file_id}`` views, ask the LLM for a federated JOIN, block any DML/DDL
statement, then execute and return a ``TableResult``.

FR-FV10-022/NFR-FV10-007: when the Postgres side would exceed the row cap,
degrade gracefully — run ``FileDataAgent`` alone and mark the answer
``degraded`` instead of returning an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Protocol

import duckdb

from chatbi.agents.file_data_agent import FileDataAgent
from chatbi.agents.file_query_support import (
    DEFAULT_QUERY_MEMORY_LIMIT,
    FileNotReadyError,
    FileOwnershipError,
    InvalidGeneratedSqlError,
    QueryResourceExceededError,
    apply_memory_limit,
    fetch_table,
    find_blocked_statement,
    load_ready_owned_file,
    register_file_parquet_view,
)
from chatbi.core.contracts import TableResult
from chatbi.files.contracts import (
    FederatedQueryAgentInput,
    FederatedQueryAgentOutput,
    FileDataAgentInput,
    PostgresQueryContext,
    UserUploadedFile,
)
from chatbi.files.repository import FileRepository
from chatbi.files.storage import ObjectStorageAdapter
from chatbi.governance.readonly_executor import ReadOnlyQueryExecutor
from chatbi.llm.types import LLMClient, LLMRequest


__all__ = [
    "FederatedQueryAgent",
    "FederatedQueryGuardrailOutcome",
    "FederatedQueryGuardrailResult",
    "FileNotReadyError",
    "FileOwnershipError",
    "PostgresRowSource",
    "ReadOnlyBusinessRowSource",
    "RowCapExceeded",
]


class ReadOnlyBusinessRowSource:
    """``PostgresRowSource`` backed by the read-only business database.

    Reuses the same ``ReadOnlyQueryExecutor``/read-only connection the
    governed SQL agent already runs through, so a federated join can never
    write, and never runs against a different (less trusted) credential.
    """

    def __init__(
        self,
        executor: ReadOnlyQueryExecutor,
        database_url: str | None,
        *,
        schema: str = "business",
    ) -> None:
        self._executor = executor
        self._database_url = database_url
        self._schema = schema

    def fetch_rows(self, context: PostgresQueryContext) -> tuple[Mapping[str, Any], ...]:
        columns_sql = ", ".join(f'"{column}"' for column in context.columns)
        sql = (
            f'SELECT {columns_sql} FROM {self._schema}."{context.table_name}" '
            f"LIMIT {context.max_rows + 1}"
        )
        result = self._executor.execute(self._database_url, sql)
        if not result.succeeded or result.table_result is None:
            return ()
        return result.table_result.rows


class RowCapExceeded(Exception):
    """Raised when the Postgres side of a federated query exceeds its row cap."""

    def __init__(self, row_count: int) -> None:
        self.row_count = row_count
        super().__init__(f"postgres result row_count {row_count} exceeds the configured cap")


class FederatedQueryGuardrailResult(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class FederatedQueryGuardrailOutcome:
    result: FederatedQueryGuardrailResult
    blocked_statement: str | None = None


class PostgresRowSource(Protocol):
    """Port that supplies the already-executed Postgres rows for one context."""

    def fetch_rows(self, context: PostgresQueryContext) -> tuple[Mapping[str, Any], ...]: ...


class FederatedQueryAgent:
    """Runs the FR-FV10-021/022 pipeline for one chat query's federated join."""

    def __init__(
        self,
        *,
        repository: FileRepository,
        storage: ObjectStorageAdapter,
        llm_client: LLMClient,
        pg_row_source: PostgresRowSource,
        memory_limit: str = DEFAULT_QUERY_MEMORY_LIMIT,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._llm_client = llm_client
        self._pg_row_source = pg_row_source
        self._memory_limit = memory_limit
        self._file_data_agent = FileDataAgent(
            repository=repository, storage=storage, llm_client=llm_client
        )

    def run(self, request: FederatedQueryAgentInput) -> FederatedQueryAgentOutput:
        pg_rows = self._pg_row_source.fetch_rows(request.pg_context)
        if len(pg_rows) > request.pg_context.max_rows:
            return self._degrade(request)

        files = tuple(
            load_ready_owned_file(self._repository, file_id, request.user_id)
            for file_id in request.file_ids
        )

        # Same constraint as FileDataAgent: an unstructured file has no
        # Parquet snapshot to register a DuckDB view over and no schema_json
        # to describe to the LLM. Query only the structured subset; if none
        # of the selected files are structured, there is nothing this agent
        # can add beyond the Postgres table alone — surface that instead of
        # crashing on the first unstructured file it touches.
        structured_files = tuple(file for file in files if file.schema_json is not None)
        if not structured_files:
            return FederatedQueryAgentOutput(
                degraded=False,
                error_code="NO_STRUCTURED_FILE_SELECTED",
            )

        temp_paths: list[Path] = []
        connection = duckdb.connect(":memory:")
        try:
            apply_memory_limit(connection, self._memory_limit)
            self._register_views(
                connection,
                pg_context=request.pg_context,
                pg_rows=pg_rows,
                files=structured_files,
                temp_paths=temp_paths,
            )

            schema_context = self._build_schema_context(request.pg_context, structured_files)
            sql_text = self._generate_sql(request, structured_files[0].org_id, schema_context)

            guardrail_outcome = self._guardrail_check(sql_text)
            if guardrail_outcome.result is FederatedQueryGuardrailResult.BLOCKED:
                return FederatedQueryAgentOutput(
                    degraded=False,
                    error_code="FederatedQueryGuardrailBlocked",
                    federated_sql=sql_text,
                )

            try:
                columns, rows = fetch_table(connection, sql_text)
            except QueryResourceExceededError:
                return FederatedQueryAgentOutput(
                    degraded=False,
                    error_code="QUERY_RESOURCE_EXCEEDED",
                    federated_sql=sql_text,
                )
            except InvalidGeneratedSqlError:
                return FederatedQueryAgentOutput(
                    degraded=False,
                    error_code="INVALID_GENERATED_SQL",
                    federated_sql=sql_text,
                )
            zero_row_join_caveat = self._compute_zero_row_join_caveat(
                connection,
                rows=rows,
                sql_text=sql_text,
                pg_table_name=request.pg_context.table_name,
                structured_files=structured_files,
            )
            return FederatedQueryAgentOutput(
                degraded=False,
                table_result=TableResult(columns=columns, rows=rows),
                federated_sql=sql_text,
                zero_row_join_caveat=zero_row_join_caveat,
            )
        finally:
            connection.close()
            for temp_path in temp_paths:
                temp_path.unlink(missing_ok=True)

    def _register_views(
        self,
        connection: Any,
        *,
        pg_context: PostgresQueryContext,
        pg_rows: tuple[Mapping[str, Any], ...],
        files: tuple[UserUploadedFile, ...],
        temp_paths: list[Path] | None = None,
    ) -> None:
        self._materialize_pg_result(connection, pg_context, pg_rows)
        for file in files:
            temp_path = register_file_parquet_view(connection, self._storage, file)
            if temp_paths is not None:
                temp_paths.append(temp_path)

    def _materialize_pg_result(
        self,
        connection: Any,
        context: PostgresQueryContext,
        rows: tuple[Mapping[str, Any], ...],
    ) -> None:
        if len(rows) > context.max_rows:
            raise RowCapExceeded(len(rows))

        column_defs = ", ".join(
            f'"{column}" {_infer_duckdb_type(column, rows)}' for column in context.columns
        )
        connection.execute(f'CREATE TABLE "db_{context.table_name}" ({column_defs})')
        if rows:
            placeholders = ", ".join("?" for _ in context.columns)
            row_values = [tuple(row.get(column) for column in context.columns) for row in rows]
            connection.executemany(
                f'INSERT INTO "db_{context.table_name}" VALUES ({placeholders})', row_values
            )

    def _guardrail_check(self, sql_text: str) -> FederatedQueryGuardrailOutcome:
        blocked_statement = find_blocked_statement(sql_text)
        if blocked_statement is None:
            return FederatedQueryGuardrailOutcome(result=FederatedQueryGuardrailResult.ALLOWED)
        return FederatedQueryGuardrailOutcome(
            result=FederatedQueryGuardrailResult.BLOCKED,
            blocked_statement=blocked_statement,
        )

    def _compute_zero_row_join_caveat(
        self,
        connection: Any,
        *,
        rows: tuple[Mapping[str, Any], ...],
        sql_text: str,
        pg_table_name: str,
        structured_files: tuple[UserUploadedFile, ...],
    ) -> bool:
        # 10-followups/12 (revised, 10-followups/14): a cross-source
        # comparison that matches nothing — whether via JOIN, EXCEPT, NOT
        # EXISTS, or an anti-join subquery — produces the same empty
        # TableResult as a comparison that genuinely found no rows passing a
        # filter; callers cannot tell them apart from `rows` alone. The
        # original version of this check looked for the literal substring
        # "join" in the generated SQL, which a real comparison query for
        # "flag any differences" is not obligated to use — an LLM asked to
        # compare two sources routinely reaches for EXCEPT or NOT EXISTS
        # instead, neither of which contains that keyword. What actually
        # matters is whether the query is a genuine cross-source comparison
        # at all: does it reference both the materialized business-table
        # view and at least one file view. Only worth checking source row
        # counts when the result is actually empty and the query really
        # spans both sources; an empty *source* (not a comparison-key
        # mismatch) is a different, unambiguous situation and must not raise
        # this caveat.
        if rows:
            return False
        references_business_table = f"db_{pg_table_name}" in sql_text
        references_a_file = any(
            f"file_{file.file_id}" in sql_text for file in structured_files
        )
        if not (references_business_table and references_a_file):
            return False
        if self._source_row_count(connection, f"db_{pg_table_name}") == 0:
            return False
        return all(
            self._source_row_count(connection, f"file_{file.file_id}") > 0
            for file in structured_files
        )

    def _source_row_count(self, connection: Any, view_name: str) -> int:
        return connection.execute(f'SELECT COUNT(*) FROM "{view_name}"').fetchone()[0]

    def _build_schema_context(
        self,
        pg_context: PostgresQueryContext,
        files: tuple[UserUploadedFile, ...],
    ) -> str:
        db_line = f"db_{pg_context.table_name}({', '.join(pg_context.columns)})"
        file_lines = self._file_data_agent.build_schema_context(files)
        return "\n".join([db_line, file_lines])

    def _generate_sql(
        self,
        request: FederatedQueryAgentInput,
        org_id: str,
        schema_context: str,
    ) -> str:
        system_prompt = (
            "You are a DuckDB SQL generator. Reply with exactly one DuckDB "
            "SELECT statement that answers the user's question and nothing "
            "else: no explanation, no markdown code fences, no prose.\n\n"
            f"Available tables:\n{schema_context}\n\n"
            "Prior conversation turns, if present, may be about a different "
            "table or data source with different value formats (e.g. month "
            "names vs. 'YYYY-MM' strings). Use them only to resolve "
            "pronouns or follow-up references in the current question (e.g. "
            "'and July?'). Never copy a literal value or format from an "
            "earlier turn into this query — every literal must match the "
            "actual values in the tables listed above."
        )
        response = self._llm_client.complete(
            LLMRequest(
                task_type="federated_query_sql_generation",
                prompt_version="v1",
                messages=(
                    {"role": "system", "content": system_prompt},
                    # FR-FV10-052/056: prior turns, prepended verbatim — the
                    # only mechanism this pipeline uses to resolve follow-up
                    # references like "and July?" before generating SQL.
                    *request.conversation_context,
                    {"role": "user", "content": request.question},
                ),
                model_policy={},
                temperature=0.0,
                max_tokens=500,
                user_id=request.user_id,
                org_id=org_id,
                trace_id=request.trace_id,
            )
        )
        return response.text

    def _degrade(self, request: FederatedQueryAgentInput) -> FederatedQueryAgentOutput:
        file_output = self._file_data_agent.run(
            FileDataAgentInput(
                file_ids=request.file_ids,
                user_id=request.user_id,
                question=request.question,
                role=request.role,
                trace_id=request.trace_id,
            )
        )
        return FederatedQueryAgentOutput(
            degraded=True,
            degradation_reason="POSTGRES_ROW_CAP_EXCEEDED",
            table_result=file_output.table_result,
        )


def _infer_duckdb_type(column: str, rows: tuple[Mapping[str, Any], ...]) -> str:
    for row in rows:
        value = row.get(column)
        if value is None:
            continue
        if isinstance(value, bool):
            return "BOOLEAN"
        if isinstance(value, int):
            return "BIGINT"
        if isinstance(value, float):
            return "DOUBLE"
        return "VARCHAR"
    return "VARCHAR"
