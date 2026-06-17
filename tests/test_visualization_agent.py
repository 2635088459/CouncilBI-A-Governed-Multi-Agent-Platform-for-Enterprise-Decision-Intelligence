import pytest

from chatbi.agents.visualization_agent import VisualizationAgentRunner
from chatbi.core.contracts import ChartType


def test_visualization_agent_returns_chart_payload() -> None:
    runner = VisualizationAgentRunner(
        chart_type=ChartType.LINE,
        x_field="month",
        y_fields=("revenue",),
        title="Revenue trend",
    )

    result = runner.run()

    assert result.payload == {
        "chart_type": "line",
        "x_field": "month",
        "y_fields": ("revenue",),
        "title": "Revenue trend",
    }
    assert result.confidence == 0.9


def test_visualization_agent_requires_x_field() -> None:
    runner = VisualizationAgentRunner(
        chart_type=ChartType.LINE,
        x_field=" ",
        y_fields=("revenue",),
    )

    with pytest.raises(ValueError, match="x_field"):
        runner.run()


def test_visualization_agent_requires_y_fields() -> None:
    runner = VisualizationAgentRunner(
        chart_type=ChartType.LINE,
        x_field="month",
        y_fields=(),
    )

    with pytest.raises(ValueError, match="y_field"):
        runner.run()
