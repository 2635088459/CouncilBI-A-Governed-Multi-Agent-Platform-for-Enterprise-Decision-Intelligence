"""Spec 4.7: Postgres-backed ObservabilityLogStore/ObservabilityStore.

Both are durable across a process restart, unlike the in-memory defaults
(observability_logs.py's InMemoryObservabilityLogStore / observability.py's
InMemoryObservabilityStore), which only ever see the current process's
uptime — the reason golden_dataset_mining.py could only mine questions
asked since the last restart before this module existed.

Code-review follow-up: this originally opened and closed a brand-new
connection per call (matching PostgresKnowledgeVectorSource's per-call
pattern), but a single chat request writes 3-5 log records/spans through
this module alone, so that pattern multiplied connection churn far more
here than it does for the once-per-request pgvector narrowing call. Both
stores now borrow connections from a shared ConnectionSource — in
production, a real psycopg_pool.ConnectionPool (see
_build_default_chatbi_application in api/http.py, which constructs exactly
one pool and passes it to both stores); in tests, a fake implementing the
same tiny protocol. Callers must never close a connection borrowed this
way themselves — returning it via the `with pool.connection() as conn:`
block is what lets the pool actually reuse it.
"""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any, Mapping, Protocol, Sequence, cast
from uuid import uuid4

from chatbi.observability import ObservabilitySpan, TraceReplay, TraceSpanName, TraceSpanStatus
from chatbi.observability_logs import LogLevel, ObservabilityLogRecord

_LOG_RECORD_COLUMNS = (
    "trace_id",
    "level",
    "message",
    "endpoint",
    "user_id",
    "service",
    "event",
    "request_id",
    "attributes",
    "recorded_at",
)

_TRACE_SPAN_COLUMNS = (
    "trace_id",
    "span_name",
    "status",
    "occurred_at",
    "duration_ms",
    "attributes",
)


class ConnectionSource(Protocol):
    """A source of connections that manages their lifecycle itself —
    psycopg_pool.ConnectionPool satisfies this directly (its own
    `.connection()` already commits on success / rolls back on error and
    returns the connection to the pool on context exit, so callers here do
    not call `.commit()` or `.close()` themselves)."""

    def connection(self) -> AbstractContextManager[Any]:
        ...


def _log_record_from_row(row: Sequence[Any]) -> ObservabilityLogRecord:
    trace_id, level, message, endpoint, user_id, service, event, request_id, attributes, recorded_at = row
    return ObservabilityLogRecord(
        trace_id=str(trace_id),
        level=LogLevel(level),
        message=str(message),
        endpoint=str(endpoint),
        user_id=str(user_id),
        service=str(service),
        event=str(event),
        request_id=str(request_id) if request_id is not None else None,
        attributes=cast(Mapping[str, Any], attributes) if attributes else {},
        recorded_at=recorded_at,
    )


def _trace_span_from_row(row: Sequence[Any]) -> ObservabilitySpan:
    trace_id, span_name, status, occurred_at, duration_ms, attributes = row
    return ObservabilitySpan(
        trace_id=str(trace_id),
        span_name=TraceSpanName(span_name),
        status=TraceSpanStatus(status),
        occurred_at=occurred_at,
        duration_ms=int(duration_ms) if duration_ms is not None else None,
        attributes=cast(Mapping[str, Any], attributes) if attributes else {},
    )


class PostgresObservabilityLogStore:
    """FR-FV03-039/042: durable, pooled backing for ObservabilityLogger's
    log records."""

    def __init__(self, pool: ConnectionSource) -> None:
        self._pool = pool

    def add(self, record: ObservabilityLogRecord) -> None:
        with self._pool.connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO observability.log_records (
                        log_id, trace_id, level, message, endpoint, user_id,
                        service, event, request_id, attributes, recorded_at
                    ) VALUES (
                        %(log_id)s, %(trace_id)s, %(level)s, %(message)s, %(endpoint)s,
                        %(user_id)s, %(service)s, %(event)s, %(request_id)s,
                        %(attributes)s::jsonb, %(recorded_at)s
                    )
                    """,
                    {
                        "log_id": f"log_{uuid4().hex}",
                        "trace_id": record.trace_id,
                        "level": record.level.value,
                        "message": record.message,
                        "endpoint": record.endpoint,
                        "user_id": record.user_id,
                        "service": record.service,
                        "event": record.event,
                        "request_id": record.request_id,
                        "attributes": json.dumps(dict(record.attributes)),
                        "recorded_at": record.recorded_at,
                    },
                )

    def list_by_trace_id(self, trace_id: str) -> tuple[ObservabilityLogRecord, ...]:
        with self._pool.connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    f"SELECT {', '.join(_LOG_RECORD_COLUMNS)} FROM observability.log_records"
                    " WHERE trace_id = %(trace_id)s ORDER BY recorded_at",
                    {"trace_id": trace_id},
                )
                rows = cur.fetchall()
        return tuple(_log_record_from_row(row) for row in rows)

    def list_all(self) -> tuple[ObservabilityLogRecord, ...]:
        with self._pool.connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    f"SELECT {', '.join(_LOG_RECORD_COLUMNS)} FROM observability.log_records"
                    " ORDER BY recorded_at"
                )
                rows = cur.fetchall()
        return tuple(_log_record_from_row(row) for row in rows)

    def prune_older_than(self, cutoff_at: datetime) -> int:
        with self._pool.connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    "DELETE FROM observability.log_records WHERE recorded_at < %(cutoff_at)s",
                    {"cutoff_at": cutoff_at},
                )
                return cast(int, cur.rowcount)


class PostgresObservabilityStore:
    """FR-FV03-039/042: durable, pooled backing for TraceRecorder's trace
    spans."""

    def __init__(self, pool: ConnectionSource) -> None:
        self._pool = pool

    def add_span(self, span: ObservabilitySpan) -> None:
        with self._pool.connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO observability.trace_spans (
                        span_id, trace_id, span_name, status, occurred_at, duration_ms, attributes
                    ) VALUES (
                        %(span_id)s, %(trace_id)s, %(span_name)s, %(status)s,
                        %(occurred_at)s, %(duration_ms)s, %(attributes)s::jsonb
                    )
                    """,
                    {
                        "span_id": f"span_{uuid4().hex}",
                        "trace_id": span.trace_id,
                        "span_name": span.span_name.value,
                        "status": span.status.value,
                        "occurred_at": span.occurred_at,
                        "duration_ms": span.duration_ms,
                        "attributes": json.dumps(dict(span.attributes)),
                    },
                )

    def list_spans(self, trace_id: str) -> tuple[ObservabilitySpan, ...]:
        with self._pool.connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    f"SELECT {', '.join(_TRACE_SPAN_COLUMNS)} FROM observability.trace_spans"
                    " WHERE trace_id = %(trace_id)s ORDER BY occurred_at",
                    {"trace_id": trace_id},
                )
                rows = cur.fetchall()
        return tuple(_trace_span_from_row(row) for row in rows)

    def replay(self, trace_id: str) -> TraceReplay | None:
        spans = self.list_spans(trace_id)
        if not spans:
            return None
        return TraceReplay(trace_id=trace_id, spans=spans)

    def list_all(self) -> tuple[ObservabilitySpan, ...]:
        with self._pool.connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    f"SELECT {', '.join(_TRACE_SPAN_COLUMNS)} FROM observability.trace_spans"
                    " ORDER BY occurred_at"
                )
                rows = cur.fetchall()
        return tuple(_trace_span_from_row(row) for row in rows)

    def prune_older_than(self, cutoff_at: datetime) -> int:
        with self._pool.connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    "DELETE FROM observability.trace_spans WHERE occurred_at < %(cutoff_at)s",
                    {"cutoff_at": cutoff_at},
                )
                return cast(int, cur.rowcount)
