import pytest

from chatbi.agents.analytics_agent import AnalyticsAgentRunner, AnalyticsModel


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
