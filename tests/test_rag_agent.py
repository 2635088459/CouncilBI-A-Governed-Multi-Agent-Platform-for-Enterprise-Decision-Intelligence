from datetime import datetime, timezone
from typing import cast

import pytest

from chatbi.agents.rag_agent import RagAgentRunner
from chatbi.core.contracts import EvidenceItem, RetrievalStats
from chatbi.embedding_vector_rag import (
    DocumentRecord,
    EmbeddingVectorRagService,
    InMemoryVectorStore,
    MockEmbeddingClient,
    ingest_document,
)
from chatbi.knowledge import (
    DocumentChunk,
    InMemoryKnowledgeStore,
    KnowledgeDocument,
)


def make_evidence_item(citation_anchor: str = "doc_001#p1") -> EvidenceItem:
    return EvidenceItem(
        source_id="doc_001",
        title="Campaign report",
        citation_anchor=citation_anchor,
        snippet="Revenue increased after campaign launch.",
    )


def test_rag_agent_returns_evidence_payload() -> None:
    evidence = (make_evidence_item(),)
    runner = RagAgentRunner(evidence_items=evidence)

    result = runner.run()

    assert result.payload == {
        "evidence_count": 1,
        "evidence_items": evidence,
    }
    assert result.confidence == 0.8


def test_rag_agent_requires_at_least_one_evidence_item() -> None:
    runner = RagAgentRunner(evidence_items=())

    with pytest.raises(ValueError, match="evidence item"):
        runner.run()


def test_rag_agent_requires_citation_anchor() -> None:
    runner = RagAgentRunner(evidence_items=(make_evidence_item(citation_anchor=" "),))

    with pytest.raises(ValueError, match="citation_anchor"):
        runner.run()


def test_rag_agent_returns_evidence_from_knowledge_store() -> None:
    store = InMemoryKnowledgeStore()
    store.save_document(
        KnowledgeDocument(
            source_id="doc_001",
            title="Campaign report",
            doc_type="report",
            publish_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
    )
    store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_001",
            source_id="doc_001",
            chunk_index=1,
            chunk_text="Revenue increased after campaign launch.",
        )
    )
    runner = RagAgentRunner(knowledge_store=store)

    result = runner.run()
    evidence_items = cast(tuple[EvidenceItem, ...], result.payload["evidence_items"])

    assert result.payload["evidence_count"] == 1
    assert evidence_items[0].source_id == "doc_001"
    assert evidence_items[0].citation_anchor == "doc_001#chunk-1"


def test_rag_agent_filters_knowledge_store_by_doc_type() -> None:
    store = InMemoryKnowledgeStore()
    store.save_document(
        KnowledgeDocument(
            source_id="doc_report",
            title="Campaign report",
            doc_type="report",
            publish_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
    )
    store.save_document(
        KnowledgeDocument(
            source_id="doc_incident",
            title="Incident note",
            doc_type="incident",
            publish_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
    )
    store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_report",
            source_id="doc_report",
            chunk_index=1,
            chunk_text="Report text.",
        )
    )
    store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_incident",
            source_id="doc_incident",
            chunk_index=1,
            chunk_text="Incident text.",
        )
    )
    runner = RagAgentRunner(knowledge_store=store, doc_type="incident")

    result = runner.run()
    evidence_items = cast(tuple[EvidenceItem, ...], result.payload["evidence_items"])

    assert result.payload["evidence_count"] == 1
    assert evidence_items[0].source_id == "doc_incident"


def test_rag_agent_retrieves_evidence_for_question_payload() -> None:
    store = InMemoryKnowledgeStore()
    store.save_document(
        KnowledgeDocument(
            source_id="doc_campaign",
            title="Campaign report",
            doc_type="report",
            publish_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
    )
    store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_campaign",
            source_id="doc_campaign",
            chunk_index=1,
            chunk_text="Revenue dropped after campaign spend paused.",
        )
    )
    runner = RagAgentRunner(
        knowledge_store=store,
        question="Why did revenue drop?",
        metric_context="revenue by month",
        trace_id="trc_rag_agent",
    )

    result = runner.run()
    evidence_items = cast(tuple[EvidenceItem, ...], result.payload["evidence_items"])
    retrieval_stats = cast(RetrievalStats, result.payload["retrieval_stats"])

    assert result.payload["evidence_count"] == 1
    assert evidence_items[0].source_id == "doc_campaign"
    assert result.payload["uncertainty"] is False
    assert result.payload["trace_id"] == "trc_rag_agent"
    assert retrieval_stats.selected_count == 1
    assert retrieval_stats.filtered_count == 1
    assert result.confidence > 0.6


def test_rag_agent_returns_uncertainty_when_retrieval_has_no_evidence() -> None:
    store = InMemoryKnowledgeStore()
    store.save_document(
        KnowledgeDocument(
            source_id="doc_report",
            title="Campaign report",
            doc_type="report",
            publish_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
    )
    store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_report",
            source_id="doc_report",
            chunk_index=1,
            chunk_text="Revenue increased after campaign launch.",
        )
    )
    runner = RagAgentRunner(
        knowledge_store=store,
        question="Why did revenue drop?",
        doc_type="incident",
        trace_id="trc_no_evidence",
    )

    result = runner.run()
    retrieval_stats = cast(RetrievalStats, result.payload["retrieval_stats"])

    assert result.payload["evidence_count"] == 0
    assert result.payload["evidence_items"] == ()
    assert result.payload["uncertainty"] is True
    assert result.payload["trace_id"] == "trc_no_evidence"
    assert retrieval_stats.filtered_count == 0
    assert result.confidence == 0.2


def test_rag_agent_retrieves_evidence_from_vector_store() -> None:
    embedding_client = MockEmbeddingClient()
    vector_store = InMemoryVectorStore()
    ingest_document(
        trace_id="trc_rag_vector_ingest",
        document=DocumentRecord(
            document_id="doc_vector_revenue",
            org_id="org_vector",
            title="Revenue Vector Policy",
            source_type="policy",
            owner_user_id="u_owner",
            version="v1",
            access_policy={"permission_tags": ("finance",)},
        ),
        text="Revenue recognition requires finance approval and signed contracts.",
        embedding_client=embedding_client,
        vector_store=vector_store,
    )
    from chatbi.agents.rag_agent import InMemoryVectorRagRetriever

    runner = RagAgentRunner(
        vector_retriever=InMemoryVectorRagRetriever(vector_store, embedding_client),
        question="What supports revenue recognition?",
        trace_id="trc_rag_vector_agent",
        org_id="org_vector",
        permission_tags=("finance",),
    )

    result = runner.run()
    evidence_items = cast(tuple[EvidenceItem, ...], result.payload["evidence_items"])

    assert result.payload["evidence_count"] == 1
    assert evidence_items[0].source_id == "doc_vector_revenue"
    assert evidence_items[0].title == "Revenue Vector Policy"
    assert evidence_items[0].citation_anchor == "doc_vector_revenue#doc_vector_revenue_chunk_1"
    assert result.payload["uncertainty"] is False


def test_rag_agent_returns_uncertainty_when_vector_store_has_no_evidence() -> None:
    from chatbi.agents.rag_agent import InMemoryVectorRagRetriever

    runner = RagAgentRunner(
        vector_retriever=InMemoryVectorRagRetriever(InMemoryVectorStore()),
        question="What supports revenue recognition?",
        trace_id="trc_rag_vector_empty",
        org_id="org_vector",
        permission_tags=("finance",),
    )

    result = runner.run()
    retrieval_stats = cast(RetrievalStats, result.payload["retrieval_stats"])

    assert result.payload["evidence_count"] == 0
    assert result.payload["evidence_items"] == ()
    assert result.payload["uncertainty"] is True
    assert retrieval_stats.selected_count == 0
    assert result.confidence == 0.2


def test_rag_agent_can_use_embedding_vector_rag_service_directly() -> None:
    service = EmbeddingVectorRagService()
    service.index_document(
        trace_id="trc_rag_service_index",
        document=DocumentRecord(
            document_id="doc_service_revenue",
            org_id="org_service",
            title="Service Revenue Policy",
            source_type="policy",
            owner_user_id="u_owner",
            version="v1",
            access_policy={"permission_tags": ("finance",)},
        ),
        text="Revenue recognition requires finance approval.",
    )
    runner = RagAgentRunner(
        vector_retriever=service,
        question="What supports revenue recognition?",
        trace_id="trc_rag_service_agent",
        org_id="org_service",
        permission_tags=("finance",),
    )

    result = runner.run()
    evidence_items = cast(tuple[EvidenceItem, ...], result.payload["evidence_items"])

    assert result.payload["evidence_count"] == 1
    assert evidence_items[0].source_id == "doc_service_revenue"
    assert evidence_items[0].citation_anchor == "doc_service_revenue#doc_service_revenue_chunk_1"
