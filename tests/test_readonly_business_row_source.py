from chatbi.agents import ReadOnlyBusinessRowSource
from chatbi.files import PostgresQueryContext
from chatbi.governance import ReadOnlyQueryExecutor


class _FakeColumn:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeCursor:
    def __init__(self, columns: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
        self.description = tuple(_FakeColumn(name) for name in columns)
        self._rows = rows

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        return self._rows[:size]


class _FakeConnection:
    def __init__(self, sql_to_result: dict[str, tuple[tuple[str, ...], list[tuple[object, ...]]]]) -> None:
        self._sql_to_result = sql_to_result
        self.executed_sql: list[str] = []

    def execute(self, sql: str) -> _FakeCursor:
        self.executed_sql.append(sql)
        columns, rows = self._sql_to_result[sql]
        return _FakeCursor(columns, rows)

    def close(self) -> None:
        pass


def _context(**overrides: object) -> PostgresQueryContext:
    fields: dict[str, object] = dict(
        table_name="revenue_by_month", columns=("month", "revenue"), max_rows=500
    )
    fields.update(overrides)
    return PostgresQueryContext(**fields)  # type: ignore[arg-type]


def test_fetch_rows_selects_only_the_context_columns_from_the_business_schema() -> None:
    context = _context()
    expected_sql = 'SELECT "month", "revenue" FROM business."revenue_by_month" LIMIT 501'
    connection = _FakeConnection(
        {expected_sql: (("month", "revenue"), [("2026-01", 150.0), ("2026-02", 250.0)])}
    )
    source = ReadOnlyBusinessRowSource(
        ReadOnlyQueryExecutor(lambda _url: connection), "postgresql://readonly"
    )

    rows = source.fetch_rows(context)

    assert connection.executed_sql == [expected_sql]
    assert rows == (
        {"month": "2026-01", "revenue": 150.0},
        {"month": "2026-02", "revenue": 250.0},
    )


def test_fetch_rows_returns_empty_tuple_when_readonly_url_is_not_configured() -> None:
    source = ReadOnlyBusinessRowSource(
        ReadOnlyQueryExecutor(lambda _url: _FakeConnection({})), None
    )

    rows = source.fetch_rows(_context())

    assert rows == ()


def test_fetch_rows_returns_empty_tuple_when_execution_fails() -> None:
    class _BrokenConnection:
        def execute(self, sql: str) -> _FakeCursor:
            raise RuntimeError("boom")

        def close(self) -> None:
            pass

    source = ReadOnlyBusinessRowSource(
        ReadOnlyQueryExecutor(lambda _url: _BrokenConnection()), "postgresql://readonly"
    )

    rows = source.fetch_rows(_context())

    assert rows == ()
