from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Sequence

from chatbi.observability import ObservabilitySpan, TraceReplay, TraceSpanName, TraceSpanStatus
from chatbi.observability_logs import LogLevel, ObservabilityLogRecord
from chatbi.observability_postgres import PostgresObservabilityLogStore, PostgresObservabilityStore


class FakeCursor:
    """Mirrors tests/test_knowledge_postgres_vector_source.py's FakeCursor."""

    def __init__(
        self,
        fetchall_rows: tuple[tuple[Sequence[object], ...], ...] = (),
        rowcount: int = 0,
    ) -> None:
        self.executed: list[tuple[str, dict[str, object]]] = []
        self._fetchall_rows = list(fetchall_rows)
        self.rowcount = rowcount

    def execute(self, sql: str, params: dict[str, object] | None = None) -> None:
        self.executed.append((sql, dict(params or {})))

    def fetchall(self) -> Sequence[Sequence[object]]:
        if not self._fetchall_rows:
            return ()
        return self._fetchall_rows.pop(0)

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.commit_count = 0

    def cursor(self) -> FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.commit_count += 1


class FakePool:
    """A ConnectionSource fake: mirrors psycopg_pool.ConnectionPool's own
    `.connection()` contract (commit on success, return to the pool on
    context exit) closely enough to prove PostgresObservabilityLogStore/
    PostgresObservabilityStore never call `.close()` themselves — that
    would defeat the whole point of pooling."""

    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection
        self.checkout_count = 0
        self.return_count = 0

    @contextmanager
    def connection(self) -> Generator[FakeConnection]:
        self.checkout_count += 1
        try:
            yield self._connection
        finally:
            self._connection.commit()
            self.return_count += 1


def test_log_store_add_writes_one_insert_with_a_jsonb_cast_and_returns_the_connection() -> None:
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    pool = FakePool(connection)
    store = PostgresObservabilityLogStore(pool)
    record = ObservabilityLogRecord(
        trace_id="trc_1",
        level=LogLevel.INFO,
        message="Received chat query from u_001: Show revenue trend.",
        endpoint="/api/v1/chat/query",
        user_id="u_001",
        attributes={"question": "Show revenue trend."},
    )

    store.add(record)

    assert len(cursor.executed) == 1
    sql, params = cursor.executed[0]
    assert "INSERT INTO observability.log_records" in sql
    assert "%(attributes)s::jsonb" in " ".join(sql.split())
    assert params["trace_id"] == "trc_1"
    assert params["level"] == "info"
    assert params["attributes"] == '{"question": "Show revenue trend."}'
    assert connection.commit_count == 1
    # The store must never close a pooled connection — only the pool does,
    # by checking it back in — so this asserts pool bookkeeping, not
    # connection.close_count (which no longer exists on this fake at all).
    assert pool.checkout_count == 1
    assert pool.return_count == 1


def test_log_store_list_by_trace_id_parses_rows_back_into_records() -> None:
    recorded_at = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    cursor = FakeCursor(
        fetchall_rows=(
            (
                (
                    "trc_1",
                    "info",
                    "Received chat query from u_001: Show revenue trend.",
                    "/api/v1/chat/query",
                    "u_001",
                    "chatbi-api",
                    "log_recorded",
                    None,
                    {"question": "Show revenue trend."},
                    recorded_at,
                ),
            ),
        )
    )
    connection = FakeConnection(cursor)
    store = PostgresObservabilityLogStore(FakePool(connection))

    records = store.list_by_trace_id("trc_1")

    assert len(records) == 1
    assert records[0].trace_id == "trc_1"
    assert records[0].level is LogLevel.INFO
    assert records[0].attributes == {"question": "Show revenue trend."}
    assert records[0].recorded_at == recorded_at
    sql, params = cursor.executed[0]
    assert "WHERE trace_id = %(trace_id)s" in sql
    assert params["trace_id"] == "trc_1"


def test_log_store_list_all_returns_every_record() -> None:
    cursor = FakeCursor(
        fetchall_rows=(
            (
                (
                    "trc_1",
                    "warning",
                    "message",
                    "/api/v1/chat/query",
                    "u_001",
                    "chatbi-api",
                    "log_recorded",
                    "req_1",
                    {},
                    datetime(2026, 7, 13, tzinfo=timezone.utc),
                ),
            ),
        )
    )
    connection = FakeConnection(cursor)
    store = PostgresObservabilityLogStore(FakePool(connection))

    records = store.list_all()

    assert len(records) == 1
    assert records[0].level is LogLevel.WARNING
    assert records[0].request_id == "req_1"


def test_span_store_add_span_writes_one_insert_with_a_jsonb_cast_and_returns_the_connection() -> None:
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    pool = FakePool(connection)
    store = PostgresObservabilityStore(pool)
    span = ObservabilitySpan(
        trace_id="trc_1",
        span_name=TraceSpanName.RAG_RETRIEVED,
        status=TraceSpanStatus.SUCCEEDED,
        duration_ms=42,
        attributes={"evidence_count": 1, "evidence_uncertainty": False},
    )

    store.add_span(span)

    assert len(cursor.executed) == 1
    sql, params = cursor.executed[0]
    assert "INSERT INTO observability.trace_spans" in sql
    assert "%(attributes)s::jsonb" in " ".join(sql.split())
    assert params["trace_id"] == "trc_1"
    assert params["span_name"] == "rag_retrieved"
    assert params["status"] == "succeeded"
    assert params["duration_ms"] == 42
    assert connection.commit_count == 1
    assert pool.checkout_count == 1
    assert pool.return_count == 1


def test_span_store_list_spans_parses_rows_back_into_spans_in_returned_order() -> None:
    occurred_at = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    cursor = FakeCursor(
        fetchall_rows=(
            (
                (
                    "trc_1",
                    "request_received",
                    "succeeded",
                    occurred_at,
                    None,
                    {},
                ),
                (
                    "trc_1",
                    "rag_retrieved",
                    "succeeded",
                    occurred_at,
                    12,
                    {"evidence_count": 1},
                ),
            ),
        )
    )
    connection = FakeConnection(cursor)
    store = PostgresObservabilityStore(FakePool(connection))

    spans = store.list_spans("trc_1")

    assert [span.span_name for span in spans] == [
        TraceSpanName.REQUEST_RECEIVED,
        TraceSpanName.RAG_RETRIEVED,
    ]
    assert spans[1].duration_ms == 12
    assert spans[1].attributes == {"evidence_count": 1}


def test_span_store_replay_returns_none_when_no_spans_exist() -> None:
    cursor = FakeCursor(fetchall_rows=((),))
    connection = FakeConnection(cursor)
    store = PostgresObservabilityStore(FakePool(connection))

    assert store.replay("trc_missing") is None


def test_span_store_replay_wraps_spans_into_a_trace_replay() -> None:
    occurred_at = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    cursor = FakeCursor(
        fetchall_rows=(
            (("trc_1", "request_received", "succeeded", occurred_at, None, {}),),
        )
    )
    connection = FakeConnection(cursor)
    store = PostgresObservabilityStore(FakePool(connection))

    replay = store.replay("trc_1")

    assert isinstance(replay, TraceReplay)
    assert replay.trace_id == "trc_1"
    assert len(replay.spans) == 1


def test_span_store_list_all_returns_every_span() -> None:
    occurred_at = datetime(2026, 7, 13, tzinfo=timezone.utc)
    cursor = FakeCursor(
        fetchall_rows=((("trc_1", "response_sent", "succeeded", occurred_at, 5, {}),),)
    )
    connection = FakeConnection(cursor)
    store = PostgresObservabilityStore(FakePool(connection))

    spans = store.list_all()

    assert len(spans) == 1
    assert spans[0].span_name is TraceSpanName.RESPONSE_SENT


def test_log_store_prune_older_than_deletes_stale_rows_and_returns_the_count() -> None:
    # FR-FV03-043: durable storage otherwise grows without bound.
    cutoff_at = datetime(2026, 6, 13, tzinfo=timezone.utc)
    cursor = FakeCursor(rowcount=3)
    connection = FakeConnection(cursor)
    store = PostgresObservabilityLogStore(FakePool(connection))

    removed_count = store.prune_older_than(cutoff_at)

    assert removed_count == 3
    sql, params = cursor.executed[0]
    assert "DELETE FROM observability.log_records" in sql
    assert "recorded_at < %(cutoff_at)s" in sql
    assert params["cutoff_at"] == cutoff_at


def test_span_store_prune_older_than_deletes_stale_rows_and_returns_the_count() -> None:
    cutoff_at = datetime(2026, 6, 13, tzinfo=timezone.utc)
    cursor = FakeCursor(rowcount=5)
    connection = FakeConnection(cursor)
    store = PostgresObservabilityStore(FakePool(connection))

    removed_count = store.prune_older_than(cutoff_at)

    assert removed_count == 5
    sql, params = cursor.executed[0]
    assert "DELETE FROM observability.trace_spans" in sql
    assert "occurred_at < %(cutoff_at)s" in sql
    assert params["cutoff_at"] == cutoff_at


def test_multiple_calls_reuse_the_pool_across_operations() -> None:
    # The whole point of pooling: two calls against the same store must
    # each check a connection out and back in, never opening/closing a
    # brand-new one the way the pre-pooling implementation did.
    cursor = FakeCursor(fetchall_rows=((), ()))
    connection = FakeConnection(cursor)
    pool = FakePool(connection)
    store = PostgresObservabilityLogStore(pool)

    store.list_all()
    store.list_all()

    assert pool.checkout_count == 2
    assert pool.return_count == 2
