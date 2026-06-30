import pytest

from chatbi.governance import SqlStatementValidator, SqlValidationViolationCode


def test_sql_statement_validator_allows_single_select() -> None:
    result = SqlStatementValidator().validate(
        "  SELECT   month, revenue   FROM revenue_by_month  "
    )

    assert result.passed
    assert result.normalized_sql == "SELECT month, revenue FROM revenue_by_month"
    assert result.violation_code is None
    assert result.message is None


def test_sql_statement_validator_denies_empty_sql() -> None:
    result = SqlStatementValidator().validate(" ")

    assert not result.passed
    assert result.violation_code is SqlValidationViolationCode.EMPTY_SQL
    assert result.message == "SQL text is empty."


def test_sql_statement_validator_denies_multiple_statements() -> None:
    result = SqlStatementValidator().validate("SELECT * FROM orders; DROP TABLE orders")

    assert not result.passed
    assert result.violation_code is SqlValidationViolationCode.MULTIPLE_STATEMENTS
    assert result.message == "Only a single SELECT statement is allowed."


@pytest.mark.parametrize(
    "sql_text",
    (
        "DROP TABLE orders",
        "DELETE FROM orders",
        "UPDATE orders SET order_amount = 0",
        "INSERT INTO orders(order_id) VALUES (1)",
        "ALTER TABLE orders ADD COLUMN probe int",
        "TRUNCATE TABLE orders",
    ),
)
def test_sql_statement_validator_denies_write_statements(sql_text: str) -> None:
    result = SqlStatementValidator().validate(sql_text)

    assert not result.passed
    assert result.violation_code is SqlValidationViolationCode.NON_SELECT_STATEMENT
    assert result.message == "Only SELECT statements are allowed."


@pytest.mark.parametrize(
    "sql_text",
    (
        "SELECT * FROM orders WHERE status = 'paid' -- hidden",
        "SELECT * FROM orders UNION SELECT * FROM users",
        "SELECT * FROM orders WHERE id = 1 OR 1 = 1",
        "SELECT sleep(5) FROM orders",
    ),
)
def test_sql_statement_validator_denies_structural_risk(sql_text: str) -> None:
    result = SqlStatementValidator().validate(sql_text)

    assert not result.passed
    assert result.violation_code is SqlValidationViolationCode.STRUCTURAL_RISK
    assert result.message == "SQL contains a blocked injection pattern."
