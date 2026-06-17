"""RAG agent adapter for lightweight evidence payloads."""

from __future__ import annotations

from dataclasses import dataclass

from chatbi.core.contracts import EvidenceItem
from chatbi.orchestration.executor import AgentRunResult


@dataclass(frozen=True, slots=True)
class RagAgentRunner:
    """Return evidence items for explanation workflows."""

    evidence_items: tuple[EvidenceItem, ...]

    def run(self) -> AgentRunResult:
        if not self.evidence_items:
            raise ValueError("at least one evidence item is required")
        for item in self.evidence_items:
            if not item.source_id.strip():
                raise ValueError("evidence source_id is required")
            if not item.citation_anchor.strip():
                raise ValueError("evidence citation_anchor is required")

        return AgentRunResult(
            payload={
                "evidence_count": len(self.evidence_items),
                "evidence_items": self.evidence_items,
            },
            confidence=0.8,
        )
