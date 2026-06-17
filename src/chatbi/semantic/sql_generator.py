"""Template SQL generation for governed semantic metrics."""

from __future__ import annotations

from dataclasses import dataclass

from chatbi.semantic.question_parser import ParsedQuestion, TimeRange


@dataclass(frozen=True, slots=True)
class GeneratedSql:
    sql_text: str
    sql_explanation: str
    semantic_version: str


class SqlTemplateGenerator:
    """Generate SQL from a parsed question using deterministic templates."""

    def generate(self, parsed_question: ParsedQuestion) -> GeneratedSql:
        if parsed_question.metric is None:
            raise ValueError("parsed_question.metric is required")

        metric = parsed_question.metric
        time_range = parsed_question.time_range
        sql_text = self._build_sql_text(
            table_name=metric.table_name,
            metric_expression=metric.sql_expression,
            time_range=time_range,
        )
        sql_explanation = (
            f"Metric {metric.name} uses {metric.sql_expression}; "
            f"date filter is {time_range.start_date.isoformat()} to {time_range.end_date.isoformat()}; "
            "aggregation is grouped by order_date."
        )

        return GeneratedSql(
            sql_text=sql_text,
            sql_explanation=sql_explanation,
            semantic_version=metric.semantic_version,
        )

    def _build_sql_text(
        self,
        table_name: str,
        metric_expression: str,
        time_range: TimeRange,
    ) -> str:
        aggregation_expression, metric_filter = self._split_metric_expression(metric_expression)
        return (
            "SELECT DATE(orders.order_date) AS order_date, "
            f"{aggregation_expression} AS metric_value "
            f"FROM {table_name} "
            f"WHERE orders.order_date >= DATE '{time_range.start_date.isoformat()}' "
            f"AND orders.order_date <= DATE '{time_range.end_date.isoformat()}' "
            f"AND {metric_filter} "
            "GROUP BY DATE(orders.order_date) "
            "ORDER BY order_date "
            "LIMIT 100"
        )

    def _split_metric_expression(self, metric_expression: str) -> tuple[str, str]:
        if " WHERE " not in metric_expression:
            return metric_expression, "1 = 1"
        aggregation_expression, metric_filter = metric_expression.split(" WHERE ", maxsplit=1)
        return aggregation_expression, metric_filter
