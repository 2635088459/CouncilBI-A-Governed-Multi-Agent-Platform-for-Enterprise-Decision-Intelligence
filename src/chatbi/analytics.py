"""Analytics v2 contracts and deterministic time-series service.

This module is the service-shaped layer for spec v2 section 09. The agent can
still be used by orchestration, but this file gives analytics a clear contract:
validate SQL-backed rows, produce anomaly and forecast fields, and persist the
result by trace id through a repository port.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from math import sqrt
from typing import Any, Protocol


class AnalyticsGrain(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class AnalyticsWarning(StrEnum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class AnalyticsErrorCode(StrEnum):
    INVALID_TIME_SERIES = "ANALYTICS_INVALID_TIME_SERIES"


@dataclass(frozen=True, slots=True)
class AnalyticsOptions:
    horizon: int = 3
    anomaly_z_threshold: float = 3.0

    def __post_init__(self) -> None:
        if self.horizon <= 0:
            raise ValueError("horizon must be positive")
        if self.anomaly_z_threshold <= 0:
            raise ValueError("anomaly_z_threshold must be positive")


@dataclass(frozen=True, slots=True)
class AnalyticsRequest:
    trace_id: str
    metric_id: str
    semantic_version_id: str
    time_column: str
    value_column: str
    grain: AnalyticsGrain
    rows: Sequence[Mapping[str, object]]
    analysis_options: AnalyticsOptions = field(default_factory=AnalyticsOptions)

    def __post_init__(self) -> None:
        for field_name in (
            "trace_id",
            "metric_id",
            "semantic_version_id",
            "time_column",
            "value_column",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} is required")


@dataclass(frozen=True, slots=True)
class AnomalyPoint:
    index: int
    timestamp: str
    value: float
    score: float
    method: str


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    timestamp: str
    value: float
    lower: float
    upper: float

    def __post_init__(self) -> None:
        if not self.lower <= self.value <= self.upper:
            raise ValueError("forecast point must satisfy lower <= value <= upper")


@dataclass(frozen=True, slots=True)
class AnalyticsResult:
    anomaly_points: tuple[AnomalyPoint, ...]
    forecast_points: tuple[ForecastPoint, ...]
    confidence_interval: Mapping[str, float] | None
    quality_warnings: tuple[str, ...]
    method: str
    model_version: str
    explanation: str


@dataclass(frozen=True, slots=True)
class AnalyticsRecord:
    trace_id: str
    metric_id: str
    semantic_version_id: str
    parameters: Mapping[str, object]
    result: AnalyticsResult


class AnalyticsRepository(Protocol):
    def save_result(self, record: AnalyticsRecord) -> None:
        """Persist one analytics result by trace id."""
        ...

    def result_by_trace_id(self, trace_id: str) -> AnalyticsRecord | None:
        """Return the latest analytics result for one trace."""
        ...


@dataclass(frozen=True, slots=True)
class _Point:
    timestamp: date
    label: str
    value: float


class AnalyticsValidationError(ValueError):
    """Raised when rows cannot be interpreted as a valid time series."""

    def __init__(self, code: AnalyticsErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class AnalyticsService:
    """Validate, analyze, forecast, and persist one metric time series."""

    model_version = "analytics-v2-rule-based-001"

    def __init__(self, repository: AnalyticsRepository) -> None:
        self._repository = repository

    def analyze(self, request: AnalyticsRequest) -> AnalyticsResult:
        points = _normalize_points(request)
        if len(points) < 3:
            result = AnalyticsResult(
                anomaly_points=(),
                forecast_points=(),
                confidence_interval=None,
                quality_warnings=(AnalyticsWarning.INSUFFICIENT_DATA.value,),
                method="trend_summary",
                model_version=self.model_version,
                explanation="Only a trend summary is available because fewer than 3 points were provided.",
            )
            self._persist(request, result)
            return result

        anomaly_points = _detect_anomalies(points, request.analysis_options.anomaly_z_threshold)
        forecast_points = _forecast(points, request.grain, request.analysis_options.horizon)
        result = AnalyticsResult(
            anomaly_points=anomaly_points,
            forecast_points=forecast_points,
            confidence_interval=_confidence_interval(forecast_points),
            quality_warnings=(),
            method="rolling_zscore_linear_forecast",
            model_version=self.model_version,
            explanation=(
                "Anomalies use a deterministic rolling z-score rule; forecast points "
                "use the recent average trend with explicit lower and upper bounds."
            ),
        )
        self._persist(request, result)
        return result

    def result_by_trace_id(self, trace_id: str) -> AnalyticsRecord | None:
        return self._repository.result_by_trace_id(trace_id)

    def _persist(self, request: AnalyticsRequest, result: AnalyticsResult) -> None:
        self._repository.save_result(
            AnalyticsRecord(
                trace_id=request.trace_id,
                metric_id=request.metric_id,
                semantic_version_id=request.semantic_version_id,
                parameters={
                    "time_column": request.time_column,
                    "value_column": request.value_column,
                    "grain": request.grain.value,
                    "horizon": request.analysis_options.horizon,
                    "anomaly_z_threshold": request.analysis_options.anomaly_z_threshold,
                    "method": result.method,
                    "model_version": result.model_version,
                },
                result=result,
            )
        )


def _normalize_points(request: AnalyticsRequest) -> tuple[_Point, ...]:
    points: list[_Point] = []
    for index, row in enumerate(request.rows):
        raw_time = row.get(request.time_column)
        raw_value = row.get(request.value_column)
        if not isinstance(raw_time, str):
            raise AnalyticsValidationError(
                AnalyticsErrorCode.INVALID_TIME_SERIES,
                f"row {index} has invalid time value",
            )
        if not isinstance(raw_value, int | float):
            raise AnalyticsValidationError(
                AnalyticsErrorCode.INVALID_TIME_SERIES,
                f"row {index} has invalid metric value",
            )
        points.append(
            _Point(
                timestamp=_parse_date(raw_time, index),
                label=raw_time,
                value=float(raw_value),
            )
        )

    return tuple(sorted(points, key=lambda point: point.timestamp))


def _parse_date(value: str, index: int) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AnalyticsValidationError(
            AnalyticsErrorCode.INVALID_TIME_SERIES,
            f"row {index} has invalid ISO date",
        ) from exc


def _detect_anomalies(
    points: tuple[_Point, ...],
    z_threshold: float,
) -> tuple[AnomalyPoint, ...]:
    window_size = max(3, min(7, len(points) // 2))
    anomalies: list[AnomalyPoint] = []

    for index in range(window_size, len(points)):
        baseline = tuple(point.value for point in points[index - window_size : index])
        mean = _mean(baseline)
        stddev = _stddev(baseline)
        if stddev == 0:
            continue

        score = abs(points[index].value - mean) / stddev
        if score >= z_threshold:
            anomalies.append(
                AnomalyPoint(
                    index=index,
                    timestamp=points[index].label,
                    value=points[index].value,
                    score=round(score, 2),
                    method="rolling_zscore",
                )
            )

    return tuple(anomalies)


def _forecast(
    points: tuple[_Point, ...],
    grain: AnalyticsGrain,
    horizon: int,
) -> tuple[ForecastPoint, ...]:
    values = tuple(point.value for point in points)
    trend = (values[-1] - values[0]) / (len(values) - 1)
    residual_spread = _stddev(
        tuple(values[index] - (values[0] + trend * index) for index in range(len(values)))
    )
    spread = residual_spread or max(abs(values[-1]) * 0.05, 1.0)

    forecast_points: list[ForecastPoint] = []
    for step in range(1, horizon + 1):
        value = round(values[-1] + trend * step, 2)
        lower = round(value - (1.96 * spread), 2)
        upper = round(value + (1.96 * spread), 2)
        forecast_points.append(
            ForecastPoint(
                timestamp=_add_grain(points[-1].timestamp, grain, step).isoformat(),
                value=value,
                lower=lower,
                upper=upper,
            )
        )

    return tuple(forecast_points)


def _add_grain(start: date, grain: AnalyticsGrain, step: int) -> date:
    if grain is AnalyticsGrain.DAY:
        return start + timedelta(days=step)
    if grain is AnalyticsGrain.WEEK:
        return start + timedelta(weeks=step)
    return _add_months(start, step)


def _add_months(start: date, months: int) -> date:
    month_index = (start.month - 1) + months
    year = start.year + (month_index // 12)
    month = (month_index % 12) + 1
    day = min(start.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def _confidence_interval(
    forecast_points: tuple[ForecastPoint, ...],
) -> Mapping[str, float] | None:
    if not forecast_points:
        return None
    return {
        "lower": min(point.lower for point in forecast_points),
        "upper": max(point.upper for point in forecast_points),
    }


def _mean(values: tuple[float, ...]) -> float:
    return sum(values) / len(values)


def _stddev(values: tuple[float, ...]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return sqrt(variance)


def result_to_dict(result: AnalyticsResult) -> Mapping[str, Any]:
    """Convert the typed result to frontend/API-friendly plain values."""

    return {
        "anomaly_points": tuple(
            {
                "index": point.index,
                "timestamp": point.timestamp,
                "value": point.value,
                "score": point.score,
                "method": point.method,
            }
            for point in result.anomaly_points
        ),
        "forecast_points": tuple(
            {
                "timestamp": point.timestamp,
                "value": point.value,
                "lower": point.lower,
                "upper": point.upper,
            }
            for point in result.forecast_points
        ),
        "confidence_interval": result.confidence_interval,
        "quality_warnings": result.quality_warnings,
        "method": result.method,
        "model_version": result.model_version,
        "explanation": result.explanation,
    }
