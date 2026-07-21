from datetime import datetime, timezone
from typing import Sequence

from chatbi.api.http import _load_knowledge_store_from_db  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
from chatbi.embedding_vector_rag import EmbeddingRequest, EmbeddingResponse


class FakeCursor:
    """Mirrors tests/test_knowledge_postgres_vector_source.py's FakeCursor:
    each execute()/fetchall() pair pops the next queued row set, matching
    _load_knowledge_store_from_db's two sequential SELECTs (documents, then
    chunks) on one cursor."""

    def __init__(self, fetchall_rows: tuple[tuple[Sequence[object], ...], ...]) -> None:
        self._fetchall_rows = list(fetchall_rows)

    def execute(self, sql: str, params: object = None) -> None:
        return None

    def fetchall(self) -> Sequence[Sequence[object]]:
        return self._fetchall_rows.pop(0)

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor


class ExplodingEmbeddingClient:
    """A real EmbeddingClient that fails the test if it is ever called —
    proves the persisted-embedding path is actually used instead of
    recomputing."""

    @property
    def provider_name(self) -> str:
        return "exploding"

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        raise AssertionError("embed_text() must not be called when a persisted embedding exists")


class _DummyVectorCandidateSource:
    """Only its non-None-ness matters here — top_chunk_ids() runs at
    retrieve() time, never during _load_knowledge_store_from_db()."""

    def top_chunk_ids(self, **kwargs: object) -> tuple[tuple[str, float], ...]:
        raise AssertionError("top_chunk_ids() must not be called while loading the store")


_DOCUMENT_ROW: tuple[object, ...] = (
    "doc_1",
    "Doc One",
    "report",
    datetime(2026, 1, 1, tzinfo=timezone.utc),
    [],
    [],
    None,
)


def test_load_knowledge_store_uses_the_persisted_embedding_when_pgvector_is_configured() -> None:
    # Code-review follow-up: recomputing every chunk's embedding via a real
    # EmbeddingClient on every process restart wastes one provider call per
    # chunk. When pgvector is configured (vector_candidate_source is not
    # None), the already-backfilled knowledge.doc_embeddings.embedding
    # column must be read instead.
    cursor = FakeCursor(
        fetchall_rows=(
            (_DOCUMENT_ROW,),
            (("doc_1_chunk_1", "doc_1", 1, "chunk text", "[1,0,0]"),),
        )
    )
    connection = FakeConnection(cursor)

    store = _load_knowledge_store_from_db(
        connect_fn=lambda database_url: connection,
        database_url="postgresql://test",
        embedding_client=ExplodingEmbeddingClient(),
        vector_candidate_source=_DummyVectorCandidateSource(),
    )

    records = store.list_chunk_records()
    assert len(records) == 1
    assert records[0].embedding is not None
    assert records[0].embedding.embedding_vector == (1.0, 0.0, 0.0)


def test_load_knowledge_store_falls_back_to_embedding_client_when_persisted_embedding_is_null() -> None:
    # A chunk not yet covered by the backfill migration (FR-FV03-033) has a
    # NULL knowledge.doc_embeddings.embedding — this must still fall back
    # to the configured EmbeddingClient, not silently drop the chunk.
    cursor = FakeCursor(
        fetchall_rows=(
            (_DOCUMENT_ROW,),
            (("doc_1_chunk_1", "doc_1", 1, "chunk text", None),),
        )
    )
    connection = FakeConnection(cursor)

    class FakeEmbeddingClient:
        @property
        def provider_name(self) -> str:
            return "fake"

        def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
            return EmbeddingResponse(
                vectors=((5.0, 5.0, 5.0),),
                provider="fake",
                model_name=request.model_name,
                dimensions=3,
                token_count=0,
                estimated_cost=0.0,
                latency_ms=0,
            )

    store = _load_knowledge_store_from_db(
        connect_fn=lambda database_url: connection,
        database_url="postgresql://test",
        embedding_client=FakeEmbeddingClient(),
        vector_candidate_source=_DummyVectorCandidateSource(),
    )

    records = store.list_chunk_records()
    assert len(records) == 1
    assert records[0].embedding is not None
    assert records[0].embedding.embedding_vector == (5.0, 5.0, 5.0)


def test_load_knowledge_store_recomputes_embeddings_when_pgvector_is_not_configured() -> None:
    # No regression for deployments that never ran the pgvector migration:
    # vector_candidate_source=None must keep exactly the original
    # recompute-every-chunk-at-load behavior, without ever selecting a
    # knowledge.doc_embeddings.embedding column that may not exist there.
    cursor = FakeCursor(
        fetchall_rows=(
            (_DOCUMENT_ROW,),
            (("doc_1_chunk_1", "doc_1", 1, "chunk text"),),
        )
    )
    connection = FakeConnection(cursor)
    calls: list[str] = []

    class CountingEmbeddingClient:
        @property
        def provider_name(self) -> str:
            return "counting"

        def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
            calls.append(request.input_texts[0])
            return EmbeddingResponse(
                vectors=((2.0, 0.0, 0.0),),
                provider="counting",
                model_name=request.model_name,
                dimensions=3,
                token_count=0,
                estimated_cost=0.0,
                latency_ms=0,
            )

    store = _load_knowledge_store_from_db(
        connect_fn=lambda database_url: connection,
        database_url="postgresql://test",
        embedding_client=CountingEmbeddingClient(),
        vector_candidate_source=None,
    )

    assert calls == ["chunk text"]
    records = store.list_chunk_records()
    assert len(records) == 1
    assert records[0].embedding is not None
    assert records[0].embedding.embedding_vector == (2.0, 0.0, 0.0)
