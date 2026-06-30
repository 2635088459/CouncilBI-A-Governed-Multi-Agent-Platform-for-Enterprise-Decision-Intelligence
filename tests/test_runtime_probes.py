from typing import Any
from typing import Sequence

from fastapi.testclient import TestClient

from chatbi.api.http import create_app
from chatbi.core.runtime_config import DatabaseReadinessChecker, RedisReadinessChecker, RuntimeConfig
from chatbi.governance import ReadOnlyProbeResult, ReadOnlyProbeStatus


class FakeReadinessCursor:
    def __init__(self, row: Sequence[object] | None = (1,)) -> None:
        self._row = row

    def fetchone(self) -> Sequence[object] | None:
        return self._row


class FakeReadinessConnection:
    def execute(self, sql: str) -> FakeReadinessCursor:
        return FakeReadinessCursor()

    def close(self) -> None:
        return None


class FakeReadOnlyProbe:
    def __init__(self, result: ReadOnlyProbeResult) -> None:
        self.result = result
        self.seen_database_urls: list[str | None] = []

    def check(self, database_url: str | None) -> ReadOnlyProbeResult:
        self.seen_database_urls.append(database_url)
        return self.result


class FakeRedisClient:
    def __init__(self, ready: bool) -> None:
        self.ready = ready
        self.closed = False

    def ping(self) -> bool:
        return self.ready

    def close(self) -> None:
        self.closed = True


def test_healthz_is_public_and_reports_process_liveness() -> None:
    client: Any = TestClient(create_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "chatbi-api",
    }


def test_readyz_fails_when_database_url_is_not_configured(monkeypatch: Any) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    client: Any = TestClient(create_app())

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["dependencies"]["postgresql"]["configured"] is False


def test_readyz_passes_when_database_url_is_configured(monkeypatch: Any) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://chatbi:test@localhost:5432/chatbi")

    client: Any = TestClient(create_app())

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["dependencies"]["postgresql"]["configured"] is True


def test_metrics_exposes_prometheus_text(monkeypatch: Any) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://chatbi:test@localhost:5432/chatbi")
    client: Any = TestClient(create_app())

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert 'chatbi_api_info{service="chatbi-api"} 1' in response.text
    assert "chatbi_api_ready 1" in response.text


def test_readyz_uses_database_readiness_checker_when_provided() -> None:
    checker = DatabaseReadinessChecker(lambda database_url: FakeReadinessConnection())
    client: Any = TestClient(
        create_app(
            runtime_config=RuntimeConfig(
                database_url="postgresql://chatbi:test@localhost:5432/chatbi",
                redis_url=None,
                vector_store_url=None,
            ),
            database_readiness_checker=checker,
        )
    )

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["dependencies"]["postgresql"]["reachable"] is True


def test_readyz_fails_when_database_readiness_checker_fails() -> None:
    def connect(database_url: str) -> FakeReadinessConnection:
        raise RuntimeError("database unavailable")

    checker = DatabaseReadinessChecker(connect)
    client: Any = TestClient(
        create_app(
            runtime_config=RuntimeConfig(
                database_url="postgresql://chatbi:test@localhost:5432/chatbi",
                redis_url=None,
                vector_store_url=None,
            ),
            database_readiness_checker=checker,
        )
    )

    ready_response = client.get("/readyz")
    health_response = client.get("/healthz")

    assert ready_response.status_code == 503
    assert ready_response.json()["dependencies"]["postgresql"]["reachable"] is False
    assert health_response.status_code == 200


def test_readyz_reports_redis_probe_success() -> None:
    redis_client = FakeRedisClient(ready=True)
    checker = RedisReadinessChecker(lambda redis_url: redis_client)
    client: Any = TestClient(
        create_app(
            runtime_config=RuntimeConfig(
                database_url="postgresql://chatbi:test@localhost:5432/chatbi",
                redis_url="redis://redis:6379/0",
                vector_store_url=None,
            ),
            redis_readiness_checker=checker,
        )
    )

    response = client.get("/readyz")
    dependency = response.json()["dependencies"]["redis"]

    assert response.status_code == 200
    assert dependency["configured"] is True
    assert dependency["reachable"] is True
    assert redis_client.closed is True


def test_readyz_fails_when_redis_probe_fails() -> None:
    checker = RedisReadinessChecker(lambda redis_url: FakeRedisClient(ready=False))
    client: Any = TestClient(
        create_app(
            runtime_config=RuntimeConfig(
                database_url="postgresql://chatbi:test@localhost:5432/chatbi",
                redis_url="redis://redis:6379/0",
                vector_store_url=None,
            ),
            redis_readiness_checker=checker,
        )
    )

    response = client.get("/readyz")
    dependency = response.json()["dependencies"]["redis"]

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert dependency["configured"] is True
    assert dependency["reachable"] is False


def test_v2_ready_endpoint_returns_enveloped_dependency_status() -> None:
    checker = RedisReadinessChecker(lambda redis_url: FakeRedisClient(ready=True))
    client: Any = TestClient(
        create_app(
            runtime_config=RuntimeConfig(
                database_url="postgresql://chatbi:test@localhost:5432/chatbi",
                redis_url="redis://redis:6379/0",
                vector_store_url=None,
            ),
            redis_readiness_checker=checker,
        )
    )

    response = client.get(
        "/api/v2/ready",
        headers={
            "Authorization": "Bearer test-token",
            "X-Request-Id": "req_ready_12345678",
        },
    )

    body = response.json()
    data = body["data"]

    assert response.status_code == 200
    assert set(body) == {"trace_id", "request_id", "data", "warnings", "error"}
    assert body["trace_id"].startswith("tr_")
    assert body["request_id"] == "req_ready_12345678"
    assert body["warnings"] == []
    assert body["error"] is None
    assert data["status"] == "ready"
    assert data["dependencies"]["postgresql"]["configured"] is True
    assert data["dependencies"]["redis"]["reachable"] is True


def test_v2_ready_endpoint_returns_503_when_dependency_fails() -> None:
    checker = RedisReadinessChecker(lambda redis_url: FakeRedisClient(ready=False))
    client: Any = TestClient(
        create_app(
            runtime_config=RuntimeConfig(
                database_url="postgresql://chatbi:test@localhost:5432/chatbi",
                redis_url="redis://redis:6379/0",
                vector_store_url=None,
            ),
            redis_readiness_checker=checker,
        )
    )

    response = client.get(
        "/api/v2/ready",
        headers={
            "Authorization": "Bearer test-token",
            "X-Request-Id": "req_ready_failed",
        },
    )

    body = response.json()

    assert response.status_code == 503
    assert body["request_id"] == "req_ready_failed"
    assert body["data"]["status"] == "not_ready"
    assert body["data"]["dependencies"]["redis"]["reachable"] is False
    assert body["error"] is None


def test_v2_ready_endpoint_requires_bearer_token() -> None:
    client: Any = TestClient(create_app())

    response = client.get(
        "/api/v2/ready",
        headers={"X-Request-Id": "req_ready_auth"},
    )

    body = response.json()

    assert response.status_code == 401
    assert body["request_id"] == "req_ready_auth"
    assert body["data"] is None
    assert body["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_readyz_reports_readonly_database_probe_success() -> None:
    readonly_probe = FakeReadOnlyProbe(
        ReadOnlyProbeResult(status=ReadOnlyProbeStatus.BLOCKED)
    )
    client: Any = TestClient(
        create_app(
            runtime_config=RuntimeConfig(
                database_url="postgresql://chatbi:test@localhost:5432/chatbi",
                readonly_database_url="postgresql://chatbi_readonly:test@localhost:5432/chatbi",
                redis_url=None,
                vector_store_url=None,
            ),
            readonly_database_probe=readonly_probe,
        )
    )

    response = client.get("/readyz")
    dependency = response.json()["dependencies"]["business_postgresql_readonly"]

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert dependency["configured"] is True
    assert dependency["write_probe_status"] == "blocked"
    assert dependency["write_blocked"] is True
    assert readonly_probe.seen_database_urls == [
        "postgresql://chatbi_readonly:test@localhost:5432/chatbi"
    ]


def test_readyz_fails_when_readonly_database_probe_allows_write() -> None:
    readonly_probe = FakeReadOnlyProbe(
        ReadOnlyProbeResult(status=ReadOnlyProbeStatus.WRITE_ALLOWED)
    )
    client: Any = TestClient(
        create_app(
            runtime_config=RuntimeConfig(
                database_url="postgresql://chatbi:test@localhost:5432/chatbi",
                readonly_database_url="postgresql://chatbi_writer:test@localhost:5432/chatbi",
                redis_url=None,
                vector_store_url=None,
            ),
            readonly_database_probe=readonly_probe,
        )
    )

    response = client.get("/readyz")
    dependency = response.json()["dependencies"]["business_postgresql_readonly"]

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert dependency["configured"] is True
    assert dependency["write_probe_status"] == "write_allowed"
    assert dependency["write_blocked"] is False
