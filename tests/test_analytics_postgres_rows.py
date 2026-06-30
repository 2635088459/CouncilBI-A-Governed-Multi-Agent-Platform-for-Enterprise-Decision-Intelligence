from chatbi.analytics import (
    AnomalyPoint,
    AnalyticsRecord,
    AnalyticsResult,
    ForecastPoint,
)
from chatbi.analytics_postgres_rows import (
    ANALYTICS_V2_TABLES_SQL,
    analytics_record_from_row,
    analytics_record_to_row,
)


def test_analytics_v2_table_sql_declares_required_table() -> None:
    assert "CREATE SCHEMA IF NOT EXISTS analytics" in ANALYTICS_V2_TABLES_SQL
    assert "CREATE TABLE IF NOT EXISTS analytics.results" in ANALYTICS_V2_TABLES_SQL
    assert "trace_id TEXT PRIMARY KEY" in ANALYTICS_V2_TABLES_SQL
    assert "anomaly_points JSONB NOT NULL" in ANALYTICS_V2_TABLES_SQL
    assert "forecast_points JSONB NOT NULL" in ANALYTICS_V2_TABLES_SQL


def test_analytics_record_round_trips_through_postgres_row() -> None:
    record = AnalyticsRecord(
        trace_id="tr_analytics_001",
        metric_id="revenue",
        semantic_version_id="sem_v2",
        parameters={"grain": "day", "horizon": 3},
        result=AnalyticsResult(
            anomaly_points=(
                AnomalyPoint(
                    index=4,
                    timestamp="2026-06-05",
                    value=180.0,
                    score=3.2,
                    method="rolling_zscore",
                ),
            ),
            forecast_points=(
                ForecastPoint(
                    timestamp="2026-06-06",
                    value=125.0,
                    lower=110.0,
                    upper=140.0,
                ),
            ),
            confidence_interval={"lower": 110.0, "upper": 140.0},
            quality_warnings=(),
            method="rolling_zscore_linear_forecast",
            model_version="analytics-v2-rule-based-001",
            explanation="Deterministic analytics result.",
        ),
    )

    row = analytics_record_to_row(record)
    restored = analytics_record_from_row(row)

    assert row["trace_id"] == "tr_analytics_001"
    assert row["method"] == "rolling_zscore_linear_forecast"
    assert restored == record


def test_analytics_row_mapper_rejects_invalid_trace_id() -> None:
    row = {
        "trace_id": "",
        "metric_id": "revenue",
        "semantic_version_id": "sem_v2",
        "parameters": {"grain": "day"},
        "anomaly_points": (),
        "forecast_points": (),
        "confidence_interval": None,
        "quality_warnings": (),
        "method": "trend_summary",
        "model_version": "analytics-v2-rule-based-001",
        "explanation": "Too little data.",
    }

    try:
        analytics_record_from_row(row)
    except ValueError as exc:
        assert "trace_id must be a non-empty string" in str(exc)
    else:
        raise AssertionError("Expected invalid trace_id to raise ValueError")
