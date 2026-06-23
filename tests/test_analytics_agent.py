import pytest
from typing import Any, Mapping, cast

from chatbi.agents.analytics_agent import (
    AnalyticsAgentRunner,
    AnalyticsModel,
    TimeSeriesPoint,
)


def test_analytics_agent_returns_payload() -> None:
    runner = AnalyticsAgentRunner(
        model=AnalyticsModel.MOVING_AVERAGE,
        metric_name="revenue",
        horizon_days=30,
    )

    result = runner.run()

    assert result.payload == {
        "model": "moving_average",
        "metric_name": "revenue",
        "horizon_days": 30,
    }
    assert result.confidence == 0.85


def test_analytics_agent_requires_metric_name() -> None:
    runner = AnalyticsAgentRunner(
        model=AnalyticsModel.MOVING_AVERAGE,
        metric_name=" ",
        horizon_days=30,
    )

    with pytest.raises(ValueError, match="metric_name"):
        runner.run()


def test_analytics_agent_requires_positive_horizon() -> None:
    runner = AnalyticsAgentRunner(
        model=AnalyticsModel.MOVING_AVERAGE,
        metric_name="revenue",
        horizon_days=0,
    )

    with pytest.raises(ValueError, match="horizon_days"):
        runner.run()


def test_analytics_agent_detects_injected_spike() -> None:
    runner = AnalyticsAgentRunner(
        model=AnalyticsModel.MOVING_AVERAGE,
        metric_name="revenue",
        horizon_days=2,
        time_series=(
            TimeSeriesPoint("2026-06-01", 100),
            TimeSeriesPoint("2026-06-02", 101),
            TimeSeriesPoint("2026-06-03", 99),
            TimeSeriesPoint("2026-06-04", 102),
            TimeSeriesPoint("2026-06-05", 100),
            TimeSeriesPoint("2026-06-06", 101),
            TimeSeriesPoint("2026-06-07", 180),
        ),
        trace_id="trc_test",
    )

    result = runner.run()

    anomaly_result = cast(Mapping[str, Any], result.payload["anomaly_result"])
    assert anomaly_result["anomaly_points"]
    assert anomaly_result["anomaly_level"] in {"medium", "high"}


def test_analytics_agent_forecast_includes_bounds_and_model_used() -> None:
    runner = AnalyticsAgentRunner(
        model=AnalyticsModel.PROPHET,
        metric_name="revenue",
        horizon_days=3,
        time_series=(
            TimeSeriesPoint("2026-06-01", 100),
            TimeSeriesPoint("2026-06-02", 105),
            TimeSeriesPoint("2026-06-03", 110),
            TimeSeriesPoint("2026-06-04", 115),
            TimeSeriesPoint("2026-06-05", 120),
        ),
    )

    result = runner.run()

    forecast_result = cast(Mapping[str, Any], result.payload["forecast_result"])
    assert forecast_result["model_used"] == "prophet"
    assert len(forecast_result["forecast_series"]) == 3
    assert len(forecast_result["lower_bound"]) == 3
    assert len(forecast_result["upper_bound"]) == 3
    assert not forecast_result["fallback"]


def test_analytics_agent_falls_back_to_moving_average_when_fit_fails() -> None:
    runner = AnalyticsAgentRunner(
        model=AnalyticsModel.ARIMA,
        metric_name="revenue",
        horizon_days=2,
        time_series=(
            TimeSeriesPoint("2026-06-01", 100),
            TimeSeriesPoint("2026-06-02", 105),
            TimeSeriesPoint("2026-06-03", 110),
            TimeSeriesPoint("2026-06-04", 115),
        ),
        force_model_failure=True,
    )

    result = runner.run()

    forecast_result = cast(Mapping[str, Any], result.payload["forecast_result"])
    warnings = cast(tuple[str, ...], result.payload["warnings"])
    assert forecast_result["model_used"] == "moving_average"
    assert forecast_result["fallback"]
    assert "fit failed" in warnings[0]


def test_analytics_agent_narrative_uses_fact_judgment_uncertainty_sections() -> None:
    runner = AnalyticsAgentRunner(
        model=AnalyticsModel.MOVING_AVERAGE,
        metric_name="revenue",
        horizon_days=1,
        time_series=(
            TimeSeriesPoint("2026-06-01", 100),
            TimeSeriesPoint("2026-06-02", 105),
            TimeSeriesPoint("2026-06-03", 110),
        ),
    )

    result = runner.run()

    narrative = cast(Mapping[str, str], result.payload["narrative"])
    assert tuple(narrative.keys()) == (
        "fact",
        "judgment",
        "uncertainty",
    )


def test_analytics_agent_empty_series_returns_quality_error_not_model_crash() -> None:
    runner = AnalyticsAgentRunner(
        model=AnalyticsModel.MOVING_AVERAGE,
        metric_name="revenue",
        horizon_days=1,
        time_series=(),
    )

    result = runner.run()

    quality_check = cast(Mapping[str, Any], result.payload["quality_check"])
    assert not quality_check["passed"]
    assert result.payload["forecast_result"] is None
    assert result.confidence == 0.2
