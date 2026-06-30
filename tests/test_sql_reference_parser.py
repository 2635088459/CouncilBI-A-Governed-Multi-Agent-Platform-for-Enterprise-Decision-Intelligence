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
