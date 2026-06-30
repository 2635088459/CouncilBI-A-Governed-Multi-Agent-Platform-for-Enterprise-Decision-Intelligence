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
        }
    )

    assert config.database_url == "postgresql://chatbi:test@db:5432/chatbi"
    assert (
        config.readonly_database_url
        == "postgresql://chatbi_readonly:test@db:5432/chatbi"
    )
    assert config.redis_url == "redis://redis:6379/0"
    assert config.vector_store_url == "http://vector-store:6333"
    assert config.postgresql_configured is True
    assert config.readonly_postgresql_configured is True
    assert config.redis_configured is True
    assert config.vector_store_configured is True


def test_runtime_config_treats_blank_values_as_missing() -> None:
    config = load_runtime_config(
        {
            "DATABASE_URL": " ",
            "CHATBI_READONLY_DATABASE_URL": "",
            "REDIS_URL": "",
            "VECTOR_STORE_URL": "   ",
        }
    )

    assert config.database_url is None
    assert config.readonly_database_url is None
    assert config.redis_url is None
    assert config.vector_store_url is None
    assert config.ready_for_traffic is False


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
