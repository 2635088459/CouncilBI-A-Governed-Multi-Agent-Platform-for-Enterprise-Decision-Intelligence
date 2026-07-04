import pytest

from chatbi.load_testing import (
    LoadTestConfig,
    LoadTestSample,
    build_load_test_report,
    load_test_artifact_schema,
    run_mock_load_test,
)


def test_load_test_report_includes_latency_percentiles_error_rate_and_config() -> None:
    config = LoadTestConfig(name="mock_api_load", request_count=5, concurrency=1)
    report = build_load_test_report(
        config=config,
        samples=(
            LoadTestSample(latency_ms=10.0, succeeded=True),
            LoadTestSample(latency_ms=20.0, succeeded=True),
            LoadTestSample(latency_ms=30.0, succeeded=False),
            LoadTestSample(latency_ms=40.0, succeeded=True),
            LoadTestSample(latency_ms=50.0, succeeded=True),
        ),
    )

    artifact = load_test_artifact_schema(report)

    assert artifact["config"] == {
        "name": "mock_api_load",
        "request_count": 5,
        "concurrency": 1,
        "provider_mode": "mock",
    }
    assert artifact["total_requests"] == 5
    assert artifact["failed_requests"] == 1
    assert artifact["error_rate"] == 0.2
    assert artifact["latency_ms"] == {
        "p50": 30.0,
        "p95": 50.0,
        "p99": 50.0,
    }


def test_mock_load_test_runs_without_real_provider_cost_by_default() -> None:
    report = run_mock_load_test(
        LoadTestConfig(name="mock_llm_load", request_count=3, concurrency=1)
    )

    assert report.config.provider_mode == "mock"
    assert report.total_requests == 3
    assert report.failed_requests == 0
    assert report.error_rate == 0.0
    assert report.p99_latency_ms >= report.p95_latency_ms >= report.p50_latency_ms


def test_load_test_report_counts_action_failures() -> None:
    def flaky_action(index: int) -> None:
        if index == 1:
            raise RuntimeError("simulated failure")

    report = run_mock_load_test(
        LoadTestConfig(name="mock_api_with_failure", request_count=3, concurrency=1),
        action=flaky_action,
    )

    assert report.total_requests == 3
    assert report.failed_requests == 1
    assert report.error_rate == 0.3333


def test_load_test_rejects_invalid_config_and_empty_samples() -> None:
    with pytest.raises(ValueError, match="request_count"):
        LoadTestConfig(name="bad", request_count=0, concurrency=1)
    with pytest.raises(ValueError, match="concurrency"):
        LoadTestConfig(name="bad", request_count=1, concurrency=0)
    with pytest.raises(ValueError, match="samples must not be empty"):
        build_load_test_report(
            config=LoadTestConfig(name="bad", request_count=1, concurrency=1),
            samples=(),
        )
