from chatbi.core.contracts import Locale, UserRole
from chatbi.frontend.api_client import FrontendUserContext
from chatbi.frontend.catalog_state import CatalogPageState, MetricDefinitionViewModel
from chatbi.frontend.component_props import ComponentId, build_catalog_page_props


def test_build_catalog_page_props_renders_empty_state() -> None:
    state = CatalogPageState(context=_context(locale=Locale.ZH_CN))

    props = build_catalog_page_props(state, Locale.ZH_CN)

    assert props.title == "指标目录"
    assert props.empty_state == "暂无可用指标。"
    assert props.search.placeholder == "搜索指标..."
    assert props.metrics == ()
    assert props.selected_metric is None
    assert props.tab_order == (ComponentId.CATALOG_SEARCH,)


def test_build_catalog_page_props_renders_filtered_metrics_and_selection() -> None:
    state = CatalogPageState(
        context=_context(),
        metrics=(
            _metric(
                name="revenue",
                sql_definition="SUM(order_amount)",
                source_tables=("orders",),
            ),
            _metric(
                name="refund_rate",
                sql_definition="SUM(refund_amount) / SUM(order_amount)",
                source_tables=("refunds", "orders"),
            ),
        ),
        search_query="refund",
        selected_metric_name="refund_rate",
    )

    props = build_catalog_page_props(state, Locale.EN)

    assert props.title == "Metric Catalog"
    assert props.search.value == "refund"
    assert [metric.name for metric in props.metrics] == ["refund_rate"]
    assert props.metrics[0].is_selected is True
    assert props.selected_metric is not None
    assert props.selected_metric.title == "Selected metric"
    assert props.selected_metric.name == "refund_rate"
    assert props.selected_metric.source_tables_label == "Source tables: refunds, orders"
    assert props.selected_metric.semantic_version_label == "Semantic version: sem_v1"
    assert props.tab_order == (
        ComponentId.CATALOG_SEARCH,
        ComponentId.CATALOG_LIST,
        ComponentId.CATALOG_DETAIL,
    )


def test_build_catalog_page_props_tracks_loading_and_error_message() -> None:
    state = CatalogPageState(
        context=_context(),
        is_loading=True,
        error_message="Catalog API failed.",
    )

    props = build_catalog_page_props(state, Locale.EN)

    assert props.is_loading is True
    assert props.error_message == "Catalog API failed."


def _context(locale: Locale = Locale.EN) -> FrontendUserContext:
    return FrontendUserContext(
        user_id="u_001",
        session_id="s_001",
        locale=locale,
        role=UserRole.BUSINESS_USER,
        bearer_token="test-token",
    )


def _metric(
    name: str,
    sql_definition: str,
    source_tables: tuple[str, ...],
) -> MetricDefinitionViewModel:
    return MetricDefinitionViewModel(
        name=name,
        sql_definition=sql_definition,
        source_tables=source_tables,
        semantic_version="sem_v1",
    )
