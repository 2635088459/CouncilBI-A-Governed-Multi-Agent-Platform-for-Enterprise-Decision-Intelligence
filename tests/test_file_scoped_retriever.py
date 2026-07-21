from dataclasses import dataclass
from datetime import datetime, timezone

from chatbi.agents.file_scoped_retriever import FileScopedRetriever
from chatbi.embedding_vector_rag import EmbeddingRequest, EmbeddingResponse
from chatbi.files import InMemoryFileRepository, InMemoryFileVectorSink, UserUploadedFile
from chatbi.files.parser_unstructured import TextChunk
from chatbi.knowledge import text_embedding


@dataclass
class FakeEmbeddingClient:
    """A real EmbeddingClient implementation returning a fixed, recognizable
    vector distinct from text_embedding()'s hash-bucket output, so the test
    can tell which one FileScopedRetriever actually used for the query."""

    vector: tuple[float, ...]

    @property
    def provider_name(self) -> str:
        return "fake"

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        return EmbeddingResponse(
            vectors=(self.vector,),
            provider="fake",
            model_name=request.model_name,
            dimensions=len(self.vector),
            token_count=0,
            estimated_cost=0.0,
            latency_ms=0,
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _unstructured_file(file_id: str, original_name: str = "onepager.pdf") -> UserUploadedFile:
    return UserUploadedFile(
        file_id=file_id,
        org_id="org_1",
        user_id="user_1",
        original_name=original_name,
        file_type="unstructured",
        mime_type="application/pdf",
        size_bytes=1024,
        storage_key=f"org_1/user_1/{file_id}/{original_name}",
        content_hash=f"hash_{file_id}",
        status="ready",
        scope="user",
        file_group_id=f"fgrp_{file_id}",
        version_number=1,
        is_latest=True,
        created_at=_now(),
        schema_json=None,
        row_count=None,
        chunk_count=1,
    )


def _retriever(repository: InMemoryFileRepository, vector_source: InMemoryFileVectorSink) -> FileScopedRetriever:
    return FileScopedRetriever(vector_source=vector_source, repository=repository)


def test_retrieve_tags_evidence_with_the_source_files_id_and_title() -> None:
    # TC-FV10-165 / FR-FV10-067
    repository = InMemoryFileRepository()
    file = _unstructured_file("ufile_doc1", original_name="pricing.pdf")
    repository.save(file)
    vector_source = InMemoryFileVectorSink()
    chunk = TextChunk(text="Team tier is $49/seat/month.", chunk_index=1, file_id="ufile_doc1")
    vector_source.upsert_chunks((chunk,), ((1.0, 0.0, 0.0),))
    retriever = _retriever(repository, vector_source)

    evidence = retriever.retrieve(question="What is the Team tier price?", file_ids=("ufile_doc1",))

    assert len(evidence) == 1
    assert evidence[0].source_id == "ufile_doc1"
    assert evidence[0].title == "pricing.pdf"
    assert evidence[0].citation_anchor == "ufile_doc1#chunk-1"
    assert evidence[0].snippet == "Team tier is $49/seat/month."


def test_retrieve_never_returns_a_chunk_from_a_file_not_in_the_requested_file_ids() -> None:
    # TC-FV10-166 / NFR-FV10-023
    repository = InMemoryFileRepository()
    repository.save(_unstructured_file("ufile_a"))
    repository.save(_unstructured_file("ufile_b"))
    repository.save(_unstructured_file("ufile_c"))
    vector_source = InMemoryFileVectorSink()
    vector_source.upsert_chunks(
        (
            TextChunk(text="pricing details for tier A", chunk_index=1, file_id="ufile_a"),
            TextChunk(text="pricing details for tier B", chunk_index=1, file_id="ufile_b"),
            TextChunk(text="pricing details for tier C", chunk_index=1, file_id="ufile_c"),
        ),
        ((1.0, 0.0), (1.0, 0.0), (1.0, 0.0)),
    )
    retriever = _retriever(repository, vector_source)

    evidence = retriever.retrieve(question="pricing details", file_ids=("ufile_a", "ufile_b"), top_k=10)

    assert {item.source_id for item in evidence} == {"ufile_a", "ufile_b"}


def test_retrieve_ranks_the_more_relevant_chunk_first() -> None:
    # TC-FV10-167 — reuses chatbi.knowledge's keyword+cosine scoring.
    repository = InMemoryFileRepository()
    repository.save(_unstructured_file("ufile_doc1"))
    vector_source = InMemoryFileVectorSink()
    vector_source.upsert_chunks(
        (
            TextChunk(text="This section covers unrelated shipping logistics.", chunk_index=1, file_id="ufile_doc1"),
            TextChunk(text="The Team tier pricing is $49 per seat per month.", chunk_index=2, file_id="ufile_doc1"),
        ),
        ((0.0, 1.0), (0.0, 1.0)),
    )
    retriever = _retriever(repository, vector_source)

    evidence = retriever.retrieve(question="What is the Team tier pricing?", file_ids=("ufile_doc1",))

    assert evidence[0].citation_anchor == "ufile_doc1#chunk-2"


def test_retrieve_returns_empty_tuple_when_no_chunks_exist_for_any_requested_file() -> None:
    # TC-FV10-168 / FR-FV10-070 (the empty-candidate-set case itself; the
    # caller distinguishes "content unavailable" from "found nothing").
    repository = InMemoryFileRepository()
    repository.save(_unstructured_file("ufile_doc1"))
    vector_source = InMemoryFileVectorSink()
    retriever = _retriever(repository, vector_source)

    evidence = retriever.retrieve(question="anything", file_ids=("ufile_doc1",))

    assert evidence == ()


def test_retrieve_embeds_the_query_with_the_real_configured_embedding_client() -> None:
    # Code-review fix: FileScopedRetriever._rank() previously always called
    # chatbi.knowledge.text_embedding(question) directly for the query
    # vector, ignoring any real EmbeddingClient the file's chunks were
    # actually embedded with (FileProcessingWorker) — comparing a
    # deterministic hash-bucket query vector against real provider vectors
    # produces a meaningless cosine similarity.
    question = "What is the Team tier price?"
    fake_vector = tuple(1.0 if index == 0 else 0.0 for index in range(16))
    hash_bucket_vector = text_embedding(question)
    assert hash_bucket_vector[0] == 0.0  # guarantees the two vectors are orthogonal

    repository = InMemoryFileRepository()
    repository.save(_unstructured_file("ufile_doc1"))
    vector_source = InMemoryFileVectorSink()
    vector_source.upsert_chunks(
        (
            TextChunk(text="matches the real embedding client", chunk_index=1, file_id="ufile_doc1"),
            TextChunk(text="matches the hash-bucket fallback", chunk_index=2, file_id="ufile_doc1"),
        ),
        (fake_vector, hash_bucket_vector),
    )
    retriever = FileScopedRetriever(
        vector_source=vector_source,
        repository=repository,
        embedding_client=FakeEmbeddingClient(vector=fake_vector),
    )

    evidence = retriever.retrieve(question=question, file_ids=("ufile_doc1",))

    assert evidence[0].citation_anchor == "ufile_doc1#chunk-1"
