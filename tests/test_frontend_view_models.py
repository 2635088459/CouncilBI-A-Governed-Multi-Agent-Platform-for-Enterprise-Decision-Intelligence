from typing import Any

from chatbi.core.contracts import ChartType, ErrorCode
from chatbi.frontend.view_models import (
    ResultBlockType,
    build_query_result_view_model,
)


def test_build_query_result_view_model_renders_distinct_blocks() -> None:
    envelope: dict[str, Any] = {
        "code": 0,
        "message": "ok",
        "trace_id": "trc_frontend_001",
        "warnings": [
            {
                "code": ErrorCode.AGENT_PARTIAL_FAILURE,
                "message": "Visualization agent failed.",
            }
        ],
        "timestamp": "2026-06-18T12:00:00Z",
        "data": {
            "answer_text": "Revenue trend is ready.",
            "sql_text": "SELECT order_month, revenue FROM monthly_revenue",
            "table_result": {
                "columns": ["order_month", "revenue"],
                "rows": [
                    {"order_month": "2026-01", "revenue": 1200},
                    {"order_month": "2026-02", "revenue": 1500},
                ],
            },
            "chart_spec": {
                "chart_type": "line",
                "x_field": "order_month",
                "y_fields": ["revenue"],
                "title": "Revenue Trend",
            },
            "analytics_result": {
                "forecast_result": {
                    "forecast_series": [1600, 1700],
                    "lower_bound": [1500, 1600],
                    "upper_bound": [1700, 1800],
                    "model_used": "moving_average",
                },
                "anomaly_result": {
                    "anomaly_points": [],
                    "anomaly_score": 0.0,
                    "anomaly_level": "none",
                },
                "narrative": {
                    "fact": "Revenue latest value is 1500.00 at 2026-02.",
                    "judgment": "moving_average projects the next value near 1600.00.",
                    "uncertainty": "The first-step confidence interval is 1500.00 to 1700.00.",
                },
            },
            "evidence_list": [
                {
                    "source_id": "doc_001",
                    "title": "Revenue Review",
                    "citation_anchor": "p3",
                    "snippet": "Revenue increased after the campaign.",
                }
            ],
            "confidence": 0.92,
        },
    }

    view_model = build_query_result_view_model(envelope)

    assert view_model.trace_id == "trc_frontend_001"
    assert view_model.answer.text == "Revenue trend is ready."
    assert view_model.warnings[0].is_partial_failure is True
    assert view_model.table is not None
    assert view_model.chart is not None
    assert view_model.chart.chart_type is ChartType.LINE
    assert view_model.analytics is not None
    assert view_model.analytics.model_used == "moving_average"
    assert view_model.analytics.anomaly_level == "none"
    assert view_model.analytics.forecast_points == 2
    assert view_model.evidence[0].source_id == "doc_001"
    assert view_model.sql_explain.sql_text.startswith("SELECT")
    assert view_model.blocks == (
        ResultBlockType.WARNING,
        ResultBlockType.TABLE,
        ResultBlockType.CHART,
        ResultBlockType.ANALYTICS,
        ResultBlockType.EVIDENCE,
        ResultBlockType.SQL_EXPLAIN,
    )


def test_build_query_result_view_model_defaults_time_series_to_line_chart() -> None:
    envelope: dict[str, Any] = {
        "code": 0,
        "message": "ok",
        "trace_id": "trc_frontend_002",
        "warnings": [],
        "timestamp": "2026-06-18T12:00:00Z",
        "data": {
            "answer_text": "Monthly orders are ready.",
            "sql_text": "SELECT order_date, order_count FROM daily_orders",
            "table_result": {
                "columns": ["order_date", "order_count"],
                "rows": [{"order_date": "2026-06-18", "order_count": 42}],
            },
            "chart_spec": None,
            "evidence_list": [],
            "confidence": 0.88,
        },
    }

    view_model = build_query_result_view_model(envelope)

    assert view_model.chart is not None
    assert view_model.chart.chart_type is ChartType.LINE
    assert view_model.chart.x_field == "order_date"
    assert view_model.chart.y_fields == ("order_count",)
    assert view_model.blocks == (
        ResultBlockType.TABLE,
        ResultBlockType.CHART,
        ResultBlockType.SQL_EXPLAIN,
    )
