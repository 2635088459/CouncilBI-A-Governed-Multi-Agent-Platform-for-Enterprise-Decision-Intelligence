from time import perf_counter

from chatbi.api.models import metrics_catalog_payload
from chatbi.data_model import DataModelCatalog, MetricDefinition


def test_metrics_catalog_payload_p95_budget_for_one_hundred_metrics() -> None:
    catalog = DataModelCatalog(
        tables=(),
        metrics=tuple(
            MetricDefinition(
                name=f"metric_{index:03d}",
                sql_definition=f"SUM(table_{index}.amount)",
                source_tables=(f"table_{index}",),
                semantic_version="sem_v1",
            )
            for index in range(100)
        ),
    )
    elapsed_ms: list[float] = []

    for _ in range(30):
        started_at = perf_counter()
        payload = metrics_catalog_payload(catalog)
        elapsed_ms.append((perf_counter() - started_at) * 1000)
        assert len(payload) == 100

    p95_ms = sorted(elapsed_ms)[int(len(elapsed_ms) * 0.95) - 1]
    assert p95_ms <= 200
