from typing import Sequence

from chatbi.core.runtime_config import (
    DatabaseReadinessChecker,
    RedisReadinessChecker,
    RuntimeConfig,
    load_runtime_config,
)


class FakeReadinessCursor:
    def __init__(self, row: Sequence[object] | None) -> None:
        self._row = row

    def fetchone(self) -> Sequence[object] | None:
        return self._row


class FakeReadinessConnection:
    def __init__(self, row: Sequence[object] | None = (1,)) -> None:
        self.row = row
        self.closed = False

    def execute(self, sql: str) -> FakeReadinessCursor:
        assert sql == "SELECT 1"
        return FakeReadinessCursor(self.row)

    def close(self) -> None:
        self.closed = True


class FakeRedisClient:
    def __init__(self, ready: bool = True) -> None:
        self.ready = ready
        self.closed = False

    def ping(self) -> bool:
        return self.ready

    def close(self) -> None:
        self.closed = True


def test_load_runtime_config_reads_required_deployment_urls() -> None:
    config = load_runtime_config(
        {
            "DATABASE_URL": "postgresql://chatbi:test@db:5432/chatbi",
            "CHATBI_READONLY_DATABASE_URL": (
                "postgresql://chatbi_readonly:test@db:5432/chatbi"
            ),
            "REDIS_URL": "redis://redis:6379/0",
            "VECTOR_STORE_URL": "http://vector-store:6333",
            "CHATBI_LLM_PROVIDER": "openai",
            "CHATBI_LLM_MODEL": "gpt-4o-mini",
            "CHATBI_LLM_TIMEOUT_MS": "2500",
            "CHATBI_LLM_MAX_RETRIES": "2",
            "CHATBI_LLM_BACKOFF_MS": "50",
            "OPENAI_API_KEY": "test-key",
            "CHATBI_EMBEDDING_PROVIDER": "mock",
            "CHATBI_EMBEDDING_MODEL": "mock-embedding-v2",
        }
    )

    assert config.database_url == "postgresql://chatbi:test@db:5432/chatbi"
    assert (
        config.readonly_database_url
        == "postgresql://chatbi_readonly:test@db:5432/chatbi"
    )
    assert config.redis_url == "redis://redis:6379/0"
    assert config.vector_store_url == "http://vector-store:6333"
    assert config.llm_provider == "openai"
    assert config.llm_model == "gpt-4o-mini"
    assert config.llm_timeout_ms == 2500
    assert config.llm_max_retries == 2
    assert config.llm_backoff_ms == 50
    assert config.llm_api_key_configured is True
    assert config.embedding_provider == "mock"
    assert config.embedding_model == "mock-embedding-v2"
    assert config.postgresql_configured is True
    assert config.readonly_postgresql_configured is True
    assert config.redis_configured is True
    assert config.vector_store_configured is True


def test_load_runtime_config_reads_file_storage_root() -> None:
    config = load_runtime_config({"CHATBI_FILE_STORAGE_ROOT": "/data/file_storage"})

    assert config.file_storage_root == "/data/file_storage"


def test_load_runtime_config_defaults_file_storage_root_to_none() -> None:
    config = load_runtime_config({})

    assert config.file_storage_root is None


def test_load_runtime_config_reads_conversation_context_turns() -> None:
    # Spec FV10.4 §6.3 / FR-FV10-053
    config = load_runtime_config({"CHATBI_CONVERSATION_CONTEXT_TURNS": "8"})

    assert config.conversation_context_turns == 8


def test_load_runtime_config_defaults_conversation_context_turns_to_5() -> None:
    config = load_runtime_config({})

    assert config.conversation_context_turns == 5


def test_load_runtime_config_ignores_invalid_conversation_context_turns() -> None:
    config = load_runtime_config({"CHATBI_CONVERSATION_CONTEXT_TURNS": "-3"})

    assert config.conversation_context_turns == 5


def test_load_runtime_config_reads_file_conversation_context_turns() -> None:
    config = load_runtime_config({"CHATBI_FILE_CONVERSATION_CONTEXT_TURNS": "4"})

    assert config.file_conversation_context_turns == 4


def test_load_runtime_config_defaults_file_conversation_context_turns_to_2() -> None:
    config = load_runtime_config({})

    assert config.file_conversation_context_turns == 2


def test_load_runtime_config_ignores_invalid_file_conversation_context_turns() -> None:
    config = load_runtime_config({"CHATBI_FILE_CONVERSATION_CONTEXT_TURNS": "-3"})

    assert config.file_conversation_context_turns == 2


def test_runtime_config_treats_blank_values_as_missing() -> None:
    config = load_runtime_config(
        {
            "DATABASE_URL": " ",
            "CHATBI_READONLY_DATABASE_URL": "",
            "REDIS_URL": "",
            "VECTOR_STORE_URL": "   ",
            "CHATBI_LLM_PROVIDER": " ",
            "CHATBI_LLM_MODEL": "",
            "CHATBI_LLM_TIMEOUT_MS": "-1",
            "CHATBI_LLM_MAX_RETRIES": "-1",
            "CHATBI_LLM_BACKOFF_MS": "bad",
            "CHATBI_EMBEDDING_PROVIDER": "",
            "CHATBI_EMBEDDING_MODEL": "",
        }
    )

    assert config.database_url is None
    assert config.readonly_database_url is None
    assert config.redis_url is None
    assert config.vector_store_url is None
    assert config.llm_provider == "mock"
    assert config.llm_model == "mock-chatbi-small"
    assert config.llm_timeout_ms == 1000
    assert config.llm_max_retries == 1
    assert config.llm_backoff_ms == 25
    assert config.embedding_provider == "mock"
    assert config.embedding_model == "mock-local-embedding"
    assert config.ready_for_traffic is False


def test_openai_runtime_config_defaults_to_openai_smoke_model() -> None:
    config = load_runtime_config(
        {
            "CHATBI_LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "test-key",
        }
    )

    assert config.llm_provider == "openai"
    assert config.llm_model == "gpt-4o-mini"
    assert config.llm_provider_configured is True


def test_runtime_config_readiness_depends_on_postgresql() -> None:
    config = RuntimeConfig(
        database_url="postgresql://chatbi:test@db:5432/chatbi",
        redis_url=None,
        vector_store_url=None,
    )

    assert config.ready_for_traffic is True
    assert config.dependency_status() == {
        "postgresql": {"configured": True},
        "business_postgresql_readonly": {"configured": False},
            "redis": {"configured": False},
            "vector_store": {"configured": False},
            "llm_provider": {"configured": True, "mock": True},
            "embedding_provider": {"configured": True, "mock": True},
        }


def test_database_readiness_checker_returns_true_for_select_one() -> None:
    connection = FakeReadinessConnection()
    checker = DatabaseReadinessChecker(lambda database_url: connection)

    assert checker.is_ready("postgresql://chatbi:test@localhost:5432/chatbi") is True
    assert connection.closed is True


def test_database_readiness_checker_returns_false_when_database_url_is_missing() -> None:
    checker = DatabaseReadinessChecker(lambda database_url: FakeReadinessConnection())

    assert checker.is_ready(None) is False


def test_database_readiness_checker_returns_false_when_ping_fails() -> None:
    def connect(database_url: str) -> FakeReadinessConnection:
        raise RuntimeError("database unavailable")

    checker = DatabaseReadinessChecker(connect)

    assert checker.is_ready("postgresql://chatbi:test@localhost:5432/chatbi") is False


def test_redis_readiness_checker_returns_true_for_ping() -> None:
    client = FakeRedisClient()
    checker = RedisReadinessChecker(lambda redis_url: client)

    assert checker.is_ready("redis://redis:6379/0") is True
    assert client.closed is True


def test_redis_readiness_checker_returns_false_when_url_is_missing() -> None:
    checker = RedisReadinessChecker(lambda redis_url: FakeRedisClient())

    assert checker.is_ready(None) is False


def test_redis_readiness_checker_returns_false_when_ping_fails() -> None:
    checker = RedisReadinessChecker(lambda redis_url: FakeRedisClient(ready=False))

    assert checker.is_ready("redis://redis:6379/0") is False
