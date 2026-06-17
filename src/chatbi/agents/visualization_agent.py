"""Visualization agent adapter for chart payload generation."""

from __future__ import annotations

from dataclasses import dataclass

from chatbi.core.contracts import ChartType
from chatbi.orchestration.executor import AgentRunResult


@dataclass(frozen=True, slots=True)
class VisualizationAgentRunner:
    """Build a minimal chart payload from known result fields."""

    chart_type: ChartType
    x_field: str
    y_fields: tuple[str, ...]
    title: str | None = None

    def run(self) -> AgentRunResult:
        if not self.x_field.strip():
            raise ValueError("x_field is required")
        if not self.y_fields:
            raise ValueError("at least one y_field is required")

        return AgentRunResult(
            payload={
                "chart_type": self.chart_type.value,
                "x_field": self.x_field,
                "y_fields": self.y_fields,
                "title": self.title,
            },
            confidence=0.9,
        )
