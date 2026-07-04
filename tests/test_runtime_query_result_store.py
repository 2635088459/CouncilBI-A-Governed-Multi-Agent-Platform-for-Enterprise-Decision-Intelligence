from datetime import datetime, timezone
from typing import Sequence

from chatbi.history.query_results import (
    InMemoryRuntimeQueryResultStore,
    PostgresRuntimeQueryResultStore,
    PsycopgRuntimeQueryResultConnection,
    RuntimeQueryResultRecord,
    postgres_runtime_query_result_store_from_psycopg,
)
from chatbi.migrations import (
    RUNTIME_MESSAGES_TABLE_SQL,
    RUNTIME_QUERY_RESULTS_TABLE_SQL,
    RUNTIME_SESSIONS_TABLE_SQL,
)


class FakeRuntimeQueryResultConnection:
    def __init__(self) -> None:
        self.commands: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0
        self.next_row: Sequence[object] | None = None

    def execute(self, sql: str, params: Sequence[object] = ()) -> None:
        self.commands.append((sql, tuple(params)))

    def fetchone(self) -> Sequence[object] | None:
        return self.next_row

    def commit(self) -> None:
        self.commits += 1


class FakePsycopgCursor:
    def __init__(self, row: Sequence[object] | None = None) -> None:
        self._row = row

    def fetchone(self) -> Sequence[object] | None:
        return self._row


class FakePsycopgConnection:
    def __init__(self, row: Sequence[object] | None = None) -> None:
        self.row = row
        self.commands: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0

    def execute(self, sql: str, params: Sequence[object] = ()) -> FakePsycopgCursor:
        self.commands.append((sql, tuple(params)))
        return FakePsycopgCursor(self.row)

    def commit(self) -> None:
        self.commits += 1


def make_record() -> RuntimeQueryResultRecord:
    return RuntimeQueryResultRecord(
        trace_id="tr_12345678",
        session_id="ses_12345678",
        user_id="u_001",
        org_id="org_001",
        question="Show revenue trend.",
        sql_text="SELECT month, revenue FROM revenue_by_month LIMIT 100",
        table_result={
            "columns": ("month", "revenue"),
            "rows": ({"month": "2026-01", "revenue": 1000.0},),
        },
        chart_spec={"chart_type": "line", "x_field": "month", "y_fields": ("revenue",)},
        created_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
    )


def test_in_memory_runtime_query_result_store_hashes_sql_text() -> None:
    store = InMemoryRuntimeQueryResultStore()

    store.save(make_record())

    record = store.get("tr_12345678")
    assert record is not None
    assert record.sql_hash is not None
    assert len(record.sql_hash) == 64
    assert record.table_result["columns"] == ("month", "revenue")


def test_postgres_runtime_query_result_store_saves_session_message_and_result() -> None:
    connection = FakeRuntimeQueryResultConnection()
    store = PostgresRuntimeQueryResultStore(connection)

    store.save(make_record())

    session_sql, session_params = connection.commands[0]
    message_sql, message_params = connection.commands[1]
    result_sql, result_params = connection.commands[2]

    assert "INSERT INTO runtime.sessions" in session_sql
    assert session_params[0] == "ses_12345678"
    assert session_params[1] == "u_001"
    assert session_params[2] == "Show revenue trend."
    assert session_params[-1] == "org_001"

    assert "INSERT INTO runtime.messages" in message_sql
    assert message_params[0] == "msg_tr_12345678_user"
    assert message_params[1] == "ses_12345678"
    assert message_params[2] == "tr_12345678"
    assert message_params[3] == "user"
    assert message_params[-1] == "org_001"

    assert "INSERT INTO runtime.query_results" in result_sql
    assert result_params[0] == "qr_tr_12345678"
    assert result_params[1] == "tr_12345678"
    assert result_params[2] == "msg_tr_12345678_user"
    assert isinstance(result_params[3], str)
    assert len(result_params[3]) == 64
    assert '"columns": ["month", "revenue"]' in str(result_params[4])
    assert '"chart_type": "line"' in str(result_params[5])
    assert "SELECT month, revenue" not in str(result_params)
    assert connection.commits == 1


def test_postgres_runtime_query_result_store_initializes_runtime_schema() -> None:
    connection = FakeRuntimeQueryResultConnection()
    store = PostgresRuntimeQueryResultStore(connection)

    store.initialize_schema()

    assert connection.commands == [
        (RUNTIME_SESSIONS_TABLE_SQL, ()),
        (RUNTIME_MESSAGES_TABLE_SQL, ()),
        (RUNTIME_QUERY_RESULTS_TABLE_SQL, ()),
    ]
    assert connection.commits == 1


def test_runtime_schema_initialization_is_backward_compatible_with_old_local_volumes() -> None:
    normalized_sessions = " ".join(RUNTIME_SESSIONS_TABLE_SQL.split())
    normalized_messages = " ".join(RUNTIME_MESSAGES_TABLE_SQL.split())
    normalized_results = " ".join(RUNTIME_QUERY_RESULTS_TABLE_SQL.split())

    assert "ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT 'org_legacy'" in normalized_sessions
    assert "ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT 'org_legacy'" in normalized_messages
    assert "ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT 'org_legacy'" in normalized_results
    assert "idx_runtime_sessions_org_user_created_at" in normalized_sessions
    assert "idx_runtime_messages_org_trace_id" in normalized_messages
    assert "idx_runtime_query_results_org_trace_id" in normalized_results


def test_postgres_runtime_query_result_store_loads_record_by_trace_id() -> None:
    connection = FakeRuntimeQueryResultConnection()
    connection.next_row = (
        "tr_12345678",
        "ses_12345678",
        "u_001",
        "Show revenue trend.",
        "abc123",
        '{"columns": ["month"], "rows": [{"month": "2026-01"}]}',
        '{"chart_type": "line"}',
        datetime(2026, 6, 26, tzinfo=timezone.utc),
    )
    store = PostgresRuntimeQueryResultStore(connection)

    record = store.get("tr_12345678")

    assert record is not None
    assert record.trace_id == "tr_12345678"
    assert record.session_id == "ses_12345678"
    assert record.sql_hash == "abc123"
    assert record.table_result == {"columns": ["month"], "rows": [{"month": "2026-01"}]}
    assert record.chart_spec == {"chart_type": "line"}
    assert "SELECT" not in record.sql_text


def test_psycopg_runtime_query_result_connection_fetches_latest_cursor_row() -> None:
    raw_connection = FakePsycopgConnection(row=("tr_12345678",))
    connection = PsycopgRuntimeQueryResultConnection(raw_connection)

    connection.execute("SELECT trace_id FROM runtime.query_results WHERE trace_id = %s", ("tr_12345678",))

    assert connection.fetchone() == ("tr_12345678",)


def test_postgres_runtime_query_result_store_factory_wraps_psycopg_connection() -> None:
    raw_connection = FakePsycopgConnection()

    store = postgres_runtime_query_result_store_from_psycopg(raw_connection)
    store.initialize_schema()

    assert raw_connection.commands[0][0] == RUNTIME_SESSIONS_TABLE_SQL
    assert raw_connection.commands[1][0] == RUNTIME_MESSAGES_TABLE_SQL
    assert raw_connection.commands[2][0] == RUNTIME_QUERY_RESULTS_TABLE_SQL
    assert raw_connection.commits == 1
