"""Template SQL generation for governed semantic metrics."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Literal

from chatbi.semantic.question_parser import ParsedQuestion, TimeGrain, TimeRange


@dataclass(frozen=True, slots=True)
class GeneratedSql:
    sql_text: str
    sql_explanation: str
    semantic_version: str


@dataclass(frozen=True, slots=True)
class SqlPreviewResponse:
    sql_text: str
    sql_hash: str
    explanation: str
    semantic_version_id: str
    executes: Literal[False] = False

    def __post_init__(self) -> None:
        if not self.sql_text.strip():
            raise ValueError("sql_text is required")
        if not self.sql_hash.strip():
            raise ValueError("sql_hash is required")
        if not self.explanation.strip():
            raise ValueError("explanation is required")
        if not self.semantic_version_id.strip():
            raise ValueError("semantic_version_id is required")
        if self.executes is not False:
            raise ValueError("SQL preview must not execute SQL")


class SqlTemplateGenerator:
    """Generate SQL from a parsed question using deterministic templates."""

    def generate(self, parsed_question: ParsedQuestion) -> GeneratedSql:
        if parsed_question.metric is None:
            raise ValueError("parsed_question.metric is required")

        metric = parsed_question.metric
        time_range = parsed_question.time_range
        _, time_bucket_alias = self._time_bucket(parsed_question.time_grain)
        sql_text = self._build_sql_text(
            table_name=metric.table_name,
            metric_expression=metric.sql_expression,
            time_range=time_range,
            time_grain=parsed_question.time_grain,
        )
        sql_explanation = (
            f"Metric {metric.name} uses {metric.sql_expression}; "
            f"date filter is {time_range.start_date.isoformat()} to {time_range.end_date.isoformat()}; "
            f"aggregation is grouped by {time_bucket_alias}."
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
        time_grain: TimeGrain,
    ) -> str:
        aggregation_expression, metric_filter = self._split_metric_expression(metric_expression)
        time_bucket_expression, time_bucket_alias = self._time_bucket(time_grain)
        return (
            f"SELECT {time_bucket_expression} AS {time_bucket_alias}, "
            f"{aggregation_expression} AS metric_value "
            f"FROM {table_name} "
            f"WHERE orders.order_date >= DATE '{time_range.start_date.isoformat()}' "
            f"AND orders.order_date <= DATE '{time_range.end_date.isoformat()}' "
            f"AND {metric_filter} "
            f"GROUP BY {time_bucket_expression} "
            f"ORDER BY {time_bucket_alias} "
            "LIMIT 100"
        )

    def _time_bucket(self, time_grain: TimeGrain) -> tuple[str, str]:
        if time_grain is TimeGrain.MONTH:
            return "DATE_TRUNC('month', orders.order_date)::DATE", "order_month"
        return "DATE(orders.order_date)", "order_date"

    def _split_metric_expression(self, metric_expression: str) -> tuple[str, str]:
        if " WHERE " not in metric_expression:
            return metric_expression, "1 = 1"
        aggregation_expression, metric_filter = metric_expression.split(" WHERE ", maxsplit=1)
        return aggregation_expression, metric_filter


def build_sql_preview_response(generated_sql: GeneratedSql) -> SqlPreviewResponse:
    sql_hash = hashlib.sha256(generated_sql.sql_text.encode("utf-8")).hexdigest()
    return SqlPreviewResponse(
        sql_text=generated_sql.sql_text,
        sql_hash=sql_hash,
        explanation=generated_sql.sql_explanation,
        semantic_version_id=generated_sql.semantic_version,
        executes=False,
    )
