from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from typing import Any, Callable

from fastapi.testclient import TestClient

from chatbi.api.http import create_app
from chatbi.application.app import ChatBIApplication
from chatbi.core.runtime_config import RuntimeConfig


def percentile(values: list[float], percentile_value: float) -> float:
    ordered = sorted(values)
    index = int((len(ordered) - 1) * percentile_value)
    return ordered[index]


def timed_call(action: Callable[[], None]) -> float:
    started_at = perf_counter()
    action()
    return (perf_counter() - started_at) * 1000


def test_healthz_readyz_and_metrics_p99_latency_smoke() -> None:
    app = create_app(
        runtime_config=RuntimeConfig(
            database_url="postgresql://chatbi:test@localhost:5432/chatbi",
            redis_url="redis://localhost:6379/0",
            vector_store_url="memory://local-vector-store",
        )
    )
    client: Any = TestClient(app)

    health_latencies: list[float] = []
    ready_latencies: list[float] = []
    metrics_latencies: list[float] = []
    for _ in range(100):
        health_latencies.append(
            timed_call(lambda: _assert_ok(client.get("/healthz").status_code))
        )
        ready_latencies.append(
            timed_call(lambda: _assert_ok(client.get("/readyz").status_code))
        )
        metrics_latencies.append(
            timed_call(lambda: _assert_ok(client.get("/metrics").status_code))
        )

    assert percentile(health_latencies, 0.99) <= 100.0
    assert percentile(ready_latencies, 0.99) <= 100.0
    assert percentile(metrics_latencies, 0.99) <= 100.0


def test_v2_chat_query_p95_latency_smoke_under_concurrency() -> None:
    app = create_app(application=ChatBIApplication(rate_limit_per_minute=0))
    client: Any = TestClient(app)

    def submit(index: int) -> float:
        request_id = f"req_latency_{index:08d}"

        def action() -> None:
            response = client.post(
                "/api/v2/chat/query",
                headers={"Authorization": "Bearer test-token"},
                json={
                    "request_id": request_id,
                    "session_id": "ses_latency0001",
                    "user_id": "u_latency",
                    "role": "business_user",
                    "locale": "en",
                    "question": "Show revenue trend.",
                },
            )
            _assert_ok(response.status_code)

        return timed_call(action)

    with ThreadPoolExecutor(max_workers=10) as executor:
        latencies = list(executor.map(submit, range(100)))

    assert percentile(latencies, 0.95) <= 500.0


def _assert_ok(status_code: int) -> None:
    assert status_code == 200
