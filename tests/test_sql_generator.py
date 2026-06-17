from datetime import date

import pytest

from chatbi.semantic.catalog import build_default_catalog
from chatbi.semantic.question_parser import ParsedQuestion, QuestionParser
from chatbi.semantic.sql_generator import SqlTemplateGenerator


def test_sql_generator_builds_revenue_sql_with_time_filter() -> None:
    parser = QuestionParser(
        catalog=build_default_catalog(),
        today=date(2026, 6, 17),
    )
    parsed = parser.parse("Show revenue trend.")

    generated = SqlTemplateGenerator().generate(parsed)

    assert "SELECT DATE(orders.order_date) AS order_date" in generated.sql_text
    assert "SUM(orders.order_amount) AS metric_value" in generated.sql_text
    assert "orders.order_date >= DATE '2026-05-18'" in generated.sql_text
    assert "orders.order_date <= DATE '2026-06-17'" in generated.sql_text
    assert "AND orders.status = 'paid'" in generated.sql_text
    assert generated.semantic_version == "sem_v1"


def test_sql_generator_includes_sql_explanation() -> None:
    parser = QuestionParser(
        catalog=build_default_catalog(),
        today=date(2026, 6, 17),
    )
    parsed = parser.parse("Show sales amount trend.")

    generated = SqlTemplateGenerator().generate(parsed)

    assert "Metric revenue uses" in generated.sql_explanation
    assert "date filter is 2026-05-18 to 2026-06-17" in generated.sql_explanation
    assert "aggregation is grouped by order_date" in generated.sql_explanation


def test_sql_generator_requires_resolved_metric() -> None:
    parser = QuestionParser(
        catalog=build_default_catalog(),
        today=date(2026, 6, 17),
    )
    parsed = parser.parse("Show gross margin trend.")
    unresolved = ParsedQuestion(
        metric=None,
        time_range=parsed.time_range,
        original_question=parsed.original_question,
    )

    with pytest.raises(ValueError, match="metric"):
        SqlTemplateGenerator().generate(unresolved)
