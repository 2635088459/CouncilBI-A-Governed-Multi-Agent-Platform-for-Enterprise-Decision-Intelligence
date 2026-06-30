"""Orchestration runner adapter for analytics v2 service.

The plan executor expects an agent-shaped object with ``run()``. The analytics
v2 module exposes a service-shaped object with ``analyze(request)``. This file
is the small adapter between those two worlds.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from chatbi.analytics import (
    AnalyticsGrain,
    AnalyticsRequest,
    AnalyticsResult,
    AnalyticsService,
    result_to_dict,
)
from chatbi.orchestration.executor import AgentRunResult


@dataclass(frozen=True, slots=True)
class AnalyticsServiceRunner:
    """Run analytics v2 service while preserving the frontend analytics shape."""

    analytics_service: AnalyticsService
    trace_id: str
    metric_id: str
    semantic_version_id: str
    time_column: str
    value_column: str
    grain: AnalyticsGrain
    rows: Sequence[Mapping[str, object]]

    def run(self) -> AgentRunResult:
        request = AnalyticsRequest(
            trace_id=self.trace_id,
            metric_id=self.metric_id,
            semantic_version_id=self.semantic_version_id,
            time_column=self.time_column,
            value_column=self.value_column,
            grain=self.grain,
            rows=tuple(_normalize_time_row(row, self.time_column) for row in self.rows),
        )
        result = self.analytics_service.analyze(request)
        return AgentRunResult(
            payload=_legacy_payload(
                request=request,
                result=result,
            ),
            confidence=_confidence(result),
        )


def _normalize_time_row(
    row: Mapping[str, object],
    time_column: str,
) -> Mapping[str, object]:
    value = row.get(time_column)
    if isinstance(value, str) and len(value) == 7 and value[4] == "-":
        normalized = dict(row)
        normalized[time_column] = f"{value}-01"
        return normalized
    return row


def _legacy_payload(
    request: AnalyticsRequest,
    result: AnalyticsResult,
) -> Mapping[str, object]:
    anomaly_score = max(
        (point.score for point in result.anomaly_points),
        default=0.0,
    )
    forecast_values = tuple(point.value for point in result.forecast_points)
    lower_bounds = tuple(point.lower for point in result.forecast_points)
    upper_bounds = tuple(point.upper for point in result.forecast_points)

    return {
        "metric_id": request.metric_id,
        "quality_check": {
            "passed": not result.quality_warnings,
            "warnings": result.quality_warnings,
        },
        "anomaly_result": {
            "anomaly_points": tuple(
                {
                    "timestamp": point.timestamp,
                    "value": point.value,
                    "score": point.score,
                    "method": point.method,
                }
                for point in result.anomaly_points
            ),
            "anomaly_score": anomaly_score,
            "anomaly_level": _anomaly_level(anomaly_score),
        },
        "forecast_result": {
            "forecast_series": forecast_values,
            "lower_bound": lower_bounds,
            "upper_bound": upper_bounds,
            "model_used": "moving_average",
            "fallback": False,
        },
        "seasonality_summary": "Seasonality was not explicitly modeled in v2 deterministic analytics.",
        "narrative": _narrative(request, result),
        "model_run": {
            "model_version": result.model_version,
            "requested_model": "moving_average",
            "parameters": {
                "grain": request.grain.value,
                "horizon": request.analysis_options.horizon,
                "method": result.method,
            },
        },
        "warnings": result.quality_warnings,
        "trace_id": request.trace_id,
        "v2_result": result_to_dict(result),
    }


def _narrative(
    request: AnalyticsRequest,
    result: AnalyticsResult,
) -> Mapping[str, str]:
    if not result.forecast_points:
        return {
            "fact": f"{request.metric_id} has fewer than 3 usable time-series points.",
            "judgment": "Only a trend summary was produced.",
            "uncertainty": "Forecasting needs more historical data before intervals are useful.",
        }

    first = result.forecast_points[0]
    return {
        "fact": f"{request.metric_id} analytics completed with method {result.method}.",
        "judgment": (
            f"moving_average projects the next value near {first.value:.2f}; "
            f"anomaly level is {_anomaly_level_from_result(result)}."
        ),
        "uncertainty": (
            f"The first-step confidence interval is {first.lower:.2f} to "
            f"{first.upper:.2f}."
        ),
    }


def _confidence(result: AnalyticsResult) -> float:
    if result.quality_warnings:
        return 0.45
    if result.anomaly_points:
        return 0.78
    return 0.86


def _anomaly_level_from_result(result: AnalyticsResult) -> str:
    score = max((point.score for point in result.anomaly_points), default=0.0)
    return _anomaly_level(score)


def _anomaly_level(score: float) -> str:
    if score >= 3:
        return "high"
    if score >= 2:
        return "medium"
    if score > 0:
        return "low"
    return "none"
