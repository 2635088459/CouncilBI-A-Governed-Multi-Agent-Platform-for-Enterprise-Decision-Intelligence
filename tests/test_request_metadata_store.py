from datetime import datetime, timezone
from typing import Sequence

import pytest

from chatbi.core.contracts import Locale, UserRole
from chatbi.core.runtime_config import RuntimeConfig
from chatbi.history.request_metadata import (
    InMemoryRequestMetadataStore,
    PostgresRequestMetadataStore,
    PsycopgRequestMetadataConnection,
    REQUEST_METADATA_TABLE,
    REQUEST_METADATA_TABLE_SQL,
    RequestMetadataConnection,
    RequestFinalStatus,
    RequestMetadataRecord,
    RequestMetadataStore,
    build_request_metadata_store,
    postgres_request_metadata_store_from_psycopg,
)


class FakeRequestMetadataConnection:
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


def make_record(trace_id: str = "tr_12345678") -> RequestMetadataRecord:
    return RequestMetadataRecord(
        trace_id=trace_id,
        request_id="req_12345678",
        session_id="ses_12345678",
        user_id="u_001",
        role=UserRole.BUSINESS_USER,
        locale=Locale.EN,
        question="Show revenue trend.",
    )


def test_request_metadata_store_saves_accepted_request_by_trace_id() -> None:
    store: RequestMetadataStore = InMemoryRequestMetadataStore()
    record = make_record()

    store.save_accepted(record)

    saved = store.get("tr_12345678")
    assert saved == record
    assert saved is not None
    assert saved.status is RequestFinalStatus.ACCEPTED
    assert saved.finished_at is None


def test_request_metadata_store_marks_request_succeeded() -> None:
    store = InMemoryRequestMetadataStore()
    store.save_accepted(make_record())

    updated = store.mark_succeeded("tr_12345678")

    assert updated.status is RequestFinalStatus.SUCCEEDED
    assert updated.finished_at is not None
    assert updated.error_code is None
    assert store.get("tr_12345678") == updated


def test_request_metadata_store_marks_request_failed_with_error_code() -> None:
    store = InMemoryRequestMetadataStore()
    store.save_accepted(make_record())

    updated = store.mark_failed("tr_12345678", error_code="VALIDATION_ERROR")

    assert updated.status is RequestFinalStatus.FAILED
    assert updated.finished_at is not None
    assert updated.error_code == "VALIDATION_ERROR"


def test_request_metadata_store_rejects_non_accepted_initial_record() -> None:
    store = InMemoryRequestMetadataStore()
    record = RequestMetadataRecord(
        trace_id="tr_12345678",
        request_id="req_12345678",
        session_id="ses_12345678",
        user_id="u_001",
        role=UserRole.BUSINESS_USER,
        locale=Locale.EN,
        question="Show revenue trend.",
        status=RequestFinalStatus.SUCCEEDED,
    )

    with pytest.raises(ValueError, match="accepted status"):
        store.save_accepted(record)


def test_request_metadata_store_raises_for_unknown_trace_id() -> None:
    store = InMemoryRequestMetadataStore()

    with pytest.raises(KeyError, match="tr_missing"):
        store.mark_succeeded("tr_missing")


def test_request_metadata_postgresql_schema_preserves_trace_lookup_contract() -> None:
    normalized_sql = " ".join(REQUEST_METADATA_TABLE_SQL.split())

    assert REQUEST_METADATA_TABLE == "chatbi_request_metadata"
    assert "CREATE TABLE IF NOT EXISTS chatbi_request_metadata" in normalized_sql
    assert "trace_id TEXT PRIMARY KEY" in normalized_sql
    assert "request_id TEXT NOT NULL" in normalized_sql
    assert "status TEXT NOT NULL CHECK" in normalized_sql
    assert "'accepted', 'succeeded', 'failed'" in normalized_sql
    assert "idx_chatbi_request_metadata_request_id" in normalized_sql
    assert "idx_chatbi_request_metadata_user_session" in normalized_sql


def test_postgres_request_metadata_store_initializes_schema() -> None:
    connection = FakeRequestMetadataConnection()
    store = PostgresRequestMetadataStore(connection)

    store.initialize_schema()

    assert REQUEST_METADATA_TABLE_SQL in connection.commands[0][0]
    assert connection.commits == 1


def test_postgres_request_metadata_store_saves_accepted_request() -> None:
    connection: RequestMetadataConnection = FakeRequestMetadataConnection()
    store = PostgresRequestMetadataStore(connection)

    store.save_accepted(make_record())

    fake_connection = connection
    assert isinstance(fake_connection, FakeRequestMetadataConnection)
    sql, params = fake_connection.commands[0]
    assert "INSERT INTO chatbi_request_metadata" in sql
    assert "ON CONFLICT (trace_id) DO UPDATE" in sql
    assert params[:8] == (
        "tr_12345678",
        "req_12345678",
        "ses_12345678",
        "u_001",
        "business_user",
        "en",
        "Show revenue trend.",
        "accepted",
    )
    assert fake_connection.commits == 1


def test_postgres_request_metadata_store_loads_row_by_trace_id() -> None:
    accepted_at = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)
    finished_at = datetime(2026, 6, 23, 12, 1, tzinfo=timezone.utc)
    connection = FakeRequestMetadataConnection()
    connection.next_row = (
        "tr_12345678",
        "req_12345678",
        "ses_12345678",
        "u_001",
        "business_user",
        "en",
        "Show revenue trend.",
        "succeeded",
        accepted_at,
        finished_at,
        None,
    )
    store = PostgresRequestMetadataStore(connection)

    record = store.get("tr_12345678")

    assert record is not None
    assert record.trace_id == "tr_12345678"
    assert record.status is RequestFinalStatus.SUCCEEDED
    assert record.accepted_at == accepted_at
    assert record.finished_at == finished_at
    assert connection.commands[0][1] == ("tr_12345678",)


def test_postgres_request_metadata_store_marks_failed_and_returns_updated_record() -> None:
    accepted_at = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)
    connection = FakeRequestMetadataConnection()
    connection.next_row = (
        "tr_12345678",
        "req_12345678",
        "ses_12345678",
        "u_001",
        "business_user",
        "en",
        "DROP TABLE orders",
        "failed",
        accepted_at,
        datetime(2026, 6, 23, 12, 1, tzinfo=timezone.utc),
        "SQL_GUARDRAIL_BLOCKED",
    )
    store = PostgresRequestMetadataStore(connection)

    record = store.mark_failed("tr_12345678", error_code="SQL_GUARDRAIL_BLOCKED")

    update_sql, update_params = connection.commands[0]
    assert "UPDATE chatbi_request_metadata" in update_sql
    assert update_params[0] == "failed"
    assert update_params[2] == "SQL_GUARDRAIL_BLOCKED"
    assert update_params[3] == "tr_12345678"
    assert record.status is RequestFinalStatus.FAILED
    assert record.error_code == "SQL_GUARDRAIL_BLOCKED"


def test_psycopg_request_metadata_connection_adapts_cursor_fetchone() -> None:
    row = ("tr_12345678",)
    raw_connection = FakePsycopgConnection(row=row)
    connection = PsycopgRequestMetadataConnection(raw_connection)

    connection.execute("SELECT trace_id FROM chatbi_request_metadata WHERE trace_id = %s", ("tr_12345678",))
    fetched = connection.fetchone()
    connection.commit()

    assert fetched == row
    assert raw_connection.commands == [
        (
            "SELECT trace_id FROM chatbi_request_metadata WHERE trace_id = %s",
            ("tr_12345678",),
        )
    ]
    assert raw_connection.commits == 1


def test_postgres_store_factory_wraps_psycopg_connection() -> None:
    raw_connection = FakePsycopgConnection()
    store = postgres_request_metadata_store_from_psycopg(raw_connection)

    store.initialize_schema()

    assert REQUEST_METADATA_TABLE_SQL in raw_connection.commands[0][0]
    assert raw_connection.commits == 1


def test_build_request_metadata_store_uses_memory_when_database_url_is_missing() -> None:
    store = build_request_metadata_store(
        RuntimeConfig(
            database_url=None,
            redis_url=None,
            vector_store_url=None,
        )
    )

    assert isinstance(store, InMemoryRequestMetadataStore)


def test_build_request_metadata_store_uses_postgres_when_connector_is_provided() -> None:
    raw_connection = FakePsycopgConnection()
    seen_urls: list[str] = []

    def connect(database_url: str) -> FakePsycopgConnection:
        seen_urls.append(database_url)
        return raw_connection

    store = build_request_metadata_store(
        RuntimeConfig(
            database_url="postgresql://chatbi:test@localhost:5432/chatbi",
            redis_url=None,
            vector_store_url=None,
        ),
        connect=connect,
    )

    assert isinstance(store, PostgresRequestMetadataStore)
    assert seen_urls == ["postgresql://chatbi:test@localhost:5432/chatbi"]
    assert REQUEST_METADATA_TABLE_SQL in raw_connection.commands[0][0]
    assert raw_connection.commits == 1


def test_build_request_metadata_store_requires_connector_when_database_url_is_present() -> None:
    with pytest.raises(RuntimeError, match="no PostgreSQL connector"):
        build_request_metadata_store(
            RuntimeConfig(
                database_url="postgresql://chatbi:test@localhost:5432/chatbi",
                redis_url=None,
                vector_store_url=None,
            )
        )
