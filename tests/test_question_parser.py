from datetime import date

from chatbi.semantic.catalog import MetricDefinition, SemanticCatalog, build_default_catalog
from chatbi.semantic.question_parser import QuestionParser


def test_question_parser_extracts_metric_from_question() -> None:
    parser = QuestionParser(
        catalog=build_default_catalog(),
        today=date(2026, 6, 17),
    )

    parsed = parser.parse("Show revenue trend.")

    assert parsed.metric is not None
    assert parsed.metric.name == "revenue"


def test_question_parser_resolves_metric_synonym() -> None:
    parser = QuestionParser(
        catalog=build_default_catalog(),
        today=date(2026, 6, 17),
    )

    parsed = parser.parse("Show sales amount trend.")

    assert parsed.metric is not None
    assert parsed.metric.name == "revenue"


def test_question_parser_defaults_missing_time_to_last_30_days() -> None:
    parser = QuestionParser(
        catalog=build_default_catalog(),
        today=date(2026, 6, 17),
    )

    parsed = parser.parse("Show revenue trend.")

    assert parsed.time_range.start_date == date(2026, 5, 18)
    assert parsed.time_range.end_date == date(2026, 6, 17)
    assert parsed.time_range.source == "default_last_30_days"


def test_question_parser_keeps_explicit_last_30_days_source() -> None:
    parser = QuestionParser(
        catalog=build_default_catalog(),
        today=date(2026, 6, 17),
    )

    parsed = parser.parse("Show revenue trend in the last 30 days.")

    assert parsed.time_range.start_date == date(2026, 5, 18)
    assert parsed.time_range.end_date == date(2026, 6, 17)
    assert parsed.time_range.source == "explicit_last_30_days"


def test_question_parser_returns_none_for_unknown_metric() -> None:
    parser = QuestionParser(
        catalog=build_default_catalog(),
        today=date(2026, 6, 17),
    )

    parsed = parser.parse("Show gross margin trend.")

    assert parsed.metric is None


def test_question_parser_extracts_requested_field_from_question() -> None:
    parser = QuestionParser(
        catalog=build_default_catalog(),
        today=date(2026, 6, 17),
    )

    parsed = parser.parse("Show customer id trend.")

    assert parsed.requested_field is not None
    assert parsed.requested_field.name == "user_id"
    assert parsed.requested_field.is_high_sensitivity


def test_question_parser_marks_ambiguous_metric_for_clarification() -> None:
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
    parser = QuestionParser(
        catalog=SemanticCatalog(metrics=(revenue, gross_sales)),
        today=date(2026, 6, 17),
    )

    parsed = parser.parse("Show sales trend.")

    assert parsed.metric is None
    assert parsed.needs_clarification
    assert parsed.metric_candidates == (revenue, gross_sales)
