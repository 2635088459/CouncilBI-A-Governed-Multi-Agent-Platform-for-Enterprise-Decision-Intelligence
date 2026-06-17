from chatbi.semantic.catalog import MetricDefinition, SemanticCatalog, build_default_catalog


def test_catalog_resolves_revenue_to_canonical_metric() -> None:
    catalog = build_default_catalog()

    metric = catalog.resolve_metric("revenue")

    assert metric is not None
    assert metric.name == "revenue"
    assert metric.semantic_version == "sem_v1"


def test_catalog_resolves_sales_amount_to_revenue_metric() -> None:
    catalog = build_default_catalog()

    revenue = catalog.resolve_metric("revenue")
    sales_amount = catalog.resolve_metric("sales amount")

    assert revenue is not None
    assert sales_amount is not None
    assert sales_amount == revenue


def test_catalog_resolves_alias_with_extra_spaces_and_case() -> None:
    catalog = build_default_catalog()

    metric = catalog.resolve_metric("  Paid   Order Amount  ")

    assert metric is not None
    assert metric.name == "revenue"


def test_catalog_returns_none_for_unknown_metric() -> None:
    catalog = build_default_catalog()

    assert catalog.resolve_metric("gross margin") is None


def test_revenue_metric_has_canonical_sql_expression() -> None:
    catalog = build_default_catalog()

    metric = catalog.get_metric("revenue")

    assert metric is not None
    assert metric.table_name == "orders"
    assert metric.sql_expression == "SUM(orders.order_amount) WHERE orders.status = 'paid'"


def test_catalog_returns_ambiguous_candidates_for_shared_alias() -> None:
    revenue = MetricDefinition(
        name="revenue",
        description="Revenue.",
        table_name="orders",
        sql_expression="SUM(orders.order_amount)",
        semantic_version="sem_v1",
        synonyms=("sales",),
    )
    gross_sales = MetricDefinition(
        name="gross_sales",
        description="Gross sales.",
        table_name="orders",
        sql_expression="SUM(orders.gross_amount)",
        semantic_version="sem_v1",
        synonyms=("sales",),
    )
    catalog = SemanticCatalog(metrics=(revenue, gross_sales))

    resolution = catalog.resolve_metric_candidates("sales")

    assert resolution.metric is None
    assert resolution.is_ambiguous
    assert resolution.candidates == (revenue, gross_sales)
