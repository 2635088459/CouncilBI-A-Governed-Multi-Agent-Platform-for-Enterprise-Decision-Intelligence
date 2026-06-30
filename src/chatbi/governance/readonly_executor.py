"""Read-only SQL execution boundary for governed queries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Callable, Protocol

from chatbi.core.contracts import TableResult


class ReadOnlyQueryStatus(StrEnum):
    SUCCEEDED = "succeeded"
    NOT_CONFIGURED = "not_configured"
    EXECUTION_FAILED = "execution_failed"


@dataclass(frozen=True, slots=True)
class ReadOnlyQueryResult:
    status: ReadOnlyQueryStatus
    table_result: TableResult | None = None
    message: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is ReadOnlyQueryStatus.SUCCEEDED


class ReadOnlyQueryCursor(Protocol):
    description: tuple[tuple[Any, ...], ...] | list[tuple[Any, ...]] | None

    def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
        ...


class ReadOnlyQueryConnection(Protocol):
    def execute(self, sql: str) -> ReadOnlyQueryCursor:
        ...

    def close(self) -> None:
        ...


class ReadOnlyQueryExecutor:
    """Execute already-governed SELECT SQL through a read-only database URL."""

    def __init__(
        self,
        connect: Callable[[str], ReadOnlyQueryConnection],
        *,
        max_rows: int = 100,
    ) -> None:
        if max_rows <= 0:
            raise ValueError("max_rows must be greater than 0")
        self._connect = connect
        self._max_rows = max_rows

    def execute(self, database_url: str | None, sql_text: str) -> ReadOnlyQueryResult:
        if database_url is None or not database_url.strip():
            return ReadOnlyQueryResult(
                status=ReadOnlyQueryStatus.NOT_CONFIGURED,
                message="Read-only database URL is not configured.",
            )

        connection: ReadOnlyQueryConnection | None = None
        try:
            connection = self._connect(database_url)
            cursor = connection.execute(sql_text)
            columns = self._column_names(cursor)
            rows = self._rows(cursor, columns)
            return ReadOnlyQueryResult(
                status=ReadOnlyQueryStatus.SUCCEEDED,
                table_result=TableResult(columns=columns, rows=rows),
            )
        except Exception:
            return ReadOnlyQueryResult(
                status=ReadOnlyQueryStatus.EXECUTION_FAILED,
                message="Read-only query execution failed.",
            )
        finally:
            self._close_quietly(connection)

    def _column_names(self, cursor: ReadOnlyQueryCursor) -> tuple[str, ...]:
        if cursor.description is None:
            return ()
        return tuple(self._column_name(column) for column in cursor.description)

    def _column_name(self, column: Any) -> str:
        name = getattr(column, "name", None)
        if name is not None:
            return str(name)
        return str(column[0])

    def _rows(
        self,
        cursor: ReadOnlyQueryCursor,
        columns: tuple[str, ...],
    ) -> tuple[dict[str, Any], ...]:
        rows = cursor.fetchmany(self._max_rows)
        return tuple(
            dict(zip(columns, (self._json_safe_value(value) for value in row), strict=False))
            for row in rows
        )

    def _json_safe_value(self, value: Any) -> Any:
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, datetime | date):
            return value.isoformat()
        return value

    def _close_quietly(self, connection: ReadOnlyQueryConnection | None) -> None:
        if connection is None:
            return
        try:
            connection.close()
        except Exception:
            return
