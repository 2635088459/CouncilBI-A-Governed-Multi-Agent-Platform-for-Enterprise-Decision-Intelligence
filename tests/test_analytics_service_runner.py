from typing import Any, Mapping, cast

from chatbi.analytics import AnalyticsGrain, AnalyticsService
from chatbi.analytics_repository import InMemoryAnalyticsRepository
from chatbi.orchestration.analytics_runner import AnalyticsServiceRunner


def test_analytics_service_runner_returns_legacy_and_v2_payload() -> None:
    repository = InMemoryAnalyticsRepository()
    runner = AnalyticsServiceRunner(
        analytics_service=AnalyticsService(repository),
        trace_id="tr_runner",
        metric_id="revenue",
        semantic_version_id="sem_v2",
        time_column="month",
        value_column="revenue",
        grain=AnalyticsGrain.MONTH,
        rows=(
            {"month": "2026-01", "revenue": 1000.0},
            {"month": "2026-02", "revenue": 1120.0},
            {"month": "2026-03", "revenue": 1180.0},
            {"month": "2026-04", "revenue": 1210.0},
        ),
    )

    result = runner.run()

    forecast = cast(Mapping[str, Any], result.payload["forecast_result"])
    v2_result = cast(Mapping[str, Any], result.payload["v2_result"])
    saved = repository.result_by_trace_id("tr_runner")

    assert forecast["model_used"] == "moving_average"
    assert len(cast(tuple[object, ...], forecast["forecast_series"])) == 3
    assert v2_result["method"] == "rolling_zscore_linear_forecast"
    assert saved is not None
    assert saved.parameters["grain"] == "month"


def test_analytics_service_runner_degrades_small_series_for_frontend_shape() -> None:
    runner = AnalyticsServiceRunner(
        analytics_service=AnalyticsService(InMemoryAnalyticsRepository()),
        trace_id="tr_runner_small",
        metric_id="revenue",
        semantic_version_id="sem_v2",
        time_column="month",
        value_column="revenue",
        grain=AnalyticsGrain.MONTH,
        rows=(
            {"month": "2026-01", "revenue": 1000.0},
            {"month": "2026-02", "revenue": 1120.0},
        ),
    )

    result = runner.run()

    quality = cast(Mapping[str, Any], result.payload["quality_check"])
    forecast = cast(Mapping[str, Any], result.payload["forecast_result"])
    narrative = cast(Mapping[str, str], result.payload["narrative"])

    assert quality["passed"] is False
    assert quality["warnings"] == ("INSUFFICIENT_DATA",)
    assert forecast["forecast_series"] == ()
    assert "fewer than 3" in narrative["fact"]
