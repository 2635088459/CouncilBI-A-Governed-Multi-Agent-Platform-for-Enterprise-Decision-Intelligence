"""Confidence aggregation rules for agent orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from chatbi.core.contracts import AgentName, WarningMessage, low_confidence_warning


CONFIDENCE_WEIGHTS: dict[AgentName, float] = {
    AgentName.SQL: 0.35,
    AgentName.VERIFIER: 0.35,
    AgentName.RAG: 0.15,
    AgentName.ANALYTICS: 0.15,
}


@dataclass(frozen=True, slots=True)
class ConfidenceAggregationResult:
    confidence: float
    warnings: tuple[WarningMessage, ...] = ()


class ConfidenceAggregator:
    """Compute the weighted final confidence from successful agent outputs."""

    def aggregate(self, scores: dict[AgentName, float]) -> ConfidenceAggregationResult:
        self._validate_scores(scores)

        weighted_sum = 0.0
        used_weight = 0.0
        for agent_name, weight in CONFIDENCE_WEIGHTS.items():
            if agent_name not in scores:
                continue
            weighted_sum += scores[agent_name] * weight
            used_weight += weight

        confidence = 0.0 if used_weight == 0.0 else weighted_sum / used_weight
        rounded_confidence = round(confidence, 4)
        warning = low_confidence_warning(rounded_confidence)
        warnings = () if warning is None else (warning,)
        return ConfidenceAggregationResult(
            confidence=rounded_confidence,
            warnings=warnings,
        )

    def _validate_scores(self, scores: dict[AgentName, float]) -> None:
        for agent_name, score in scores.items():
            if agent_name not in CONFIDENCE_WEIGHTS:
                raise ValueError(f"unsupported confidence agent: {agent_name}")
            if not 0.0 <= score <= 1.0:
                raise ValueError("confidence score must be between 0.0 and 1.0")
