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


def test_sql_statement_validator_allows_a_single_with_cte() -> None:
    # A `WITH ... AS (...) SELECT ...` common table expression is a single
    # read-only statement — period-over-period comparisons and running
    # totals routinely need one. Previously denied outright because the
    # normalized SQL doesn't start with "select ", regardless of how
    # read-only the statement actually was.
    sql_text = (
        "WITH monthly AS (SELECT month, revenue FROM revenue_by_month) "
        "SELECT month, revenue FROM monthly ORDER BY revenue DESC"
    )

    result = SqlStatementValidator().validate(sql_text)

    assert result.passed
    assert result.violation_code is None


def test_sql_statement_validator_still_denies_a_write_statement_hidden_in_a_cte() -> None:
    # Allowing the "with " prefix must not create a new bypass: a write
    # keyword anywhere in the statement is still denied, regardless of
    # whether it appears inside a CTE.
    sql_text = "WITH x AS (SELECT 1) INSERT INTO orders(order_id) VALUES (1)"

    result = SqlStatementValidator().validate(sql_text)

    assert not result.passed
    assert result.violation_code is SqlValidationViolationCode.NON_SELECT_STATEMENT
    assert result.message == "Only SELECT statements are allowed."


# 10-followups/13 (Spec FV10.12/13 §8.1, TC-FV10-208/209): a real dangerous
# statement keyword must still be reported as NON_SELECT_STATEMENT, but
# model output that is simply not SQL at all (prose, a refusal, an
# explanation with no dangerous keyword) is a distinct failure mode —
# UNRECOGNIZED_QUERY_OUTPUT — so downstream layers can stop describing it as
# a data-modification attempt.
def test_sql_statement_validator_denies_dangerous_statement_as_non_select_statement() -> None:
    # AC-FV10-096 (unchanged behavior, confirmed here alongside the new code).
    result = SqlStatementValidator().validate("UPDATE revenue_by_month SET revenue = 0")

    assert not result.passed
    assert result.violation_code is SqlValidationViolationCode.NON_SELECT_STATEMENT
    assert result.message == "Only SELECT statements are allowed."


def test_sql_statement_validator_denies_prose_output_as_unrecognized_query_output() -> None:
    # AC-FV10-097: no SELECT/WITH prefix, no dangerous keyword either — the
    # model just didn't produce SQL, most often because the question asked
    # about a metric/table the schema doesn't have.
    result = SqlStatementValidator().validate("I don't have a churn table to query against.")

    assert not result.passed
    assert result.violation_code is SqlValidationViolationCode.UNRECOGNIZED_QUERY_OUTPUT
    assert result.message == "The model's output was not a single read-only query."
