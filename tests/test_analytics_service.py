from chatbi.analytics import (
    AnalyticsErrorCode,
    AnalyticsGrain,
    AnalyticsRequest,
    AnalyticsService,
    AnalyticsValidationError,
)
from chatbi.analytics_repository import InMemoryAnalyticsRepository


def test_valid_daily_revenue_fixture_returns_forecast_and_persists_by_trace_id() -> None:
    repository = InMemoryAnalyticsRepository()
    service = AnalyticsService(repository)
    request = _request(
        trace_id="tr_analytics_daily",
        rows=(
            {"date": "2026-06-01", "revenue": 100.0},
            {"date": "2026-06-02", "revenue": 105.0},
            {"date": "2026-06-03", "revenue": 110.0},
            {"date": "2026-06-04", "revenue": 115.0},
            {"date": "2026-06-05", "revenue": 120.0},
        ),
    )

    result = service.analyze(request)

    assert result.quality_warnings == ()
    assert len(result.forecast_points) == 3
    assert result.anomaly_points == ()
    saved = service.result_by_trace_id("tr_analytics_daily")
    assert saved is not None
    assert saved.result == result
    assert saved.parameters["method"] == "rolling_zscore_linear_forecast"
    assert saved.parameters["model_version"] == service.model_version


def test_analytics_request_owner_is_persisted_on_record_and_parameters() -> None:
    repository = InMemoryAnalyticsRepository()
    service = AnalyticsService(repository)
    request = _request(
        trace_id="tr_analytics_owner",
        rows=(
            {"date": "2026-06-01", "revenue": 100.0},
            {"date": "2026-06-02", "revenue": 105.0},
            {"date": "2026-06-03", "revenue": 110.0},
        ),
        org_id="org_owner",
        user_id="user_owner",
    )

    service.analyze(request)

    saved = service.result_by_trace_id("tr_analytics_owner")
    assert saved is not None
    assert saved.org_id == "org_owner"
    assert saved.user_id == "user_owner"
    assert saved.parameters["org_id"] == "org_owner"
    assert saved.parameters["user_id"] == "user_owner"


def test_two_point_fixture_degrades_to_trend_summary() -> None:
    service = AnalyticsService(InMemoryAnalyticsRepository())
    request = _request(
        trace_id="tr_analytics_two_points",
        rows=(
            {"date": "2026-06-01", "revenue": 100.0},
            {"date": "2026-06-02", "revenue": 105.0},
        ),
    )

    result = service.analyze(request)

    assert result.method == "trend_summary"
    assert result.quality_warnings == ("INSUFFICIENT_DATA",)
    assert result.anomaly_points == ()
    assert result.forecast_points == ()
    assert result.confidence_interval is None


def test_forecast_points_keep_bounds_ordered() -> None:
    service = AnalyticsService(InMemoryAnalyticsRepository())
    result = service.analyze(
        _request(
            trace_id="tr_analytics_bounds",
            rows=(
                {"date": "2026-06-01", "revenue": 100.0},
                {"date": "2026-06-02", "revenue": 104.0},
                {"date": "2026-06-03", "revenue": 109.0},
                {"date": "2026-06-04", "revenue": 113.0},
            ),
        )
    )

    assert result.forecast_points
    for point in result.forecast_points:
        assert point.lower <= point.value <= point.upper


def test_invalid_dates_return_analytics_invalid_time_series() -> None:
    service = AnalyticsService(InMemoryAnalyticsRepository())

    try:
        service.analyze(
            _request(
                trace_id="tr_analytics_bad_date",
                rows=(
                    {"date": "not-a-date", "revenue": 100.0},
                    {"date": "2026-06-02", "revenue": 105.0},
                    {"date": "2026-06-03", "revenue": 110.0},
                ),
            )
        )
    except AnalyticsValidationError as exc:
        assert exc.code is AnalyticsErrorCode.INVALID_TIME_SERIES
    else:
        raise AssertionError("expected AnalyticsValidationError")


def test_same_fixture_returns_identical_anomaly_dates() -> None:
    service = AnalyticsService(InMemoryAnalyticsRepository())
    request = _request(
        trace_id="tr_analytics_deterministic",
        rows=(
            {"date": "2026-06-01", "revenue": 100.0},
            {"date": "2026-06-02", "revenue": 101.0},
            {"date": "2026-06-03", "revenue": 99.0},
            {"date": "2026-06-04", "revenue": 100.0},
            {"date": "2026-06-05", "revenue": 102.0},
            {"date": "2026-06-06", "revenue": 250.0},
        ),
    )

    first = service.analyze(request)
    second = service.analyze(request)

    assert tuple(point.timestamp for point in first.anomaly_points) == tuple(
        point.timestamp for point in second.anomaly_points
    )


def _request(
    trace_id: str,
    rows: tuple[dict[str, object], ...],
    org_id: str | None = None,
    user_id: str | None = None,
) -> AnalyticsRequest:
    return AnalyticsRequest(
        trace_id=trace_id,
        metric_id="revenue",
        semantic_version_id="sem_v2",
        time_column="date",
        value_column="revenue",
        grain=AnalyticsGrain.DAY,
        rows=rows,
        org_id=org_id,
        user_id=user_id,
    )
