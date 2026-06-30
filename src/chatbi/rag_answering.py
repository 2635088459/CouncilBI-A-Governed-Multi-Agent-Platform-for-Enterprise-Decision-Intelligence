"""Question-answering use case for RAG v2.

This layer is intentionally thin. It calls the evidence service, builds a cited
explanation, and returns the trace-linked evidence events that observability can
inspect later.
"""

from __future__ import annotations

from dataclasses import dataclass

from chatbi.rag import EvidenceEvent, EvidenceSearchRequest, EvidenceSearchResult
from chatbi.rag_explanation import RagExplanation, build_rag_explanation
from chatbi.rag_service import InMemoryRagService


@dataclass(frozen=True, slots=True)
class RagAnswer:
    search_result: EvidenceSearchResult
    explanation: RagExplanation
    evidence_events: tuple[EvidenceEvent, ...]

    @property
    def has_evidence(self) -> bool:
        return bool(self.search_result.evidence_list)


class RagAnsweringService:
    """Turn an evidence search request into a cited RAG answer."""

    def __init__(self, rag_service: InMemoryRagService) -> None:
        self._rag_service = rag_service

    def answer(
        self,
        request: EvidenceSearchRequest,
        answer_intro: str = "I found document evidence for this answer.",
    ) -> RagAnswer:
        search_result = self._rag_service.search_evidence(request)
        explanation = build_rag_explanation(
            search_result=search_result,
            answer_intro=answer_intro,
        )
        evidence_events = self._rag_service.evidence_events_by_trace_id(request.trace_id)
        return RagAnswer(
            search_result=search_result,
            explanation=explanation,
            evidence_events=evidence_events,
        )
