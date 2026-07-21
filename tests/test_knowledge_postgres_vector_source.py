from typing import Any, Sequence

import pytest

from chatbi.knowledge_postgres_vector_source import (
    PostgresKnowledgeVectorSource,
    backfill_knowledge_embeddings,
    parse_pgvector_embedding,
)


class FakeCursor:
    def __init__(
        self,
        fetchall_rows: tuple[tuple[Sequence[object], ...], ...] = (),
        should_raise: bool = False,
    ) -> None:
        self.executed: list[tuple[str, dict[str, object]]] = []
        self._fetchall_rows = list(fetchall_rows)
        self._should_raise = should_raise

    def execute(self, sql: str, params: dict[str, object] | None = None) -> None:
        self.executed.append((sql, dict(params or {})))
        if self._should_raise:
            raise RuntimeError("query failed")

    def fetchall(self) -> Sequence[Sequence[object]]:
        if not self._fetchall_rows:
            return ()
        return self._fetchall_rows.pop(0)

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


class FakeKnowledgeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.commit_count = 0
        self.close_count = 0

    def cursor(self) -> FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.commit_count += 1

    def close(self) -> None:
        self.close_count += 1


class RaisingConnectFn:
    def __call__(self, database_url: str) -> Any:
        raise RuntimeError("connection failed")


def test_parse_pgvector_embedding_parses_the_bracketed_text_format() -> None:
    # Code-review follow-up: no pgvector Python type adapter is registered
    # anywhere in this project, so callers must SELECT with an explicit
    # ::text cast and parse the wire format themselves.
    assert parse_pgvector_embedding("[0.1,0.2,0.3]") == (0.1, 0.2, 0.3)
    assert parse_pgvector_embedding("[1,-2.5,0]") == (1.0, -2.5, 0.0)


def test_top_chunk_ids_executes_exactly_one_sql_statement_with_owner_and_role_scoping() -> None:
    # TC-FV03-050 / AC-FV03-028 / NFR-FV03-014.
    cursor = FakeCursor(fetchall_rows=((("chunk_1", 0.1), ("chunk_2", 0.3)),))
    connection = FakeKnowledgeConnection(cursor)
    source = PostgresKnowledgeVectorSource(
        connect_fn=lambda database_url: connection,
        database_url="postgresql://test",
    )

    source.top_chunk_ids(
        query_vector=(0.1, 0.2, 0.3),
        requesting_user_id="user_a",
        user_role="analyst",
        doc_type=None,
        doc_types=(),
        limit=10,
    )

    assert len(cursor.executed) == 1
    sql, params = cursor.executed[0]
    assert "owner_user_id" in sql
    assert "allowed_roles" in sql
    assert "<=>" in sql
    # Code-review fix: without this cast, psycopg has no adapter for
    # pgvector's `vector` type and Postgres rejects the query outright.
    assert "%(query_vector)s::vector" in " ".join(sql.split())
    assert params["requesting_user_id"] == "user_a"
    assert params["user_role"] == "analyst"
    assert params["limit"] == 10
    # Code-review fix: the connection must be closed after use — this
    # method runs once per retrieve() call, not once at process startup.
    assert connection.close_count == 1


def test_top_chunk_ids_parses_rows_in_returned_order_without_resorting() -> None:
    # TC-FV03-051: the SQL's own ORDER BY is the sole ordering authority.
    cursor = FakeCursor(fetchall_rows=((("chunk_far", 0.9), ("chunk_near", 0.1)),))
    connection = FakeKnowledgeConnection(cursor)
    source = PostgresKnowledgeVectorSource(
        connect_fn=lambda database_url: connection,
        database_url="postgresql://test",
    )

    results = source.top_chunk_ids(
        query_vector=(0.1, 0.2, 0.3),
        requesting_user_id="user_a",
        user_role=None,
        doc_type=None,
        doc_types=(),
        limit=10,
    )

    assert results == (("chunk_far", 0.9), ("chunk_near", 0.1))


def test_top_chunk_ids_owner_isolation_binds_requesting_user_id_into_the_where_clause() -> None:
    # TC-FV03-057 / AC-FV03-033: verified against the executed SQL and
    # parameters, not only the returned rows — a query that filtered in
    # Python after fetching everything would also pass a
    # result-set-only assertion.
    cursor = FakeCursor(fetchall_rows=((),))
    connection = FakeKnowledgeConnection(cursor)
    source = PostgresKnowledgeVectorSource(
        connect_fn=lambda database_url: connection,
        database_url="postgresql://test",
    )

    source.top_chunk_ids(
        query_vector=(0.1, 0.2, 0.3),
        requesting_user_id="user_a",
        user_role=None,
        doc_type=None,
        doc_types=(),
        limit=5,
    )

    sql, params = cursor.executed[0]
    assert "d.owner_user_id = %(requesting_user_id)s" in " ".join(sql.split())
    assert params["requesting_user_id"] == "user_a"


def test_top_chunk_ids_closes_the_connection_even_when_the_query_raises() -> None:
    # Code-review regression test: the connection must not leak when the
    # query itself fails (e.g. a real "operator does not exist" error
    # before the ::vector cast fix, or any other transient DB failure).
    cursor = FakeCursor(should_raise=True)
    connection = FakeKnowledgeConnection(cursor)
    source = PostgresKnowledgeVectorSource(
        connect_fn=lambda database_url: connection,
        database_url="postgresql://test",
    )

    with pytest.raises(RuntimeError, match="query failed"):
        source.top_chunk_ids(
            query_vector=(0.1, 0.2, 0.3),
            requesting_user_id="user_a",
            user_role=None,
            doc_type=None,
            doc_types=(),
            limit=5,
        )

    assert connection.close_count == 1


def test_backfill_updates_only_rows_with_null_embedding() -> None:
    # TC-FV03-056 / AC-FV03-032.
    cursor = FakeCursor(
        fetchall_rows=(
            (("chunk_1", "Revenue dropped after campaign spend paused."),),
            (),  # second SELECT ... WHERE embedding IS NULL LIMIT batch_size returns nothing more
        )
    )
    connection = FakeKnowledgeConnection(cursor)

    class FakeEmbeddingClient:
        provider_name = "fake"
        call_count = 0

        def embed(self, request: Any) -> Any:
            self.call_count += 1
            from chatbi.embedding_vector_rag import EmbeddingResponse

            return EmbeddingResponse(
                vectors=((1.0, 2.0, 3.0),),
                provider="fake",
                model_name=request.model_name,
                dimensions=3,
                token_count=0,
                estimated_cost=0.0,
                latency_ms=0,
            )

    embedding_client = FakeEmbeddingClient()

    updated_count = backfill_knowledge_embeddings(
        connect_fn=lambda database_url: connection,
        database_url="postgresql://test",
        embedding_client=embedding_client,
        batch_size=50,
    )

    assert updated_count == 1
    assert embedding_client.call_count == 1
    update_statements = [sql for sql, _params in cursor.executed if sql.strip().startswith("UPDATE")]
    assert len(update_statements) == 1
    # Code-review fix: same ::vector cast requirement as top_chunk_ids.
    assert "%(embedding)s::vector" in update_statements[0]
    assert connection.commit_count == 1
    assert connection.close_count == 1


def test_backfill_stops_when_no_null_embedding_rows_remain() -> None:
    cursor = FakeCursor(fetchall_rows=((),))
    connection = FakeKnowledgeConnection(cursor)

    class FakeEmbeddingClient:
        def embed(self, request: Any) -> Any:
            raise AssertionError("embed() must not be called when there is nothing to backfill")

    updated_count = backfill_knowledge_embeddings(
        connect_fn=lambda database_url: connection,
        database_url="postgresql://test",
        embedding_client=FakeEmbeddingClient(),
    )

    assert updated_count == 0
    assert connection.close_count == 1


def test_backfill_closes_the_connection_even_when_the_query_raises() -> None:
    # Code-review regression test: same connection-leak concern as
    # top_chunk_ids, for the backfill script's own connection.
    cursor = FakeCursor(should_raise=True)
    connection = FakeKnowledgeConnection(cursor)

    with pytest.raises(RuntimeError, match="query failed"):
        backfill_knowledge_embeddings(
            connect_fn=lambda database_url: connection,
            database_url="postgresql://test",
            embedding_client=object(),
        )

    assert connection.close_count == 1
