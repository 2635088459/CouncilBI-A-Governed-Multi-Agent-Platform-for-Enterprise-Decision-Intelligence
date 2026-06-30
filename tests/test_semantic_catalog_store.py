from typing import Sequence

from chatbi.semantic.catalog import MetricStatus
from chatbi.semantic.catalog_store import PostgresSemanticCatalogStore, SemanticCatalogConnection


class FakeSemanticCatalogConnection:
    def __init__(self) -> None:
        self.commands: list[tuple[str, tuple[object, ...]]] = []
        self.rows: tuple[tuple[object, ...], ...] = (
            (
                "revenue",
                "Total paid order amount.",
                "orders",
                "SUM(orders.order_amount) WHERE orders.status = 'paid'",
                "sem_v1",
                ("sales amount", "paid order amount"),
                "analytics",
                "active",
            ),
        )

    def execute(self, sql: str, params: Sequence[object] = ()) -> object:
        self.commands.append((sql, tuple(params)))
        return object()

    def fetchall(self) -> Sequence[Sequence[object]]:
        return self.rows


def test_postgres_semantic_catalog_store_loads_metrics_by_semantic_version() -> None:
    connection: SemanticCatalogConnection = FakeSemanticCatalogConnection()
    store = PostgresSemanticCatalogStore(connection)

    catalog = store.load_catalog("sem_v1")
    revenue = catalog.resolve_metric("sales amount")

    assert isinstance(connection, FakeSemanticCatalogConnection)
    sql, params = connection.commands[0]
    assert "FROM semantic.metrics" in sql
    assert "WHERE semantic_version_id = %s" in sql
    assert params == ("sem_v1",)
    assert revenue is not None
    assert revenue.metric_id == "revenue"
    assert revenue.formula == "SUM(orders.order_amount) WHERE orders.status = 'paid'"
    assert revenue.owner == "analytics"
    assert revenue.status is MetricStatus.ACTIVE
    assert revenue.semantic_version_id == "sem_v1"
