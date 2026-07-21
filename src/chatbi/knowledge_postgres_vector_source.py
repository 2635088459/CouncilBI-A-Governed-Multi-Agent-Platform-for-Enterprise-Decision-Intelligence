"""Spec FV03.5: pgvector-backed vector candidate generation for
``InMemoryKnowledgeStore``'s hybrid retrieval path.

This is deliberately not an implementation of the ``VectorStore`` protocol
(``embedding_vector_rag.py``) used by the retired vector-only pipeline —
that protocol's ``org_id``/``permission_tags`` filter model does not match
``InMemoryKnowledgeStore``'s actual ``owner_user_id``/``allowed_roles``
permission model. ``VectorCandidateSource`` here is a new, narrower
protocol shaped for that model instead.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol


class VectorCandidateSource(Protocol):
    """FR-FV03-030: given a query embedding, return the nearest chunk ids
    (and their cosine distance, nearest first), scoped to what the
    requesting user/role/doc_type may see."""

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
        ...


class PostgresKnowledgeVectorSource:
    """FR-FV03-030/031: queries knowledge.doc_embeddings/doc_chunks/documents
    directly, with owner_user_id/allowed_roles/doc_type scoping applied in
    the SQL WHERE clause itself — not as a post-retrieval filter.

    Known gap (Spec FV03.5 §3.2/§9, deliberately not silently absorbed
    here): this does not grant visibility to a document shared via Spec
    FV10.2's approval workflow but not owned by the requester. Callers
    must still run this source's output through
    ``InMemoryKnowledgeStore.list_chunk_records()``'s existing Python-side
    filtering, which remains the authority — this source only narrows.
    """

    # Code-review fix: %(query_vector)s must be cast to ::vector explicitly
    # — psycopg has no built-in adapter for pgvector's `vector` type (no
    # `pgvector` package is registered anywhere in this project), so a
    # plain Python list binds as a generic array and Postgres raises
    # "operator does not exist: vector <=> double precision[]" without
    # this cast.
    _TOP_CHUNK_IDS_SQL = """
        SELECT c.chunk_id, e.embedding <=> %(query_vector)s::vector AS distance
        FROM knowledge.doc_embeddings e
        JOIN knowledge.doc_chunks c ON c.chunk_id = e.chunk_id
        JOIN knowledge.documents d ON d.source_id = c.source_id
        WHERE e.embedding IS NOT NULL
          AND (d.owner_user_id IS NULL OR d.owner_user_id = %(requesting_user_id)s)
          AND (
            %(user_role)s IS NULL
            OR d.allowed_roles = '{}'
            OR %(user_role)s = ANY(d.allowed_roles)
          )
          AND (%(doc_type)s IS NULL OR d.doc_type = %(doc_type)s)
          AND (%(doc_types)s = '{}' OR d.doc_type = ANY(%(doc_types)s))
        ORDER BY e.embedding <=> %(query_vector)s::vector
        LIMIT %(limit)s
    """

    def __init__(self, connect_fn: Callable[[str], Any], database_url: str) -> None:
        self._connect_fn = connect_fn
        self._database_url = database_url

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
        # Code-review fix: the connection is now explicitly closed — this
        # method runs once per retrieve() call (i.e. potentially once per
        # chat request), unlike the one-time-at-startup connections
        # elsewhere in this codebase, so leaving it open here would leak
        # one live connection per request under sustained traffic.
        connection = self._connect_fn(self._database_url)
        try:
            with connection.cursor() as cur:
                cur.execute(
                    self._TOP_CHUNK_IDS_SQL,
                    {
                        "query_vector": list(query_vector),
                        "requesting_user_id": requesting_user_id,
                        "user_role": user_role,
                        "doc_type": doc_type,
                        "doc_types": list(doc_types),
                        "limit": limit,
                    },
                )
                rows = cur.fetchall()
            return tuple((row[0], float(row[1])) for row in rows)
        finally:
            connection.close()


def backfill_knowledge_embeddings(
    connect_fn: Callable[[str], Any],
    database_url: str,
    embedding_client: Any,
    batch_size: int = 50,
) -> int:
    """FR-FV03-033: populate ``embedding`` for every knowledge.doc_embeddings
    row currently NULL, via the same EmbeddingClient Spec FV03.1 wires into
    ``InMemoryKnowledgeStore.embed_text()`` — not a separate embedding code
    path. Not part of the request-serving path; a one-time/periodic script,
    the same shape as this project's other migrate.py-style repair jobs.

    Returns the number of rows updated.
    """

    from chatbi.embedding_vector_rag import EmbeddingRequest

    connection = connect_fn(database_url)
    updated_count = 0
    try:
        with connection.cursor() as cur:
            while True:
                cur.execute(
                    """
                    SELECT e.chunk_id, c.chunk_text
                    FROM knowledge.doc_embeddings e
                    JOIN knowledge.doc_chunks c ON c.chunk_id = e.chunk_id
                    WHERE e.embedding IS NULL
                    LIMIT %(batch_size)s
                    """,
                    {"batch_size": batch_size},
                )
                rows = cur.fetchall()
                if not rows:
                    break
                for chunk_id, chunk_text in rows:
                    response = embedding_client.embed(
                        EmbeddingRequest(
                            trace_id="trc_knowledge_backfill",
                            org_id="org_legacy",
                            input_texts=(chunk_text,),
                        )
                    )
                    # Code-review fix: ::vector cast (see top_chunk_ids's
                    # own comment) — psycopg has no default adapter for
                    # pgvector's `vector` column type.
                    cur.execute(
                        "UPDATE knowledge.doc_embeddings SET embedding = %(embedding)s::vector"
                        " WHERE chunk_id = %(chunk_id)s",
                        {"embedding": list(response.vectors[0]), "chunk_id": chunk_id},
                    )
                    updated_count += 1
            connection.commit()
    finally:
        connection.close()
    return updated_count
