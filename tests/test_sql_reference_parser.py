from chatbi.governance import SqlReferenceParser


def test_sql_reference_parser_extracts_table_and_unqualified_fields() -> None:
    references = SqlReferenceParser().parse(
        "SELECT order_id, order_amount FROM orders"
    )

    assert references.table_names == frozenset({"orders"})
    assert references.field_names == frozenset({"orders.order_id", "orders.order_amount"})


def test_sql_reference_parser_resolves_table_aliases() -> None:
    references = SqlReferenceParser().parse(
        "SELECT c.user_email FROM customers AS c"
    )

    assert references.table_aliases == {"customers": "customers", "c": "customers"}
    assert references.table_names == frozenset({"customers"})
    assert references.field_names == frozenset({"customers.user_email"})


def test_sql_reference_parser_resolves_join_aliases() -> None:
    references = SqlReferenceParser().parse(
        "SELECT o.order_amount, c.user_email "
        "FROM orders o JOIN customers c ON o.customer_id = c.customer_id"
    )

    assert references.table_names == frozenset({"orders", "customers"})
    assert "orders.order_amount" in references.field_names
    assert "customers.user_email" in references.field_names
    assert "orders.customer_id" in references.field_names
    assert "customers.customer_id" in references.field_names


def test_sql_reference_parser_skips_aggregate_selected_columns() -> None:
    references = SqlReferenceParser().parse(
        "SELECT sum(order_amount) AS revenue FROM orders"
    )

    assert references.table_names == frozenset({"orders"})
    assert references.field_names == frozenset()


def test_sql_reference_parser_excludes_a_cte_name_from_table_references() -> None:
    # "monthly" is a query-local alias defined by the WITH clause, not a
    # real schema object — it must not show up in table_names, or every
    # CTE query would fail the allow-list check for a "table" that was
    # never really queried.
    references = SqlReferenceParser().parse(
        "WITH monthly AS (SELECT month, revenue FROM revenue_by_month) "
        "SELECT month, revenue FROM monthly ORDER BY revenue DESC"
    )

    assert references.table_names == frozenset({"revenue_by_month"})


def test_sql_reference_parser_excludes_multiple_cte_names() -> None:
    references = SqlReferenceParser().parse(
        "WITH a AS (SELECT month FROM revenue_by_month), "
        "b AS (SELECT month FROM support_ticket_summary) "
        "SELECT a.month FROM a JOIN b ON a.month = b.month"
    )

    assert references.table_names == frozenset({"revenue_by_month", "support_ticket_summary"})


def test_sql_reference_parser_does_not_treat_a_derived_table_alias_as_a_cte() -> None:
    # "(...) AS orders_sub" is a derived-table alias, not a CTE definition
    # — no opening paren immediately follows AS, so it must not be excluded
    # the way a real "orders_sub AS (" CTE name would be.
    references = SqlReferenceParser().parse(
        "SELECT * FROM (SELECT order_id FROM orders) AS orders_sub"
    )

    assert references.table_names == frozenset({"orders"})
