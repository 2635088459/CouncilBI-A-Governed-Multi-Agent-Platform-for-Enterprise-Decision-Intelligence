"""PostgreSQL-backed runtime query history for the v2 data model."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping, Protocol, Sequence, cast

from chatbi.migrations import RUNTIME_QUERY_HISTORY_TABLE_SQL


class RuntimeQueryHistoryStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEGRADED = "degraded"


class RuntimeQueryHistoryConnection(Protocol):
    def execute(self, sql: str, params: Sequence[object] = ()) -> Any:
        ...

    def fetchone(self) -> Sequence[object] | None:
        ...

    def fetchall(self) -> Sequence[Sequence[object]]:
        ...

    def commit(self) -> None:
        ...


@dataclass(frozen=True, slots=True)
class RuntimeQueryHistoryRecord:
    trace_id: str
    session_id: str
    message_id: str
    status: RuntimeQueryHistoryStatus
    question: str
    created_at: datetime
    sql_text: str | None = None
    final_answer: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not self.trace_id.strip():
            raise ValueError("trace_id is required")
        if not self.trace_id.startswith("trc_"):
            raise ValueError("trace_id must start with 'trc_'")
        if not self.session_id.strip():
            raise ValueError("session_id is required")
        if not self.message_id.strip():
            raise ValueError("message_id is required")
        if not self.question.strip():
            raise ValueError("question is required")


class PostgresRuntimeQueryHistoryStore:
    """Persist and replay final query history rows from PostgreSQL."""

    def __init__(self, connection: RuntimeQueryHistoryConnection) -> None:
        self._connection = connection

    def initialize_schema(self) -> None:
        self._connection.execute(RUNTIME_QUERY_HISTORY_TABLE_SQL)
        self._connection.commit()

    def save(self, record: RuntimeQueryHistoryRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO runtime.query_history (
                trace_id,
                session_id,
                message_id,
                status,
                question,
                sql_text,
                final_answer,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (trace_id) DO UPDATE SET
                session_id = EXCLUDED.session_id,
                message_id = EXCLUDED.message_id,
                status = EXCLUDED.status,
                question = EXCLUDED.question,
                sql_text = EXCLUDED.sql_text,
                final_answer = EXCLUDED.final_answer,
                created_at = EXCLUDED.created_at
            """,
            (
                record.trace_id,
                record.session_id,
                record.message_id,
                record.status.value,
                record.question,
                record.sql_text,
                (
                    json.dumps(record.final_answer, sort_keys=True)
                    if record.final_answer is not None
                    else None
                ),
                record.created_at,
            ),
        )
        self._connection.commit()

    def get(self, trace_id: str) -> RuntimeQueryHistoryRecord | None:
        self._connection.execute(
            """
            SELECT
                trace_id,
                session_id,
                message_id,
                status,
                question,
                sql_text,
                final_answer,
                created_at
            FROM runtime.query_history
            WHERE trace_id = %s
            """,
            (trace_id,),
        )
        row = self._connection.fetchone()
        if row is None:
            return None
        return _record_from_row(row)

    def list_by_session(
        self,
        session_id: str,
        limit: int = 50,
    ) -> tuple[RuntimeQueryHistoryRecord, ...]:
        if not session_id.strip():
            raise ValueError("session_id is required")
        if limit <= 0:
            raise ValueError("limit must be greater than 0")

        self._connection.execute(
            """
            SELECT
                trace_id,
                session_id,
                message_id,
                status,
                question,
                sql_text,
                final_answer,
                created_at
            FROM runtime.query_history
            WHERE session_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (session_id, limit),
        )
        return tuple(_record_from_row(row) for row in self._connection.fetchall())


class PsycopgRuntimeQueryHistoryConnection:
    """Adapt a psycopg-style connection to RuntimeQueryHistoryConnection."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._latest_cursor: Any | None = None

    def execute(self, sql: str, params: Sequence[object] = ()) -> Any:
        self._latest_cursor = self._connection.execute(sql, params)
        return self._latest_cursor

    def fetchone(self) -> Sequence[object] | None:
        if self._latest_cursor is None:
            return None
        row = self._latest_cursor.fetchone()
        return cast(Sequence[object] | None, row)

    def fetchall(self) -> Sequence[Sequence[object]]:
        if self._latest_cursor is None:
            return ()
        rows = self._latest_cursor.fetchall()
        return cast(Sequence[Sequence[object]], rows)

    def commit(self) -> None:
        self._connection.commit()


def postgres_runtime_query_history_store_from_psycopg(
    connection: Any,
) -> PostgresRuntimeQueryHistoryStore:
    return PostgresRuntimeQueryHistoryStore(PsycopgRuntimeQueryHistoryConnection(connection))


def _record_from_row(row: Sequence[object]) -> RuntimeQueryHistoryRecord:
    return RuntimeQueryHistoryRecord(
        trace_id=cast(str, row[0]),
        session_id=cast(str, row[1]),
        message_id=cast(str, row[2]),
        status=RuntimeQueryHistoryStatus(cast(str, row[3])),
        question=cast(str, row[4]),
        sql_text=cast(str | None, row[5]),
        final_answer=cast(Mapping[str, object] | None, _loads_json(row[6])),
        created_at=cast(datetime, row[7]),
    )


def _loads_json(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value
