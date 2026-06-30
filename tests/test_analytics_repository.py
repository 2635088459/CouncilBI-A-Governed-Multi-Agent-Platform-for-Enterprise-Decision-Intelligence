from collections.abc import Sequence
from typing import Any

from chatbi.analytics import (
    AnalyticsGrain,
    AnalyticsRequest,
    AnalyticsService,
)
from chatbi.analytics_postgres_rows import analytics_record_to_row
from chatbi.analytics_repository import (
    InMemoryAnalyticsRepository,
    PostgresAnalyticsRepository,
)


class FakeAnalyticsConnection:
    def __init__(self) -> None:
        self.statements: list[tuple[str, Sequence[object]]] = []
        self.fetchone_result: Sequence[object] | None = None
        self.commit_count = 0

    def execute(self, sql: str, params: Sequence[object] = ()) -> Any:
        self.statements.append((sql, params))
        return self

    def fetchone(self) -> Sequence[object] | None:
        return self.fetchone_result

    def commit(self) -> None:
        self.commit_count += 1


def test_in_memory_analytics_repository_persists_result_by_trace_id() -> None:
    repository = InMemoryAnalyticsRepository()
    service = AnalyticsService(repository)
    result = service.analyze(_request("tr_memory_repo"))

    saved = repository.result_by_trace_id("tr_memory_repo")

    assert saved is not None
    assert saved.result == result
    assert saved.metric_id == "revenue"


def test_postgres_analytics_repository_initializes_schema() -> None:
    connection = FakeAnalyticsConnection()
    repository = PostgresAnalyticsRepository(connection)

    repository.initialize_schema()

    assert "CREATE TABLE IF NOT EXISTS analytics.results" in connection.statements[0][0]
    assert connection.commit_count == 1


def test_postgres_analytics_repository_saves_and_reads_by_trace_id() -> None:
    memory_repository = InMemoryAnalyticsRepository()
    service = AnalyticsService(memory_repository)
    service.analyze(_request("tr_postgres_repo"))
    record = memory_repository.result_by_trace_id("tr_postgres_repo")
    assert record is not None

    row = analytics_record_to_row(record)
    connection = FakeAnalyticsConnection()
    connection.fetchone_result = (
        row["trace_id"],
        row["metric_id"],
        row["semantic_version_id"],
        row["parameters"],
        row["anomaly_points"],
        row["forecast_points"],
        row["confidence_interval"],
        row["quality_warnings"],
        row["method"],
        row["model_version"],
        row["explanation"],
    )
    repository = PostgresAnalyticsRepository(connection)

    repository.save_result(record)
    restored = repository.result_by_trace_id("tr_postgres_repo")

    assert "INSERT INTO analytics.results" in connection.statements[0][0]
    assert "ON CONFLICT (trace_id)" in connection.statements[0][0]
    assert connection.statements[1][1] == ("tr_postgres_repo",)
    assert restored == record
    assert connection.commit_count == 1


def _request(trace_id: str) -> AnalyticsRequest:
    return AnalyticsRequest(
        trace_id=trace_id,
        metric_id="revenue",
        semantic_version_id="sem_v2",
        time_column="date",
        value_column="revenue",
        grain=AnalyticsGrain.DAY,
        rows=(
            {"date": "2026-06-01", "revenue": 100.0},
            {"date": "2026-06-02", "revenue": 105.0},
            {"date": "2026-06-03", "revenue": 110.0},
            {"date": "2026-06-04", "revenue": 115.0},
        ),
    )
