"""Persistence boundary for analytics v2 results.

The production target is PostgreSQL, but tests and local teaching flows use the
in-memory implementation. Both expose the same tiny behavior: save by trace id,
then read by trace id.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from chatbi.analytics import AnalyticsRecord, AnalyticsRepository
from chatbi.analytics_postgres_rows import (
    ANALYTICS_V2_TABLES_SQL,
    analytics_record_from_row,
    analytics_record_to_row,
)


def _empty_records() -> dict[str, AnalyticsRecord]:
    return {}


@dataclass(slots=True)
class InMemoryAnalyticsRepository(AnalyticsRepository):
    """Small repository shaped like the future analytics_results table."""

    _records_by_trace_id: dict[str, AnalyticsRecord] = field(default_factory=_empty_records)

    def save_result(self, record: AnalyticsRecord) -> None:
        if not record.trace_id.strip():
            raise ValueError("trace_id is required")
        self._records_by_trace_id[record.trace_id] = record

    def result_by_trace_id(self, trace_id: str) -> AnalyticsRecord | None:
        return self._records_by_trace_id.get(trace_id)


class AnalyticsPostgresConnection(Protocol):
    """Tiny DB-API style connection shape used by PostgresAnalyticsRepository."""

    def execute(self, sql: str, params: Sequence[object] = ()) -> Any:
        ...

    def fetchone(self) -> Sequence[object] | None:
        ...

    def commit(self) -> None:
        ...


class PsycopgAnalyticsConnection:
    """Adapt a psycopg-style connection to the small analytics protocol."""

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


class PostgresAnalyticsRepository(AnalyticsRepository):
    """PostgreSQL implementation of the analytics result repository."""

    _columns = (
        "trace_id",
        "org_id",
        "user_id",
        "metric_id",
        "semantic_version_id",
        "parameters",
        "anomaly_points",
        "forecast_points",
        "confidence_interval",
        "quality_warnings",
        "method",
        "model_version",
        "explanation",
    )

    def __init__(self, connection: AnalyticsPostgresConnection) -> None:
        self._connection = connection

    def initialize_schema(self) -> None:
        self._connection.execute(ANALYTICS_V2_TABLES_SQL)
        self._connection.commit()

    def save_result(self, record: AnalyticsRecord) -> None:
        row = analytics_record_to_row(record)
        self._connection.execute(
            """
            INSERT INTO analytics.results (
                trace_id,
                org_id,
                user_id,
                metric_id,
                semantic_version_id,
                parameters,
                anomaly_points,
                forecast_points,
                confidence_interval,
                quality_warnings,
                method,
                model_version,
                explanation
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (trace_id) DO UPDATE SET
                org_id = EXCLUDED.org_id,
                user_id = EXCLUDED.user_id,
                metric_id = EXCLUDED.metric_id,
                semantic_version_id = EXCLUDED.semantic_version_id,
                parameters = EXCLUDED.parameters,
                anomaly_points = EXCLUDED.anomaly_points,
                forecast_points = EXCLUDED.forecast_points,
                confidence_interval = EXCLUDED.confidence_interval,
                quality_warnings = EXCLUDED.quality_warnings,
                method = EXCLUDED.method,
                model_version = EXCLUDED.model_version,
                explanation = EXCLUDED.explanation
            """,
            (
                row["trace_id"],
                row["org_id"],
                row["user_id"],
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
            ),
        )
        self._connection.commit()

    def result_by_trace_id(self, trace_id: str) -> AnalyticsRecord | None:
        self._connection.execute(
            f"""
            SELECT {", ".join(self._columns)}
            FROM analytics.results
            WHERE trace_id = %s
            """,
            (trace_id,),
        )
        row = self._connection.fetchone()
        if row is None:
            return None
        return analytics_record_from_row(_row_mapping(self._columns, row))


def postgres_analytics_repository_from_psycopg(connection: Any) -> PostgresAnalyticsRepository:
    """Build a PostgreSQL analytics repository from a psycopg-style connection."""

    return PostgresAnalyticsRepository(PsycopgAnalyticsConnection(connection))


def _row_mapping(columns: tuple[str, ...], row: Sequence[object]) -> dict[str, object]:
    if len(row) == len(columns):
        return dict(zip(columns, row, strict=True))
    legacy_columns = tuple(column for column in columns if column not in {"org_id", "user_id"})
    if len(row) == len(legacy_columns):
        mapping = dict(zip(legacy_columns, row, strict=True))
        mapping["org_id"] = "org_legacy"
        mapping["user_id"] = "user_legacy"
        return mapping
    else:
        raise ValueError("Analytics PostgreSQL row has unexpected column count.")
