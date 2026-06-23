"""RAG agent adapter for evidence-grounded explanation workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from chatbi.core.contracts import EvidenceItem
from chatbi.knowledge import InMemoryKnowledgeStore, RetrievalQuery, RetrievalResult
from chatbi.orchestration.executor import AgentRunResult


@dataclass(frozen=True, slots=True)
class RagAgentRunner:
    """Retrieve and return evidence items for why-explanation workflows.

    Think of this class as the RAG "agent shell":
    - it does not know how scoring works;
    - it knows what question and filters to send to the knowledge store;
    - it shapes the retrieval result into the standard agent payload.
    """

    evidence_items: tuple[EvidenceItem, ...] = ()
    knowledge_store: InMemoryKnowledgeStore | None = None
    question: str = ""
    metric_context: str = ""
    doc_type: str | None = None
    doc_types: tuple[str, ...] = ()
    published_from: datetime | None = None
    published_to: datetime | None = None
    user_role: str | None = None
    tags: tuple[str, ...] = ()
    top_k: int = 5
    trace_id: str = ""

    def run(self) -> AgentRunResult:
        retrieval_result = self._retrieve_if_possible()
        if retrieval_result is not None:
            return self._agent_result_from_retrieval(retrieval_result)

        evidence_items = self._resolve_static_evidence_items()
        if not evidence_items:
            raise ValueError("at least one evidence item is required")
        self._validate_evidence_items(evidence_items)

        return AgentRunResult(
            payload={
                "evidence_count": len(evidence_items),
                "evidence_items": evidence_items,
            },
            confidence=0.8,
        )

    def _retrieve_if_possible(self) -> RetrievalResult | None:
        if self.knowledge_store is None:
            return None
        if not self.question.strip():
            return None

        return self.knowledge_store.retrieve(
            RetrievalQuery(
                question=self.question,
                metric_context=self.metric_context,
                doc_type=self.doc_type,
                doc_types=self.doc_types,
                published_from=self.published_from,
                published_to=self.published_to,
                user_role=self.user_role,
                tags=self.tags,
                top_k=self.top_k,
            ),
            trace_id=self.trace_id,
        )

    def _agent_result_from_retrieval(self, retrieval_result: RetrievalResult) -> AgentRunResult:
        self._validate_evidence_items(retrieval_result.evidence_list)
        return AgentRunResult(
            payload={
                "evidence_count": len(retrieval_result.evidence_list),
                "evidence_items": retrieval_result.evidence_list,
                "explanation_text": retrieval_result.explanation_text,
                "uncertainty": retrieval_result.uncertainty,
                "retrieval_stats": retrieval_result.retrieval_stats,
                "trace_id": retrieval_result.trace_id,
            },
            confidence=retrieval_result.confidence,
        )

    def _resolve_static_evidence_items(self) -> tuple[EvidenceItem, ...]:
        if self.evidence_items:
            return self.evidence_items
        if self.knowledge_store is None:
            return ()
        return self.knowledge_store.evidence_items(
            doc_type=self.doc_type,
            doc_types=self.doc_types,
            published_from=self.published_from,
            published_to=self.published_to,
            user_role=self.user_role,
            tags=self.tags,
        )

    def _validate_evidence_items(self, evidence_items: tuple[EvidenceItem, ...]) -> None:
        for item in evidence_items:
            if not item.source_id.strip():
                raise ValueError("evidence source_id is required")
            if not item.citation_anchor.strip():
                raise ValueError("evidence citation_anchor is required")
