from typing import Any, Sequence

from chatbi.core import TraceLinkedRecordType
from chatbi.history import PostgresTraceLinkedRecordStore
from chatbi.history.trace_links import PsycopgTraceLinkedRecordConnection
from chatbi.migrations import DEMO_TRACE_JOIN_SQL


class FakeTraceLinkConnection:
    def __init__(self) -> None:
        self.commands: list[tuple[str, tuple[object, ...]]] = []
        self.next_row: Sequence[object] | None = None

    def execute(self, sql: str, params: Sequence[object] = ()) -> object:
        self.commands.append((sql, tuple(params)))
        return object()

    def fetchone(self) -> Sequence[object] | None:
        return self.next_row


class FakeCursor:
    def __init__(self, row: Sequence[object] | None) -> None:
        self._row = row

    def fetchone(self) -> Sequence[object] | None:
        return self._row


class FakePsycopgConnection:
    def __init__(self, row: Sequence[object] | None) -> None:
        self.row = row
        self.commands: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, params: Sequence[object] = ()) -> FakeCursor:
        self.commands.append((sql, tuple(params)))
        return FakeCursor(self.row)


def test_postgres_trace_linked_record_store_loads_joined_records_by_trace_id() -> None:
    connection = FakeTraceLinkConnection()
    connection.next_row = (
        "trc_demo_revenue_2026_h1",
        "msg_demo_revenue_question",
        "qr_demo_revenue_2026_h1",
        "agt_demo_sql_revenue_2026_h1",
        "aud_demo_revenue_2026_h1",
        "eval_score_demo_revenue_2026_h1",
        1.0,
    )
    store = PostgresTraceLinkedRecordStore(connection)

    records = store.get_records("trc_demo_revenue_2026_h1")

    assert connection.commands == [
        (DEMO_TRACE_JOIN_SQL, ("trc_demo_revenue_2026_h1",)),
    ]
    assert tuple(record.record_type for record in records) == (
        TraceLinkedRecordType.MESSAGE,
        TraceLinkedRecordType.QUERY_RESULT,
        TraceLinkedRecordType.AGENT_TRACE,
        TraceLinkedRecordType.AUDIT_EVENT,
        TraceLinkedRecordType.EVAL_SCORE,
    )
    assert tuple(record.record_id for record in records) == (
        "msg_demo_revenue_question",
        "qr_demo_revenue_2026_h1",
        "agt_demo_sql_revenue_2026_h1",
        "aud_demo_revenue_2026_h1",
        "eval_score_demo_revenue_2026_h1",
    )


def test_postgres_trace_linked_record_store_returns_empty_tuple_for_unknown_trace() -> None:
    connection = FakeTraceLinkConnection()
    store = PostgresTraceLinkedRecordStore(connection)

    assert store.get_records("trc_missing") == ()


def test_psycopg_trace_linked_record_connection_adapts_cursor_fetchone() -> None:
    row: tuple[Any, ...] = ("trc_demo", "msg_1")
    raw_connection = FakePsycopgConnection(row)
    connection = PsycopgTraceLinkedRecordConnection(raw_connection)

    connection.execute("SELECT trace_id, message_id FROM trace_links WHERE trace_id = %s", ("trc_demo",))

    assert connection.fetchone() == row
    assert raw_connection.commands == [
        ("SELECT trace_id, message_id FROM trace_links WHERE trace_id = %s", ("trc_demo",)),
    ]
