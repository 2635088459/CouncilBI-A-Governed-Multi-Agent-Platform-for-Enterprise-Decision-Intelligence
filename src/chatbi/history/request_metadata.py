"""Request metadata persistence for the v2 architecture slice.

The Overall Architecture spec requires accepted requests and final status to be
selectable by ``trace_id``. This module models that requirement without tying
the rest of the code to PostgreSQL yet. The in-memory implementation is the
early TDD version; a database-backed implementation can keep the same method
shape later.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Callable, Protocol, Sequence, cast

from chatbi.core.contracts import Locale, UserRole
from chatbi.core.runtime_config import RuntimeConfig


class RequestFinalStatus(StrEnum):
    ACCEPTED = "accepted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


REQUEST_METADATA_TABLE = "chatbi_request_metadata"

REQUEST_METADATA_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS chatbi_request_metadata (
    trace_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('business_user', 'analyst', 'admin')),
    locale TEXT NOT NULL CHECK (locale IN ('en', 'zh-CN')),
    question TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('accepted', 'succeeded', 'failed')),
    accepted_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NULL,
    error_code TEXT NULL,
    org_id TEXT NOT NULL DEFAULT 'org_legacy'
);

ALTER TABLE chatbi_request_metadata
    ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT 'org_legacy';

CREATE INDEX IF NOT EXISTS idx_chatbi_request_metadata_request_id
    ON chatbi_request_metadata (request_id);

CREATE INDEX IF NOT EXISTS idx_chatbi_request_metadata_user_session
    ON chatbi_request_metadata (user_id, session_id);

CREATE INDEX IF NOT EXISTS idx_chatbi_request_metadata_org_trace
    ON chatbi_request_metadata (org_id, trace_id);
""".strip()


class RequestMetadataStore(Protocol):
    def save_accepted(self, record: "RequestMetadataRecord") -> None:
        """Persist a request as soon as the Backend API accepts it."""
        ...

    def mark_succeeded(self, trace_id: str) -> "RequestMetadataRecord":
        """Persist the final successful status for one trace id."""
        ...

    def mark_failed(self, trace_id: str, error_code: str) -> "RequestMetadataRecord":
        """Persist the final failed status for one trace id."""
        ...

    def get(self, trace_id: str) -> "RequestMetadataRecord | None":
        """Load request metadata by trace id."""
        ...


class RequestMetadataConnection(Protocol):
    def execute(self, sql: str, params: Sequence[object] = ()) -> Any:
        """Execute one SQL statement with positional parameters."""
        ...

    def fetchone(self) -> Sequence[object] | None:
        """Return one row from the latest SELECT statement."""
        ...

    def commit(self) -> None:
        """Commit the current transaction."""
        ...


class PsycopgRequestMetadataConnection:
    """Adapt a psycopg-style connection to RequestMetadataConnection.

    Psycopg connections usually return a cursor from ``execute``; our store uses
    a tiny connection protocol with ``execute`` followed by ``fetchone``. This
    adapter keeps that cursor so the repository code stays independent from the
    database driver.
    """

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


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class RequestMetadataRecord:
    trace_id: str
    request_id: str
    session_id: str
    user_id: str
    role: UserRole
    locale: Locale
    question: str
    org_id: str = "org_legacy"
    status: RequestFinalStatus = RequestFinalStatus.ACCEPTED
    accepted_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None
    error_code: str | None = None


class InMemoryRequestMetadataStore:
    """Small repository for request metadata, keyed by trace id."""

    def __init__(self) -> None:
        self._records: dict[str, RequestMetadataRecord] = {}

    def save_accepted(self, record: RequestMetadataRecord) -> None:
        if record.status is not RequestFinalStatus.ACCEPTED:
            raise ValueError("save_accepted expects a record with accepted status.")
        self._records[record.trace_id] = record

    def mark_succeeded(self, trace_id: str) -> RequestMetadataRecord:
        record = self._require_record(trace_id)
        updated = replace(
            record,
            status=RequestFinalStatus.SUCCEEDED,
            finished_at=utc_now(),
            error_code=None,
        )
        self._records[trace_id] = updated
        return updated

    def mark_failed(self, trace_id: str, error_code: str) -> RequestMetadataRecord:
        record = self._require_record(trace_id)
        updated = replace(
            record,
            status=RequestFinalStatus.FAILED,
            finished_at=utc_now(),
            error_code=error_code,
        )
        self._records[trace_id] = updated
        return updated

    def get(self, trace_id: str) -> RequestMetadataRecord | None:
        return self._records.get(trace_id)

    def list_all(self) -> tuple[RequestMetadataRecord, ...]:
        return tuple(self._records.values())

    def _require_record(self, trace_id: str) -> RequestMetadataRecord:
        record = self._records.get(trace_id)
        if record is None:
            raise KeyError(f"Request metadata was not found for trace_id={trace_id}.")
        return record


class PostgresRequestMetadataStore:
    """DB-API style PostgreSQL implementation of RequestMetadataStore.

    This class is intentionally driver-light. It needs a tiny connection object
    with ``execute``, ``fetchone``, and ``commit`` so tests can use a fake
    connection and production can later pass a psycopg-backed adapter.
    """

    _columns = (
        "trace_id",
        "request_id",
        "session_id",
        "user_id",
        "role",
        "locale",
        "question",
        "status",
        "accepted_at",
        "finished_at",
        "error_code",
        "org_id",
    )

    def __init__(self, connection: RequestMetadataConnection) -> None:
        self._connection = connection

    def initialize_schema(self) -> None:
        self._connection.execute(REQUEST_METADATA_TABLE_SQL)
        self._connection.commit()

    def save_accepted(self, record: RequestMetadataRecord) -> None:
        if record.status is not RequestFinalStatus.ACCEPTED:
            raise ValueError("save_accepted expects a record with accepted status.")
        self._connection.execute(
            """
            INSERT INTO chatbi_request_metadata (
                trace_id,
                request_id,
                session_id,
                user_id,
                role,
                locale,
                question,
                status,
                accepted_at,
                finished_at,
                error_code,
                org_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (trace_id) DO UPDATE SET
                request_id = EXCLUDED.request_id,
                session_id = EXCLUDED.session_id,
                user_id = EXCLUDED.user_id,
                role = EXCLUDED.role,
                locale = EXCLUDED.locale,
                question = EXCLUDED.question,
                status = EXCLUDED.status,
                accepted_at = EXCLUDED.accepted_at,
                finished_at = EXCLUDED.finished_at,
                error_code = EXCLUDED.error_code,
                org_id = EXCLUDED.org_id
            """,
            self._record_params(record),
        )
        self._connection.commit()

    def mark_succeeded(self, trace_id: str) -> RequestMetadataRecord:
        return self._mark_final(
            trace_id=trace_id,
            status=RequestFinalStatus.SUCCEEDED,
            error_code=None,
        )

    def mark_failed(self, trace_id: str, error_code: str) -> RequestMetadataRecord:
        return self._mark_final(
            trace_id=trace_id,
            status=RequestFinalStatus.FAILED,
            error_code=error_code,
        )

    def get(self, trace_id: str) -> RequestMetadataRecord | None:
        self._connection.execute(
            f"""
            SELECT {", ".join(self._columns)}
            FROM chatbi_request_metadata
            WHERE trace_id = %s
            """,
            (trace_id,),
        )
        row = self._connection.fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def _mark_final(
        self,
        trace_id: str,
        status: RequestFinalStatus,
        error_code: str | None,
    ) -> RequestMetadataRecord:
        finished_at = utc_now()
        self._connection.execute(
            """
            UPDATE chatbi_request_metadata
            SET status = %s,
                finished_at = %s,
                error_code = %s
            WHERE trace_id = %s
            """,
            (status.value, finished_at, error_code, trace_id),
        )
        self._connection.commit()
        record = self.get(trace_id)
        if record is None:
            raise KeyError(f"Request metadata was not found for trace_id={trace_id}.")
        return record

    def _record_params(self, record: RequestMetadataRecord) -> tuple[object, ...]:
        return (
            record.trace_id,
            record.request_id,
            record.session_id,
            record.user_id,
            record.role.value,
            record.locale.value,
            record.question,
            record.status.value,
            record.accepted_at,
            record.finished_at,
            record.error_code,
            record.org_id,
        )

    def _row_to_record(self, row: Sequence[object]) -> RequestMetadataRecord:
        if len(row) not in {len(self._columns), len(self._columns) - 1}:
            raise ValueError("request metadata row has unexpected column count.")
        return RequestMetadataRecord(
            trace_id=cast(str, row[0]),
            request_id=cast(str, row[1]),
            session_id=cast(str, row[2]),
            user_id=cast(str, row[3]),
            role=UserRole(cast(str, row[4])),
            locale=Locale(cast(str, row[5])),
            question=cast(str, row[6]),
            status=RequestFinalStatus(cast(str, row[7])),
            accepted_at=cast(datetime, row[8]),
            finished_at=cast(datetime | None, row[9]),
            error_code=cast(str | None, row[10]),
            org_id=cast(str, row[11]) if len(row) == len(self._columns) else "org_legacy",
        )


def postgres_request_metadata_store_from_psycopg(connection: Any) -> PostgresRequestMetadataStore:
    """Build the PostgreSQL store from a psycopg-style connection object."""

    return PostgresRequestMetadataStore(PsycopgRequestMetadataConnection(connection))


def connect_psycopg(database_url: str) -> Any:
    """Open a psycopg connection without making psycopg a hard import at module load."""

    psycopg = importlib.import_module("psycopg")
    return psycopg.connect(database_url)


def build_request_metadata_store(
    runtime_config: RuntimeConfig,
    connect: Callable[[str], Any] | None = None,
    initialize_schema: bool = True,
) -> RequestMetadataStore:
    """Choose the request metadata store for the current runtime.

    Local demos can run without PostgreSQL and use the in-memory store. A
    deployable runtime passes ``DATABASE_URL`` plus a connector function, and
    receives a PostgreSQL-backed store.
    """

    if runtime_config.database_url is None:
        return InMemoryRequestMetadataStore()

    if connect is None:
        raise RuntimeError(
            "DATABASE_URL is configured, but no PostgreSQL connector was provided."
        )

    store = postgres_request_metadata_store_from_psycopg(connect(runtime_config.database_url))
    if initialize_schema:
        store.initialize_schema()
    return store
