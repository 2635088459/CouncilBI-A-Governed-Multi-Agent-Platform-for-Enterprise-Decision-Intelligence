from datetime import date, timedelta
from time import perf_counter

from chatbi.analytics import AnalyticsGrain, AnalyticsOptions, AnalyticsRequest, AnalyticsService
from chatbi.analytics_repository import InMemoryAnalyticsRepository


def test_analytics_over_1000_daily_points_stays_under_local_p95_budget() -> None:
    rows = _daily_rows(count=1000)
    samples_ms: list[float] = []

    for run_index in range(7):
        service = AnalyticsService(InMemoryAnalyticsRepository())
        request = AnalyticsRequest(
            trace_id=f"tr_analytics_perf_{run_index}",
            metric_id="revenue",
            semantic_version_id="sem_v2",
            time_column="date",
            value_column="revenue",
            grain=AnalyticsGrain.DAY,
            rows=rows,
            analysis_options=AnalyticsOptions(horizon=14),
        )

        started_at = perf_counter()
        result = service.analyze(request)
        samples_ms.append((perf_counter() - started_at) * 1000)

        assert len(result.forecast_points) == 14
        assert result.method == "rolling_zscore_linear_forecast"

    assert _p95(samples_ms) <= 6000


def _daily_rows(count: int) -> tuple[dict[str, object], ...]:
    start = date(2023, 1, 1)
    rows: list[dict[str, object]] = []
    for index in range(count):
        seasonal_bump = (index % 30) * 0.35
        rows.append(
            {
                "date": (start + timedelta(days=index)).isoformat(),
                "revenue": round(1000 + (index * 1.7) + seasonal_bump, 2),
            }
        )
    return tuple(rows)


def _p95(samples_ms: list[float]) -> float:
    ordered = sorted(samples_ms)
    index = max(0, int(len(ordered) * 0.95) - 1)
    return ordered[index]
