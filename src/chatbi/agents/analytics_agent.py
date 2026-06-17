"""Analytics agent adapter for lightweight analytical payloads."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from chatbi.orchestration.executor import AgentRunResult


class AnalyticsModel(StrEnum):
    MOVING_AVERAGE = "moving_average"
    ARIMA = "arima"
    PROPHET = "prophet"


@dataclass(frozen=True, slots=True)
class AnalyticsAgentRunner:
    """Build a minimal analytics payload for forecast/anomaly workflows."""

    # choose the model we have: arima, moving average, prophet, etc
    model: AnalyticsModel
    # the metric we want to analyze/forecast, e.g. "revenue", daily_active_users, etc
    metric_name: str
    # the forecast horizon in days, e.g. 7 for a week ahead or NONE for anomaly detection
    horizon_days: int | None = None

    def run(self) -> AgentRunResult:
        if not self.metric_name.strip():
            raise ValueError("metric_name is required")
        if self.horizon_days is not None and self.horizon_days <= 0:
            raise ValueError("horizon_days must be positive")

        return AgentRunResult(
            payload={
                "model": self.model.value,
                "metric_name": self.metric_name,
                "horizon_days": self.horizon_days,
            },
            confidence=0.85,
        )
