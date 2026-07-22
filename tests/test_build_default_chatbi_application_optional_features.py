"""Code-review regression tests: Specs FV03.3 (reranking) and FV03.5
(pgvector narrowing) were fully implemented and unit-tested but never
constructed by _build_default_chatbi_application() — the function that
builds the live application's knowledge store. These tests assert the
opt-in RuntimeConfig flags actually reach InMemoryKnowledgeStore's
constructor, not just that RuntimeConfig itself parses them (already
covered by tests/test_runtime_config.py).
"""

from typing import cast

from psycopg_pool import ConnectionPool

from chatbi.api.http import _build_default_chatbi_application  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
from chatbi.core.runtime_config import RuntimeConfig
from chatbi.knowledge import BgeCrossEncoderReranker
from chatbi.knowledge_postgres_vector_source import PostgresKnowledgeVectorSource
from chatbi.observability import InMemoryObservabilityStore
from chatbi.observability_logs import InMemoryObservabilityLogStore
from chatbi.observability_postgres import PostgresObservabilityLogStore, PostgresObservabilityStore


def test_reranker_disabled_by_default() -> None:
    application = _build_default_chatbi_application(RuntimeConfig())

    knowledge_store = application.orchestrator.knowledge_store
    assert knowledge_store is not None
    assert knowledge_store._reranker is None  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


def test_reranker_enabled_flag_constructs_a_real_reranker() -> None:
    application = _build_default_chatbi_application(RuntimeConfig(reranker_enabled=True))

    knowledge_store = application.orchestrator.knowledge_store
    assert knowledge_store is not None
    assert isinstance(
        knowledge_store._reranker,  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        BgeCrossEncoderReranker,
    )


def test_pgvector_search_disabled_by_default() -> None:
    application = _build_default_chatbi_application(
        RuntimeConfig(database_url="postgresql://ignored-for-this-test")
    )

    knowledge_store = application.orchestrator.knowledge_store
    assert knowledge_store is not None
    assert (
        knowledge_store._vector_candidate_source is None  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    )


def test_pgvector_search_enabled_flag_constructs_a_real_vector_candidate_source() -> None:
    application = _build_default_chatbi_application(
        RuntimeConfig(
            database_url="postgresql://ignored-for-this-test",
            pgvector_search_enabled=True,
        )
    )

    knowledge_store = application.orchestrator.knowledge_store
    assert knowledge_store is not None
    assert isinstance(
        knowledge_store._vector_candidate_source,  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        PostgresKnowledgeVectorSource,
    )


def test_pgvector_search_enabled_flag_is_a_no_op_without_a_database_url() -> None:
    # pgvector needs a real Postgres instance to search — enabling the
    # flag with no database_url configured must not construct a source
    # with nothing to connect to.
    application = _build_default_chatbi_application(
        RuntimeConfig(database_url=None, pgvector_search_enabled=True)
    )

    knowledge_store = application.orchestrator.knowledge_store
    assert knowledge_store is not None
    assert (
        knowledge_store._vector_candidate_source is None  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    )


def test_observability_postgres_disabled_by_default() -> None:
    application = _build_default_chatbi_application(
        RuntimeConfig(database_url="postgresql://ignored-for-this-test")
    )

    assert isinstance(application.observability_store, InMemoryObservabilityStore)
    assert isinstance(application.observability_log_store, InMemoryObservabilityLogStore)


def test_close_is_a_no_op_when_observability_postgres_is_disabled() -> None:
    application = _build_default_chatbi_application(RuntimeConfig())

    application.close()  # must not raise — nothing was registered to close


def test_close_shuts_down_the_shared_observability_connection_pool_when_enabled() -> None:
    # Code-review follow-up (Spec 4.7): _build_default_chatbi_application()
    # constructs a ConnectionPool for the two stores below but nothing
    # closed it on shutdown before this fix — create_app()'s retention-sweep
    # lifespan now calls ChatBIApplication.close() to run this.
    application = _build_default_chatbi_application(
        RuntimeConfig(
            database_url="postgresql://ignored-for-this-test",
            observability_postgres_enabled=True,
        )
    )
    pool = cast(
        ConnectionPool,
        cast(
            PostgresObservabilityStore, application.observability_store
        )._pool,  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    )

    application.close()

    assert pool.closed is True


def test_observability_postgres_enabled_flag_constructs_durable_stores() -> None:
    application = _build_default_chatbi_application(
        RuntimeConfig(
            database_url="postgresql://ignored-for-this-test",
            observability_postgres_enabled=True,
        )
    )

    assert isinstance(application.observability_store, PostgresObservabilityStore)
    assert isinstance(application.observability_log_store, PostgresObservabilityLogStore)


def test_observability_postgres_enabled_flag_is_a_no_op_without_a_database_url() -> None:
    # Same "needs a real Postgres instance" guard as pgvector above:
    # enabling the flag with no database_url configured must not construct
    # a store with nothing to connect to.
    application = _build_default_chatbi_application(
        RuntimeConfig(database_url=None, observability_postgres_enabled=True)
    )

    assert isinstance(application.observability_store, InMemoryObservabilityStore)
    assert isinstance(application.observability_log_store, InMemoryObservabilityLogStore)
