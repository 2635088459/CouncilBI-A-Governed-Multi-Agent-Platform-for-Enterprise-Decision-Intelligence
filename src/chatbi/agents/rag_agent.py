"""RAG agent adapter for evidence-grounded explanation workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from chatbi.core.contracts import EvidenceItem, RetrievalStats
from chatbi.embedding_vector_rag import (
    EmbeddingClient,
    EmbeddingRequest,
    EvidenceChunk,
    MockEmbeddingClient,
    VectorStore,
)
from chatbi.knowledge import InMemoryKnowledgeStore, RetrievalQuery, RetrievalResult
from chatbi.orchestration.executor import AgentRunResult


class VectorRagRetriever(Protocol):
    def retrieve(
        self,
        *,
        trace_id: str,
        org_id: str,
        question: str,
        permission_tags: tuple[str, ...],
        limit: int,
    ) -> tuple[EvidenceChunk, ...]:
        ...


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
    requesting_user_id: str = ""
    metric_context: str = ""
    conversation_context: str = ""
    doc_type: str | None = None
    doc_types: tuple[str, ...] = ()
    published_from: datetime | None = None
    published_to: datetime | None = None
    user_role: str | None = None
    tags: tuple[str, ...] = ()
    top_k: int = 5
    trace_id: str = ""
    vector_retriever: VectorRagRetriever | None = None
    org_id: str = "org_legacy"
    permission_tags: tuple[str, ...] = ()

    def run(self) -> AgentRunResult:
        vector_result = self._retrieve_vector_if_possible()
        if vector_result is not None:
            return vector_result

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

    def _retrieve_vector_if_possible(self) -> AgentRunResult | None:
        if self.vector_retriever is None:
            return None
        if not self.question.strip():
            return None

        evidence_chunks = self.vector_retriever.retrieve(
            trace_id=self.trace_id,
            org_id=self.org_id,
            question=self.question,
            permission_tags=self.permission_tags,
            limit=self.top_k,
        )
        evidence_items = tuple(_evidence_item_from_vector_chunk(chunk) for chunk in evidence_chunks)
        retrieval_stats = RetrievalStats(
            candidate_count=len(evidence_chunks),
            filtered_count=len(evidence_chunks),
            reranked_count=len(evidence_chunks),
            selected_count=len(evidence_chunks),
            latency_ms=0.0,
        )
        return AgentRunResult(
            payload={
                "evidence_count": len(evidence_items),
                "evidence_items": evidence_items,
                "uncertainty": not evidence_items,
                "retrieval_stats": retrieval_stats,
                "trace_id": self.trace_id,
            },
            confidence=0.8 if evidence_items else 0.2,
        )

    def _retrieve_if_possible(self) -> RetrievalResult | None:
        if self.knowledge_store is None:
            return None
        if not self.question.strip():
            return None

        return self.knowledge_store.retrieve(
            RetrievalQuery(
                question=self.question,
                requesting_user_id=self.requesting_user_id,
                metric_context=self.metric_context,
                conversation_context=self.conversation_context,
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
            requesting_user_id=self.requesting_user_id,
        )

    def _validate_evidence_items(self, evidence_items: tuple[EvidenceItem, ...]) -> None:
        for item in evidence_items:
            if not item.source_id.strip():
                raise ValueError("evidence source_id is required")
            if not item.citation_anchor.strip():
                raise ValueError("evidence citation_anchor is required")


class InMemoryVectorRagRetriever:
    def __init__(
        self,
        vector_store: VectorStore,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self._vector_store = vector_store
        self._embedding_client = embedding_client or MockEmbeddingClient()

    def retrieve(
        self,
        *,
        trace_id: str,
        org_id: str,
        question: str,
        permission_tags: tuple[str, ...],
        limit: int,
    ) -> tuple[EvidenceChunk, ...]:
        query_response = self._embedding_client.embed(
            EmbeddingRequest(
                trace_id=trace_id,
                org_id=org_id,
                input_texts=(question,),
            )
        )
        return self._vector_store.search(
            trace_id=trace_id,
            org_id=org_id,
            query_vector=query_response.vectors[0],
            permission_tags=permission_tags,
            limit=limit,
        )


def _evidence_item_from_vector_chunk(chunk: EvidenceChunk) -> EvidenceItem:
    title = chunk.citation.get("title")
    return EvidenceItem(
        source_id=chunk.document_id,
        title=title if isinstance(title, str) else chunk.document_id,
        citation_anchor=f"{chunk.document_id}#{chunk.chunk_id}",
        snippet=chunk.text,
        relevance_score=chunk.score,
    )
