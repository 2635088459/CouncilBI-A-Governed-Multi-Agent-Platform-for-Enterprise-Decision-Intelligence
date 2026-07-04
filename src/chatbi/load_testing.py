"""Local load-test report helpers for FV-06."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Callable, Mapping


@dataclass(frozen=True, slots=True)
class LoadTestConfig:
    name: str
    request_count: int
    concurrency: int
    provider_mode: str = "mock"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name is required")
        if self.request_count < 1:
            raise ValueError("request_count must be greater than or equal to 1")
        if self.concurrency < 1:
            raise ValueError("concurrency must be greater than or equal to 1")
        if not self.provider_mode.strip():
            raise ValueError("provider_mode is required")


@dataclass(frozen=True, slots=True)
class LoadTestSample:
    latency_ms: float
    succeeded: bool

    def __post_init__(self) -> None:
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be greater than or equal to 0")


@dataclass(frozen=True, slots=True)
class LoadTestReport:
    config: LoadTestConfig
    total_requests: int
    succeeded_requests: int
    failed_requests: int
    error_rate: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float

    def to_artifact(self) -> dict[str, object]:
        return {
            "config": {
                "name": self.config.name,
                "request_count": self.config.request_count,
                "concurrency": self.config.concurrency,
                "provider_mode": self.config.provider_mode,
            },
            "total_requests": self.total_requests,
            "succeeded_requests": self.succeeded_requests,
            "failed_requests": self.failed_requests,
            "error_rate": self.error_rate,
            "latency_ms": {
                "p50": self.p50_latency_ms,
                "p95": self.p95_latency_ms,
                "p99": self.p99_latency_ms,
            },
        }


LoadAction = Callable[[int], object]


def run_mock_load_test(
    config: LoadTestConfig,
    action: LoadAction | None = None,
) -> LoadTestReport:
    """Run a deterministic local load test without real provider calls."""

    active_action = action or _default_mock_action
    samples: list[LoadTestSample] = []
    for index in range(config.request_count):
        started_at = perf_counter()
        succeeded = True
        try:
            active_action(index)
        except Exception:
            succeeded = False
        samples.append(
            LoadTestSample(
                latency_ms=(perf_counter() - started_at) * 1000,
                succeeded=succeeded,
            )
        )
    return build_load_test_report(config=config, samples=tuple(samples))


def build_load_test_report(
    *,
    config: LoadTestConfig,
    samples: tuple[LoadTestSample, ...],
) -> LoadTestReport:
    if not samples:
        raise ValueError("samples must not be empty")
    total_requests = len(samples)
    succeeded_requests = sum(1 for sample in samples if sample.succeeded)
    failed_requests = total_requests - succeeded_requests
    sorted_latencies = tuple(sorted(sample.latency_ms for sample in samples))
    return LoadTestReport(
        config=config,
        total_requests=total_requests,
        succeeded_requests=succeeded_requests,
        failed_requests=failed_requests,
        error_rate=round(failed_requests / total_requests, 4),
        p50_latency_ms=_percentile(sorted_latencies, 0.50),
        p95_latency_ms=_percentile(sorted_latencies, 0.95),
        p99_latency_ms=_percentile(sorted_latencies, 0.99),
    )


def load_test_artifact_schema(report: LoadTestReport) -> Mapping[str, object]:
    return report.to_artifact()


def _default_mock_action(index: int) -> None:
    _ = index


def _percentile(sorted_values: tuple[float, ...], percentile: float) -> float:
    if not sorted_values:
        raise ValueError("sorted_values must not be empty")
    if not 0.0 <= percentile <= 1.0:
        raise ValueError("percentile must be between 0.0 and 1.0")
    index = min(
        len(sorted_values) - 1,
        int(round((len(sorted_values) - 1) * percentile)),
    )
    return sorted_values[index]
