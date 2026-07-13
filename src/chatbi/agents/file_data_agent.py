"""FileDataAgent: governed DuckDB SQL over a user's own Parquet snapshots.

FR-FV10-018/019: validate ownership and readiness for every requested file,
ask the LLM to generate SQL from the files' schemas, block any DML/DDL
statement before DuckDB is even started (AC-FV10-009: a blocked query must
not cause any DuckDB execution), then run the approved query and return a
``TableResult``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Mapping

import duckdb

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
from chatbi.files.contracts import FileDataAgentInput, FileDataAgentOutput, UserUploadedFile
from chatbi.files.repository import FileRepository
from chatbi.files.storage import ObjectStorageAdapter
from chatbi.llm.types import LLMClient, LLMRequest


__all__ = [
    "FileDataAgent",
    "FileDataGuardrailOutcome",
    "FileDataGuardrailResult",
    "FileNotReadyError",
    "FileOwnershipError",
]


class FileDataGuardrailResult(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class FileDataGuardrailOutcome:
    result: FileDataGuardrailResult
    blocked_statement: str | None = None


class FileDataAgent:
    """Runs the FR-FV10-018 pipeline for one chat query's ``file_ids``."""

    def __init__(
        self,
        *,
        repository: FileRepository,
        storage: ObjectStorageAdapter,
        llm_client: LLMClient,
        memory_limit: str = DEFAULT_QUERY_MEMORY_LIMIT,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._llm_client = llm_client
        self._memory_limit = memory_limit

    def run(self, request: FileDataAgentInput) -> FileDataAgentOutput:
        files = tuple(
            load_ready_owned_file(self._repository, file_id, request.user_id)
            for file_id in request.file_ids
        )

        # An unstructured file (PDF/DOCX/TXT/MD/PPTX) has no schema_json and
        # was never converted to Parquet — it is not queryable as a table.
        # If none of the selected files are structured, there is nothing for
        # DuckDB SQL to run against; a mix just queries the structured
        # subset, since a SELECT can't join against un-indexed document text
        # anyway.
        structured_files = tuple(file for file in files if file.schema_json is not None)
        if not structured_files:
            return FileDataAgentOutput(
                file_ids_queried=request.file_ids,
                guardrail_blocked=False,
                error_code="NO_STRUCTURED_FILE_SELECTED",
            )

        schema_context = self.build_schema_context(structured_files)
        sql_text = self._generate_sql(request, structured_files[0].org_id, schema_context)

        guardrail_outcome = self._guardrail_check(sql_text)
        if guardrail_outcome.result is FileDataGuardrailResult.BLOCKED:
            return FileDataAgentOutput(
                file_ids_queried=request.file_ids,
                guardrail_blocked=True,
                error_code="FileDataGuardrailBlocked",
                duckdb_sql=sql_text,
            )

        try:
            table_result = self._execute(structured_files, sql_text)
        except QueryResourceExceededError:
            return FileDataAgentOutput(
                file_ids_queried=request.file_ids,
                guardrail_blocked=False,
                error_code="QUERY_RESOURCE_EXCEEDED",
                duckdb_sql=sql_text,
            )
        except InvalidGeneratedSqlError:
            return FileDataAgentOutput(
                file_ids_queried=request.file_ids,
                guardrail_blocked=False,
                error_code="INVALID_GENERATED_SQL",
                duckdb_sql=sql_text,
            )
        return FileDataAgentOutput(
            file_ids_queried=request.file_ids,
            guardrail_blocked=False,
            table_result=table_result,
            duckdb_sql=sql_text,
        )

    def build_schema_context(self, files: tuple[UserUploadedFile, ...]) -> str:
        lines: list[str] = []
        for file in files:
            assert file.schema_json is not None
            columns = file.schema_json["columns"]
            column_defs = ", ".join(self._column_def(column) for column in columns)
            lines.append(f"file_{file.file_id}({column_defs})")
        return "\n".join(lines)

    def _column_def(self, column: Mapping[str, object]) -> str:
        # 10-followups/11: a VARCHAR column's schema_json may carry a value
        # sample computed once at upload time (SchemaSerializer); render it
        # so SQL generation sees the column's actual stored format, not
        # just its name and type. A column with neither key (every file
        # uploaded before this feature) renders exactly as before.
        piece = f"{column['name']} {column['type']}"
        if "sample_values" in column:
            examples = ", ".join(repr(value) for value in column["sample_values"])  # type: ignore[union-attr]
            return f"{piece} [e.g. {examples}]"
        if "sample_range" in column:
            low, high = column["sample_range"]  # type: ignore[misc]
            return f"{piece} [{low!r}..{high!r}]"
        return piece

    def _guardrail_check(self, sql_text: str) -> FileDataGuardrailOutcome:
        blocked_statement = find_blocked_statement(sql_text)
        if blocked_statement is None:
            return FileDataGuardrailOutcome(result=FileDataGuardrailResult.ALLOWED)
        return FileDataGuardrailOutcome(
            result=FileDataGuardrailResult.BLOCKED,
            blocked_statement=blocked_statement,
        )

    def _generate_sql(self, request: FileDataAgentInput, org_id: str, schema_context: str) -> str:
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
                task_type="file_data_sql_generation",
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

    def _execute(self, files: tuple[UserUploadedFile, ...], sql_text: str) -> TableResult:
        temp_paths: list[Path] = []
        connection = duckdb.connect(":memory:")
        try:
            apply_memory_limit(connection, self._memory_limit)
            for file in files:
                temp_paths.append(register_file_parquet_view(connection, self._storage, file))

            columns, rows = fetch_table(connection, sql_text)
            return TableResult(columns=columns, rows=rows)
        finally:
            connection.close()
            for temp_path in temp_paths:
                temp_path.unlink(missing_ok=True)
