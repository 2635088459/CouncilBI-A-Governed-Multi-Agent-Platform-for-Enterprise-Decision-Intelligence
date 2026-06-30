import pytest

from chatbi.governance import RowLimitRewriter


def test_row_limit_rewriter_adds_missing_limit() -> None:
    result = RowLimitRewriter(max_rows=100).rewrite(
        "SELECT month, revenue FROM revenue_by_month"
    )

    assert result.sql_text == "SELECT month, revenue FROM revenue_by_month LIMIT 100"
    assert result.changed


def test_row_limit_rewriter_keeps_existing_limit_within_max_rows() -> None:
    result = RowLimitRewriter(max_rows=100).rewrite(
        "SELECT month, revenue FROM revenue_by_month LIMIT 25"
    )

    assert result.sql_text == "SELECT month, revenue FROM revenue_by_month LIMIT 25"
    assert not result.changed


def test_row_limit_rewriter_caps_existing_limit_above_max_rows() -> None:
    result = RowLimitRewriter(max_rows=100).rewrite(
        "SELECT month, revenue FROM revenue_by_month LIMIT 10000"
    )

    assert result.sql_text == "SELECT month, revenue FROM revenue_by_month LIMIT 100"
    assert result.changed


def test_row_limit_rewriter_rejects_invalid_max_rows() -> None:
    with pytest.raises(ValueError, match="max_rows"):
        RowLimitRewriter(max_rows=0)
