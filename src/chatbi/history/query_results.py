"""Runtime query result persistence for answered chat queries."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from typing import Any, Iterable, Mapping, Protocol, Sequence, cast

from chatbi.governance import SqlHasher
from chatbi.migrations import (
    RUNTIME_MESSAGES_TABLE_SQL,
    RUNTIME_QUERY_RESULTS_TABLE_SQL,
    RUNTIME_SESSIONS_TABLE_SQL,
)


class RuntimeQueryResultConnection(Protocol):
    def execute(self, sql: str, params: Sequence[object] = ()) -> Any:
        ...

    def fetchone(self) -> Sequence[object] | None:
        ...

    def commit(self) -> None:
        ...


class RuntimeQueryResultStore(Protocol):
    def initialize_schema(self) -> None:
        ...

    def save(self, record: "RuntimeQueryResultRecord") -> None:
        ...

    def get(self, trace_id: str) -> "RuntimeQueryResultRecord | None":
        ...


@dataclass(frozen=True, slots=True)
class RuntimeQueryResultRecord:
    trace_id: str
    session_id: str
    user_id: str
    question: str
    sql_text: str
    table_result: Mapping[str, object]
    chart_spec: Mapping[str, object] | None = None
    sql_hash: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.trace_id.strip():
            raise ValueError("trace_id is required")
        if not self.session_id.strip():
            raise ValueError("session_id is required")
        if not self.user_id.strip():
            raise ValueError("user_id is required")
        if not self.question.strip():
            raise ValueError("question is required")
        if not self.sql_text.strip():
            raise ValueError("sql_text is required")


class InMemoryRuntimeQueryResultStore:
    def initialize_schema(self) -> None:
        return

    def __init__(self) -> None:
        self._records: dict[str, RuntimeQueryResultRecord] = {}

    def save(self, record: RuntimeQueryResultRecord) -> None:
        sql_hash = record.sql_hash or SqlHasher().hash(record.sql_text)
        created_at = record.created_at or utc_now()
        self._records[record.trace_id] = RuntimeQueryResultRecord(
            trace_id=record.trace_id,
            session_id=record.session_id,
            user_id=record.user_id,
            question=record.question,
            sql_text=record.sql_text,
            table_result=record.table_result,
            chart_spec=record.chart_spec,
            sql_hash=sql_hash,
            created_at=created_at,
        )

    def get(self, trace_id: str) -> RuntimeQueryResultRecord | None:
        return self._records.get(trace_id)


class PostgresRuntimeQueryResultStore:
    def __init__(self, connection: RuntimeQueryResultConnection) -> None:
        self._connection = connection
        self._hasher = SqlHasher()

    def initialize_schema(self) -> None:
        self._connection.execute(RUNTIME_SESSIONS_TABLE_SQL)
        self._connection.execute(RUNTIME_MESSAGES_TABLE_SQL)
        self._connection.execute(RUNTIME_QUERY_RESULTS_TABLE_SQL)
        self._connection.commit()

    def save(self, record: RuntimeQueryResultRecord) -> None:
        created_at = record.created_at or utc_now()
        sql_hash = record.sql_hash or self._hasher.hash(record.sql_text)
        message_id = self._message_id_for(record.trace_id)
        query_result_id = self._query_result_id_for(record.trace_id)

        self._connection.execute(
            """
            INSERT INTO runtime.sessions (
                session_id,
                user_id,
                title,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (session_id) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                title = EXCLUDED.title,
                updated_at = EXCLUDED.updated_at
            """,
            (
                record.session_id,
                record.user_id,
                self._title_for(record.question),
                created_at,
                created_at,
            ),
        )
        self._connection.execute(
            """
            INSERT INTO runtime.messages (
                message_id,
                session_id,
                trace_id,
                role,
                content,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (message_id) DO UPDATE SET
                session_id = EXCLUDED.session_id,
                trace_id = EXCLUDED.trace_id,
                role = EXCLUDED.role,
                content = EXCLUDED.content,
                created_at = EXCLUDED.created_at
            """,
            (
                message_id,
                record.session_id,
                record.trace_id,
                "user",
                record.question,
                created_at,
            ),
        )
        self._connection.execute(
            """
            INSERT INTO runtime.query_results (
                query_result_id,
                trace_id,
                message_id,
                sql_hash,
                table_result,
                chart_spec,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (trace_id) DO UPDATE SET
                message_id = EXCLUDED.message_id,
                sql_hash = EXCLUDED.sql_hash,
                table_result = EXCLUDED.table_result,
                chart_spec = EXCLUDED.chart_spec,
                created_at = EXCLUDED.created_at
            """,
            (
                query_result_id,
                record.trace_id,
                message_id,
                sql_hash,
                json.dumps(_json_safe(record.table_result), sort_keys=True),
                (
                    json.dumps(_json_safe(record.chart_spec), sort_keys=True)
                    if record.chart_spec is not None
                    else None
                ),
                created_at,
            ),
        )
        self._connection.commit()

    def get(self, trace_id: str) -> RuntimeQueryResultRecord | None:
        self._connection.execute(
            """
            SELECT
                qr.trace_id,
                m.session_id,
                s.user_id,
                m.content,
                qr.sql_hash,
                qr.table_result,
                qr.chart_spec,
                qr.created_at
            FROM runtime.query_results qr
            JOIN runtime.messages m ON m.message_id = qr.message_id
            JOIN runtime.sessions s ON s.session_id = m.session_id
            WHERE qr.trace_id = %s
            """,
            (trace_id,),
        )
        row = self._connection.fetchone()
        if row is None:
            return None

        return RuntimeQueryResultRecord(
            trace_id=cast(str, row[0]),
            session_id=cast(str, row[1]),
            user_id=cast(str, row[2]),
            question=cast(str, row[3]),
            sql_text="SQL text is intentionally not persisted.",
            sql_hash=cast(str, row[4]),
            table_result=cast(Mapping[str, object], _loads_json(row[5])),
            chart_spec=cast(Mapping[str, object] | None, _loads_json(row[6])),
            created_at=cast(datetime, row[7]),
        )

    def _message_id_for(self, trace_id: str) -> str:
        return f"msg_{trace_id}_user"

    def _query_result_id_for(self, trace_id: str) -> str:
        return f"qr_{trace_id}"

    def _title_for(self, question: str) -> str:
        return question.strip()[:80] or "ChatBI query"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _loads_json(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def _json_safe(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): _json_safe(item) for key, item in mapping.items()}
    if isinstance(value, tuple | list):
        values = cast(Iterable[object], value)
        return [_json_safe(item) for item in values]
    return value


class PsycopgRuntimeQueryResultConnection:
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

    def commit(self) -> None:
        self._connection.commit()


def postgres_runtime_query_result_store_from_psycopg(
    connection: Any,
) -> PostgresRuntimeQueryResultStore:
    return PostgresRuntimeQueryResultStore(PsycopgRuntimeQueryResultConnection(connection))
