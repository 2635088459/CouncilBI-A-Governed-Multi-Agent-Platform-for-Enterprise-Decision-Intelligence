"""PostgreSQL-backed semantic catalog loading."""

from __future__ import annotations

from typing import Protocol, Sequence, cast

from chatbi.semantic.catalog import MetricDefinition, MetricStatus, SemanticCatalog


class SemanticCatalogConnection(Protocol):
    def execute(self, sql: str, params: Sequence[object] = ()) -> object:
        ...

    def fetchall(self) -> Sequence[Sequence[object]]:
        ...


class PostgresSemanticCatalogStore:
    """Load governed metric definitions from the semantic schema."""

    def __init__(self, connection: SemanticCatalogConnection) -> None:
        self._connection = connection

    def load_catalog(self, semantic_version_id: str = "sem_v1") -> SemanticCatalog:
        self._connection.execute(
            """
            SELECT
                metric_id,
                description,
                table_name,
                formula,
                semantic_version_id,
                synonyms,
                owner,
                status
            FROM semantic.metrics
            WHERE semantic_version_id = %s
            ORDER BY metric_id ASC
            """,
            (semantic_version_id,),
        )
        rows = self._connection.fetchall()
        metrics = tuple(self._metric_from_row(row) for row in rows)
        return SemanticCatalog(metrics=metrics)

    def _metric_from_row(self, row: Sequence[object]) -> MetricDefinition:
        synonyms_value = row[5]
        synonyms = tuple(cast(Sequence[str], synonyms_value or ()))
        return MetricDefinition(
            name=cast(str, row[0]),
            description=cast(str, row[1]),
            table_name=cast(str, row[2]),
            sql_expression=cast(str, row[3]),
            semantic_version=cast(str, row[4]),
            synonyms=synonyms,
            owner=cast(str, row[6]),
            status=MetricStatus(cast(str, row[7])),
        )
