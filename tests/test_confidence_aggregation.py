import pytest

from chatbi.core.contracts import AgentName, ErrorCode
from chatbi.orchestration.confidence import ConfidenceAggregator


def test_confidence_aggregator_computes_weighted_score() -> None:
    result = ConfidenceAggregator().aggregate(
        {
            AgentName.SQL: 0.8,
            AgentName.VERIFIER: 0.6,
            AgentName.RAG: 1.0,
            AgentName.ANALYTICS: 0.4,
        }
    )

    assert result.confidence == 0.7
    assert result.warnings == ()


def test_confidence_aggregator_renormalizes_missing_agent_weights() -> None:
    result = ConfidenceAggregator().aggregate(
        {
            AgentName.SQL: 0.8,
            AgentName.RAG: 0.4,
        }
    )

    assert result.confidence == 0.68


def test_confidence_aggregator_adds_warning_below_threshold() -> None:
    result = ConfidenceAggregator().aggregate(
        {
            AgentName.SQL: 0.4,
            AgentName.VERIFIER: 0.5,
        }
    )

    assert result.confidence == 0.45
    assert len(result.warnings) == 1
    assert result.warnings[0].code is ErrorCode.LOW_CONFIDENCE


def test_confidence_aggregator_rejects_invalid_score() -> None:
    with pytest.raises(ValueError, match="between 0.0 and 1.0"):
        ConfidenceAggregator().aggregate({AgentName.SQL: 1.1})


def test_confidence_aggregator_rejects_unsupported_agent() -> None:
    with pytest.raises(ValueError, match="unsupported confidence agent"):
        ConfidenceAggregator().aggregate({AgentName.VISUALIZATION: 0.9})
