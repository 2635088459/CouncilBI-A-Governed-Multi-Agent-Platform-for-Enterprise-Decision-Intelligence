from datetime import date
from decimal import Decimal
from typing import Any

from chatbi.governance import ReadOnlyQueryExecutor, ReadOnlyQueryStatus


class FakeReadOnlyCursor:
    def __init__(
        self,
        *,
        description: tuple[tuple[Any, ...], ...],
        rows: list[tuple[Any, ...]],
    ) -> None:
        self.description = description
        self.rows = rows
        self.fetch_sizes: list[int] = []

    def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
        self.fetch_sizes.append(size)
        return self.rows[:size]


class FakeReadOnlyQueryConnection:
    def __init__(
        self,
        *,
        cursor: FakeReadOnlyCursor | None = None,
        execution_error: Exception | None = None,
    ) -> None:
        self.cursor = cursor or FakeReadOnlyCursor(description=(), rows=[])
        self.execution_error = execution_error
        self.executed_sql: list[str] = []
        self.closed = False

    def execute(self, sql: str) -> FakeReadOnlyCursor:
        self.executed_sql.append(sql)
        if self.execution_error is not None:
            raise self.execution_error
        return self.cursor

    def close(self) -> None:
        self.closed = True


def test_readonly_query_executor_returns_table_result_from_select_rows() -> None:
    cursor = FakeReadOnlyCursor(
        description=(("month",), ("revenue",)),
        rows=[("2026-01", 1000.0), ("2026-02", 1120.0)],
    )
    connection = FakeReadOnlyQueryConnection(cursor=cursor)
    executor = ReadOnlyQueryExecutor(lambda database_url: connection, max_rows=100)

    result = executor.execute(
        "postgresql://chatbi_readonly:test@db:5432/chatbi",
        "SELECT month, revenue FROM revenue_by_month LIMIT 100",
    )

    assert result.status is ReadOnlyQueryStatus.SUCCEEDED
    assert result.succeeded is True
    assert result.table_result is not None
    assert result.table_result.columns == ("month", "revenue")
    assert result.table_result.rows == (
        {"month": "2026-01", "revenue": 1000.0},
        {"month": "2026-02", "revenue": 1120.0},
    )
    assert cursor.fetch_sizes == [100]
    assert connection.executed_sql == ["SELECT month, revenue FROM revenue_by_month LIMIT 100"]
    assert connection.closed is True


def test_readonly_query_executor_caps_fetched_rows() -> None:
    cursor = FakeReadOnlyCursor(
        description=(("id",),),
        rows=[(1,), (2,), (3,)],
    )
    connection = FakeReadOnlyQueryConnection(cursor=cursor)
    executor = ReadOnlyQueryExecutor(lambda database_url: connection, max_rows=2)

    result = executor.execute(
        "postgresql://chatbi_readonly:test@db:5432/chatbi",
        "SELECT id FROM orders LIMIT 100",
    )

    assert result.table_result is not None
    assert result.table_result.rows == ({"id": 1}, {"id": 2})
    assert cursor.fetch_sizes == [2]


def test_readonly_query_executor_converts_database_values_to_json_safe_rows() -> None:
    cursor = FakeReadOnlyCursor(
        description=(("month",), ("revenue",)),
        rows=[(date(2026, 1, 1), Decimal("1000.50"))],
    )
    connection = FakeReadOnlyQueryConnection(cursor=cursor)
    executor = ReadOnlyQueryExecutor(lambda database_url: connection)

    result = executor.execute(
        "postgresql://chatbi_readonly:test@db:5432/chatbi",
        "SELECT month, revenue FROM revenue_by_month LIMIT 100",
    )

    assert result.table_result is not None
    assert result.table_result.rows == ({"month": "2026-01-01", "revenue": 1000.5},)


def test_readonly_query_executor_reports_missing_database_url() -> None:
    executor = ReadOnlyQueryExecutor(
        lambda database_url: FakeReadOnlyQueryConnection(),
    )

    result = executor.execute(None, "SELECT 1")

    assert result.status is ReadOnlyQueryStatus.NOT_CONFIGURED
    assert result.succeeded is False
    assert result.table_result is None
    assert result.message == "Read-only database URL is not configured."


def test_readonly_query_executor_does_not_echo_plaintext_credentials_on_failure() -> None:
    secret_url = "postgresql://chatbi_readonly:super_secret@db:5432/chatbi"
    connection = FakeReadOnlyQueryConnection(
        execution_error=RuntimeError(f"failed for {secret_url}")
    )
    executor = ReadOnlyQueryExecutor(lambda database_url: connection)

    result = executor.execute(secret_url, "SELECT 1")

    assert result.status is ReadOnlyQueryStatus.EXECUTION_FAILED
    assert result.table_result is None
    assert result.message == "Read-only query execution failed."
    assert "super_secret" not in repr(result)
    assert secret_url not in repr(result)
    assert connection.closed is True


def test_readonly_query_executor_rejects_non_positive_max_rows() -> None:
    try:
        ReadOnlyQueryExecutor(lambda database_url: FakeReadOnlyQueryConnection(), max_rows=0)
    except ValueError as exc:
        assert str(exc) == "max_rows must be greater than 0"
    else:
        raise AssertionError("Expected max_rows validation to fail.")
