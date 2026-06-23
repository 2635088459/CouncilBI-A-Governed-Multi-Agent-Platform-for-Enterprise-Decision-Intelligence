from datetime import datetime, timezone

import pytest

from chatbi.knowledge import (
    ChunkEmbedding,
    DocumentChunk,
    InMemoryKnowledgeStore,
    KnowledgeDocument,
    RetrievalQuery,
    chunk_text,
)


def make_document(
    source_id: str = "doc_001",
    doc_type: str = "report",
    publish_time: datetime = datetime(2026, 6, 1, tzinfo=timezone.utc),
) -> KnowledgeDocument:
    return KnowledgeDocument(
        source_id=source_id,
        title="Campaign report",
        doc_type=doc_type,
        publish_time=publish_time,
    )


def test_knowledge_store_saves_document_chunk_and_embedding() -> None:
    store = InMemoryKnowledgeStore()
    document = make_document()
    chunk = DocumentChunk(
        chunk_id="chunk_001",
        source_id=document.source_id,
        chunk_index=1,
        chunk_text="Revenue increased after campaign launch.",
        metadata={"page": 1},
    )
    embedding = ChunkEmbedding(
        embedding_id="emb_001",
        chunk_id=chunk.chunk_id,
        embedding_vector=(0.1, 0.2, 0.3),
    )

    store.save_document(document)
    store.save_chunk(chunk)
    store.save_embedding(embedding)
    records = store.list_chunk_records()

    assert len(records) == 1
    assert records[0].document == document
    assert records[0].chunk == chunk
    assert records[0].embedding == embedding


def test_knowledge_store_filters_chunks_by_doc_type_and_publish_time() -> None:
    store = InMemoryKnowledgeStore()
    report = make_document(
        source_id="doc_report",
        doc_type="report",
        publish_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    incident = make_document(
        source_id="doc_incident",
        doc_type="incident",
        publish_time=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    store.save_document(report)
    store.save_document(incident)
    store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_report",
            source_id=report.source_id,
            chunk_index=1,
            chunk_text="Campaign report text.",
        )
    )
    store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_incident",
            source_id=incident.source_id,
            chunk_index=1,
            chunk_text="Incident text.",
        )
    )

    records = store.list_chunk_records(
        doc_type="report",
        published_from=datetime(2026, 5, 15, tzinfo=timezone.utc),
        published_to=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )

    assert len(records) == 1
    assert records[0].document.source_id == "doc_report"


def test_knowledge_store_returns_evidence_items_with_source_id_and_snippet() -> None:
    store = InMemoryKnowledgeStore()
    document = make_document()
    store.save_document(document)
    store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_001",
            source_id=document.source_id,
            chunk_index=1,
            chunk_text="Revenue increased after campaign launch.",
        )
    )

    evidence_items = store.evidence_items()

    assert len(evidence_items) == 1
    assert evidence_items[0].source_id == "doc_001"
    assert evidence_items[0].title == "Campaign report"
    assert evidence_items[0].citation_anchor == "doc_001#chunk-1"
    assert evidence_items[0].snippet == "Revenue increased after campaign launch."
    assert evidence_items[0].publish_time == document.publish_time


def test_knowledge_store_rejects_chunk_for_unknown_document() -> None:
    store = InMemoryKnowledgeStore()

    with pytest.raises(ValueError, match="Unknown document source_id doc_missing"):
        store.save_chunk(
            DocumentChunk(
                chunk_id="chunk_001",
                source_id="doc_missing",
                chunk_index=1,
                chunk_text="Text.",
            )
        )


def test_knowledge_store_rejects_embedding_for_unknown_chunk() -> None:
    store = InMemoryKnowledgeStore()

    with pytest.raises(ValueError, match="Unknown chunk_id chunk_missing"):
        store.save_embedding(
            ChunkEmbedding(
                embedding_id="emb_001",
                chunk_id="chunk_missing",
                embedding_vector=(0.1,),
            )
        )


def test_chunk_text_uses_configured_overlap() -> None:
    chunks = chunk_text(
        "alpha beta gamma delta epsilon zeta eta theta",
        chunk_size=4,
        chunk_overlap=2,
    )

    assert chunks == (
        "alpha beta gamma delta",
        "gamma delta epsilon zeta",
        "epsilon zeta eta theta",
    )


def test_retrieval_excludes_out_of_permission_documents() -> None:
    store = InMemoryKnowledgeStore()
    public_document = make_document(source_id="doc_public")
    restricted_document = KnowledgeDocument(
        source_id="doc_restricted",
        title="Executive incident report",
        doc_type="incident",
        publish_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
        allowed_roles=("admin",),
    )
    store.save_document(public_document)
    store.save_document(restricted_document)
    store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_public",
            source_id=public_document.source_id,
            chunk_index=1,
            chunk_text="Revenue dropped after campaign spend paused.",
        )
    )
    store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_restricted",
            source_id=restricted_document.source_id,
            chunk_index=1,
            chunk_text="Revenue dropped because of a confidential executive incident.",
        )
    )

    result = store.retrieve(
        RetrievalQuery(
            question="Why did revenue drop?",
            user_role="business_user",
            top_k=5,
        ),
        trace_id="trc_permission",
    )

    assert tuple(item.source_id for item in result.evidence_list) == ("doc_public",)
    assert result.evidence_list[0].relevance_score > 0
    assert result.uncertainty is False
    assert result.trace_id == "trc_permission"


def test_retrieval_returns_uncertainty_when_filters_remove_all_candidates() -> None:
    store = InMemoryKnowledgeStore()
    document = make_document(source_id="doc_report", doc_type="report")
    store.save_document(document)
    store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_report",
            source_id=document.source_id,
            chunk_index=1,
            chunk_text="Revenue increased after campaign launch.",
        )
    )

    result = store.retrieve(
        RetrievalQuery(
            question="Why did revenue drop?",
            doc_type="incident",
        )
    )

    assert result.evidence_list == ()
    assert result.uncertainty is True
    assert result.confidence == 0.2
    assert "No relevant evidence" in result.explanation_text
    assert result.retrieval_stats.filtered_count == 0


def test_retrieval_merges_adjacent_chunks_from_same_document() -> None:
    store = InMemoryKnowledgeStore()
    document = make_document(source_id="doc_campaign")
    store.save_document(document)
    store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_1",
            source_id=document.source_id,
            chunk_index=1,
            chunk_text="Revenue dropped after campaign spend paused.",
        )
    )
    store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_2",
            source_id=document.source_id,
            chunk_index=2,
            chunk_text="The pause reduced paid traffic and new orders.",
        )
    )

    result = store.retrieve(
        RetrievalQuery(
            question="Why did revenue drop after campaign spend paused?",
            top_k=5,
        )
    )

    assert len(result.evidence_list) == 1
    assert result.evidence_list[0].citation_anchor == "doc_campaign#chunk-1"
    assert result.evidence_list[0].snippet == (
        "Revenue dropped after campaign spend paused. "
        "The pause reduced paid traffic and new orders."
    )
