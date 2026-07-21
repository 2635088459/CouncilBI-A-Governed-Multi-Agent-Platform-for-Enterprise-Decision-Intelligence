import sys
import types
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import pytest

from chatbi.embedding_vector_rag import EmbeddingRequest, EmbeddingResponse
from chatbi.knowledge import (
    BgeCrossEncoderReranker,
    Bm25CandidateScorer,
    ChunkEmbedding,
    DocumentChunk,
    InMemoryKnowledgeStore,
    KnowledgeChunkRecord,
    KnowledgeDocument,
    RetrievalQuery,
    chunk_text,
    cjk_and_ascii_tokens,
    clean_document_text,
    normalize_scores,
    rerank,
    text_embedding,
)


@dataclass
class FakeEmbeddingClient:
    """FR-FV03-014 test double: a real EmbeddingClient implementation that
    returns a fixed, recognizable vector distinct from text_embedding()'s
    hash-bucket output, so tests can tell which one was actually used."""

    provider_name: str = "fake"
    vector: tuple[float, ...] = (9.0, 9.0, 9.0)

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        return EmbeddingResponse(
            vectors=(self.vector,),
            provider=self.provider_name,
            model_name=request.model_name,
            dimensions=len(self.vector),
            token_count=0,
            estimated_cost=0.0,
            latency_ms=0,
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
            requesting_user_id="u_001",
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
            requesting_user_id="u_001",
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
            requesting_user_id="u_001",
            top_k=5,
        )
    )

    assert len(result.evidence_list) == 1
    assert result.evidence_list[0].citation_anchor == "doc_campaign#chunk-1"
    assert result.evidence_list[0].snippet == (
        "Revenue dropped after campaign spend paused. "
        "The pause reduced paid traffic and new orders."
    )


def _owned_document_with_chunk(store: InMemoryKnowledgeStore, owner_user_id: str) -> KnowledgeDocument:
    document = KnowledgeDocument(
        source_id=f"doc_owned_by_{owner_user_id}",
        title="Analyst's private runbook",
        doc_type="report",
        publish_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
        owner_user_id=owner_user_id,
    )
    store.save_document(document)
    store.save_chunk(
        DocumentChunk(
            chunk_id=f"chunk_owned_by_{owner_user_id}",
            source_id=document.source_id,
            chunk_index=1,
            chunk_text="Escalate P1 incidents to the on-call engineer within 15 minutes.",
        )
    )
    return document


def test_retrieve_returns_document_owned_by_the_requesting_user() -> None:
    # TC-FV10-107
    store = InMemoryKnowledgeStore()
    document = _owned_document_with_chunk(store, owner_user_id="U1")

    result = store.retrieve(
        RetrievalQuery(
            question="Escalate P1 incidents to the on-call engineer",
            requesting_user_id="U1",
        )
    )

    assert tuple(item.source_id for item in result.evidence_list) == (document.source_id,)


def test_retrieve_excludes_document_owned_by_a_different_user() -> None:
    # TC-FV10-108 / NFR-FV10-011
    store = InMemoryKnowledgeStore()
    _owned_document_with_chunk(store, owner_user_id="U1")

    result = store.retrieve(
        RetrievalQuery(
            question="Escalate P1 incidents to the on-call engineer",
            requesting_user_id="U2",
        )
    )

    assert result.evidence_list == ()


def test_retrieve_returns_baseline_document_regardless_of_requesting_user() -> None:
    # TC-FV10-109
    store = InMemoryKnowledgeStore()
    baseline_document = make_document(source_id="doc_baseline")
    store.save_document(baseline_document)
    store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_baseline",
            source_id=baseline_document.source_id,
            chunk_index=1,
            chunk_text="Revenue increased after campaign launch.",
        )
    )

    result = store.retrieve(
        RetrievalQuery(
            question="Revenue increased after campaign launch.",
            requesting_user_id="any_user",
        )
    )

    assert tuple(item.source_id for item in result.evidence_list) == ("doc_baseline",)


def test_save_document_accepts_both_baseline_and_owned_documents() -> None:
    # TC-FV10-110
    store = InMemoryKnowledgeStore()

    store.save_document(make_document(source_id="doc_baseline_ok"))
    store.save_document(
        KnowledgeDocument(
            source_id="doc_owned_ok",
            title="Owned doc",
            doc_type="report",
            publish_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
            owner_user_id="U1",
        )
    )

    baseline_doc = store._documents_by_source_id["doc_baseline_ok"]  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    owned_doc = store._documents_by_source_id["doc_owned_ok"]  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    assert baseline_doc.owner_user_id is None
    assert owned_doc.owner_user_id == "U1"


def test_retrieve_includes_owned_document_once_shared_visibility_authorizes_requester() -> None:
    # TC-FV10-111: stubs the Spec FV10.2 share lookup this store defers to.
    document_id = "doc_shared_with_u2"

    def shared_visibility(document: KnowledgeDocument) -> frozenset[str]:
        if document.source_id == document_id:
            return frozenset({"U2"})
        return frozenset()

    store = InMemoryKnowledgeStore(shared_visibility_resolver=shared_visibility)
    document = KnowledgeDocument(
        source_id=document_id,
        title="Analyst's shared runbook",
        doc_type="report",
        publish_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
        owner_user_id="U1",
    )
    store.save_document(document)
    store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_shared_with_u2",
            source_id=document_id,
            chunk_index=1,
            chunk_text="Escalate P1 incidents to the on-call engineer within 15 minutes.",
        )
    )

    unauthorized_result = store.retrieve(
        RetrievalQuery(
            question="Escalate P1 incidents to the on-call engineer",
            requesting_user_id="U3",
        )
    )
    authorized_result = store.retrieve(
        RetrievalQuery(
            question="Escalate P1 incidents to the on-call engineer",
            requesting_user_id="U2",
        )
    )

    assert unauthorized_result.evidence_list == ()
    assert tuple(item.source_id for item in authorized_result.evidence_list) == (document_id,)


def test_conversation_context_helps_a_pronoun_only_query_match_the_right_document() -> None:
    # Spec FV10.4 FR-FV10-052/056: a follow-up like "why did that happen?"
    # carries no subject of its own — conversation_context supplies it.
    store = InMemoryKnowledgeStore()
    document = make_document(source_id="doc_campaign_pause")
    store.save_document(document)
    store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_campaign_pause",
            source_id=document.source_id,
            chunk_index=1,
            chunk_text="Revenue dropped after campaign spend paused in July.",
        )
    )

    without_context = store.retrieve(
        RetrievalQuery(
            question="Why did that happen?",
            requesting_user_id="u_001",
        )
    )
    with_context = store.retrieve(
        RetrievalQuery(
            question="Why did that happen?",
            requesting_user_id="u_001",
            conversation_context="Why did revenue drop after the campaign spend paused?",
        )
    )

    assert tuple(item.source_id for item in with_context.evidence_list) == ("doc_campaign_pause",)
    # With no keyword overlap of its own, the question only clears the
    # relevance floor on baseline source-weight; conversation_context
    # supplies the missing subject and measurably raises the score.
    assert with_context.evidence_list[0].relevance_score > without_context.evidence_list[0].relevance_score


def test_conversation_context_defaults_to_empty_and_does_not_change_baseline_ranking() -> None:
    # NFR-FV10-018: a first-turn query (no conversation_context) must rank
    # identically to how it did before this field existed.
    store = InMemoryKnowledgeStore()
    document = make_document(source_id="doc_campaign")
    store.save_document(document)
    store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_campaign",
            source_id=document.source_id,
            chunk_index=1,
            chunk_text="Revenue dropped after campaign spend paused.",
        )
    )

    result = store.retrieve(
        RetrievalQuery(question="Why did revenue drop?", requesting_user_id="u_001")
    )

    assert tuple(item.source_id for item in result.evidence_list) == ("doc_campaign",)
    assert result.evidence_list[0].relevance_score > 0


def test_embed_text_uses_constructor_embedding_client_when_provided() -> None:
    # AC-FV03-009: a real embedding client, wired in at construction, must
    # govern embed_text()'s output instead of the deterministic fallback.
    fake_client = FakeEmbeddingClient(vector=(9.0, 9.0, 9.0))
    store = InMemoryKnowledgeStore(embedding_client=fake_client)

    vector = store.embed_text("Revenue dropped after campaign spend paused.")

    assert vector == (9.0, 9.0, 9.0)
    assert vector != text_embedding("Revenue dropped after campaign spend paused.")


def test_embed_text_method_level_client_takes_precedence_over_constructor_client() -> None:
    # FR-FV03-014: the ingest_document()-level embedding_client argument
    # takes precedence over the constructor-level one.
    constructor_client = FakeEmbeddingClient(vector=(1.0, 1.0, 1.0))
    method_client = FakeEmbeddingClient(vector=(2.0, 2.0, 2.0))
    store = InMemoryKnowledgeStore(embedding_client=constructor_client)

    vector = store.embed_text("some chunk text", embedding_client=method_client)

    assert vector == (2.0, 2.0, 2.0)


def test_embed_text_falls_back_to_deterministic_embedding_with_no_client() -> None:
    # AC-FV03-010 / NFR-FV03-006: no embedding_client anywhere means
    # embed_text() must produce byte-identical output to text_embedding().
    store = InMemoryKnowledgeStore()

    assert store.embed_text("Revenue dropped after campaign spend paused.") == text_embedding(
        "Revenue dropped after campaign spend paused."
    )


def test_ingest_document_stores_real_embedding_client_vector_not_hash_bucket() -> None:
    # TC-FV03-015 / AC-FV03-009: ingest_document() with a fake EmbeddingClient
    # stores the fake client's returned vector as the chunk's
    # embedding_vector, not text_embedding()'s output.
    fake_client = FakeEmbeddingClient(vector=(9.0, 9.0, 9.0))
    store = InMemoryKnowledgeStore(embedding_client=fake_client)
    document = make_document(source_id="doc_ingested")

    records = store.ingest_document(document, "Revenue dropped after campaign spend paused.")

    assert len(records) == 1
    assert records[0].embedding is not None
    assert records[0].embedding.embedding_vector == (9.0, 9.0, 9.0)


def test_ingest_document_with_no_embedding_client_matches_pre_spec_deterministic_output() -> None:
    # TC-FV03-016 / AC-FV03-010: ingest_document() with no embedding_client
    # anywhere stores exactly the same embedding_vector values as before
    # FR-FV03-014 — a regression guard against silently changing this
    # store's default (test-friendly, offline) behavior.
    store = InMemoryKnowledgeStore()
    document = make_document(source_id="doc_ingested_default")
    raw_text = "Revenue dropped after campaign spend paused."

    records = store.ingest_document(document, raw_text)

    assert len(records) == 1
    assert records[0].embedding is not None
    # ingest_document() chunks clean_document_text(raw_text) before embedding
    # each chunk; for a short single-chunk document the cleaned text and the
    # chunk text are identical, so this mirrors that exactly.
    assert records[0].embedding.embedding_vector == text_embedding(clean_document_text(raw_text))


def make_scored_record(source_id: str, chunk_text_value: str) -> KnowledgeChunkRecord:
    document = make_document(source_id=source_id)
    chunk = DocumentChunk(
        chunk_id=f"{source_id}_chunk_1",
        source_id=source_id,
        chunk_index=1,
        chunk_text=chunk_text_value,
    )
    return KnowledgeChunkRecord(document=document, chunk=chunk)


def test_cjk_and_ascii_tokens_returns_both_ascii_words_and_cjk_unigrams() -> None:
    # TC-FV03-024: mixed Chinese/English text yields ASCII word tokens plus
    # individual CJK characters.
    tokens = cjk_and_ascii_tokens("Revenue 收入 dropped 下降 in July")

    assert "revenue" in tokens
    assert "dropped" in tokens
    assert "july" in tokens
    assert "收" in tokens
    assert "入" in tokens
    assert "下" in tokens
    assert "降" in tokens


def test_normalize_scores_all_equal_input_returns_neutral_midpoint() -> None:
    # TC-FV03-025 (revised): an all-equal input (e.g. a single-candidate
    # corpus, where BM25Okapi degenerates to identical scores) must not
    # divide by zero, and must not collapse to 0.0 either — a 1-document
    # corpus's BM25 IDF term is itself sign-unreliable (a term appearing in
    # 100% of a 1-document corpus reads as "common"), so 0.0 would actively
    # (and wrongly) argue against a genuine single-candidate match. 0.5 is
    # neutral: it defers to the vector/source-weight terms instead.
    assert normalize_scores((3.0, 3.0, 3.0)) == (0.5, 0.5, 0.5)
    assert normalize_scores(()) == ()
    assert normalize_scores((0.0,)) == (0.5,)


def test_normalize_scores_maps_max_to_one_and_min_to_zero() -> None:
    # TC-FV03-026 / AC-FV03-015: normalized scores fall within [0.0, 1.0].
    normalized = normalize_scores((1.0, 3.0, 5.0))

    assert normalized[0] == 0.0
    assert normalized[2] == 1.0
    assert all(0.0 <= score <= 1.0 for score in normalized)


def test_bm25_candidate_scorer_ranks_rare_term_chunk_above_common_term_chunk() -> None:
    # TC-FV03-023 / AC-FV03-013: BM25's IDF weighting must rank a chunk
    # containing a rare term above a chunk matched only by an equally
    # frequent but corpus-common term — the prior Jaccard-overlap
    # implementation would have scored both identically whenever
    # token-set-intersection size was equal.
    records = (
        make_scored_record(
            "doc_rare",
            "The employer liability insurance clause covers workplace injury.",
        ),
        make_scored_record("doc_common_1", "The report covers monthly revenue."),
        make_scored_record("doc_common_2", "The report covers monthly expenses."),
        make_scored_record("doc_common_3", "The report covers quarterly revenue."),
    )
    scorer = Bm25CandidateScorer(records)

    query_tokens = cjk_and_ascii_tokens("employer liability insurance clause")
    # normalize_scores() is a monotonic (min-max) transform, so comparing the
    # public, normalized scores() output preserves the same ordering the
    # raw BM25 scores would show, without reaching into the private index.
    scores = scorer.scores(query_tokens)

    assert scores[0] > scores[1]
    assert scores[0] > scores[2]
    assert scores[0] > scores[3]


def test_rank_records_scores_chinese_chunk_against_chinese_question() -> None:
    # TC-FV03-027 / AC-FV03-014 / NFR-FV03-008: a chunk containing only
    # Chinese text must not score zero on the keyword term purely because
    # of tokenization — keyword_score must contribute a nonzero amount on
    # top of the baseline source_score alone.
    store = InMemoryKnowledgeStore()
    document = make_document(source_id="doc_chinese")
    store.save_document(document)
    store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_chinese",
            source_id="doc_chinese",
            chunk_index=1,
            chunk_text="收入下降是因为营销预算暂停了。",
        )
    )

    result = store.retrieve(
        RetrievalQuery(question="收入为什么下降？", requesting_user_id="u_001")
    )

    assert tuple(item.source_id for item in result.evidence_list) == ("doc_chinese",)
    # source_score alone (baseline doc_type "report") is 0.02 — see
    # _source_weight()'s weights dict. This single-chunk corpus also hits
    # normalize_scores()'s degenerate (single-candidate) branch, so
    # keyword_score is the neutral 0.5, not 0.0: relevance_score =
    # 0.5*0.60 + 0.0*0.35 + 0.02 = 0.32. Asserting the exact value (not
    # just "> 0.02") is deliberate: a prior version of this test asserted
    # "> 0.01" against an incorrect assumption about source_score's actual
    # value, which passed even when keyword_score contributed nothing.
    assert result.evidence_list[0].relevance_score == 0.32


def test_rank_records_builds_a_fresh_bm25_index_per_call() -> None:
    # TC-FV03-028 / AC-FV03-016: _rank_records() must not reuse a BM25 index
    # across calls with different candidate sets — each call's IDF
    # statistics must reflect only that call's own filtered_records.
    store = InMemoryKnowledgeStore()
    small_candidate_set = (make_scored_record("doc_a", "revenue dropped after campaign"),)
    large_candidate_set = small_candidate_set + tuple(
        make_scored_record(f"doc_noise_{i}", "revenue dropped after campaign")
        for i in range(1, 21)
    )

    query = RetrievalQuery(question="revenue dropped after campaign", requesting_user_id="u_001")
    query_text = query.question
    query_embedding = store.embed_text(query_text)
    small_scores = store._rank_records(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        small_candidate_set, query, query_text, query_embedding
    )
    large_scores = store._rank_records(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        large_candidate_set, query, query_text, query_embedding
    )

    # Every chunk in both sets contains identical text, so within a single,
    # freshly-built index every candidate must score identically to its
    # siblings in that same call — proving each call built its own index
    # rather than reusing (or being skewed by) the other call's corpus size.
    assert len({round(record.relevance_score, 4) for record in small_scores}) == 1
    assert len({round(record.relevance_score, 4) for record in large_scores}) == 1


def test_retrieve_ranks_rare_term_chunk_above_common_word_chunk_end_to_end() -> None:
    # TC-FV03-029: end-to-end confirmation through retrieve()'s full
    # filter -> rank -> dedupe pipeline, not just the isolated scorer.
    store = InMemoryKnowledgeStore()
    store.save_document(make_document(source_id="doc_rare"))
    store.save_chunk(
        DocumentChunk(
            chunk_id="doc_rare_chunk_1",
            source_id="doc_rare",
            chunk_index=1,
            chunk_text="The employer liability insurance clause covers workplace injury.",
        )
    )
    store.save_document(make_document(source_id="doc_common"))
    store.save_chunk(
        DocumentChunk(
            chunk_id="doc_common_chunk_1",
            source_id="doc_common",
            chunk_index=1,
            chunk_text="The report covers monthly revenue and expenses.",
        )
    )

    result = store.retrieve(
        RetrievalQuery(
            question="employer liability insurance clause",
            requesting_user_id="u_001",
            top_k=2,
        )
    )

    assert result.evidence_list[0].source_id == "doc_rare"


def test_retrieve_tenant_isolation_bm25_scores_unaffected_by_excluded_owner_corpus_size() -> None:
    # TC-FV03-030 / AC-FV03-016: a document a requester cannot see (owned by
    # a different user) must not influence this requester's BM25 scores,
    # regardless of how many such excluded documents share the same term —
    # confirms list_chunk_records()'s permission filtering happens before
    # BM25 index construction, not after.
    store = InMemoryKnowledgeStore()
    store.save_document(make_document(source_id="doc_visible"))
    store.save_chunk(
        DocumentChunk(
            chunk_id="doc_visible_chunk_1",
            source_id="doc_visible",
            chunk_index=1,
            chunk_text="revenue dropped after campaign spend paused",
        )
    )
    query = RetrievalQuery(
        question="revenue dropped after campaign spend paused",
        requesting_user_id="u_001",
    )
    baseline_result = store.retrieve(query)
    baseline_score = baseline_result.evidence_list[0].relevance_score

    for index in range(20):
        owned_document = KnowledgeDocument(
            source_id=f"doc_owned_by_other_{index}",
            title="Private document",
            doc_type="report",
            publish_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
            owner_user_id="u_other",
        )
        store.save_document(owned_document)
        store.save_chunk(
            DocumentChunk(
                chunk_id=f"doc_owned_by_other_{index}_chunk_1",
                source_id=owned_document.source_id,
                chunk_index=1,
                chunk_text="revenue dropped after campaign spend paused",
            )
        )

    result_after_noise = store.retrieve(query)

    assert result_after_noise.evidence_list[0].source_id == "doc_visible"
    assert result_after_noise.evidence_list[0].relevance_score == baseline_score


@dataclass
class FakeCrossEncoderReranker:
    """FR-FV03-021 test double: scores pairs via a caller-supplied
    function, so tests can pin down the reranked order precisely."""

    score_fn: Callable[[tuple[tuple[str, str], ...]], tuple[float, ...]]

    def score(self, pairs: tuple[tuple[str, str], ...]) -> tuple[float, ...]:
        return self.score_fn(pairs)


@dataclass
class RaisingCrossEncoderReranker:
    def score(self, pairs: tuple[tuple[str, str], ...]) -> tuple[float, ...]:
        raise RuntimeError("reranker exploded")


def test_rerank_with_fake_reranker_reverses_order() -> None:
    # TC-FV03-031 / AC-FV03-017 mechanism test.
    candidates = (
        make_scored_record("doc_a", "first"),
        make_scored_record("doc_b", "second"),
        make_scored_record("doc_c", "third"),
    )
    reversed_scores = FakeCrossEncoderReranker(
        score_fn=lambda pairs: tuple(float(index) for index in range(len(pairs)))
    )

    reranked, did_rerank = rerank("question", candidates, reversed_scores)

    assert tuple(record.document.source_id for record in reranked) == ("doc_c", "doc_b", "doc_a")
    assert did_rerank is True


def test_rerank_with_no_reranker_returns_candidates_unchanged() -> None:
    # TC-FV03-032.
    candidates = (make_scored_record("doc_a", "first"), make_scored_record("doc_b", "second"))

    reranked, did_rerank = rerank("question", candidates, None)

    assert reranked == candidates
    assert did_rerank is False


def test_rerank_falls_back_to_pre_rerank_order_when_reranker_raises() -> None:
    # TC-FV03-033 / AC-FV03-019: a reranker error must not propagate — the
    # candidates come back in their pre-rerank hybrid order, and did_rerank
    # reports False so callers can tell this was a fallback, not a genuine
    # rerank pass (fixed after code review found reranked_count previously
    # couldn't distinguish the two).
    candidates = (make_scored_record("doc_a", "first"), make_scored_record("doc_b", "second"))

    reranked, did_rerank = rerank("question", candidates, RaisingCrossEncoderReranker())

    assert reranked == candidates
    assert did_rerank is False


def test_bge_cross_encoder_reranker_loads_model_at_most_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # TC-FV03-034 / AC-FV03-020 / NFR-FV03-009: the model must be
    # constructed at most once across multiple score() calls on the same
    # instance — a fake sentence_transformers module is injected so this
    # test does not require the real (heavy, optional) dependency.
    construction_count = 0

    class FakeCrossEncoder:
        def __init__(self, model_name: str) -> None:
            nonlocal construction_count
            construction_count += 1

        def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
            return [0.0 for _ in pairs]

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.CrossEncoder = FakeCrossEncoder  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    reranker = BgeCrossEncoderReranker()
    reranker.score((("q1", "c1"),))
    reranker.score((("q2", "c2"),))

    assert construction_count == 1


def test_retrieve_populates_reranked_count_when_reranker_configured() -> None:
    # TC-FV03-035 / AC-FV03-018.
    store = InMemoryKnowledgeStore(
        reranker=FakeCrossEncoderReranker(score_fn=lambda pairs: tuple(1.0 for _ in pairs))
    )
    for index in range(3):
        store.save_document(make_document(source_id=f"doc_{index}"))
        store.save_chunk(
            DocumentChunk(
                chunk_id=f"doc_{index}_chunk_1",
                source_id=f"doc_{index}",
                chunk_index=1,
                chunk_text="revenue dropped after campaign spend paused",
            )
        )

    result = store.retrieve(
        RetrievalQuery(
            question="revenue dropped after campaign spend paused",
            requesting_user_id="u_001",
            top_k=1,
        )
    )

    assert result.retrieval_stats.reranked_count == min(3, 1 * 2)


def test_retrieve_reranked_count_is_zero_when_reranker_fails() -> None:
    # Code-review regression test: reranked_count must reflect whether
    # rerank() actually succeeded, not merely whether a reranker was
    # configured — a reranker that raises must report reranked_count == 0,
    # the same as if none were configured, even though evidence is still
    # returned via the pre-rerank hybrid ordering.
    store = InMemoryKnowledgeStore(reranker=RaisingCrossEncoderReranker())
    store.save_document(make_document(source_id="doc_a"))
    store.save_chunk(
        DocumentChunk(
            chunk_id="doc_a_chunk_1",
            source_id="doc_a",
            chunk_index=1,
            chunk_text="revenue dropped after campaign spend paused",
        )
    )

    result = store.retrieve(
        RetrievalQuery(question="revenue dropped after campaign spend paused", requesting_user_id="u_001")
    )

    assert result.retrieval_stats.reranked_count == 0
    assert len(result.evidence_list) == 1


def test_retrieve_reranked_count_is_zero_without_a_reranker() -> None:
    # TC-FV03-036.
    store = InMemoryKnowledgeStore()
    store.save_document(make_document(source_id="doc_a"))
    store.save_chunk(
        DocumentChunk(
            chunk_id="doc_a_chunk_1",
            source_id="doc_a",
            chunk_index=1,
            chunk_text="revenue dropped after campaign spend paused",
        )
    )

    result = store.retrieve(
        RetrievalQuery(question="revenue dropped after campaign spend paused", requesting_user_id="u_001")
    )

    assert result.retrieval_stats.reranked_count == 0


def test_retrieve_uses_reranked_order_over_hybrid_order() -> None:
    # TC-FV03-037 / AC-FV03-017: a chunk the reranker ranks highest must
    # come first in evidence_list, even though its pre-rerank hybrid score
    # (driven by keyword+vector overlap) was lower than another candidate's.
    def score_fn(pairs: tuple[tuple[str, str], ...]) -> tuple[float, ...]:
        # Score doc_b's chunk highest regardless of the hybrid ranking.
        return tuple(1.0 if "doc_b marker" in chunk_text_value else 0.0 for _, chunk_text_value in pairs)

    store = InMemoryKnowledgeStore(reranker=FakeCrossEncoderReranker(score_fn=score_fn))
    store.save_document(make_document(source_id="doc_a"))
    store.save_chunk(
        DocumentChunk(
            chunk_id="doc_a_chunk_1",
            source_id="doc_a",
            chunk_index=1,
            chunk_text="revenue dropped after campaign spend paused revenue revenue",
        )
    )
    store.save_document(make_document(source_id="doc_b"))
    store.save_chunk(
        DocumentChunk(
            chunk_id="doc_b_chunk_1",
            source_id="doc_b",
            chunk_index=1,
            chunk_text="doc_b marker",
        )
    )

    result = store.retrieve(
        RetrievalQuery(question="revenue dropped after campaign spend paused", requesting_user_id="u_001")
    )

    assert result.evidence_list[0].source_id == "doc_b"


def test_bge_cross_encoder_reranker_real_model_end_to_end() -> None:
    # TC-FV03-038: requires the optional `rerank` extra
    # (sentence-transformers); skipped automatically when it is not
    # installed, per this spec's own guidance that this is the one test in
    # the plan needing the real, heavy dependency.
    pytest.importorskip("sentence_transformers")

    reranker = BgeCrossEncoderReranker()
    scores = reranker.score(
        (
            ("What caused the revenue drop?", "Revenue dropped after campaign spend paused."),
            ("What caused the revenue drop?", "The cafeteria menu changed on Monday."),
        )
    )

    assert len(scores) == 2
    assert scores[0] > scores[1]


@dataclass
class FakeVectorCandidateSource:
    """FR-FV03-032 test double: returns a caller-supplied fixed set of
    (chunk_id, distance) pairs, or raises, so tests can control narrowing
    precisely without a real Postgres connection. Records every
    query_vector it was called with, so tests can assert which embedding
    actually reached it."""

    chunk_ids: tuple[str, ...] = ()
    should_raise: bool = False
    received_query_vectors: list[tuple[float, ...]] = field(default_factory=lambda: [])

    def top_chunk_ids(
        self,
        *,
        query_vector: tuple[float, ...],
        requesting_user_id: str,
        user_role: str | None,
        doc_type: str | None,
        doc_types: tuple[str, ...],
        limit: int,
    ) -> tuple[tuple[str, float], ...]:
        self.received_query_vectors.append(query_vector)
        if self.should_raise:
            raise RuntimeError("vector candidate source unavailable")
        return tuple((chunk_id, 0.1) for chunk_id in self.chunk_ids)


def _seed_five_chunk_store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    for index in range(1, 6):
        source_id = f"doc_{index}"
        store.save_document(make_document(source_id=source_id))
        store.save_chunk(
            DocumentChunk(
                chunk_id=f"{source_id}_chunk_1",
                source_id=source_id,
                chunk_index=1,
                chunk_text="revenue dropped after campaign spend paused",
            )
        )
    return store


def test_retrieve_with_no_vector_candidate_source_is_unchanged() -> None:
    # TC-FV03-052 / AC-FV03-029 / NFR-FV03-013: explicit regression guard —
    # every existing test in this file already proves this implicitly by
    # continuing to pass, but this test states the invariant directly.
    store = _seed_five_chunk_store()
    query = RetrievalQuery(question="revenue dropped after campaign spend paused", requesting_user_id="u_001")

    result = store.retrieve(query)

    assert result.retrieval_stats.filtered_count == 5
    assert len(result.evidence_list) > 0


def test_retrieve_narrows_to_vector_candidate_source_subset() -> None:
    # TC-FV03-053 / AC-FV03-030: only the two chunks the fake source
    # returns are ranked/returned, out of a five-chunk permission-filtered
    # set.
    store = InMemoryKnowledgeStore(
        vector_candidate_source=FakeVectorCandidateSource(chunk_ids=("doc_1_chunk_1", "doc_2_chunk_1"))
    )
    for index in range(1, 6):
        source_id = f"doc_{index}"
        store.save_document(make_document(source_id=source_id))
        store.save_chunk(
            DocumentChunk(
                chunk_id=f"{source_id}_chunk_1",
                source_id=source_id,
                chunk_index=1,
                chunk_text="revenue dropped after campaign spend paused",
            )
        )

    result = store.retrieve(
        RetrievalQuery(
            question="revenue dropped after campaign spend paused",
            requesting_user_id="u_001",
            top_k=5,
        )
    )

    returned_source_ids = {item.source_id for item in result.evidence_list}
    assert returned_source_ids <= {"doc_1", "doc_2"}
    assert result.retrieval_stats.filtered_count == 2


def test_retrieve_vector_candidate_source_narrowing_cannot_widen_past_owner_filtering() -> None:
    # TC-FV03-054: a fake source that (incorrectly, simulating a SQL
    # scoping bug) includes a chunk belonging to a document the requester
    # cannot see must still have it excluded by list_chunk_records()'s
    # existing Python-side owner filtering — proving that filtering
    # remains authoritative, not merely additive.
    store = InMemoryKnowledgeStore(
        vector_candidate_source=FakeVectorCandidateSource(
            chunk_ids=("doc_visible_chunk_1", "doc_private_chunk_1")
        )
    )
    store.save_document(make_document(source_id="doc_visible"))
    store.save_chunk(
        DocumentChunk(
            chunk_id="doc_visible_chunk_1",
            source_id="doc_visible",
            chunk_index=1,
            chunk_text="revenue dropped after campaign spend paused",
        )
    )
    store.save_document(
        KnowledgeDocument(
            source_id="doc_private",
            title="Private",
            doc_type="report",
            publish_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
            owner_user_id="u_other",
        )
    )
    store.save_chunk(
        DocumentChunk(
            chunk_id="doc_private_chunk_1",
            source_id="doc_private",
            chunk_index=1,
            chunk_text="revenue dropped after campaign spend paused",
        )
    )

    result = store.retrieve(
        RetrievalQuery(
            question="revenue dropped after campaign spend paused",
            requesting_user_id="u_001",
        )
    )

    returned_source_ids = {item.source_id for item in result.evidence_list}
    assert "doc_private" not in returned_source_ids
    assert returned_source_ids == {"doc_visible"}


def test_retrieve_falls_back_when_vector_candidate_source_raises() -> None:
    # TC-FV03-055 / AC-FV03-031 / FR-FV03-034.
    store = InMemoryKnowledgeStore(vector_candidate_source=FakeVectorCandidateSource(should_raise=True))
    store.save_document(make_document(source_id="doc_1"))
    store.save_chunk(
        DocumentChunk(
            chunk_id="doc_1_chunk_1",
            source_id="doc_1",
            chunk_index=1,
            chunk_text="revenue dropped after campaign spend paused",
        )
    )

    result = store.retrieve(
        RetrievalQuery(question="revenue dropped after campaign spend paused", requesting_user_id="u_001")
    )

    assert len(result.evidence_list) == 1
    assert result.evidence_list[0].source_id == "doc_1"


def test_retrieve_narrows_using_the_real_configured_embedding_client() -> None:
    # Code-review regression test: _narrow_by_vector_candidates() must
    # embed the query with the store's real configured EmbeddingClient
    # (via retrieve()'s shared embed_text() call), not the deterministic
    # hash-bucket text_embedding() fallback — otherwise a pgvector-backed
    # VectorCandidateSource (whose stored document vectors come from the
    # real client) would be searched with an incompatible query vector.
    fake_client = FakeEmbeddingClient(vector=(9.0, 9.0, 9.0))
    vector_source = FakeVectorCandidateSource(chunk_ids=("doc_1_chunk_1",))
    store = InMemoryKnowledgeStore(embedding_client=fake_client, vector_candidate_source=vector_source)
    store.save_document(make_document(source_id="doc_1"))
    store.save_chunk(
        DocumentChunk(
            chunk_id="doc_1_chunk_1",
            source_id="doc_1",
            chunk_index=1,
            chunk_text="revenue dropped after campaign spend paused",
        )
    )

    store.retrieve(
        RetrievalQuery(question="revenue dropped after campaign spend paused", requesting_user_id="u_001")
    )

    assert vector_source.received_query_vectors == [(9.0, 9.0, 9.0)]
