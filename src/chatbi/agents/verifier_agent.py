"""Verifier agent adapter for lightweight answer verification payloads."""

from __future__ import annotations

from dataclasses import dataclass

from chatbi.orchestration.executor import AgentRunResult


@dataclass(frozen=True, slots=True)
class VerifierAgentRunner:
    """Return a minimal verification payload for completed branches."""

    verified: bool
    confidence: float
    reason: str

    def run(self) -> AgentRunResult:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if not self.reason.strip():
            raise ValueError("reason is required")

        return AgentRunResult(
            payload={
                "verified": self.verified,
                "reason": self.reason,
            },
            confidence=self.confidence,
        )
