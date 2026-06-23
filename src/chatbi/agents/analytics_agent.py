"""Analytics agent for anomaly detection and lightweight forecasting."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import sqrt
from typing import Mapping

from chatbi.orchestration.executor import AgentRunResult


class AnalyticsModel(StrEnum):
    MOVING_AVERAGE = "moving_average"
    ARIMA = "arima"
    PROPHET = "prophet"


@dataclass(frozen=True, slots=True)
class TimeSeriesPoint:
    """One metric value at one time bucket."""

    timestamp: str
    value: float


@dataclass(frozen=True, slots=True)
class _QualityCheck:
    passed: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ForecastComputation:
    forecast_series: tuple[float, ...]
    lower_bound: tuple[float, ...]
    upper_bound: tuple[float, ...]
    model_used: AnalyticsModel
    fallback: bool
    warning: str | None = None


SeriesRow = TimeSeriesPoint | Mapping[str, object]


@dataclass(frozen=True, slots=True)
class AnalyticsAgentRunner:
    """Run deterministic anomaly and forecast logic for one metric series."""

    model: AnalyticsModel
    metric_name: str
    horizon_days: int | None = None
    time_series: tuple[SeriesRow, ...] | None = None
    granularity: str = "day"
    trace_id: str | None = None
    model_version: str = "analytics-v1"
    force_model_failure: bool = False

    def run(self) -> AgentRunResult:
        if not self.metric_name.strip():
            raise ValueError("metric_name is required")
        if self.horizon_days is not None and self.horizon_days <= 0:
            raise ValueError("horizon_days must be positive")

        # Backward-compatible adapter mode used by the early orchestrator tests.
        if self.time_series is None:
            return AgentRunResult(
                payload={
                    "model": self.model.value,
                    "metric_name": self.metric_name,
                    "horizon_days": self.horizon_days,
                },
                confidence=0.85,
            )

        points = self._normalize_series(self.time_series)
        quality_check = self._quality_check(points)
        if not quality_check.passed:
            return AgentRunResult(
                payload={
                    "metric_id": self.metric_name,
                    "quality_check": {
                        "passed": False,
                        "warnings": quality_check.warnings,
                    },
                    "anomaly_result": {
                        "anomaly_points": (),
                        "anomaly_score": 0.0,
                        "anomaly_level": "none",
                    },
                    "forecast_result": None,
                    "seasonality_summary": "Not enough valid data to evaluate seasonality.",
                    "narrative": {
                        "fact": f"{self.metric_name} has no valid time-series points.",
                        "judgment": "No analytics model was applied because data quality failed.",
                        "uncertainty": "The result is unavailable until the input series is fixed.",
                    },
                    "model_run": self._model_run_log({}),
                    "warnings": quality_check.warnings,
                    "trace_id": self.trace_id,
                },
                confidence=0.2,
            )

        anomaly_result = self._detect_anomalies(points)
        forecast_result = self._forecast(points)
        warnings = tuple(
            warning
            for warning in (*quality_check.warnings, forecast_result.warning)
            if warning is not None
        )
        narrative = self._build_narrative(
            points=points,
            anomaly_level=str(anomaly_result["anomaly_level"]),
            forecast=forecast_result,
        )

        confidence = 0.78 if forecast_result.fallback else 0.86
        if anomaly_result["anomaly_level"] == "high":
            confidence -= 0.08

        return AgentRunResult(
            payload={
                "metric_id": self.metric_name,
                "quality_check": {
                    "passed": True,
                    "warnings": quality_check.warnings,
                },
                "anomaly_result": anomaly_result,
                "forecast_result": {
                    "forecast_series": forecast_result.forecast_series,
                    "lower_bound": forecast_result.lower_bound,
                    "upper_bound": forecast_result.upper_bound,
                    "model_used": forecast_result.model_used.value,
                    "fallback": forecast_result.fallback,
                },
                "seasonality_summary": self._seasonality_summary(points),
                "narrative": narrative,
                "model_run": self._model_run_log(
                    {
                        "granularity": self.granularity,
                        "horizon_days": self.horizon_days,
                        "window": self._window_size(points),
                    }
                ),
                "warnings": warnings,
                "trace_id": self.trace_id,
            },
            confidence=round(max(0.0, min(confidence, 1.0)), 2),
        )

    def _normalize_series(self, rows: tuple[SeriesRow, ...]) -> tuple[TimeSeriesPoint, ...]:
        points: list[TimeSeriesPoint] = []
        for row in rows:
            if isinstance(row, TimeSeriesPoint):
                points.append(row)
                continue

            timestamp = row.get("timestamp") or row.get("date") or row.get("time")
            value = row.get("value") or row.get(self.metric_name)
            if not isinstance(timestamp, str):
                continue
            if not isinstance(value, int | float):
                continue
            points.append(TimeSeriesPoint(timestamp=timestamp, value=float(value)))

        return tuple(points)

    def _quality_check(self, points: tuple[TimeSeriesPoint, ...]) -> _QualityCheck:
        warnings: list[str] = []
        if not points:
            warnings.append("time_series must contain at least one valid point")
        if self.horizon_days is None:
            warnings.append("forecast_horizon is required for forecasting")
        if len(points) < 3:
            warnings.append("at least 3 points are required for anomaly detection")

        return _QualityCheck(passed=not warnings, warnings=tuple(warnings))

    def _detect_anomalies(self, points: tuple[TimeSeriesPoint, ...]) -> Mapping[str, object]:
        values = tuple(point.value for point in points)
        window_size = self._window_size(points)
        anomaly_points: list[Mapping[str, object]] = []
        max_score = 0.0

        for index in range(window_size, len(points)):
            baseline = values[index - window_size : index]
            mean = _mean(baseline)
            stddev = _stddev(baseline)
            if stddev == 0:
                continue

            score = abs(values[index] - mean) / stddev
            upper_band = mean + (2 * stddev)
            lower_band = mean - (2 * stddev)
            if values[index] > upper_band or values[index] < lower_band:
                max_score = max(max_score, score)
                anomaly_points.append(
                    {
                        "timestamp": points[index].timestamp,
                        "value": values[index],
                        "score": round(score, 2),
                        "method": "bollinger_zscore",
                    }
                )

        return {
            "anomaly_points": tuple(anomaly_points),
            "anomaly_score": round(max_score, 2),
            "anomaly_level": self._anomaly_level(max_score),
        }

    def _forecast(self, points: tuple[TimeSeriesPoint, ...]) -> _ForecastComputation:
        horizon = self.horizon_days or 1
        if self.model is AnalyticsModel.MOVING_AVERAGE:
            return self._moving_average_forecast(points, horizon, fallback=False)

        try:
            return self._trend_forecast(points, horizon)
        except ValueError as exc:
            fallback = self._moving_average_forecast(points, horizon, fallback=True)
            return _ForecastComputation(
                forecast_series=fallback.forecast_series,
                lower_bound=fallback.lower_bound,
                upper_bound=fallback.upper_bound,
                model_used=fallback.model_used,
                fallback=True,
                warning=f"{self.model.value} fit failed; used moving_average fallback: {exc}",
            )

    def _trend_forecast(
        self,
        points: tuple[TimeSeriesPoint, ...],
        horizon: int,
    ) -> _ForecastComputation:
        if self.force_model_failure:
            raise ValueError("forced model failure")
        if len(points) < 4:
            raise ValueError("not enough points for trend model")

        values = tuple(point.value for point in points)
        trend = (values[-1] - values[0]) / (len(values) - 1)
        residuals = tuple(
            values[index] - (values[0] + trend * index)
            for index in range(len(values))
        )
        spread = _stddev(residuals) or max(abs(values[-1]) * 0.05, 1.0)

        forecast = tuple(round(values[-1] + trend * step, 2) for step in range(1, horizon + 1))
        lower = tuple(round(value - (1.96 * spread), 2) for value in forecast)
        upper = tuple(round(value + (1.96 * spread), 2) for value in forecast)

        return _ForecastComputation(
            forecast_series=forecast,
            lower_bound=lower,
            upper_bound=upper,
            model_used=self.model,
            fallback=False,
        )

    def _moving_average_forecast(
        self,
        points: tuple[TimeSeriesPoint, ...],
        horizon: int,
        fallback: bool,
    ) -> _ForecastComputation:
        values = tuple(point.value for point in points)
        window = values[-self._window_size(points) :]
        forecast_value = round(_mean(window), 2)
        spread = _stddev(window) or max(abs(forecast_value) * 0.05, 1.0)
        forecast = tuple(forecast_value for _ in range(horizon))
        lower = tuple(round(forecast_value - (1.96 * spread), 2) for _ in range(horizon))
        upper = tuple(round(forecast_value + (1.96 * spread), 2) for _ in range(horizon))

        return _ForecastComputation(
            forecast_series=forecast,
            lower_bound=lower,
            upper_bound=upper,
            model_used=AnalyticsModel.MOVING_AVERAGE,
            fallback=fallback,
        )

    def _build_narrative(
        self,
        points: tuple[TimeSeriesPoint, ...],
        anomaly_level: str,
        forecast: _ForecastComputation,
    ) -> Mapping[str, str]:
        latest = points[-1]
        first_forecast = forecast.forecast_series[0]
        first_lower = forecast.lower_bound[0]
        first_upper = forecast.upper_bound[0]

        return {
            "fact": f"{self.metric_name} latest value is {latest.value:.2f} at {latest.timestamp}.",
            "judgment": (
                f"{forecast.model_used.value} projects the next value near "
                f"{first_forecast:.2f}; anomaly level is {anomaly_level}."
            ),
            "uncertainty": (
                f"The first-step confidence interval is {first_lower:.2f} to "
                f"{first_upper:.2f}."
            ),
        }

    def _seasonality_summary(self, points: tuple[TimeSeriesPoint, ...]) -> str:
        if len(points) < 14:
            return "Not enough data to confirm seasonality."
        return "Seasonality was not explicitly modeled in v1 deterministic analytics."

    def _model_run_log(self, parameters: Mapping[str, object]) -> Mapping[str, object]:
        return {
            "model_version": self.model_version,
            "requested_model": self.model.value,
            "parameters": dict(parameters),
        }

    def _window_size(self, points: tuple[TimeSeriesPoint, ...]) -> int:
        return max(3, min(7, len(points) // 2))

    def _anomaly_level(self, score: float) -> str:
        if score >= 3:
            return "high"
        if score >= 2:
            return "medium"
        if score > 0:
            return "low"
        return "none"


def _mean(values: tuple[float, ...]) -> float:
    return sum(values) / len(values)


def _stddev(values: tuple[float, ...]) -> float:
    if len(values) < 2:
        return 0.0

    mean = _mean(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return sqrt(variance)
