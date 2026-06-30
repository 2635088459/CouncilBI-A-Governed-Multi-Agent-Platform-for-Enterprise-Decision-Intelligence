"""Trace-linked record replay from the v2 data model."""

from __future__ import annotations

from typing import Any, Protocol, Sequence, cast

from chatbi.core import TraceLinkedRecord, build_trace_linked_records
from chatbi.migrations import DEMO_TRACE_JOIN_SQL


class TraceLinkedRecordConnection(Protocol):
    def execute(self, sql: str, params: Sequence[object] = ()) -> Any:
        ...

    def fetchone(self) -> Sequence[object] | None:
        ...


class TraceLinkedRecordStore(Protocol):
    def get_records(self, trace_id: str) -> tuple[TraceLinkedRecord, ...]:
        ...


class PsycopgTraceLinkedRecordConnection:
    """Adapt a psycopg-style connection to the trace-link store."""

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


class PostgresTraceLinkedRecordStore:
    """Load all records that prove one completed query is trace-joinable."""

    def __init__(self, connection: TraceLinkedRecordConnection) -> None:
        self._connection = connection

    def get_records(self, trace_id: str) -> tuple[TraceLinkedRecord, ...]:
        self._connection.execute(DEMO_TRACE_JOIN_SQL, (trace_id,))
        row = self._connection.fetchone()
        if row is None:
            return ()

        return build_trace_linked_records(
            trace_id=cast(str, row[0]),
            message_id=cast(str, row[1]),
            query_result_id=cast(str, row[2]),
            agent_trace_id=cast(str, row[3]),
            audit_event_id=cast(str, row[4]),
            eval_score_id=cast(str, row[5]),
        )


def postgres_trace_linked_record_store_from_psycopg(
    connection: Any,
) -> PostgresTraceLinkedRecordStore:
    return PostgresTraceLinkedRecordStore(PsycopgTraceLinkedRecordConnection(connection))
