from datetime import date

from chatbi.partitioning import PartitionPruningChecker
from chatbi.semantic.catalog import build_default_catalog
from chatbi.semantic.question_parser import QuestionParser
from chatbi.semantic.sql_generator import SqlTemplateGenerator


def test_partition_checker_passes_orders_date_range_query() -> None:
    sql_text = (
        "SELECT SUM(orders.order_amount) "
        "FROM orders "
        "WHERE orders.order_date >= DATE '2026-05-01' "
        "AND orders.order_date <= DATE '2026-05-31'"
    )

    reports = PartitionPruningChecker().check(sql_text)

    assert len(reports) == 1
    assert reports[0].table_name == "orders"
    assert reports[0].partition_column == "order_date"
    assert reports[0].uses_lower_bound
    assert reports[0].uses_upper_bound
    assert reports[0].passed


def test_partition_checker_fails_orders_query_without_date_range() -> None:
    sql_text = (
        "SELECT SUM(orders.order_amount) "
        "FROM orders "
        "WHERE orders.status = 'paid'"
    )

    reports = PartitionPruningChecker().check(sql_text)

    assert len(reports) == 1
    assert not reports[0].passed
    assert not reports[0].uses_lower_bound
    assert not reports[0].uses_upper_bound


def test_partition_checker_fails_when_only_one_bound_is_present() -> None:
    sql_text = (
        "SELECT SUM(orders.order_amount) "
        "FROM orders "
        "WHERE orders.order_date >= DATE '2026-05-01'"
    )

    reports = PartitionPruningChecker().check(sql_text)

    assert len(reports) == 1
    assert not reports[0].passed
    assert reports[0].uses_lower_bound
    assert not reports[0].uses_upper_bound


def test_partition_checker_ignores_non_partitioned_tables() -> None:
    sql_text = "SELECT products.category FROM products"

    reports = PartitionPruningChecker().check(sql_text)

    assert reports == ()
    assert PartitionPruningChecker().passes(sql_text)


def test_generated_revenue_sql_uses_orders_partition_pruning_filter() -> None:
    parser = QuestionParser(
        catalog=build_default_catalog(),
        today=date(2026, 6, 17),
    )
    parsed = parser.parse("Show revenue trend.")
    generated = SqlTemplateGenerator().generate(parsed)

    assert PartitionPruningChecker().passes(generated.sql_text)
