from typing import Any, Mapping

from chatbi.core.contracts import Locale, UserRole
from chatbi.frontend.api_client import FrontendUserContext, MetricCatalogViewModel
from chatbi.frontend.catalog_state import CatalogPageStore


class FakeCatalogApiClient:
    def __init__(self) -> None:
        self.calls = 0

    def load_metric_catalog(self, context: FrontendUserContext) -> MetricCatalogViewModel:
        self.calls += 1
        return MetricCatalogViewModel(
            metrics=(
                _raw_metric(
                    name="revenue",
                    sql_definition="SUM(order_amount)",
                    source_tables=("orders",),
                    semantic_version="sem_v1",
                ),
                _raw_metric(
                    name="refund_rate",
                    sql_definition="SUM(refund_amount) / SUM(order_amount)",
                    source_tables=("refunds", "orders"),
                    semantic_version="sem_v1",
                ),
            )
        )


class ErrorCatalogApiClient(FakeCatalogApiClient):
    def load_metric_catalog(self, context: FrontendUserContext) -> MetricCatalogViewModel:
        raise ValueError("Catalog API failed.")


def test_load_catalog_stores_metric_definitions_and_selects_first_metric() -> None:
    api_client = FakeCatalogApiClient()
    store = CatalogPageStore(context=_context(), api_client=api_client)

    state = store.load_catalog()

    assert state.is_loading is False
    assert state.error_message is None
    assert [metric.name for metric in state.metrics] == ["revenue", "refund_rate"]
    assert state.selected_metric is not None
    assert state.selected_metric.name == "revenue"
    assert state.selected_metric.source_tables == ("orders",)
    assert api_client.calls == 1


def test_set_search_query_filters_metrics_by_name_sql_and_source_table() -> None:
    store = CatalogPageStore(context=_context(), api_client=FakeCatalogApiClient())
    store.load_catalog()

    by_name = store.set_search_query("refund").filtered_metrics
    by_sql = store.set_search_query("SUM(order_amount)").filtered_metrics
    by_source_table = store.set_search_query("orders").filtered_metrics

    assert [metric.name for metric in by_name] == ["refund_rate"]
    assert [metric.name for metric in by_sql] == ["revenue", "refund_rate"]
    assert [metric.name for metric in by_source_table] == ["revenue", "refund_rate"]


def test_select_metric_updates_selected_metric() -> None:
    store = CatalogPageStore(context=_context(), api_client=FakeCatalogApiClient())
    store.load_catalog()

    state = store.select_metric("refund_rate")

    assert state.error_message is None
    assert state.selected_metric is not None
    assert state.selected_metric.name == "refund_rate"
    assert state.selected_metric.semantic_version == "sem_v1"


def test_select_metric_reports_unknown_metric() -> None:
    store = CatalogPageStore(context=_context(), api_client=FakeCatalogApiClient())
    store.load_catalog()

    state = store.select_metric("unknown_metric")

    assert state.selected_metric is None
    assert state.error_message == "Metric was not found."


def test_load_catalog_preserves_existing_selection_when_metric_still_exists() -> None:
    store = CatalogPageStore(context=_context(), api_client=FakeCatalogApiClient())
    store.load_catalog()
    store.select_metric("refund_rate")

    state = store.load_catalog()

    assert state.selected_metric is not None
    assert state.selected_metric.name == "refund_rate"


def test_load_catalog_records_error_without_dropping_existing_metrics() -> None:
    working_store = CatalogPageStore(context=_context(), api_client=FakeCatalogApiClient())
    previous_state = working_store.load_catalog()
    error_store = CatalogPageStore(context=_context(), api_client=ErrorCatalogApiClient())
    error_store_state = error_store.load_catalog()

    assert previous_state.metrics[0].name == "revenue"
    assert error_store_state.metrics == ()
    assert error_store_state.error_message == "Catalog API failed."


def _context() -> FrontendUserContext:
    return FrontendUserContext(
        user_id="u_001",
        session_id="s_001",
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
        bearer_token="test-token",
    )


def _raw_metric(
    name: str,
    sql_definition: str,
    source_tables: tuple[str, ...],
    semantic_version: str,
) -> Mapping[str, Any]:
    return {
        "name": name,
        "sql_definition": sql_definition,
        "source_tables": source_tables,
        "semantic_version": semantic_version,
    }
