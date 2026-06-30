from datetime import datetime, timezone
from typing import Sequence

from chatbi.history import (
    PostgresRuntimeQueryHistoryStore,
    RuntimeQueryHistoryRecord,
    RuntimeQueryHistoryStatus,
)
from chatbi.history.query_history import PsycopgRuntimeQueryHistoryConnection
from chatbi.migrations import RUNTIME_QUERY_HISTORY_TABLE_SQL


class FakeRuntimeQueryHistoryConnection:
    def __init__(self) -> None:
        self.commands: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0
        self.next_row: Sequence[object] | None = None
        self.next_rows: Sequence[Sequence[object]] = ()

    def execute(self, sql: str, params: Sequence[object] = ()) -> object:
        self.commands.append((sql, tuple(params)))
        return object()

    def fetchone(self) -> Sequence[object] | None:
        return self.next_row

    def fetchall(self) -> Sequence[Sequence[object]]:
        return self.next_rows

    def commit(self) -> None:
        self.commits += 1


class FakePsycopgCursor:
    def __init__(
        self,
        row: Sequence[object] | None,
        rows: Sequence[Sequence[object]] = (),
    ) -> None:
        self._row = row
        self._rows = rows

    def fetchone(self) -> Sequence[object] | None:
        return self._row

    def fetchall(self) -> Sequence[Sequence[object]]:
        return self._rows


class FakePsycopgConnection:
    def __init__(
        self,
        row: Sequence[object] | None = None,
        rows: Sequence[Sequence[object]] = (),
    ) -> None:
        self.row = row
        self.rows = rows
        self.commands: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0

    def execute(self, sql: str, params: Sequence[object] = ()) -> FakePsycopgCursor:
        self.commands.append((sql, tuple(params)))
        return FakePsycopgCursor(self.row, self.rows)

    def commit(self) -> None:
        self.commits += 1


def make_record() -> RuntimeQueryHistoryRecord:
    return RuntimeQueryHistoryRecord(
        trace_id="trc_demo_revenue_2026_h1",
        session_id="sess_demo_revenue_2026_h1",
        message_id="msg_demo_revenue_question",
        status=RuntimeQueryHistoryStatus.SUCCEEDED,
        question="What is revenue by month for the first half of 2026?",
        sql_text="SELECT month, revenue FROM business.revenue_by_month ORDER BY month",
        final_answer={"answer_text": "Revenue increased.", "confidence": 1.0},
        created_at=datetime(2026, 6, 25, tzinfo=timezone.utc),
    )


def test_runtime_query_history_record_rejects_invalid_identity_fields() -> None:
    try:
        RuntimeQueryHistoryRecord(
            trace_id="wrong-prefix",
            session_id="sess_1",
            message_id="msg_1",
            status=RuntimeQueryHistoryStatus.SUCCEEDED,
            question="Show revenue.",
            created_at=datetime(2026, 6, 25, tzinfo=timezone.utc),
        )
    except ValueError as exc:
        assert "trace_id" in str(exc)
    else:
        raise AssertionError("expected trace_id validation failure")


def test_postgres_runtime_query_history_store_initializes_schema() -> None:
    connection = FakeRuntimeQueryHistoryConnection()
    store = PostgresRuntimeQueryHistoryStore(connection)

    store.initialize_schema()

    assert connection.commands == [(RUNTIME_QUERY_HISTORY_TABLE_SQL, ())]
    assert connection.commits == 1


def test_postgres_runtime_query_history_store_saves_record() -> None:
    connection = FakeRuntimeQueryHistoryConnection()
    store = PostgresRuntimeQueryHistoryStore(connection)

    store.save(make_record())

    sql, params = connection.commands[0]
    assert "INSERT INTO runtime.query_history" in sql
    assert "ON CONFLICT (trace_id) DO UPDATE SET" in sql
    assert params[:6] == (
        "trc_demo_revenue_2026_h1",
        "sess_demo_revenue_2026_h1",
        "msg_demo_revenue_question",
        "succeeded",
        "What is revenue by month for the first half of 2026?",
        "SELECT month, revenue FROM business.revenue_by_month ORDER BY month",
    )
    assert '"answer_text": "Revenue increased."' in str(params[6])
    assert connection.commits == 1


def test_postgres_runtime_query_history_store_loads_record_by_trace_id() -> None:
    created_at = datetime(2026, 6, 25, tzinfo=timezone.utc)
    connection = FakeRuntimeQueryHistoryConnection()
    connection.next_row = (
        "trc_demo_revenue_2026_h1",
        "sess_demo_revenue_2026_h1",
        "msg_demo_revenue_question",
        "succeeded",
        "What is revenue by month for the first half of 2026?",
        "SELECT month, revenue FROM business.revenue_by_month ORDER BY month",
        '{"answer_text": "Revenue increased.", "confidence": 1.0}',
        created_at,
    )
    store = PostgresRuntimeQueryHistoryStore(connection)

    record = store.get("trc_demo_revenue_2026_h1")

    assert record is not None
    assert record.trace_id == "trc_demo_revenue_2026_h1"
    assert record.status is RuntimeQueryHistoryStatus.SUCCEEDED
    assert record.final_answer == {"answer_text": "Revenue increased.", "confidence": 1.0}
    assert connection.commands[0][1] == ("trc_demo_revenue_2026_h1",)


def test_postgres_runtime_query_history_store_returns_none_for_unknown_trace_id() -> None:
    connection = FakeRuntimeQueryHistoryConnection()
    store = PostgresRuntimeQueryHistoryStore(connection)

    assert store.get("trc_missing") is None


def test_postgres_runtime_query_history_store_lists_records_by_session_created_at() -> None:
    first_created_at = datetime(2026, 6, 25, 12, 1, tzinfo=timezone.utc)
    second_created_at = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
    connection = FakeRuntimeQueryHistoryConnection()
    connection.next_rows = (
        (
            "trc_recent",
            "sess_demo_revenue_2026_h1",
            "msg_recent",
            "succeeded",
            "Show recent revenue.",
            "SELECT 1",
            '{"answer_text": "Recent.", "confidence": 1.0}',
            first_created_at,
        ),
        (
            "trc_older",
            "sess_demo_revenue_2026_h1",
            "msg_older",
            "degraded",
            "Show older revenue.",
            None,
            None,
            second_created_at,
        ),
    )
    store = PostgresRuntimeQueryHistoryStore(connection)

    records = store.list_by_session("sess_demo_revenue_2026_h1", limit=20)

    sql, params = connection.commands[0]
    assert "FROM runtime.query_history" in sql
    assert "WHERE session_id = %s" in sql
    assert "ORDER BY created_at DESC" in sql
    assert "LIMIT %s" in sql
    assert params == ("sess_demo_revenue_2026_h1", 20)
    assert tuple(record.trace_id for record in records) == ("trc_recent", "trc_older")
    assert records[0].final_answer == {"answer_text": "Recent.", "confidence": 1.0}
    assert records[1].status is RuntimeQueryHistoryStatus.DEGRADED


def test_postgres_runtime_query_history_store_rejects_invalid_session_lookup_inputs() -> None:
    store = PostgresRuntimeQueryHistoryStore(FakeRuntimeQueryHistoryConnection())

    try:
        store.list_by_session(" ")
    except ValueError as exc:
        assert "session_id" in str(exc)
    else:
        raise AssertionError("expected session_id validation failure")

    try:
        store.list_by_session("sess_demo", limit=0)
    except ValueError as exc:
        assert "limit" in str(exc)
    else:
        raise AssertionError("expected limit validation failure")


def test_psycopg_runtime_query_history_connection_adapts_cursor_and_commit() -> None:
    row = ("trc_demo_revenue_2026_h1",)
    raw_connection = FakePsycopgConnection(row)
    connection = PsycopgRuntimeQueryHistoryConnection(raw_connection)

    connection.execute("SELECT trace_id FROM runtime.query_history WHERE trace_id = %s", ("trc_demo",))
    fetched = connection.fetchone()
    connection.commit()

    assert fetched == row
    assert raw_connection.commands == [
        ("SELECT trace_id FROM runtime.query_history WHERE trace_id = %s", ("trc_demo",)),
    ]
    assert raw_connection.commits == 1


def test_psycopg_runtime_query_history_connection_adapts_cursor_fetchall() -> None:
    rows = (("trc_recent",), ("trc_older",))
    raw_connection = FakePsycopgConnection(rows=rows)
    connection = PsycopgRuntimeQueryHistoryConnection(raw_connection)

    connection.execute("SELECT trace_id FROM runtime.query_history WHERE session_id = %s", ("sess_demo",))

    assert connection.fetchall() == rows
